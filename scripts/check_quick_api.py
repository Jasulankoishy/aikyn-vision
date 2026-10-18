"""Exercise the live local upload API without printing media, model text, or API keys."""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import re
import secrets
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

from qwen_engine import ALLOWED_MODELS

WORKSPACE = Path(__file__).resolve().parents[1]
MAX_RESPONSE_BYTES = 50 * 1024 * 1024


def local_address(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise ValueError("Only a plain HTTP loopback API address is allowed")
    return parsed.hostname, parsed.port or 80


def read_key(path):
    key = path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,}", key):
        raise ValueError("Private API key is absent or malformed")
    return key


def read_json_response(response):
    payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError("API response exceeds the local validation size limit")
    try:
        value = json.loads(payload)
    except ValueError as error:
        raise ValueError("API response is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("API response is not a JSON object")
    return response.status, value


def request_json(address, key, method, path, timeout):
    connection = http.client.HTTPConnection(*address, timeout=timeout)
    try:
        connection.request(method, path, headers={"X-API-Key": key, "Accept": "application/json"})
        return read_json_response(connection.getresponse())
    finally:
        connection.close()


def upload(address, key, video, deadline):
    """Stream the file only to the approved local API, rather than loading it in RAM."""
    boundary = "----ForteLocal" + secrets.token_hex(16)
    before = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"video.mov\"\r\n"
              "Content-Type: video/quicktime\r\n\r\n").encode("ascii")
    after = f"\r\n--{boundary}--\r\n".encode("ascii")
    connection = http.client.HTTPConnection(*address, timeout=min(60, max(.1, deadline - time.monotonic())))
    digest = hashlib.sha256()
    try:
        connection.putrequest("POST", "/api/v1/analyze")
        connection.putheader("X-API-Key", key)
        connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        connection.putheader("Content-Length", str(len(before) + video.stat().st_size + len(after)))
        connection.endheaders()
        connection.send(before)
        with video.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Local API verification deadline reached during upload")
                connection.send(chunk)
                digest.update(chunk)
        connection.send(after)
        return (*read_json_response(connection.getresponse()), digest.hexdigest())
    finally:
        connection.close()


def result_summary(result):
    """Deliberately exclude every model description, rule text, image and key."""
    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
    events = result.get("violations") if isinstance(result.get("violations"), list) else []
    model = analysis.get("model")
    model_valid = type(model) is str and model in ALLOWED_MODELS
    pixel_cap = analysis.get("pixel_cap")
    cap_valid = pixel_cap is None or (type(pixel_cap) is int and 0 < pixel_cap <= 8_388_608)
    pixel_budget = analysis.get("pixel_budget")
    budget_valid = "pixel_budget" not in analysis or (type(pixel_budget) is int and 524_288 <= pixel_budget <= 8_388_608)
    complete = (analysis.get("complete") is True and analysis.get("timeline_covered") is True
                and type(analysis.get("windows_done")) is int
                and type(analysis.get("windows_total")) is int
                and analysis["windows_done"] == analysis["windows_total"] > 0)
    valid = (result.get("status") == "done" and result.get("mode") == "real"
             and result.get("verdict") in {"violation", "no_violation"}
             and (result["verdict"] == "violation") == bool(events)
             and analysis.get("experimental") is True and analysis.get("new_training") is False
             and analysis.get("findings_status") == "requires_review" and complete and model_valid and cap_valid and budget_valid)
    for event in events:
        if not isinstance(event, dict):
            valid = False
            continue
        frames = event.get("evidence_frames")
        if not isinstance(frames, list) or not 1 <= len(frames) <= 3:
            valid = False
    return {
        "status": result.get("status") if result.get("status") in {"processing", "done", "failed"} else "invalid",
        "contract_valid": valid,
        "model": model if model_valid else None,
        "pixel_cap": pixel_cap if cap_valid else None,
        "pixel_budget": pixel_budget if budget_valid else None,
        "verdict": result.get("verdict") if result.get("verdict") in {"violation", "no_violation"} else None,
        "candidate_events": len(events),
        "evidence_frames": sum(len(event.get("evidence_frames", [])) for event in events
                               if isinstance(event, dict) and isinstance(event.get("evidence_frames"), list)),
        "complete": complete,
        "windows_done": analysis.get("windows_done") if type(analysis.get("windows_done")) is int else None,
        "windows_total": analysis.get("windows_total") if type(analysis.get("windows_total")) is int else None,
        "new_training": analysis.get("new_training") if type(analysis.get("new_training")) is bool else None,
        "experimental": analysis.get("experimental") if type(analysis.get("experimental")) is bool else None,
        "review_questions": len(analysis.get("review_questions", []))
        if isinstance(analysis.get("review_questions"), list) else 0,
    }


