"""Native video, whole-operation context, and independent dense temporal review."""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sys
import tempfile
import time

from native_video import encode_video, select_frames
from model_snapshot import snapshot_metadata
from temporal_context import earlier_frame_pairs, history_prompt
from native_sampling import sampling_metadata, validate_coverage
from native_core import (FIELDS, RISK_KEYS, ROLE_GUIDANCE, ChecklistGrammar, ChoiceGrammar, parse_checklist,
                         checklist_prompt, bounded_memory, risk_candidates, action_observations,
                         localization_choices, validate_localization, source_bins)
from quick_inference import QuickEngine, IncompleteAnalysis, inspect, evidence, ROOT
from quick_core import merge_observations, sequence_view
from sequence_core import summarize
from temporal_core import windows
from review_findings import build_findings, PUBLIC_CASH_RULE
from door_observation import infer_door_observation

VERSION='native-sequence-refine-v15-fourteen-categories'
RISK_TITLES={
    'cash_mixed':('c02','Возможное объединение пачек наличных'),
    'old_cash_at_client_change':('c01','Возможное оставление наличных при смене клиента'),
    'cash_unattended':('c06','Возможное оставление наличных при уходе кассира'),
    'safe_open_when_left':('c08','Возможно открытый сейф при уходе кассира'),
    'screen_unlocked_when_left':('c11','Возможно незаблокированный экран при уходе кассира'),
    'room_door_left_open':('c12','Возможно открытая дверь кассового помещения'),
    'cash_receipt_without_visible_count':('c03','Возможный приём наличных без видимого пересчёта'),
    'cash_receipt_without_visible_identity_check':('c04','Возможный приём без видимой идентификации клиента'),
    'cash_counted_after_client_departure':('c05','Возможный пересчёт принимаемых денег после ухода клиента'),
    'package_left_unattended':('c07','Возможно оставленный без присмотра пакет'),
    'safe_key_left_in_lock':('c09','Возможно оставленный в замке сейфа ключ'),
    'documents_or_seals_left_unattended':('c10','Возможно оставленные документы или печати при уходе кассира'),
    'personal_items_in_cash_area':('c13','Возможные личные вещи в рабочей кассовой зоне'),
    'rejected_banknotes_recombined':('c14','Возможное объединение отделённых аппаратом купюр без видимой проверки'),
}

# A tiny crop cannot establish a missing earlier step or the order of a whole
# operation. These categories receive the full proposed operation window.
OPERATION_CONTEXT_KEYS = frozenset({
    'cash_receipt_without_visible_count', 'cash_receipt_without_visible_identity_check',
    'cash_counted_after_client_departure', 'rejected_banknotes_recombined',
})
DETAIL_OBJECT_KEYS = frozenset({'safe_key_left_in_lock', 'personal_items_in_cash_area'})
CATEGORY_NOTES = {
    'cash_receipt_without_visible_count': 'Ненаблюдаемый пересчёт не равнозначен его отсутствию; скрытые этапы операции остаются неизвестными.',
    'cash_receipt_without_visible_identity_check': 'Физическое удостоверение может быть заменено цифровой проверкой; отсутствие документа в кадре не доказывает нарушение.',
    'cash_counted_after_client_departure': 'Нужно отличать первичный приём от повторного внутреннего пересчёта и установить фактический уход клиента.',
    'package_left_unattended': 'Содержимое непрозрачного пакета неизвестно; пакет автоматически не считается наличными.',
    'safe_key_left_in_lock': 'Нужны различимый ключ, замок сейфа и контекст доступа; ручка или выступ не считаются ключом.',
    'documents_or_seals_left_unattended': 'Содержание бумаг и статус печатей неизвестны; их наличие на столе само по себе не устанавливает юридическое нарушение.',
    'personal_items_in_cash_area': 'Личное назначение предмета и границы кассового узла требуют установления; рабочее оборудование не считается личной вещью.',
    'rejected_banknotes_recombined': 'Отделение аппаратом не доказывает подделку; причина отделения и выполненные проверки могут быть неизвестны.',
}


