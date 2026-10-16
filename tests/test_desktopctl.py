"""Resident launcher boundaries; tests never signal a real desktop process."""
import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location("desktopctl", Path(__file__).parents[1] / "scripts" / "desktopctl.py")
ctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ctl)


def test_unrelated_process_cannot_be_adopted():
    import os
    assert ctl.process_identity(os.getpid()) is None


@pytest.mark.parametrize("payload", [[], None, {"pid": 15}, {"pid": 15, "updated_at": float("nan")},
                                     {"pid": 15, "updated_at": 101}, {"pid": 15, "updated_at": 90},
                                     {"pid": 16, "updated_at": 99}])
def test_stale_malformed_or_foreign_heartbeat_is_not_presence(tmp_path, monkeypatch, payload):
    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text(json.dumps(payload))
    monkeypatch.setattr(ctl, "STATUS", heartbeat)
    monkeypatch.setattr(ctl.time, "time", lambda: 100)
    assert ctl.live_status({"pid": 15}) is None


def test_presence_requires_exposed_native_window_and_core_connection():
    status = {"visible": True, "exposed": True, "connected": True, "platform": "xcb"}
    assert ctl.ready(status)
    assert not ctl.ready({**status, "exposed": False})
    assert not ctl.ready({**status, "connected": False})
    assert not ctl.ready({**status, "platform": "offscreen"})


def test_ownership_change_immediately_before_stop_never_sends_signal(monkeypatch):
    record = {"pid": 15, "start_ticks": "old", "boot_id": "boot"}
    monkeypatch.setattr(ctl, "process_identity", lambda pid: {**record, "start_ticks": "new"})
    def forbidden(*args):
        pytest.fail("Unrelated process must never receive a signal")
    monkeypatch.setattr(ctl.os, "kill", forbidden)
    assert ctl.stop(record) == 1


def test_process_exiting_during_stop_is_cleanly_handled(tmp_path, monkeypatch):
    record = {"pid": 15, "start_ticks": "same", "boot_id": "boot"}
    marker = tmp_path / "managed.json"
    marker.write_text(json.dumps(record))
    monkeypatch.setattr(ctl, "RECORD", marker)
    monkeypatch.setattr(ctl, "process_identity", lambda pid: record)
    def already_exited(*args):
        raise ProcessLookupError()
    monkeypatch.setattr(ctl.os, "kill", already_exited)
    assert ctl.stop(record) == 0
    assert not marker.exists()


@pytest.mark.parametrize("scale", [None, 1.3])
def test_initializing_desktop_identity_is_retried_before_native_readiness(tmp_path, monkeypatch, scale):
    runtime = tmp_path / ".local"
    runtime.mkdir()
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(ctl, "ROOT", tmp_path)
    monkeypatch.setattr(ctl, "DATA", runtime)
    monkeypatch.setattr(ctl, "RECORD", runtime / "managed-desktop.json")
    monkeypatch.setattr(ctl, "STATUS", runtime / "desktop-status.json")
    monkeypatch.setattr(ctl, "CAPTURE", runtime / "desktop-presence.png")
    monkeypatch.setenv("DISPLAY", ":test")
    record = {"pid": 17, "start_ticks": "ticks", "boot_id": "boot"}
    identities = iter([None, record])
    identity_calls, launches, status_calls, sleeps = [], [], [], []

    class HealthyCore:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return b'{"service":"terminus","status":"ok"}'

    def initializing_identity(pid):
        identity_calls.append(pid)
        return next(identities)

    def launch(command, **kwargs):
        launches.append(command)
        return type("Child", (), {"pid": 17, "poll": lambda self: None})()

    def status(verified):
        assert verified == record
        assert json.loads(ctl.RECORD.read_text()) == record
        status_calls.append(verified)
        return {"visible": True, "exposed": len(status_calls) > 1,
                "connected": True, "platform": "xcb"}

    monkeypatch.setattr(ctl.urllib.request, "urlopen", lambda *args, **kwargs: HealthyCore())
    monkeypatch.setattr(ctl.subprocess, "run", lambda *args, **kwargs: pytest.fail("The healthy core must not be changed"))
    monkeypatch.setattr(ctl.subprocess, "Popen", launch)
    monkeypatch.setattr(ctl, "process_identity", initializing_identity)
    monkeypatch.setattr(ctl, "live_status", status)
    monkeypatch.setattr(ctl.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(ctl.os, "kill", lambda *args: pytest.fail("Starting must never signal a process"))
    assert ctl.start(None, scale) == 0
    assert identity_calls == [17, 17]
    assert len(launches) == 1 and len(status_calls) == 2
    assert sleeps == [.1, .1]
    assert json.loads(ctl.RECORD.read_text()) == record
    command = launches[0]
    if scale is None:
        assert "--scale" not in command
    else:
        assert command[command.index("--scale") + 1] == str(scale)


def test_desktop_record_uses_a_single_verified_process_identity(tmp_path, monkeypatch):
    record = {"pid": 17, "start_ticks": "ticks", "boot_id": "boot"}
    path = tmp_path / "managed-desktop.json"
    path.write_text(json.dumps(record))
    monkeypatch.setattr(ctl, "RECORD", path)
    calls = []

    def identity_once(pid):
        calls.append(pid)
        if len(calls) > 1:
            pytest.fail("A second read could adopt a replacement process")
        return record

    monkeypatch.setattr(ctl, "process_identity", identity_once)
    assert ctl.owned_record() == record
    assert calls == [17]
