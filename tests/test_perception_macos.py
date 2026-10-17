"""Pure fixtures for the metadata adapter. These never call native macOS APIs."""
import ctypes as C
import math
from types import SimpleNamespace

from desktop.perception_macos import MacMetadataBackend, Point


def backend():
    result = MacMetadataBackend.__new__(MacMetadataBackend)
    result.permission_at = -math.inf
    result.typing_available = False
    result.last_key = None
    return result


def test_denied_input_monitoring_never_queries_keyboard_idle_or_requests_permission():
    result = backend()
    calls = []
    result.cg = SimpleNamespace(CGPreflightListenEventAccess=lambda: False,
                                CGEventSourceSecondsSinceLastEventType=lambda *_: calls.append("idle"))
    assert result.keypresses() == 0
    assert result.typing_available is False and result.last_key is None
    assert calls == []


def test_existing_permission_uses_idle_timestamps_and_no_key_objects(monkeypatch):
    result = backend()
    now, age = [100.], [.1]
    monkeypatch.setattr("desktop.perception_macos.time.monotonic", lambda: now[0])
    calls = []
    def idle(state, event_type):
        calls.append((state, event_type))
        return age[0]
    result.cg = SimpleNamespace(CGPreflightListenEventAccess=lambda: True,
                                CGEventSourceSecondsSinceLastEventType=idle)
    assert result.keypresses() == 0  # First sample has no fabricated activity.
    now[0] += .1
    age[0] += .1
    assert result.keypresses() == 0  # Idle timer advances, so no fresh pulse.
    now[0] += .1
    age[0] = .02
    assert result.keypresses() == 1
    assert calls == [(0, 10)] * 3 and result.typing_available is True


def test_pointer_snapshot_releases_the_native_object_and_contains_no_event_data():
    result = backend()
    result.screen = {"x": 0., "y": 0., "width": 1200., "height": 900.}
    released = []
    result.cg = SimpleNamespace(CGEventCreate=lambda _: 42, CGEventGetLocation=lambda _: Point(24, 80))
    result.cf = SimpleNamespace(CFRelease=released.append)
    assert result.pointer() == {"x": 24., "y": 80., "screen": result.screen}
    assert released == [42]


def test_window_query_only_accesses_fixed_geometry_keys_and_caps_window_count():
    result = backend()
    result.next_windows, result.own_pid = -math.inf, 123
    released, reads = [], []
    result.cg = SimpleNamespace(CGWindowListCopyWindowInfo=lambda flags, window: (flags, window))
    result.cf = SimpleNamespace(CFArrayGetCount=lambda _: 1000,
                                CFArrayGetValueAtIndex=lambda _, index: index,
                                CFRelease=released.append)
    def number(record, key, default=0.):
        reads.append(key)
        return {"kCGWindowLayer": 0, "kCGWindowAlpha": 1, "X": 10, "Y": 20,
                "Width": 500, "Height": 400, "kCGWindowOwnerPID": 999}.get(key, default)
    def value(record, key):
        assert key == "kCGWindowBounds"
        return 1
    result._number, result._value = number, value
    result._window_metadata(10.)
    assert len(result.windows) == 32 and result.window["own"] is False
    assert set(reads) == {"kCGWindowLayer", "kCGWindowAlpha", "X", "Y", "Width", "Height", "kCGWindowOwnerPID"}
    assert released == [(17, 0)]
    prior_reads = len(reads)
    result._window_metadata(10.2)
    assert len(reads) == prior_reads
    assert result.microphone_status() is None
