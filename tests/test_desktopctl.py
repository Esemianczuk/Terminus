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
