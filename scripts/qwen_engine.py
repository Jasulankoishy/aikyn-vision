"""Local stdio bridge: HTTP stays in the small API venv, Qwen in the offline GPU venv."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from uuid import uuid4

WORKSPACE = Path(__file__).resolve().parents[1]
MAX_LINE_BYTES = 32 * 1024 * 1024
ALLOWED_MODELS = frozenset({"Qwen3-VL-2B-Instruct", "Qwen3-VL-4B-Instruct"})


class QwenWorkerError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _hidden_process_options():
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


class QwenEngine:
    """One persistent worker, serialized requests, bounded waits and safe restarts."""

    def __init__(self, *, python=None, worker=None, runtime=None, startup_timeout=None,
                 request_reserve_sec=5, popen=subprocess.Popen):
        self.python = Path(python or os.environ.get("QWEN_PYTHON", WORKSPACE / ("training/.venv/Scripts/python.exe" if os.name == "nt" else "training/.venv/bin/python")))
        self.worker = Path(worker or os.environ.get("QWEN_WORKER", WORKSPACE / "training/qwen/quick_inference.py"))
        self.runtime = Path(runtime or os.environ.get("QUICK_RUNTIME", WORKSPACE / ".runtime/quick-local"))
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.startup_timeout = float(startup_timeout if startup_timeout is not None
                                     else os.environ.get("QWEN_STARTUP_TIMEOUT_SEC", "180"))
        if not 0 < self.startup_timeout <= 600:
            raise ValueError("QWEN_STARTUP_TIMEOUT_SEC must be in (0, 600]")
        self.request_reserve_sec = float(request_reserve_sec)
        self._popen = popen
        self._lock = threading.Lock()
        self._restart_lock = threading.Lock()
        self._process = None
        self._messages = None
        self._ready = False
        self._closed = False
        self._last_start = 0.0
        self._model = None
        self._stderr = None
        self._restart_thread = None
        with self._lock:
            self._start(time.monotonic() + self.startup_timeout)

    @property
    def ready(self):
        return bool(self._ready and self._process is not None and self._process.poll() is None and not self._closed)

    def health(self):
        if not self.ready and not self._closed:
            self._schedule_restart()
        return {"model_loaded": self.ready, "model": self._model,
                "experimental": True, "new_training": False, "backend": "qwen_local"}

    @staticmethod
    def _read_stdout(process, messages):
        try:
            while True:
                line = process.stdout.readline(MAX_LINE_BYTES + 1)
                if not line:
                    messages.put_nowait((False, "worker_closed_stdout"))
                    return
                if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
                    messages.put_nowait((False, "worker_output_too_large_or_incomplete"))
                    return
                try:
                    payload = json.loads(line)
                except (ValueError, UnicodeError):
                    messages.put_nowait((False, "worker_output_is_not_json"))
                    return
                if not isinstance(payload, dict):
                    messages.put_nowait((False, "worker_output_is_not_an_object"))
                    return
                messages.put_nowait((True, payload))
        except (OSError, ValueError, queue.Full):
            try:
                messages.put_nowait((False, "worker_stdout_failed"))
            except queue.Full:
                pass

    def _receive(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Local Qwen worker exceeded its deadline")
        try:
            okay, payload = self._messages.get(timeout=remaining)
        except queue.Empty as error:
            raise TimeoutError("Local Qwen worker exceeded its deadline") from error
        if not okay:
            raise QwenWorkerError("worker_unavailable", "Local model worker stopped or returned an invalid response")
        return payload

    def _start(self, deadline):
        if self._closed:
            raise QwenWorkerError("worker_unavailable", "Local model worker is closed")
        if not self.python.is_file() or not self.worker.is_file():
            raise QwenWorkerError("worker_unavailable", "Local Qwen runtime or worker script is missing")
        self._stop_process()
        self._last_start = time.monotonic()
        self._stderr = (self.runtime / "qwen-worker.stderr.log").open("ab")
        env = os.environ.copy()
        env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1", HF_HUB_OFFLINE="1",
                   TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", WANDB_DISABLED="true")
        try:
            self._process = self._popen(
                [str(self.python), "-u", str(self.worker), "--worker"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr,
                cwd=WORKSPACE, env=env, **_hidden_process_options())
            self._messages = queue.Queue(maxsize=4)
            threading.Thread(target=self._read_stdout, args=(self._process, self._messages),
                             name="qwen-stdout", daemon=True).start()
            payload = self._receive(min(deadline, time.monotonic() + self.startup_timeout))
            if (payload.get("state") != "ready" or payload.get("new_training") is not False
                    or type(payload.get("model")) is not str or payload["model"] not in ALLOWED_MODELS):
                raise QwenWorkerError("worker_unavailable", "Local worker did not confirm base-model readiness")
            self._model = payload["model"]
            self._ready = True
        except Exception:
            self._stop_process()
            raise

    def _stop_process(self):
        self._ready = False
        process, self._process = self._process, None
        if process is not None:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()
        if self._stderr is not None:
            self._stderr.close()
            self._stderr = None

    def _schedule_restart(self):
        if self._closed or self.ready or (self._restart_thread and self._restart_thread.is_alive()):
            return
        if not self._restart_lock.acquire(blocking=False):
            return
        try:
            if self._closed or self.ready or (self._restart_thread and self._restart_thread.is_alive()):
                return

            def restart():
                # Prevent rapid failed restarts (e.g. another local tool owns the GPU lock).
                delay = max(0, 5 - (time.monotonic() - self._last_start))
                if delay:
                    time.sleep(delay)
                with self._lock:
                    if self._closed or self.ready:
                        return
                    try:
                        self._start(time.monotonic() + self.startup_timeout)
                    except Exception:
                        # Detailed model logs remain local. A later health request can retry.
                        self._ready = False

            self._restart_thread = threading.Thread(target=restart, name="qwen-restart", daemon=True)
            self._restart_thread.start()
        finally:
            self._restart_lock.release()

    def analyze(self, video_path, budget_sec=230.0):
        deadline = time.monotonic() + min(float(budget_sec), 230.0)
        if not self._lock.acquire(timeout=max(0, deadline - time.monotonic())):
            raise TimeoutError("Local model is busy")
        broken = False
        try:
            if not self.ready:
                self._start(deadline)
            remaining = deadline - time.monotonic()
            worker_budget = min(220.0, remaining - self.request_reserve_sec)
            if worker_budget <= 0:
                raise TimeoutError("No time remains for local model analysis")
            request_id = str(uuid4())
            request = {"id": request_id, "path": str(Path(video_path).resolve()), "budget_sec": worker_budget}
            self._process.stdin.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
            self._process.stdin.flush()
            response = self._receive(deadline)
            if response.get("id") != request_id or type(response.get("ok")) is not bool:
                raise QwenWorkerError("worker_unavailable", "Local worker returned an unmatched response")
            if not response["ok"]:
                error = response.get("error", {})
                code = error.get("code") if isinstance(error, dict) else "analysis_failed"
                if code in {"analysis_timeout", "timeout"}:
                    raise TimeoutError("Local analysis did not finish within the time limit")
                if code == "incomplete_analysis":
                    raise QwenWorkerError(code, "The model could not analyze the entire video; no verdict was issued")
                raise QwenWorkerError("analysis_failed", "Local model could not complete this analysis")
            result = response.get("result")
            if not isinstance(result, dict) or result.get("verdict") not in {"violation", "no_violation"}:
                raise QwenWorkerError("worker_unavailable", "Local worker returned an invalid result")
            events, analysis = result.get("violations"), result.get("analysis")
            if (not isinstance(events, list) or (result["verdict"] == "violation") != bool(events)
                    or not isinstance(analysis, dict) or analysis.get("experimental") is not True
                    or analysis.get("new_training") is not False or analysis.get("model") != self._model):
                raise QwenWorkerError("worker_unavailable", "Local worker result does not match the experimental contract")
            done, total = analysis.get("windows_done"), analysis.get("windows_total")
            if (analysis.get("complete") is not True or analysis.get("timeline_covered") is not True
                    or type(done) is not int or type(total) is not int or done != total or total <= 0):
                raise QwenWorkerError("incomplete_analysis", "The model could not analyze the entire video; no verdict was issued")
            return result
        except (TimeoutError, BrokenPipeError, OSError):
            broken = True
            self._stop_process()
            raise
        except QwenWorkerError as error:
            if error.code == "worker_unavailable":
                broken = True
                self._stop_process()
            raise
        finally:
            self._lock.release()
            if broken:
                self._schedule_restart()

    def close(self):
        self._closed = True
        with self._lock:
            self._stop_process()
