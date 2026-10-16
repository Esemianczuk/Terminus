"""Optional event-only AT-SPI caret geometry, isolated from the Qt interpreter.

The system Python supplies pyatspi on this host. Nothing scans the accessible
tree, reads text/names/titles, changes accessibility settings, or writes a file.
Only a bounded rectangle and the focused source's password-role flag cross the
pipe. Unsupported applications simply leave the local window fallback active.
"""

from __future__ import annotations

import json
import math
from contextlib import suppress
from pathlib import Path
import subprocess
import sys
import threading
import time


EVENTS = ("object:state-changed:focused", "object:text-caret-moved")
MAX_LINE = 512
MAX_AGE = 2.8


def bounded_rect(value):
    if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
        return None
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)
           for item in value.values()):
        return None
    x, y, width, height = (int(value[key]) for key in ("x", "y", "width", "height"))
    if abs(x) > 131072 or abs(y) > 131072 or not 1 <= width <= 512 or not 1 <= height <= 512:
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def caret_from_source(source, api):
    """Query the event source alone; never request its contents or ancestors."""
    try:
        states = source.getState()
        if not all(states.contains(state) for state in (api.STATE_FOCUSED, api.STATE_VISIBLE, api.STATE_SHOWING)):
            return {"rect": None, "secure": None}
        if source.getRole() == api.ROLE_PASSWORD_TEXT:
            return {"rect": None, "secure": True}
        text = source.queryText()
        offset = int(text.caretOffset)
        if offset < 0:
            return {"rect": None, "secure": False}
        try:
            bounds = text.getCharacterExtents(offset, api.DESKTOP_COORDS)
            rect = bounded_rect(dict(zip(("x", "y", "width", "height"), bounds)))
        except Exception:
            rect = None
        if rect:
            rect["width"] = 1
        elif offset:
            # Some applications expose no glyph at the insertion point after
            # the final character. Its preceding glyph's trailing edge is a
            # geometric fallback, without reading that character.
            bounds = text.getCharacterExtents(offset - 1, api.DESKTOP_COORDS)
            preceding = bounded_rect(dict(zip(("x", "y", "width", "height"), bounds)))
            if preceding:
                rect = bounded_rect({"x": preceding["x"] + preceding["width"], "y": preceding["y"],
                                     "width": 1, "height": preceding["height"]})
        return {"rect": rect, "secure": False}
    except Exception:
        return {"rect": None, "secure": None}


class LocalCaretObserver:
    """Cache short-lived geometry from an optional, disposable helper process."""

    def __init__(self, *, clock=time.monotonic, executable="/usr/bin/python3", popen=subprocess.Popen):
        self.clock, self.executable, self.popen = clock, executable, popen
        self.process = self.reader = None
        self.lock = threading.Lock()
        self.latest = None
        self.updated_at = -math.inf
        self.available = False

    def start(self):
        if self.process is not None:
            return self.process.poll() is None
        try:
            self.process = self.popen([self.executable, "-u", str(Path(__file__).resolve()), "--worker"],
                                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                      bufsize=0, close_fds=True)
        except (OSError, ValueError):
            self.process = None
            return False
        self.reader = threading.Thread(target=self._read, daemon=True, name="terminus-caret")
        self.reader.start()
        return True

    def _accept(self, line):
        if len(line) > MAX_LINE:
            return False
        try:
            value = json.loads(line)
        except (ValueError, TypeError, UnicodeError):
            return False
        if not isinstance(value, dict) or set(value) - {"rect", "secure", "available"}:
            return False
        secure = value.get("secure")
        if type(value.get("available")) is not bool or (secure is not None and type(secure) is not bool):
            return False
        rect = bounded_rect(value.get("rect"))
        if value.get("rect") is not None and rect is None:
            return False
        if value.get("secure") is True:
            rect = None
        with self.lock:
            self.available = value["available"]
            self.latest = {"rect": rect, "secure": value.get("secure")}
            self.updated_at = self.clock()
        return True

    def _read(self):
        process = self.process
        try:
            while True:
                line = process.stdout.readline(MAX_LINE + 1)
                if not line:
                    break
                if len(line) > MAX_LINE or not line.endswith(b"\n"):
                    break  # A misbehaving helper cannot grow an unbounded line.
                self._accept(line)
        except (OSError, ValueError):
            pass
        finally:
            with self.lock:
                self.available = False
                self.latest = None

    def snapshot(self):
        with self.lock:
            alive = self.process is not None and self.process.poll() is None
            fresh = bool(alive and self.available and 0 <= self.clock() - self.updated_at < MAX_AGE)
            value = self.latest if fresh else None
            return {"rect": dict(value["rect"]) if value and value["rect"] else None,
                    "secure": value["secure"] if value else None,
                    "available": bool(alive and self.available), "fresh": fresh, "backend": "atspi-events",
                    "precision": "glyph-edge" if value and value["rect"] else None}

    def close(self):
        process, reader = self.process, self.reader
        if process is not None:
            if process.poll() is None:
                with suppress(OSError):
                    process.terminate()
                try:
                    process.wait(timeout=.6)
                except subprocess.TimeoutExpired:
                    with suppress(OSError):
                        process.kill()
                    with suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=.6)
            if process.stdout is not None:
                with suppress(OSError):
                    process.stdout.close()
        if reader and reader is not threading.current_thread():
            reader.join(timeout=.3)
        self.process = self.reader = None
        with self.lock:
            self.available = False
            self.latest = None


def worker():
    try:
        import pyatspi
        from gi.repository import GLib
    except ImportError:
        return 1
    import signal

    def emit(rect=None, secure=None, available=True):
        try:
            sys.stdout.write(json.dumps({"rect": rect, "secure": secure, "available": available}, separators=(",", ":")) + "\n")
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            pyatspi.Registry.stop()

    last_query = [-math.inf]

    def observe(event):
        focused = event.type == EVENTS[0]
        if focused and not event.detail1:
            emit()
            return
        now = time.monotonic()
        if not focused and now - last_query[0] < .08:
            return
        last_query[0] = now
        emit(**caret_from_source(event.source, pyatspi))

    def stop():
        pyatspi.Registry.stop()
        return False

    try:
        pyatspi.Registry.registerEventListener(observe, *EVENTS)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, stop)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, stop)
        emit()
        pyatspi.Registry.start(gil=False)
    finally:
        pyatspi.Registry.deregisterEventListener(observe, *EVENTS)
    return 0


if __name__ == "__main__":
    raise SystemExit(worker() if sys.argv[1:] == ["--worker"] else 2)
