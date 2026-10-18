import copy

import pytest

from native_core import FIELDS, action_observations, risk_candidates
from native_sampling import sampling_metadata, validate_coverage


def frames(*times):
    return [{'time_sec': t} for t in times]


def outcome(index, start, end, *, sampled=(), **seen):
    return {'index': index, 'start_sec': start, 'end_sec': end,
            'sampled_timestamps': list(sampled),
            'checks': {**dict.fromkeys(FIELDS, 'not_seen'), **seen}}


def test_positive_overlapping_windows_remain_separate_localization_proposals():
    outcomes = [outcome(0, 0, 20, cash_mixed='seen'),
                outcome(1, 16, 36, cash_mixed='seen'),
                outcome(2, 32, 52, cash_mixed='seen')]
    before = copy.deepcopy(outcomes)
    result = risk_candidates(outcomes)
    assert [(r['start_sec'], r['end_sec']) for r in result] == [(0, 20), (16, 36), (32, 52)]
    assert [r['supporting_windows'] for r in result] == [[0], [1], [2]]
    assert outcomes == before


def test_repeated_identical_window_is_not_duplicated_and_unclear_is_not_positive():
    row = outcome(0, 0, 20, cash_mixed='seen', cash_unattended='unclear')
    assert len(risk_candidates([row, copy.deepcopy(row)])) == 1
    assert risk_candidates([outcome(0, 0, 20, cash_mixed='unclear')]) == []


def test_evidence_uses_model_sampling_intersected_with_actual_source_frames():
    source = frames(0., .25, .5, .75, 1.)
    row = outcome(0, 0., 1., sampled=[0., .5, 1., .66, 99., True, float('nan')], cash_received='seen')
    result = action_observations([row], source)
    assert len(result) == 1
    assert result[0]['evidence_timestamps'] == [0., .5, 1.]
    assert result[0]['evidence_kind'] == 'sampled_window_context'
    assert result[0]['start_sec'] == 0 and result[0]['end_sec'] == 1


def test_observation_support_does_not_borrow_unshown_source_timestamps():
    row = outcome(0, 0., 1., sampled=[.25, .75], cash_received='seen')
    result = action_observations([row], frames(0., .25, .5, .75, 1.))
    assert result[0]['start_sec'] == .25 and result[0]['end_sec'] == .75
    assert result[0]['evidence_timestamps'] == [.25, .75]


def test_missing_or_disjoint_model_input_support_fails_instead_of_inventing_evidence():
    row = outcome(0, 0., 1., cash_received='seen')
    with pytest.raises(ValueError, match='no actual model input'):
        action_observations([row], frames(0., .5, 1.))
    del row['sampled_timestamps']
    with pytest.raises(ValueError, match='sampled_timestamps'):
        action_observations([row], frames(0., .5, 1.))


def test_sampling_metadata_distinguishes_requested_and_actual_density():
    result = sampling_metadata(frames(10., 12., 14.), requested_fps=2.)
    assert result['requested_fps'] == 2 and result['effective_fps'] == .5
    assert result['max_gap_sec'] == 2 and result['sampled_timestamps'] == [10., 12., 14.]
    assert result['frame_count'] == 3 and result['first_time_sec'] == 10 and result['last_time_sec'] == 14


def test_metadata_retains_vfr_pts_and_exposes_worst_gap():
    source = frames(20., 20.266667, 20.5, 20.766667)
    result = sampling_metadata(source, 4.)
    assert result['sampled_timestamps'] == [f['time_sec'] for f in source]
    assert result['max_gap_sec'] == pytest.approx(.266667)
    assert result['effective_fps'] == pytest.approx(3/.766667)


@pytest.mark.parametrize('source', [frames(0.), frames(1., 1.), frames(1., 0.),
                                    frames(-1., 0.), frames(False, 1.), frames(0., float('inf'))])
def test_invalid_sampling_metadata_is_rejected(source):
    with pytest.raises(ValueError):
        sampling_metadata(source, 2.)


@pytest.mark.parametrize('fps', [0, -1, True, float('nan')])
def test_invalid_requested_density_is_rejected(fps):
    with pytest.raises(ValueError):
        sampling_metadata(frames(0., 1.), fps)


def test_coverage_checks_prefix_tail_and_internal_gap_separately():
    with pytest.raises(ValueError, match='beginning'):
        validate_coverage(frames(5., 5.25, 5.5), 0., 5.5)
    with pytest.raises(ValueError, match='end'):
        validate_coverage(frames(0., .25, .5), 0., 5.5)
    with pytest.raises(ValueError, match='Gap'):
        validate_coverage(frames(0., .25, 2., 2.25), 0., 2.25)


def test_coverage_accepts_explicit_tolerance_and_rejects_outside_frames():
    assert validate_coverage(frames(.1, .35, .6, .85), 0., 1., endpoint_tolerance=.15, max_gap_sec=.25) is None
    with pytest.raises(ValueError, match='outside'):
        validate_coverage(frames(0., .25, .5), .1, .5)


@pytest.mark.parametrize('patch', [{'start': True}, {'end': float('nan')},
                                 {'endpoint_tolerance': -1}, {'max_gap_sec': 0}])
def test_invalid_coverage_parameters_are_rejected(patch):
    options = {'start': 0., 'end': 1., 'endpoint_tolerance': .5, 'max_gap_sec': .5, **patch}
    with pytest.raises(ValueError):
        validate_coverage(frames(0., .5, 1.), **options)
