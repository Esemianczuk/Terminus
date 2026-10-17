"""Read-only CoreGraphics metadata queries. No event taps, AX or input changes.

Only plain geometry, an existing Input Monitoring permission check, cursor
position, and aggregate idle time leave this module. Window titles and owner
names are never accessed. All calls run in the disposable observer process.
"""
from __future__ import annotations

import ctypes as C
import math
import time


class Point(C.Structure):
    _fields_ = [("x", C.c_double), ("y", C.c_double)]


class Size(C.Structure):
    _fields_ = [("width", C.c_double), ("height", C.c_double)]


class Rect(C.Structure):
    _fields_ = [("origin", Point), ("size", Size)]


class MacMetadataBackend:
    source = "mac-readonly"

    def __init__(self, stop, own_pid):
        self.stop, self.own_pid = stop, own_pid
        self.cg = C.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        self.cf = C.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self._bind()
        self.keys = {}
        self.last_key = None
        self.next_windows = -math.inf
        self.window, self.windows = None, []
        self.permission_at = -math.inf
        self.typing_available = False
        bounds = self.cg.CGDisplayBounds(self.cg.CGMainDisplayID())
        self.screen = {"x": bounds.origin.x, "y": bounds.origin.y,
                       "width": bounds.size.width, "height": bounds.size.height}

    def _bind(self):
        def bind(lib, name, arguments, result):
            fn = getattr(lib, name)
            fn.argtypes, fn.restype = arguments, result
        p, u = C.c_void_p, C.c_uint32
        bind(self.cg, "CGMainDisplayID", [], u)
        bind(self.cg, "CGDisplayBounds", [u], Rect)
        bind(self.cg, "CGWindowListCopyWindowInfo", [u, u], p)
        bind(self.cg, "CGEventCreate", [p], p)
        bind(self.cg, "CGEventGetLocation", [p], Point)
        bind(self.cg, "CGEventSourceSecondsSinceLastEventType", [C.c_int, u], C.c_double)
        if hasattr(self.cg, "CGPreflightListenEventAccess"):
            bind(self.cg, "CGPreflightListenEventAccess", [], C.c_bool)
        bind(self.cf, "CFStringCreateWithCString", [p, C.c_char_p, u], p)
        bind(self.cf, "CFRelease", [p], None)
        bind(self.cf, "CFArrayGetCount", [p], C.c_long)
        bind(self.cf, "CFArrayGetValueAtIndex", [p, C.c_long], p)
        bind(self.cf, "CFDictionaryGetValue", [p, p], p)
        bind(self.cf, "CFNumberGetValue", [p, C.c_int, p], C.c_bool)

    def _value(self, mapping, name):
        if name not in self.keys:
            self.keys[name] = self.cf.CFStringCreateWithCString(None, name.encode("ascii"), 0x08000100)
        return self.cf.CFDictionaryGetValue(mapping, self.keys[name])

    def _number(self, mapping, name, default=0.):
        value = self._value(mapping, name)
        result = C.c_double()
        if value and self.cf.CFNumberGetValue(value, 13, C.byref(result)) and math.isfinite(result.value):
            return result.value
        return default

    def _window_metadata(self, now):
        if now < self.next_windows:
            return
        self.next_windows = now + 2
        # On-screen windows only, excluding desktop elements. No image capture.
        array = self.cg.CGWindowListCopyWindowInfo(1 | 16, 0)
        windows = []
        if array:
            try:
                for index in range(min(128, self.cf.CFArrayGetCount(array))):
                    record = self.cf.CFArrayGetValueAtIndex(array, index)
                    if self._number(record, "kCGWindowLayer", 1) != 0:
                        continue
                    if self._number(record, "kCGWindowAlpha", 0) <= .05:
                        continue
                    bounds = self._value(record, "kCGWindowBounds")
                    if not bounds:
                        continue
                    rect = {key: self._number(bounds, name) for key, name in
                            (("x", "X"), ("y", "Y"), ("width", "Width"), ("height", "Height"))}
                    if rect["width"] < 32 or rect["height"] < 32:
                        continue
                    rect["own"] = int(self._number(record, "kCGWindowOwnerPID", -1)) == self.own_pid
                    windows.append(rect)
                    if len(windows) == 32:
                        break
            finally:
                self.cf.CFRelease(array)
        self.windows = windows
        self.window = next((dict(rect) for rect in windows if not rect["own"]), None)

    def focused_window(self, now):
        # The frontmost normal window is a geometric approximation, not an AX
        # focused text control. Do not query accessibility or request permission.
        self._window_metadata(now)
        return dict(self.window) if self.window else None

    def keypresses(self):
        now = time.monotonic()
        if now - self.permission_at >= 30:
            self.permission_at = now
            preflight = getattr(self.cg, "CGPreflightListenEventAccess", None)
            self.typing_available = bool(preflight and preflight())
        if not self.typing_available:
            self.last_key = None
            return 0
        age = self.cg.CGEventSourceSecondsSinceLastEventType(0, 10)
        if not math.isfinite(age) or age < 0 or age > 86400:
            return 0
        last = now - age
        # Idle timestamps yield a coarse pulse. They never yield a keycode.
        changed = self.last_key is not None and last > self.last_key + .025 and age <= .5
        self.last_key = last
        return int(changed)

    def pointer(self):
        event = self.cg.CGEventCreate(None)
        if not event:
            return None
        try:
            point = self.cg.CGEventGetLocation(event)
            return {"x": point.x, "y": point.y, "screen": dict(self.screen)}
        finally:
            self.cf.CFRelease(event)

    def visible_windows(self, now):
        self._window_metadata(now)
        return [dict(rect) for rect in self.windows]

    def microphone_status(self):
        # No microphone or audio API is opened. A future platform adapter may
        # report the system's existing in-use flag, with no audio permission.
        return None

    def close(self):
        for key in self.keys.values():
            self.cf.CFRelease(key)
        self.keys.clear()
