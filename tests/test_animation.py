"""Real GIF decoding, bounded assets and presentation-state contracts."""

import json
import math
from pathlib import Path
import struct
import tempfile
import unittest

from PySide6 import QtGui

from desktop.animation import ClipError, ClipLibrary, ClipPlayer


ROOT = Path(__file__).resolve().parents[1]


def gif_bytes(delays=(60, 100), *, transparent=True):
    """A tiny real GIF89a fixture; clear codes avoid an image-library dependency."""
    data = bytearray(b"GIF89a" + struct.pack("<HHBBB", 2, 2, 0x80, 0, 0))
    data.extend(bytes((255, 0, 255, 0, 180, 170)))
    data.extend(b"!\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00")
    for index, delay in enumerate(delays):
        data.extend(b"!\xf9\x04" + bytes((9 if transparent else 8,)) + struct.pack("<H", delay // 10) + b"\x00\x00")
        data.extend(b"," + struct.pack("<HHHHB", 0, 0, 2, 2, 0))
        pixels = [1, 0, 0, 0] if index % 2 == 0 else [0, 0, 0, 1]
        codes = [code for pixel in pixels for code in (4, pixel)] + [5]
        packed = sum(code << (position * 3) for position, code in enumerate(codes))
        encoded = packed.to_bytes(math.ceil(len(codes) * 3 / 8), "little")
        data.extend(bytes((2, len(encoded))) + encoded + b"\x00")
    data.extend(b";")
    return bytes(data)


class AnimationTests(unittest.TestCase):
    def library(self, names=None):
        temporary = tempfile.TemporaryDirectory(prefix="terminus-gif-test-")
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        names = names or ("idle", "moving", "sleep", "typing", "takeoff", "landing", "turn", "wake", "poke", "sleep-in", "stretch", "yawn")
        entries = {}
        for name in names:
            (directory / (name + ".gif")).write_bytes(gif_bytes())
            entries[name] = {"file": name + ".gif", "loop": name in {"idle", "moving", "sleep", "typing"},
                             "anchors": {"left": [.3, .7], "right": [.7, .7], "center": [.5, .75]}}
        path = directory / "manifest.json"
        path.write_text(json.dumps({"version": 1, "canvas": [2, 2], "clips": entries}))
        return ClipLibrary.from_manifest(path), path

    def test_real_gif_frames_are_decoded_once_with_their_delays_and_transparency(self):
        library, path = self.library(("idle",))
        clip = library.clips["idle"]
        self.assertEqual(len(clip.frames), 2)
        self.assertNotEqual(clip.frames[0], clip.frames[1])
        self.assertEqual(clip.delays_ms, (60, 100))
        self.assertEqual(clip.duration_ms, 160)
        self.assertEqual(library.decoded_bytes, 32)
        self.assertEqual(QtGui.qAlpha(clip.frames[0].pixel(0, 0)), 255)
        self.assertEqual(QtGui.qAlpha(clip.frames[0].pixel(1, 1)), 0)
        self.assertEqual(QtGui.qAlpha(clip.frames[1].pixel(0, 0)), 0)
        self.assertEqual(QtGui.qAlpha(clip.frames[1].pixel(1, 1)), 255)
        (path.parent / "idle.gif").unlink()
        player = ClipPlayer(library)
        player.advance(10., "idle")
        self.assertEqual(player.advance(10.10, "idle").index, 1)
        self.assertEqual(player.advance(11.10, "idle").index, 1)
        self.assertEqual(player.advance(11.14, "idle").index, 0)

    def test_takeoff_and_landing_play_once_between_persistent_loops(self):
        library, _ = self.library()
        player = ClipPlayer(library)
        self.assertEqual(player.advance(0, "idle").clip, "idle")
        takeoff = player.advance(.02, "moving")
        self.assertEqual((takeoff.clip, takeoff.index, takeoff.transition), ("takeoff", 0, True))
        self.assertEqual(player.advance(.10, "moving").index, 1)
        self.assertEqual(player.advance(.19, "moving").clip, "moving")
        self.assertEqual(player.advance(.30, "moving").index, 1)
        self.assertEqual(player.advance(.32, "idle").clip, "landing")
        landed = player.advance(.50, "idle")
        self.assertEqual(landed.clip, "idle")
        self.assertFalse(landed.transition)

    def test_facing_flips_current_frame_immediately_without_restarting_playback(self):
        library, _ = self.library()
        for state in ("idle", "moving"):
            with self.subTest(state=state):
                player = ClipPlayer(library)
                player.advance(0, state, facing=1)
                before = player.advance(.10, state, facing=1)
                flipped = player.advance(.10, state, facing=-1)
                self.assertEqual((flipped.clip, flipped.index, flipped.image), (before.clip, before.index, before.image))
                self.assertTrue(flipped.mirror)
                self.assertFalse(flipped.transition)
                self.assertFalse(player.advance(.101, state, facing=1).mirror)
                self.assertEqual(player.advance(.12, state, facing=-1).index, 1)

        player = ClipPlayer(library)
        player.advance(0, "idle")
        player.advance(.02, "moving")
        before = player.advance(.10, "moving", facing=1)
        flipped = player.advance(.10, "moving", facing=-1)
        self.assertEqual((flipped.clip, flipped.index), ("takeoff", before.index))
        self.assertTrue(flipped.mirror)
        self.assertEqual(player.advance(.19, "moving", facing=-1).clip, "moving")

    def test_drag_immediately_interrupts_a_poke_or_optional_gesture(self):
        library, _ = self.library()
        player = ClipPlayer(library)
        player.advance(0, "idle")
        self.assertEqual(player.advance(.02, "idle", poke_id="touch-1").clip, "poke")
        dragged = player.advance(.04, "idle", dragging=True, poke_id="touch-1")
        self.assertEqual((dragged.clip, dragged.index, dragged.state), ("takeoff", 0, "moving"))
        self.assertEqual(player.advance(.23, "idle", dragging=True).clip, "moving")
        self.assertEqual(player.advance(.24, "idle", dragging=False).clip, "landing")

    def test_pokes_and_core_gesture_ids_are_one_shot(self):
        library, _ = self.library()
        player = ClipPlayer(library)
        player.advance(0, "idle")
        self.assertEqual(player.advance(.02, "idle", poke_id="p-one").clip, "poke")
        self.assertEqual(player.advance(.10, "idle", poke_id="p-one").index, 1)
        self.assertEqual(player.advance(.20, "idle", poke_id="p-one").clip, "idle")
        gesture = {"id": "g-one", "kind": "stretch"}
        self.assertEqual(player.advance(.22, "idle", gesture=gesture).clip, "stretch")
        self.assertEqual(player.advance(.31, "idle", gesture=gesture).index, 1)
        self.assertEqual(player.advance(.40, "idle", gesture=gesture).clip, "idle")
        self.assertEqual(player.advance(1.4, "idle", gesture=gesture).clip, "idle")
        self.assertEqual(player.advance(1.5, "idle", gesture="yawn", gesture_id="g-two").clip, "yawn")

    def test_waking_and_entering_sleep_use_finite_clips(self):
        library, _ = self.library()
        player = ClipPlayer(library)
        self.assertEqual(player.advance(0, "sleep").clip, "sleep")
        self.assertEqual(player.advance(.1, "idle").clip, "wake")
        self.assertEqual(player.advance(.3, "idle").clip, "idle")
        self.assertEqual(player.advance(.4, "sleep").clip, "sleep-in")
        self.assertEqual(player.advance(.6, "sleep").clip, "sleep")

    def test_stale_or_degraded_state_freezes_last_presented_frame_and_discards_old_actions(self):
        library, _ = self.library()
        player = ClipPlayer(library)
        player.advance(0, "idle")
        last_good = player.advance(.10, "idle")
        frozen = player.advance(.12, "moving", fresh=False)
        self.assertEqual(frozen.image, last_good.image)
        self.assertEqual((frozen.clip, frozen.index), (last_good.clip, last_good.index))
        self.assertEqual(frozen.next_frame_ms, 1000)
        later = player.advance(10., "sleep", poke_id="stale-touch", gesture="stretch", gesture_id="old", fresh=False)
        self.assertEqual(later, frozen)
        self.assertEqual(player.advance(10.05, "moving", facing=-1, reduced_motion=True, fresh=False), frozen)
        resumed = player.advance(10.1, "idle", poke_id="stale-touch", gesture="stretch", gesture_id="old")
        self.assertEqual(resumed.clip, "idle")
        self.assertFalse(resumed.transition)

    def test_reduced_motion_uses_first_loop_frame_and_never_a_transition(self):
        library, _ = self.library()
        player = ClipPlayer(library)
        player.advance(0, "idle")
        first = player.advance(.1, "moving", facing=-1, reduced_motion=True)
        self.assertEqual((first.clip, first.index, first.transition, first.mirror), ("moving", 0, False, True))
        self.assertEqual(player.advance(9, "moving", facing=-1, reduced_motion=True).image, first.image)
        self.assertEqual(player.advance(9.1, "sleep", reduced_motion=True).clip, "sleep")

    def test_missing_optional_clips_have_a_deterministic_animated_fallback(self):
        library, _ = self.library(("idle",))
        player = ClipPlayer(library)
        player.advance(0, "idle")
        fallback = player.advance(.1, "moving")
        self.assertEqual(fallback.clip, "idle")
        self.assertTrue(fallback.fallback)
        self.assertEqual(player.advance(.20, "moving").index, 1)
        self.assertEqual(player.advance(.21, "moving", gesture="missing", gesture_id="unknown").clip, "idle")

    def test_bad_individual_clips_do_not_break_valid_idle_footage(self):
        library, path = self.library(("idle", "moving"))
        (path.parent / "moving.gif").write_bytes(b"broken")
        recovered = ClipLibrary.from_manifest(path)
        self.assertEqual(set(recovered.clips), {"idle"})
        self.assertIn("moving", recovered.errors)
        self.assertEqual(recovered.loop("moving").name, "idle")

    def test_asset_loading_rejects_static_images_path_escape_and_unbounded_caches(self):
        _, path = self.library(("idle", "moving"))
        image = QtGui.QImage(2, 2, QtGui.QImage.Format_ARGB32)
        image.fill(0)
        image.save(str(path.parent / "moving.gif"), "PNG")
        self.assertIn("moving", ClipLibrary.from_manifest(path).errors)
        value = json.loads(path.read_text())
        value["clips"]["moving"]["file"] = "../outside.gif"
        path.write_text(json.dumps(value))
        self.assertIn("moving", ClipLibrary.from_manifest(path).errors)
        for limits in ({"max_cache_bytes": 16}, {"max_frames": 1}, {"max_compressed_bytes": 8}, {"max_duration_ms": 100}):
            with self.subTest(limits=limits), self.assertRaises(ClipError):
                ClipLibrary.from_manifest(path, **limits)
        value["canvas"] = [2048, 2]
        path.write_text(json.dumps(value))
        with self.assertRaises(ClipError):
            ClipLibrary.from_manifest(path)

    def test_single_frame_and_opaque_gifs_are_not_accepted_as_desktop_animation(self):
        for contents in (gif_bytes((100,)), gif_bytes(transparent=False)):
            with self.subTest(contents=contents[:20]):
                _, path = self.library(("idle",))
                (path.parent / "idle.gif").write_bytes(contents)
                with self.assertRaises(ClipError):
                    ClipLibrary.from_manifest(path)

    def test_clock_does_not_rewind_or_accept_nonfinite_values(self):
        library, _ = self.library()
        player = ClipPlayer(library)
        player.advance(10., "idle")
        later = player.advance(10.1, "idle")
        self.assertEqual(player.advance(9., "idle"), later)
        for now in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                player.advance(now)

    def test_shipped_library_is_real_transparent_multiframe_gif_with_distinct_poses(self):
        library = ClipLibrary.from_manifest(ROOT / "web" / "assets" / "clips" / "manifest.json")
        self.assertEqual(library.canvas, (384, 416))
        self.assertFalse(library.errors)
        self.assertTrue({"idle", "moving", "sleep", "typing", "takeoff", "landing", "turn", "wake", "poke", "sleep-in", "stretch", "yawn"} <= set(library.clips))
        self.assertLessEqual(library.decoded_bytes, 96 * 1024 * 1024)
        for name, clip in library.clips.items():
            with self.subTest(clip=name):
                self.assertGreater(len(clip.frames), 1)
                self.assertTrue(any(frame != clip.frames[0] for frame in clip.frames[1:]))
                self.assertEqual(QtGui.qAlpha(clip.frames[0].pixel(0, 0)), 0)
                self.assertTrue(20 <= min(clip.delays_ms) <= max(clip.delays_ms) <= 1000)


if __name__ == "__main__":
    unittest.main()
