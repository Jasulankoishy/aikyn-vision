"""Launcher tests use only synthetic state and an empty local TCP listener."""
import importlib
import json
import os
from pathlib import Path
import socket
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launch_quick_local as launcher


@pytest.mark.skipif(os.name != "nt", reason="Windows process identity API")
def test_process_identity_protects_against_reused_pid():
    identity = launcher.process_identity(os.getpid())
    assert identity is not None and launcher.same_process(identity)
    assert not launcher.same_process({**identity, "created": identity["created"] - 1})


def test_launcher_paths_stay_inside_repository():
    root = Path(__file__).resolve().parents[2]
    assert launcher.REPO == launcher.WORKSPACE == root
    assert launcher.DEFAULT_RUNTIME == root / ".runtime/quick-local"


def test_stop_never_kills_unmatched_process(monkeypatch, tmp_path):
    saved = {"pid": 987654, "created": 1, "executable": "synthetic.exe"}
    launcher.write_state(tmp_path, {"state": "starting", "processes": {"java": saved}})
    monkeypatch.setattr(launcher, "same_process", lambda saved: False)
    monkeypatch.setattr(launcher.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not kill unmatched PID"))
    assert launcher.stop(tmp_path)["stopped_processes"] == []


def test_occupied_port_is_reported_without_stopping_its_owner():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        with pytest.raises(RuntimeError, match="is in use"):
            launcher.check_port(listener.getsockname()[1])


def test_status_reports_key_path_but_not_key_text(monkeypatch, tmp_path):
    key = "synthetic-secret-that-must-never-appear"
    (tmp_path / "api-key.txt").write_text(key, encoding="utf-8")
    launcher.write_state(tmp_path, {"state": "stopped", "url": "http://127.0.0.1:1", "processes": {}})
    result = launcher.status(tmp_path)
    assert key not in json.dumps(result)
    assert result["api_key_file"] == str(tmp_path / "api-key.txt")
    assert result["ready"] is False


def test_reuses_known_editor_without_taking_ownership(monkeypatch):
    def occupied(port):
        if port == 4321:
            raise RuntimeError("in use")
    monkeypatch.setattr(launcher, "check_port", occupied)
    monkeypatch.setattr(launcher, "review_tool_available", lambda role: role == "annotation")
    assert launcher.review_tools_plan() == {"annotation": False, "fragments": True}


def test_unknown_port_owner_is_left_untouched(monkeypatch):
    monkeypatch.setattr(launcher, "check_port", lambda port: (_ for _ in ()).throw(RuntimeError("in use")))
    monkeypatch.setattr(launcher, "review_tool_available", lambda role: False)
    with pytest.raises(RuntimeError, match="left untouched"):
        launcher.review_tools_plan()


def test_stop_does_not_kill_reused_editors(monkeypatch, tmp_path):
    launcher.write_state(tmp_path, {"state": "ready", "processes": {}, "review_tools": {"annotation": "http://127.0.0.1:4321"}})
    monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **kw: pytest.fail("must not stop externally started editors"))
    assert launcher.stop(tmp_path)["stopped_processes"] == []
