"""Renderer startup protection without GUI, services or real waiting."""
import json
import os
import stat

import pytest

from desktop.render_guard import MARKER_NAME, RenderGuard


def report(now, **changes):
    return {"visible": True, "exposed": True, "connected": True, "snapshot_fresh": True,
            "platform": "xcb", "updated_at": now, "pid": 123,
            "graphics": {"available": True, "frames_rendered": 10, "scene_graph_initialized": True}, **changes}


def test_two_early_failures_latch_fallback_across_later_restarts(tmp_path):
    now = [100.]
    def guard():
        return RenderGuard(tmp_path, clock=lambda: now[0], pid=123)
    first = guard()
    assert first.begin() and first.begin()  # Calling begin twice is harmless.
    assert json.loads(first.path.read_text())["count"] == 0
    now[0] += 3
    assert guard().begin()
    now[0] += 3
    blocked = guard()
    assert blocked.begin() is False and blocked.latched
    assert json.loads(blocked.path.read_text())["count"] == 2
    now[0] += 100000
    assert guard().begin() is False  # Raster does not reset the crash latch.
    assert blocked.healthy(report(now[0])) is False
    assert blocked.path.exists()


def test_early_failures_older_than_ten_minutes_do_not_accumulate(tmp_path):
    now = [100.]
    first = RenderGuard(tmp_path, clock=lambda: now[0], pid=123)
    assert first.begin()
    now[0] += 601
    second = RenderGuard(tmp_path, clock=lambda: now[0], pid=124)
    assert second.begin()
    assert json.loads(second.path.read_text())["count"] == 0


def test_fifteen_continuous_healthy_seconds_clear_pending_and_failures(tmp_path):
    now = [100.]
    RenderGuard(tmp_path, clock=lambda: now[0], pid=123).begin()
    now[0] += 1
    guard = RenderGuard(tmp_path, clock=lambda: now[0], pid=123)
    assert guard.begin()
    assert guard.record["count"] == 1
    for step in range(16):
        now[0] = 101 + step
        assert guard.healthy(report(now[0])) is (step == 15)
    assert not guard.path.exists()
    assert guard.healthy(report(now[0]))
    assert RenderGuard(tmp_path, clock=lambda: now[0], pid=123).begin()
    assert json.loads(guard.path.read_text())["count"] == 0


@pytest.mark.parametrize("changes", [
    {"visible": False}, {"exposed": False}, {"connected": False}, {"snapshot_fresh": False},
    {"platform": "offscreen"}, {"platform": "minimal"}, {"platform": ""}, {"pid": 999},
    {"graphics": {"available": False, "frames_rendered": 10, "scene_graph_initialized": True}},
    {"graphics": {"available": True, "frames_rendered": 0, "scene_graph_initialized": True}},
    {"graphics": {"available": True, "frames_rendered": True, "scene_graph_initialized": True}},
    {"graphics": {"available": True, "frames_rendered": 10, "scene_graph_initialized": False}},
])
def test_any_missing_native_health_condition_resets_the_interval(tmp_path, changes):
    now = [100.]
    guard = RenderGuard(tmp_path, clock=lambda: now[0], pid=123)
    assert guard.begin()
    for step in range(10):
        now[0] = 100 + step
        assert not guard.healthy(report(now[0]))
    now[0] = 110
    assert not guard.healthy(report(now[0], **changes))
    assert guard.healthy_since is None
    for step in range(15):
        now[0] = 111 + step
        assert not guard.healthy(report(now[0]))
    now[0] = 126
    assert guard.healthy(report(now[0]))


def test_stale_timestamp_long_gap_and_backwards_clock_restart_health(tmp_path):
    now = [100.]
    guard = RenderGuard(tmp_path, clock=lambda: now[0], pid=123)
    assert guard.begin()
    assert not guard.healthy(report(100.))
    now[0] = 120
    assert not guard.healthy(report(120.))
    assert guard.healthy_since == 120
    now[0] = 119
    assert not guard.healthy(report(119.))
    assert guard.healthy_since == 119
    assert not guard.healthy(report(100.))
    assert guard.healthy_since is None


