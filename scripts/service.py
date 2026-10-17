"""
Internal FastAPI service: keeps the models in memory so each video skips the model-loading cost.
Run:  uvicorn service:app --host 127.0.0.1 --port 8001      (ONE worker: models live in this process)
Bind to 127.0.0.1 only - it must not be reachable from outside; the Java backend is the public API.
"""
import os
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from common import log
from engine import Engine

BUDGET_SEC = float(os.environ.get("ANALYZE_BUDGET_SEC", "230"))     # keep below the Java timeout
MAX_CONCURRENT = int(os.environ.get("ANALYZE_CONCURRENCY", "1"))    # heavy CPU work: keep small
TMP_DIR = Path(tempfile.gettempdir()).resolve()

_gate = threading.Semaphore(MAX_CONCURRENT)
_state = {}


@asynccontextmanager
async def lifespan(app):
    _state["engine"] = Engine()      # load models once, at startup
    yield
    _state.clear()


app = FastAPI(lifespan=lifespan)


class AnalyzeRequest(BaseModel):
    path: str    # absolute path of the uploaded .mov (same machine as the Java backend)


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": "engine" in _state}


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    t0 = time.time()
    p = Path(req.path).resolve()
    # Only accept files inside the temp dir, so the service can't be used to read arbitrary files
    if TMP_DIR not in p.parents or p.suffix.lower() != ".mov" or not p.is_file():
        raise HTTPException(status_code=400, detail="invalid path")

    with _gate:                                   # waits here if other videos are being analysed
        remaining = BUDGET_SEC - (time.time() - t0)
        if remaining <= 0 or not p.is_file():     # waited too long, or Java already gave up and deleted it
            raise HTTPException(status_code=504, detail="time budget exceeded")
        try:
            return _state["engine"].analyze(str(p), remaining)
        except TimeoutError:
            raise HTTPException(status_code=504, detail="time budget exceeded")
        except Exception as e:                    # details stay in this log, not in the response
            log(f"analysis failed for {p.name}: {e!r}")
            raise HTTPException(status_code=500, detail="analysis failed")
