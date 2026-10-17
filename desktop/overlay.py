#!/usr/bin/env python3
"""A small native view of the organism owned by the Terminus core."""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
from pathlib import Path
import signal
import sys
import time
from typing import Any
from urllib.parse import urlsplit
import uuid

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:sys.path.insert(0,str(REPO_ROOT))
from PySide6 import QtCore, QtGui, QtNetwork, QtSvg, QtWidgets
from terminus.supervision import notify,set_paused
from desktop.graph_motion import GraphMotion

try:
    from desktop.skin import SkinAtlas, SkinEngine, MODES as SKIN_MODES
except ModuleNotFoundError:
    from skin import SkinAtlas, SkinEngine, MODES as SKIN_MODES


REPO_ROOT = Path(__file__).resolve().parents[1]
CANVAS_WIDTH = 440
CANVAS_HEIGHT = 340
DEFAULT_URL = "http://127.0.0.1:8769"
SNAPSHOT_FRESHNESS = 5.0

# The same fictional visual alphabet as web/app.js. Sequences come only from
# authenticated utterances, never from the desktop animation clock.
GLYPH_PATHS = (
    'M12 3v18M4 8l8 5 8-5M5 19l7-4 7 4',
    'M5 7c8-7 18 3 12 10S-1 16 5 7M9 10l6 4',
    'M4 18L12 4l8 14M7 13h10M12 18v4',
    'M4 6h16M8 6v12l4 4 4-4V6M5 14h14',
    'M6 4v16M18 4v16M6 9l12 6M6 15l12-6',
    'M12 3C4 3 3 10 8 12c-5 2-4 9 4 9M12 3c8 0 9 7 4 9 5 2 4 9-4 9',
    'M4 12h16M12 4v16M6 6l12 12M18 6 6 18',
    'M4 18c1-11 6-16 8-9 2-7 7-2 8 9M8 17h8',
    'M5 4l14 8L5 20V4M11 8v8M3 12h3',
    'M4 7h16l-8 14L4 7M12 3v4M9 13h6',
    'M4 12c0-9 16-9 16 0S4 21 4 12M9 8v8M15 8v8',
    'M5 20V4l14 16V4M3 12h18',
    'M12 3v18M5 6l7 5 7-5M5 18l7-5 7 5',
    'M4 5c12 0 16 5 16 15M4 20C4 9 8 5 20 5M7 17l10-10',
    'M12 3L3 12l9 9 9-9-9-9M8 12h8M12 8v8',
    'M4 20l4-16 4 10 4-10 4 16M8 18h8',
    'M3 8h18M7 8v9l5 4 5-4V8M9 3l3 5 3-5',
    'M4 19C4 3 20 3 20 19M8 19V9M16 19V9M4 14h16',
    'M4 4l8 8-8 8M12 4l8 8-8 8M4 12h16',
    'M12 3C2 9 2 16 12 21c10-5 10-12 0-18M8 11l4 5 4-5',
)


def validate_url(raw: str, *, explicit: bool) -> str:
    """Only an explicit CLI URL may authorize a non-loopback destination."""
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("The core URL must be an http:// or https:// URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("The core URL cannot contain credentials, a query, or a fragment.")
    if parsed.path not in {"", "/"}:
        raise ValueError("Use the core's origin URL without a path.")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("The core URL has an invalid port.") from exc
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = parsed.hostname.lower() == "localhost"
    if not loopback and not explicit:
        raise ValueError("A remote core requires an explicit --url argument.")
    return raw.rstrip("/")


def _finite_unit(value: Any) -> bool:
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value) and 0 <= value <= 1)


def validate_snapshot(state: Any) -> dict:
    """Reject incomplete responses before they reach the drawing code."""
    if not isinstance(state, dict):
        raise ValueError("Core returned an invalid snapshot.")
    if not isinstance(state.get("behavior"), str) or not isinstance(state.get("revision"), int):
        raise ValueError("Core snapshot is missing behavior or revision.")
    position = state.get("position")
    if not isinstance(position, dict) or not all(_finite_unit(position.get(k)) for k in ("x", "y")):
        raise ValueError("Core snapshot has an invalid organism position.")
    nodes, edges = state.get("nodes"), state.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("Core snapshot is missing its graph.")
    for node in nodes:
        if (not isinstance(node, dict) or not isinstance(node.get("id"), str)
                or not all(_finite_unit(node.get(k)) for k in ("x", "y"))):
            raise ValueError("Core snapshot has an invalid graph node.")
    for edge in edges:
        if (not isinstance(edge, dict) or not isinstance(edge.get("source"), str)
                or not isinstance(edge.get("target"), str)):
            raise ValueError("Core snapshot has an invalid graph edge.")
    if "server_time" in state and (not isinstance(state["server_time"], (int, float))
                                    or not math.isfinite(state["server_time"])):
        raise ValueError("Core snapshot has an invalid clock.")
    for name in ("gesture", "motion"):
        value = state.get(name)
        if value is None:
            continue
        if (not isinstance(value, dict) or not isinstance(value.get("kind" if name == "gesture" else "intent"), str)
                or not isinstance(value.get("started_at"), (int, float)) or not math.isfinite(value["started_at"])
                or not isinstance(value.get("duration"), (int, float)) or not math.isfinite(value["duration"])
                or not 0 < value["duration"] <= 600
                or value.get("target_id") is not None and not isinstance(value["target_id"], str)):
            raise ValueError("Core snapshot has an invalid " + name + ".")
    if state.get("runtime") is not None and (not isinstance(state["runtime"], dict)
                                              or state["runtime"].get("status") not in {"ok", "degraded"}):
        raise ValueError("Core snapshot has an invalid runtime status.")
    return state


def amount(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(value):
        return max(0.0, min(1.0, value))
    return default


def smoothstep(start: float, end: float, value: float) -> float:
    t = amount((value - start) / (end - start))
    return t * t * (3 - 2 * t)


def reach_envelope(progress: float) -> float:
    """A slow outward reach, a real hold, then a longer soft return."""
    progress = amount(progress)
    if progress < .30:
        t = progress / .30
    elif progress <= .55:
        return 1.
    else:
        t = (1 - progress) / .45
    return t * t * t * (t * (t * 6 - 15) + 10)


class CoreClient(QtCore.QObject):
    snapshot = QtCore.Signal(dict)
    disconnected = QtCore.Signal(str)

    def __init__(self, url: str, data_dir: Path, parent=None):
        super().__init__(parent)
        self.url = url
        self.data_dir = data_dir
        identity = f"{uuid.getnode()}:{data_dir.resolve()}"
        self.device_id = "desktop-" + uuid.uuid5(uuid.NAMESPACE_URL, identity).hex[:12]
        self.manager = QtNetwork.QNetworkAccessManager(self)
        self.poll_reply = None
        self.poll_timer = QtCore.QTimer(self)
        self.poll_timer.setInterval(1000)
        self.poll_timer.timeout.connect(self.poll)

    def start(self):
        self.poll_timer.start()
        QtCore.QTimer.singleShot(0, self.poll)

    def _request(self, endpoint: str):
        try:
            token = (self.data_dir / "token").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            self.disconnected.emit("Local token unavailable · start the core")
            return None
        if not token or len(token) > 4096 or "\n" in token or "\r" in token:
            self.disconnected.emit("Local token is invalid")
            return None
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(self.url + endpoint))
        request.setRawHeader(b"Authorization", ("Bearer " + token).encode("utf-8"))
        request.setRawHeader(b"Accept", b"application/json")
        # Never forward a token to a redirect destination.
        request.setAttribute(QtNetwork.QNetworkRequest.RedirectPolicyAttribute,
                             QtNetwork.QNetworkRequest.ManualRedirectPolicy)
        return request

    def _guard(self, reply):
        timeout = QtCore.QTimer(reply)
        timeout.setSingleShot(True)
        timeout.timeout.connect(reply.abort)
        timeout.start(4000)
        reply.finished.connect(timeout.stop)

    def poll(self):
        if self.poll_reply is not None:
            return
        request = self._request("/api/state")
        if request is None:
            return
        reply = self.manager.get(request)
        self.poll_reply = reply
        self._guard(reply)
        reply.finished.connect(lambda: self._finish_poll(reply))

    @staticmethod
    def _failure(reply):
        status = reply.attribute(QtNetwork.QNetworkRequest.HttpStatusCodeAttribute)
        if status == 401 or status == 403:
            return "Core rejected the local token"
        if status and 300 <= status < 400:
            return "Core redirect refused · check --url"
        if reply.error() != QtNetwork.QNetworkReply.NoError:
            return "Core disconnected · reconnecting"
        if status != 200:
            return "Core returned an unexpected response"
        return None

    def _finish_poll(self, reply):
        self.poll_reply = None
        failure = self._failure(reply)
        if failure:
            self.disconnected.emit(failure)
        else:
            try:
                state = validate_snapshot(json.loads(bytes(reply.readAll())))
            except (ValueError, TypeError, UnicodeError):
                self.disconnected.emit("Core returned an invalid snapshot")
            else:
                self.snapshot.emit(state)
        reply.deleteLater()

    def send_event(self, kind: str, **fields):
        request = self._request("/api/events")
        if request is None:
            return
        request.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader, "application/json")
        payload = {"id": str(uuid.uuid4()), "kind": kind, "device_id": self.device_id,
                   "context": "native overlay interaction", "intensity": 0.65,
                   "source": "manual", "timestamp": time.time(), **fields}
        reply = self.manager.post(request, json.dumps(payload).encode("utf-8"))
        self._guard(reply)
        reply.finished.connect(lambda: self._finish_event(reply))

    def _finish_event(self, reply):
        status = reply.attribute(QtNetwork.QNetworkRequest.HttpStatusCodeAttribute)
        if status == 429:
            # A busy observer cannot make a healthy organism look disconnected.
            self.rate_limited_events=getattr(self,"rate_limited_events",0)+1
        elif reply.error() != QtNetwork.QNetworkReply.NoError or status not in {200, 201, 202}:
            self.disconnected.emit("Interaction was not delivered · reconnecting")
        else:
            QtCore.QTimer.singleShot(0, self.poll)
        reply.deleteLater()


