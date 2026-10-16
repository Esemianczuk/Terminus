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
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("terminus_overlay", ROOT / "desktop" / "overlay.py")
OVERLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OVERLAY)


class OverlayTests(unittest.TestCase):
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
            send(Event.MouseButtonPress, origin, Qt.AltModifier)
            send(Event.MouseMove, (260, 210), Qt.AltModifier)
            send(Event.MouseButtonRelease, (260, 210), Qt.AltModifier)
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
