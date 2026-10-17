"""Local observer boundaries; tests do not inspect applications or inject input."""

import ctypes as C
from collections import deque
import struct
import threading
import time
from types import SimpleNamespace

import pytest

from desktop import awareness


ENVIRONMENT = {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":test"}
WINDOW = {"x": 100, "y": 50, "width": 800, "height": 600, "own": False}


def eventually(predicate):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    pytest.fail("Observer did not reach its expected state within one second")


class FakeBackend:
    def __init__(self):
        self.counts = deque([4])
        self.window_reads = 0
        self.closed = False

    def focused_window(self, now):
        self.window_reads += 1
        return dict(WINDOW)

    def keypresses(self):
        return self.counts.popleft() if self.counts else 0

    def close(self):
        self.closed = True


def test_typing_aggregate_is_bounded_transient_and_contains_no_key_identities():
    rhythm = awareness._TypingRhythm()
    for sample in range(1000):
        rhythm.note(3, sample / 100)
    assert len(rhythm.samples) == 128
    state = rhythm.state(10)
    assert state["active"] and state["last_at"] == 9.99
    assert state["rate"] == 20
    assert state["sequence"] == 1000
    assert set(state) == {"active", "last_at", "rate", "pulse", "sequence"}
    later = rhythm.state(15)
    assert not later["active"] and later["rate"] == 0 and later["pulse"] < .001
    rhythm.clear()
    assert rhythm.state(15)["last_at"] is None


@pytest.mark.parametrize("enabled,environment,reason", [
    (False, ENVIRONMENT, "disabled"),
    (True, {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":test"}, "wayland_unsupported"),
    (True, {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":test"}, "wayland_unsupported"),
    (True, {}, "x11_display_unavailable"),
])
def test_disabled_and_unsupported_modes_never_open_input_connection(enabled, environment, reason):
    def forbidden(*args):
        pytest.fail("Disabled/unsupported observation must not open an input connection")
    observer = awareness.DesktopAwareness(enabled=enabled, environment=environment,
                                         platform="linux", backend_factory=forbidden).start()
    assert not observer.snapshot()["available"]
    assert observer.snapshot()["reason"] == reason
    assert observer.close()


def test_worker_has_fresh_local_pulses_lazy_window_poll_and_bounded_teardown():
    backend = FakeBackend()
    observer = awareness.DesktopAwareness(environment=ENVIRONMENT, backend_factory=lambda *args: backend).start()
    eventually(lambda: observer.snapshot()["available"])
    state = observer.snapshot()
    assert state["source"] == "x11-xinput2"
    assert state["focused_window"] == WINDOW
    assert state["typing"]["active"]
    assert abs(time.monotonic() - state["observed_at"]) < .5
    assert state["caret"] is None and state["caret_source"] == "window-fallback"
    assert state["secure_entry"] is None
    state["focused_window"]["x"] = -100  # Consumers cannot mutate worker state.
    assert observer.snapshot()["focused_window"] == WINDOW
    time.sleep(.12)
    assert backend.window_reads == 1
    started = time.monotonic()
    assert observer.close(timeout=.5)
    assert time.monotonic() - started < .5 and backend.closed
    assert not observer.snapshot()["enabled"] and not observer.snapshot()["available"]


def test_retired_caret_provider_is_never_called_or_used():
    backend = FakeBackend()
    def forbidden(*_):
        pytest.fail("Desktop awareness must not query any accessibility text interface")
    observer = awareness.DesktopAwareness(environment=ENVIRONMENT, backend_factory=lambda *args: backend,
                                         caret_provider=forbidden).start()
    try:
        eventually(lambda: observer.snapshot()["available"])
        assert observer.snapshot()["caret"] is None
        assert observer.snapshot()["caret_source"] == "window-fallback"
        assert observer.snapshot()["secure_entry"] is None
    finally:
        assert observer.close()


