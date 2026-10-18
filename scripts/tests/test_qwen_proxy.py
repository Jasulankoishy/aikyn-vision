"""Synthetic local stdio/HTTP tests only: no bank media, model, GPU, or network API."""
import importlib
import json
import os
from pathlib import Path
import sys
import time

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qwen_engine import QwenEngine, QwenWorkerError
import qwen_engine


def test_qwen_paths_are_repository_relative():
    assert qwen_engine.WORKSPACE == Path(__file__).resolve().parents[2]


def test_default_service_keeps_legacy_engine(monkeypatch, tmp_path):
    from types import SimpleNamespace
    monkeypatch.delenv("ANALYZER_BACKEND", raising=False)
    module = importlib.reload(importlib.import_module("service"))
    monkeypatch.setattr(module, "TMP_DIR", tmp_path)
    closed = []
    class Legacy:
        def analyze(self, path, budget):
            return {"verdict": "no_violation", "violations": []}
        def close(self):
            closed.append(True)
    monkeypatch.setitem(sys.modules, "engine", SimpleNamespace(Engine=Legacy))
    monkeypatch.setattr(module, "QwenEngine", lambda: pytest.fail("Default must not load Qwen"))
    video = tmp_path / "legacy.mov"
    video.write_bytes(b"synthetic")
    with TestClient(module.app) as client:
        assert module.BACKEND == "legacy"
        assert client.get("/health").json() == {"status": "ok", "model_loaded": True}
        assert client.post("/analyze", json={"path": str(video)}).json() == {"verdict": "no_violation", "violations": []}
    assert closed == [True]


STUB = '''import json, sys, time
from pathlib import Path
print(json.dumps({"state":"ready","model":"Qwen3-VL-2B-Instruct","new_training":False}),flush=True)
for line in sys.stdin:
    req=json.loads(line)
    name=Path(req["path"]).name
    if "timeout" in name:
        time.sleep(5)
    if "crash" in name:
        sys.exit(9)
    if "wrong-id" in name:
        req["id"]="wrong"
    if "incomplete" in name:
        out={"id":req["id"],"ok":False,"error":{"code":"incomplete_analysis","message":"RAW_PRIVATE_MODEL_TEXT"}}
    else:
        out={"id":req["id"],"ok":True,"result":{"verdict":"no_violation","violations":[],
             "analysis":{"model":"Qwen3-VL-2B-Instruct","experimental":True,"new_training":False,"findings_status":"requires_review",
                         "complete":True,"timeline_covered":True,"windows_done":1,"windows_total":1}}}
        if "partial" in name:
            out["result"]["analysis"]["windows_done"]=0
    print(json.dumps(out),flush=True)
'''


@pytest.fixture
def engine(tmp_path):
    worker = tmp_path / "synthetic_worker.py"
    worker.write_text(STUB, encoding="utf-8")
    instance = QwenEngine(python=sys.executable, worker=worker, runtime=tmp_path / "runtime",
                          startup_timeout=5, request_reserve_sec=0)
    try:
        yield instance
    finally:
        instance.close()


