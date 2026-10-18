"""Synthetic result validation, without video/model/GPU access."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis_contract import AnalysisContractError, enforce_evidence_contract


def result():
    return {"verdict": "violation", "violations": [{
        "category_id": "c12", "status": "possible_sign_requires_review",
        "start_sec": 0., "timecode_sec": 0., "end_sec": 4.,
        "evidence_frames": [{"timestamp_sec": 0., "image_base64": "synthetic"}],
    }], "analysis": {
        "implementation": "native-sequence-refine-test", "findings_status": "requires_review",
        "duration_sec": 5., "review_questions": [], "uncertain_windows": 0,
        "candidate_review": {"status": "complete", "done": 1, "total": 1, "remaining": 0},
        "source_sampling": {"sampled_timestamps": [0., 2., 4.]},
        "refinements": [{"kind": "room_door_left_open", "status": "observed",
                         "start_sec": 0., "end_sec": 4.,
                         "sampling": {"sampled_timestamps": [0., 2., 4.]}}],
    }}


def test_valid_door_candidate_remains_a_candidate_even_if_general_checklist_missed_it():
    data = result()
    data["analysis"]["windows"] = [{"checks": {"room_door_left_open": "not_seen"}}]
    accepted = enforce_evidence_contract(data)
    assert len(accepted["violations"]) == 1
    assert accepted["analysis"]["result_status"] == "possible_sign_requires_review"
    assert accepted["analysis"]["compliance_established"] is False
    assert accepted["violations"][0]["human_verified"] is False


@pytest.mark.parametrize("fault", [
    "pending", "missing_queue", "count_mismatch", "confirmed", "verified", "no_evidence",
    "invented_time", "outside_clip", "nan", "boolean_time", "rejected_review",
    "wrong_category", "unreviewed_bounds", "missing_source", "compliance_claim",
    "evidence_not_reviewed", "invented_review_sample", "missing_review",
])
def test_broken_evidence_contract_never_becomes_a_clean_negative(fault):
    data = result()
    event, analysis = data["violations"][0], data["analysis"]
    if fault == "pending": analysis["candidate_review"]["status"] = "running"
    if fault == "missing_queue": analysis.pop("candidate_review")
    if fault == "count_mismatch": analysis["candidate_review"]["total"] = 2
    if fault == "confirmed": event["status"] = "confirmed_violation"
    if fault == "verified": event["human_verified"] = True
    if fault == "no_evidence": event["evidence_frames"] = []
    if fault == "invented_time": event["evidence_frames"][0]["timestamp_sec"] = 1.
    if fault == "outside_clip": event["end_sec"] = 100.
    if fault == "nan": event["start_sec"] = float("nan")
    if fault == "boolean_time": event["timecode_sec"] = False
    if fault == "rejected_review": analysis["refinements"][0]["status"] = "not_observed"
    if fault == "wrong_category": event["category_id"] = "c13"
    if fault == "unreviewed_bounds": event["end_sec"] = 2.
    if fault == "missing_source": analysis.pop("source_sampling")
    if fault == "compliance_claim": analysis["compliance_established"] = True
    if fault == "evidence_not_reviewed":
        event["evidence_frames"][0]["timestamp_sec"] = 2.
        analysis["refinements"][0]["sampling"]["sampled_timestamps"] = [0., 4.]
    if fault == "invented_review_sample": analysis["refinements"][0]["sampling"]["sampled_timestamps"] = [0., 1., 4.]
    if fault == "missing_review": analysis["refinements"] = []
    original = deepcopy(data)
    with pytest.raises(AnalysisContractError):
        enforce_evidence_contract(data)
    assert data["verdict"] == "violation"
    assert len(data["violations"]) == len(original["violations"]) == 1
    assert "reporting_policy" not in analysis


@pytest.mark.parametrize("uncertain,questions,expected", [
    (0, [], "no_signals_found"), (1, [], "review_required"),
    (0, [{"reason": "native_refinement_unclear"}], "review_required"),
])
def test_no_candidate_never_establishes_compliance(uncertain, questions, expected):
    data = result()
    data.update(verdict="no_violation", violations=[])
    data["analysis"].update(uncertain_windows=uncertain, review_questions=questions)
    data["analysis"]["refinements"][0]["status"] = "unclear" if uncertain or questions else "not_observed"
    accepted = enforce_evidence_contract(data)
    assert accepted["analysis"]["result_status"] == expected
    assert accepted["analysis"]["compliance_established"] is False
    assert accepted["analysis"]["verdict_semantics"] == "candidate_presence_only"


@pytest.mark.parametrize("fault", ["lost_observed", "lost_review", "missing_queue"])
def test_lost_work_cannot_turn_into_no_signals(fault):
    data = result()
    data.update(verdict="no_violation", violations=[])
    if fault == "lost_review": data["analysis"]["refinements"] = []
    if fault == "missing_queue": data["analysis"].pop("candidate_review")
    with pytest.raises(AnalysisContractError):
        enforce_evidence_contract(data)
    assert "result_status" not in data["analysis"]
