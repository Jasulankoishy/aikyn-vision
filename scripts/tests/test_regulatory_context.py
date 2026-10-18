"""Synthetic contract tests: legal context must not alter the model's findings."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from regulatory_context import CATEGORIES, enrich_regulatory_context


def sample(category):
    return {
        "verdict": "violation",
        "violations": [{
            "category_id": category, "type": "Синтетическое событие",
            "description": "Тестовое наблюдение.",
            "start_sec": 1.0, "timecode_sec": 2.0, "end_sec": 3.0,
            "status": "possible_sign_requires_review", "confidence": 0.6,
            "evidence_frames": [{"timestamp_sec": 2.0, "image_base64": "synthetic"}],
            "rule": {"id": "invented", "section": "Статья, придуманная моделью"},
        }],
        "analysis": {"findings_status": "requires_review", "complete": True},
    }


@pytest.mark.parametrize("category", ["c01", "c02", "c06"])
def test_public_reference_is_conditional_and_visible_in_existing_fields(category):
    result = enrich_regulatory_context(sample(category))
    event = result["violations"][0]
    assert set(event["rule"]) == {"id", "document", "section", "source_url"}
    assert event["rule"]["source_url"] == "https://adilet.zan.kz/rus/docs/V1900019680"
    assert "применимость не установлена" in event["rule"]["section"]
    assert "ранее принят" in event["description"]
    assert "только сейфом" in event["description"]
    assert event["regulatory_context"]["legal_violation_established"] is False


@pytest.mark.parametrize("category", ["c07", "c08", "c11", "c12", "unknown", None])
def test_no_article_is_invented_for_internal_or_unknown_rule(category):
    event = enrich_regulatory_context(sample(category))["violations"][0]
    assert event["rule"] is None
    assert "Юридическое нарушение автоматически не установлено" in event["description"]
    assert "Статья, придуманная моделью" not in event["description"]


def test_does_not_mutate_or_reclassify_candidates_and_is_idempotent():
    source = sample("c12")
    before = deepcopy(source)
    result = enrich_regulatory_context(source)
    assert source == before
    for key in ("category_id", "type", "start_sec", "timecode_sec", "end_sec",
                "status", "confidence", "evidence_frames"):
        assert result["violations"][0][key] == source["violations"][0][key]
    assert result["verdict"] == source["verdict"]
    assert len(result["violations"]) == len(source["violations"])
    assert enrich_regulatory_context(result) == result


def test_empty_result_remains_empty_and_questions_are_unchanged():
    source = {"verdict": "no_violation", "violations": [],
              "analysis": {"review_questions": [{"category_id": "c04", "status": "requires_review"}]}}
    result = enrich_regulatory_context(source)
    assert result["verdict"] == "no_violation"
    assert result["violations"] == []
    assert result["analysis"]["review_questions"] == source["analysis"]["review_questions"]


@pytest.mark.parametrize("category", [f"c{n:02}" for n in range(1, 15)])
def test_every_team_category_has_explanation_without_asserting_a_legal_violation(category):
    assert category in CATEGORIES
    source = sample(category)
    result = enrich_regulatory_context(source)
    event = result["violations"][0]
    assert CATEGORIES[category]["conditions"] in event["description"]
    assert event["regulatory_context"]["applicability_established"] is False
    assert event["regulatory_context"]["legal_violation_established"] is False
    assert event["timecode_sec"] == source["violations"][0]["timecode_sec"]
    if event["rule"]:
        assert "применимость не установлена" in event["rule"]["section"]
    assert enrich_regulatory_context(result) == result
