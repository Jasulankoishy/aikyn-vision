"""Candidate queue integration checks; symbolic timestamps, no video/model/GPU."""
import json
from types import SimpleNamespace

import pytest

import native_engine as native


class Characters:
    eos_token_id = 0

    def __call__(self, texts, add_special_tokens=False):
        return {'input_ids': [list(map(ord, text)) for text in texts]}


@pytest.fixture
def mock_engine(monkeypatch, tmp_path):
    clock = {'seconds': 0.0}
    monkeypatch.setattr(native.time, 'monotonic', lambda: clock['seconds'])
    monkeypatch.setattr(native, 'ROOT', tmp_path)
    monkeypatch.setattr(native, 'inspect', lambda path: 20.0)
    engine = native.NativeQuickEngine.__new__(native.NativeQuickEngine)
    engine.torch = SimpleNamespace(cuda=SimpleNamespace(
        reset_peak_memory_stats=lambda: None, max_memory_allocated=lambda: 0))
    engine.processor = SimpleNamespace(tokenizer=Characters())
    engine.cancelled_error = InterruptedError
    frames = [{'time_sec': i / 4} for i in range(81)]
    engine.sample_video = lambda *args: frames
    engine.infer_checks = lambda *args, **kwargs: (
        dict.fromkeys(native.FIELDS, 'not_seen'), {'mock': True})
    candidates = [dict(kind='cash_mixed', start_sec=0.0, end_sec=20.0,
                       supporting_windows=[i]) for i in range(9)]
    monkeypatch.setattr(native, 'risk_candidates', lambda outcomes: candidates)
    monkeypatch.setattr(native, 'evidence', lambda frames, times: [
        {'timestamp_sec': timestamp} for timestamp in times])
    return engine, clock, tmp_path / 'symbolic.mov'


def test_ninth_candidate_is_reviewed_and_its_finding_is_preserved(mock_engine):
    engine, clock, path = mock_engine
    locates = []

    def infer(frames, prompt, grammar, deadline, **kwargs):
        clock['seconds'] += 1
        if 'time_sec' in grammar.choices[0]:
            locates.append(1)
            answer = {'time_sec': 10.0 if len(locates) == 9 else None}
        else:
            answer = next(value for value in grammar.choices
                          if value['status'] == 'observed')
        return answer, {'response': answer}

    engine.infer = infer
    result = engine.analyze(path, budget_sec=60)

    assert len(locates) == 9
    assert len(result['analysis']['refinements']) == 9
    assert result['analysis']['candidate_review'] == {
        'status': 'complete', 'total': 9, 'done': 9, 'remaining': 0}
    assert result['analysis']['complete'] is True
    assert result['verdict'] == 'violation'
    assert len(result['violations']) == 1
    assert result['analysis']['refinements'][-1]['supporting_windows'] == [8]
    assert result['analysis']['refinements'][-1]['status'] == 'observed'


@pytest.mark.parametrize('timeout_mode', ['inside_inference', 'after_inference'])
def test_timeout_keeps_queue_counts_and_never_returns_clean(mock_engine, timeout_mode):
    engine, clock, path = mock_engine
    calls = []

    def infer(*args, **kwargs):
        calls.append(1)
        if len(calls) == 3:
            if timeout_mode == 'inside_inference':
                raise TimeoutError('Model generation deadline')
            clock['seconds'] = 59.0
        return {'time_sec': None}, {'response': {'time_sec': None}}

    engine.infer = infer
    with pytest.raises(TimeoutError, match='completed 2/9 candidates; 7 remaining'):
        engine.analyze(path, budget_sec=60)

    progress = next(row for row in engine._last_diagnostics
                    if row['stage'] == 'candidate_queue')
    assert progress['status'] == 'incomplete'
    assert progress['done'] == 2 and progress['remaining'] == 7
    assert progress['reason'] == 'deadline_exceeded'
    assert progress['current_candidate']['kind'] == 'cash_mixed'
    serialized = json.dumps(engine._last_diagnostics)
    assert 'image_base64' not in serialized and 'pixel' not in serialized


def test_expired_budget_before_first_candidate_is_explicit(mock_engine):
    engine, clock, path = mock_engine

    def checks(*args, **kwargs):
        clock['seconds'] = 59.0
        return dict.fromkeys(native.FIELDS, 'not_seen'), {'mock': True}

    engine.infer_checks = checks
    engine.infer = lambda *args, **kwargs: pytest.fail('Expired queue called model')
    with pytest.raises(TimeoutError, match='completed 0/9 candidates; 9 remaining'):
        engine.analyze(path, budget_sec=60)
    progress = engine._last_diagnostics[-1]
    assert progress['stage'] == 'candidate_queue' and progress['status'] == 'incomplete'


def test_invalid_candidate_answer_keeps_queue_incomplete(mock_engine):
    engine, clock, path = mock_engine
    engine.infer = lambda *args, **kwargs: ({'time_sec': 999.0}, {'mock': True})
    with pytest.raises(native.IncompleteAnalysis, match='Invalid temporal proposal'):
        engine.analyze(path, budget_sec=60)
    progress = next(row for row in engine._last_diagnostics
                    if row['stage'] == 'candidate_queue')
    assert progress['done'] == 0 and progress['remaining'] == 9
    assert progress['status'] == 'incomplete'
    assert progress['reason'] == 'candidate_processing_error'
