"""Pure contract/privacy tests for the optional live API checker."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_quick_api import local_address, read_key, result_summary


@pytest.mark.parametrize("url", ["https://remote.example", "http://remote.example",
                                "http://user:pass@localhost:8080", "http://localhost:8080/?secret=yes",
                                "http://localhost:8080/path", "http://127.0.0.1.evil.example:8080"])
def test_checker_refuses_remote_or_ambiguous_destinations(url):
    with pytest.raises(ValueError):
        local_address(url)


def test_loopback_addresses_are_allowed():
    assert local_address("http://127.0.0.1:8080") == ("127.0.0.1", 8080)
    assert local_address("http://localhost:18080/") == ("localhost", 18080)


def test_response_summary_never_contains_model_text_or_frames():
    response = {"status": "done", "mode": "real", "verdict": "violation", "violations": [
        {"description": "PRIVATE_BANK_OBSERVATION", "evidence_frames": [{"image_base64": "PRIVATE_FRAME_BYTES"}]}],
        "analysis": {"model": "Qwen3-VL-2B-Instruct", "experimental": True, "new_training": False, "complete": True, "timeline_covered": True,
                     "findings_status": "requires_review", "windows_done": 2, "windows_total": 2,
                     "actions": ["PRIVATE_ACTION"], "review_questions": ["PRIVATE_QUESTION"]}}
    summary = result_summary(response)
    assert summary["contract_valid"] is True
    assert summary["candidate_events"] == summary["evidence_frames"] == 1
    assert "PRIVATE" not in json.dumps(summary)
    response["analysis"]["windows_done"] = "PRIVATE_UNEXPECTED_VALUE"
    summary = result_summary(response)
    assert summary["contract_valid"] is False
    assert summary["windows_done"] is None
    assert "PRIVATE" not in json.dumps(summary)


def test_partial_response_is_not_a_valid_negative():
    response = {"status": "done", "mode": "real", "verdict": "no_violation", "violations": [],
                "analysis": {"experimental": True, "new_training": False, "complete": False,
                             "timeline_covered": False, "findings_status": "requires_review",
                             "windows_done": 1, "windows_total": 2}}
    assert result_summary(response)["contract_valid"] is False


def test_bad_key_error_does_not_include_its_value(tmp_path):
    path = tmp_path / "key.txt"
    path.write_text("PRIVATE_SECRET\nheader-injection", encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        read_key(path)
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("model", ["Qwen3-VL-2B-Instruct", "Qwen3-VL-4B-Instruct"])
def test_checker_accepts_and_reports_actual_supported_model(model):
    response = {"status": "done", "mode": "real", "verdict": "no_violation", "violations": [],
                "analysis": {"model": model, "pixel_cap": 3_145_728,
                             "experimental": True, "new_training": False, "complete": True,
                             "timeline_covered": True, "findings_status": "requires_review",
                             "windows_done": 5, "windows_total": 5}}
    summary = result_summary(response)
    assert summary["contract_valid"] is True
    assert summary["model"] == model and summary["pixel_cap"] == 3_145_728
    del response["analysis"]["pixel_cap"]
    assert result_summary(response)["contract_valid"] is True


@pytest.mark.parametrize("model", [None, "Qwen3-VL-8B-Instruct", "PRIVATE_MODEL_TEXT", [], {}])
def test_missing_unknown_or_malformed_model_cannot_pass_api_verification(model):
    response = {"status": "done", "mode": "real", "verdict": "no_violation", "violations": [],
                "analysis": {"model": model, "experimental": True, "new_training": False,
                             "complete": True, "timeline_covered": True, "findings_status": "requires_review",
                             "windows_done": 1, "windows_total": 1}}
    summary = result_summary(response)
    assert summary["contract_valid"] is False and summary["model"] is None
    assert "PRIVATE" not in json.dumps(summary)


@pytest.mark.parametrize("cap", [True, -1, 0, 8_388_609, "PRIVATE_PIXEL_BUDGET"])
def test_malformed_pixel_cap_is_rejected_and_not_echoed(cap):
    response = {"status": "done", "mode": "real", "verdict": "no_violation", "violations": [],
                "analysis": {"model": "Qwen3-VL-4B-Instruct", "pixel_cap": cap,
                             "experimental": True, "new_training": False, "complete": True,
                             "timeline_covered": True, "findings_status": "requires_review",
                             "windows_done": 1, "windows_total": 1}}
    summary = result_summary(response)
    assert summary["contract_valid"] is False and summary["pixel_cap"] is None
    assert "PRIVATE" not in json.dumps(summary)


@pytest.mark.parametrize("budget", [524_288, 2_097_152, 4_194_304, 8_388_608])
def test_focused_pixel_budget_is_reported_without_losing_model_identity(budget):
    response = {"status": "done", "mode": "real", "verdict": "no_violation", "violations": [],
                "analysis": {"model": "Qwen3-VL-4B-Instruct", "pixel_budget": budget,
                             "experimental": True, "new_training": False, "complete": True,
                             "timeline_covered": True, "findings_status": "requires_review",
                             "windows_done": 1, "windows_total": 1}}
    summary = result_summary(response)
    assert summary["contract_valid"] is True and summary["pixel_budget"] == budget
    assert summary["model"] == "Qwen3-VL-4B-Instruct"


@pytest.mark.parametrize("budget", [None, True, False, 524_287, 8_388_609, 2_097_152.0, "PRIVATE_PIXEL_BUDGET"])
def test_invalid_focused_pixel_budget_is_rejected_and_not_echoed(budget):
    response = {"status": "done", "mode": "real", "verdict": "no_violation", "violations": [],
                "analysis": {"model": "Qwen3-VL-4B-Instruct", "pixel_budget": budget,
                             "experimental": True, "new_training": False, "complete": True,
                             "timeline_covered": True, "findings_status": "requires_review",
                             "windows_done": 1, "windows_total": 1}}
    summary = result_summary(response)
    assert summary["contract_valid"] is False and summary["pixel_budget"] is None
    assert "PRIVATE" not in json.dumps(summary)
