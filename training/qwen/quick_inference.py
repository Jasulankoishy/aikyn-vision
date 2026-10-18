"""Persistent local Qwen inference for the website. No finetuning or label lookup."""
import argparse
import base64
import contextlib
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import time

# The native engine imports this module for the shared exception/base class.
# Keep script execution and normal import bound to the same class identities.
if __name__ == '__main__':
    sys.modules.setdefault('quick_inference', sys.modules[__name__])

from quick_core import PresenceGrammar, parse_presence, prompt, sequence_view, merge_observations
from sequence_core import summarize
from temporal_core import windows

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
VERSION = 'quick-base-qwen-presence-v1'


class IncompleteAnalysis(RuntimeError):
    pass


def inspect(path):
    import av
    if not path.is_file() or path.suffix.lower() != '.mov' or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('Expected a local MOV file up to 64 MiB')
    with av.open(str(path), options={'protocol_whitelist': 'file'}) as container:
        if 'mov' not in container.format.name or len(container.streams.video) != 1:
            raise ValueError('Expected a single MOV video stream')
        stream = container.streams.video[0]
        duration = float(stream.duration * stream.time_base) if stream.duration else float((container.duration or 0)/av.time_base)
        fps = float(stream.average_rate or 0)
        if not math.isfinite(duration) or not 0 < duration <= 180 or not 0 < fps <= 120:
            raise ValueError('Video duration/FPS outside supported limits')
        if not 0 < stream.width <= 4096 or not 0 < stream.height <= 2160:
            raise ValueError('Video resolution outside supported limits')
        return duration


