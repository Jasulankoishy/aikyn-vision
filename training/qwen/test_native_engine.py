"""Backend orchestration tests using symbolic frames, never bank media or GPU."""
from types import SimpleNamespace
import pytest
import native_engine as module
from native_core import FIELDS


class Tokens:
    eos_token_id=0
    def __call__(self,texts,add_special_tokens=False):
        return {'input_ids':[list(map(ord,text)) for text in texts]}


def engine(monkeypatch, tmp_path, *, confirmed=True, first=0., overview_only=False, door_sequence='A'):
    item=object.__new__(module.NativeQuickEngine)
    item.torch=SimpleNamespace(cuda=SimpleNamespace(reset_peak_memory_stats=lambda:None,max_memory_allocated=lambda:0))
    item.processor=SimpleNamespace(tokenizer=Tokens())
    item.cancelled_error=RuntimeError
    frames=[{'time_sec':i/4,'path':'unused'} for i in range(int(first*4),161)]
    item.sample_video=lambda *args:frames
    monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.setattr(module,'inspect',lambda _:40.033)
    monkeypatch.setattr(module,'evidence',lambda frames,times:[{'timestamp_sec':times[0],'image_base64':'synthetic'}])
    calls=[]
    def checks(frames,start,end,context,deadline,**kwargs):
        calls.append({'stage':'checks','start':start,'end':end,'memory':context})
        values=dict.fromkeys(FIELDS,'not_seen')
        if (overview_only and end-start>20) or (not overview_only and end-start<=20 and start<32):
            values.update(cash_mixed='seen',cash_received='seen')
        return values,{}
    def infer(frames,question,grammar,deadline,**kwargs):
        if 'time_sec' in grammar.choices[0]:
            calls.append({'stage':'locate'})
            source={f['time_sec'] for f in frames}
            assert all(c['time_sec'] is None or c['time_sec'] in source for c in grammar.choices)
            desired=10. if frames[0]['time_sec']==0 else 26.
            return min(grammar.choices[1:],key=lambda c:abs(c['time_sec']-desired)),{}
        calls.append({'stage':'refine'})
        assert 'Displayed timestamps denote frame-pair averages' in question
        if not confirmed:return {'status':'not_observed'},{}
        return next(c for c in grammar.choices if c['status']=='observed'),{}
    def classify_door(frames,start,end,deadline):
        calls.append({'stage':'door_sequence'})
        assert len(frames)<=4
        assert frames[0]['time_sec']==start
        assert frames[-1]['time_sec']==end
        return {'sequence':door_sequence(start,end) if callable(door_sequence) else door_sequence},{}
    item.infer_checks=checks;item.infer=infer;item.infer_door_sequence=classify_door
    return item,calls


def test_native_pipeline_keeps_context_and_refines_separate_episodes(monkeypatch,tmp_path):
    item,calls=engine(monkeypatch,tmp_path)
    result=item.analyze(tmp_path/'unused.mov')
    assert len(result['violations'])==2
    assert [c['stage'] for c in calls].count('locate')==2
    assert [c['stage'] for c in calls].count('refine')==2
    coarse=[c for c in calls if c['stage']=='checks'][1:]
    assert len(coarse)==3 and coarse[1]['memory'][0]['observed']==['cash_received','cash_mixed']
    a=result['analysis']
    assert a['complete'] and a['timeline_covered'] and a['windows_done']==a['windows_total']==3
    assert a['source_sampling']['requested_fps']==4
    assert a['overview_sampling']['sampled_timestamps'][0]==0
    assert [c['stage'] for c in calls].count('door_sequence')==3
    positive_refinements=[r for r in a['refinements'] if r['status']=='observed']
    assert len(positive_refinements)==len(result['violations'])
    for event,refinement in zip(result['violations'],positive_refinements):
        assert event['start_sec'] in refinement['sampling']['sampled_timestamps']
        assert event['end_sec'] in refinement['sampling']['sampled_timestamps']
        assert event['status']=='possible_sign_requires_review'


def test_dense_rejection_never_publishes_coarse_candidate(monkeypatch,tmp_path):
    item,_=engine(monkeypatch,tmp_path,confirmed=False)
    result=item.analyze(tmp_path/'unused.mov')
    assert result['violations']==[]
    assert all(r['status']=='not_observed' for r in result['analysis']['refinements'])
    assert any(q['reason']=='native_refinement_not_observed' for q in result['analysis']['review_questions'])


