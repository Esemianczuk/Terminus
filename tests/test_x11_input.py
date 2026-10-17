"""Input-only shape requests must never clip rendering or control input."""
import ctypes as C
import inspect
from types import SimpleNamespace

import pytest

from desktop import x11_input


class Rect:
    def __init__(self, x=1, y=2, width=30, height=40):
        self.values = x, y, width, height
    def x(self):
        return self.values[0]
    def y(self):
        return self.values[1]
    def width(self):
        return self.values[2]
    def height(self):
        return self.values[3]


def adapter():
    result = x11_input.OwnWindowInputShape.__new__(x11_input.OwnWindowInputShape)
    result.window = 42
    result.widget = SimpleNamespace(winId=lambda: 42)
    result.available, result.connection, result.error = True, object(), None
    calls, disconnected = [], []
    result.xcb = SimpleNamespace(xcb_connection_has_error=lambda _: 0,
                                 xcb_poll_for_event=lambda _: None,
                                 xcb_flush=lambda _: 1,
                                 xcb_disconnect=disconnected.append)
    def rectangles(connection, operation, kind, order, window, x, y, count, array):
        calls.append({"operation": operation, "kind": kind, "ordering": order,
                      "window": window, "offset": (x, y), "count": count,
                      "rectangles": [(rect.x, rect.y, rect.width, rect.height) for rect in array] if array else []})
        return x11_input._Cookie(1)
    result.shape = SimpleNamespace(xcb_shape_rectangles=rectangles)
    result.free = lambda _: None
    return result, calls, disconnected


def test_only_input_shape_is_modified_and_empty_region_is_clickthrough():
    shape, calls, _ = adapter()
    assert shape.set_region([Rect(), Rect(-5, -6, 10, 11)])
    assert calls == [{"operation": 0, "kind": 2, "ordering": 0, "window": 42,
                      "offset": (0, 0), "count": 2, "rectangles": [(1, 2, 30, 40), (-5, -6, 10, 11)]}]
    assert shape.set_region([])
    assert calls[-1]["kind"] == 2 and calls[-1]["count"] == 0


@pytest.mark.parametrize("rect", [Rect(x=-32769), Rect(y=32768), Rect(width=65536),
                                  Rect(height=-1), Rect(x=True), Rect(width=1.5), object()])
def test_invalid_regions_send_no_partial_shape_request(rect):
    shape, calls, _ = adapter()
    assert shape.set_region([Rect(), rect]) is False
    assert calls == []


def test_region_limit_is_bounded_before_any_native_call():
    shape, calls, _ = adapter()
    yielded = []
    def flood():
        for index in range(100000):
            yielded.append(index)
            yield Rect()
    assert shape.set_region(flood()) is False
    assert len(yielded) == 4097 and calls == []
    assert shape.set_region([Rect()] * 4096)
    assert calls[-1]["count"] == 4096


def test_native_handle_change_never_retargets_and_closes_only_owned_connection():
    shape, calls, disconnected = adapter()
    connection = shape.connection
    shape.widget.winId = lambda: 999
    assert shape.set_region([Rect()]) is False
    assert calls == [] and disconnected == [connection]
    assert not shape.available and shape.connection is None
    shape.close()
    assert disconnected == [connection]


def test_protocol_error_is_nonfatal_and_disables_the_adapter():
    shape, calls, disconnected = adapter()
    buffer = C.create_string_buffer(b"\x00" * 32)
    freed = []
    shape.xcb.xcb_poll_for_event = lambda _: C.addressof(buffer)
    shape.free = freed.append
    assert shape.set_region([Rect()]) is False
    assert not shape.available and calls == []
    assert len(disconnected) == len(freed) == 1


def test_failed_flush_closes_optional_connection():
    shape, calls, disconnected = adapter()
    shape.xcb.xcb_flush = lambda _: 0
    assert shape.set_region([Rect()]) is False
    assert len(calls) == len(disconnected) == 1
    assert shape.available is False


def test_missing_libraries_or_non_widget_never_open_a_connection(monkeypatch):
    monkeypatch.setattr(x11_input.C.util, "find_library", lambda _: None)
    for widget in (42, object(), SimpleNamespace(winId=lambda: 0), SimpleNamespace(winId=lambda: True),
                   SimpleNamespace(winId=lambda: 2**40), SimpleNamespace(winId=lambda: 42)):
        shape = x11_input.OwnWindowInputShape(widget)
        assert shape.available is False and shape.connection is None
        shape.close()


def test_ffi_surface_has_only_input_shape_and_nonfatal_connection_calls():
    source = inspect.getsource(x11_input)
    for forbidden in ("XShape", "XSetErrorHandler", "xcb_request_check", "xcb_wait_for_reply",
                      "xcb_grab", "xcb_set_input_focus", "xcb_send_event", "xcb_warp_pointer", "XTest"):
        assert forbidden not in source
    assert "self.connection, 0, 2, 0, self.window" in source


def test_region_matches_native_device_pixel_ratio_without_changing_visual_shape():
    shape, calls, _ = adapter()
    shape.widget.devicePixelRatioF = lambda: 2.
    assert shape.set_region([Rect()])
    assert calls[-1]["rectangles"] == [(2, 4, 60, 80)]
    assert calls[-1]["kind"] == 2
    assert not shape.set_region([Rect(x=32000)])
    assert len(calls) == 1


def test_deleted_qt_widget_is_a_safe_optional_adapter_failure():
    shape, calls, _ = adapter()
    def deleted():
        raise RuntimeError("Internal C++ object already deleted")
    shape.widget.winId = deleted
    assert not shape.set_region([Rect()])
    assert calls == []
