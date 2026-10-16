"""Native-client boundary checks; all network activity stays on loopback."""

import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("terminus_overlay", ROOT / "desktop" / "overlay.py")
OVERLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OVERLAY)


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        cls.app = OVERLAY.QtWidgets.QApplication.instance() or OVERLAY.QtWidgets.QApplication([])

    def widget(self):
        client = OVERLAY.CoreClient("http://127.0.0.1:8769", Path("/unused-test-data"))
        widget = OVERLAY.Overlay(client, ROOT / "web" / "assets")
        self.addCleanup(widget.close)
        return widget

    @staticmethod
    def snapshot():
        return {"revision": 8, "behavior": "inspect", "position": {"x": .5, "y": .62},
                "attention": "work", "nodes": [
                    {"id": "touch", "x": .06, "y": .65, "activation": .2},
                    {"id": "time", "x": .12, "y": .22, "activation": .02},
                    {"id": "self", "x": .45, "y": .7, "activation": .1},
                    {"id": "work", "x": .94, "y": .3, "activation": .8}],
                "edges": [{"source": "self", "target": "work", "weight": .8},
                          {"source": "self", "target": "touch", "weight": .3}]}

    def test_destinations_require_explicit_remote_url_and_refuse_url_secrets(self):
        self.assertEqual(OVERLAY.validate_url("http://127.0.0.1:8769/", explicit=False), "http://127.0.0.1:8769")
        self.assertEqual(OVERLAY.validate_url("https://example.invalid", explicit=True), "https://example.invalid")
        for url in ["http://example.invalid", "file:///tmp/token", "http://name:secret@localhost:8769", "http://localhost:8769/?token=secret", "http://localhost:8769/#secret"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                OVERLAY.validate_url(url, explicit=False)

    def test_invalid_network_coordinates_are_rejected(self):
        state = {"revision": 1, "behavior": "idle", "position": {"x": float("nan"), "y": 0.5}, "nodes": [], "edges": []}
        with self.assertRaises(ValueError):
            OVERLAY.validate_snapshot(state)

    def test_click_window_drag_and_graph_drag_are_distinct(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        app = OVERLAY.QtWidgets.QApplication.instance() or OVERLAY.QtWidgets.QApplication([])
        client = OVERLAY.CoreClient("http://127.0.0.1:8769", Path("/unused-test-data"))
        events = []
        client.send_event = lambda kind, **fields: events.append((kind, fields))
        widget = OVERLAY.Overlay(client, ROOT / "web" / "assets")
        widget.receive_state({"revision": 1, "behavior": "idle", "position": {"x": 0.5, "y": 0.5}, "nodes": [], "edges": []})
        widget.show()
        app.processEvents()
        Qt = OVERLAY.QtCore.Qt
        Event = OVERLAY.QtCore.QEvent

        def send(kind, local, modifiers=Qt.NoModifier):
            local = OVERLAY.QtCore.QPoint(*local)
            global_position = widget.mapToGlobal(local)
            event = OVERLAY.QtGui.QMouseEvent(kind, OVERLAY.QtCore.QPointF(local),
                                             OVERLAY.QtCore.QPointF(global_position),
                                             Qt.LeftButton, Qt.LeftButton, modifiers)
            app.sendEvent(widget, event)

        try:
            point = widget.creature_rect.center().toPoint()
            origin = (point.x(), point.y())
            send(Event.MouseButtonPress, origin)
            send(Event.MouseButtonRelease, origin)
            self.assertEqual(events, [("poke", {})])
            events.clear()
            before = widget.pos()
            send(Event.MouseButtonPress, origin)
            send(Event.MouseMove, (origin[0] + 30, origin[1] + 20))
            send(Event.MouseButtonRelease, origin)
            self.assertNotEqual(widget.pos(), before)
            self.assertEqual(events, [])
            target = widget.graph_point(.9, .85).toPoint()
            target = (target.x(), target.y())
            send(Event.MouseButtonPress, origin, Qt.AltModifier)
            send(Event.MouseMove, target, Qt.AltModifier)
            send(Event.MouseButtonRelease, target, Qt.AltModifier)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0][0], "drag")
            self.assertGreater(events[0][1]["x"], 0.8)
            self.assertGreater(events[0][1]["y"], 0.7)
            events.clear()
            widget.disconnect("test disconnection")
            send(Event.MouseButtonPress, origin)
            send(Event.MouseButtonRelease, origin)
            self.assertEqual(events, [])
        finally:
            widget.close()
            widget.deleteLater()
            app.processEvents()

    def test_transparent_desktop_corners_and_visible_graph_share_input_shape(self):
        widget = self.widget()
        widget.receive_state(self.snapshot())
        now = time.monotonic() + 10
        widget.status_until = 0
        widget.render_frame(now)
        Qt = OVERLAY.QtCore.Qt
        self.assertTrue(widget.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        self.assertTrue(widget.windowFlags() & Qt.WindowStaysOnTopHint)
        self.assertTrue(widget.testAttribute(Qt.WA_TranslucentBackground))
        for point in [(0, 0), (439, 0), (0, 339), (439, 339), (220, 322)]:
            with self.subTest(point=point):
                self.assertFalse(widget.input_region.contains(OVERLAY.QtCore.QPoint(*point)))
                self.assertEqual(OVERLAY.QtGui.qAlpha(widget.frame.pixel(*point)), 0)
        body = widget.creature_rect.center().toPoint()
        self.assertTrue(widget.input_region.contains(body))
        target = widget.graph_point(.94, .3).toPoint()
        self.assertTrue(widget.input_region.contains(target))
        self.assertGreater(OVERLAY.QtGui.qAlpha(widget.frame.pixel(target)), 30)
        # A contacted memory node has a shaded, graspable surface. An untouched
        # node keeps its faint point and glow rather than becoming a platform.
        self.assertGreater(OVERLAY.QtGui.qAlpha(widget.frame.pixel(target + OVERLAY.QtCore.QPoint(5, 0))), 120)
        untouched = widget.graph_point(.12, .22).toPoint()
        self.assertLess(OVERLAY.QtGui.qAlpha(widget.frame.pixel(untouched + OVERLAY.QtCore.QPoint(5, 0))), 80)
        widget.hovering = True
        widget.render_frame(now + 1)
        self.assertGreater(OVERLAY.QtGui.qAlpha(widget.frame.pixel(220, 322)), 150)
        widget.hovering = False
        widget.render_frame(now + 2)
        self.assertEqual(OVERLAY.QtGui.qAlpha(widget.frame.pixel(220, 322)), 0)

    def test_visual_roaming_is_bounded_and_pauses_for_user_or_resting_core(self):
        widget = self.widget()
        state = self.snapshot()
        widget.receive_state(state)
        widget.move(500, 500)
        widget.roam_position = OVERLAY.QtCore.QPointF(widget.pos())
        widget.interaction_until = widget.next_departure = 0
        widget.hovering = False
        area = OVERLAY.QtCore.QRect(0, 36, 1920, 1044)
        before = widget.pos()
        for step in range(1800):
            widget.advance_motion(100 + step / 10, .1, area)
            self.assertTrue(area.contains(widget.geometry()))
        self.assertNotEqual(widget.pos(), before)
        self.assertEqual(state, self.snapshot())
        for condition in ("hovering", "menu_open", "roaming_paused"):
            setattr(widget, condition, True)
            before = widget.pos()
            widget.advance_motion(1000, .2, area)
            self.assertEqual(widget.pos(), before)
            setattr(widget, condition, False)
        for behavior in ("sleep", "dream", "attend", "startled", "settle"):
            state["behavior"] = behavior
            before = widget.pos()
            widget.advance_motion(1000, .2, area)
            self.assertEqual(widget.pos(), before)
        state["behavior"] = "inspect"
        widget.connected = False
        before = widget.pos()
        widget.advance_motion(1000, .2, area)
        self.assertEqual(widget.pos(), before)

    def test_reaching_graph_and_signs_follow_authoritative_attention_and_utterance(self):
        widget = self.widget()
        state = self.snapshot()
        widget.receive_state(state)
        now = time.monotonic()
        _, points = widget.scene_geometry(now)
        tendrils = widget.tendril_geometry(points, now)
        self.assertGreater(points["work"].x() - points["touch"].x(), 280)
        self.assertIn("work", [key for key, _, _ in tendrils])
        for key, path, activity in tendrils:
            self.assertEqual(path.pointAtPercent(1), points[key])
            self.assertGreater(path.length(), 10)
        self.assertEqual(widget.glyph_sequence, [])
        state["utterance"] = {"id": "u-new", "created_at": time.time(), "glyphs": [4, 11]}
        widget.receive_state(state)
        self.assertEqual(widget.glyph_sequence, [4, 11])
        started = widget.glyph_started
        widget.receive_state(state)
        self.assertEqual(widget.glyph_started, started)
        state["utterance"] = {"id": "u-historic", "created_at": time.time() - 500, "glyphs": [4, 11]}
        widget.receive_state(state)
        self.assertEqual(widget.glyph_sequence, [])

    def _smoke(self, *, redirect=False):
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                calls.append(self.path)
                if self.headers.get("Authorization") != "Bearer test-only-local-token":
                    self.send_response(401)
                    self.end_headers()
                    return
                if redirect:
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/should-not-follow")
                    self.end_headers()
                    return
                state = {"revision": 3, "behavior": "idle", "position": {"x": 0.5, "y": 0.5},
                         "nodes": [{"id": "one", "x": 0.5, "y": 0.5, "activation": 0.5}],
                         "edges": [], "latent": {}, "attention": "one"}
                encoded = json.dumps(state).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="terminus-overlay-test-") as directory:
                (Path(directory) / "token").write_text("test-only-local-token\n")
                result = subprocess.run([sys.executable, str(ROOT / "desktop" / "overlay.py"),
                                         "--url", f"http://127.0.0.1:{server.server_port}",
                                         "--data-dir", directory, "--smoke-test"],
                                        capture_output=True, text=True, timeout=10)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertNotIn("test-only-local-token", result.stdout + result.stderr)
        return result, calls

    def test_offscreen_frame_uses_authenticated_core_and_exits(self):
        result, calls = self._smoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Overlay smoke passed", result.stdout)
        self.assertEqual(calls, ["/api/state"])

    def test_redirect_is_not_followed_with_bearer_token(self):
        result, calls = self._smoke(redirect=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("redirect refused", result.stderr)
        self.assertEqual(calls, ["/api/state"])


if __name__ == "__main__":
    unittest.main()