def test_missing_source_prefix_is_incomplete_before_any_model_answer(monkeypatch,tmp_path):
    item,calls=engine(monkeypatch,tmp_path,first=5.)
    with pytest.raises(module.IncompleteAnalysis,match='beginning'):
        item.analyze(tmp_path/'unused.mov')
    assert calls==[]


def test_whole_video_candidate_only_uses_anchors_visible_in_locate_input(monkeypatch,tmp_path):
    item,calls=engine(monkeypatch,tmp_path,overview_only=True)
    result=item.analyze(tmp_path/'unused.mov')
    assert len(result['violations'])==1
    positive=[r for r in result['analysis']['refinements'] if r['status']=='observed']
    assert len(positive)==1 and positive[0]['origin']=='overview'
    assert [c['stage'] for c in calls].count('locate')==1


@pytest.mark.parametrize('door_state,confirmed,expected', [
    ('seen', True, 1), ('seen', False, 0), ('not_seen', True, 1), ('unclear', True, 1),
])
def test_room_door_has_own_category_and_requires_dense_visual_support(monkeypatch,tmp_path,door_state,confirmed,expected):
    item,calls=engine(monkeypatch,tmp_path,confirmed=confirmed,
                      door_sequence=lambda start,end:'C' if start==0 else 'A')
    def checks(frames,start,end,context,deadline,**kwargs):
        values=dict.fromkeys(FIELDS,'not_seen')
        if start == 0 and end <= 20:
            values['room_door_left_open']=door_state
        return values,{}
    item.infer_checks=checks
    result=item.analyze(tmp_path/'arbitrary-name.mov')
    assert len(result['violations']) == expected
    assert [c['stage'] for c in calls].count('door_sequence')==3
    assert 'c12' in result['analysis']['supported_categories']
    if expected:
        event=result['violations'][0]
        assert event['category_id']=='c12'
        assert event['rule'] is None  # Do not attach an unrelated cash rule.
        assert event['timecode_sec']==event['start_sec']
        assert event['evidence_frames'][0]['timestamp_sec']==event['start_sec']
        assert result['analysis']['candidate_review']['remaining']==0
        refinement=result['analysis']['refinements'][0]
        assert refinement['dense_start_sec']==0
        assert refinement['dense_end_sec']==20
        assert refinement['proposed_time_sec'] is None
        assert refinement['input_window_selection']=='complete_candidate'
        assert not any(c['stage']=='locate' for c in calls)
        assert len(refinement['sampling']['sampled_timestamps'])==4
        assert event['localization']=='detailed_state_sample_support'
        assert refinement['sampling']['effective_fps']<1


@pytest.mark.parametrize('sequence', ['A', 'B', 'D'])
def test_room_door_visual_sequence_rejects_closed_passage_and_ambiguous(monkeypatch,tmp_path,sequence):
    item,calls=engine(monkeypatch,tmp_path,door_sequence=sequence)
    def checks(frames,start,end,context,deadline,**kwargs):
        values=dict.fromkeys(FIELDS,'not_seen')
        if start==0 and end<=20:
            values['room_door_left_open']='seen'
        return values,{}
    item.infer_checks=checks
    result=item.analyze(tmp_path/'unrelated.mov')
    assert result['violations']==[]
    assert [c['stage'] for c in calls]==['door_sequence']*3
    assert result['analysis']['candidate_review']['remaining']==0
    assert result['analysis']['refinements'][0]['door_sequence']==sequence
    assert all(r['door_sequence']==sequence for r in result['analysis']['refinements'])


def test_detailed_door_pass_can_find_event_despite_negative_general_checklist(monkeypatch,tmp_path):
    item,calls=engine(monkeypatch,tmp_path,door_sequence=lambda start,end:'C' if start==0 else 'A')
    item.infer_checks=lambda *args,**kwargs:(dict.fromkeys(FIELDS,'not_seen'),{})
    result=item.analyze(tmp_path/'unrelated.mov')
    assert len(result['violations'])==1
    assert result['violations'][0]['category_id']=='c12'
    positive=[r for r in result['analysis']['refinements'] if r['status']=='observed']
    assert len(positive)==1
    assert positive[0]['origin']=='independent_detailed_door_review'
    assert positive[0]['supporting_windows']==[0]
    assert [c['stage'] for c in calls].count('door_sequence')==3
    assert [c['stage'] for c in calls].count('refine')==1
    assert result['analysis']['candidate_review']['remaining']==0
