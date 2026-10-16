"""Local X11 geometry and typing rhythm, without text or key identities.

The UI reads ``DesktopAwareness.snapshot()``; this module never sends events,
keeps an outbox, captures pixels, or reads titles/clipboard/application text.
XI2 packets are inspected only through their generic ten-byte event header.
The key-detail field is never decoded. Counts live in a bounded four-second ring.

Coordinates are X11 screen pixels. A caret is supplied only by an optional,
focused accessibility provider; the default is explicitly a window fallback.
XCB uses a separate connection with bounded, interruptible reply waits, avoiding
process-global Xlib error handlers and fatal errors from disappearing windows.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
import ctypes as C
import ctypes.util
import math
import os
import struct
import threading
import time


class _Cookie(C.Structure):
    _fields_ = [("sequence", C.c_uint)]


class _Iterator(C.Structure):
    _fields_ = [("data", C.c_void_p), ("remaining", C.c_int), ("index", C.c_int)]


class _Extension(C.Structure):
    _fields_ = [("response", C.c_uint8), ("pad", C.c_uint8), ("sequence", C.c_uint16),
                ("length", C.c_uint32), ("present", C.c_uint8), ("opcode", C.c_uint8)]


class _Version(C.Structure):
    _fields_ = [("response", C.c_uint8), ("pad", C.c_uint8), ("sequence", C.c_uint16),
                ("length", C.c_uint32), ("major", C.c_uint16), ("minor", C.c_uint16)]


class _Atom(C.Structure):
    _fields_ = [("response", C.c_uint8), ("pad", C.c_uint8), ("sequence", C.c_uint16),
                ("length", C.c_uint32), ("atom", C.c_uint32)]


class _Property(C.Structure):
    _fields_ = [("response", C.c_uint8), ("format", C.c_uint8), ("sequence", C.c_uint16),
                ("length", C.c_uint32), ("type", C.c_uint32), ("remaining", C.c_uint32),
                ("items", C.c_uint32), ("pad", C.c_uint8 * 12)]


class _Geometry(C.Structure):
    _fields_ = [("response", C.c_uint8), ("depth", C.c_uint8), ("sequence", C.c_uint16),
                ("length", C.c_uint32), ("root", C.c_uint32), ("x", C.c_int16),
                ("y", C.c_int16), ("width", C.c_uint16), ("height", C.c_uint16)]


class _Translation(C.Structure):
    _fields_ = [("response", C.c_uint8), ("same_screen", C.c_uint8), ("sequence", C.c_uint16),
                ("length", C.c_uint32), ("child", C.c_uint32), ("x", C.c_int16), ("y", C.c_int16)]


class _InputMask(C.Structure):
    _fields_ = [("device", C.c_uint16), ("length", C.c_uint16), ("bits", C.c_uint32)]


def _rectangle(value):
    if not isinstance(value, dict):
        return None
    try:
        result = {key: float(value[key]) for key in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(number) and abs(number) <= 1_000_000 for number in result.values()):
        return None
    if result["width"] < 0 or result["height"] <= 0:
        return None
    result["width"] = max(1.0, result["width"])
    return result


class _TypingRhythm:
    """Aggregate sample buckets only; no individual key identity or timestamp."""

    def __init__(self):
        self.samples = deque(maxlen=128)
        self.last_at = None
        self.sequence = 0

    def clear(self):
        self.samples.clear()
        self.last_at = None

    def note(self, count, now):
        if count > 0:
            self.samples.append((now, min(int(count), 10_000)))
            self.last_at = now
            self.sequence += 1  # One aggregate pulse, not a key identity/count.

    def state(self, now):
        while self.samples and self.samples[0][0] < now - 4:
            self.samples.popleft()
        age = math.inf if self.last_at is None else max(0.0, now - self.last_at)
        return {"active": age <= 1.1, "last_at": self.last_at,
                "rate": min(20.0, sum(count for _, count in self.samples) / 4),
                "pulse": math.exp(-age / .5), "sequence": self.sequence}


class _XcbBackend:
    """Own one nonfatal XCB connection, used exclusively by its worker thread."""

    def __init__(self, stop, own_pid):
        self.stop = stop
        self.own_pid = own_pid
        self.connection = None
        self.window_id = None
        self.window_cache = None
        self.geometry_at = -math.inf
        xcb_path, input_path = C.util.find_library("xcb"), C.util.find_library("xcb-xinput")
        if not xcb_path or not input_path:
            raise RuntimeError("xinput2_libraries_unavailable")
        self.xcb, self.input = C.CDLL(xcb_path), C.CDLL(input_path)
        self.free = C.CDLL(None).free
        self.free.argtypes, self.free.restype = [C.c_void_p], None
        self._bind()
        try:
            screen_number = C.c_int()
            self.connection = self.xcb.xcb_connect(None, C.byref(screen_number))
            if not self.connection or self.xcb.xcb_connection_has_error(self.connection):
                raise RuntimeError("x11_connection_unavailable")
            screens = self.xcb.xcb_setup_roots_iterator(self.xcb.xcb_get_setup(self.connection))
            for _ in range(screen_number.value):
                self.xcb.xcb_screen_next(C.byref(screens))
            if not screens.data or screens.remaining < 1:
                raise RuntimeError("x11_screen_unavailable")
            self.root = C.cast(screens.data, C.POINTER(C.c_uint32)).contents.value
            extension = self._reply(self.xcb.xcb_query_extension(self.connection, 15, b"XInputExtension"), _Extension)
            if not extension.present:
                raise RuntimeError("xinput2_unavailable")
            self.opcode = extension.opcode
            version = self._reply(self.input.xcb_input_xi_query_version(self.connection, 2, 0), _Version)
            if version.major < 2:
                raise RuntimeError("xinput2_unavailable")
            self.active_atom = self._atom(b"_NET_ACTIVE_WINDOW")
            self.pid_atom = self._atom(b"_NET_WM_PID")
            # XIAllMasterDevices, one 32-bit mask word, XI_RawKeyPress only.
            mask = _InputMask(1, 1, 1 << 13)
            self.input.xcb_input_xi_select_events(self.connection, self.root, 1, C.byref(mask))
            self.xcb.xcb_flush(self.connection)
        except BaseException:
            self.close()
            raise

    def _bind(self):
        def bind(library, name, arguments, result):
            function = getattr(library, name)
            function.argtypes, function.restype = arguments, result
        pointer, u32 = C.c_void_p, C.c_uint32
        bind(self.xcb, "xcb_connect", [C.c_char_p, C.POINTER(C.c_int)], pointer)
        bind(self.xcb, "xcb_disconnect", [pointer], None)
        bind(self.xcb, "xcb_connection_has_error", [pointer], C.c_int)
        bind(self.xcb, "xcb_get_setup", [pointer], pointer)
        bind(self.xcb, "xcb_setup_roots_iterator", [pointer], _Iterator)
        bind(self.xcb, "xcb_screen_next", [C.POINTER(_Iterator)], None)
        bind(self.xcb, "xcb_flush", [pointer], C.c_int)
        bind(self.xcb, "xcb_poll_for_reply", [pointer, C.c_uint, C.POINTER(pointer), C.POINTER(pointer)], C.c_int)
        bind(self.xcb, "xcb_discard_reply", [pointer, C.c_uint], None)
        bind(self.xcb, "xcb_poll_for_event", [pointer], pointer)
        bind(self.xcb, "xcb_query_extension", [pointer, C.c_uint16, C.c_char_p], _Cookie)
        bind(self.xcb, "xcb_intern_atom", [pointer, C.c_uint8, C.c_uint16, C.c_char_p], _Cookie)
        bind(self.xcb, "xcb_get_property", [pointer, C.c_uint8, u32, u32, u32, u32, u32], _Cookie)
        bind(self.xcb, "xcb_get_property_value", [pointer], pointer)
        bind(self.xcb, "xcb_get_property_value_length", [pointer], C.c_int)
        bind(self.xcb, "xcb_get_geometry", [pointer, u32], _Cookie)
        bind(self.xcb, "xcb_translate_coordinates", [pointer, u32, u32, C.c_int16, C.c_int16], _Cookie)
        bind(self.input, "xcb_input_xi_query_version", [pointer, C.c_uint16, C.c_uint16], _Cookie)
        bind(self.input, "xcb_input_xi_select_events", [pointer, u32, C.c_uint16, pointer], _Cookie)

    def _wait(self, cookie):
        reply, error = C.c_void_p(), C.c_void_p()
        deadline = time.monotonic() + .25
        self.xcb.xcb_flush(self.connection)
        while not self.stop.is_set() and time.monotonic() < deadline:
            if self.xcb.xcb_connection_has_error(self.connection):
                raise RuntimeError("x11_disconnected")
            if self.xcb.xcb_poll_for_reply(self.connection, cookie.sequence, C.byref(reply), C.byref(error)):
                if error.value:
                    self.free(error)
                    if reply.value:
                        self.free(reply)
                    raise RuntimeError("x11_request_failed")
                if not reply.value:
                    raise RuntimeError("x11_reply_unavailable")
                return reply
            self.stop.wait(.005)
        self.xcb.xcb_discard_reply(self.connection, cookie.sequence)
        raise TimeoutError("x11_reply_timeout")

    def _reply(self, cookie, structure):
        reply = self._wait(cookie)
        try:
            return structure.from_buffer_copy(C.string_at(reply, C.sizeof(structure)))
        finally:
            self.free(reply)

    def _atom(self, name):
        return self._reply(self.xcb.xcb_intern_atom(self.connection, 1, len(name), name), _Atom).atom

    def _property(self, window, atom):
        if not atom:
            return None
        reply = self._wait(self.xcb.xcb_get_property(self.connection, 0, window, atom, 0, 0, 1))
        try:
            header = C.cast(reply, C.POINTER(_Property)).contents
            if header.format != 32 or self.xcb.xcb_get_property_value_length(reply) < 4:
                return None
            return C.cast(self.xcb.xcb_get_property_value(reply), C.POINTER(C.c_uint32)).contents.value
        finally:
            self.free(reply)

    def focused_window(self, now):
        try:
            window = self._property(self.root, self.active_atom)
            if not window:
                self.window_id, self.window_cache = None, None
                return None
            if window == self.window_id and now - self.geometry_at < 2:
                return deepcopy(self.window_cache)
            geometry = self._reply(self.xcb.xcb_get_geometry(self.connection, window), _Geometry)
            position = self._reply(self.xcb.xcb_translate_coordinates(self.connection, window, self.root, 0, 0), _Translation)
            bounds = _rectangle({"x": position.x, "y": position.y, "width": geometry.width, "height": geometry.height})
            if bounds is None:
                return None
            bounds["own"] = self._property(window, self.pid_atom) == self.own_pid
            self.window_id, self.window_cache, self.geometry_at = window, bounds, now
            return deepcopy(bounds)
        except (RuntimeError, TimeoutError):
            # Closing a focused window races geometry requests routinely.
            self.window_id, self.window_cache = None, None
            return None

    def keypresses(self):
        count = 0
        for _ in range(1024):
            event = self.xcb.xcb_poll_for_event(self.connection)
            if not event:
                break
            try:
                # XGE header only. In particular, never read XI2's detail field.
                response, extension, _, _, event_type = struct.unpack("=BBHIH", C.string_at(event, 10))
                if response == 0:
                    raise RuntimeError("x11_event_selection_failed")
                if response == 35 and extension == self.opcode and event_type == 13:
                    count += 1
            finally:
                self.free(event)
        if self.xcb.xcb_connection_has_error(self.connection):
            raise RuntimeError("x11_disconnected")
        return count

    def close(self):
        if self.connection:
            self.xcb.xcb_disconnect(self.connection)
            self.connection = None


class DesktopAwareness:
    """Bounded local observer; call start/snapshot/close from the UI thread.

    ``caret_provider(window)`` may return ``{"rect": bounds, "secure": bool}``.
    It must inspect only the focused accessibility object and never fetch text.
    With no such provider installed, caret remains None and window-fallback is
    reported explicitly. Unknown secure-entry status is never claimed as safe.
    """

    def __init__(self, enabled=True, poll_interval=.5, own_pid=None, *,
                 clock=time.monotonic, backend_factory=None, caret_provider=None, environment=None):
        self.enabled = bool(enabled)
        self.poll_interval = max(.1, float(poll_interval))
        self.own_pid = os.getpid() if own_pid is None else own_pid
        self.clock = clock
        self.backend_factory = backend_factory or _XcbBackend
        self.caret_provider = caret_provider
        self.environment = dict(os.environ if environment is None else environment)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.current = self._empty("disabled" if not self.enabled else "starting")

    def _empty(self, reason, permission=None):
        return {"enabled": self.enabled, "available": False, "observed_at": self.clock(),
                "focused_window": None, "typing": None, "caret": None, "secure_entry": None,
                "permission": permission or ("disabled" if not self.enabled else "local-observation"),
                "source": "unavailable", "caret_source": "window-fallback", "reason": reason}

    def start(self):
        if self.thread is not None or not self.enabled:
            return self
        session = self.environment.get("XDG_SESSION_TYPE", "")
        if session == "wayland" or (self.environment.get("WAYLAND_DISPLAY") and session != "x11"):
            self.current = self._empty("wayland_unsupported", "unsupported")
        elif not self.environment.get("DISPLAY"):
            self.current = self._empty("x11_display_unavailable", "unsupported")
        else:
            self.thread = threading.Thread(target=self._run, name="terminus-awareness", daemon=True)
            self.thread.start()
        return self

    def _publish(self, snapshot):
        if not self.stop_event.is_set():
            with self.lock:
                self.current = snapshot

    def _run(self):
        backend = None
        rhythm = _TypingRhythm()
        window, caret, secure = None, None, None
        next_poll = -math.inf
        try:
            backend = self.backend_factory(self.stop_event, self.own_pid)
            while not self.stop_event.is_set():
                now = self.clock()
                if now >= next_poll:
                    window = backend.focused_window(now)
                    caret, secure = None, None
                    if self.caret_provider is not None and window is not None:
                        try:
                            result = self.caret_provider(deepcopy(window))
                            if isinstance(result, dict) and result.get("available") is not False and result.get("fresh") is not False:
                                secure = result.get("secure") if isinstance(result.get("secure"), bool) else None
                                caret = _rectangle(result.get("rect")) if secure is not True else None
                                if caret and not (window["x"] - 2 <= caret["x"]
                                                  and window["y"] - 2 <= caret["y"]
                                                  and caret["x"] + caret["width"] <= window["x"] + window["width"] + 2
                                                  and caret["y"] + caret["height"] <= window["y"] + window["height"] + 2):
                                    caret = None
                        except Exception:
                            pass  # Optional accessibility never disables XI2.
                    next_poll = now + self.poll_interval
                if self.stop_event.is_set():
                    break
                count = backend.keypresses()
                if secure is True:
                    rhythm.clear()
                else:
                    rhythm.note(count, now)
                self._publish({"enabled": True, "available": True, "observed_at": now,
                               "focused_window": deepcopy(window), "typing": rhythm.state(now),
                               "caret": caret, "secure_entry": secure,
                               "permission": "local-observation", "source": "x11-xinput2",
                               "caret_source": "at-spi" if caret else "window-fallback", "reason": None})
                self.stop_event.wait(.05)
        except Exception as error:
            self._publish(self._empty(type(error).__name__, "unsupported"))
        finally:
            if backend is not None:
                backend.close()

    def snapshot(self):
        with self.lock:
            return deepcopy(self.current)

    def close(self, timeout=1.0):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(max(0.0, float(timeout)))
        self.enabled = False
        with self.lock:
            self.current = self._empty("stopped", "disabled")
        return self.thread is None or not self.thread.is_alive()
