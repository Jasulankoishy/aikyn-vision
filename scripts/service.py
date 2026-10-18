"""
Internal FastAPI service: keeps the models in memory so each video skips the model-loading cost.
Run:  uvicorn service:app --host 127.0.0.1 --port 8001      (ONE worker: models live in this process)
Bind to 127.0.0.1 only - it must not be reachable from outside; the Java backend is the public API.
"""
import os
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from qwen_engine import QwenEngine, QwenWorkerError

BUDGET_SEC = float(os.environ.get("ANALYZE_BUDGET_SEC", "230"))     # keep below the Java timeout
BUDGET_SEC = min(230.0, BUDGET_SEC)
MAX_CONCURRENT = int(os.environ.get("ANALYZE_CONCURRENCY", "1"))    # one GPU worker
BACKEND = os.environ.get("ANALYZER_BACKEND", "legacy").lower()
if BUDGET_SEC <= 0 or MAX_CONCURRENT < 1 or BACKEND not in {"legacy", "qwen"}:
    raise ValueError("Invalid analysis service configuration")
TMP_DIR = Path(tempfile.gettempdir()).resolve()

_gate = threading.Semaphore(MAX_CONCURRENT)
_state = {}


@asynccontextmanager
async def lifespan(app):
    if BACKEND == "qwen":
        _state["engine"] = QwenEngine()
    else:
        from engine import Engine  # Never import dummy/CLIP model code in Qwen mode.
        _state["engine"] = Engine()
    try:
        yield
    finally:
        engine = _state.pop("engine", None)
        if engine is not None and hasattr(engine, "close"):
            engine.close()


app = FastAPI(lifespan=lifespan)


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str    # absolute path of the uploaded .mov (same machine as the Java backend)


@app.get("/health")
def health():
    engine = _state.get("engine")
    details = engine.health() if engine is not None and hasattr(engine, "health") else {"model_loaded": engine is not None}
    return {"status": "ok" if details["model_loaded"] else "starting", **details}


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    t0 = time.monotonic()
    p = Path(req.path).resolve()
    # Only accept files inside the temp dir, so the service can't be used to read arbitrary files
    if TMP_DIR not in p.parents or p.suffix.lower() != ".mov" or not p.is_file():
        raise HTTPException(status_code=400, detail="invalid path")

    if not _gate.acquire(timeout=BUDGET_SEC):
        raise HTTPException(status_code=504, detail="time budget exceeded while waiting for model")
    try:
        remaining = BUDGET_SEC - (time.monotonic() - t0)
        if remaining <= 0 or not p.is_file():     # waited too long, or Java already gave up and deleted it
            raise HTTPException(status_code=504, detail="time budget exceeded")
        try:
            return _state["engine"].analyze(str(p), remaining)
        except TimeoutError:
            raise HTTPException(status_code=504, detail="time budget exceeded")
        except QwenWorkerError as error:
            status = 422 if error.code == "incomplete_analysis" else 503 if error.code == "worker_unavailable" else 500
            return JSONResponse(status_code=status, content={"error": {"code": error.code, "message": str(error)}})
        except Exception as e:                    # details stay in this log, not in the response
            print(f"analysis failed for {p.name}: {type(e).__name__}", file=sys.stderr, flush=True)
            raise HTTPException(status_code=500, detail="analysis failed")
    finally:
        _gate.release()