@contextmanager
def _review_candidate(progress, index, candidate, deadline):
    """Keep queue progress even when inference raises or a candidate is rejected."""
    progress['current_candidate'] = {
        key: candidate[key] for key in ('kind', 'start_sec', 'end_sec')
    }
    progress['status'] = 'running'
    try:
        if time.monotonic() >= deadline - 3:
            raise TimeoutError('Temporal review deadline before candidate')
        yield
        if time.monotonic() >= deadline - 2:
            raise TimeoutError('Temporal review deadline during candidate')
    except TimeoutError as error:
        progress['status'] = 'incomplete'
        progress['reason'] = 'deadline_exceeded'
        raise TimeoutError(
            f"Temporal review deadline: completed {progress['done']}/{progress['total']} "
            f"candidates; {progress['remaining']} remaining (including the current candidate)"
        ) from error
    except Exception:
        progress['status'] = 'incomplete'
        progress['reason'] = 'candidate_processing_error'
        raise
    else:
        progress['done'] = index + 1
        progress['remaining'] = progress['total'] - progress['done']
        progress.pop('current_candidate', None)


class NativeQuickEngine(QuickEngine):
    # Default attributes also support orchestration-only tests that skip loading.
    model_name = 'Qwen3-VL-2B-Instruct'
    model_revision = '89644892e4d85e24eaac8bacfd4f463576704203'
    pixel_cap = None
    temporal_context = False

    def __init__(self, model_dir=None, pixel_cap=None, temporal_context=False):
        if pixel_cap is not None and (type(pixel_cap) is not int or pixel_cap <= 0):
            raise ValueError('pixel_cap must be a positive integer or None')
        if type(temporal_context) is not bool:
            raise ValueError('temporal_context must be a boolean')
        metadata = snapshot_metadata(model_dir)
        super().__init__(model_dir=model_dir)
        if self.model.config.text_config.hidden_size != metadata['hidden_size']:
            self.close()
            raise ValueError('Loaded model identity differs from its verified snapshot')
        self.model_name = metadata['model']
        self.model_revision = metadata['revision']
        self.model_snapshot_validation = metadata['validation']
        self.pixel_cap = pixel_cap
        self.temporal_context = temporal_context
        # One keyed answer retains the name next to each classification while
        # avoiding three costly re-encodings of the same video on a 6 GiB GPU.
        self.check_groups=(tuple(FIELDS),)
        self.checklist_grammars=[ChecklistGrammar(self.processor.tokenizer, group) for group in self.check_groups]

    def infer_checks(self, frames, start, end, context, deadline, *, pixels=6_291_456):
        checks={}; traces=[]
        for group,grammar in zip(self.check_groups,self.checklist_grammars):
            value,trace=self.infer(frames,checklist_prompt(start,end,context,fields=group),grammar,deadline,pixels=pixels)
            checks.update(parse_checklist(json.dumps(value),group))
            traces.append(trace)
        return checks,{'groups':traces}

    def infer_door_sequence(self, frames, start, end, deadline):
        return infer_door_observation(self, frames, start, end, deadline)

    def infer(self, frames, question, grammar, deadline, *, pixels=6_291_456):
        if time.monotonic() >= deadline-3: raise TimeoutError('Native video deadline before encoding')
        effective_pixels = pixels if self.pixel_cap is None else min(pixels, self.pixel_cap)
        inputs=encode_video(self.processor,frames,question,max_total_pixels=effective_pixels)
        n=inputs['input_ids'].shape[1]
        if time.monotonic() >= deadline-3:
            del inputs
            raise TimeoutError('Native video deadline during encoding')
        def allowed(batch_id, token_ids): return grammar.allowed(token_ids[n:].tolist())
        with self.torch.inference_mode():
            output=self.model.generate(**inputs,max_new_tokens=grammar.max_tokens,do_sample=False,use_cache=True,
                                       prefix_allowed_tokens_fn=allowed,stopping_criteria=self.stopping(deadline-2))
        text=self.processor.decode(output[0,n:],skip_special_tokens=True)
        grid=inputs['video_grid_thw'].tolist()
        del inputs,output
        if time.monotonic() >= deadline-2: raise TimeoutError('Native video analysis deadline')
        try: value=json.loads(text)
        except ValueError as error: raise IncompleteAnalysis('Model did not complete the native video answer') from error
        return value, {'frames':len(frames),'video_grid_thw':grid,'input_tokens':n,'response':value,
                       'requested_max_total_pixels':pixels,'effective_max_total_pixels':effective_pixels}

    def analyze(self,path,budget_sec=220.):
        if type(budget_sec) not in (int,float) or not math.isfinite(budget_sec) or not 0<budget_sec<=240:
            raise ValueError('Invalid processing budget')
        began=time.monotonic(); deadline=began+budget_sec
        path=Path(path).resolve(); duration=inspect(path)
        self.torch.cuda.reset_peak_memory_stats()
        plan=windows(duration,size=20.,stride=16.)
        cache=ROOT/'data/quick_runtime';cache.mkdir(parents=True,exist_ok=True)
        diagnostics=[]; outcomes=[]; refinements=[]
        self._last_diagnostics=diagnostics
        with tempfile.TemporaryDirectory(prefix='native-',dir=cache) as temp:
            class Deadline:
                def exists(self):return time.monotonic()>=deadline-3
            try: frames=self.sample_video(path,Path(temp)/'frames',4.,Deadline())
            except self.cancelled_error as error:raise TimeoutError('Video decoding deadline') from error
            try: validate_coverage(frames,0,duration,endpoint_tolerance=.5,max_gap_sec=.5)
            except ValueError as error: raise IncompleteAnalysis(str(error)) from error
            source_sampling=sampling_metadata(frames,4.)
            plan=windows(frames[-1]['time_sec'],size=20.,stride=16.)
            overview_frames=select_frames(frames,0,duration,fps=1.,max_frames=16 if self.temporal_context else 96)
            overview_sampling=sampling_metadata(overview_frames,1.)
            overview,trace=self.infer_checks(overview_frames,0,duration,[],deadline,pixels=4_194_304)
            overview=parse_checklist(json.dumps(overview));diagnostics.append({'stage':'overview',**trace})
            print(json.dumps({'stage':'overview','elapsed_sec':round(time.monotonic()-began,2)}),file=sys.stderr,flush=True)
            for w in plan:
                selected=select_frames(frames,w['start_sec'],w['end_sec'],fps=2.,max_frames=48)
                try: validate_coverage(selected,w['start_sec'],w['end_sec'],endpoint_tolerance=.5,max_gap_sec=.8)
                except ValueError as error: raise IncompleteAnalysis(str(error)) from error
                context=bounded_memory(outcomes)
                checks,trace=self.infer_checks(selected,w['start_sec'],w['end_sec'],context,deadline)
                checks=parse_checklist(json.dumps(checks))
                outcomes.append({**w,'checks':checks,'uncertain':any(v=='unclear' for v in checks.values()),
                                 'sampled_timestamps':[f['time_sec'] for f in selected],'sampling':sampling_metadata(selected,2.)})
                diagnostics.append({'stage':'coarse','window':w['index'],'memory':context,**trace})
                print(json.dumps({'stage':'coarse','window_done':len(outcomes),'windows_total':len(plan),
                                  'elapsed_sec':round(time.monotonic()-began,2)}),file=sys.stderr,flush=True)
            actions=merge_observations(action_observations(outcomes,frames))
            sequence=summarize(sequence_view(actions))
            preliminary=build_findings(actions,sequence,duration)
            questions=list(preliminary['review_questions'])
            candidates=risk_candidates(outcomes)
            # A low-resolution general checklist must not veto the dedicated
            # high-detail door observation. Every covered window gets its own
            # visual sequence decision; A/B/D still create no event.
            for w in outcomes:
                if not any(c['kind']=='room_door_left_open' and w['index'] in c['supporting_windows']
                           for c in candidates):
                    candidates.append({'kind':'room_door_left_open','start_sec':w['start_sec'],
                                       'end_sec':w['end_sec'],'supporting_windows':[w['index']],
                                       'origin':'independent_detailed_door_review'})
            candidates.sort(key=lambda c:(c['start_sec'],RISK_KEYS.index(c['kind'])))
            # Whole-video observations may find a transition missed by window
            # boundaries. They are proposals only and still need dense review.
            for kind in RISK_KEYS:
                if overview[kind]=='seen' and not any(c['kind']==kind for c in candidates):
                    candidates.append({'kind':kind,'start_sec':0.,'end_sec':duration,'supporting_windows':[], 'origin':'overview'})
            queue_progress={'stage':'candidate_queue','status':'pending','total':len(candidates),
                            'done':0,'remaining':len(candidates)}
            diagnostics.append(queue_progress)
            events=[]
            for index,candidate in enumerate(candidates):
                with _review_candidate(queue_progress,index,candidate,deadline):
                    kind=candidate['kind']; a,b=candidate['start_sec'],candidate['end_sec']
                    selected=select_frames(frames,a,b,fps=2.,max_frames=64)
                    if kind == 'room_door_left_open':
                        # Spread the same pixel budget over four source frames
                        # so the door panel/gap remains visible. Keep the full
                        # interval; the later dense pass still localizes it.
                        door_frames=select_frames(frames,a,b,fps=2.,max_frames=4)
                        door,trace=self.infer_door_sequence(door_frames,a,b,deadline)
                        if door.get('sequence') not in ('A','B','C','D'):
                            raise IncompleteAnalysis('Invalid door sequence classification')
                        diagnostics.append({'stage':'door_sequence','kind':kind,
                                            'sampling':sampling_metadata(door_frames,2.),
                                            'input_selection':'four_source_frames_full_interval',**trace})
                        if door['sequence'] != 'C':
                            status='unclear' if door['sequence']=='D' else 'not_observed'
                            refinements.append({**candidate,'status':status,
                                                'method':'visual_door_sequence','door_sequence':door['sequence']})
                            if status=='unclear':
                                questions.append({'type':RISK_TITLES[kind][1],
                                                  'timecode_sec':selected[len(selected)//2]['time_sec'],
                                                  'message':'Модель не смогла различить положение двери помещения в последовательности кадров.',
                                                  'status':'requires_review','reason':'door_sequence_unclear'})
                            continue
                    full_state_window=(kind == 'room_door_left_open' and b-a <= 20.) or kind in OPERATION_CONTEXT_KEYS
                    if full_state_window:
                        # The dense pass uses the whole candidate anyway, so a
                        # separate point search is redundant. This midpoint is
                        # only an input-window center, never an event timecode.
                        center=(a+b)/2
                    else:
                        # Null is valid: a coarse candidate must not force a hit.
                        point_frames=select_frames(selected,a,b,fps=1.,max_frames=80)
                        choices=[{'time_sec':None}]+[{'time_sec':f['time_sec']} for f in point_frames]
                        grammar=ChoiceGrammar(self.processor.tokenizer,choices)
                        question=(f'Watch the video interval {a:.2f} to {b:.2f} seconds. Locate this specific visible event: '+FIELDS[kind]+'. '
                                  + ROLE_GUIDANCE +
                                  'The earlier detector is unverified and may be wrong. Use only visible evidence. '
                                  'Return {"time_sec":null} if this event cannot be located. Otherwise choose the source time nearest its start. '
                                  'Return exactly one JSON object. Allowed source times: '+json.dumps([x['time_sec'] for x in choices])+'.')
                        point,trace=self.infer(selected,question,grammar,deadline)
                        diagnostics.append({'stage':'locate','kind':kind,'sampling':sampling_metadata(selected,2.),**trace})
                        if point not in choices:raise IncompleteAnalysis('Invalid temporal proposal')
                        if point['time_sec'] is None:
                            refinements.append({**candidate,'status':'not_localized'})
                            questions.append({'type':RISK_TITLES[kind][1],'timecode_sec':selected[len(selected)//2]['time_sec'],
                                              'message':'Первый проход отметил возможный признак, но повторный просмотр не смог установить его момент. Кандидат не включён в нарушения.',
                                              'status':'requires_review','reason':'native_candidate_not_localized'})
                            continue
                        center=point['time_sec']
                    lower=max(0.,center-3.); upper=min(duration,center+4.)
                    fine_limit=32
                    if kind in OPERATION_CONTEXT_KEYS:
                        lower,upper=a,b
                        fine_limit=96
                    elif kind in DETAIL_OBJECT_KEYS:
                        fine_limit=8
                    if kind == 'room_door_left_open':
                        # A persistent state needs the passage and later closure
                        # context. A short crop around a late proposal can cut
                        # away its beginning or conceal a normal door closure.
                        # Keep the complete coarse window, capped at 20 seconds
                        # for an overview-only proposal, without using labels.
                        span=min(20.,b-a)
                        lower=max(a,min(center-span/2,b-span)); upper=lower+span
                        fine_limit=4
                    fine=select_frames(frames,lower,upper,fps=4.,max_frames=fine_limit)
                    grammar=ChoiceGrammar(self.processor.tokenizer,localization_choices(fine))
                    time_map=[{'displayed_sec':round((pair['start_sec']+pair['end_sec'])/2,1),**pair}
                              for pair in source_bins(fine)]
                    question=(f'Re-examine these source video frames from {fine[0]["time_sec"]:.6f} to {fine[-1]["time_sec"]:.6f} seconds. '
                              + ROLE_GUIDANCE +
                              'Independently verify whether the following specific visible event occurs: '+FIELDS[kind]+'. '
                              'Do not trust the earlier proposal. Cash moving on the desk is not necessarily combining bundles; '
                              'cash on the desk alone does not prove a change of customer. '
                              'If the event is absent, return {"status":"not_observed"}. If it is ambiguous or needs missing earlier/later visual context, '
                              'return {"status":"unclear"}. If clearly visible, return {"status":"observed","start_sec":number,"end_sec":number} '
                              'using the beginning and end supported by this video, in original video seconds. '
                              'Displayed timestamps denote frame-pair averages; source boundaries for each are: '
                              +json.dumps(time_map,separators=(',',':'))+'. '
                              'Use start_sec from the first supporting pair and end_sec from the last. '
                              'Do not return guessed identities or money ownership.')
                    if kind in OPERATION_CONTEXT_KEYS:
                        question += (
                            ' This category depends on the visible sequence of a complete operation. '
                            'Trace its beginning, relevant handling and completion within this input. '
                            'An unobserved document check/count is NOT evidence that it was omitted. '
                            'If the operation begins before this input, ends after it, contains occlusion, '
                            'or sparse frames could hide the required check, return unclear. '
                            'Digital identity checks may not be visually observable. '
                            'Do not infer lack of verification from typing, a missing physical card or a machine reject tray. '
                            'For a supported candidate, localize the visible transition or action, not an invented missing action.'
                        )
                    history = (earlier_frame_pairs(frames,fine)
                               if self.temporal_context and kind=='old_cash_at_client_change' else [])
                    if history:
                        question=history_prompt(history,fine)+question
                    localized,trace=self.infer(history+fine,question,grammar,deadline,pixels=8_388_608)
                    localized=validate_localization(localized,fine)
                    diagnostics.append({'stage':'refine','kind':kind,'history_frame_count':len(history),**trace})
                    refinements.append({**candidate,'proposed_time_sec':None if full_state_window else center,
                                        'input_window_selection':'complete_candidate' if full_state_window else 'model_point',
                                        'dense_start_sec':fine[0]['time_sec'],
                                        'dense_end_sec':fine[-1]['time_sec'],'sampling':sampling_metadata(fine,4.),
                                        'history_timestamps':[frame['time_sec'] for frame in history],**localized})
                    if localized['status']!='observed':
                        questions.append({'type':RISK_TITLES[kind][1],'timecode_sec':center,
                                          'message':'Первый и повторный проходы модели не подтвердили один и тот же видимый признак. Требуется просмотр человеком; нарушение не установлено.',
                                          'status':'requires_review','reason':'native_refinement_'+localized['status']})
                        continue
                    times=[f['time_sec'] for f in fine if localized['start_sec']<=f['time_sec']<=localized['end_sec']]
                    cid,title=RISK_TITLES[kind]
                    # Preserve separate episodes; deduplicate only identical dense
                    # supports reached from overlapping candidate windows.
                    if any(e['category_id']==cid and e['start_sec']==times[0] and e['end_sec']==times[-1] for e in events):
                        continue
                    rule=PUBLIC_CASH_RULE.copy() if kind in {'cash_mixed','old_cash_at_client_change','cash_unattended'} else None
                    description=((('Локальная модель отметила состояние двери при подробном просмотре четырёх исходных кадров и повторном определении интервала. '
                                   if kind=='room_door_left_open' else
                                   'Локальная модель отметила признак при обзорном просмотре и повторном анализе последовательности исходных кадров. '))+
                                 f'Интервал по выбранным кадрам: {times[0]:.2f}–{times[-1]:.2f} с. '
                                 'Это автоматическая локализация, её границы и правильность требуют проверки человеком. ')
                    description+= ('Принадлежность денег разным клиентам не установлена; пункт 20 применим только при подтверждении соответствующих обстоятельств операции.'
                                  if rule else 'Применимость нормативного основания требует проверки.')
                    if kind in CATEGORY_NOTES:
                        description += ' ' + CATEGORY_NOTES[kind]
                    if kind == 'room_door_left_open':
                        description += 'Найден подозрительный эпизод: возможно, дверь помещения оставалась открытой. Вход человека и его права доступа этим событием не устанавливаются.'
                    events.append({'type':title,'category_id':cid,'timecode_sec':times[0],
                                   'start_sec':times[0],'end_sec':times[-1],'description':description,
                                   'localization':('detailed_state_sample_support' if kind=='room_door_left_open' else
                                                   'operation_window_sample_support' if kind in OPERATION_CONTEXT_KEYS else
                                                   'object_detail_sample_support' if kind in DETAIL_OBJECT_KEYS else 'dense_sample_support'),
                                   'status':'possible_sign_requires_review',
                                   'rule':rule,'evidence_frames':evidence(frames,times)})
                    print(json.dumps({'stage':'refine','candidates_reviewed':index+1,'candidates_total':len(candidates),
                                      'elapsed_sec':round(time.monotonic()-began,2)}),file=sys.stderr,flush=True)
            queue_progress['status']='complete'
            events.sort(key=lambda x:x['timecode_sec'])
            questions.sort(key=lambda x:x['timecode_sec'])
            return {'verdict':'violation' if events else 'no_violation','violations':events,
                    'analysis':{'model':self.model_name,'model_revision':self.model_revision,'pixel_cap':self.pixel_cap,
                                'temporal_context':self.temporal_context,
                                'implementation':VERSION,'experimental':True,'new_training':False,'network_disabled':True,
                                'findings_status':'requires_review','complete':True,'timeline_covered':True,
                                'duration_sec':duration,'elapsed_sec':round(time.monotonic()-began,3),
                                'input_mode':'native_video_with_source_pts','requested_sample_fps':2.,'window_seconds':20.,'stride_seconds':16.,
                                'source_sampling':source_sampling,'overview_sampling':overview_sampling,
                                'requested_refinement_sample_fps':4.,'temporal_patch_frames':2,
                                'room_door_refinement':'four_detailed_source_frames_full_window',
                                'localization':'approximate_window','boundary_method':'independent_dense_video_review',
                                'windows_done':len(outcomes),'windows_total':len(plan),'coverage_gaps':[],
                                'uncertain_windows':sum(w['uncertain'] for w in outcomes),'windows':outcomes,
                                'overview':overview,'actions':actions,'sequence':sequence,'refinements':refinements,
                                'supported_categories':[value[0] for value in RISK_TITLES.values()],
                                'category_coverage':{'configured':len(RISK_TITLES),'screened':list(RISK_TITLES),
                                                     'accuracy_validated':False},
                                'candidate_review':{k:v for k,v in queue_progress.items() if k!='stage'},
                                'review_questions':questions[:40],
                                'limitations':preliminary['limitations']+[
                                    'Видеомодель использует обзор всей операции, перекрывающиеся фрагменты и историю непроверенных наблюдений.',
                                    'Кандидаты проходят повторный просмотр исходных кадров: полный фрагмент для последовательности операции, детальные кадры для мелких предметов и двери. Число кадров ограничено бюджетом; короткое действие может быть пропущено. Это не независимая проверка человеком.',
                                    'Начало и конец привязаны к исходным кадрам, но точность границ не гарантирована; два кадра объединяются видеопроцессором.',
                                    'Отсутствие действия в выборке не доказывает его отсутствие в операции. Записи в банковской базе по видео не проверяются.'],
                                'peak_vram_gib':round(self.torch.cuda.max_memory_allocated()/2**30,3)},
                    '_diagnostics':{'responses':diagnostics}}
