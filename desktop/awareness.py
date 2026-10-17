"""Disposable read-only desktop metadata and coarse input rhythm.

The UI reads ``DesktopAwareness.snapshot()``; this module never sends events,
keeps an outbox, captures pixels, or reads titles/clipboard/application text.
XI2 packets are inspected only through their generic ten-byte event header.
The key-detail field is never decoded. Counts live in a bounded four-second ring.

Window coordinates remain local screen pixels; cursor and visual summaries are
normalized. Exact caret observation has been retired. OS metadata queries run
in a disposable child process with bounded IPC, stale detection and teardown.
XCB uses bounded interruptible reply waits and no process-global Xlib handlers.
The macOS backend uses permission-preflighted idle queries, never an event tap.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
import ctypes as C
import ctypes.util
import math
import os
from pathlib import Path
import select
import struct
import subprocess
import sys
import json
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


class _Attributes(C.Structure):
    _fields_ = [("response", C.c_uint8), ("backing", C.c_uint8), ("sequence", C.c_uint16),
                ("length", C.c_uint32), ("visual", C.c_uint32), ("window_class", C.c_uint16),
                ("bit_gravity", C.c_uint8), ("win_gravity", C.c_uint8), ("planes", C.c_uint32),
                ("pixel", C.c_uint32), ("save", C.c_uint8), ("installed", C.c_uint8),
                ("map_state", C.c_uint8), ("override", C.c_uint8)]


class _Pointer(C.Structure):
    _fields_ = [("response", C.c_uint8), ("same_screen", C.c_uint8), ("sequence", C.c_uint16),
                ("length", C.c_uint32), ("root", C.c_uint32), ("child", C.c_uint32),
                ("root_x", C.c_int16), ("root_y", C.c_int16), ("x", C.c_int16),
                ("y", C.c_int16)]


class _InputMask(C.Structure):
    _fields_ = [("device", C.c_uint16), ("length", C.c_uint16), ("bits", C.c_uint32)]


def _rectangle(value):
    if not isinstance(value, dict):
        return None
    try:
        if any(type(value[key]) not in (int, float) for key in ("x", "y", "width", "height")):
            return None
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
        self.bout_start = None
        self.bout_sequence = 0

    def clear(self):
        self.samples.clear()
        self.last_at = None
        self.bout_start = None

    def note(self, count, now):
        if count > 0:
            if self.last_at is None or now - self.last_at > 1.1:
                self.bout_start = now
                self.bout_sequence += 1
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

    def bout(self, now):
        state = self.state(now)
        age = math.inf if self.last_at is None else max(0., now - self.last_at)
        duration = max(0., (self.last_at if self.last_at is not None else now) - (self.bout_start if self.bout_start is not None else now))
        # A single key or shortcut cannot count as heavy computer use.
        level = min(1., state["rate"] / 4) * min(1., duration / 1.2)
        return {"phase": "active" if state["active"] else "pause" if age <= 8 else "idle",
                "duration_s": min(120., duration), "level": round(level, 3),
                "pause_age_s": min(120., age), "sequence": self.bout_sequence}


class _XcbBackend:
    """Own one nonfatal XCB connection, used exclusively by its worker thread."""

    source = "x11-xinput2"
    typing_available = True

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
            screen = struct.unpack("=IIIIIHH", C.string_at(screens.data, 24))
            self.root = screen[0]
            self.screen = {"x": 0., "y": 0., "width": float(screen[5]), "height": float(screen[6])}
            extension = self._reply(self.xcb.xcb_query_extension(self.connection, 15, b"XInputExtension"), _Extension)
            if not extension.present:
                raise RuntimeError("xinput2_unavailable")
            self.opcode = extension.opcode
            version = self._reply(self.input.xcb_input_xi_query_version(self.connection, 2, 0), _Version)
            if version.major < 2:
                raise RuntimeError("xinput2_unavailable")
            self.active_atom = self._atom(b"_NET_ACTIVE_WINDOW")
            self.pid_atom = self._atom(b"_NET_WM_PID")
            self.windows_atom = self._atom(b"_NET_CLIENT_LIST_STACKING")
            self.current_desktop_atom = self._atom(b"_NET_CURRENT_DESKTOP")
            self.desktop_atom = self._atom(b"_NET_WM_DESKTOP")
            self.next_windows, self.windows_cache = -math.inf, []
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
        bind(self.xcb, "xcb_query_pointer", [pointer, u32], _Cookie)
        bind(self.xcb, "xcb_get_window_attributes", [pointer, u32], _Cookie)
        bind(self.xcb, "xcb_translate_coordinates", [pointer, u32, u32, C.c_int16, C.c_int16], _Cookie)
        bind(self.input, "xcb_input_xi_query_version", [pointer, C.c_uint16, C.c_uint16], _Cookie)
        bind(self.input, "xcb_input_xi_select_events", [pointer, u32, C.c_uint16, pointer], _Cookie)

    def _wait(self, cookie):
        reply, error = C.c_void_p(), C.c_void_p()
        deadline = min(time.monotonic() + .25, getattr(self, "query_deadline", math.inf))
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

    def _property_values(self, window, atom, limit=32):
        if not atom:
            return []
        reply = self._wait(self.xcb.xcb_get_property(self.connection, 0, window, atom, 0, 0, limit))
        try:
            header = C.cast(reply, C.POINTER(_Property)).contents
            size = self.xcb.xcb_get_property_value_length(reply)
            if header.format != 32 or size < 4:
                return []
            count = min(limit, size // 4)
            return list(struct.unpack("=" + "I" * count,
                                    C.string_at(self.xcb.xcb_get_property_value(reply), count * 4)))
        finally:
            self.free(reply)

    def pointer(self):
        reply = self._reply(self.xcb.xcb_query_pointer(self.connection, self.root), _Pointer)
        if not reply.same_screen:
            return None
        return {"x": reply.root_x, "y": reply.root_y, "screen": dict(self.screen)}

    def visible_windows(self, now):
        if now < self.next_windows:
            return deepcopy(self.windows_cache)
        self.next_windows = now + 2
        result = []
        self.query_deadline = time.monotonic() + .18
        try:
            current = self._property(self.root, self.current_desktop_atom)
            ids = self._property_values(self.root, self.windows_atom, 32)
            for window in reversed(ids):
                if time.monotonic() >= self.query_deadline:
                    break
                try:
                    desktop = self._property(window, self.desktop_atom)
                    if desktop is not None and current is not None and desktop not in (current, 0xffffffff):
                        continue
                    attributes = self._reply(self.xcb.xcb_get_window_attributes(self.connection, window), _Attributes)
                    if attributes.map_state != 2:
                        continue
                    geometry = self._reply(self.xcb.xcb_get_geometry(self.connection, window), _Geometry)
                    position = self._reply(self.xcb.xcb_translate_coordinates(self.connection, window, self.root, 0, 0), _Translation)
                    bounds = _rectangle({"x": position.x, "y": position.y,
                                         "width": geometry.width, "height": geometry.height})
                    if bounds and bounds["width"] >= 32 and bounds["height"] >= 32:
                        result.append(bounds)
                except (RuntimeError, TimeoutError):
                    continue
        finally:
            self.query_deadline = math.inf
        self.windows_cache = result
        return deepcopy(result)

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



MAX_SNAPSHOT = 16384
STALE_AFTER = 4.
CHILD_ENVIRONMENT = frozenset({"DISPLAY", "XAUTHORITY", "XAUTHLOCALHOSTNAME", "WAYLAND_DISPLAY",
                               "XDG_SESSION_TYPE", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS",
                               "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "PULSE_SERVER",
                               "PULSE_COOKIE", "__CF_USER_TEXT_ENCODING"})


def _window_summary(windows, screen):
    if not isinstance(windows, list) or not screen:
        return {"available": False, "count": 0, "coverage": 0., "rects": []}
    width, height = max(1., screen["width"]), max(1., screen["height"])
    clean = []
    area = 0.
    for value in windows[:32]:
        rect = _rectangle(value)
        if not rect:
            continue
        x = max(0., min(1., (rect["x"] - screen["x"]) / width))
        y = max(0., min(1., (rect["y"] - screen["y"]) / height))
        right = max(0., min(1., (rect["x"] + rect["width"] - screen["x"]) / width))
        bottom = max(0., min(1., (rect["y"] + rect["height"] - screen["y"]) / height))
        normalized = {"x": round(x, 3), "y": round(y, 3),
                      "width": round(max(0., right - x), 3), "height": round(max(0., bottom - y), 3)}
        area += normalized["width"] * normalized["height"]
        clean.append(normalized)
    # Coverage is a coarse clipped sum, not an image/occlusion reconstruction.
    return {"available": True, "count": len(clean), "coverage": round(min(1., area), 3), "rects": clean[:8]}


class _MicrophoneStatus:
    """Linux audio-server metadata only. Never opens an audio source/stream."""

    def __init__(self):
        self.next_at, self.current = -math.inf, None

    def sample(self, now):
        if now < self.next_at:
            return self.current
        self.next_at = now + 3
        self.current = None
        if sys.platform != "linux":
            return None
        process = None
        try:
            process = subprocess.Popen(["pactl", "list", "short", "source-outputs"],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, close_fds=True)
            deadline, seen, size = time.monotonic() + .25, False, 0
            while time.monotonic() < deadline:
                ready, _, _ = select.select([process.stdout], [], [], max(0., deadline-time.monotonic()))
                if not ready:
                    break
                block = os.read(process.stdout.fileno(), 4096)
                if not block:
                    if process.wait(timeout=.05) == 0:
                        self.current = seen
                    break
                size += len(block)
                if size > 65536:
                    break
                seen = seen or bool(block.strip())
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                try:
                    process.wait(timeout=.05)
                except subprocess.TimeoutExpired:
                    pass
                process.stdout.close()
        return self.current


class DesktopAwareness:
    """Read-only metadata cache backed by a disposable OS observer process.

    UI calls never make an OS/IPC request. No observer code can grab keyboard,
    inject input, select a window, activate an app, or open a microphone. A dead
    or stalled child becomes unavailable, with bounded termination and no retry
    storm. ``backend_factory`` exists only for deterministic unit fixtures.
    """

    def __init__(self, enabled=True, poll_interval=.5, own_pid=None, *,
                 clock=time.monotonic, backend_factory=None, caret_provider=None, environment=None,
                 platform=None, popen=subprocess.Popen, _worker=False):
        self.enabled = bool(enabled)
        self.poll_interval = max(.1, float(poll_interval))
        self.own_pid = os.getpid() if own_pid is None else own_pid
        self.clock, self.backend_factory = clock, backend_factory
        self.environment = dict(os.environ if environment is None else environment)
        self.platform, self.popen = platform or sys.platform, popen
        self.worker_mode = _worker
        self.stop_event, self.lock = threading.Event(), threading.Lock()
        self.thread = self.process = None
        self.current = self._empty("disabled" if not self.enabled else "starting")
        self.last_received = self.clock()

    def _empty(self, reason, permission=None):
        return {"enabled": self.enabled, "available": False, "observed_at": self.clock(),
                "focused_window": None, "typing": None, "bout": None, "caret": None, "secure_entry": None,
                "pointer": {"available": False}, "windows": {"available": False, "count": 0, "coverage": 0., "rects": []},
                "microphone": {"available": False, "in_use": None},
                "permission": permission or ("disabled" if not self.enabled else "local-observation"),
                "source": "unavailable", "caret_source": "window-fallback", "reason": reason}

    def start(self):
        if self.thread is not None or not self.enabled:
            return self
        session = self.environment.get("XDG_SESSION_TYPE", "")
        if self.platform != "darwin" and (session == "wayland" or (self.environment.get("WAYLAND_DISPLAY") and session != "x11")):
            self.current = self._empty("wayland_unsupported", "unsupported")
        elif self.platform != "darwin" and not self.environment.get("DISPLAY"):
            self.current = self._empty("x11_display_unavailable", "unsupported")
        else:
            target = self._run if self.backend_factory is not None or self.worker_mode else self._spawn_and_read
            self.thread = threading.Thread(target=target, name="terminus-awareness", daemon=True)
            self.thread.start()
        return self

    def _publish(self, snapshot):
        if not self.stop_event.is_set():
            with self.lock:
                self.current = snapshot

    def _run(self):
        backend, rhythm = None, _TypingRhythm()
        window, windows, pointer, last_pointer = None, None, None, None
        next_poll, next_windows = -math.inf, -math.inf
        mic = _MicrophoneStatus()
        try:
            factory = self.backend_factory
            if factory is None:
                if self.platform == "darwin":
                    try:
                        from desktop.perception_macos import MacMetadataBackend
                    except ModuleNotFoundError:
                        from perception_macos import MacMetadataBackend
                    factory = MacMetadataBackend
                else:
                    factory = _XcbBackend
            backend = factory(self.stop_event, self.own_pid)
            while not self.stop_event.is_set():
                now = self.clock()
                if now >= next_poll:
                    window = backend.focused_window(now)
                    next_poll = now + self.poll_interval
                if self.stop_event.is_set():
                    break
                rhythm.note(backend.keypresses(), now)
                pointer_state = {"available": False}
                if hasattr(backend, "pointer"):
                    try:
                        pointer = backend.pointer()
                        if pointer and all(math.isfinite(float(pointer[k])) for k in ("x", "y")):
                            screen = pointer["screen"]
                            x = max(0., min(1., (pointer["x"] - screen["x"]) / max(1., screen["width"])))
                            y = max(0., min(1., (pointer["y"] - screen["y"]) / max(1., screen["height"])))
                            motion = min(1., math.hypot(x-last_pointer[0], y-last_pointer[1]) * 5) if last_pointer else 0.
                            pointer_state = {"available": True, "x": round(x, 3), "y": round(y, 3), "motion": round(motion, 3)}
                            last_pointer = (x, y)
                    except (RuntimeError, TimeoutError):
                        pass
                if now >= next_windows:
                    windows = backend.visible_windows(now) if hasattr(backend, "visible_windows") else ([window] if window else [])
                    next_windows = now + 2
                screen = getattr(backend, "screen", pointer.get("screen") if pointer else None)
                use = mic.sample(now) if self.worker_mode else None
                available = getattr(backend, "typing_available", True)
                self._publish({"enabled": True, "available": True, "observed_at": now,
                               "focused_window": deepcopy(window), "typing": rhythm.state(now) if available else None,
                               "bout": rhythm.bout(now) if available else None, "pointer": pointer_state,
                               "windows": _window_summary(windows, screen),
                               "microphone": {"available": use is not None, "in_use": use},
                               "caret": None, "secure_entry": None, "permission": "local-observation",
                               "source": getattr(backend, "source", "x11-xinput2"),
                               "caret_source": "window-fallback", "reason": None})
                self.stop_event.wait(.1)
        except Exception as error:
            self._publish(self._empty(type(error).__name__, "unsupported"))
        finally:
            if backend is not None:
                backend.close()

    def _accept(self, line):
        if len(line) > MAX_SNAPSHOT:
            return False
        try:
            value = json.loads(line)
        except (ValueError, TypeError, UnicodeError):
            return False
        if not isinstance(value, dict) or set(value) != set(self._empty("")):
            return False
        now = self.clock()
        observed = value.get("observed_at")
        if (type(observed) not in (int, float) or not math.isfinite(observed)
                or not 0 <= now - observed <= STALE_AFTER
                or not isinstance(value.get("source"), str)
                or value["source"] not in {"x11-xinput2", "mac-readonly", "unavailable"}):
            return False
        allowed = {
            "typing": {"active", "last_at", "rate", "pulse", "sequence"},
            "bout": {"phase", "duration_s", "level", "pause_age_s", "sequence"},
            "pointer": {"available", "x", "y", "motion"},
            "windows": {"available", "count", "coverage", "rects"},
            "microphone": {"available", "in_use"},
            "focused_window": {"x", "y", "width", "height", "own"},
        }
        for key, fields in allowed.items():
            item = value[key]
            if item is not None and (not isinstance(item, dict) or set(item) - fields):
                return False
        windows = value["windows"]
        if not isinstance(windows, dict) or not isinstance(windows.get("rects"), list):
            return False
        if any(not isinstance(rect, dict) or set(rect) != {"x", "y", "width", "height"}
               for rect in windows["rects"]):
            return False
        if type(value["enabled"]) is not bool or type(value["available"]) is not bool:
            return False
        if not isinstance(value["permission"], str) or value["permission"] not in {"local-observation", "disabled", "unsupported"}:
            return False
        if value["caret_source"] != "window-fallback":
            return False
        if value["reason"] is not None and not isinstance(value["reason"], str):
            return False
        if value["reason"] not in {None, "disabled", "starting", "stopped", "wayland_unsupported",
                                   "x11_display_unavailable", "observer_stale", "RuntimeError", "TimeoutError",
                                   "OSError", "ImportError", "ModuleNotFoundError", "AttributeError",
                                   "ValueError", "PermissionError", "FileNotFoundError", "NotImplementedError",
                                   "ConnectionError", "TypeError"}:
            return False
        bout = value["bout"]
        if bout is not None and (not isinstance(bout.get("phase"), str) or bout["phase"] not in {"active", "pause", "idle"}):
            return False
        # This is a bounded private protocol, not an extension point for text.
        def numeric_tree(item, depth=0):
            if depth > 4:
                return False
            if isinstance(item, dict):
                return len(item) <= 8 and all(numeric_tree(child, depth+1) for child in item.values())
            if isinstance(item, list):
                return len(item) <= 8 and all(numeric_tree(child, depth+1) for child in item)
            if item is None or type(item) is bool:
                return True
            if type(item) in (int, float):
                return math.isfinite(item) and abs(item) <= 1e15
            return False
        for key in ("typing", "bout", "pointer", "windows", "microphone", "focused_window"):
            item = {field: data for field, data in value[key].items() if field != "phase"} if key == "bout" and value[key] is not None else value[key]
            if not numeric_tree(item):
                return False
        if value["caret"] is not None or value["secure_entry"] is not None:
            return False
        self.last_received = now
        self._publish(value)
        return True

    def _spawn_and_read(self):
        try:
            environment = {key: value for key, value in self.environment.items() if key in CHILD_ENVIRONMENT}
            environment["PYTHONNOUSERSITE"] = "1"
            self.process = self.popen([sys.executable, "-u", str(Path(__file__).resolve()), "--worker", str(self.own_pid)],
                                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                      bufsize=0, close_fds=True, start_new_session=True, env=environment)
            pending = bytearray()
            self.last_received = self.clock()
            while not self.stop_event.is_set():
                ready, _, _ = select.select([self.process.stdout], [], [], .2)
                if ready:
                    block = os.read(self.process.stdout.fileno(), 4096)
                    if not block:
                        break
                    pending.extend(block)
                    if len(pending) > MAX_SNAPSHOT:
                        break
                    while b"\n" in pending:
                        line, _, tail = pending.partition(b"\n")
                        pending = bytearray(tail)
                        if not self._accept(line):
                            raise ValueError("invalid_observer_snapshot")
                if self.clock() - self.last_received > STALE_AFTER:
                    raise TimeoutError("observer_stalled")
        except Exception as error:
            self._publish(self._empty(type(error).__name__, "unsupported"))
        finally:
            self._reap()
            self._publish(self._empty("observer_exited", "unsupported"))

    def _reap(self):
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=.35)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=.35)
            except OSError:
                pass
        if process.stdout is not None:
            process.stdout.close()

    def snapshot(self):
        with self.lock:
            value = deepcopy(self.current)
        if value["available"] and self.clock() - value["observed_at"] > STALE_AFTER:
            return self._empty("observer_stale", "unsupported")
        return value

    def close(self, timeout=1.0):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(max(0., float(timeout)))
        self.enabled = False
        with self.lock:
            self.current = self._empty("stopped", "disabled")
        return self.thread is None or not self.thread.is_alive()


def _worker_main(own_pid):
    import signal
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, OSError, ValueError):
        pass
    try:
        os.nice(10)
    except OSError:
        pass
    observer = DesktopAwareness(own_pid=own_pid, _worker=True)
    signal.signal(signal.SIGTERM, lambda *_: observer.stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: observer.stop_event.set())
    observer.start()
    try:
        while observer.thread and observer.thread.is_alive() and not observer.stop_event.wait(.2):
            sys.stdout.write(json.dumps(observer.snapshot(), separators=(",", ":"), allow_nan=False) + "\n")
            sys.stdout.flush()
    except (BrokenPipeError, OSError):
        pass
    finally:
        observer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_worker_main(int(sys.argv[2])) if len(sys.argv) == 3 and sys.argv[1] == "--worker" else 2)
