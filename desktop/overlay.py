#!/usr/bin/env python3
"""A small native view of the organism owned by the Terminus core."""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.parse import urlsplit
import uuid

from PyQt5 import QtCore, QtGui, QtNetwork, QtWidgets


REPO_ROOT = Path(__file__).resolve().parents[1]
CANVAS_WIDTH = 320
CANVAS_HEIGHT = 282
DEFAULT_URL = "http://127.0.0.1:8769"


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
    return state


def amount(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(value):
        return max(0.0, min(1.0, value))
    return default


class CoreClient(QtCore.QObject):
    snapshot = QtCore.pyqtSignal(dict)
    disconnected = QtCore.pyqtSignal(str)

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
                   "source": "manual", **fields}
        reply = self.manager.post(request, json.dumps(payload).encode("utf-8"))
        self._guard(reply)
        reply.finished.connect(lambda: self._finish_event(reply))

    def _finish_event(self, reply):
        status = reply.attribute(QtNetwork.QNetworkRequest.HttpStatusCodeAttribute)
        if reply.error() != QtNetwork.QNetworkReply.NoError or status not in {200, 201, 202}:
            self.disconnected.emit("Interaction was not delivered · reconnecting")
        else:
            QtCore.QTimer.singleShot(0, self.poll)
        reply.deleteLater()


