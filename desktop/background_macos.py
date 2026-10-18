"""A transient, two-by-two colour sample of windows beneath our own panel.

No text recognition, full-screen capture, input hooks, files or networking. The
caller runs capture() in its bounded worker. Screen Recording permission is
checked without prompting; request_access() is reserved for an explicit user
action. The full cropped image is released before capture() returns.
"""
from __future__ import annotations

import ctypes
import math
import os


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _Size(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _Rect(ctypes.Structure):
    _fields_ = [("origin", _Point), ("size", _Size)]


def _rectangle(values):
    try:
        x, y, width, height = (float(value) for value in values)
    except (TypeError, ValueError):
        return None
    if (not all(math.isfinite(value) for value in (x, y, width, height))
            or abs(x) > 100000 or abs(y) > 100000
            or not 1 <= width <= 1024 or not 1 <= height <= 1024):
        return None
    return _Rect(_Point(x, y), _Size(width, height))


class _CoreGraphics:
    """Own CF objects explicitly so sampling never accumulates frame buffers."""
    def __init__(self):
        self.library = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
        self.cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        definitions = {
            'CGPreflightScreenCaptureAccess': (ctypes.c_bool, []),
            'CGRequestScreenCaptureAccess': (ctypes.c_bool, []),
            'CGWindowListCopyWindowInfo': (ctypes.c_void_p, [ctypes.c_uint32, ctypes.c_uint32]),
            'CGWindowListCreateImage': (ctypes.c_void_p, [_Rect, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]),
            'CGImageGetWidth': (ctypes.c_size_t, [ctypes.c_void_p]),
            'CGImageGetHeight': (ctypes.c_size_t, [ctypes.c_void_p]),
            'CGColorSpaceCreateDeviceRGB': (ctypes.c_void_p, []),
            'CGBitmapContextCreate': (ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t,
                                                     ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_uint32]),
            'CGContextDrawImage': (None, [ctypes.c_void_p, _Rect, ctypes.c_void_p]),
            'CGContextSetInterpolationQuality': (None, [ctypes.c_void_p, ctypes.c_int]),
        }
        for name, (result, arguments) in definitions.items():
            function = getattr(self.library, name)
            function.restype, function.argtypes = result, arguments
            setattr(self, name, function)
        self.release = self.cf.CFRelease
        self.release.argtypes, self.release.restype = [ctypes.c_void_p], None

    def reduce(self, image, width=2, height=2):
        """Resample in CoreGraphics to bounded canonical premultiplied RGBA."""
        pixels = (ctypes.c_uint8 * (width * height * 4))()
        colour_space = self.CGColorSpaceCreateDeviceRGB()
        if not colour_space:
            return None
        context = None
        try:
            # Big-endian 32-bit + premultiplied-last has RGBA byte order.
            context = self.CGBitmapContextCreate(pixels, width, height, 8, width * 4,
                                                 colour_space, 0x4001)
            if not context:
                return None
            self.CGContextSetInterpolationQuality(context, 3)
            self.CGContextDrawImage(context, _Rect(_Point(0, 0), _Size(width, height)), image)
            return bytes(pixels)
        finally:
            if context:
                self.release(context)
            self.release(colour_space)


class MacBackground:
    def __init__(self):
        self._api = _CoreGraphics()
        self.reason = None

    @property
    def available(self):
        permitted = bool(self._api.CGPreflightScreenCaptureAccess())
        self.reason = None if permitted else 'screen_recording_permission_required'
        return permitted

    def _own_window(self, own_pid):
        import objc
        pointer = self._api.CGWindowListCopyWindowInfo(1, 0)
        if not pointer:
            return None
        try:
            rows = objc.objc_object(c_void_p=pointer)
            windows = [row for row in rows if int(row.get('kCGWindowOwnerPID', 0)) == own_pid
                       and int(row.get('kCGWindowLayer', 0)) == 21
                       and row.get('kCGWindowIsOnscreen', False)]
            if not windows:
                return None
            selected = max(windows, key=lambda row: float(row.get('kCGWindowBounds', {}).get('Width', 0))
                           * float(row.get('kCGWindowBounds', {}).get('Height', 0)))
            return int(selected['kCGWindowNumber'])
        finally:
            self._api.release(pointer)

    def _colours(self, rect, own_pid):
        rectangle = _rectangle(rect)
        if (rectangle is None or type(own_pid) is not int
                or own_pid not in (os.getpid(), os.getppid())):
            self.reason = 'invalid_own_window_crop'
            return None
        if not self.available:
            return None
        window = self._own_window(own_pid)
        if window is None:
            self.reason = 'own_panel_unavailable'
            return None
        # kCGWindowListOptionOnScreenBelowWindow excludes our own creature and
        # everything above it, preventing a camouflage feedback loop.
        image = self._api.CGWindowListCreateImage(rectangle, 4, window, 1 | 16)
        if not image:
            self.reason = 'background_capture_unavailable'
            return None
        try:
            pixels = self._api.reduce(image)
            if pixels is None:
                self.reason = 'background_reduction_unavailable'
                return None
            # Memory order is top row then bottom row. Undo premultiplication;
            # transparent gaps are discarded instead of being read as black.
            colours = []
            for offset in range(0, 16, 4):
                alpha = pixels[offset + 3]
                if alpha < 8:
                    self.reason = 'background_transparent'
                    return None
                colours.append(tuple(min(1., pixels[offset + channel] / alpha) for channel in range(3)))
            self.reason = None
            return tuple(colours)
        finally:
            self._api.release(image)

    def capture(self, rect, own_pid):
        colours = self._colours(rect, own_pid)
        if colours is None:
            return {'available': False, 'reason': self.reason or 'background_capture_unavailable'}
        return {'available': True, 'colors': [list(colour) for colour in colours]}

    def close(self):
        # No stream, persistent native object, image or input registration.
        pass


def request_access():
    """Ask macOS once, only when the user enables screen camouflage."""
    return bool(_CoreGraphics().CGRequestScreenCaptureAccess())
