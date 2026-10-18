"""Exercise every category through the real orchestration with symbolic frames."""
import pytest
import native_engine as module
from native_core import FIELDS
from test_native_engine import engine


@pytest.mark.parametrize('kind,cid', [(k,v[0]) for k,v in module.RISK_TITLES.items()])
def test_every_category_is_refined_and_published(monkeypatch,tmp_path,kind,cid):
    item,calls=engine(monkeypatch,tmp_path,door_sequence=lambda a,b:'C' if kind=='room_door_left_open' and a==0 else 'A')
    def checks(frames,start,end,context,deadline,**kwargs):
        values=dict.fromkeys(FIELDS,'not_seen')
        if start==0 and end<=20: values[kind]='seen'
        return values,{}
    item.infer_checks=checks
    result=item.analyze(tmp_path/'arbitrary.mov')
    assert [e['category_id'] for e in result['violations']]==[cid]
    analysis=result['analysis']
    assert set(analysis['supported_categories'])=={f'c{i:02d}' for i in range(1,15)}
    assert analysis['category_coverage']['configured']==14
    assert analysis['category_coverage']['accuracy_validated'] is False
    assert analysis['candidate_review']['remaining']==0
    refinement=next(r for r in analysis['refinements'] if r['kind']==kind and r['status']=='observed')
    event=result['violations'][0]
    assert event['start_sec'] in refinement['sampling']['sampled_timestamps']
    assert event['end_sec'] in refinement['sampling']['sampled_timestamps']
    if kind in module.OPERATION_CONTEXT_KEYS:
        assert refinement['dense_start_sec']==0
        assert refinement['dense_end_sec']==20
        assert not any(c['stage']=='locate' for c in calls)
        assert event['localization']=='operation_window_sample_support'


def test_negative_checklist_does_not_manufacture_missing_actions(monkeypatch,tmp_path):
    item,_=engine(monkeypatch,tmp_path)
    item.infer_checks=lambda *args,**kwargs:(dict.fromkeys(FIELDS,'not_seen'),{})
    assert item.analyze(tmp_path/'arbitrary.mov')['violations']==[]
