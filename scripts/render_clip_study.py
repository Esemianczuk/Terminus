#!/usr/bin/env python3
"""Preview the real GIF player in the native view with labelled state fixtures.

This does not access the resident organism or observe any desktop applications.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from terminus.core import Organism

SPEC = importlib.util.spec_from_file_location("terminus_gif_study", ROOT / "desktop/overlay.py")
NATIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)
SCENES = (("Idle loop", 3.2, "idle", 1), ("Takeoff and moving loop", 3.2, "moving", 1),
          ("Instant flip and moving loop", 3.0, "moving", -1), ("Landing into idle", 2.0, "idle", -1),
          ("Poke transition", 1.2, "idle", -1), ("Settle into sleep loop", 4., "sleep", -1),
          ("Wake transition", 1.3, "idle", -1), ("Typing loop", 2.4, "typing", -1),
          ("Stretch clip", 1.2, "idle", -1), ("Yawn clip", 1.2, "idle", -1))


def run(output, fps, video):
    output.mkdir(parents=True, exist_ok=True)
    app = NATIVE.QtWidgets.QApplication.instance() or NATIVE.QtWidgets.QApplication([])
    with tempfile.TemporaryDirectory(prefix="terminus-gif-study-") as temporary:
        client = NATIVE.CoreClient("http://127.0.0.1:1", Path(temporary))
        widget = NATIVE.Overlay(client, ROOT / "web/assets", 1.3)
        for timer in (widget.animation, widget.asset_timer, widget.presence_timer, widget.awareness_timer):
            timer.stop()
        if widget.clip_player is None:
            raise RuntimeError("The actual GIF bank must load for this study")
        state = Organism(seed=814, now=1000.).state()
        for index, node in enumerate(state["nodes"]):
            node["activation"] = .06 + .05 * (.5 + .5 * math.sin(index))
        state.update(behavior="idle", attention="curious", gesture=None)
        widget.state, widget.connected = state, True
        widget.status_until = 0
        widget.glyph_sequence = []
        widget.roaming_paused = True
        widget.reduced_motion = False
        request = {}

        def prepare(now):
            widget.clip_sample = widget.clip_player.advance(now, **request)

        widget.prepare_clip = prepare
        timeline, count, samples, stills = 0., 0, [], []
        frames = Path(temporary) / "frames"
        frames.mkdir()
        for scene_index, (label, duration, desired, facing) in enumerate(SCENES):
            for index in range(math.ceil(duration * fps)):
                elapsed = index / fps
                now = widget.started + timeline + elapsed
                widget.last_seen = now
                request.update(desired=desired, facing=facing, dragging=False, fresh=True,
                               poke_id="fixture-poke" if scene_index >= 4 else None,
                               gesture="stretch" if scene_index == 8 else "yawn" if scene_index == 9 else None,
                               gesture_id="fixture-" + str(scene_index))
                widget.flight_strength = .2 if desired == "moving" else 0.
                widget.flight_bank = 3 * math.sin(elapsed) if desired == "moving" else 0.
                widget.render_frame(now)
                sample = widget.clip_sample
                image = NATIVE.QtGui.QImage(widget.frame.width(), widget.frame.height() + 58,
                                             NATIVE.QtGui.QImage.Format_ARGB32)
                image.fill(NATIVE.QtGui.QColor("#242a31"))
                painter = NATIVE.QtGui.QPainter(image)
                painter.setPen(NATIVE.QtGui.QColor("#d5eee6")); painter.setFont(NATIVE.QtGui.QFont("Sans Serif", 11))
                painter.drawText(18, 24, label + " · " + sample.clip + ".gif")
                painter.setPen(NATIVE.QtGui.QColor("#87a8a5")); painter.setFont(NATIVE.QtGui.QFont("Sans Serif", 8))
                painter.drawText(18, 45, "Controlled GIF playback / no live state or desktop capture")
                painter.drawImage(0, 58, widget.frame); painter.end()
                if video:
                    image.save(str(frames / f"frame-{count:05d}.png"))
                if index == min(8, math.ceil(duration * fps) - 1):
                    image.save(str(output / ("scene-" + str(scene_index) + ".png")))
                    stills.append(image.copy())
                samples.append({"time": round(timeline + elapsed, 3), "clip": sample.clip,
                                "frame": sample.index, "mirror": sample.mirror, "transition": sample.transition})
                count += 1
            timeline += math.ceil(duration * fps) / fps
        if stills:
            sheet = NATIVE.QtGui.QImage(stills[0].width() * 2, stills[0].height() * math.ceil(len(stills) / 2),
                                        NATIVE.QtGui.QImage.Format_ARGB32)
            sheet.fill(NATIVE.QtGui.QColor("#242a31")); painter = NATIVE.QtGui.QPainter(sheet)
            for index, image in enumerate(stills):
                painter.drawImage((index % 2) * image.width(), (index // 2) * image.height(), image)
            painter.end(); sheet.save(str(output / "contact-sheet.png"))
        if video and shutil.which("ffmpeg"):
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(fps),
                            "-i", str(frames / "frame-%05d.png"), "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                            "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", str(output / "gif-state-preview.mp4")], check=True)
        report = {"scope": "controlled real GIF player and native-view fixtures", "live_state_accessed": False,
                  "screen_or_apps_captured": False, "fps": fps, "frames": count, "duration_seconds": round(timeline, 3),
                  "decoded_bytes": widget.clip_library.decoded_bytes, "clips": sorted({s["clip"] for s in samples}), "samples": samples}
        (output / "provenance.json").write_text(json.dumps(report, indent=2) + "\n")
        widget.close(); app.processEvents()
        print(json.dumps({key: value for key, value in report.items() if key != "samples"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "work/gif-study")
    parser.add_argument("--fps", type=int, default=18)
    parser.add_argument("--stills-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.fps <= 60:
        parser.error("--fps must be 1..60")
    run(args.output_dir.resolve(), args.fps, not args.stills_only)