def save_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def check(args):
    address = local_address(args.api_url)
    video = args.video.resolve()
    if not video.is_file() or video.suffix.lower() != ".mov" or not video.stat().st_size:
        raise ValueError("Select an existing nonempty local MOV file")
    if not 1 <= args.timeout <= 240:
        raise ValueError("Validation timeout must be between 1 and 240 seconds")
    key = read_key(args.key_file)
    output = args.output or WORKSPACE / "outputs" / (
        "quick-local-api-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8])
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / ".gitignore").write_text("*\n", encoding="ascii")
    (output / "PRIVATE.txt").write_text(
        "LOCAL ONLY: response.json may contain bank evidence frames. Do not publish or send to cloud tools.\n",
        encoding="ascii")
    started = time.monotonic()
    deadline = started + args.timeout
    summary = {"output_dir": str(output), "new_training": False, "status": "starting", "contract_valid": False}
    try:
        status, ready = request_json(address, key, "GET", "/readyz", min(10, args.timeout))
        save_json(output / "readiness.json", ready)
        if status != 200 or ready.get("ready") is not True or ready.get("mode") != "real":
            summary.update(status="not_ready", http_status=status)
            return summary
        status, accepted, digest = upload(address, key, video, deadline)
        save_json(output / "accepted.json", accepted)
        save_json(output / "input.json", {"path": str(video), "bytes": video.stat().st_size, "sha256": digest})
        if status != 202 or not isinstance(accepted.get("job_id"), str):
            summary.update(status="upload_rejected", http_status=status)
            return summary
        job_id = accepted["job_id"]
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", job_id):
            raise ValueError("API returned an invalid job identifier")
        summary["job_id"] = job_id
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            status, body = request_json(address, key, "GET", f"/api/v1/jobs/{job_id}", min(10, remaining))
            save_json(output / "response.json", body)
            if status != 200:
                summary.update(status="poll_failed", http_status=status)
                return summary
            if body.get("status") == "done":
                summary.update(result_summary(body))
                if body.get("job_id") != job_id:
                    summary.update(status="job_mismatch", contract_valid=False)
                return summary
            if body.get("status") == "failed":
                error = body.get("error", {})
                code = error.get("code") if isinstance(error, dict) else None
                summary.update(status="failed", error_code=code if isinstance(code, str)
                               and re.fullmatch(r"[A-Za-z0-9_]{1,64}", code) else "unspecified")
                return summary
            if body.get("status") != "processing":
                summary.update(status="invalid_status")
                return summary
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        summary.update(status="wait_timeout")
        return summary
    except Exception as error:
        # Never print raw exception messages that might contain request/response data.
        summary.update(status="client_error", error_type=type(error).__name__)
        return summary
    finally:
        summary["elapsed_sec"] = round(time.monotonic() - started, 3)
        save_json(output / "summary.json", summary)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8080")
    parser.add_argument("--key-file", type=Path, default=WORKSPACE / ".runtime/quick-local/api-key.txt")
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        summary = check(args)
    except (ValueError, OSError) as error:
        summary = {"status": "preflight_failed", "contract_valid": False, "error_type": type(error).__name__}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("contract_valid") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