def test_connection_failure_is_an_unavailable_snapshot_and_still_releases_resources():
    backend = FakeBackend()
    def disconnected():
        raise RuntimeError("disconnected")
    backend.keypresses = disconnected
    observer = awareness.DesktopAwareness(environment=ENVIRONMENT, backend_factory=lambda *args: backend).start()
    eventually(lambda: observer.snapshot()["reason"] == "RuntimeError")
    assert not observer.snapshot()["available"]
    assert observer.close() and backend.closed


def test_raw_input_reader_only_reads_generic_header_and_ignores_other_events(monkeypatch):
    buffers = [C.create_string_buffer(struct.pack("=BBHIH", response, extension, 1, 2, event_type) + b"private-detail" * 3)
               for response, extension, event_type in [(35, 131, 13), (35, 131, 14), (35, 130, 13), (163, 131, 13)]]
    events = deque(C.addressof(buffer) for buffer in buffers)
    freed, read_lengths = [], []
    backend = awareness._XcbBackend.__new__(awareness._XcbBackend)
    backend.connection, backend.opcode = object(), 131
    backend.free = freed.append
    backend.xcb = SimpleNamespace(xcb_poll_for_event=lambda connection: events.popleft() if events else None,
                                  xcb_connection_has_error=lambda connection: 0)
    string_at = C.string_at
    def header_only(pointer, size):
        read_lengths.append(size)
        assert size == 10, "The XI2 detail/keycode field must never be read"
        return string_at(pointer, size)
    monkeypatch.setattr(awareness.C, "string_at", header_only)
    assert backend.keypresses() == 1
    assert len(freed) == 4 and read_lengths == [10] * 4


def test_window_queries_cache_geometry_and_survive_destroyed_window_races():
    backend = awareness._XcbBackend.__new__(awareness._XcbBackend)
    backend.root, backend.active_atom, backend.pid_atom, backend.own_pid = 1, 2, 3, 99
    backend.connection, backend.window_id, backend.window_cache, backend.geometry_at = None, None, None, -1e10
    property_reads, geometry_reads = [], []
    def property_value(window, atom):
        property_reads.append((window, atom))
        return 10 if atom == 2 else 99
    backend._property = property_value
    backend.xcb = SimpleNamespace(xcb_get_geometry=lambda *args: "geometry", xcb_translate_coordinates=lambda *args: "position")
    def reply(cookie, structure):
        geometry_reads.append(cookie)
        return SimpleNamespace(width=800, height=600) if cookie == "geometry" else SimpleNamespace(x=100, y=50)
    backend._reply = reply
    assert backend.focused_window(0) == {**WINDOW, "own": True}
    assert backend.focused_window(.5) == {**WINDOW, "own": True}
    assert geometry_reads == ["geometry", "position"]
    assert property_reads == [(1, 2), (10, 3), (1, 2)]
    backend.focused_window(2.1)
    assert len(geometry_reads) == 4
    def destroyed(window, atom):
        raise RuntimeError("BadWindow")
    backend._property = destroyed
    assert backend.focused_window(3) is None
    assert backend.window_cache is None


def test_stopping_reply_wait_discards_request_without_blocking():
    backend = awareness._XcbBackend.__new__(awareness._XcbBackend)
    backend.stop = threading.Event()
    backend.stop.set()
    backend.connection = object()
    discarded = []
    backend.xcb = SimpleNamespace(xcb_flush=lambda connection: 1,
                                  xcb_discard_reply=lambda connection, sequence: discarded.append(sequence))
    with pytest.raises(TimeoutError):
        backend._wait(awareness._Cookie(42))
    assert discarded == [42]


