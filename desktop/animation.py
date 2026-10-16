"""Decoded GIF clips and a small monotonic presentation state machine.

The organism chooses behavior; this module selects already-authored footage.
Returned images are cached, read-only QImages. There is no mesh, crossfade,
network access, event production, or independent behavior clock here.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping

from PyQt5 import QtGui


LOOP_STATES = ("idle", "moving", "sleep", "typing")
TRANSITIONS = {"takeoff", "landing", "turn", "wake", "poke", "sleep-in", "stretch", "yawn", "blink", "peer", "signal"}
DEFAULT_ANCHORS = MappingProxyType({"left": (.18, .78), "right": (.82, .78), "center": (.5, .80)})


class ClipError(ValueError):
    """An invalid or unusable local clip library."""


@dataclass(frozen=True)
class Clip:
    name: str
    path: Path
    frames: tuple
    delays_ms: tuple[int, ...]
    ends_ms: tuple[int, ...]
    duration_ms: int
    loop: bool
    anchors: Mapping[str, tuple[float, float]]

    def frame_at(self, elapsed: float, *, first=False):
        elapsed_ms = max(0., elapsed * 1000)
        position = 0. if first else elapsed_ms % self.duration_ms if self.loop else min(elapsed_ms, self.duration_ms - .001)
        index = min(len(self.frames) - 1, bisect_right(self.ends_ms, position))
        return index, max(1, math.ceil(self.ends_ms[index] - position))


@dataclass(frozen=True)
class AnimationFrame:
    image: QtGui.QImage
    clip: str
    index: int
    state: str
    transition: bool
    mirror: bool
    next_frame_ms: int
    anchors: Mapping[str, tuple[float, float]]
    fallback: bool


class ClipLibrary:
    """Bounded GIF decoding once, then shared immutable frames for each view."""

    def __init__(self, clips: Mapping[str, Clip], canvas, *, errors=None):
        self.clips = MappingProxyType(dict(clips))
        self.canvas = tuple(canvas)
        self.errors = MappingProxyType(dict(errors or {}))
        self.decoded_bytes = sum(image.sizeInBytes() for clip in clips.values() for image in clip.frames)
        if not any(name in self.clips for name in LOOP_STATES):
            raise ClipError("No usable animated idle, moving, sleep, or typing clip.")

    @classmethod
    def from_manifest(cls, path: Path | str, *, max_cache_bytes=96 * 1024 * 1024,
                      max_compressed_bytes=24 * 1024 * 1024, max_frames=180,
                      max_dimension=1024, max_duration_ms=12000):
        path = Path(path)
        try:
            if path.stat().st_size > 64 * 1024:
                raise ClipError("Clip manifest is too large.")
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise ClipError("Cannot read a valid clip manifest.") from exc
        if not isinstance(manifest, dict) or manifest.get("version") != 1:
            raise ClipError("Unsupported clip manifest version.")
        canvas = manifest.get("canvas")
        if (not isinstance(canvas, list) or len(canvas) != 2
                or any(not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= max_dimension for value in canvas)):
            raise ClipError("Clip canvas must contain two bounded integer dimensions.")
        entries = manifest.get("clips")
        if not isinstance(entries, dict) or not 1 <= len(entries) <= 16:
            raise ClipError("A clip manifest must contain 1 to 16 clips.")
        directory = path.resolve().parent
        clips, errors = {}, {}
        used_bytes = compressed_bytes = 0
        for name, entry in entries.items():
            try:
                if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", name):
                    raise ClipError("Invalid clip name.")
                if name not in LOOP_STATES and name not in TRANSITIONS:
                    raise ClipError("Unknown clip role.")
                if not isinstance(entry, dict) or type(entry.get("loop")) is not bool:
                    raise ClipError("Clip loop must be true or false.")
                if entry["loop"] != (name in LOOP_STATES):
                    raise ClipError("Loop and transition roles do not match.")
                filename = entry.get("file")
                if not isinstance(filename, str) or not filename or Path(filename).is_absolute():
                    raise ClipError("A clip needs a relative GIF file.")
                source = (directory / filename).resolve()
                if not source.is_relative_to(directory) or source.suffix.lower() != ".gif":
                    raise ClipError("Clip files must stay inside their asset directory.")
                size = source.stat().st_size
                if size <= 0 or size > 8 * 1024 * 1024 or compressed_bytes + size > max_compressed_bytes:
                    raise ClipError("Compressed clip budget exceeded.")
                anchors = cls._anchors(entry.get("anchors"))
                clip = cls._decode(name, source, entry["loop"], anchors, tuple(canvas),
                                   max_cache_bytes - used_bytes, max_frames, max_duration_ms)
            except (OSError, ValueError) as exc:
                errors[str(name)[:32]] = str(exc)
                continue
            clips[name] = clip
            compressed_bytes += size
            used_bytes += sum(image.sizeInBytes() for image in clip.frames)
        return cls(clips, canvas, errors=errors)

    @staticmethod
    def _anchors(value):
        if value is None:
            return DEFAULT_ANCHORS
        if not isinstance(value, dict) or set(value) - set(DEFAULT_ANCHORS):
            raise ClipError("Clip anchors must use left, right, and center keys.")
        result = dict(DEFAULT_ANCHORS)
        for key, point in value.items():
            if (not isinstance(point, list) or len(point) != 2
                    or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or not 0 <= v <= 1 for v in point)):
                raise ClipError("Clip anchors must be normalized coordinate pairs.")
            result[key] = tuple(point)
        return MappingProxyType(result)

    @staticmethod
    def _decode(name, source, loop, anchors, canvas, remaining_bytes, max_frames, max_duration_ms):
        reader = QtGui.QImageReader(str(source))
        if bytes(reader.format()).lower() != b"gif" or not reader.supportsAnimation():
            raise ClipError("Clip must be an animated GIF, not a renamed static image.")
        size = reader.size()
        if (size.width(), size.height()) != canvas:
            raise ClipError("GIF canvas does not match registered clip dimensions.")
        count = reader.imageCount()
        if not 2 <= count <= max_frames:
            raise ClipError("GIF frame count must be between 2 and the configured limit.")
        if count * size.width() * size.height() * 4 > remaining_bytes:
            raise ClipError("Decoded clip cache budget exceeded.")
        frames, delays, ends = [], [], []
        total = used_bytes = 0
        for _ in range(count):
            image = reader.read()
            if image.isNull() or (image.width(), image.height()) != canvas:
                raise ClipError("GIF contains an unreadable or unregistered frame.")
            if not image.hasAlphaChannel():
                raise ClipError("Desktop GIF frames must preserve transparency.")
            image = image.convertToFormat(QtGui.QImage.Format_ARGB32_Premultiplied)
            used_bytes += image.sizeInBytes()
            if used_bytes > remaining_bytes:
                raise ClipError("Decoded clip cache budget exceeded.")
            # GIF stores centiseconds. Browsers and Qt already normalize its
            # special zero-delay convention; enforce an explicit 20ms floor.
            delay = max(20, min(1000, reader.nextImageDelay()))
            total += delay
            if total > max_duration_ms:
                raise ClipError("GIF duration exceeds the configured limit.")
            frames.append(image)
            delays.append(delay)
            ends.append(total)
        if reader.canRead():
            raise ClipError("GIF contains more frames than its declared count.")
        return Clip(name, source, tuple(frames), tuple(delays), tuple(ends), total, loop, anchors)

    def loop(self, desired: str):
        if desired not in LOOP_STATES:
            raise ValueError("Unknown animation state: " + str(desired))
        for name in (desired, "idle", "sleep", "moving", "typing"):
            if name in self.clips:
                return self.clips[name]
        raise ClipError("No usable loop clip.")


class ClipPlayer:
    """Persistent loops with finite, interruptible authored transitions."""

    def __init__(self, library: ClipLibrary):
        self.library = library
        self._clip = None
        self._state = "idle"
        self._target = "idle"
        self._started_at = self._last_now = 0.
        self._facing = self._turn_from = self._turn_to = 1
        self._last_dragging = False
        self._last_poke = None
        self._seen_gestures = []
        self._suspended_at = None
        self._frozen_frame = None
        self._last_sample = None
        self._reduced = False

    def _enter_loop(self, state, now):
        self._clip = self.library.loop(state)
        self._state = self._target = state
        self._started_at = now

    def _begin(self, name, target, now, facing=None):
        clip = self.library.clips.get(name)
        if clip is None:
            self._enter_loop(target, now)
            if facing is not None:
                self._facing = facing
            return
        self._clip, self._target, self._started_at = clip, target, now
        if name == "turn":
            self._turn_from, self._turn_to = self._facing, facing

    def _visual_facing(self, now):
        if self._clip.name == "turn":
            return self._turn_to if (now - self._started_at) * 1000 >= self._clip.duration_ms / 2 else self._turn_from
        return self._facing

    def _complete(self, now):
        if not self._clip.loop and (now - self._started_at) * 1000 >= self._clip.duration_ms:
            end = self._started_at + self._clip.duration_ms / 1000
            if self._clip.name == "turn":
                self._facing = self._turn_to
            self._enter_loop(self._target, end)

    def _reconcile(self, desired, facing, now):
        if not self._clip.loop:
            return
        if self._state != desired:
            if self._state == "sleep":
                self._begin("wake", "idle", now)
            elif self._state == "moving":
                self._begin("landing", "idle", now)
            elif desired == "moving":
                self._begin("takeoff", "moving", now)
            elif desired == "sleep":
                self._begin("sleep-in", "sleep", now)
            else:
                self._enter_loop(desired, now)
        elif facing != self._facing:
            self._begin("turn", desired, now, facing=facing)

    @staticmethod
    def _gesture_key(gesture, gesture_id):
        if isinstance(gesture, dict):
            gesture_id = gesture.get("id", gesture_id)
            gesture = gesture.get("kind")
        if not isinstance(gesture, str):
            return None
        if gesture_id is not None and not isinstance(gesture_id, (str, int, float)):
            return None
        return gesture, gesture_id

    def advance(self, now: float, desired="idle", *, facing=1, dragging=False, poke_id=None,
                gesture=None, gesture_id=None, reduced_motion=False, fresh=True) -> AnimationFrame:
        if not isinstance(now, (int, float)) or not math.isfinite(now):
            raise ValueError("The clip player needs a finite monotonic clock.")
        if desired not in LOOP_STATES:
            raise ValueError("Unknown animation state: " + str(desired))
        now = max(self._last_now, float(now))
        self._last_now = now
        facing = -1 if facing < 0 else 1
        desired = "moving" if dragging else desired
        key = self._gesture_key(gesture, gesture_id)
        new_gesture = key is not None and key not in self._seen_gestures
        if new_gesture:
            self._seen_gestures = (self._seen_gestures + [key])[-64:]
        new_poke = poke_id is not None and poke_id != self._last_poke
        if poke_id is not None:
            self._last_poke = poke_id
        if self._clip is None:
            self._enter_loop(desired, now)
            self._facing = facing

        if not fresh:
            if self._suspended_at is None:
                self._suspended_at = now
                self._frozen_frame = (replace(self._last_sample, next_frame_ms=1000) if self._last_sample is not None
                                      else self._sample(now, quiet=True))
            self._last_dragging = bool(dragging)
            return self._frozen_frame
        if self._suspended_at is not None:
            # A reconnect must not replay a ten-minute-old takeoff or poke.
            self._facing = -1 if self._frozen_frame.mirror else 1
            self._enter_loop(desired, now)
            self._suspended_at = None
            self._frozen_frame = None
        if reduced_motion:
            if not self._reduced or self._state != desired or not self._clip.loop:
                self._enter_loop(desired, now)
            self._reduced, self._facing = True, facing
            self._last_dragging = bool(dragging)
            self._last_sample = self._sample(now, first=True, quiet=True)
            return self._last_sample
        if self._reduced:
            self._enter_loop(desired, now)
            self._reduced = False
        self._complete(now)
        drag_started = bool(dragging) and not self._last_dragging
        self._last_dragging = bool(dragging)
        if drag_started and self._clip.name not in {"moving", "takeoff"}:
            self._facing = self._visual_facing(now)
            self._begin("takeoff", "moving", now)
        elif desired == "moving" and not self._clip.loop and self._clip.name in {"poke", "stretch", "yawn", "blink", "peer", "signal"}:
            self._facing = self._visual_facing(now)
            self._begin("takeoff", "moving", now)
        elif new_poke and not dragging:
            self._facing = self._visual_facing(now)
            self._begin("poke", desired, now)
        elif (new_gesture and desired not in {"moving", "sleep"} and self._clip.loop
              and key[0] in {"stretch", "yawn", "blink", "peer", "signal"} and key[0] in self.library.clips):
            self._begin(key[0], desired, now)
        else:
            self._reconcile(desired, facing, now)
        self._last_sample = self._sample(now)
        return self._last_sample

    def _sample(self, now, *, first=False, quiet=False):
        index, delay = self._clip.frame_at(now - self._started_at, first=first)
        return AnimationFrame(self._clip.frames[index], self._clip.name, index, self._target,
                              not self._clip.loop, self._visual_facing(now) < 0,
                              1000 if quiet else delay, self._clip.anchors,
                              self._clip.loop and self._clip.name != self._target)