@pytest.mark.parametrize("payload", [
    b"broken", b"x" * 513, b"[]", b'{"schema":1,"pid":123,"time":NaN,"count":0}',
    b'{"schema":1,"pid":123,"time":100000,"count":0}',
    b'{"schema":1,"pid":123,"time":100,"count":false}',
    b'{"schema":1,"pid":123,"time":100,"count":0,"text":"private"}',
])
def test_invalid_oversize_and_future_markers_choose_safe_fallback(tmp_path, payload):
    path = tmp_path / MARKER_NAME
    path.write_bytes(payload)
    guard = RenderGuard(tmp_path, clock=lambda: 100., pid=123)
    assert not guard.begin() and guard.latched
    assert json.loads(path.read_text())["count"] == 2
    if os.name != "nt":assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_marker_is_atomic_private_and_contains_only_version_pid_time_count(tmp_path):
    guard = RenderGuard(tmp_path, clock=lambda: 100., pid=123)
    assert guard.begin()
    assert set(json.loads(guard.path.read_text())) == {"schema", "pid", "time", "count"}
    if os.name != "nt":assert stat.S_IMODE(guard.path.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [guard.path]


def test_symlink_target_is_never_read_changed_or_removed(tmp_path):
    target = tmp_path / "unrelated"
    target.write_text("private")
    path = tmp_path / MARKER_NAME
    try:path.symlink_to(target)
    except OSError as error:
        if os.name=="nt" and getattr(error,"winerror",None)==1314:pytest.skip("Windows developer mode or symlink privilege is needed")
        raise
    guard = RenderGuard(tmp_path, clock=lambda: 100., pid=123)
    assert guard.begin() is False
    assert target.read_text() == "private"
    assert not path.is_symlink()


def test_unavailable_latches_fallback_and_manual_marker_removal_permits_retry(tmp_path):
    guard = RenderGuard(tmp_path, clock=lambda: 100., pid=123)
    assert guard.begin()
    guard.unavailable()
    assert not guard.begin()
    assert not guard.healthy(report(100.))
    assert not RenderGuard(tmp_path, clock=lambda: 200., pid=123).begin()
    guard.path.unlink()
    assert RenderGuard(tmp_path, clock=lambda: 200., pid=123).begin()


def test_replaced_marker_is_not_deleted_by_an_older_guard(tmp_path):
    now = [100.]
    guard = RenderGuard(tmp_path, clock=lambda: now[0], pid=123)
    guard.begin()
    for step in range(15):
        now[0] = 100 + step
        assert not guard.healthy(report(now[0]))
    other = {"schema": 1, "pid": 999, "time": 114., "count": 2}
    guard.path.write_text(json.dumps(other))
    now[0] = 115
    assert not guard.healthy(report(now[0]))
    assert json.loads(guard.path.read_text()) == other


def test_unwritable_or_invalid_data_directory_fails_to_raster_without_raising(tmp_path):
    path = tmp_path / "file"
    path.write_text("unrelated")
    guard = RenderGuard(path, clock=lambda: 100., pid=123)
    assert guard.begin() is False
    guard.unavailable()
    assert path.read_text() == "unrelated"


def test_non_regular_marker_cannot_block_startup(tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("Named pipes unavailable")
    os.mkfifo(tmp_path / MARKER_NAME)
    guard = RenderGuard(tmp_path, clock=lambda: 100., pid=123)
    assert guard.begin() is False
    assert stat.S_ISREG(guard.path.stat().st_mode)


def test_repeated_healthy_reports_after_marker_replacement_stay_safe(tmp_path):
    now = [100.]
    guard = RenderGuard(tmp_path, clock=lambda: now[0], pid=123)
    guard.begin()
    for step in range(15):
        now[0] = 100 + step
        guard.healthy(report(now[0]))
    other = {"schema": 1, "pid": 999, "time": 114., "count": 2}
    guard.path.write_text(json.dumps(other))
    for step in range(20):
        now[0] = 115 + step
        assert not guard.healthy(report(now[0]))
    assert json.loads(guard.path.read_text()) == other


def test_gpu_failure_after_initial_stability_latches_fallback_again(tmp_path):
    now = [100.]
    guard = RenderGuard(tmp_path, clock=lambda: now[0], pid=123)
    guard.begin()
    for step in range(16):
        now[0] = 100 + step
        guard.healthy(report(now[0]))
    assert guard.cleared and not guard.path.exists()
    guard.unavailable()
    assert guard.latched and not guard.cleared
    assert not guard.healthy(report(now[0]))
    assert json.loads(guard.path.read_text())["count"] == 2