class Overlay(QtWidgets.QWidget):
    """An input-shaped native presence; the authenticated core owns his mind."""

    def __init__(self, client: CoreClient, assets: Path, scale: float | None = None):
        flags = (QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint |
                 QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setWindowTitle("Terminus · desktop presence")
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("Terminus desktop creature")
        self.setAccessibleDescription("Click to touch. Drag to move. Alt-drag on the memory graph. Use the tray or right-click for controls.")
        self.client, self.assets = client, assets
        self.preferences = QtCore.QSettings(str(client.data_dir / "desktop.ini"), QtCore.QSettings.IniFormat)
        try:
            saved_scale = float(self.preferences.value("scale", 1.))
        except (ValueError, TypeError):
            saved_scale = 1.
        self.scale = scale if scale is not None else saved_scale if math.isfinite(saved_scale) and .65 <= saved_scale <= 2 else 1.
        self.setFixedSize(round(CANVAS_WIDTH * self.scale), round(CANVAS_HEIGHT * self.scale))
        self.state = None
        self.connected = False
        self.gpu_scene = None
        self.native_input_shape = None
        self.reference_renderer = os.environ.get("TERMINUS_CPU_REFERENCE") == "1"
        self.status = "Connecting to core"
        self.last_seen = 0.0
        self.started = time.monotonic()
        self.last_frame = self.started
        self.last_live_frame = self.started
        self.last_mask = 0.0
        self.frame = QtGui.QImage()
        self.input_region = QtGui.QRegion()
        self.creature_rect = QtCore.QRectF()
        self.drag_target = None
        self.press_global = self.press_local = self.press_window = None
        self.dragged = self.press_creature = False
        self.drag_mode = None
        self.hovering = self.menu_open = False
        self.roaming_paused = self.preferences.value("pause_roaming", False, type=bool)
        self.reduced_motion = (self.preferences.value("reduced_motion", False, type=bool)
                               or os.environ.get("TERMINUS_REDUCED_MOTION") == "1")
        self.interaction_until = self.started + 8
        self.status_until = self.started + 4
        self.roam_goal = None
        self.roam_position = None
        self.roam_velocity = QtCore.QPointF()
        self.roam_step = 0
        self.next_departure = self.started + 8
        self.moving_window = False
        self.art_signature = None
        self.static_art = QtGui.QPixmap()
        self.sleep_art = QtGui.QPixmap()
        self.pose_art = {}
        self.art_cache = {}
        self.clip_library = self.clip_player = self.clip_sample = None
        self.skin = SkinEngine(mode=self.preferences.value("skin_mode", "automatic"))
        self.clip_error = None
        self.clip_pixmap = QtGui.QPixmap()
        self.clip_pixmap_key = None
        self.glow_cache = {}
        self.graph_cache_key = None
        self.graph_points = {}
        self.graph_paths = []
        self.graph_motion = GraphMotion()
        self.sleep_blend = 0.0
        self.body_offset = QtCore.QPointF()
        self.body_velocity = QtCore.QPointF()
        self.last_drag_position = None
        self.last_drag_at = self.started
        self.drag_velocity = QtCore.QPointF()
        self.flight_velocity = QtCore.QPointF()
        self.flight_strength = 0.
        self.flight_bank = 0.
        self.facing = self.facing_target = 1.
        self.facing_mode = self.preferences.value("facing", "automatic")
        if self.facing_mode not in {"left", "right", "automatic"}:
            self.facing_mode = "automatic"
        if self.facing_mode == "left":
            self.facing = self.facing_target = -1.
        self.last_facing_change = -math.inf
        self.typing_blend = 0.
        self.typing_phase = 0.
        self.graph_visibility = self.preferences.value("graph_visibility", "bright")
        if self.graph_visibility not in {"subtle", "clear", "bright"}:
            self.graph_visibility = "bright"
        self.graph_gain = {"subtle": 1., "clear": 1.8, "bright": 2.8}[self.graph_visibility]
        self.awareness = {"available": False, "enabled": False, "observed_at": 0.}
        self.awareness_provider = None
        self.caret_provider = None
        self.awareness_enabled = self.preferences.value("desktop_awareness", True, type=bool)
        self.last_typing_sent = -math.inf
        self.last_typing_sequence = -1
        self.last_window_perch = -math.inf
        self.awareness_timer = QtCore.QTimer(self)
        self.awareness_timer.setInterval(500)
        self.awareness_timer.timeout.connect(self.poll_awareness)
        self.touch_started = -math.inf
        self.touch_direction = 1
        self.render_ms = 0.0
        self.mask_ms = 0.0
        self.presence_at = -math.inf
        self.time_period = None
        self.movie = None
        self.glyph_id = None
        self.glyph_started = 0.0
        self.glyph_sequence = []
        self.gesture_clock_id = None
        self.gesture_clock_start = None
        self.glyph_renderers = [QtSvg.QSvgRenderer(
            ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
             '<path d="' + path + '" fill="none" stroke="#b5fae8" '
             'stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/></svg>').encode(), self)
             for path in GLYPH_PATHS]
        self.load_art()
        self.restoring_view = True
        self.home_screen = QtWidgets.QApplication.primaryScreen()
        monitor = self.preferences.value("monitor", "")
        self.home_screen = next((screen for screen in QtWidgets.QApplication.screens() if screen.name() == monitor), self.home_screen)
        self.reposition("lower-right")
        try:
            x, y = float(self.preferences.value("x")), float(self.preferences.value("y"))
        except (TypeError, ValueError):
            pass
        else:
            if math.isfinite(x) and math.isfinite(y):
                left, top, right, bottom = self.motion_bounds()
                self.move(round(max(left, min(right, x))), round(max(top, min(bottom, y))))
                self.roam_position = QtCore.QPointF(self.pos())
        self.restoring_view = False
        self.tray = None
        if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QtWidgets.QSystemTrayIcon(self)
            icon = self.artwork().scaled(64, 64, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            self.tray.setIcon(QtGui.QIcon(icon))
            self.tray.setToolTip("Terminus · desktop presence")
            self.tray.setContextMenu(self.make_menu())
            self.tray.activated.connect(self.tray_activated)
            self.tray.show()
        client.snapshot.connect(self.receive_state)
        client.disconnected.connect(self.disconnect)
        self.animation = QtCore.QTimer(self)
        self.animation.setInterval(33)
        self.animation.timeout.connect(self.animate)
        self.animation.start()
        self.asset_timer = QtCore.QTimer(self)
        self.asset_timer.setInterval(5000)
        self.asset_timer.timeout.connect(self.load_art)
        self.asset_timer.start()
        self.presence_timer = QtCore.QTimer(self)
        self.presence_timer.setInterval(60000)
        self.presence_timer.timeout.connect(self.observe_presence)
        self.presence_timer.start()
        QtCore.QTimer.singleShot(5000, self.observe_presence)
        self.setToolTip("Click to touch · drag to move · Alt-drag on graph · right-click for controls")
        self.render_frame(self.started)

    def load_art(self):
        candidates = [self.assets / "terminus-refined.png", self.assets / "terminus.png", self.assets / "idle.gif"]
        art = next((path for path in candidates if path.is_file()), None)
        sleep_path = self.assets / "terminus-sleep.png"
        optional = {kind: self.assets / ("terminus-" + kind + ".png") for kind in ("stretch", "yawn", "flight", "typing")}
        manifest = self.assets / "clips" / "manifest.json"
        skin_atlas = manifest.parent / "skin-atlas.json"
        def fingerprint(path):
            try:
                information = path.stat()
                return (str(path), information.st_mtime_ns, information.st_size)
            except OSError:
                return None
        signature = ((str(art), art.stat().st_mtime_ns) if art else None,
                     sleep_path.stat().st_mtime_ns if sleep_path.is_file() else None,
                     tuple((kind, path.stat().st_mtime_ns if path.is_file() else None)
                           for kind, path in optional.items()), fingerprint(manifest), fingerprint(skin_atlas),
                     tuple(fingerprint(path) for path in sorted(manifest.parent.glob("*.gif"))[:32]))
        if signature == self.art_signature:
            return
        self.art_signature = signature
        if self.movie:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None
        self.static_art = QtGui.QPixmap()
        self.sleep_art = QtGui.QPixmap()
        self.pose_art = {kind: QtGui.QPixmap(str(path)) for kind, path in optional.items() if path.is_file()}
        self.art_cache.clear()
        if sleep_path.is_file():
            self.sleep_art.load(str(sleep_path))
        if art and art.suffix.lower() == ".gif":
            self.movie = QtGui.QMovie(str(art), parent=self)
            self.movie.setCacheMode(QtGui.QMovie.CacheAll)
            self.movie.frameChanged.connect(self.update)
            self.movie.start()
        elif art:
            self.static_art.load(str(art))
        self.clip_library = self.clip_player = self.clip_sample = None
        self.skin.clear()
        self.skin.atlas = SkinAtlas()
        self.clip_error = None
        self.clip_pixmap = QtGui.QPixmap()
        self.clip_pixmap_key = None
        if manifest.is_file():
            try:
                try:
                    from desktop.animation import ClipLibrary, ClipPlayer
                except ModuleNotFoundError:
                    from animation import ClipLibrary, ClipPlayer
                self.clip_library = ClipLibrary.from_manifest(manifest)
                self.clip_player = ClipPlayer(self.clip_library)
                self.skin.atlas = SkinAtlas.load(skin_atlas, self.clip_library)
                self.prepare_clip(time.monotonic())
            except (ImportError, OSError, ValueError, RuntimeError) as error:
                self.clip_error = type(error).__name__
                self.clip_library = self.clip_player = self.clip_sample = None
        self.update()

    def artwork(self):
        if self.clip_sample is not None and not self.clip_sample.image.isNull():
            key = self.clip_sample.image.cacheKey()
            if key != self.clip_pixmap_key:
                self.clip_pixmap = QtGui.QPixmap.fromImage(self.clip_sample.image)
                self.clip_pixmap_key = key
            return self.clip_pixmap
        return self.movie.currentPixmap() if self.movie else self.static_art

    def prepare_clip(self, now):
        """Choose real animation frames; core/local observations own the inputs."""
        if self.clip_player is None:
            return
        state = self.state or {}
        gesture = self.gesture(now)
        dragging = self.press_global is not None and self.dragged and self.drag_mode == "window"
        if state.get("behavior") in {"sleep", "dream"}:
            desired = "sleep"
        elif gesture and gesture.get("kind") == "imitate" and self.typing_recent(now) and not dragging:
            desired = "typing"
        elif dragging or self.flight_strength > .08 or (self.roam_goal is not None and self.can_roam(now)
                                                       and math.hypot(self.roam_velocity.x(), self.roam_velocity.y()) > 6):
            desired = "moving"
        else:
            desired = "idle"
        self.clip_sample = self.clip_player.advance(
            now, desired=desired, facing=-1 if self.facing_target < 0 else 1, dragging=dragging,
            poke_id=f"touch-{self.touch_started}" if math.isfinite(self.touch_started) else None,
            reduced_motion=self.reduced_motion, fresh=self.fresh(now),
            gesture=gesture.get("kind") if gesture else None, gesture_id=gesture.get("id") if gesture else None)

    def fresh(self, now=None):
        now = time.monotonic() if now is None else now
        runtime = (self.state or {}).get("runtime")
        healthy = runtime is None or isinstance(runtime, dict) and runtime.get("status") == "ok"
        return self.connected and healthy and 0 <= now - self.last_seen <= SNAPSHOT_FRESHNESS

    def core_time(self, now):
        """Advance the received server clock only while its owner is reachable."""
        received = (self.state or {}).get("server_time")
        received = received if isinstance(received, (int, float)) and math.isfinite(received) else time.time()
        return received + max(0, min(SNAPSHOT_FRESHNESS, now - self.last_seen))

    def gesture(self, now):
        """Finite core-authored actions; repainting never invents a second mind."""
        if not self.fresh(now):
            return None
        gesture = (self.state or {}).get("gesture")
        if not isinstance(gesture, dict):
            return None
        start, duration = gesture.get("started_at"), gesture.get("duration")
        if (not isinstance(start, (int, float)) or not math.isfinite(start)
                or not isinstance(duration, (int, float)) or not math.isfinite(duration)
                or not .05 <= duration <= 180):
            return None
        progress = (self.core_time(now) - start) / duration
        if not 0 <= progress < 1:
            return None
        if gesture.get("id") == self.gesture_clock_id and self.gesture_clock_start is not None:
            # A 1Hz response can precede that second's core tick. Repeated
            # snapshots must not rewind an eyelid or replay an already-finished
            # gesture; continue its first received monotonic display clock.
            progress = (now - self.gesture_clock_start) / duration
            if not 0 <= progress < 1:
                return None
        return {**gesture, "progress": progress, "strength": amount(gesture.get("strength"), .5)}

    def pose(self, now):
        elapsed = now - self.started
        gesture = self.gesture(now)
        kind = gesture.get("kind") if gesture else None
        progress = gesture["progress"] if gesture else 0.
        strength = gesture["strength"] if gesture else 0.
        envelope = (reach_envelope(progress) if kind in {"peer", "tendril-inspect", "signal", "stretch"}
                    else math.sin(math.pi * progress) ** 2) * (.45 + strength * .55)
        reduced = 0. if self.reduced_motion else 1.
        state = self.state or {}
        target_id = gesture.get("target_id") if gesture else state.get("attention")
        target_id = target_id if isinstance(target_id, str) else None
        target = self.graph_points.get(target_id)
        gaze = max(-1., min(1., (target.x() - self.creature_rect.center().x()) / 150)) if target else 0.
        inspection = self.inspection_target(now)
        gaze_y = 0.
        if inspection is not None:
            origin = QtCore.QPointF(self.x() + self.creature_rect.center().x() * self.scale,
                                   self.y() + self.creature_rect.center().y() * self.scale)
            gaze = max(-1., min(1., (inspection.x() - origin.x()) / 250))
            gaze_y = max(-1., min(1., (inspection.y() - origin.y()) / 250))
        # A blink closes quickly and opens a little more slowly. The closed-eye
        # artwork is registered to the original, preserving the cheeky face.
        blink = 0.
        if kind == "blink":
            blink = max((math.cos((progress - center) / width * math.pi / 2) ** 2
                         if abs(progress - center) < width else 0)
                        for center, width in ((.25, .16), (.78, .14)))
        elif kind in {"yawn", "curl", "settle"}:
            blink = envelope * (.85 if kind == "yawn" else .45)
        touch_age = now - self.touch_started
        touch = math.exp(-touch_age * 3.2) * math.sin(touch_age * 10) if 0 <= touch_age < 1.6 else 0.
        if 0 <= touch_age < .25:
            blink = max(blink, math.sin(math.pi * touch_age / .25))
        restful = .23 if self.sleep_blend > .7 else 1.
        if not self.fresh(now):
            restful *= .25
        if self.reduced_motion:
            blink = 0.
        return {"kind": kind, "progress": progress, "gesture": envelope * reduced,
                "breath": math.sin(elapsed * (1.05 if self.sleep_blend > .5 else 1.65)),
                "ripple": elapsed if self.fresh(now) else max(0, self.last_live_frame - self.started), "blink": max(self.sleep_blend, blink),
                "tilt": reduced * (-3.5 * self.sleep_blend + .5 * math.sin(elapsed * .43) * restful
                                    + (gaze * 7 if kind in {"peer", "tilt", "tendril-inspect"} else 0) * envelope
                                    + touch * self.touch_direction * 3 + self.flight_bank
                                    + gaze * (1 - self.sleep_blend) * (2 if inspection is not None else 0)),
                "lean": reduced * gaze * (envelope * (5 if kind in {"peer", "tilt", "tendril-inspect"} else 1)
                                           + (3 * (1 - self.sleep_blend) if inspection is not None else 0)),
                "stretch": reduced * envelope if kind == "stretch" else 0.,
                "curl": reduced * envelope if kind in {"curl", "sleep", "settle"} else 0.,
                "startle": reduced * envelope if kind == "startled" else 0.,
                "touch": reduced * touch, "amplitude": reduced * restful,
                "flight": reduced * self.flight_strength, "flight_x": reduced * self.flight_velocity.x(),
                "flight_y": reduced * self.flight_velocity.y(), "typing": reduced * self.typing_blend,
                "typing_phase": self.typing_phase, "gaze_y": gaze_y * reduced,
                "facing": (-1. if self.clip_sample.mirror else 1.) if self.clip_sample is not None
                          else self.facing if not self.reduced_motion else (1 if self.facing_target >= 0 else -1)}

    def receive_state(self, state):
        self.state = state
        self.connected = True
        self.last_seen = time.monotonic()
        gesture = state.get("gesture")
        if (isinstance(gesture, dict) and isinstance(gesture.get("id"), str)
                and gesture["id"] != self.gesture_clock_id):
            start = gesture.get("started_at")
            server = state.get("server_time")
            if (isinstance(start, (int, float)) and math.isfinite(start)
                    and isinstance(server, (int, float)) and math.isfinite(server)):
                self.gesture_clock_id = gesture["id"]
                self.gesture_clock_start = self.last_seen - (server - start)
        runtime = state.get("runtime")
        self.status = "Core recovering · " + state["behavior"] if isinstance(runtime, dict) and runtime.get("status") != "ok" else state["behavior"]
        utterance = state.get("utterance")
        utterance = utterance if isinstance(utterance, dict) else {}
        if utterance.get("id") and utterance["id"] != self.glyph_id:
            self.glyph_id = utterance["id"]
            # A stale inscription is history, not a new desktop utterance.
            created_at = utterance.get("created_at", 0)
            age = time.time() - created_at if isinstance(created_at, (int, float)) else math.inf
            glyphs = utterance.get("glyphs", [])
            glyphs = glyphs if isinstance(glyphs, list) else []
            self.glyph_sequence = [g for g in glyphs
                                   if isinstance(g, int) and not isinstance(g, bool) and 0 <= g < 20][:3] if 0 <= age < 12 else []
            self.glyph_started = time.monotonic()
        self.render_frame(time.monotonic())
        self.update()

    def disconnect(self, reason):
        if self.connected or self.status != reason:
            self.status_until = time.monotonic() + 6
        self.connected = False
        self.status = reason
        self.update()

    def start_awareness(self):
        """Observe local geometry/event counts only in an actual X11 session."""
        if not self.awareness_enabled or self.awareness_provider is not None or not self.awareness_supported():
            return
        try:
            try:
                from desktop.awareness import DesktopAwareness
            except ModuleNotFoundError:
                from awareness import DesktopAwareness
            self.awareness_provider = DesktopAwareness(enabled=True, poll_interval=.5, own_pid=os.getpid())
            self.awareness_provider.start()
        except (ImportError, OSError, RuntimeError):
            if self.caret_provider is not None:
                self.caret_provider.close()
                self.caret_provider = None
            self.awareness_provider = None
            self.awareness = {"available": False, "enabled": True, "observed_at": time.monotonic(),
                              "source": "unavailable", "permission": "unsupported"}
            return
        self.awareness_timer.start()
        self.poll_awareness()

    @staticmethod
    def awareness_supported():
        session = os.environ.get("XDG_SESSION_TYPE", "")
        return sys.platform == "darwin" and QtWidgets.QApplication.platformName() == "cocoa" or (QtWidgets.QApplication.platformName() == "xcb" and bool(os.environ.get("DISPLAY"))
                and session != "wayland" and not (os.environ.get("WAYLAND_DISPLAY") and session != "x11"))

    def poll_awareness(self):
        if self.awareness_provider is not None:
            self.receive_awareness(self.awareness_provider.snapshot())

    def receive_awareness(self, snapshot):
        """Retain only bounds and aggregate activity, never titles or key data."""
        if not isinstance(snapshot, dict):
            return
        now = time.monotonic()
        observed = snapshot.get("observed_at")
        if not isinstance(observed, (int, float)) or not math.isfinite(observed) or observed > now + 1:
            return

        def rectangle(value):
            if (not isinstance(value, dict)
                    or not all(isinstance(value.get(key), (int, float)) and math.isfinite(value[key]) for key in ("x", "y", "width", "height"))
                    or not 0 < value["width"] < 100000 or not 0 < value["height"] < 100000):
                return None
            return {key: value[key] for key in ("x", "y", "width", "height")}

        window = rectangle(snapshot.get("focused_window"))
        if window is not None:
            window["own"] = snapshot["focused_window"].get("own") is True
        typing = snapshot.get("typing")
        clean_typing = None
        if isinstance(typing, dict):
            last = typing.get("last_at")
            sequence = typing.get("sequence")
            if (isinstance(last, (int, float)) and math.isfinite(last) and last <= now + 1
                    and isinstance(sequence, int) and not isinstance(sequence, bool) and sequence >= 0):
                rate = typing.get("rate", 0)
                rate = max(0., min(60., rate)) if isinstance(rate, (int, float)) and math.isfinite(rate) else 0.
                clean_typing = {"active": typing.get("active") is True, "last_at": last,
                                "sequence": sequence, "rate": rate, "pulse": amount(typing.get("pulse"))}
        if snapshot.get("secure_entry") is True:
            clean_typing = None
        self.awareness = {"available": snapshot.get("available") is True,
                          "enabled": snapshot.get("enabled") is True, "observed_at": observed,
                          "focused_window": window, "typing": clean_typing,
                          "caret": None if snapshot.get("secure_entry") is True else rectangle(snapshot.get("caret")),
                          "source": snapshot.get("source") if snapshot.get("source") in {"x11-xinput2", "mac-readonly", "unavailable"} else "unavailable",
                          "permission": snapshot.get("permission") if snapshot.get("permission") in {"local-observation", "disabled", "unsupported"} else "unsupported",
                          "caret_source": snapshot.get("caret_source") if snapshot.get("caret_source") in {"at-spi", "window-fallback"} else "window-fallback"}
        # Geometry stays in this view. The core receives sparse fixed-category
        # cues only, never a key identity, title, pointer trace or microphone audio.
        if not (self.awareness_enabled and self.awareness["available"] and self.awareness["enabled"]
                and self.fresh(now) and 0 <= now-observed <= 3):
            return
        def unit(value):
            return max(0.,min(1.,float(value))) if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) else 0.
        pointer=snapshot.get("pointer")
        if isinstance(pointer,dict) and pointer.get("available") is True:
            self.awareness["pointer"]={"available":True,"x":unit(pointer.get("x")),"y":unit(pointer.get("y")),"motion":unit(pointer.get("motion"))}
        windows=snapshot.get("windows")
        if isinstance(windows,dict) and windows.get("available") is True:
            rects=[]
            for rect in (windows.get("rects",[]) if isinstance(windows.get("rects"),list) else [])[:8]:
                if isinstance(rect,dict):rects.append({k:unit(rect.get(k)) for k in ("x","y","width","height")})
            self.awareness["windows"]={"available":True,"count":max(0,min(32,int(windows["count"]))) if isinstance(windows.get("count"),int) else 0,"coverage":unit(windows.get("coverage")),"rects":rects}
        microphone=snapshot.get("microphone")
        if isinstance(microphone,dict):
            self.awareness["microphone"]={"available":microphone.get("available") is True,"in_use":microphone.get("in_use") is True}
        bout=snapshot.get("bout")
        previous=getattr(self,"perception_emissions",{})
        def emit(context,intensity,minimum,sequence=None,observed_wall=None):
            old=previous.get(context,(-math.inf,None,0.))
            escalation=context=="typing" and intensity>=.45 and old[2]<.45 and now-old[0]>=.5
            if (now-old[0]<minimum and not escalation) or sequence is not None and sequence==old[1]:return
            budget=[stamp for stamp in getattr(self,"passive_event_budget",[]) if 0<=now-stamp<60]
            self.passive_event_budget=budget
            if len(budget)>=18:
                self.passive_events_dropped=getattr(self,"passive_events_dropped",0)+1
                return
            budget.append(now)
            self.client.send_event("activity",context=context,source="live",intensity=intensity,timestamp=time.time() if observed_wall is None else observed_wall)
            previous[context]=(now,sequence,intensity)
        if isinstance(bout,dict):
            phase=bout.get("phase");sequence=bout.get("sequence")
            if phase=="active" and clean_typing is not None and 0<=now-clean_typing["last_at"]<=2:
                level=unit(bout.get("level"))
                emit("typing",max(.45,level) if level>=.4 else .16,8,
                     observed_wall=time.time()-max(0.,now-clean_typing["last_at"]))
            elif (phase=="pause" and isinstance(sequence,int) and clean_typing is not None
                  and 0<=now-clean_typing["last_at"]<=10
                  and (unit(bout.get("level"))>=.4 or previous.get("typing",(0,None,0))[2]>=.45)):
                emit("typing-pause",max(.45,unit(bout.get("level"))),2.5,sequence,
                     observed_wall=time.time()-max(0.,now-clean_typing["last_at"]))
        elif self.typing_recent(now) and clean_typing is not None and clean_typing["active"]:
            emit("typing",.16,45,clean_typing["sequence"])
        pointer=self.awareness.get("pointer",{})
        if pointer.get("motion",0)>.08:emit("pointer",pointer["motion"]*.3,15)
        windows=self.awareness.get("windows",{})
        if windows.get("available"):emit("desktop",windows.get("coverage",0)*.2,30)
        microphone=self.awareness.get("microphone",{})
        old_microphone=getattr(self,"microphone_in_use",False)
        if microphone.get("available"):
            current=microphone["in_use"]
            if current:emit("microphone",.55,15)
            elif old_microphone:emit("microphone",0.,0)
            self.microphone_in_use=current
        self.perception_emissions=previous

    def awareness_fresh(self, now):
        window = self.awareness.get("focused_window")
        return (self.awareness_enabled and self.fresh(now) and self.awareness.get("available")
                and self.awareness.get("enabled") and 0 <= now - self.awareness.get("observed_at", 0) <= 3
                and isinstance(window, dict) and not window.get("own"))

    def typing_recent(self, now):
        typing = self.awareness.get("typing")
        return (self.awareness_enabled and self.fresh(now) and self.awareness.get("available")
                and 0 <= now-self.awareness.get("observed_at",0) <= 3 and isinstance(typing, dict)
                and 0 <= now - typing.get("last_at", -math.inf) <= 1.8)

    def inspection_target(self, now):
        if not (self.awareness_enabled and self.fresh(now) and self.awareness.get("available")
                and 0<=now-self.awareness.get("observed_at",0)<=3):return None
        pointer=self.awareness.get("pointer",{})
        if pointer.get("available") and pointer.get("motion",0)>.04 and self.home_screen:
            area=self.home_screen.availableGeometry()
            return QtCore.QPointF(area.x()+pointer["x"]*area.width(),area.y()+pointer["y"]*area.height())
        if not self.awareness_fresh(now):return None
        window = self.awareness["focused_window"]
        rect = QtCore.QRectF(window["x"], window["y"], window["width"], window["height"])
        origin = QtCore.QPointF(self.x() + self.creature_rect.center().x() * self.scale,
                               self.y() + self.creature_rect.center().y() * self.scale)
        target = QtCore.QPointF(max(rect.left(), min(rect.right(), origin.x())),
                               max(rect.top(), min(rect.bottom(), origin.y())))
        if rect.contains(origin):
            options = [QtCore.QPointF(rect.left(), origin.y()), QtCore.QPointF(rect.right(), origin.y()),
                       QtCore.QPointF(origin.x(), rect.top()), QtCore.QPointF(origin.x(), rect.bottom())]
            target = min(options, key=lambda point: math.hypot(point.x() - origin.x(), point.y() - origin.y()))
        return target

    def toggle_awareness(self, checked=False):
        self.awareness_enabled = not self.awareness_enabled
        if self.awareness_enabled:
            self.start_awareness()
        else:
            self.awareness_timer.stop()
            if self.awareness_provider is not None:
                self.awareness_provider.close(timeout=1.)
                self.awareness_provider = None
            if self.caret_provider is not None:
                self.caret_provider.close()
                self.caret_provider = None
            self.awareness = {"available": False, "enabled": False, "observed_at": time.monotonic()}
        self.save_view_preferences()

    @staticmethod
    def graph_point(x, y):
        return QtCore.QPointF(48 + amount(x) * 344, 156 + amount(y) * 146)

    @staticmethod
    def graph_position(point):
        return {"x": amount((point.x() - 48) / 344), "y": amount((point.y() - 156) / 146)}

    def scene_geometry(self, now):
        state = self.state or {}
        self.cache_graph(state, now)
        anchor = self.graph_point(*self.graph_motion.anchor)
        anchor.setX(max(120, min(320, anchor.x())))
        anchor.setY(max(236, min(278, anchor.y())))
        breath = 0 if self.reduced_motion or self.clip_sample is not None else math.sin((now - self.started) * (1.0 if self.sleep_blend > .5 else 1.6))
        # GIFs own the whole silhouette, including breathing and rest poses.
        # Their fixed canvas stays attached to the graph without a texture rig.
        resting = self.sleep_blend if self.clip_sample is None else 0.
        height = 206 * (1 - resting * .07) * (1 + .002 * breath)
        if self.clip_library is not None:
            width=height*self.clip_library.canvas[0]/self.clip_library.canvas[1]
        else:
            art = self.artwork()
            width = height * (art.width() / art.height() if not art.isNull() else .92)
        width *= 1 + resting * .07
        self.creature_rect = QtCore.QRectF(anchor.x() - width / 2 + self.body_offset.x(),
                                         anchor.y() - height + 10 + self.body_offset.y() - self.flight_strength * 9, width, height)
        return anchor, self.graph_points

    def cache_graph(self, state, now=None):
        now=time.monotonic() if now is None else now
        self.graph_motion.sample(state,now,frozen=not self.fresh(now),reduced_motion=self.reduced_motion)
        positions=self.graph_motion.points
        key = (tuple((node_id,*point) for node_id,point in positions.items()),
               tuple((edge["source"], edge["target"]) for edge in state.get("edges", [])))
        if key == self.graph_cache_key:
            return
        self.graph_cache_key = key
        self.graph_points = {node_id:self.graph_point(*point) for node_id,point in positions.items()}
        self.graph_paths = []
        for index, edge in enumerate(state.get("edges", [])):
            a, b = edge["source"], edge["target"]
            if a not in self.graph_points or b not in self.graph_points:
                self.graph_paths.append(None)
                continue
            middle = (self.graph_points[a] + self.graph_points[b]) / 2
            bow = 8 * math.sin(index * 2.4)
            path = QtGui.QPainterPath(self.graph_points[a])
            path.quadTo(middle + QtCore.QPointF(bow, 12 + abs(bow)), self.graph_points[b])
            self.graph_paths.append(path)

    def tendril_geometry(self, points, now):
        """Connect the body to actual attention/activation nodes, not fake targets."""
        if not points:
            return []
        nodes = {n["id"]: n for n in self.state["nodes"]}
        attention = self.state.get("attention")
        gesture = self.gesture(now)
        if (gesture and gesture.get("kind") in {"peer", "tendril-inspect", "signal", "stretch"}
                and gesture.get("target_id") in points and gesture.get("target_id") in nodes):
            # Keep the finite gesture's actual target while it reaches and
            # releases, even if another node briefly wins global attention.
            attention = gesture["target_id"]
        center = self.creature_rect.center()
        ranked = sorted(nodes, key=lambda key: (key == attention, amount(nodes[key].get("activation"))), reverse=True)
        selected = []
        if attention in points:
            selected.append(attention)
        # Supporting contacts linger through small activation-rank crossings.
        # This is local presentation state, never a new learned association.
        contact_clock = now if self.fresh(now) else self.last_live_frame
        contacts = getattr(self, "tendril_contacts", {})
        # Flanking connections provide a real memory hammock even at rest.
        for side in (-1, 1):
            candidates = [key for key in ranked if key not in selected and (points[key].x() - center.x()) * side >= 8]
            if candidates:
                choice = candidates[0]
                previous = contacts.get(side)
                if previous and previous["id"] in candidates:
                    old = previous["id"]
                    if (contact_clock < previous["until"]
                            or amount(nodes[choice].get("activation")) < amount(nodes[old].get("activation")) + .18):
                        choice = old
                if not previous or previous["id"] != choice:
                    contacts[side] = {"id": choice, "until": contact_clock + 1.5}
                selected.append(choice)
            else:
                contacts.pop(side, None)
        self.tendril_contacts = contacts
        if not selected:
            selected = ranked[:1]
        rect = self.creature_rect
        gestures = []
        elapsed = now - self.started if self.fresh(now) else max(0, self.last_live_frame - self.started)
        pose = self.pose(now)
        for index, key in enumerate(selected[:3]):
            target = points[key]
            side = -1 if target.x() < center.x() else 1
            # Flight raises the attachment points into the opaque mantle/arm
            # junction. Apply the exact body turn/bank transform to each root;
            # the actual graph contact stays in world coordinates.
            flying = smoothstep(.15, .85, pose["flight"])
            reach_side = side * (1 if pose["facing"] >= 0 else -1)
            u = .5 + reach_side * (.32 * (1 - flying) + .16 * flying)
            v = (.75 + .045 * index) * (1 - flying) + (.57 + .025 * index) * flying
            anchors = getattr(self.clip_sample, "anchors", {}) if self.clip_sample is not None else {}
            contact = anchors.get("center" if index == 0 else "left" if reach_side < 0 else "right")
            if (isinstance(contact, (list, tuple)) and len(contact) == 2
                    and all(isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1 for value in contact)):
                u, v = contact
            start = self.body_transform(pose).map(QtCore.QPointF(rect.left() + u * rect.width(), rect.top() + v * rect.height()))
            active = amount(nodes[key].get("activation"))
            gesture = 5 * math.sin(elapsed * .75 + index * 2.2) * pose["amplitude"]
            reaching = pose["gesture"] if key == attention else pose["stretch"] * .7
            # Attention lowers one limb to investigate a specific real node;
            # the other two hold the creature's weight. Stretch/curl flow down
            # the arms with different phases rather than moving in lockstep.
            reach = reaching * (20 if pose["kind"] in {"peer", "tendril-inspect", "signal"} else 10)
            curl = pose["curl"] * (16 + index * 4)
            trail = QtCore.QPointF(max(-22, min(22, -pose["flight_x"] * .035)),
                                   max(-14, min(14, -pose["flight_y"] * .025)))
            tapping = math.sin(pose["typing_phase"] * 8 + index * 2.5) * pose["typing"]
            curve = QtGui.QPainterPath(start)
            curve.cubicTo(start + QtCore.QPointF(side * (32 + active * 18 + reach - curl),
                                                14 + gesture - pose["stretch"] * 18 - tapping * 7) + trail,
                          target + QtCore.QPointF(-side * (24 + active * 12 + curl),
                                                 20 + gesture - reach + curl + tapping * 3), target)
            gestures.append((key, curve, active))
        return gestures

    def draw_glow(self, painter, point, radius, color, alpha):
        # Hundreds of radial-gradient allocations per frame made a sleeping
        # companion needlessly expensive. Reuse small premultiplied sprites.
        radius = max(1, round(radius * 2) / 2)
        key = (radius, color)
        sprite = self.glow_cache.get(key)
        if sprite is None:
            extent = math.ceil(radius) + 1
            sprite = QtGui.QPixmap(extent * 2, extent * 2)
            sprite.fill(QtCore.Qt.transparent)
            glow = QtGui.QPainter(sprite)
            glow.setRenderHint(QtGui.QPainter.Antialiasing)
            center = QtCore.QPointF(extent, extent)
            gradient = QtGui.QRadialGradient(center, radius)
            gradient.setColorAt(0, QtGui.QColor(*color, 255))
            gradient.setColorAt(.35, QtGui.QColor(*color, 77))
            gradient.setColorAt(1, QtGui.QColor(*color, 0))
            glow.setPen(QtCore.Qt.NoPen)
            glow.setBrush(gradient)
            glow.drawEllipse(center, radius, radius)
            glow.end()
            if len(self.glow_cache) > 256:
                self.glow_cache.clear()
            self.glow_cache[key] = sprite
        opacity = painter.opacity()
        painter.setOpacity(opacity * max(0, min(255, alpha)) / 255)
        painter.drawPixmap(point - QtCore.QPointF(sprite.width() / 2, sprite.height() / 2), sprite)
        painter.setOpacity(opacity)

    def draw_graph(self, painter, points, elapsed, contacts):
        state = self.state or {}
        nodes = {n["id"]: n for n in state.get("nodes", [])}
        attention = state.get("attention")
        for index, edge in enumerate(state.get("edges", [])):
            a, b = edge["source"], edge["target"]
            if a not in points or b not in points:
                continue
            activity = max(amount(nodes[a].get("activation")), amount(nodes[b].get("activation")))
            weight = amount(edge.get("weight"), .3)
            focus = a == attention or b == attention
            visibility = .55 + .45 * (.5 + .5 * math.sin(elapsed * .31 + index * 1.618))
            alpha = (13 + weight * 24 + activity * 72 + (16 if focus else 0)) * visibility
            path = self.graph_paths[index]
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.setPen(QtGui.QPen(QtGui.QColor(66, 192, 201, int(alpha * .26)), 4.5 + weight, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
            painter.drawPath(path)
            painter.setPen(QtGui.QPen(QtGui.QColor(127, 225, 213, int(alpha)), .55 + weight * .8))
            painter.drawPath(path)
            if activity > .06:
                phase = (elapsed * (.08 + activity * .15) + index * .381) % 1
                pulse = path.pointAtPercent(phase)
                self.draw_glow(painter, pulse, 5 + activity * 3, (115, 239, 215), 35 + activity * 100)
        for index, (key, point) in enumerate(points.items()):
            active = amount(nodes[key].get("activation"))
            focus = key == attention
            contacted = key in contacts
            breath = .75 + .25 * math.sin(elapsed * (.65 + active) + index * 1.7)
            self.draw_glow(painter, point, 7 + active * 12 + (3 if focus else 0),
                           (113, 231, 214), (16 + active * 95 + (18 if focus else 0)) * breath)
            radius = 6 + active * 2 if contacted else 1.2 + active * 2.5 + (1 if focus else 0)
            painter.setPen(QtGui.QPen(QtGui.QColor(172, 246, 228, 120 + int(active * 100)), .55))
            if contacted:
                # Only nodes physically touched by a rendered arm become a
                # little shaded pearl, keeping the rest of the field ephemeral.
                pearl = QtGui.QRadialGradient(point - QtCore.QPointF(radius * .28, radius * .34), radius * 1.35)
                pearl.setColorAt(0, QtGui.QColor(171, 244, 223, 220))
                pearl.setColorAt(.30, QtGui.QColor(79, 181, 157, 215))
                pearl.setColorAt(.65, QtGui.QColor(28, 111, 108, 210))
                pearl.setColorAt(1, QtGui.QColor(13, 51, 71, 180))
                painter.setBrush(pearl)
            else:
                painter.setBrush(QtGui.QColor(95, 210, 196, int(65 + active * 150)))
            painter.drawEllipse(point, radius, radius)
            if focus:
                painter.setPen(QtGui.QPen(QtGui.QColor(159, 244, 221, 45 + int(active * 65)), .7))
                painter.setBrush(QtCore.Qt.NoBrush)
                orbit = radius + 3
                painter.drawArc(QtCore.QRectF(point.x() - orbit, point.y() - orbit, orbit * 2, orbit * 2), int(elapsed * 23) * 16, 215 * 16)

    def draw_tendrils(self, painter, gestures, now):
        for index, (key, centerline, active) in enumerate(gestures):
            left, right = [], []
            count = 18
            for step in range(count + 1):
                t = step / count
                point = centerline.pointAtPercent(t)
                before = centerline.pointAtPercent(max(0, t - .01))
                after = centerline.pointAtPercent(min(1, t + .01))
                dx, dy = after.x() - before.x(), after.y() - before.y()
                length = max(.001, math.hypot(dx, dy))
                half_width = (1 - t) ** .85 * (7.5 + active * 1.5) + .7
                normal = QtCore.QPointF(-dy / length * half_width, dx / length * half_width)
                left.append(point + normal)
                right.append(point - normal)
            shape = QtGui.QPainterPath()
            shape.addPolygon(QtGui.QPolygonF(left + list(reversed(right))))
            shape.closeSubpath()
            start, end = centerline.pointAtPercent(0), centerline.pointAtPercent(1)
            gradient = QtGui.QLinearGradient(start, end)
            gradient.setColorAt(0, QtGui.QColor(22, 86, 107, 248))
            gradient.setColorAt(.38, QtGui.QColor(39, 107, 124, 240))
            gradient.setColorAt(.70, QtGui.QColor(84, 73, 125, 232))
            gradient.setColorAt(1, QtGui.QColor(85, 217, 195, 205))
            painter.setPen(QtGui.QPen(QtGui.QColor(6, 28, 53, 245), 1.4))
            painter.setBrush(gradient)
            painter.drawPath(shape)
            painter.setPen(QtGui.QPen(QtGui.QColor(140, 236, 218, 112), .8))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawPath(centerline)
            for step in range(4, 12, 2):
                t = step / 13
                dot = centerline.pointAtPercent(t)
                pulse = .5 + .5 * math.sin((now - self.started) * 1.4 - step * .7 + index)
                self.draw_glow(painter, dot, 2.3, (139, 241, 226), 40 + active * 50 * pulse)
            self.draw_glow(painter, end, 7 + active * 7, (139, 241, 213), 60 + active * 95)

    def status_visible(self, now):
        return self.hovering or self.menu_open or now < self.status_until

    def cached_art(self, source):
        if source.isNull():
            return source
        # Keep the original files untouched; the desktop only needs a small
        # supersampled texture, not a 1536px rescale for every animated patch.
        ratio = self.devicePixelRatioF()
        height = max(64, math.ceil(self.creature_rect.height() * self.scale * ratio * 1.5 / 16) * 16)
        key = (source.cacheKey(), height)
        if key not in self.art_cache:
            if len(self.art_cache) > 16:
                self.art_cache.clear()
            self.art_cache[key] = source.scaledToHeight(height, QtCore.Qt.SmoothTransformation)
        return self.art_cache[key]

    def draw_body(self, painter, now):
        """Draw one actual GIF frame, with a static-image compatibility fallback."""
        pose = self.pose(now)
        painter.save()
        painter.setTransform(self.body_transform(pose), True)
        if self.clip_sample is not None and not self.clip_sample.image.isNull():
            # The decoded frame owns the silhouette and expression. Never
            # crossfade it with another pose or warp it through a texture mesh.
            dragging = self.press_global is not None and self.dragged and self.drag_mode == "window"
            self.skin.update(now, state=self.state, motion=max(self.flight_strength, .85 if dragging else 0.),
                             touch_age=now-self.touch_started, gesture=(self.gesture(now) or {}).get("kind"),
                             fresh=self.fresh(now), reduced_motion=self.reduced_motion)
            # Keep the source resolution here: Qt must perform exactly the
            # same final sampling as the unshaded GIF, including its alpha
            # silhouette, eye detail and the desktop's input shape.
            image = self.skin.shade(self.clip_sample) if self.reference_renderer else self.clip_sample.image
            painter.drawImage(self.creature_rect, image)
        else:
            art = self.artwork()
            if not self.sleep_art.isNull() and pose["blink"] >= .5:
                art = self.sleep_art
            elif not self.reduced_motion:
                kind = "typing" if pose["typing"] > .5 else "flight" if pose["flight"] > .5 else pose["kind"]
                optional = self.pose_art.get(kind)
                if optional is not None and not optional.isNull():
                    art = optional
            if not art.isNull():
                texture = self.cached_art(art)
                painter.drawPixmap(self.creature_rect, texture, QtCore.QRectF(texture.rect()))
        painter.restore()

    def body_transform(self, pose):
        pivot = self.creature_rect.center() + QtCore.QPointF(0, 30)
        transform = QtGui.QTransform()
        transform.translate(pivot.x(), pivot.y())
        if self.clip_sample is not None:
            # Body, protected eyes and skin turn together in one instant.
            transform.rotate(max(-16., min(16., self.flight_bank)))
            transform.scale(-1. if self.clip_sample.mirror else 1., 1.)
        else:
            transform.rotate(pose["tilt"])
            transform.scale(-1. if pose["facing"] < 0 else 1., 1.)
        transform.translate(-pivot.x(), -pivot.y())
        return transform

    def enable_gpu(self):
        if QtWidgets.QApplication.platformName() in {"offscreen","minimal"}:
            return False
        try:
            from desktop.gpu import GpuScene
            scene=GpuScene(self)
            if not scene.available:
                self.gpu_error="; ".join(scene.errors)
                scene.deleteLater()
                return False
            from desktop.animation import ClipPlayer
            self.clip_library=scene.playback_library()
            self.clip_player=ClipPlayer(self.clip_library)
            self.clip_sample=None
            self.clip_pixmap=QtGui.QPixmap();self.clip_pixmap_key=None
            self.static_art=QtGui.QPixmap();self.sleep_art=QtGui.QPixmap();self.pose_art.clear();self.art_cache.clear()
            QtGui.QPixmapCache.clear()
            self.gpu_scene=scene
            scene.setGeometry(self.rect())
            scene.show()
            self.render_frame(time.monotonic())
            self.update()
            return True
        except (ImportError,OSError,RuntimeError,ValueError) as error:
            self.gpu_error=type(error).__name__+": "+str(error)
            return False

    def render_gpu_frame(self, now, anchor, points, gestures):
        sample=self.clip_sample
        if sample is None:return
        dragging=self.press_global is not None and self.dragged and self.drag_mode=="window"
        self.skin.update(now,state=self.state,motion=max(self.flight_strength,.85 if dragging else 0.),
                         touch_age=now-self.touch_started,gesture=(self.gesture(now) or {}).get("kind"),
                         fresh=self.fresh(now),reduced_motion=self.reduced_motion)
        state=self.state or {};by_id={n["id"]:n for n in state.get("nodes",[])}
        contacts={key for key,_,_ in gestures};attention=state.get("attention")
        visual=self.graph_motion.values
        nodes=[{"id":key,"x":point.x(),"y":point.y(),"activation":visual[key]["activation"],
                "focus":key==attention,"contact":key in contacts,
                "focusStrength":visual[key]["focus"],"contactStrength":visual[key]["contact"]}
               for key,point in points.items()]
        edges=[]
        for i,edge in enumerate(state.get("edges",[])):
            a,b=edge["source"],edge["target"]
            if a not in points or b not in points:continue
            middle=(points[a]+points[b])/2;bow=8*math.sin(i*2.4)
            edges.append({"x0":points[a].x(),"y0":points[a].y(),"x1":points[b].x(),"y1":points[b].y(),
                          "cx":middle.x()+bow,"cy":middle.y()+12+abs(bow),"index":i,
                          "activation":max(visual[a]["activation"],visual[b]["activation"]),
                          "weight":amount(edge.get("weight"),.3),"focus":a==attention or b==attention,
                          "focusStrength":max(visual[a]["focus"],visual[b]["focus"])})
        tendrils=[]
        for i,(_,curve,active) in enumerate(gestures):
            values=[curve.elementAt(j) for j in range(4)]
            tendrils.append(dict(zip(("x0","y0","cx0","cy0","cx1","cy1","x1","y1"),
                                     [v for e in values for v in (e.x,e.y)]),activation=active,index=i))
        glyphs=[];age=now-self.glyph_started
        if self.fresh(now) and self.glyph_sequence and 0<=age<7:
            import base64
            x=max(22,min(CANVAS_WIDTH-80,anchor.x()+64));y=max(18,self.creature_rect.top()+42-(0 if self.reduced_motion else age*5))
            for i,glyph in enumerate(self.glyph_sequence):
                svg=('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="'+GLYPH_PATHS[glyph]+'" fill="none" stroke="#b5fae8" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/></svg>')
                glyphs.append({"source":"data:image/svg+xml;base64,"+base64.b64encode(svg.encode()).decode(),
                               "x":x+i*20,"y":y+(0 if self.reduced_motion else math.sin(i+age)*2),
                               "opacity":max(0.,min(1.,age/.45,(7-age)/2))*.85})
        clip=self.clip_library.clips[sample.clip];delay=clip.delays_ms[sample.index]
        phase=0. if self.reduced_motion else (getattr(sample,"phase",max(0.,min(1.,1-sample.next_frame_ms/delay))) if self.fresh(now) else getattr(self,"last_gpu_phase",0.))
        self.last_gpu_phase=phase
        rect=self.creature_rect
        self.gpu_scene.setGeometry(self.rect())
        self.gpu_scene.set_scene(clip=sample.clip,index=sample.index,phase=phase,
            body_rect=(rect.x(),rect.y(),rect.width(),rect.height()),mirror=sample.mirror,bank=self.flight_bank,
            clock=0. if self.reduced_motion else max(0.,self.last_live_frame-self.started),
            skin_weights=tuple(float(x) for x in self.skin.weights),skin_clock=self.skin.phase,skin_intensity=float(self.skin.intensity) if self.skin.mode!="off" else 0.,
            graph_gain=self.graph_gain,nodes=nodes,edges=edges,tendrils=tendrils,glyphs=glyphs,
            opacity=1. if self.connected else .48,morph_strength=0. if self.reduced_motion else 1.,
            status={"visible":self.status_visible(now),"text":"Terminus · "+self.status},
            desktop_rects=self.awareness.get("windows",{}).get("rects",[]) if self.awareness_enabled else (),
            cursor=(self.awareness["pointer"]["x"],self.awareness["pointer"]["y"],self.awareness["pointer"]["motion"])
                if self.awareness_enabled and self.awareness.get("pointer",{}).get("available") else None,
            mic_active=self.awareness.get("microphone",{}).get("in_use",False) if self.awareness_enabled else False)
        if now-self.last_mask>=.5 or self.input_region.isEmpty():
            # Native hit testing uses source alpha and a few vector curves at
            # 2Hz. It never reads the GPU framebuffer or the rest of the desktop.
            frame=QtGui.QImage(self.size(),QtGui.QImage.Format_ARGB32_Premultiplied);frame.fill(QtCore.Qt.transparent)
            painter=QtGui.QPainter(frame);painter.scale(self.scale,self.scale)
            painter.save();painter.setTransform(self.body_transform(self.pose(now)),True)
            matte=self.gpu_scene.hit_frame(sample.clip,sample.index)
            painter.drawImage(rect,matte);painter.restore()
            painter.setPen(QtGui.QPen(QtCore.Qt.white,5));painter.setBrush(QtCore.Qt.NoBrush)
            for _,curve,_ in gestures:painter.drawPath(curve)
            painter.setPen(QtGui.QPen(QtCore.Qt.white,2))
            for path in self.graph_paths:
                if path is not None:painter.drawPath(path)
            painter.end();self.update_input_mask(frame);self.last_mask=now

    def render_frame(self, now):
        started = time.perf_counter()
        if self.gpu_scene is not None and not self.gpu_scene.available:
            scene=self.gpu_scene;self.gpu_scene=None
            self.gpu_error="; ".join(scene.errors) or "GPU renderer unavailable"
            scene.hide();scene.deleteLater()
            self.art_signature=None;self.load_art()
        if self.fresh(now):
            self.last_live_frame = now
        self.prepare_clip(now)
        clock = self.last_live_frame
        elapsed = 0 if self.reduced_motion else max(0, clock - self.started)
        anchor, points = self.scene_geometry(now)
        gestures = self.tendril_geometry(points, now)
        self.graph_motion.set_contacts(key for key,_,_ in gestures)
        if self.gpu_scene is not None and self.gpu_scene.available:
            self.render_gpu_frame(now,anchor,points,gestures)
            self.render_ms=(time.perf_counter()-started)*1000
            return
        graph = QtGui.QImage(self.size(), QtGui.QImage.Format_ARGB32_Premultiplied)
        graph.fill(QtCore.Qt.transparent)
        graph_painter = QtGui.QPainter(graph)
        graph_painter.setRenderHint(QtGui.QPainter.Antialiasing)
        graph_painter.scale(self.scale, self.scale)
        graph_painter.setOpacity(1 if self.connected else .48)
        self.draw_graph(graph_painter, points, elapsed, {key for key, _, _ in gestures})
        graph_painter.end()
        foreground = QtGui.QImage(self.size(), QtGui.QImage.Format_ARGB32_Premultiplied)
        foreground.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(foreground)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.scale(self.scale, self.scale)
        painter.setOpacity(1 if self.connected else .48)
        self.draw_tendrils(painter, gestures, self.started if self.reduced_motion else clock)
        self.draw_body(painter, now)
        painter.setOpacity(1)
        # Inscribed signs float away only after a fresh real core utterance.
        glyph_age = now - self.glyph_started
        if self.fresh(now) and self.glyph_sequence and 0 <= glyph_age < 7:
            opacity = min(1., glyph_age / .45, (7 - glyph_age) / 2)
            painter.save()
            painter.setOpacity(opacity * .85)
            x = max(22, min(CANVAS_WIDTH - 80, anchor.x() + 64))
            y = max(18, self.creature_rect.top() + 42 - (0 if self.reduced_motion else glyph_age * 5))
            for index, glyph in enumerate(self.glyph_sequence):
                self.glyph_renderers[glyph].render(painter, QtCore.QRectF(x + index * 20, y + (0 if self.reduced_motion else math.sin(index + glyph_age) * 2), 17, 20))
            painter.restore()
        if self.drag_target is not None:
            target = self.graph_point(**self.graph_position(self.drag_target))
            painter.setPen(QtGui.QPen(QtGui.QColor(183, 246, 223, 150), 1, QtCore.Qt.DashLine))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawLine(anchor, target)
            painter.drawEllipse(target, 6, 6)
        if self.status_visible(now):
            # Brief help/status beside the creature, with no permanent furniture.
            painter.setFont(QtGui.QFont("Sans Serif", 8))
            text = self.status if not self.connected else "Terminus · " + self.status
            if self.roaming_paused:
                text += " · staying here"
            metrics = painter.fontMetrics()
            label = QtCore.QRectF(0, 0, min(396, metrics.horizontalAdvance(text) + 20), 24)
            label.moveCenter(QtCore.QPointF(220, 322))
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(10, 20, 28, 210))
            painter.drawRoundedRect(label, 9, 9)
            painter.setPen(QtGui.QColor(195, 237, 223) if self.connected else QtGui.QColor(239, 191, 132))
            painter.drawText(label.adjusted(8, 0, -8, 0), QtCore.Qt.AlignCenter,
                             metrics.elidedText(text, QtCore.Qt.ElideRight, int(label.width() - 16)))
        painter.end()
        frame = graph.copy()
        composite = QtGui.QPainter(frame)
        # Add premultiplied light instead of clamping a second source-over
        # layer. Bright is a real 2.8x graph-alpha gain, with unchanged colors.
        composite.setCompositionMode(QtGui.QPainter.CompositionMode_Plus)
        remaining = max(0., min(4., self.graph_gain) - 1)
        while remaining > .001:
            composite.setOpacity(min(1., remaining))
            composite.drawImage(0, 0, graph)
            remaining -= 1
        composite.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
        composite.setOpacity(1)
        composite.drawImage(0, 0, foreground)
        composite.end()
        self.frame = frame
        mask_interval = .45 if self.sleep_blend > .8 or self.reduced_motion else .24
        if now - self.last_mask > mask_interval or self.input_region.isEmpty():
            # Brighter light must not intercept more of the desktop. The input
            # shape uses the original graph alpha, before the visual boost.
            input_frame = graph.copy()
            mask_painter = QtGui.QPainter(input_frame)
            mask_painter.drawImage(0, 0, foreground)
            mask_painter.end()
            self.update_input_mask(input_frame)
            self.last_mask = now
        self.render_ms = (time.perf_counter() - started) * 1000

    def update_input_mask(self, frame):
        started = time.perf_counter()
        # QBitmap alphaMask's normal 50% threshold would cut off the graph.
        # Threshold at 2/255 instead, and pad two pixels for breathing/glows.
        alpha = frame.convertToFormat(QtGui.QImage.Format_Alpha8)
        pointer = alpha.constBits()
        pass  # Qt 6 returns an already sized memoryview.
        # QBitmap's opaque color is black (Qt.color1); white is transparent.
        threshold = bytes(pointer).translate(bytes(0 if value > 2 else 255 for value in range(256)))
        monochrome = QtGui.QImage(threshold, alpha.width(), alpha.height(), alpha.bytesPerLine(),
                                  QtGui.QImage.Format_Grayscale8).convertToFormat(QtGui.QImage.Format_Mono, QtCore.Qt.ThresholdDither)
        region = QtGui.QRegion(QtGui.QBitmap.fromImage(monochrome))
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            region = region.united(region.translated(dx, dy))
        self.input_region = region
        if sys.platform != "darwin":
            gpu=self.gpu_scene is not None and self.gpu_scene.available
            if self.native_input_shape is not None and self.native_input_shape.available:
                if not self.native_input_shape.set_region(region):
                    if gpu:self.gpu_scene._graphics_error(None,"Native input shape unavailable; using raster")
                    self.setMask(region)
            elif not gpu and self.mask()!=region:
                self.setMask(region)

        self.mask_ms = (time.perf_counter() - started) * 1000

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        if self.gpu_scene is not None and self.gpu_scene.available:
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
            painter.fillRect(self.rect(),QtCore.Qt.transparent)
        else:
            painter.drawImage(0, 0, self.frame)

    def animate(self):
        now = time.monotonic()
        dt = min(.15, max(0., now - self.last_frame))
        self.last_frame = now
        target = 1. if (self.state or {}).get("behavior") in {"sleep", "dream"} and (self.gpu_scene is not None or not self.sleep_art.isNull()) else 0.
        # This is a resident companion: slow sleep breathing does not need a
        # full 30-fps repaint, and a disconnected view can be quieter still.
        interval = self.frame_interval(now)
        if self.animation.interval() != interval:
            self.animation.setInterval(interval)
        self.sleep_blend = target if self.reduced_motion else self.sleep_blend + (target - self.sleep_blend) * (1 - math.exp(-dt / .7))
        self.advance_physics(dt)
        self.advance_motion(now, dt)
        self.advance_presentation(now, dt)
        self.render_frame(now)
        self.update()

    def frame_interval(self, now):
        if self.gpu_scene is not None and self.gpu_scene.available:
            if self.reduced_motion:return 250
            if not self.fresh(now):return 500
            if self.graph_motion.settling:return 33
            if self.hovering or self.press_global is not None or now-self.touch_started<1.6:return 50
            if self.gesture(now) or self.roam_goal is not None and self.can_roam(now):return 66
            return 250 if (self.state or {}).get("behavior") in {"sleep","dream"} else 125
        interval = self.presentation_interval(now)
        if self.clip_sample is not None and not self.reduced_motion and self.fresh(now):
            interval = min(interval, max(20, min(250, int(self.clip_sample.next_frame_ms))))
            if self.skin.mode != "off" and self.skin.atlas.frames:
                interval = min(interval, 167 if (self.state or {}).get("behavior") in {"sleep", "dream"} else 66)
        if sys.platform == "darwin":
            interacting = self.hovering or self.press_global is not None or now-self.touch_started < 1.6
            moving = self.roam_goal is not None and self.can_roam(now)
            if interacting:
                interval = max(interval, 50)
            elif moving or self.gesture(now):
                interval = max(interval, 66)
            else:
                # A fanless laptop should not repaint a quiet resident at GIF
                # speed just because the next source frame is near its boundary.
                floor = 250 if (self.state or {}).get("behavior") in {"sleep","dream"} else 125
                interval = max(interval, floor)
        return interval

    def presentation_interval(self, now):
        if self.reduced_motion:
            return 250
        if self.hovering or self.press_global is not None or now - self.touch_started < 1.6:
            return 33
        if not self.fresh(now):
            return 500
        if self.gesture(now):
            return 66 if (self.state or {}).get("behavior") in {"sleep", "dream"} else 33
        if self.glyph_sequence and now - self.glyph_started < 7:
            return 50
        if self.flight_strength > .025 or abs(self.facing - self.facing_target) > .015 or self.typing_blend > .02:
            return 33
        if self.roam_goal is not None and self.can_roam(now):
            return 40
        return 167 if (self.state or {}).get("behavior") in {"sleep", "dream"} else 66

    def advance_physics(self, dt):
        if self.reduced_motion:
            self.body_offset = QtCore.QPointF()
            self.body_velocity = QtCore.QPointF()
            return
        # A short, damped spring makes a touch or placement feel like it has
        # mass. It is local rendering feedback, never a synthetic core event.
        remaining = min(.2, max(0, dt))
        while remaining > .0001:
            step = min(.025, remaining)
            self.body_velocity += (self.body_offset * -55 - self.body_velocity * 10) * step
            self.body_offset += self.body_velocity * step
            remaining -= step
        self.body_offset.setX(max(-9, min(9, self.body_offset.x())))
        self.body_offset.setY(max(-9, min(9, self.body_offset.y())))

    def advance_presentation(self, now, dt):
        """Animate actual movement/activity without inventing an observation."""
        dt = min(.2, max(0., dt))
        if self.reduced_motion:
            self.flight_velocity = QtCore.QPointF()
            self.flight_strength = self.flight_bank = self.typing_blend = 0.
            self.facing = self.facing_target
            return
        dragging = self.press_global is not None and self.dragged and self.drag_mode == "window"
        target_velocity = QtCore.QPointF()
        if dragging and 0 <= now - self.last_drag_at < .18:
            target_velocity = self.drag_velocity
        elif self.roam_goal is not None and self.can_roam(now):
            target_velocity = self.roam_velocity / self.scale
        self.flight_velocity += (target_velocity - self.flight_velocity) * (1 - math.exp(-dt / (.13 if dragging else .32)))
        speed = math.hypot(self.flight_velocity.x(), self.flight_velocity.y())
        strength = amount(speed / 180)
        if not dragging and self.can_roam(now):
            strength = max(strength, min(.32, speed / 70))
        self.flight_strength += (strength - self.flight_strength) * (1 - math.exp(-dt / .22))
        bank = max(-14, min(14, self.flight_velocity.x() / 45))
        bank += max(-5, min(5, self.flight_velocity.y() / 80)) * (1 if self.facing_target >= 0 else -1)
        self.flight_bank += (bank - self.flight_bank) * (1 - math.exp(-dt / .18))

        desired = self.facing_target
        if self.facing_mode in {"left", "right"}:
            desired = -1. if self.facing_mode == "left" else 1.
        elif abs(self.drag_velocity.x() if dragging else self.flight_velocity.x()) > 9:
            direction = self.drag_velocity.x() if dragging else self.flight_velocity.x()
            desired = 1. if direction > 0 else -1.
        elif not dragging and now - self.last_facing_change > 1.2:
            inspection = self.inspection_target(now)
            if inspection is not None and (self.state or {}).get("behavior") not in {"sleep", "dream"}:
                dx = inspection.x() - (self.x() + self.creature_rect.center().x() * self.scale)
                if abs(dx) > 90:
                    desired = 1. if dx > 0 else -1.
            else:
                gesture = self.gesture(now)
                if gesture and gesture.get("kind") in {"peer", "tilt", "tendril-inspect"}:
                    target = self.graph_points.get(gesture.get("target_id"))
                    if target is not None and abs(target.x() - self.creature_rect.center().x()) > 70:
                        desired = 1. if target.x() > self.creature_rect.center().x() else -1.
        if desired != self.facing_target and (dragging or now - self.last_facing_change > .7):
            self.facing_target = desired
            self.last_facing_change = now
        self.facing = self.facing_target

        gesture = self.gesture(now)
        imitate = (gesture and gesture.get("kind") == "imitate" and self.typing_recent(now)
                   and not dragging and self.flight_strength < .25)
        self.typing_blend += ((1. if imitate else 0.) - self.typing_blend) * (1 - math.exp(-dt / .28))
        if imitate:
            self.typing_phase += dt * (.7 + min(12., self.awareness["typing"].get("rate", 0)) * .08)

    def motion_bounds(self, area=None):
        screen = self.home_screen or self.screen() or QtWidgets.QApplication.primaryScreen()
        area = area if area is not None else screen.availableGeometry()
        return (area.left() + 8, area.top() + 8,
                max(area.left() + 8, area.right() - self.width() - 7),
                max(area.top() + 8, area.bottom() - self.height() - 7))

    def advance_motion(self, now, dt, area=None):
        # Only the native *view* drifts. This never creates events, revises the
        # organism, or persists a second model. Resting core states stay put.
        behavior = (self.state or {}).get("behavior", "sleep")
        if not self.can_roam(now):
            self.roam_velocity = QtCore.QPointF()
            return
        motion = (self.state or {}).get("motion")
        left, top, right, bottom = self.motion_bounds(area)
        if self.roam_position is None:
            self.roam_position = QtCore.QPointF(self.pos())
        position = self.roam_position
        if self.roam_goal is None:
            if now < self.next_departure:
                return
            self.roam_step += 1
            self.roam_goal = self.window_perch(now, position, (left, top, right, bottom), motion)
            if self.roam_goal is None:
                self.roam_goal = self.next_perch(position, (left, top, right, bottom), motion)
        delta = self.roam_goal - position
        distance = math.hypot(delta.x(), delta.y())
        exploring = isinstance(motion, dict) and motion.get("intent") == "explore"
        speed = 22 if exploring else (16 if behavior == "inspect" else 12)
        dt = min(.2, max(0, dt))
        speed *= smoothstep(0, 65, distance) * .85 + .15
        desired = delta * (speed / distance) if distance > .01 else QtCore.QPointF()
        self.roam_velocity += (desired - self.roam_velocity) * (1 - math.exp(-dt / .65))
        travel = math.hypot(self.roam_velocity.x(), self.roam_velocity.y()) * dt
        if distance > .01:
            position += self.roam_velocity * dt if travel < distance else delta
        position.setX(max(left, min(right, position.x())))
        position.setY(max(top, min(bottom, position.y())))
        self.moving_window = True
        self.move(position.toPoint())
        self.moving_window = False
        if distance <= max(1., travel + .2):
            self.roam_goal = None
            self.roam_velocity = QtCore.QPointF()
            self.next_departure = now + 9 + (self.roam_step % 4) * 4

    def can_roam(self, now):
        """Share movement eligibility with the resident repaint scheduler.

        A destination can survive a nap or a user pause. Merely retaining that
        destination must not keep a stationary body repainting at travel speed.
        """
        behavior = (self.state or {}).get("behavior", "sleep")
        if (not self.fresh(now) or self.reduced_motion or self.roaming_paused or self.hovering or self.menu_open
                or self.press_global is not None or now < self.interaction_until
                or behavior in {"sleep", "dream", "startled", "attend", "settle"}):
            return False
        motion = (self.state or {}).get("motion")
        if isinstance(motion, dict):
            start, duration = motion.get("started_at"), motion.get("duration")
            return (motion.get("intent") in {"drift", "explore"}
                    and isinstance(start, (int, float)) and math.isfinite(start)
                    and isinstance(duration, (int, float)) and math.isfinite(duration)
                    and 0 < duration <= 600 and 0 <= self.core_time(now) - start < duration)
        return motion is None

    def next_perch(self, position, bounds, motion):
        """Take continuous excursions along the monitor's available perimeter.

        No screen contents or app identities are inspected. Most perches are
        beside an edge, leaving the working centre available. A manually placed
        body first approaches the closest rim rather than teleporting there.
        """
        left, top, right, bottom = bounds
        width, height = right - left, bottom - top
        perimeter = 2 * (width + height)
        if perimeter <= .1:
            return QtCore.QPointF(left, top)
        candidates = ((abs(position.y() - top), position.x() - left),
                      (abs(position.x() - right), width + position.y() - top),
                      (abs(position.y() - bottom), width + height + right - position.x()),
                      (abs(position.x() - left), 2 * width + height + bottom - position.y()))
        rim_distance, along = min(candidates)
        exploring = isinstance(motion, dict) and motion.get("intent") == "explore"
        excursion = (390 + (self.roam_step * 137 % 420)) if exploring else (180 + self.roam_step * 83 % 250)
        # The organism's identity sets a preferred direction. Excursions keep
        # that direction for several stops, so he explores instead of circling
        # the same tiny patch at the bottom right.
        identity = str((self.state or {}).get("organism_id", "terminus"))
        direction = 1 if sum(map(ord, identity)) % 2 else -1
        if (self.roam_step // 7) % 2:
            direction *= -1
        if rim_distance > 100:
            excursion *= .25
        along = (along + excursion * direction) % perimeter
        if along <= width:
            return QtCore.QPointF(left + along, top)
        along -= width
        if along <= height:
            return QtCore.QPointF(right, top + along)
        along -= height
        if along <= width:
            return QtCore.QPointF(right - along, bottom)
        return QtCore.QPointF(left, bottom - (along - width))

    def window_perch(self, now, position, bounds, motion):
        if (not isinstance(motion, dict) or motion.get("intent") != "explore" or self.roam_step % 3
                or now - self.last_window_perch < 75 or not self.awareness_fresh(now)):
            return None
        window = self.awareness["focused_window"]
        left, top, right, bottom = bounds
        candidates = [QtCore.QPointF(window["x"] - self.width() + 68 * self.scale,
                                     window["y"] + min(window["height"] * .3, 160)),
                      QtCore.QPointF(window["x"] + window["width"] - 68 * self.scale,
                                     window["y"] + min(window["height"] * .3, 160)),
                      QtCore.QPointF(window["x"] + window["width"] * .75 - self.width() / 2,
                                     window["y"] - self.height() + 55 * self.scale)]
        candidates = [QtCore.QPointF(max(left, min(right, point.x())), max(top, min(bottom, point.y()))) for point in candidates]
        # Local geometry chooses a nearby outside perch. It never moves toward
        # the caret or crosses into the centre to chase a typing target.
        target = min(candidates, key=lambda point: math.hypot(point.x() - position.x(), point.y() - position.y()))
        if math.hypot(target.x() - position.x(), target.y() - position.y()) < 70:
            return None
        self.last_window_perch = now
        return target

    def _logical(self, point):
        return QtCore.QPointF(point.x() / self.scale, point.y() / self.scale)

    def enterEvent(self, event):
        self.hovering = True
        if not self.reduced_motion:
            self.animation.setInterval(33)
        self.interaction_until = time.monotonic() + 5
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovering = False
        self.interaction_until = time.monotonic() + 5
        self.status_until = time.monotonic() + .7
        super().leaveEvent(event)

    def moveEvent(self, event):
        if not self.moving_window:
            self.roam_position = QtCore.QPointF(self.pos())
            self.roam_goal = None
        super().moveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton:
            return super().mousePressEvent(event)
        self.press_global = event.globalPosition().toPoint()
        self.press_local = self._logical(event.position().toPoint())
        self.press_window = self.pos()
        self.press_creature = self.creature_rect.contains(self.press_local)
        self.dragged = False
        self.drag_mode = "graph" if event.modifiers() & QtCore.Qt.AltModifier else "window"
        self.last_drag_position = event.globalPosition().toPoint()
        self.last_drag_at = time.monotonic()
        self.drag_velocity = QtCore.QPointF()
        self.interaction_until = time.monotonic() + 8
        self.setCursor(QtCore.Qt.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        if self.press_global is None:
            self.setCursor(QtCore.Qt.PointingHandCursor if self.creature_rect.contains(self._logical(event.position().toPoint())) else QtCore.Qt.OpenHandCursor)
            return
        delta = event.globalPosition().toPoint() - self.press_global
        if delta.manhattanLength() >= QtWidgets.QApplication.startDragDistance():
            self.dragged = True
        if self.dragged:
            if self.drag_mode == "window":
                self.move(self.press_window + delta)
                if self.last_drag_position is not None:
                    movement = event.globalPosition().toPoint() - self.last_drag_position
                    now = time.monotonic()
                    if not self.reduced_motion:
                        self.body_velocity += QtCore.QPointF(-movement.x() * .8, -movement.y() * .8)
                        elapsed = max(.008, min(.2, now - self.last_drag_at))
                        velocity = QtCore.QPointF(movement.x() / elapsed / self.scale, movement.y() / elapsed / self.scale)
                        speed = math.hypot(velocity.x(), velocity.y())
                        if speed > 1800:
                            velocity *= 1800 / speed
                        self.drag_velocity = velocity
                    self.last_drag_at = now
                    if movement.x() and self.facing_mode == "automatic":
                        direction = 1. if movement.x() > 0 else -1.
                        changed = direction != self.facing_target
                        self.facing = self.facing_target = direction
                        self.last_facing_change = now
                        if changed:
                            self.render_frame(now)
                            self.update()
                    self.animation.setInterval(33)
                self.last_drag_position = event.globalPosition().toPoint()
            elif self.connected:
                self.drag_target = self._logical(event.position().toPoint())
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton or self.press_global is None:
            return super().mouseReleaseEvent(event)
        if self.connected:
            if self.dragged and self.drag_mode == "graph":
                self.client.send_event("drag", **self.graph_position(self._logical(event.position().toPoint())))
            elif not self.dragged and self.press_creature:
                self.touch_started = time.monotonic()
                self.touch_direction = -1 if self.press_local.x() < self.creature_rect.center().x() else 1
                self.body_velocity += QtCore.QPointF(self.touch_direction * 18, -26)
                self.client.send_event("poke")
        self.press_global = None
        self.drag_target = None
        self.interaction_until = time.monotonic() + 8
        self.next_departure = self.interaction_until
        screen = QtWidgets.QApplication.screenAt(self.frameGeometry().center())
        if screen:
            self.home_screen = screen
        self.setCursor(QtCore.Qt.OpenHandCursor)
        self.save_view_preferences()
        self.update()
        event.accept()

    def toggle_roaming(self, checked=False):
        self.roaming_paused = not self.roaming_paused
        self.status_until = time.monotonic() + 4
        self.next_departure = time.monotonic() + 2
        self.roam_goal = None
        self.save_view_preferences()

    def toggle_reduced_motion(self, checked=False):
        self.reduced_motion = not self.reduced_motion
        self.roam_velocity = QtCore.QPointF()
        self.roam_goal = None
        self.advance_physics(0)
        self.advance_presentation(time.monotonic(), 0)
        self.status_until = time.monotonic() + 4
        self.save_view_preferences()
        self.render_frame(time.monotonic())
        self.update()

    def save_view_preferences(self):
        if getattr(self, "restoring_view", False) or not self.client.data_dir.is_dir():
            return
        self.preferences.setValue("scale", self.scale)
        self.preferences.setValue("pause_roaming", self.roaming_paused)
        self.preferences.setValue("reduced_motion", self.reduced_motion)
        self.preferences.setValue("desktop_awareness", self.awareness_enabled)
        self.preferences.setValue("graph_visibility", self.graph_visibility)
        self.preferences.setValue("facing", self.facing_mode)
        self.preferences.setValue("skin_mode", self.skin.mode)
        self.preferences.setValue("x", self.x())
        self.preferences.setValue("y", self.y())
        self.preferences.setValue("monitor", self.home_screen.name() if self.home_screen else "")
        self.preferences.sync()
        try:
            os.chmod(self.preferences.fileName(), 0o600)
        except OSError:
            pass

    def observe_presence(self):
        """Observe this body's own visibility and local clock, never other apps.

        A visible habitat is evidence of a running habitat, not evidence that
        its human is at the keyboard. Nothing is queued when the core is down.
        """
        handle = self.windowHandle()
        now = time.monotonic()
        if not self.fresh(now) or not self.isVisible() or not handle or not handle.isExposed():
            return
        timestamp = time.time()
        if now - self.presence_at >= 58:
            self.client.send_event("presence", source="live", intensity=.06,
                                   context="native habitat visible", timestamp=timestamp)
            self.presence_at = now
        period = ("night", "morning", "afternoon", "evening")[((time.localtime(timestamp).tm_hour + 2) % 24) // 6]
        if period != self.time_period:
            self.client.send_event("time", source="live", intensity=.10,
                                   context=period, timestamp=timestamp)
            self.time_period = period

    def change_scale(self, scale):
        center = self.frameGeometry().center()
        self.scale = scale
        self.setFixedSize(round(CANVAS_WIDTH * scale), round(CANVAS_HEIGHT * scale))
        left, top, right, bottom = self.motion_bounds()
        self.move(max(left, min(right, center.x() - self.width() // 2)),
                  max(top, min(bottom, center.y() - self.height() // 2)))
        self.interaction_until = time.monotonic() + 5
        self.render_frame(time.monotonic())
        self.save_view_preferences()

    def set_facing_mode(self, mode):
        if mode not in {"left", "right", "automatic"}:
            return
        self.facing_mode = mode
        if mode != "automatic":
            self.facing_target = -1. if mode == "left" else 1.
        self.last_facing_change = -math.inf
        self.facing = self.facing_target
        self.render_frame(time.monotonic())
        self.update()
        self.save_view_preferences()

    def set_graph_visibility(self, mode):
        if mode not in {"subtle", "clear", "bright"}:
            return
        self.graph_visibility = mode
        self.graph_gain = {"subtle": 1., "clear": 1.8, "bright": 2.8}[mode]
        self.save_view_preferences()
        self.render_frame(time.monotonic())
        self.update()

    def set_skin_mode(self, mode):
        if mode not in SKIN_MODES:
            return
        self.skin.mode = mode
        self.skin.result_key = None
        self.save_view_preferences()
        self.render_frame(time.monotonic())
        self.update()

    def make_menu(self):
        menu = QtWidgets.QMenu(self)
        menu.addAction("&Open habitat", lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(self.client.url)))
        pause = menu.addAction("&Pause roaming")
        pause.setCheckable(True)
        pause.setChecked(self.roaming_paused)
        pause.triggered.connect(self.toggle_roaming)
        reduce = menu.addAction("&Reduced motion")
        reduce.setCheckable(True)
        reduce.setChecked(self.reduced_motion)
        reduce.triggered.connect(self.toggle_reduced_motion)
        facing = menu.addMenu("&Look")
        for label, mode in (("Automatic", "automatic"), ("Left", "left"), ("Right", "right")):
            action = facing.addAction(label, lambda checked=False, value=mode: self.set_facing_mode(value))
            action.setCheckable(True)
            action.setChecked(self.facing_mode == mode)
            menu.aboutToShow.connect(lambda item=action, value=mode: item.setChecked(self.facing_mode == value))
        observe = menu.addAction("Notice windows and &typing")
        observe.setCheckable(True)
        observe.setChecked(self.awareness_enabled)
        observe.setEnabled(self.awareness_supported())
        observe.triggered.connect(self.toggle_awareness)
        menu.aboutToShow.connect(lambda: observe.setChecked(self.awareness_enabled))
        if sys.platform == "darwin":
            from desktop.macos import request_input_monitoring
            menu.addAction("Allow typing awareness...", lambda checked=False: request_input_monitoring())
        graph = menu.addMenu("Memory &graph")
        for label, mode in (("Subtle", "subtle"), ("Clear", "clear"), ("Bright", "bright")):
            action = graph.addAction(label, lambda checked=False, value=mode: self.set_graph_visibility(value))
            action.setCheckable(True)
            action.setChecked(self.graph_visibility == mode)
            menu.aboutToShow.connect(lambda item=action, value=mode: item.setChecked(self.graph_visibility == value))
        skin = menu.addMenu("&Living skin")
        for mode in SKIN_MODES:
            action = skin.addAction(mode.capitalize(), lambda checked=False, value=mode: self.set_skin_mode(value))
            action.setCheckable(True)
            action.setChecked(self.skin.mode == mode)
            menu.aboutToShow.connect(lambda item=action, value=mode: item.setChecked(self.skin.mode == value))
        sizes = menu.addMenu("&Size")
        for label, scale in (("Small", .8), ("Companion", 1.), ("Large", 1.3), ("Extra large", 1.6)):
            action = sizes.addAction(label, lambda checked=False, value=scale: self.change_scale(value))
            action.setCheckable(True)
            action.setChecked(abs(self.scale - scale) < .01)
            menu.aboutToShow.connect(lambda item=action, value=scale: item.setChecked(abs(self.scale - value) < .01))
        places = menu.addMenu("&Move to")
        for label, place in (("Lower right", "lower-right"), ("Lower left", "lower-left"), ("Center", "center")):
            places.addAction(label, lambda checked=False, value=place: self.reposition(value))
        screens = QtWidgets.QApplication.screens()
        if len(screens) > 1:
            monitors = places.addMenu("Monitor")
            for screen in screens:
                monitors.addAction(screen.name(), lambda checked=False, target=screen: self.select_screen(target))
        menu.addSeparator()
        detail = menu.addAction(self.status)
        detail.setEnabled(False)
        menu.aboutToShow.connect(lambda: detail.setText(self.status))
        menu.addAction("&Quit desktop companion", self.quit_desktop)
        menu.aboutToShow.connect(lambda: self.menu_visibility(True))
        menu.aboutToShow.connect(lambda: pause.setChecked(self.roaming_paused))
        menu.aboutToShow.connect(lambda: reduce.setChecked(self.reduced_motion))
        menu.aboutToHide.connect(lambda: self.menu_visibility(False))
        return menu

    def quit_desktop(self):
        # An explicit Quit must remain possible under Restart=always. Stopping
        # the unit is intentional; a process exit or crash otherwise recovers.
        if os.environ.get("TERMINUS_SERVICE") == "desktop":
            set_paused("desktop", self.client.data_dir, True)
            if sys.platform == "darwin":
                QtCore.QProcess.startDetached("launchctl", ["bootout", f"gui/{os.getuid()}/org.terminus.desktop"])
            else:
                QtCore.QProcess.startDetached("systemctl", ["--user", "--no-block", "stop", "terminus-desktop.service"])
        QtWidgets.QApplication.quit()

    def menu_visibility(self, visible):
        self.menu_open = visible
        self.interaction_until = time.monotonic() + 6

    def contextMenuEvent(self, event):
        menu = self.make_menu()
        menu.exec(event.globalPos())
        menu.deleteLater()

    def tray_activated(self, reason):
        if reason in {QtWidgets.QSystemTrayIcon.Trigger, QtWidgets.QSystemTrayIcon.DoubleClick}:
            self.show()
            self.raise_()
            self.status_until = time.monotonic() + 4

    def select_screen(self, screen):
        self.home_screen = screen
        self.reposition("lower-right")
        self.save_view_preferences()

    def reposition(self, place):
        screen = self.home_screen or self.screen() or QtWidgets.QApplication.primaryScreen()
        area = screen.availableGeometry()
        if place == "center":
            self.move(area.center() - self.rect().center())
        else:
            x = area.right() - self.width() - 24 if place == "lower-right" else area.left() + 24
            self.move(x, area.bottom() - self.height() - 24)
        self.roam_position = QtCore.QPointF(self.pos())
        self.roam_goal = None
        self.interaction_until = time.monotonic() + 6
        self.save_view_preferences()

    def closeEvent(self, event):
        self.save_view_preferences()
        if self.native_input_shape is not None:self.native_input_shape.close()
        self.animation.stop()
        self.asset_timer.stop()
        self.presence_timer.stop()
        self.awareness_timer.stop()
        if self.awareness_provider is not None:
            self.awareness_provider.close(timeout=1.)
            self.awareness_provider = None
        if self.caret_provider is not None:
            self.caret_provider.close()
            self.caret_provider = None
        if self.tray:
            self.tray.hide()
        if self.movie:
            self.movie.stop()
        self.clip_player = self.clip_library = self.clip_sample = None
        self.skin.clear()
        super().closeEvent(event)

    def diagnostics(self):
        handle = self.windowHandle()
        screen = self.home_screen or self.screen()
        geometry = self.geometry()
        area = screen.availableGeometry() if screen else QtCore.QRect()
        state = self.state or {}
        return {"pid": os.getpid(), "updated_at": time.time(), "visible": self.isVisible(),
                "isExposed": bool(handle and handle.isExposed()), "nativewinid": int(self.winId()),
                "platform": QtWidgets.QApplication.platformName(),
                "native_focus": self.mac_presence.diagnostics() if hasattr(self,"mac_presence") else None,
                "translucent": self.testAttribute(QtCore.Qt.WA_TranslucentBackground),
                "topmost": bool(self.windowFlags() & QtCore.Qt.WindowStaysOnTopHint),
                "frameless": bool(self.windowFlags() & QtCore.Qt.FramelessWindowHint),
                "accepts_focus": not bool(self.windowFlags() & QtCore.Qt.WindowDoesNotAcceptFocus),
                "input_shape_only":bool(self.native_input_shape is not None and self.native_input_shape.available),
                "geometry": {"x": geometry.x(), "y": geometry.y(), "width": geometry.width(), "height": geometry.height()},
                "screen": {"name": screen.name() if screen else None, "x": area.x(), "y": area.y(), "width": area.width(), "height": area.height()},
                "exposed": bool(handle and handle.isExposed()), "connected": self.connected,
                "organism_id": state.get("organism_id"), "revision": state.get("revision"),
                "behavior": state.get("behavior"), "roaming_paused": self.roaming_paused,
                "reduced_motion": self.reduced_motion, "snapshot_fresh": self.fresh(),
                "facing": "left" if self.facing < 0 else "right", "facing_mode": self.facing_mode,
                "flight_strength": round(self.flight_strength, 3), "typing_pose": self.typing_blend > .05,
                "body_animation": {"backend": "gpu-flow-atlas" if self.gpu_scene is not None and self.gpu_scene.available else "gif" if self.clip_sample is not None else "image-fallback",
                                   "clip": self.clip_sample.clip if self.clip_sample is not None else None,
                                   "frame": self.clip_sample.index if self.clip_sample is not None else None,
                                   "transition": bool(self.clip_sample is not None and self.clip_sample.transition),
                                   "fallback": bool(getattr(self.clip_sample, "fallback", False)),
                                   "load_error": self.clip_error,
                                   "clip_errors": len(getattr(self.clip_library, "errors", ()))},
                "graph_visibility": self.graph_visibility, "graph_gain": self.graph_gain,
                "graphics": self.gpu_scene.diagnostics() if self.gpu_scene is not None else {"backend":"raster-sprite-fallback","error":getattr(self,"gpu_error",None)},
                "skin": {**self.skin.diagnostics(),"backend":"gpu-fragment-shader","eye_mask_valid":True,"evaluation_ms":0.} if self.gpu_scene is not None and self.gpu_scene.available else self.skin.diagnostics(),
                "desktop_awareness": {"enabled": self.awareness_enabled, "available": bool(self.awareness.get("available")),
                                      "source": self.awareness.get("source", "unavailable"), "caret_source": "retired", "worker": self.awareness.get("source","unavailable"),
                                      "typing_available":isinstance(self.awareness.get("typing"),dict),
                                      "pointer_available":bool(self.awareness.get("pointer",{}).get("available")),
                                      "windows_available":bool(self.awareness.get("windows",{}).get("available")),
                                      "microphone_available":bool(self.awareness.get("microphone",{}).get("available")),
                                      "passive_events_dropped":getattr(self,"passive_events_dropped",0)},
                "frame_interval_ms": self.animation.interval(), "render_ms": round(self.render_ms, 2),
                "input_mask_ms": round(self.mask_ms, 2),
                "gesture": (self.gesture(time.monotonic()) or {}).get("kind"),
                "motion_intent": (state.get("motion") or {}).get("intent"),
                "graph_nodes": len(state.get("nodes", [])), "graph_edges": len(state.get("edges", [])),
                "tendrils": len(self.tendril_geometry(self.scene_geometry(time.monotonic())[1], time.monotonic())),
                "input_shape_rectangles": self.input_region.rectCount(),
                "status_visible": self.status_visible(time.monotonic())}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renderer",choices=("auto","gpu","raster"),default="auto")
    parser.add_argument("--url", default=None, help="Core origin; default http://127.0.0.1:8769")
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / ".local", help="Core data directory containing token")
    parser.add_argument("--scale", type=float, default=None, help="Overlay size multiplier, 0.65 to 2; default restores this body's setting")
    parser.add_argument("--no-roam", action="store_true", help="Keep the desktop companion where placed")
    parser.add_argument("--reduced-motion", action="store_true", help="Keep the body, graph and perches still")
    parser.add_argument("--no-awareness", action="store_true", help="Do not observe focused-window bounds or aggregate typing")
    parser.add_argument("--status-file", type=Path, help="Write native-view diagnostics here once per second")
    parser.add_argument("--capture-file", type=Path, help="Save one image of this widget after it is exposed and connected")
    parser.add_argument("--smoke-test", action="store_true", help="Offscreen network + render check; exits without sending events")
    args = parser.parse_args(argv)
    try:
        url = validate_url(args.url or DEFAULT_URL, explicit=args.url is not None)
    except ValueError as exc:
        parser.error(str(exc))
    if args.scale is not None and (not math.isfinite(args.scale) or not 0.65 <= args.scale <= 2):
        parser.error("--scale must be between 0.65 and 2")
    if args.smoke_test:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    if sys.platform=="darwin" and not args.smoke_test:
        from desktop.macos import prepare_macos_environment,configure_macos_application
        prepare_macos_environment()
    app = QtWidgets.QApplication([sys.argv[0]])
    if sys.platform=="darwin" and not args.smoke_test:
        configure_macos_application()
    app.setApplicationName("Terminus desktop")
    app.setQuitOnLastWindowClosed(True)
    lock = None
    if not args.smoke_test:
        args.data_dir.mkdir(parents=True, exist_ok=True)
        lock = QtCore.QLockFile(str(args.data_dir.resolve() / "desktop.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            print("Terminus desktop is already present for this core data directory.", file=sys.stderr)
            return 1
    client = CoreClient(url, args.data_dir.resolve())
    overlay = Overlay(client, REPO_ROOT / "web" / "assets", args.scale)
    mac_presence = None
    if sys.platform == "darwin" and not args.smoke_test:
        from desktop.macos import MacPresence
        mac_presence = MacPresence(overlay)
        overlay.mac_presence = mac_presence
    render_guard=None
    if args.renderer!="raster" and not args.smoke_test:
        from desktop.render_guard import RenderGuard
        render_guard=RenderGuard(args.data_dir)
        if render_guard.begin():
            if not overlay.enable_gpu():render_guard.unavailable()
        else:
            overlay.gpu_error=render_guard.reason
    if args.no_roam:
        overlay.roaming_paused = True
    if args.reduced_motion:
        overlay.reduced_motion = True
    if args.no_awareness:
        overlay.awareness_enabled = False
    overlay.show()
    if app.platformName()=="xcb" and overlay.gpu_scene is not None:
        from desktop.x11_input import OwnWindowInputShape
        overlay.clearMask();QtGui.QGuiApplication.sync()
        overlay.native_input_shape=OwnWindowInputShape(overlay)
        if not overlay.native_input_shape.available or not overlay.native_input_shape.set_region(overlay.input_region):
            overlay.gpu_scene._graphics_error(None,"Native input shape unavailable; using raster")
            if render_guard is not None:render_guard.unavailable()
            overlay.render_frame(time.monotonic())
    if not args.smoke_test:
        overlay.start_awareness()
    # A short Qt timer gives Python a regular opportunity to receive SIGTERM.
    signal.signal(signal.SIGTERM, lambda signum, frame: app.quit())
    signal.signal(signal.SIGINT, lambda signum, frame: app.quit())
    permission_request = {"pending": False}
    if sys.platform == "darwin" and not args.smoke_test:
        signal.signal(signal.SIGUSR1, lambda signum, frame: permission_request.__setitem__("pending", True))

    def process_permission_request():
        if permission_request["pending"]:
            permission_request["pending"] = False
            from desktop.macos import request_input_monitoring
            request_input_monitoring()

    signal_pump = QtCore.QTimer(app)
    signal_pump.timeout.connect(process_permission_request)
    signal_pump.start(250)
    captured = {"since": None, "done": False}

    def report_view():
        report = overlay.diagnostics()
        if render_guard is not None:
            if render_guard.attempting and (overlay.gpu_scene is not None and not overlay.gpu_scene.available or overlay.gpu_scene is None and getattr(overlay,"gpu_error",None)):
                render_guard.unavailable()
            render_guard.healthy(report)
        alive = report["visible"] and report["platform"] not in {"offscreen", "minimal"}
        # This timer runs on Qt's own event loop. Core disconnection is handled
        # by reconnection, without restarting an otherwise healthy desktop.
        notify("Native desktop body responsive", healthy=alive)
        if args.status_file:
            args.status_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.status_file.with_suffix(args.status_file.suffix + ".tmp")
            temporary.write_text(json.dumps(report), encoding="utf-8")
            temporary.replace(args.status_file)
        if args.capture_file and not captured["done"] and report["exposed"] and report["connected"]:
            captured["since"] = captured["since"] or time.monotonic()
            if time.monotonic() - captured["since"] >= 1 and time.monotonic() - overlay.started >= 5:
                args.capture_file.parent.mkdir(parents=True, exist_ok=True)
                # This captures only our own widget, never another application.
                captured["done"] = True
                captured["saved"] = overlay.grab().save(str(args.capture_file), "PNG")

    status_timer = QtCore.QTimer(app)
    status_timer.timeout.connect(report_view)
    status_timer.start(1000)
    QtCore.QTimer.singleShot(0, report_view)
    if args.smoke_test:
        completed = {"done": False}

        def fail(reason):
            if not completed["done"]:
                completed["done"] = True
                print("Overlay smoke failed: " + reason, file=sys.stderr)
                app.exit(1)

        def render(state):
            if completed["done"]:
                return
            if overlay.artwork().isNull():
                fail("No readable creature artwork in web/assets")
                return
            frame = QtGui.QImage(overlay.size(), QtGui.QImage.Format_ARGB32)
            frame.fill(QtCore.Qt.transparent)
            overlay.render(frame)
            if not any(QtGui.qAlpha(frame.pixel(x, y)) for x in range(0, frame.width(), 11) for y in range(0, frame.height(), 11)):
                fail("The widget did not render a frame")
                return
            completed["done"] = True
            print(f"Overlay smoke passed: revision={state['revision']}, nodes={len(state['nodes'])}, frame={frame.width()}x{frame.height()}")
            app.exit(0)

        client.snapshot.connect(lambda state: QtCore.QTimer.singleShot(80, lambda: render(state)))
        client.disconnected.connect(fail)
        QtCore.QTimer.singleShot(6500, lambda: fail("No authoritative snapshot received"))
    client.start()
    result = app.exec()
    overlay.close()
    if lock:
        lock.unlock()
    return result


if __name__ == "__main__":
    sys.exit(main())
