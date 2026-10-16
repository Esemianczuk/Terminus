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
    observer = awareness.DesktopAwareness(enabled=enabled, environment=environment, backend_factory=forbidden).start()
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


@pytest.mark.parametrize("provider_result,caret_source,typing", [
    ({"rect": {"x": 180, "y": 150, "width": 0, "height": 18}, "secure": False, "fresh": True}, "at-spi", True),
    ({"rect": {"x": 180, "y": 150, "width": 1, "height": 18}, "secure": True}, "window-fallback", False),
    ({"rect": {"x": 0, "y": 0, "width": 1, "height": 18}, "secure": False}, "window-fallback", True),
    ({"rect": {"x": 180, "y": 150, "width": 1, "height": 18}, "fresh": False}, "window-fallback", True),
])
def test_caret_geometry_is_optional_current_and_secure_entry_suppresses_pulses(provider_result, caret_source, typing):
    backend = FakeBackend()
    observer = awareness.DesktopAwareness(environment=ENVIRONMENT, backend_factory=lambda *args: backend,
                                         caret_provider=lambda window: provider_result).start()
    try:
        eventually(lambda: observer.snapshot()["available"])
        state = observer.snapshot()
        assert state["caret_source"] == caret_source
        assert state["typing"]["active"] is typing
        if not typing:
            assert state["typing"]["last_at"] is None and state["typing"]["rate"] == 0
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