class Overlay(QtWidgets.QWidget):
    def __init__(self, client: CoreClient, assets: Path, scale: float = 1.0):
        flags = QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setWindowTitle("Terminus · desktop habitat")
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setFixedSize(round(CANVAS_WIDTH * scale), round(CANVAS_HEIGHT * scale))
        self.scale = scale
        self.client = client
        self.assets = assets
        self.state = None
        self.connected = False
        self.status = "Connecting to core"
        self.last_seen = 0.0
        self.started = time.monotonic()
        self.creature_rect = QtCore.QRectF()
        self.drag_target = None
        self.press_global = None
        self.press_local = None
        self.press_window = None
        self.dragged = False
        self.drag_mode = None
        self.press_creature = False
        self.art_signature = None
        self.static_art = QtGui.QPixmap()
        self.sleep_art = QtGui.QPixmap()
        self.sleep_blend = 0.0
        self.last_paint = time.monotonic()
        self.movie = None
        self.load_art()
        client.snapshot.connect(self.receive_state)
        client.disconnected.connect(self.disconnect)
        self.animation = QtCore.QTimer(self)
        self.animation.setInterval(33)
        self.animation.timeout.connect(self.update)
        self.animation.start()
        self.asset_timer = QtCore.QTimer(self)
        self.asset_timer.setInterval(5000)
        self.asset_timer.timeout.connect(self.load_art)
        self.asset_timer.start()
        self.setToolTip("Click Terminus to poke · drag to move window · Alt-drag to move on graph · right-click for menu")
        self.reposition("lower-right")

    def load_art(self):
        candidates = [self.assets / "terminus-refined.png", self.assets / "terminus.png", self.assets / "idle.gif"]
        art = next((path for path in candidates if path.is_file()), None)
        sleep_path = self.assets / "terminus-sleep.png"
        signature = ((str(art), art.stat().st_mtime_ns) if art else None,
                     sleep_path.stat().st_mtime_ns if sleep_path.is_file() else None)
        if signature == self.art_signature:
            return
        self.art_signature = signature
        if self.movie:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None
        self.static_art = QtGui.QPixmap()
        self.sleep_art = QtGui.QPixmap()
        if sleep_path.is_file():
            self.sleep_art.load(str(sleep_path))
        if art and art.suffix.lower() == ".gif":
            self.movie = QtGui.QMovie(str(art), parent=self)
            self.movie.setCacheMode(QtGui.QMovie.CacheAll)
            self.movie.frameChanged.connect(self.update)
            self.movie.start()
        elif art:
            self.static_art.load(str(art))
        self.update()

    def artwork(self):
        return self.movie.currentPixmap() if self.movie else self.static_art

    def receive_state(self, state):
        self.state = state
        self.connected = True
        self.last_seen = time.monotonic()
        self.status = state["behavior"]
        self.update()

    def disconnect(self, reason):
        self.connected = False
        self.status = reason
        self.update()

    @staticmethod
    def graph_point(x, y):
        return QtCore.QPointF(38 + amount(x) * 244, 162 + amount(y) * 65)

    @staticmethod
    def graph_position(point):
        return {"x": amount((point.x() - 38) / 244), "y": amount((point.y() - 162) / 65)}

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        p.scale(self.scale, self.scale)
        now = time.monotonic()
        elapsed = now - self.started
        target = 1.0 if (self.state or {}).get("behavior") in {"sleep", "dream"} else 0.0
        target = target if not self.sleep_art.isNull() else 0.0
        dt = min(0.15, max(0.0, now - self.last_paint))
        self.last_paint = now
        self.sleep_blend += (target - self.sleep_blend) * (1 - math.exp(-dt / 0.35))

        # The floor is a view of authoritative graph coordinates. All movement
        # and behavior come from snapshots; this timer only animates breathing.
        halo = QtGui.QRadialGradient(160, 195, 146)
        halo.setColorAt(0, QtGui.QColor(46, 167, 170, 38))
        halo.setColorAt(0.7, QtGui.QColor(16, 29, 48, 150))
        halo.setColorAt(1, QtGui.QColor(7, 12, 24, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QtCore.QRectF(5, 135, 310, 122))
        p.setBrush(QtGui.QColor(11, 20, 34, 160))
        p.setPen(QtGui.QPen(QtGui.QColor(114, 222, 222, 55), 0.9))
        p.drawEllipse(QtCore.QRectF(18, 150, 284, 96))
        p.setPen(QtGui.QPen(QtGui.QColor(90, 169, 184, 24), 0.8))
        p.drawEllipse(QtCore.QRectF(35, 159, 250, 78))

        p.save()
        if not self.connected:
            p.setOpacity(0.35)
        nodes = {node["id"]: node for node in (self.state or {}).get("nodes", [])}
        for edge in (self.state or {}).get("edges", []):
            a, b = nodes.get(edge["source"]), nodes.get(edge["target"])
            if a and b:
                weight = amount(edge.get("weight"), 0.3)
                p.setPen(QtGui.QPen(QtGui.QColor(113, 204, 210, int(40 + weight * 70)), 0.7 + weight))
                p.drawLine(self.graph_point(a["x"], a["y"]), self.graph_point(b["x"], b["y"]))
        for node in nodes.values():
            xy = self.graph_point(node["x"], node["y"])
            active = amount(node.get("activation"))
            radius = 2.4 + 3 * active
            if node["id"] == self.state.get("attention"):
                p.setPen(QtGui.QPen(QtGui.QColor(165, 240, 218, 120), 1))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawEllipse(xy, radius + 4, radius + 4)
            p.setPen(QtGui.QPen(QtGui.QColor(174, 240, 237, 180), 0.6))
            p.setBrush(QtGui.QColor(75, 170 + int(active * 60), 193, 190))
            p.drawEllipse(xy, radius, radius)
        position = (self.state or {}).get("position", {"x": 0.5, "y": 0.5})
        feet = self.graph_point(position["x"], position["y"])
        art = self.artwork()
        height = 167 * (1 + 0.008 * math.sin(elapsed * 1.65))
        width = height * art.width() / art.height() if not art.isNull() else height * 0.92
        width = min(width, 184)
        self.creature_rect = QtCore.QRectF(feet.x() - width / 2, feet.y() - height + 9, width, height)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 5, 12, 110))
        p.drawEllipse(QtCore.QRectF(feet.x() - 47, feet.y() - 7, 94, 18))
        if not art.isNull():
            opacity = p.opacity()
            # Keep the common body opaque while the closed-eye layer fades in.
            p.drawPixmap(self.creature_rect, art, QtCore.QRectF(art.rect()))
            if not self.sleep_art.isNull():
                p.setOpacity(opacity * self.sleep_blend)
                p.drawPixmap(self.creature_rect, self.sleep_art, QtCore.QRectF(self.sleep_art.rect()))
            p.setOpacity(opacity)
        else:
            p.setPen(QtGui.QColor(180, 207, 214))
            p.drawText(self.creature_rect, QtCore.Qt.AlignCenter, "Artwork unavailable")
        p.restore()

        if self.drag_target is not None:
            target = self.graph_point(**self.graph_position(self.drag_target))
            p.setPen(QtGui.QPen(QtGui.QColor(183, 246, 223, 200), 1, QtCore.Qt.DashLine))
            p.drawLine(feet, target)
            p.drawEllipse(target, 8, 4)

        # A compact status pill remains visible even when the core is lost.
        pill = QtCore.QRectF(29, 248, 262, 27)
        p.setPen(QtGui.QPen(QtGui.QColor(128, 196, 209, 50), 0.7))
        p.setBrush(QtGui.QColor(10, 17, 30, 228))
        p.drawRoundedRect(pill, 13, 13)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#91e7c3" if self.connected else "#e5ad72"))
        p.drawEllipse(QtCore.QPointF(43, 261), 2.5, 2.5)
        font = QtGui.QFont("Sans Serif", 8)
        font.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 0.6)
        p.setFont(font)
        p.setPen(QtGui.QColor("#d9eeed"))
        text = "TERMINUS  ·  " + (self.status if self.connected else "disconnected")
        p.drawText(QtCore.QRectF(53, 250, 224, 22), QtCore.Qt.AlignVCenter, text)
        p.end()

    def _logical(self, point):
        return QtCore.QPointF(point.x() / self.scale, point.y() / self.scale)

    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton:
            return super().mousePressEvent(event)
        self.press_global = event.globalPos()
        self.press_local = self._logical(event.pos())
        self.press_window = self.pos()
        self.press_creature = self.creature_rect.contains(self.press_local)
        self.dragged = False
        self.drag_mode = "graph" if event.modifiers() & QtCore.Qt.AltModifier else "window"
        self.setCursor(QtCore.Qt.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        if self.press_global is None:
            self.setCursor(QtCore.Qt.PointingHandCursor if self.creature_rect.contains(self._logical(event.pos())) else QtCore.Qt.OpenHandCursor)
            return
        delta = event.globalPos() - self.press_global
        if delta.manhattanLength() >= QtWidgets.QApplication.startDragDistance():
            self.dragged = True
        if self.dragged:
            if self.drag_mode == "window":
                self.move(self.press_window + delta)
            elif self.connected:
                self.drag_target = self._logical(event.pos())
                self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton or self.press_global is None:
            return super().mouseReleaseEvent(event)
        if self.connected:
            if self.dragged and self.drag_mode == "graph":
                self.client.send_event("drag", **self.graph_position(self._logical(event.pos())))
            elif not self.dragged and self.press_creature:
                self.client.send_event("poke")
        self.press_global = None
        self.drag_target = None
        self.setCursor(QtCore.Qt.OpenHandCursor)
        self.update()
        event.accept()

    def contextMenuEvent(self, event):
        menu = QtWidgets.QMenu(self)
        menu.addAction("Open full habitat", lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(self.client.url)))
        places = menu.addMenu("Reposition overlay")
        for label, position in [("Lower right", "lower-right"), ("Lower left", "lower-left"), ("Center", "center")]:
            places.addAction(label, lambda checked=False, place=position: self.reposition(place))
        menu.addSeparator()
        detail = menu.addAction(self.status)
        detail.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Quit overlay", QtWidgets.QApplication.quit)
        menu.exec_(event.globalPos())

    def reposition(self, place):
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        area = screen.availableGeometry()
        if place == "center":
            self.move(area.center() - self.rect().center())
        else:
            x = area.right() - self.width() - 24 if place == "lower-right" else area.left() + 24
            self.move(x, area.bottom() - self.height() - 24)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=None, help="Core origin; default http://127.0.0.1:8769")
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / ".local", help="Core data directory containing token")
    parser.add_argument("--scale", type=float, default=1.0, help="Overlay size multiplier, 0.65 to 2")
    parser.add_argument("--smoke-test", action="store_true", help="Offscreen network + render check; exits without sending events")
    args = parser.parse_args(argv)
    try:
        url = validate_url(args.url or DEFAULT_URL, explicit=args.url is not None)
    except ValueError as exc:
        parser.error(str(exc))
    if not math.isfinite(args.scale) or not 0.65 <= args.scale <= 2:
        parser.error("--scale must be between 0.65 and 2")
    if args.smoke_test:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
    app = QtWidgets.QApplication([sys.argv[0]])
    app.setApplicationName("Terminus desktop")
    client = CoreClient(url, args.data_dir.resolve())
    overlay = Overlay(client, REPO_ROOT / "web" / "assets", args.scale)
    overlay.show()
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
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
