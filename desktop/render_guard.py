"""Private startup crash-loop guard for the optional hardware renderer.

The desktop's exclusive data-directory lock must be acquired before begin().
An uncleared marker then belongs to a previous startup. This module never
signals a process or touches a GUI, input API, service, environment or network.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import stat
import tempfile
import time


MARKER_NAME = ".render-guard.json"
FAILURE_WINDOW = 600.
STABLE_SECONDS = 15.
MAX_HEALTH_GAP = 5.
MAX_RECORD_BYTES = 512


class RenderGuard:
    """Latch cheap raster rendering after two consecutive early GPU exits.

    begin() writes a pending startup marker before Qt initializes the GPU. A
    stable, visible, connected native renderer clears that marker. Two pending
    restarts within ten minutes select raster. The raster latch is sticky, so
    a successful fallback cannot restart the GPU crash loop on the next launch.
    Removing .render-guard.json while the desktop is stopped permits a retry.
    """

    def __init__(self, data_dir, *, clock=time.time, pid=None):
        self.path = Path(data_dir) / MARKER_NAME
        self.clock = clock
        self.pid = os.getpid() if pid is None else pid
        self.attempting = False
        self.latched = False
        self.begun = False
        self.cleared = False
        self.healthy_since = self.last_health = None
        self.record = None
        self.reason = None

    def _now(self):
        value = self.clock()
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid_clock")
        return float(value)

    def _read(self, now):
        try:
            descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0))
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RECORD_BYTES:
                raise ValueError("invalid_marker")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                value = json.loads(stream.read(MAX_RECORD_BYTES + 1))
        finally:
            os.close(descriptor)
        if not isinstance(value, dict) or set(value) != {"schema", "pid", "time", "count"}:
            raise ValueError("invalid_marker")
        if (type(value["schema"]) is not int or value["schema"] != 1
                or type(value["pid"]) is not int or not 1 <= value["pid"] <= 2**31-1
                or type(value["count"]) is not int or not 0 <= value["count"] <= 2
                or type(value["time"]) not in (int, float)
                or not math.isfinite(value["time"]) or value["time"] < 0
                or value["time"] > now + 60):
            raise ValueError("invalid_marker")
        return value

    def _write(self, count, now):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        record = {"schema": 1, "pid": self.pid, "time": now, "count": count}
        descriptor, temporary = tempfile.mkstemp(prefix=".render-guard-", suffix=".tmp", dir=self.path.parent)
        try:
            if hasattr(os,"fchmod"):os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                descriptor = None
                json.dump(record, stream, separators=(",", ":"), allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        self.record = record

    def begin(self):
        if self.begun:
            return self.attempting
        self.begun = True
        try:
            now = self._now()
            previous = self._read(now)
            if previous is not None and previous["count"] >= 2:
                self.record = previous
                self.latched, self.reason = True, "previous_renderer_failures"
                return False
            count = 0
            if previous is not None and now - previous["time"] <= FAILURE_WINDOW:
                count = min(2, previous["count"] + 1)
            self._write(count, now)
            self.latched = count >= 2
            self.attempting = not self.latched
            self.reason = "previous_renderer_failures" if self.latched else None
        except (OSError, ValueError, TypeError, OverflowError):
            # A corrupt/unwritable marker cannot prevent the inexpensive body
            # from starting or cause repeated unsafe GPU bootstrap attempts.
            self.latched, self.reason = True, "renderer_guard_unavailable"
            try:
                self._write(2, self._now())
            except (OSError, ValueError, TypeError, OverflowError):
                pass
        return self.attempting

    def healthy(self, report):
        """Clear a pending GPU startup after fifteen continuous healthy seconds.

        Returns True once this instance has cleared its marker. A raster body
        cannot clear a latch. Reports separated by over five seconds, stale
        report timestamps, backwards clocks or any missing health condition
        restart the stable interval.
        """
        if self.cleared:
            return True
        if not self.attempting or self.latched or not isinstance(report, dict):
            return False
        try:
            now = self._now()
        except (ValueError, TypeError, OverflowError):
            self.healthy_since = self.last_health = None
            return False
        graphics = report.get("graphics")
        frames = graphics.get("frames_rendered") if isinstance(graphics, dict) else None
        platform = report.get("platform")
        updated = report.get("updated_at", now)
        valid = (report.get("visible") is True and report.get("exposed") is True
                 and report.get("connected") is True and report.get("snapshot_fresh") is True
                 and isinstance(platform, str) and bool(platform) and platform not in {"minimal", "offscreen"}
                 and isinstance(graphics, dict) and graphics.get("available") is True
                 and graphics.get("scene_graph_initialized") is True
                 and type(frames) is int and frames > 0
                 and type(updated) in (int, float) and math.isfinite(updated) and -1 <= now-updated <= 5
                 and report.get("pid", self.pid) == self.pid)
        if not valid:
            self.healthy_since = self.last_health = None
            return False
        if (self.healthy_since is None or self.last_health is None or now < self.last_health or now-self.last_health > MAX_HEALTH_GAP):
            self.healthy_since = now
        self.last_health = now
        if now-self.healthy_since < STABLE_SECONDS:
            return False
        try:
            # The exclusive desktop lock makes this our pending marker. Still
            # compare identity so an unrelated replacement is never removed.
            if self._read(now) != self.record:
                self.healthy_since = None
                return False
            self.path.unlink()
        except (OSError, ValueError, TypeError, OverflowError):
            return False
        self.cleared = True
        return True

    def unavailable(self):
        """Latch raster when GPU initialization reports it cannot render."""
        self.attempting, self.latched = False, True
        self.cleared = False
        self.healthy_since = self.last_health = None
        self.reason = "renderer_unavailable"
        try:
            self._write(2, self._now())
        except (OSError, ValueError, TypeError, OverflowError):
            pass
