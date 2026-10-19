"""Behavior and native coordinate checks for binocular gaze intent."""
from __future__ import annotations

import math
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6 import QtCore

from desktop.gaze import GazeController
from desktop.overlay import Overlay


class GazeControllerTests(unittest.TestCase):
    BODY = (400., 300., 190., 206.)
    SCREEN = (0., 0., 4000., 2400.)
    CENTRES = ((.47, .43), (.69, .37))

    def follow(self, target, *, body=None, bank=0., mirror=False, pivot_offset=30.):
        gaze = GazeController(5)
        for step in range(90):
            gaze.update(step/60, body=body or self.BODY, screen=self.SCREEN,
                        pointer=(target[0]/4000, target[1]/2400, .2),
                        bank=bank, mirror=mirror, eye_centres=self.CENTRES,
                        pivot_offset=pivot_offset)
        return gaze

    def test_actual_pointer_changes_are_seen_without_motion_flags(self):
        gaze = GazeController(2)
        gaze.update(0., body=self.BODY, screen=self.SCREEN, pointer=(.6, .4, 0.))
        self.assertNotEqual(gaze.mode, "pointer")
        gaze.update(.125, body=self.BODY, screen=self.SCREEN, pointer=(.601, .4, 0.))
        self.assertEqual(gaze.mode, "pointer")
        self.assertIsNotNone(gaze.world_target)
        self.assertTrue(gaze.settling)
        # A reused aggregate motion flag is not a new movement.
        for step in range(1, 9):
            gaze.update(.125+step*.1, body=self.BODY, screen=self.SCREEN, pointer=(.601, .4, .2))
        self.assertEqual(gaze.pointer_at, .125)
        self.assertFalse(gaze.settling)
        gaze.update(3., body=self.BODY, screen=self.SCREEN, pointer=(.601, .4, .2))
        self.assertNotEqual(gaze.mode, "pointer")

    def test_pointer_loss_and_reduced_motion_forget_desktop_target(self):
        gaze = self.follow((2400., 700.))
        self.assertEqual(gaze.mode, "pointer")
        gaze.update(1.6, body=self.BODY, screen=self.SCREEN, pointer=None)
        self.assertIsNone(gaze.pointer_xy)
        self.assertIsNone(gaze._pointer_previous)
        self.assertNotEqual(gaze.mode, "pointer")
        self.assertEqual(gaze.update(1.7, body=self.BODY, screen=self.SCREEN,
                                     pointer=(.6, .4, .2), reduced_motion=True), (0.,)*4)
        self.assertFalse(gaze.settling)
        self.assertIsNone(gaze.pointer_xy)

    def test_same_world_target_in_body_coordinates_survives_bank_and_mirror(self):
        bx, by, bw, bh = self.BODY
        pivot = (bx+bw*.5, by+bh*.5+30.)
        center = (bx+.58*bw, by+.40*bh)
        target = (center[0]+130., center[1]+35.)
        reference = self.follow(target)
        for mirror in (False, True):
            for bank in (-16., 16.):
                angle = math.radians(bank)
                def transform(point):
                    x, y = point[0]-pivot[0], point[1]-pivot[1]
                    if mirror:
                        x = -x
                    return (pivot[0]+math.cos(angle)*x-math.sin(angle)*y,
                            pivot[1]+math.sin(angle)*x+math.cos(angle)*y)
                transformed = self.follow(transform(target), bank=bank, mirror=mirror)
                with self.subTest(mirror=mirror, bank=bank):
                    for first, second in zip(reference.shift, transformed.shift):
                        self.assertAlmostEqual(first, second, places=6)

    def test_user_scale_preserves_gaze_direction_and_near_convergence(self):
        target = (self.BODY[0]+self.BODY[2]*.58+25., self.BODY[1]+self.BODY[3]*.4+15.)
        reference = self.follow(target)
        for scale in (.65, 2.):
            scaled = self.follow(tuple(v*scale for v in target),
                                 body=tuple(v*scale for v in self.BODY), pivot_offset=30*scale)
            for first, second in zip(reference.shift, scaled.shift):
                self.assertAlmostEqual(first, second, places=6)
        self.assertGreater(reference.shift[0]-reference.shift[2], 1.)

    def test_saccade_is_bounded_then_ends_without_permanent_high_frame_rate(self):
        gaze = GazeController(5)
        shifts = []
        for step in range(100):
            t = step/60
            shifts.append(gaze.update(t, body=self.BODY, screen=self.SCREEN,
                                      pointer=(.9, .9, .2), eye_centres=self.CENTRES))
        self.assertTrue(all(abs(s[0]) <= 4.32 and abs(s[2]) <= 4.32
                            and abs(s[1]) <= 2.5 and abs(s[3]) <= 2.5 for s in shifts))
        self.assertTrue(all(a[0] <= b[0]+1e-9 for a, b in zip(shifts, shifts[1:])))
        self.assertFalse(gaze.settling)
        gaze.update(2., body=self.BODY, screen=self.SCREEN, sleeping=True)
        self.assertFalse(gaze.settling)
        self.assertEqual(gaze.mode, "sleep")
        self.assertIsNone(gaze.world_target)

    def test_native_pointer_query_requires_enabled_fresh_observation(self):
        fake = SimpleNamespace(
            home_screen=SimpleNamespace(virtualGeometry=lambda: QtCore.QRect(-1920, 0, 3840, 1080)),
            creature_rect=QtCore.QRectF(100., 80., 190., 206.), scale=1.,
            x=lambda: 20., y=lambda: 30., awareness_enabled=True,
            awareness={"available": True, "enabled": True, "observed_at": 10.,
                       "pointer": {"available": True}}, fresh=lambda now: True,
            state={"behavior": "idle"}, inspection_target=lambda now: None,
            clip_sample=None, gaze_atlas=None, gaze=Mock(), typing_blend=0.,
            reduced_motion=False, flight_bank=12.)
        fake.gaze.update.return_value = (0.,)*4
        with patch("desktop.overlay.QtGui.QCursor.pos", return_value=QtCore.QPoint(1200, 300)) as cursor:
            Overlay.update_gaze(fake, 10.1, {})
            cursor.assert_called_once_with()
            supplied = fake.gaze.update.call_args.kwargs
            self.assertAlmostEqual(supplied["pointer"][0], 3120/3840)
            self.assertEqual(supplied["bank"], 12.)
            fake.awareness_enabled = False
            cursor.reset_mock()
            Overlay.update_gaze(fake, 10.2, {})
            cursor.assert_not_called()
            self.assertIsNone(fake.gaze.update.call_args.kwargs["pointer"])
            fake.awareness_enabled = True
            fake.fresh = lambda now: True
            fake.awareness["observed_at"] = 1.
            Overlay.update_gaze(fake, 10.2, {})
            cursor.assert_not_called()
            self.assertIsNone(fake.gaze.update.call_args.kwargs["pointer"])
            fake.awareness["observed_at"] = 10.
            fake.awareness["enabled"] = False
            Overlay.update_gaze(fake, 10.2, {})
            cursor.assert_not_called()
            self.assertIsNone(fake.gaze.update.call_args.kwargs["pointer"])
            fake.awareness["enabled"] = True
            fake.fresh = lambda now: False
            Overlay.update_gaze(fake, 10.2, {})
            cursor.assert_not_called()
            self.assertIsNone(fake.gaze.update.call_args.kwargs["pointer"])

    def test_native_gaze_frame_pacing_is_temporary(self):
        fake = SimpleNamespace(gpu_scene=SimpleNamespace(available=True), reduced_motion=False,
                               fresh=lambda now: True, gaze=SimpleNamespace(settling=True),
                               directional_motion=SimpleNamespace(settling=False),
                               tendril_motion=SimpleNamespace(settling=False),
                               skin=SimpleNamespace(effect_uniforms=lambda:{}),
                               graph_motion=SimpleNamespace(settling=False), hovering=False,
                               press_global=None, touch_started=-math.inf, gesture=lambda now: None,
                               roam_goal=None, state={"behavior": "idle"})
        self.assertEqual(Overlay.frame_interval(fake, 10.), 33)
        fake.gaze.settling = False
        self.assertEqual(Overlay.frame_interval(fake, 10.), 125)
        fake.reduced_motion = True
        self.assertEqual(Overlay.frame_interval(fake, 10.), 250)
        fake.gpu_scene = None
        fake.reduced_motion = False
        fake.clip_sample = None
        fake.presentation_interval = lambda now: 66
        with patch("desktop.overlay.sys.platform", "darwin"):
            fake.gaze.settling = True
            self.assertEqual(Overlay.frame_interval(fake, 10.), 50)
            fake.gaze.settling = False
            self.assertEqual(Overlay.frame_interval(fake, 10.), 125)


if __name__ == "__main__":
    unittest.main()
