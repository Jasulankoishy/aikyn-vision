"""Start/inspect/stop the existing Spring site with a persistent local Qwen worker.

Windows only. No installation, training, video upload, or cloud request is performed
by this launcher. API keys are stored only in the ignored private runtime directory.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = WORKSPACE / ".runtime/quick-local"


def process_identity(pid):
    """Record creation time as well as PID, so stop never kills a reused PID."""
    if os.name != "nt":
        raise RuntimeError("This local launcher currently supports Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        exit_code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value != 259:
            return None
        values = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(value) for value in values]):
            return None
        length = wintypes.DWORD(32768)
        image = ctypes.create_unicode_buffer(length.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length)):
            return None
        created = (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime
        return {"pid": int(pid), "created": created, "executable": image.value}
    finally:
        kernel.CloseHandle(handle)


def same_process(saved):
    return bool(saved and process_identity(saved["pid"]) == saved)


def find_java(explicit=None):
    candidates = [explicit] if explicit else []
    if os.environ.get("JAVA_HOME"):
        candidates.append(str(Path(os.environ["JAVA_HOME"]) / "bin/java.exe"))
    # Prefer installed JDKs over an old java.exe shim on PATH.
    java_dir = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Java"
    candidates += [str(path) for path in sorted(java_dir.glob("jdk-*/bin/java.exe"), reverse=True)]
    candidates.append(shutil.which("java"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise RuntimeError("Java 21+ was not found; pass --java with the installed java.exe path")


def preflight(args):
    runtime = args.runtime.resolve()
    paths = {
        "api_python": WORKSPACE / ".venv/Scripts/python.exe",
        "gpu_python": WORKSPACE / "training/.venv/Scripts/python.exe",
        "worker": WORKSPACE / "training/qwen/quick_inference.py",
        "java": find_java(args.java),
    }
    jars = sorted((REPO / "backend/target").glob("backend-*.jar"))
    if not jars:
        raise RuntimeError("Built Spring JAR is missing; build backend with mvnw.cmd package first")
    paths["jar"] = jars[-1]
    for label, path in paths.items():
        if not path.is_file():
            raise RuntimeError(f"Missing {label}: {path}")
    if not 1024 <= args.api_port <= 65535 or not 1024 <= args.service_port <= 65535 or args.api_port == args.service_port:
        raise ValueError("Choose distinct API and service ports between 1024 and 65535")
    return runtime, paths


def read_state(runtime):
    path = runtime / "processes.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_state(runtime, state):
    pending = runtime / "processes.json.tmp"
    pending.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(runtime / "processes.json")


def check_port(port):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as error:
            raise RuntimeError(f"Local port {port} is in use; stop its owner or choose another port") from error


def spawn(command, cwd, env, stdout_path, stderr_path):
    with stdout_path.open("ab") as output, stderr_path.open("ab") as errors:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=output, stderr=errors,
                                   stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    # Query immediately and retain exact process birth information for safe stopping.
    identity = process_identity(process.pid)
    if identity is None:
        raise RuntimeError(f"Local process exited during startup; inspect {stderr_path.name}")
    return identity


def stop(runtime):
    state = read_state(runtime)
    stopped = []
    for role in ("fragments", "annotation", "java", "service"):
        saved = state.get("processes", {}).get(role)
        if saved and same_process(saved):
            result = subprocess.run(["taskkill", "/PID", str(saved["pid"]), "/T", "/F"],
                                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode and same_process(saved):
                raise RuntimeError(f"Could not stop owned {role} process")
            stopped.append(role)
    if state:
        state.update(state="stopped", stopped_at=time.time(), processes={})
        write_state(runtime, state)
    return {"state": "stopped", "stopped_processes": stopped}


REVIEW_TOOLS = {"annotation": (4321, "server.py"), "fragments": (4323, "fragment_review.py")}


def review_tool_available(role):
    port = REVIEW_TOOLS[role][0]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/", timeout=2) as response:
            page = response.read(128 * 1024).decode("utf-8")
        expected = ("Разметка видео", "Автоматический анализ видео") if role == "annotation" else ("Категории и проверка фрагментов",)
        return any(brand in page for brand in ("Aiqyn Vision", "Aikyn Vision")) and any(label in page for label in expected)
    except (OSError, ValueError):
        return False


def review_tools_plan():
    plan = {}
    for role, (port, _) in REVIEW_TOOLS.items():
        try:
            check_port(port)
            plan[role] = True  # Start and own this process.
        except RuntimeError:
            if not review_tool_available(role):
                raise RuntimeError(f"Port {port} is occupied by an unrecognized service; it was left untouched")
            plan[role] = False  # Reuse; never stop an externally started editor.
    return plan


def status(runtime):
    state = read_state(runtime)
    if not state:
        return {"state": "not_started", "ready": False}
    alive = {role: same_process(saved) for role, saved in state.get("processes", {}).items()}
    result = {"state": state.get("state"), "ready": False, "processes_alive": alive,
              "url": state.get("url"), "api_key_file": str(runtime / "api-key.txt"),
              "logs": str(runtime), "new_training": False,
              "review_tools": {role: {"url": url, "running": review_tool_available(role), "managed": role in alive}
                               for role, url in state.get("review_tools", {}).items()}}
    if alive.get("java") and alive.get("service"):
        try:
            key = (runtime / "api-key.txt").read_text(encoding="utf-8").strip()
            request = urllib.request.Request(state["url"] + "/readyz", headers={"X-API-Key": key})
            # Bypass machine proxy settings for strictly local readiness checks.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=5) as response:
                body = json.loads(response.read(64 * 1024))
            result["ready"] = body.get("ready") is True
            result["mode"] = body.get("mode")
            result["state"] = "ready" if result["ready"] else "starting"
        except (urllib.error.URLError, OSError, ValueError):
            result["state"] = "starting"
    elif state.get("state") != "stopped":
        result["state"] = "process_unavailable"
    return result


def start(args):
    runtime, paths = preflight(args)
    runtime.mkdir(parents=True, exist_ok=True)
    previous = read_state(runtime)
    alive = [same_process(saved) for saved in previous.get("processes", {}).values()]
    if alive and all(alive):
        if args.review_tools and not all(role in previous.get("review_tools", {}) for role in REVIEW_TOOLS):
            raise RuntimeError("The analysis stack is already running without review tools. Stop it first, then start with START_AIQYN_VISION.ps1")
        return status(runtime)
    if any(alive):
        raise RuntimeError("A previous partial stack is still running; run this launcher with stop first")
    check_port(args.api_port)
    check_port(args.service_port)
    review_plan = review_tools_plan() if args.review_tools else {}
    uploads = runtime / "uploads"
    uploads.mkdir(exist_ok=True)
    key_path = runtime / "api-key.txt"
    if not key_path.exists():
        key_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    key = key_path.read_text(encoding="utf-8").strip()
    if len(key) < 24:
        raise RuntimeError("Private API key is missing or too short")
    env = os.environ.copy()
    env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", ANALYZER_BACKEND="qwen",
               ANALYZE_BUDGET_SEC="230", ANALYZE_CONCURRENCY="1", QUICK_RUNTIME=str(runtime),
               QWEN_STARTUP_TIMEOUT_SEC="180", APP_ANALYSIS_QUEUE_CAPACITY="0",
               QWEN_PYTHON=str(paths["gpu_python"]), QWEN_WORKER=str(paths["worker"]),
               TEMP=str(uploads), TMP=str(uploads), APP_API_KEY=key, APP_MODE="real",
               APP_LOCAL_BOOTSTRAP_ENABLED="true",
               APP_PYTHON_SERVICE_URL=f"http://127.0.0.1:{args.service_port}", APP_TIMEOUT_MINUTES="4",
               SERVER_ADDRESS="127.0.0.1", SERVER_PORT=str(args.api_port),
               SPRING_DATASOURCE_URL="jdbc:sqlite:" + str(runtime / "jobs.db").replace("\\", "/"))
    state = {"state": "starting", "started_at": time.time(), "url": f"http://127.0.0.1:{args.api_port}",
             "service_url": f"http://127.0.0.1:{args.service_port}", "processes": {}, "new_training": False}
    write_state(runtime, state)
    try:
        if args.review_tools:
            state["review_tools"] = {"annotation": "http://127.0.0.1:4321", "fragments": "http://127.0.0.1:4323"}
            for role, (_, script) in REVIEW_TOOLS.items():
                if not review_plan[role]:
                    continue
                state["processes"][role] = spawn(
                    [str(paths["api_python"]), str(WORKSPACE / "training/annotation" / script)],
                    WORKSPACE, env, runtime / f"{role}.stdout.log", runtime / f"{role}.stderr.log")
                write_state(runtime, state)
        state["processes"]["service"] = spawn(
            [str(paths["api_python"]), "-m", "uvicorn", "service:app", "--host", "127.0.0.1",
             "--port", str(args.service_port), "--workers", "1"], REPO / "scripts", env,
            runtime / "service.stdout.log", runtime / "service.stderr.log")
        write_state(runtime, state)
        state["processes"]["java"] = spawn(
            [str(paths["java"]), f"-Djava.io.tmpdir={uploads}", "-jar", str(paths["jar"])],
            REPO / "backend", env, runtime / "java.stdout.log", runtime / "java.stderr.log")
        write_state(runtime, state)
    except Exception:
        stop(runtime)
        raise
    return status(runtime)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "status", "stop", "preflight"))
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--api-port", type=int, default=8080)
    parser.add_argument("--service-port", type=int, default=8001)
    parser.add_argument("--java", help="Installed Java 21+ java.exe path")
    parser.add_argument("--review-tools", action="store_true", help="Also run the local annotation and fragment review interfaces")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This launcher supports Windows")
    if args.action == "start":
        result = start(args)
    elif args.action == "stop":
        result = stop(args.runtime.resolve())
    elif args.action == "preflight":
        runtime, paths = preflight(args)
        check_port(args.api_port)
        check_port(args.service_port)
        review_plan = review_tools_plan() if args.review_tools else {}
        result = {"runtime": str(runtime), "paths": {name: str(path) for name, path in paths.items()},
                  "ports_available": True, "review_tools_to_start": review_plan, "starts_processes": False, "new_training": False}
    else:
        result = status(args.runtime.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
