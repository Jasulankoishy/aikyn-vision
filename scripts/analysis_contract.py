"""Fail closed on broken evidence contracts; this does not verify model perception."""
import math


VERSION = "evidence-contract-v1"
NATIVE_KINDS = {
    "c01": "old_cash_at_client_change", "c02": "cash_mixed",
    "c03": "cash_receipt_without_visible_count",
    "c04": "cash_receipt_without_visible_identity_check",
    "c05": "cash_counted_after_client_departure",
    "c06": "cash_unattended", "c07": "package_left_unattended",
    "c08": "safe_open_when_left",
    "c09": "safe_key_left_in_lock",
    "c10": "documents_or_seals_left_unattended",
    "c11": "screen_unlocked_when_left", "c12": "room_door_left_open",
    "c13": "personal_items_in_cash_area", "c14": "rejected_banknotes_recombined",
}


class AnalysisContractError(ValueError):
    pass


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def enforce_evidence_contract(result):
    """Validate before publication. Never turn a rejected result into an empty one.

    `verdict` is retained for the existing website protocol and only indicates
    candidate presence. Neither value establishes compliance or a violation.
    """
    analysis, events = result["analysis"], result["violations"]
    if (analysis.get("findings_status") != "requires_review"
            or analysis.get("compliance_established") not in (None, False)
            or analysis.get("human_verified") not in (None, False)):
        raise AnalysisContractError("Automated findings cannot claim verified conclusions")
    native = str(analysis.get("implementation", "")).startswith("native-sequence-refine-")
    progress = analysis.get("candidate_review")
    if native or progress is not None:
        if not isinstance(progress, dict):
            raise AnalysisContractError("Candidate review completion is missing")
        counts = [progress.get(k) for k in ("done", "total", "remaining")]
        if (any(type(n) is not int or n < 0 for n in counts)
                or progress.get("status") != "complete"
                or counts[0] != counts[1] or counts[2] != 0):
            raise AnalysisContractError("Candidate review is incomplete")
    source_sampling = analysis.get("source_sampling")
    source = source_sampling.get("sampled_timestamps", []) if isinstance(source_sampling, dict) else []
    if native and (not isinstance(source, list) or not source or any(not finite(t) for t in source)):
        raise AnalysisContractError("Source frame timestamps are missing")
    duration = analysis.get("duration_sec")
    refinements = analysis.get("refinements", [])
    if native:
        if (not isinstance(refinements, list) or len(refinements) != progress["total"]
                or any(not isinstance(r, dict) or r.get("status") not in
                       {"observed", "not_observed", "unclear", "not_localized"} for r in refinements)):
            raise AnalysisContractError("Completed candidate reviews are missing")
        for review in refinements:
            if review["status"] != "observed":
                continue
            if not any(isinstance(e, dict) and NATIVE_KINDS.get(e.get("category_id")) == review.get("kind")
                       and e.get("start_sec") == review.get("start_sec")
                       and e.get("end_sec") == review.get("end_sec") for e in events):
                raise AnalysisContractError("An observed candidate was lost from the result")
    for event in events:
        if (not isinstance(event, dict) or event.get("status") != "possible_sign_requires_review"
                or event.get("human_verified") not in (None, False)):
            raise AnalysisContractError("A model candidate cannot be a confirmed violation")
        start, point, end = [event.get(k) for k in ("start_sec", "timecode_sec", "end_sec")]
        if (not all(finite(v) for v in (start, point, end, duration))
                or not 0 <= start <= point <= end <= duration):
            raise AnalysisContractError("Finding timestamps are invalid")
        frames = event.get("evidence_frames")
        if not isinstance(frames, list) or not frames:
            raise AnalysisContractError("A finding has no source evidence")
        for frame in frames:
            if not isinstance(frame, dict):
                raise AnalysisContractError("Source evidence is invalid")
            timestamp, payload = frame.get("timestamp_sec"), frame.get("image_base64")
            if (not finite(timestamp) or not start <= timestamp <= end
                    or not isinstance(payload, str) or not payload
                    or (native and timestamp not in source)):
                raise AnalysisContractError("Source evidence is invalid")
        if native:
            kind = NATIVE_KINDS.get(event.get("category_id"))
            supported = False
            for review in refinements:
                if (kind is None or review.get("kind") != kind or review["status"] != "observed"
                        or review.get("start_sec") != start or review.get("end_sec") != end):
                    continue
                sampling = review.get("sampling")
                times = sampling.get("sampled_timestamps") if isinstance(sampling, dict) else None
                if (isinstance(times, list) and times and all(finite(t) and t in source for t in times)
                        and start in times and end in times
                        and all(frame["timestamp_sec"] in times for frame in frames)):
                    supported = True
                    break
            if not supported:
                raise AnalysisContractError("A finding lacks a matching reviewed source interval")
    # Set these only after the complete result passes validation.
    analysis.update(reporting_policy=VERSION, compliance_established=False,
                    human_verified=False, verdict_semantics="candidate_presence_only",
                    result_status=("possible_sign_requires_review" if events else
                                   "review_required" if analysis.get("review_questions") or analysis.get("uncertain_windows")
                                   else "no_signals_found"))
    for event in events:
        event["human_verified"] = False
    return result