def test_typing_bouts_require_sustained_activity_and_have_one_pause_phase():
    rhythm = awareness._TypingRhythm()
    rhythm.note(1, 10.)
    assert rhythm.bout(10.)["level"] == 0
    assert rhythm.bout(10.)["phase"] == "active"
    for step in range(1, 21):
        rhythm.note(1, 10 + step / 10)
    active = rhythm.bout(12.)
    assert active["phase"] == "active" and active["duration_s"] == 2
    assert active["level"] >= .9 and active["sequence"] == 1
    pause = rhythm.bout(13.2)
    assert pause["phase"] == "pause" and pause["sequence"] == 1
    assert 1.1 < pause["pause_age_s"] < 1.3
    assert rhythm.bout(21.)["phase"] == "idle"
    rhythm.note(1, 22.)
    assert rhythm.bout(22.)["sequence"] == 2
    assert rhythm.bout(22.)["level"] == 0


def test_window_summary_is_coarse_bounded_and_rejects_names():
    screen = {"x": 0, "y": 0, "width": 1000, "height": 1000}
    summary = awareness._window_summary([{**WINDOW, "title": "never exported", "pid": 999}] * 40, screen)
    assert summary["available"] and summary["count"] == 32 and len(summary["rects"]) == 8
    assert summary["coverage"] == 1
    assert all(set(rect) == {"x", "y", "width", "height"} for rect in summary["rects"])
    assert "never exported" not in str(summary)
    assert awareness._window_summary([], None)["available"] is False


def test_child_protocol_rejects_text_unknown_fields_nan_and_stale_data():
    import json
    observer = awareness.DesktopAwareness(environment=ENVIRONMENT)
    value = observer._empty("starting")
    assert observer._accept(json.dumps(value))
    for bad in ({**value, "text": "private"},
                {**value, "pointer": {"available": True, "title": 10}},
                {**value, "observed_at": float("nan")},
                {**value, "observed_at": time.monotonic()-10},
                {**value, "focused_window": {**WINDOW, "class": "private"}},
                {**value, "caret": {"x": 0}},
                {**value, "windows": {"available": True, "count": 1, "coverage": .2,
                                     "rects": [{"x": 1, "y": 2, "width": 3, "height": 4, "title": "private"}]}}):
        assert not observer._accept(json.dumps(bad))
    assert not observer._accept(b"x" * (awareness.MAX_SNAPSHOT + 1))


def test_stalled_child_is_disposable_and_snapshot_does_not_block(monkeypatch):
    import subprocess
    import sys
    monkeypatch.setattr(awareness, "STALE_AFTER", .2)
    children = []
    def popen(args, **kwargs):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], **kwargs)
        children.append(process)
        return process
    observer = awareness.DesktopAwareness(environment=ENVIRONMENT, popen=popen).start()
    try:
        eventually(lambda: bool(children))
        start = time.monotonic()
        for _ in range(1000):
            observer.snapshot()
        assert time.monotonic() - start < .2
        eventually(lambda: children[0].poll() is not None)
        assert not observer.snapshot()["available"]
        assert observer.close()
        assert children[0].stdout.closed
    finally:
        observer.close()


def test_oversize_or_invalid_child_pipe_is_reaped_without_unbounded_accumulation():
    import subprocess
    import sys
    children = []
    def popen(args, **kwargs):
        code = "import sys,time; sys.stdout.write('x'*100000); sys.stdout.flush(); time.sleep(20)"
        process = subprocess.Popen([sys.executable, "-c", code], **kwargs)
        children.append(process)
        return process
    observer = awareness.DesktopAwareness(environment=ENVIRONMENT, popen=popen).start()
    try:
        eventually(lambda: bool(children) and children[0].poll() is not None)
        assert observer.snapshot()["available"] is False
        assert observer.close()
    finally:
        observer.close()


def test_termination_resistant_child_is_killed_and_only_owned_pid_is_touched():
    import subprocess
    import sys
    children = []
    def popen(args, **kwargs):
        code = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('ready',flush=True); time.sleep(20)"
        # Parent sees invalid output and terminates/reaps the owned child.
        process = subprocess.Popen([sys.executable, "-c", code], **kwargs)
        children.append(process)
        return process
    observer = awareness.DesktopAwareness(environment=ENVIRONMENT, popen=popen).start()
    try:
        eventually(lambda: bool(children) and children[0].poll() is not None)
        assert children[0].returncode < 0
        assert observer.close(timeout=.8)
    finally:
        observer.close()


