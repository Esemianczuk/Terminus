"""Set only our own X11 Input shape, independently of visible GPU pixels.

There are no keyboard, focus, grab, pointer-warp or synthetic-event bindings.
The visual Bounding and Clip shapes are never modified. XCB protocol errors
are polled without a reply wait and disable this optional adapter.
"""
from __future__ import annotations

import ctypes as C
import ctypes.util
import math


MAX_RECTANGLES = 4096


class _Cookie(C.Structure):
    _fields_ = [("sequence", C.c_uint)]


class _Rectangle(C.Structure):
    _fields_ = [("x", C.c_int16), ("y", C.c_int16), ("width", C.c_uint16), ("height", C.c_uint16)]


class OwnWindowInputShape:
    """One connection, bound to the native handle of the supplied widget.

    Construct after widget.show() on an XCB Qt platform. Check available and
    every set_region result. Failure must select raster rendering with its
    normal widget mask, rather than leave a full rectangle intercepting clicks.
    """

    def __init__(self, widget):
        self.widget = widget
        self.connection = None
        self.available = False
        self.error = None
        self.window = None
        try:
            handle = widget.winId()
            if type(handle) is not int:
                raise ValueError("invalid_native_window")
            self.window = int(handle)
            if not 1 <= self.window <= 0xffffffff:
                raise ValueError("invalid_native_window")
            xcb_path, shape_path = C.util.find_library("xcb"), C.util.find_library("xcb-shape")
            if not xcb_path or not shape_path:
                raise OSError("xcb_shape_unavailable")
            self.xcb, self.shape = C.CDLL(xcb_path), C.CDLL(shape_path)
            self.free = C.CDLL(None).free
            self.free.argtypes, self.free.restype = [C.c_void_p], None
            self._bind()
            screen = C.c_int()
            self.connection = self.xcb.xcb_connect(None, C.byref(screen))
            if not self.connection or self.xcb.xcb_connection_has_error(self.connection):
                raise OSError("xcb_connection_unavailable")
            self.available = True
        except (AttributeError, TypeError, ValueError, OverflowError, OSError, RuntimeError):
            self.error = "input_shape_unavailable"
            self.close()

    def _bind(self):
        def bind(lib, name, arguments, result):
            function = getattr(lib, name)
            function.argtypes, function.restype = arguments, result
        pointer = C.c_void_p
        bind(self.xcb, "xcb_connect", [C.c_char_p, C.POINTER(C.c_int)], pointer)
        bind(self.xcb, "xcb_disconnect", [pointer], None)
        bind(self.xcb, "xcb_connection_has_error", [pointer], C.c_int)
        bind(self.xcb, "xcb_flush", [pointer], C.c_int)
        bind(self.xcb, "xcb_poll_for_event", [pointer], pointer)
        bind(self.shape, "xcb_shape_rectangles", [pointer, C.c_uint8, C.c_uint8, C.c_uint8,
                                                C.c_uint32, C.c_int16, C.c_int16, C.c_uint32,
                                                C.POINTER(_Rectangle)], _Cookie)

    def _transport_ok(self):
        if not self.connection or self.xcb.xcb_connection_has_error(self.connection):
            return False
        for _ in range(8):
            event = self.xcb.xcb_poll_for_event(self.connection)
            if not event:
                return True
            try:
                if C.cast(event, C.POINTER(C.c_uint8)).contents.value == 0:
                    return False
            finally:
                self.free(event)
        return True

    def set_region(self, region):
        if not self.available:
            return False
        try:
            # A recreated Qt native window invalidates this adapter. It must
            # never silently retarget an arbitrary external window identifier.
            if int(self.widget.winId()) != self.window:
                self.error = "native_window_changed"
                self.close()
                return False
            ratio = float(getattr(self.widget, "devicePixelRatioF", lambda: 1.)())
            if not math.isfinite(ratio) or not .25 <= ratio <= 8.:
                self.error = "invalid_device_pixel_ratio"
                return False
            rectangles = []
            for index, rect in enumerate(region):
                if index >= MAX_RECTANGLES:
                    self.error = "input_region_too_large"
                    return False
                values = tuple(getattr(rect, name)() for name in ("x", "y", "width", "height"))
                if (any(type(value) is not int for value in values)
                        or not -32768 <= values[0] <= 32767 or not -32768 <= values[1] <= 32767
                        or not 0 <= values[2] <= 65535 or not 0 <= values[3] <= 65535):
                    self.error = "invalid_input_rectangle"
                    return False
                # Qt regions use logical widget pixels; X11 Shape uses native
                # pixels. Match Qt's native scaling without changing geometry.
                scaled = tuple(int(round(value * ratio)) for value in values)
                if (not -32768 <= scaled[0] <= 32767 or not -32768 <= scaled[1] <= 32767
                        or not 0 <= scaled[2] <= 65535 or not 0 <= scaled[3] <= 65535):
                    self.error = "invalid_scaled_input_rectangle"
                    return False
                if scaled[2] and scaled[3]:
                    rectangles.append(_Rectangle(*scaled))
        except (AttributeError, TypeError, ValueError, OverflowError, RuntimeError):
            self.error = "invalid_input_region"
            return False
        if not self._transport_ok():
            self.error = "xcb_connection_failed"
            self.close()
            return False
        array = (_Rectangle * len(rectangles))(*rectangles) if rectangles else None
        # Shape Set=0, destination Input=2, Unsorted=0. Never Bounding=0 or Clip=1.
        cookie = self.shape.xcb_shape_rectangles(self.connection, 0, 2, 0, self.window, 0, 0,
                                                 len(rectangles), array)
        if (not cookie.sequence or self.xcb.xcb_flush(self.connection) <= 0 or not self._transport_ok()):
            self.error = "xcb_shape_failed"
            self.close()
            return False
        self.error = None
        return True

    def close(self):
        self.available = False
        if self.connection:
            self.xcb.xcb_disconnect(self.connection)
            self.connection = None
