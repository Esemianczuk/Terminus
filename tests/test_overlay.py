"""Native-client boundary checks; all network activity stays on loopback."""

import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("terminus_overlay", ROOT / "desktop" / "overlay.py")
OVERLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OVERLAY)


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        cls.app = OVERLAY.QtWidgets.QApplication.instance() or OVERLAY.QtWidgets.QApplication([])

    def widget(self, directory=None, scale=None):
        client = OVERLAY.CoreClient("http://127.0.0.1:8769", directory or Path("/unused-test-data"))
        widget = OVERLAY.Overlay(client, ROOT / "web" / "assets", scale)
        widget.reference_renderer = True  # Explicit CPU reference fixtures, never the production path.
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

    def test_malformed_animation_contract_cannot_crash_the_render_loop(self):
        for changes in ({"server_time": float("nan")},
                        {"gesture": {"kind": "peer", "started_at": 1000., "duration": float("inf")}},
                        {"motion": {"intent": "explore", "started_at": 1000., "duration": 60., "target_id": []}},
                        {"runtime": {"status": "pretend-healthy"}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                OVERLAY.validate_snapshot({**self.snapshot(), **changes})

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
        base = widget.last_seen
        for step in range(1800):
            now = base + step / 10
            # A continuing stream of real snapshots keeps the view fresh.
            widget.last_seen = now
            widget.advance_motion(now, .1, area)
            self.assertTrue(area.contains(widget.geometry()))
        self.assertNotEqual(widget.pos(), before)
        self.assertEqual(state, self.snapshot())
        for condition in ("hovering", "menu_open", "roaming_paused"):
            setattr(widget, condition, True)
            before = widget.pos()
            widget.advance_motion(now, .2, area)
            self.assertEqual(widget.pos(), before)
            setattr(widget, condition, False)
        for behavior in ("sleep", "dream", "attend", "startled", "settle"):
            state["behavior"] = behavior
            before = widget.pos()
            widget.advance_motion(now, .2, area)
            self.assertEqual(widget.pos(), before)
        state["behavior"] = "inspect"
        widget.connected = False
        before = widget.pos()
        widget.advance_motion(now, .2, area)
        self.assertEqual(widget.pos(), before)

    def test_a_stale_snapshot_cannot_keep_roaming_or_replay_a_gesture(self):
        widget = self.widget()
        state = self.snapshot()
        state.update(server_time=1000., gesture={"id": "g-one", "kind": "stretch", "started_at": 1000.,
                                                "duration": 8., "strength": .7, "target_id": "work"},
                     motion={"intent": "explore", "started_at": 1000., "duration": 60., "strength": .4})
        widget.receive_state(state)
        now = widget.last_seen
        self.assertIsNotNone(widget.gesture(now + 3))
        widget.interaction_until = widget.next_departure = 0
        before = widget.pos()
        widget.advance_motion(now + OVERLAY.SNAPSHOT_FRESHNESS + 1, .2)
        self.assertEqual(widget.pos(), before)
        self.assertIsNone(widget.gesture(now + OVERLAY.SNAPSHOT_FRESHNESS + 1))
        widget.state["gesture"]["started_at"] = 1000 - 20
        self.assertIsNone(widget.gesture(now))
        widget.state["gesture"]["started_at"] = 1000 + 20
        self.assertIsNone(widget.gesture(now))
        widget.state["gesture"]["started_at"] = float("nan")
        self.assertIsNone(widget.gesture(now))

    def test_motion_intent_and_reduced_motion_control_real_window_travel(self):
        widget = self.widget()
        state = self.snapshot()
        state.update(server_time=2000., motion={"intent": "rest", "started_at": 2000., "duration": 90., "strength": .3})
        widget.receive_state(state)
        widget.interaction_until = widget.next_departure = 0
        widget.move(900, 600)
        widget.roam_position = OVERLAY.QtCore.QPointF(widget.pos())
        area = OVERLAY.QtCore.QRect(0, 36, 1920, 1044)
        now = widget.last_seen
        for intent in ("rest", "perch"):
            state["motion"]["intent"] = intent
            before = widget.pos()
            widget.advance_motion(now, .2, area)
            self.assertEqual(widget.pos(), before)
        state["motion"]["intent"] = "explore"
        for step in range(200):
            clock = now + step * .1
            widget.last_seen = clock
            widget.state["server_time"] = 2000. + step * .1
            widget.advance_motion(clock, .1, area)
        travelled = widget.pos() - before
        self.assertGreater(abs(travelled.x()) + abs(travelled.y()), 200)
        widget.reduced_motion = True
        before = widget.pos()
        widget.advance_motion(clock, .2, area)
        self.assertEqual(widget.pos(), before)
        widget.reduced_motion = False
        widget.state["server_time"] = 2200.
        widget.advance_motion(clock, .2, area)
        self.assertEqual(widget.pos(), before)

    def test_runtime_degradation_stops_autonomy_even_when_polling_succeeds(self):
        widget = self.widget()
        state = self.snapshot()
        state.update(server_time=2000., runtime={"status": "degraded"},
                     gesture={"id": "g-peer", "kind": "peer", "started_at": 2000., "duration": 4., "strength": .7},
                     motion={"intent": "explore", "started_at": 2000., "duration": 60., "strength": .4})
        widget.receive_state(state)
        self.assertTrue(widget.connected)
        self.assertFalse(widget.fresh())
        self.assertIsNone(widget.gesture(widget.last_seen))
        widget.interaction_until = widget.next_departure = 0
        before = widget.pos()
        widget.advance_motion(widget.last_seen, .2)
        self.assertEqual(widget.pos(), before)

    def test_reduced_motion_keeps_pixels_still_between_core_changes(self):
        widget = self.widget()
        widget.receive_state(self.snapshot())
        widget.reduced_motion = True
        widget.status_until = 0
        now = widget.last_seen
        widget.render_frame(now)
        first = widget.frame.copy()
        widget.render_frame(now + 3)
        self.assertEqual(widget.frame, first)

    def test_brighter_graph_does_not_expand_the_desktop_input_shape(self):
        widget = self.widget()
        widget.receive_state(self.snapshot())
        widget.status_until = 0
        now = widget.last_seen
        widget.graph_gain = 1.
        widget.last_mask = -float("inf")
        widget.render_frame(now)
        original, region = widget.frame.copy(), widget.input_region
        widget.graph_gain = 2.8
        widget.last_mask = -float("inf")
        widget.render_frame(now)
        self.assertEqual(widget.input_region, region)
        point = widget.graph_point(.12, .22).toPoint() + OVERLAY.QtCore.QPoint(5, 0)
        self.assertGreater(OVERLAY.QtGui.qAlpha(widget.frame.pixel(point)), OVERLAY.QtGui.qAlpha(original.pixel(point)) * 2)
        self.assertEqual(OVERLAY.QtGui.qAlpha(widget.frame.pixel(0, 0)), 0)

    def test_graph_visibility_defaults_bright_and_restores_explicit_choice(self):
        with tempfile.TemporaryDirectory(prefix="terminus-graph-settings-") as directory:
            path = Path(directory)
            widget = self.widget(path)
            self.assertEqual(widget.graph_visibility, "bright")
            self.assertEqual(widget.graph_gain, 2.8)
            widget.set_graph_visibility("subtle")
            self.assertEqual(widget.graph_gain, 1.)
            widget.close()
            restored = self.widget(path)
            self.assertEqual(restored.graph_visibility, "subtle")
            restored.set_graph_visibility("clear")
            self.assertEqual(restored.graph_gain, 1.8)
            restored.set_graph_visibility("invalid")
            self.assertEqual(restored.graph_visibility, "clear")

    def test_drag_velocity_banks_turns_and_settles_without_creating_core_events(self):
        widget = self.widget()
        widget.receive_state(self.snapshot())
        events = []
        widget.client.send_event = lambda kind, **fields: events.append((kind, fields))
        now = widget.last_seen
        widget.press_global = OVERLAY.QtCore.QPoint(600, 500)
        widget.dragged, widget.drag_mode = True, "window"
        for index in range(18):
            clock = now + index / 30
            widget.last_drag_at = clock
            widget.drag_velocity = OVERLAY.QtCore.QPointF(600, -90)
            widget.advance_presentation(clock, 1 / 30)
        self.assertGreater(widget.flight_strength, .8)
        self.assertGreater(widget.flight_bank, 4)
        self.assertEqual(widget.facing_target, 1.)
        for index in range(18, 48):
            clock = now + index / 30
            widget.last_drag_at = clock
            widget.drag_velocity = OVERLAY.QtCore.QPointF(-600, 60)
            widget.advance_presentation(clock, 1 / 30)
            self.assertEqual(widget.facing, -1.)
        self.assertLess(widget.flight_bank, -4)
        widget.press_global = None
        for index in range(48, 160):
            widget.advance_presentation(now + index / 30, 1 / 30)
        self.assertLess(widget.flight_strength, .01)
        self.assertLess(abs(widget.flight_bank), .02)
        self.assertEqual(events, [])

    def test_facing_changes_body_without_mirroring_memory_contacts_or_signs(self):
        widget = self.widget()
        widget.receive_state(self.snapshot())
        widget.status_until = 0
        # Both motion preferences use immediate mirroring, leaving graph
        # contacts and inscriptions in their existing world orientation.
        widget.reduced_motion = True
        now = widget.last_seen
        widget.glyph_sequence, widget.glyph_started = [4, 11, 19], now - 1
        widget.facing = widget.facing_target = 1.
        widget.render_frame(now)
        original = widget.frame.copy()
        original_points = dict(widget.graph_points)
        anchor, _ = widget.scene_geometry(now)
        glyph = OVERLAY.QtCore.QRect(round(anchor.x() + 104), round(widget.creature_rect.top() + 34), 20, 27)
        widget.facing = widget.facing_target = -1.
        widget.render_frame(now)
        self.assertNotEqual(widget.frame, original)
        self.assertEqual(widget.graph_points, original_points)
        self.assertEqual(widget.frame.copy(glyph), original.copy(glyph))
        for key, path, _ in widget.tendril_geometry(widget.graph_points, now):
            self.assertEqual(path.pointAtPercent(1), original_points[key])

    def test_drag_reversal_mirrors_on_the_mouse_event_even_with_reduced_motion(self):
        for reduced in (False, True):
            with self.subTest(reduced_motion=reduced):
                widget = self.widget()
                widget.receive_state(self.snapshot())
                widget.animation.stop()
                widget.reduced_motion = reduced
                widget.press_global = OVERLAY.QtCore.QPoint(1000, 500)
                widget.press_window = widget.pos()
                widget.last_drag_position = widget.press_global
                widget.last_drag_at = time.monotonic()
                widget.dragged, widget.drag_mode = True, "window"

                def move(x):
                    event = OVERLAY.QtGui.QMouseEvent(
                        OVERLAY.QtCore.QEvent.MouseMove, widget.creature_rect.center(),
                        OVERLAY.QtCore.QPointF(x, 500), OVERLAY.QtCore.Qt.NoButton,
                        OVERLAY.QtCore.Qt.LeftButton, OVERLAY.QtCore.Qt.NoModifier)
                    widget.mouseMoveEvent(event)

                move(1100)
                move(1099)  # One-pixel reversal while previous flight is rightward.
                self.assertEqual(widget.facing_target, -1.)
                self.assertTrue(widget.clip_sample.mirror)
                self.assertNotEqual(widget.clip_sample.clip, "turn")
                move(1100)
                self.assertFalse(widget.clip_sample.mirror)
                widget.set_facing_mode("left")
                move(1200)
                self.assertTrue(widget.clip_sample.mirror)

    def test_actual_gif_loops_persist_through_takeoff_movement_and_landing(self):
        widget = self.widget()
        widget.receive_state(self.snapshot())
        widget.status_until = 0
        self.assertIsNotNone(widget.clip_player)
        self.assertEqual(dict(widget.clip_library.errors), {})
        self.assertLessEqual(widget.clip_library.decoded_bytes, 96 * 1024 * 1024)
        now = widget.last_seen
        widget.render_frame(now)
        self.assertEqual(widget.clip_sample.clip, "idle")
        first = widget.clip_sample.image
        widget.render_frame(now + .25)
        self.assertGreater(widget.clip_sample.index, 0)
        self.assertNotEqual(widget.clip_sample.image, first)
        widget.flight_strength = 1.
        widget.render_frame(now + .3)
        self.assertEqual(widget.clip_sample.clip, "takeoff")
        moving_at = now + .3 + widget.clip_library.clips["takeoff"].duration_ms / 1000 + .01
        widget.render_frame(moving_at)
        self.assertEqual(widget.clip_sample.clip, "moving")
        widget.render_frame(moving_at + .2)
        self.assertEqual(widget.clip_sample.clip, "moving")
        self.assertGreater(widget.clip_sample.index, 0)
        widget.flight_strength = 0.
        widget.render_frame(moving_at + .3)
        self.assertEqual(widget.clip_sample.clip, "landing")
        landed_at = moving_at + .3 + widget.clip_library.clips["landing"].duration_ms / 1000 + .01
        widget.render_frame(landed_at)
        self.assertEqual(widget.clip_sample.clip, "idle")
        self.assertFalse(widget.clip_sample.transition)

        class SingleFramePainter:
            def __init__(self):
                self.images = []
                self.transform = None
            def save(self):
                pass
            def restore(self):
                pass
            def setTransform(self, transform, combine):
                self.transform = transform
            def drawImage(self, rectangle, image):
                self.images.append(image)
            def drawPixmap(self, *args):
                raise AssertionError("A GIF body must not blend with a PNG pose")

        painter = SingleFramePainter()
        widget.draw_body(painter, landed_at)
        self.assertEqual(len(painter.images), 1)
        self.assertEqual(painter.images[0].size(), widget.skin.result.size())
        self.assertTrue(widget.skin.mask_valid)
        widget.skin.mode = "off"
        painter.images.clear()
        widget.draw_body(painter, landed_at)
        self.assertEqual(len(painter.images), 1)
        self.assertEqual(painter.images[0].size(), widget.clip_sample.image.size())
        self.assertAlmostEqual(abs(painter.transform.m11()), 1., places=6)

    def test_living_skin_changes_only_the_body_and_persists_its_controls(self):
        import numpy as np
        from desktop.skin import rgba
        with tempfile.TemporaryDirectory() as directory:
            widget = self.widget(Path(directory))
            widget.receive_state(self.snapshot())
            widget.reduced_motion = True
            widget.status_until = 0
            now = widget.last_seen
            widget.skin.mode = "off"
            widget.last_mask = 0
            widget.render_frame(now)
            original = rgba(widget.frame)
            original_region = widget.input_region
            widget.skin.mode = "crimson"
            widget.last_mask = 0
            widget.render_frame(now)
            colored = rgba(widget.frame)
            # Alpha and input shape must survive the color layer unchanged.
            np.testing.assert_array_equal(original[:,:,3], colored[:,:,3])
            self.assertEqual(widget.input_region, original_region)
            rect = widget.creature_rect.adjusted(-2,-2,2,2)
            changed = np.any(original != colored,axis=2)
            ys,xs = np.where(changed)
            self.assertGreater(len(xs),100)
            self.assertTrue(all(rect.contains(float(x),float(y)) for x,y in zip(xs,ys)))
            widget.set_skin_mode("camouflage")
            self.assertEqual(widget.preferences.value("skin_mode"), "camouflage")
            self.assertEqual(widget.diagnostics()["skin"]["registered_clips"],12)
            restored = self.widget(Path(directory))
            self.assertEqual(restored.skin.mode, "camouflage")

    def test_missing_or_unreadable_gif_bank_falls_back_to_an_intact_png(self):
        widget = self.widget()
        widget.receive_state(self.snapshot())
        with tempfile.TemporaryDirectory(prefix="terminus-gif-fallback-") as directory:
            assets = Path(directory)
            shutil.copyfile(ROOT / "web/assets/terminus-refined.png", assets / "terminus-refined.png")
            widget.assets = assets
            widget.load_art()
            self.assertIsNone(widget.clip_player)
            self.assertFalse(widget.artwork().isNull())
            clips = assets / "clips"
            clips.mkdir()
            (clips / "broken.gif").write_bytes(b"not a gif")
            (clips / "manifest.json").write_text(json.dumps({"version": 1, "canvas": [384, 416], "clips": {
                "idle": {"file": "broken.gif", "loop": True}}}))
            widget.load_art()
            widget.render_frame(widget.last_seen)
            self.assertIsNone(widget.clip_player)
            self.assertEqual(widget.clip_error, "ClipError")
            self.assertFalse(widget.artwork().isNull())
            self.assertGreater(OVERLAY.QtGui.qAlpha(widget.frame.pixel(widget.creature_rect.center().toPoint())), 0)

    @staticmethod
    def awareness_snapshot(now):
        return {"available": True, "enabled": True, "observed_at": now,
                "focused_window": {"x": 200, "y": 100, "width": 900, "height": 600, "own": False},
                "typing": {"active": True, "last_at": now, "rate": 6., "pulse": .7, "sequence": 1},
                "caret": {"x": 500, "y": 300, "width": 1, "height": 18},
                "source": "x11-xinput2", "permission": "local-observation", "caret_source": "at-spi"}

    def test_awareness_only_emits_bounded_real_aggregate_events_and_discards_content(self):
        widget = self.widget()
        widget.receive_state(self.snapshot())
        now = widget.last_seen
        events = []
        widget.client.send_event = lambda kind, **fields: events.append((kind, fields))
        snapshot = self.awareness_snapshot(now)
        snapshot["focused_window"]["title"] = "secret content"
        snapshot["typing"]["keycodes"] = ["secret content"]
        snapshot["text"] = "secret content"
        widget.receive_awareness(snapshot)
        self.assertEqual(len(events), 1)

        self.assertEqual(events[0][0], "activity")
        self.assertEqual(events[0][1]["context"], "typing")
        self.assertEqual(events[0][1]["source"], "live")
        self.assertEqual(events[0][1]["intensity"], .16)
        self.assertEqual(set(events[0][1]), {"context", "source", "intensity", "timestamp"})
        self.assertNotIn("secret content", json.dumps(widget.awareness))
        snapshot["typing"]["sequence"] = 2
        widget.receive_awareness(snapshot)
        self.assertEqual(len(events), 1)
        widget.last_typing_sent = -float("inf")
        snapshot["typing"]["last_at"] = now - 10
        widget.receive_awareness(snapshot)
        self.assertEqual(len(events), 1)
        snapshot["typing"]["last_at"] = now
        snapshot["secure_entry"] = True
        widget.receive_awareness(snapshot)
        self.assertEqual(len(events), 1)
        self.assertIsNone(widget.awareness["typing"])
        self.assertIsNone(widget.awareness["caret"])
        snapshot["secure_entry"] = False
        widget.disconnect("offline")
        widget.receive_awareness(snapshot)
        self.assertEqual(len(events), 1)

    def test_idle_mac_typing_permission_is_visible_before_first_key(self):
        widget = self.widget()
        widget.receive_state(self.snapshot())
        snapshot = self.awareness_snapshot(widget.last_seen)
        snapshot["source"] = "mac-readonly"
        snapshot["typing"] = {"active": False, "last_at": None, "rate": 0., "pulse": 0., "sequence": 0}
        widget.receive_awareness(snapshot)
        self.assertIsNone(widget.awareness["typing"])
        self.assertTrue(widget.diagnostics()["desktop_awareness"]["typing_available"])

    def test_typing_pose_requires_both_authoritative_imitation_and_recent_real_activity(self):
        widget = self.widget()
        state = self.snapshot()
        state.update(server_time=1000., gesture={"id": "g-imitate", "kind": "imitate", "started_at": 1000.,
                                                "duration": 6., "strength": .3})
        widget.receive_state(state)
        now = widget.last_seen
        widget.client.send_event = lambda *args, **fields: None
        for step in range(10):
            widget.advance_presentation(now + step / 30, 1 / 30)
        self.assertEqual(widget.typing_blend, 0.)
        self.assertEqual(widget.typing_phase, 0.)
        widget.receive_awareness(self.awareness_snapshot(now))
        for step in range(25):
            widget.advance_presentation(now + step / 30, 1 / 30)
        self.assertGreater(widget.typing_blend, .9)
        self.assertGreater(widget.typing_phase, .5)
        phase = widget.typing_phase
        for step in range(40):
            widget.advance_presentation(now + 3 + step / 30, 1 / 30)
        self.assertLess(widget.typing_blend, .02)
        self.assertEqual(widget.typing_phase, phase)
        widget.receive_awareness(self.awareness_snapshot(time.monotonic()))
        state["gesture"] = None
        widget.typing_blend = 0.
        widget.advance_presentation(now + .1, .1)
        self.assertEqual(widget.typing_blend, 0.)

    def test_window_inspection_perches_outside_the_observed_window_and_honors_cooldown(self):
        widget = self.widget()
        widget.receive_state(self.snapshot())
        now = widget.last_seen
        snapshot = self.awareness_snapshot(now)
        snapshot["typing"] = None
        widget.receive_awareness(snapshot)
        widget.roam_step = 3
        area = OVERLAY.QtCore.QRect(0, 36, 1920, 1044)
        bounds = widget.motion_bounds(area)
        position = OVERLAY.QtCore.QPointF(1400, 600)
        motion = {"intent": "explore"}
        target = widget.window_perch(now, position, bounds, motion)
        self.assertIsNotNone(target)
        self.assertTrue(bounds[0] <= target.x() <= bounds[2])
        self.assertTrue(bounds[1] <= target.y() <= bounds[3])
        center = target + OVERLAY.QtCore.QPointF(220, 160)
        self.assertFalse(OVERLAY.QtCore.QRectF(200, 100, 900, 600).contains(center))
        self.assertIsNone(widget.window_perch(now + 1, position, bounds, motion))
        self.assertIsNone(widget.window_perch(now + 80, position, bounds, motion))

    def test_optional_desktop_observers_are_offscreen_disabled_and_closed_with_the_body(self):
        widget = self.widget()
        widget.start_awareness()
        self.assertIsNone(widget.awareness_provider)
        self.assertIsNone(widget.caret_provider)
        self.assertFalse(widget.awareness_timer.isActive())
        lifecycle = []

        class Caret:
            def start(self):
                lifecycle.append("caret-start")
                return True
            def snapshot(self):
                return {"rect": None, "available": False}
            def close(self):
                lifecycle.append("caret-close")

        class Awareness:
            def __init__(self, **fields):
                self.fields = fields
            def start(self):
                lifecycle.append("awareness-start")
            def snapshot(self):
                if "caret_provider" in self.fields:raise AssertionError("Retired caret reader must not be started")
                return {"available": False, "enabled": True, "observed_at": time.monotonic()}
            def close(self, timeout=1.):
                lifecycle.append("awareness-close")
                return True

        with patch.dict(sys.modules, {"desktop.awareness": types.SimpleNamespace(DesktopAwareness=Awareness),
                                      "desktop.caret": types.SimpleNamespace(LocalCaretObserver=Caret)}), \
                patch.object(OVERLAY.QtWidgets.QApplication, "platformName", return_value="xcb"):
            with patch.dict(os.environ, {"DISPLAY": ":fixture", "XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}):
                widget.start_awareness()
                self.assertIsNone(widget.caret_provider)
                self.assertIsNone(widget.awareness_provider)
                self.assertEqual(lifecycle, [])
            with patch.dict(os.environ, {"DISPLAY": ":fixture", "XDG_SESSION_TYPE": "x11", "WAYLAND_DISPLAY": ""}):
                widget.start_awareness()
                self.assertIsNone(widget.caret_provider)
                self.assertIsInstance(widget.awareness_provider, Awareness)
                widget.close()
        self.assertEqual(lifecycle, ["awareness-start", "awareness-close"])

    def test_animation_scheduler_is_quiet_at_rest_and_smooth_during_actions(self):
        widget = self.widget()
        state = self.snapshot()
        state.update(behavior="sleep", server_time=1000.)
        widget.receive_state(state)
        now = widget.last_seen
        self.assertGreaterEqual(widget.frame_interval(now), 125)
        state["behavior"] = "inspect"
        state["gesture"] = {"id": "g-peer", "kind": "peer", "started_at": 1000., "duration": 4., "strength": .7}
        self.assertLessEqual(widget.frame_interval(now), 66 if sys.platform == "darwin" else 40)
        self.assertGreaterEqual(widget.frame_interval(now + 6), 250)
        widget.reduced_motion = True
        self.assertGreaterEqual(widget.frame_interval(now), 250)

    def test_an_unfinished_excursion_does_not_keep_naps_repainting_at_travel_speed(self):
        widget = self.widget()
        state = self.snapshot()
        state.update(server_time=1000., motion={"intent": "explore", "started_at": 1000., "duration": 60., "strength": .4})
        widget.receive_state(state)
        now = widget.last_seen
        widget.interaction_until = 0
        widget.roam_goal = OVERLAY.QtCore.QPointF(widget.pos()) + OVERLAY.QtCore.QPointF(-400, 0)
        self.assertLessEqual(widget.frame_interval(now), 66 if sys.platform == "darwin" else 40)
        for behavior in ("sleep", "dream"):
            state["behavior"] = behavior
            self.assertGreaterEqual(widget.frame_interval(now), 125)
            before = widget.pos()
            widget.advance_motion(now, .1)
            self.assertEqual(widget.pos(), before)
            self.assertIsNotNone(widget.roam_goal)
        state["gesture"] = {"id": "g-curl", "kind": "curl", "started_at": 1000., "duration": 4., "strength": .6}
        self.assertLessEqual(widget.frame_interval(now), 66)
        state["gesture"] = None
        state["behavior"] = "inspect"
        state["motion"]["intent"] = "rest"
        self.assertGreaterEqual(widget.frame_interval(now), 66)

    def test_mac_quiet_frame_budget_does_not_follow_gif_boundary_or_slow_dragging(self):
        widget = self.widget()
        state = self.snapshot()
        state.update(server_time=1000., behavior="idle", motion={"intent":"rest"})
        widget.receive_state(state)
        now = widget.last_seen
        widget.advance_presentation(now, .1)
        with patch.object(OVERLAY.sys, "platform", "darwin"):
            self.assertGreaterEqual(widget.frame_interval(now), 125)
            state["behavior"] = "sleep"
            self.assertGreaterEqual(widget.frame_interval(now), 250)
            widget.press_global = OVERLAY.QtCore.QPoint(10,10)
            self.assertLessEqual(widget.frame_interval(now), 66)

    def test_closed_eyes_do_not_open_during_a_sleeping_blink(self):
        widget = self.widget()
        state = self.snapshot()
        state.update(behavior="sleep", server_time=1000., gesture={"id": "g-blink", "kind": "blink", "started_at": 1000.,
                                                                  "duration": 1.8, "strength": .6})
        widget.receive_state(state)
        now = widget.last_seen
        widget.sleep_blend = 1.
        for progress in (0., .25, .5, .78, .99):
            self.assertEqual(widget.pose(now + progress * 1.8)["blink"], 1.)
        widget.sleep_blend = 0.
        self.assertGreater(widget.pose(now + .25 * 1.8)["blink"], .99)
        self.assertLess(widget.pose(now + .5 * 1.8)["blink"], .01)

    def test_repeated_core_snapshots_cannot_rewind_or_replay_a_gesture(self):
        widget = self.widget()
        state = self.snapshot()
        state.update(server_time=1000., gesture={"id": "g-blink", "kind": "blink", "started_at": 1000.,
                                                "duration": 1.8, "strength": .6})
        widget.receive_state(state)
        now = widget.last_seen
        first_start = widget.gesture_clock_start
        # Receiving the same snapshot again must preserve the local playhead.
        widget.receive_state(state)
        self.assertEqual(widget.gesture_clock_start, first_start)
        self.assertAlmostEqual(widget.gesture(now + 1)["progress"], 1 / 1.8, places=4)
        widget.last_seen = now + 2
        self.assertIsNone(widget.gesture(now + 2))

    def test_view_preferences_survive_restart_and_invalid_placement_is_clamped(self):
        with tempfile.TemporaryDirectory(prefix="terminus-view-settings-") as directory:
            path = Path(directory)
            widget = self.widget(path)
            widget.change_scale(.8)
            widget.move(24, 42)
            widget.roaming_paused = widget.reduced_motion = True
            widget.save_view_preferences()
            widget.close()
            restored = self.widget(path)
            self.assertEqual(restored.scale, .8)
            self.assertEqual(restored.pos(), OVERLAY.QtCore.QPoint(24, 42))
            self.assertTrue(restored.roaming_paused)
            self.assertTrue(restored.reduced_motion)
            self.assertEqual((path / "desktop.ini").stat().st_mode & 0o777, 0o600)
            restored.close()
            settings = OVERLAY.QtCore.QSettings(str(path / "desktop.ini"), OVERLAY.QtCore.QSettings.IniFormat)
            settings.setValue("scale", "nan")
            settings.setValue("x", 999999)
            settings.setValue("y", -999999)
            settings.sync()
            repaired = self.widget(path)
            self.assertEqual(repaired.scale, 1.)
            left, top, right, bottom = repaired.motion_bounds()
            self.assertTrue(left <= repaired.x() <= right)
            self.assertTrue(top <= repaired.y() <= bottom)
            override = self.widget(path, scale=1.3)
            self.assertEqual(override.scale, 1.3)

    def test_native_observations_describe_only_own_visibility_and_clock(self):
        widget = self.widget()
        widget.receive_state(self.snapshot())
        widget.show()
        self.app.processEvents()
        events = []
        widget.client.send_event = lambda kind, **fields: events.append((kind, fields))
        widget.observe_presence()
        self.assertEqual([kind for kind, _ in events], ["presence", "time"])
        self.assertEqual(events[0][1]["context"], "native habitat visible")
        self.assertTrue(all(fields["source"] == "live" and fields["intensity"] <= .1 and fields["timestamp"] > 0
                            for _, fields in events))
        widget.observe_presence()
        self.assertEqual(len(events), 2)
        widget.disconnect("offline")
        widget.presence_at = -float("inf")
        widget.observe_presence()
        self.assertEqual(len(events), 2)

    def test_local_touch_physics_settles_and_reduced_motion_is_still(self):
        widget = self.widget()
        widget.body_velocity = OVERLAY.QtCore.QPointF(25, -30)
        widget.advance_physics(.05)
        self.assertGreater(abs(widget.body_offset.x()) + abs(widget.body_offset.y()), .1)
        for _ in range(200):
            widget.advance_physics(.02)
        self.assertLess(abs(widget.body_offset.x()) + abs(widget.body_offset.y()), .01)
        widget.body_velocity = OVERLAY.QtCore.QPointF(25, -30)
        widget.reduced_motion = True
        widget.advance_physics(.1)
        self.assertEqual(widget.body_offset, OVERLAY.QtCore.QPointF())
        self.assertEqual(widget.body_velocity, OVERLAY.QtCore.QPointF())

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