def test_passive_xcb_api_surface_has_no_input_control_symbols():
    import inspect
    source = inspect.getsource(awareness._XcbBackend)
    for forbidden in ("xcb_grab", "xcb_ungrab", "xcb_set_input_focus", "xcb_send_event",
                      "XGrab", "XTest", "warp_pointer", "set_selection_owner"):
        assert forbidden not in source
    assert "xcb_input_xi_select_events" in source
    assert "1 << 13" in source  # RawKeyPress only, passive header counts.


def test_macos_adapter_never_uses_event_taps_accessibility_or_audio():
    from pathlib import Path
    source = (Path(awareness.__file__).with_name("perception_macos.py")).read_text()
    for forbidden in ("CGEventTapCreate", "CGEventPost", "CGWarpMouseCursorPosition", "AXUIElement",
                      "CGRequestListenEventAccess", "AVCapture", "pyaudio", "kCGWindowName", "kCGWindowOwnerName"):
        assert forbidden not in source
    assert "CGPreflightListenEventAccess" in source
    assert "CGEventSourceSecondsSinceLastEventType" in source


def test_microphone_status_is_only_bounded_stream_metadata_and_never_recording(monkeypatch):
    import subprocess
    import sys
    if sys.platform != "linux":
        pytest.skip("The stream metadata adapter is Linux-only")
    original = subprocess.Popen
    commands, children = [], []
    def popen(args, **kwargs):
        commands.append(args)
        process = original([sys.executable, "-c", "print('123\\t2\\t4\\tprotocol-native.c')"], **kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(awareness.subprocess, "Popen", popen)
    status = awareness._MicrophoneStatus()
    assert status.sample(10.) is True
    assert status.sample(11.) is True
    assert len(commands) == 1  # Cached, no audio-device opening or tight polling.
    assert commands == [["pactl", "list", "short", "source-outputs"]]
    assert children[0].poll() == 0 and children[0].stdout.closed
    assert set(status.__dict__) == {"next_at", "current"}


def test_microphone_metadata_deadline_and_output_cap_reap_the_owned_query(monkeypatch):
    import subprocess
    import sys
    if sys.platform != "linux":
        pytest.skip("The stream metadata adapter is Linux-only")
    original = subprocess.Popen
    children = []
    def popen(args, **kwargs):
        code = "import sys,time;sys.stdout.write('x'*100000);sys.stdout.flush();time.sleep(20)"
        process = original([sys.executable, "-c", code], **kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(awareness.subprocess, "Popen", popen)
    start = time.monotonic()
    assert awareness._MicrophoneStatus().sample(10.) is None
    assert time.monotonic()-start < .5
    assert children[0].poll() is not None and children[0].stdout.closed


def test_child_environment_does_not_inherit_credentials_or_injection_variables():
    import subprocess
    import sys
    original = subprocess.Popen
    calls = []
    def popen(args, **kwargs):
        calls.append(kwargs)
        return original([sys.executable, "-c", "pass"], **kwargs)
    environment = {**ENVIRONMENT, "PATH": "/usr/bin", "HOME": "/tmp", "GITHUB_TOKEN": "secret",
                   "TERMINUS_PAIR_TOKEN": "secret", "LD_PRELOAD": "unsafe.so", "PYTHONPATH": "/unsafe"}
    observer = awareness.DesktopAwareness(environment=environment, popen=popen).start()
    try:
        eventually(lambda: observer.process is not None and observer.process.poll() is not None)
        assert set(calls[0]["env"]) == {"DISPLAY", "XDG_SESSION_TYPE", "PATH", "HOME", "PYTHONNOUSERSITE"}
        assert "secret" not in str(calls[0]["env"])
        assert calls[0]["stdin"] == subprocess.DEVNULL and calls[0]["close_fds"] is True
        assert observer.close()
    finally:
        observer.close()