def wait_ready(engine, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if engine.ready:
            return True
        time.sleep(.02)
    return False


def test_persistent_worker_receives_unicode_paths_without_new_training(engine, tmp_path):
    pid = engine._process.pid
    for name in ("касса.mov", "другое.mov"):
        result = engine.analyze(tmp_path / name, 2)
        assert result["analysis"]["new_training"] is False
        assert result["verdict"] == "no_violation"
        assert engine._process.pid == pid
    assert engine.health()["model_loaded"] is True


def test_incomplete_response_never_becomes_no_violation(engine, tmp_path):
    with pytest.raises(QwenWorkerError) as caught:
        engine.analyze(tmp_path / "incomplete.mov", 2)
    assert caught.value.code == "incomplete_analysis"
    assert "RAW_PRIVATE" not in str(caught.value)
    assert engine.ready


def test_partial_success_cannot_be_reported_as_no_violation(engine, tmp_path):
    with pytest.raises(QwenWorkerError) as caught:
        engine.analyze(tmp_path / "partial.mov", 2)
    assert caught.value.code == "incomplete_analysis"


def test_timeout_kills_and_restarts_only_its_worker(engine, tmp_path):
    old = engine._process
    engine._last_start -= 5
    with pytest.raises(TimeoutError):
        engine.analyze(tmp_path / "timeout.mov", .2)
    assert old.poll() is not None
    assert wait_ready(engine)
    assert engine._process.pid != old.pid
    assert engine.analyze(tmp_path / "fine.mov", 2)["violations"] == []


@pytest.mark.parametrize("name", ["crash.mov", "wrong-id.mov"])
def test_worker_death_and_unmatched_result_fail_then_restart(engine, tmp_path, name):
    old = engine._process
    engine._last_start -= 5
    with pytest.raises(QwenWorkerError, match="worker"):
        engine.analyze(tmp_path / name, 2)
    assert old.poll() is not None
    assert wait_ready(engine)
    assert engine._process.pid != old.pid


def test_close_stops_worker_and_reports_not_ready(engine):
    old = engine._process
    engine.close()
    assert old.poll() is not None
    assert engine.health()["model_loaded"] is False


def test_startup_requires_base_model_ready_confirmation(tmp_path):
    worker = tmp_path / "bad_worker.py"
    worker.write_text('print(\'{"state":"ready","model":"wrong","new_training":true}\',flush=True)', encoding="utf-8")
    with pytest.raises(QwenWorkerError, match="readiness"):
        QwenEngine(python=sys.executable, worker=worker, runtime=tmp_path / "runtime", startup_timeout=2)


def test_verified_4b_worker_readiness_and_matching_result_are_accepted(tmp_path):
    worker = tmp_path / "synthetic_4b_worker.py"
    worker.write_text(STUB.replace("Qwen3-VL-2B-Instruct", "Qwen3-VL-4B-Instruct"), encoding="utf-8")
    instance = QwenEngine(python=sys.executable, worker=worker, runtime=tmp_path / "runtime",
                          startup_timeout=5, request_reserve_sec=0)
    try:
        assert instance.health()["model"] == "Qwen3-VL-4B-Instruct"
        assert instance.analyze(tmp_path / "synthetic.mov", 2)["analysis"]["model"] == "Qwen3-VL-4B-Instruct"
    finally:
        instance.close()


@pytest.mark.parametrize("missing_model", [False, True])
def test_result_must_identify_the_model_that_confirmed_readiness(tmp_path, missing_model):
    worker = tmp_path / "mismatched_model_worker.py"
    source = STUB.replace("Qwen3-VL-2B-Instruct", "Qwen3-VL-4B-Instruct", 1)
    if missing_model:
        source = source.replace('"model":"Qwen3-VL-2B-Instruct",', '')
    worker.write_text(source, encoding="utf-8")
    instance = QwenEngine(python=sys.executable, worker=worker, runtime=tmp_path / "runtime",
                          startup_timeout=5, request_reserve_sec=0)
    try:
        with pytest.raises(QwenWorkerError, match="contract") as caught:
            instance.analyze(tmp_path / "synthetic.mov", 2)
        assert caught.value.code == "worker_unavailable"
    finally:
        instance.close()


@pytest.mark.parametrize("model", ["Qwen3-VL-8B-Instruct", "remote-model", None, ["Qwen3-VL-2B-Instruct"]])
def test_unknown_or_malformed_ready_model_is_rejected(tmp_path, model):
    worker = tmp_path / "unknown_model_worker.py"
    payload = json.dumps({"state": "ready", "model": model, "new_training": False})
    worker.write_text(f"print({payload!r},flush=True)", encoding="utf-8")
    with pytest.raises(QwenWorkerError, match="readiness"):
        QwenEngine(python=sys.executable, worker=worker, runtime=tmp_path / "runtime", startup_timeout=2)


@pytest.fixture
def service(monkeypatch, tmp_path):
    monkeypatch.setenv("ANALYZER_BACKEND", "qwen")
    module = importlib.import_module("service")
    module = importlib.reload(module)
    monkeypatch.setattr(module, "TMP_DIR", tmp_path)
    instances = []

    class Fake:
        closed = False

        def __init__(self):
            instances.append(self)

        def health(self):
            return {"model_loaded": not self.closed, "new_training": False, "experimental": True}

        def analyze(self, path, budget):
            assert 0 < budget <= 230
            if "incomplete" in Path(path).name:
                raise QwenWorkerError("incomplete_analysis", "No complete analysis")
            if "timeout" in Path(path).name:
                raise TimeoutError()
            return {"verdict": "no_violation", "violations": [],
                    "analysis": {"new_training": False, "experimental": True}}

        def close(self):
            self.closed = True

    monkeypatch.setattr(module, "QwenEngine", Fake)
    return module, instances


def test_http_health_input_boundary_and_lifespan_cleanup(service, tmp_path):
    module, instances = service
    video = tmp_path / "sample.mov"
    video.write_bytes(b"synthetic-only")
    with TestClient(module.app) as client:
        assert client.get("/health").json()["model_loaded"] is True
        assert client.post("/analyze", json={"path": str(video)}).status_code == 200
        assert client.post("/analyze", json={"path": str(video), "extra": True}).status_code == 422
        assert client.post("/analyze", json={"path": str(tmp_path.parent / "outside.mov")}).status_code == 400
        assert client.post("/analyze", json={"path": str(tmp_path / "missing.mov")}).status_code == 400
    assert instances[0].closed and "engine" not in module._state


def test_http_incomplete_and_timeout_have_no_verdict(service, tmp_path):
    module, _ = service
    with TestClient(module.app) as client:
        for name, expected in (("incomplete.mov", 422), ("timeout.mov", 504)):
            path = tmp_path / name
            path.write_bytes(b"synthetic-only")
            response = client.post("/analyze", json={"path": str(path)})
            assert response.status_code == expected
            assert "verdict" not in response.json()


def test_service_gate_timeout_does_not_wait_unbounded(service, tmp_path, monkeypatch):
    module, _ = service
    monkeypatch.setattr(module, "BUDGET_SEC", .01)
    path = tmp_path / "sample.mov"
    path.write_bytes(b"synthetic-only")
    with TestClient(module.app) as client:
        module._gate.acquire()
        try:
            before = time.monotonic()
            response = client.post("/analyze", json={"path": str(path)})
            assert response.status_code == 504
            assert time.monotonic() - before < 1
        finally:
            module._gate.release()