def evidence(frames, timestamps):
    """Return actual sampled JPEGs; bytes never go to any remote API."""
    result = []
    used = set()
    source = {f['time_sec']: f for f in frames}
    times = sorted(set(timestamps))
    selected_times = sorted({times[0], times[len(times)//2], times[-1]}) if times else []
    for timestamp in selected_times:
        if timestamp not in source:
            raise IncompleteAnalysis('Evidence timestamp is not a sampled source frame')
        frame = source[timestamp]
        if frame['path'] in used:
            continue
        used.add(frame['path'])
        # The existing website declares evidence data as image/jpeg. The
        # original-resolution experimental decoder stores PNGs, so normalize
        # those bytes here without changing the source frame or timestamp.
        from PIL import Image
        with Image.open(frame['path']) as source_image:
            if source_image.format == 'JPEG':
                payload = Path(frame['path']).read_bytes()
            else:
                buffer = io.BytesIO()
                source_image.convert('RGB').save(buffer, format='JPEG', quality=92)
                payload = buffer.getvalue()
        result.append({'timestamp_sec': frame['time_sec'],
                       'image_base64': base64.b64encode(payload).decode('ascii')})
    return result


class QuickEngine:
    def __init__(self, model_dir=None, precision='nf4'):
        print('Loading local inference dependencies...', file=sys.stderr, flush=True)
        from local_model import load, torch
        from transformers import StoppingCriteria, StoppingCriteriaList
        from temporal_scan import gpu_lock, sample_video, Cancelled
        self.torch, self.sample_video = torch, sample_video
        self.cancelled_error = Cancelled
        self._lock = gpu_lock()
        self._lock.__enter__()
        try:
            print('Loading offline Qwen weights...', file=sys.stderr, flush=True)
            self.model, self.processor = load(max_pixels=147456, model_dir=model_dir, precision=precision)
        except BaseException:
            self._lock.__exit__(*sys.exc_info())
            raise
        self.model.eval()
        print('Local Qwen ready.', file=sys.stderr, flush=True)
        self.model.generation_config.temperature = None
        self.model.generation_config.top_p = None
        self.model.generation_config.top_k = None
        self.grammar = PresenceGrammar(self.processor.tokenizer)

        class Deadline(StoppingCriteria):
            def __init__(self, end): self.end = end
            def __call__(self, input_ids, scores, **kwargs): return time.monotonic() >= self.end

        self.stopping = lambda end: StoppingCriteriaList([Deadline(end)])

    def close(self):
        self._lock.__exit__(None, None, None)

    def analyze(self, path, budget_sec=220.):
        from local_model import encode
        from review_findings import build_findings
        began = time.monotonic()
        if not isinstance(budget_sec, (float, int)) or not math.isfinite(budget_sec) or not 0 < budget_sec <= 240:
            raise ValueError('Invalid processing budget')
        deadline = began + budget_sec
        path = Path(path).resolve()
        duration = inspect(path)
        plan = windows(duration, size=6., stride=4.)
        raw_actions, outcomes, responses = [], [], []
        cache = ROOT / 'data/quick_runtime'
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='request-', dir=cache) as temp:
            temp = Path(temp)
            class ExpiringRequest:
                def exists(self): return time.monotonic() >= deadline-3
            try:
                frames = self.sample_video(path, temp/'frames', 2., ExpiringRequest())
            except self.cancelled_error as error:
                raise TimeoutError('Deadline reached while decoding video') from error
            if time.monotonic() >= deadline-3:
                raise TimeoutError('Deadline reached while decoding video')
            if not frames or frames[-1]['time_sec'] < duration-1:
                raise IncompleteAnalysis('The decoded video ends before its declared duration')
            for window in plan:
                if time.monotonic() >= deadline-3:
                    raise TimeoutError('Analysis deadline reached before the full video was processed')
                selected = [f for f in frames if window['start_sec'] <= f['time_sec'] <= window['end_sec'] and f['time_sec'] < duration]
                if not selected:
                    raise IncompleteAnalysis('No usable frames in a video window')
                if selected[0]['time_sec']-window['start_sec'] > .6 or window['end_sec']-selected[-1]['time_sec'] > .6:
                    raise IncompleteAnalysis('Sampled frames do not cover a window')
                if any(b['time_sec']-a['time_sec'] > .75 for a,b in zip(selected, selected[1:])):
                    raise IncompleteAnalysis('Gap in sampled video timestamps')
                prior = merge_observations(raw_actions)
                for attempt in range(2):
                    prefix = '{"actions":'
                    question = prompt(selected, prior)
                    if attempt:
                        question += ' The previous reply was invalid. actions must contain only allowed NAME STRINGS, no objects or numbers. Close the JSON object.'
                    if time.monotonic() >= deadline-3:
                        raise TimeoutError('Deadline reached before image encoding')
                    inputs = encode(self.processor, {'frames': selected, 'number_frames': True}, prompt=question, assistant_prefix=prefix)
                    if time.monotonic() >= deadline-3:
                        del inputs
                        raise TimeoutError('Deadline reached during image encoding')
                    input_length = inputs['input_ids'].shape[1]
                    def allowed_tokens(batch_id, token_ids):
                        return self.grammar.allowed(token_ids[input_length:].tolist())
                    with self.torch.inference_mode():
                        output = self.model.generate(**inputs, max_new_tokens=self.grammar.max_tokens, do_sample=False, use_cache=True,
                                                     prefix_allowed_tokens_fn=allowed_tokens,
                                                     stopping_criteria=self.stopping(deadline-2))
                    text = prefix + self.processor.decode(output[0, inputs['input_ids'].shape[1]:], skip_special_tokens=True)
                    del inputs, output
                    if time.monotonic() >= deadline-2:
                        raise TimeoutError('Analysis deadline reached')
                    responses.append({'window': window['index'], 'attempt': attempt, 'text': text})
                    try:
                        uncertain, actions = parse_presence(text, selected, window)
                        break
                    except (ValueError, TypeError, KeyError) as error:
                        if attempt:
                            failure = IncompleteAnalysis(f'Model returned invalid actions in window {window["index"]}: {error}')
                            failure.responses = responses
                            raise failure from error
                raw_actions.extend(actions)
                outcomes.append({**window, 'uncertain': uncertain, 'action_count': len(actions)})
                print(json.dumps({'window_done': len(outcomes), 'windows_total': len(plan),
                                  'elapsed_sec': round(time.monotonic()-began, 2)}), file=sys.stderr, flush=True)
            actions = merge_observations(raw_actions)
            summary = summarize(sequence_view(actions))
            findings = build_findings(actions, summary, duration)
            violations = []
            for event in findings['events']:
                frames_for_event = evidence(frames, event['evidence_timestamps'])
                if not frames_for_event:
                    raise IncompleteAnalysis('A finding has no source frames')
                violations.append({**{k: v for k,v in event.items() if k != 'evidence_timestamps'},
                                   'evidence_frames': frames_for_event})
            return {'verdict': 'violation' if violations else 'no_violation', 'violations': violations,
                    'analysis': {'model': 'Qwen3-VL-2B-Instruct', 'model_revision': '89644892e4d85e24eaac8bacfd4f463576704203',
                                 'implementation': VERSION, 'experimental': True, 'new_training': False,
                                 'network_disabled': True, 'findings_status': 'requires_review',
                                 'complete': True, 'timeline_covered': True, 'duration_sec': duration,
                                 'elapsed_sec': round(time.monotonic()-began, 3),
                                 'sample_fps': 2., 'window_seconds': 6., 'stride_seconds': 4.,
                                 'max_pixels_per_frame': 147456,
                                 'localization': 'approximate_window',
                                 'output_format': 'constrained_action_labels', 'max_actions_per_window': 3,
                                 'windows_done': len(outcomes), 'windows_total': len(plan),
                                 'uncertain_windows': sum(w['uncertain'] for w in outcomes),
                                 'coverage_gaps': [], 'windows': outcomes,
                                 'actions': actions, 'review_questions': findings['review_questions'],
                                 'limitations': findings['limitations'] + ['Время приблизительное: модель отмечает действия внутри 6-секундного окна. Кадры показывают контекст окна, а не точную границу события.',
                                      'Выборка 2 кадра в секунду может пропустить короткое движение.',
                                      'Для каждого окна модель выбирает до трёх действий; корректный формат ответа не подтверждает правильность распознавания.',
                                      'Это автоматические предположения; точность на новых записях не гарантирована.'],
                                 'peak_vram_gib': round(self.torch.cuda.max_memory_allocated()/2**30, 3)},
                    '_diagnostics': {'responses': responses}}


def protocol_reply(value):
    print(json.dumps(value, ensure_ascii=False, separators=(',', ':')), flush=True)


def worker():
    from runtime_selection import create_engine
    with contextlib.redirect_stdout(sys.stderr):
        engine = create_engine()
    protocol_reply({'state': 'ready', 'model': engine.model_name, 'new_training': False})
    try:
        for line in sys.stdin:
            request = {}
            try:
                request = json.loads(line)
                with contextlib.redirect_stdout(sys.stderr):
                    result = engine.analyze(request['path'], request.get('budget_sec', 220.))
                result.pop('_diagnostics', None)
                protocol_reply({'id': request.get('id'), 'ok': True, 'result': result})
            except Exception as error:
                code = 'analysis_timeout' if isinstance(error, TimeoutError) else 'incomplete_analysis' if isinstance(error, IncompleteAnalysis) else 'analysis_failed'
                print(f'{type(error).__name__}: {error}', file=sys.stderr, flush=True)
                protocol_reply({'id': request.get('id'), 'ok': False, 'error': {'code': code, 'message': str(error)}})
    finally:
        engine.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--videos', type=Path, nargs='+')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--pipeline', choices=['native', 'legacy'], default='native')
    args = parser.parse_args()
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    if args.worker:
        return worker()
    if not args.videos or not args.output:
        parser.error('Use --worker or --videos ... --output NEW_DIRECTORY')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'.gitignore').write_text('*\n', encoding='utf-8')
    from native_engine import NativeQuickEngine
    with contextlib.redirect_stdout(sys.stderr):
        engine = NativeQuickEngine() if args.pipeline == 'native' else QuickEngine()
    report = []
    try:
        for index, path in enumerate(args.videos, 1):
            started = time.monotonic()
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    result = engine.analyze(path)
                diagnostics = result.pop('_diagnostics')
                (args.output/f'{index:02}-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                (args.output/f'{index:02}-diagnostics.json').write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding='utf-8')
                # No bank image bytes or identities are printed to the tool output.
                item = {'index': index, 'filename': path.name, 'ok': True, 'elapsed_sec': result['analysis']['elapsed_sec'],
                        'events': len(result['violations']), 'questions': len(result['analysis']['review_questions']),
                        'actions': len(result['analysis']['actions']), 'windows': result['analysis']['windows_done']}
            except Exception as error:
                item = {'index': index, 'filename': path.name, 'ok': False, 'elapsed_sec': round(time.monotonic()-started,3),
                        'error': f'{type(error).__name__}: {error}'}
                failed_trace=getattr(error,'responses',getattr(engine,'_last_diagnostics',None))
                if failed_trace is not None:
                    (args.output/f'{index:02}-diagnostics.json').write_text(json.dumps(failed_trace, ensure_ascii=False, indent=2), encoding='utf-8')
            report.append(item)
            (args.output/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            protocol_reply(item)
    finally:
        engine.close()


if __name__ == '__main__':
    main()
