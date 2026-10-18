import json
import math
import pytest
from native_core import (FIELDS, ChecklistGrammar, ChoiceGrammar, parse_checklist, bounded_memory,
                         checklist_prompt, risk_candidates, localization_choices, validate_localization,
                         action_observations)
from native_video import timestamp_metadata,select_frames


class Characters:
    eos_token_id=0
    def __call__(self,texts,add_special_tokens=False):return {'input_ids':[list(map(ord,t)) for t in texts]}


def accepts(grammar,text):
    prefix=[]
    for token in map(ord,text):
        assert token in grammar.allowed(prefix)
        prefix.append(token)
    assert grammar.allowed(prefix)==[0]


def test_checklist_grammar_does_not_cap_observed_actions_at_three():
    for value in ['seen','not_seen','unclear']:
        checks=dict.fromkeys(FIELDS,value)
        grammar=ChecklistGrammar(Characters())
        text=json.dumps(checks,separators=(',',':'))
        accepts(grammar,text)
        assert grammar.max_tokens>=len(text)+1
        assert parse_checklist(text)==checks


@pytest.mark.parametrize('patch',[{'cash_counted':True},{'cash_counted':[]},{'cash_counted':'yes'},{'unknown':'seen'}])
def test_malformed_checklist_never_becomes_a_negative(patch):
    checks=dict.fromkeys(FIELDS,'not_seen');checks.update(patch)
    with pytest.raises(ValueError):parse_checklist(json.dumps(checks))


def test_mixed_checklist_and_temporal_alternatives():
    checks={key:('seen','not_seen','unclear')[i%3] for i,key in enumerate(FIELDS)}
    accepts(ChecklistGrammar(Characters()),json.dumps(checks,separators=(',',':')))
    choices=[{'time_sec':None},{'time_sec':7.25}]
    grammar=ChoiceGrammar(Characters(),choices)
    for c in choices:accepts(grammar,json.dumps(c,separators=(',',':')))
    with pytest.raises(ValueError):grammar.allowed(list(map(ord,'{"time_sec":999')))


def outcome(i,start,end,**seen):
    return {'index':i,'start_sec':start,'end_sec':end,'checks':{**dict.fromkeys(FIELDS,'not_seen'),**seen}}


def test_sequence_memory_preserves_observations_across_windows_without_promoting_negatives():
    rows=[outcome(i,i*16,i*16+20,cash_received='seen') for i in range(6)]
    rows[0]['filename']='LABEL_WITH_ORACLE_TIME_999'
    memory=bounded_memory(rows)
    assert len(memory)==4 and memory[0]['start_sec']==32
    assert memory[0]['observed']==['cash_received']
    prompt=checklist_prompt(96,116,memory)
    assert 'UNVERIFIED' in prompt and '999' not in prompt and 'LABEL' not in prompt


def test_candidates_require_model_positive_and_keep_disjoint_episodes():
    rows=[outcome(0,0,20,cash_mixed='seen'),outcome(1,16,36,cash_mixed='seen'),
          outcome(2,32,52,cash_unattended='unclear'),outcome(3,48,68,cash_mixed='seen')]
    found=risk_candidates(rows)
    assert len(found)==3 and found[0]['end_sec']==20 and found[1]['supporting_windows']==[1]
    assert not risk_candidates([outcome(0,0,20)])


def test_dense_boundaries_must_be_actual_temporal_patch_support():
    frames=[{'time_sec':10.0},{'time_sec':10.266667},{'time_sec':10.5},{'time_sec':10.766667}]
    choices=localization_choices(frames)
    good={'status':'observed','start_sec':10.,'end_sec':10.266667}
    assert validate_localization(good,frames)==good
    assert {'status':'not_observed'} in choices and {'status':'unclear'} in choices
    accepts(ChoiceGrammar(Characters(),choices),json.dumps(good,separators=(',',':')))
    for bad in [{'status':'observed','start_sec':10.1,'end_sec':10.266667},
                {'status':'observed','start_sec':10.5,'end_sec':10.266667},
                {'status':'observed','start_sec':True,'end_sec':10.266667}]:
        with pytest.raises(ValueError):validate_localization(bad,frames)


def test_source_pts_survive_vfr_and_nonzero_clip_offset():
    frames=[{'time_sec':55.033333},{'time_sec':55.3},{'time_sec':55.533333}]
    m=timestamp_metadata(frames)
    assert [v/m['fps'] for v in m['frames_indices']]==[f['time_sec'] for f in frames]
    with pytest.raises(ValueError):timestamp_metadata(frames[::-1])
    with pytest.raises(ValueError):timestamp_metadata([{'time_sec':False},{'time_sec':1.}])


def test_sampling_preserves_tail_and_excludes_context_outside_interval():
    frames=[{'time_sec':i/4} for i in range(81)]
    selected=select_frames(frames,4.,12.,fps=2,max_frames=48)
    assert selected[0]['time_sec']==4 and selected[-1]['time_sec']==12
    assert len(selected)==17


def test_resampling_vfr_does_not_accumulate_rounding_drift_and_halve_density():
    # 30 FPS source, sampled at 4 FPS: alternating .25 s targets round upwards.
    frames=[{'time_sec':round(math.ceil(i*30/4)/30,6)} for i in range(29)]
    selected=select_frames(frames,0,7,fps=4,max_frames=32)
    assert selected==frames
    assert max(b['time_sec']-a['time_sec'] for a,b in zip(selected,selected[1:]))<.27


def test_observations_are_unverified_context_not_fabricated_exact_evidence():
    rows=[outcome(0,0,1,cash_received='seen',cash_stored='unclear')]
    rows[0]['sampled_timestamps']=[0.,.5,1.]
    result=action_observations(rows,[{'time_sec':0.},{'time_sec':.5},{'time_sec':1.}])
    assert len(result)==1 and result[0]['action']=='cash_received'
    assert result[0]['evidence_kind']=='sampled_window_context'
    assert result[0]['human_verified'] is False
