#!/usr/bin/env python3
"""Render controlled native gesture fixtures without opening the live organism.

This is an animation regression study, not evidence of autonomous live behavior.
All pixels come from our own offscreen QWidget. No screen or app is captured.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from terminus.core import Organism

SPEC = importlib.util.spec_from_file_location("terminus_native_study", ROOT / "desktop" / "overlay.py")
NATIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)


SCENES = (
    ("peer", "inspect", 3.2, "curious"),
    ("blink", "idle", 1.8, "self"),
    ("stretch", "idle", 4.4, "curious"),
    ("yawn", "settle", 4.2, "sleep"),
    ("tendril-inspect", "inspect", 3.8, "time"),
    ("signal", "attend", 3.2, "presence"),
    ("startled", "startled", 1.4, "poke"),
    ("curl", "settle", 3.8, "sleep"),
    ("sleep", "sleep", 4.4, "sleep"),
    ("dream", "dream", 4.2, "familiar"),
)


def fixture(base, kind, behavior, duration, target, elapsed):
    state = deepcopy(base)
    state.update(behavior=behavior, behavior_since=1000., server_time=1000. + elapsed,
                 attention=target, gesture={"id": "fixture-" + kind, "kind": kind,
                     "started_at": 1000., "duration": duration, "target_id": target, "strength": .78},
                 motion={"intent": "rest", "started_at": 1000., "duration": 120., "strength": .2})
    for index, node in enumerate(state["nodes"]):
        node["activation"] = .78 if node["id"] == target else .04 + .08 * (.5 + .5 * math.sin(index * 1.7))
    return NATIVE.validate_snapshot(state)


def labelled(frame, title, subtitle, scale):
    image = NATIVE.QtGui.QImage(frame.width(), frame.height() + round(55 * scale), NATIVE.QtGui.QImage.Format_ARGB32)
    image.fill(NATIVE.QtGui.QColor("#17232a"))
    painter = NATIVE.QtGui.QPainter(image)
    painter.setPen(NATIVE.QtGui.QColor("#d5eee6"))
    painter.setFont(NATIVE.QtGui.QFont("Sans Serif", round(10 * scale)))
    painter.drawText(round(16 * scale), round(24 * scale), title)
    painter.setPen(NATIVE.QtGui.QColor("#83a59f"))
    painter.setFont(NATIVE.QtGui.QFont("Sans Serif", round(7 * scale)))
    painter.drawText(round(16 * scale), round(43 * scale), subtitle)
    painter.drawImage(0, round(55 * scale), frame)
    painter.end()
    return image


def run(output, fps, scale, video):
    output.mkdir(parents=True, exist_ok=True)
    app = NATIVE.QtWidgets.QApplication.instance() or NATIVE.QtWidgets.QApplication([])
    base = Organism(seed=814, now=1000.).state()
    frame_times = []
    stills = []
    with tempfile.TemporaryDirectory(prefix="terminus-motion-study-") as temporary:
        client = NATIVE.CoreClient("http://127.0.0.1:1", Path(temporary))
        widget = NATIVE.Overlay(client, ROOT / "web" / "assets", scale)
        widget.animation.stop()
        widget.asset_timer.stop()
        widget.presence_timer.stop()
        widget.reduced_motion = False
        widget.roaming_paused = True
        widget.status_until = 0
        clock = widget.started

        def render(scene, elapsed, timeline):
            kind, behavior, duration, target = scene
            state = fixture(base, kind, behavior, duration, target, elapsed)
            widget.state = state
            widget.connected = True
            widget.last_seen = clock + timeline
            widget.sleep_blend = 1. if behavior in {"sleep", "dream"} else (.3 if kind == "curl" else 0.)
            if kind == "signal":
                widget.glyph_sequence, widget.glyph_started = [1, 10, 19], clock + timeline - elapsed
            else:
                widget.glyph_sequence = []
            widget.render_frame(clock + timeline)
            frame_times.append(widget.render_ms)
            return labelled(widget.frame, "Controlled gesture fixture · " + kind,
                            "Native renderer / no live state or desktop capture", scale)

        for index, scene in enumerate(SCENES):
            phase = .25 if scene[0] == "blink" else .5
            image = render(scene, scene[2] * phase, index * 10 + scene[2] * phase)
            image.save(str(output / (scene[0] + ".png")))
            stills.append(image)
        sheet = NATIVE.QtGui.QImage(stills[0].width() * 2, stills[0].height() * 5, NATIVE.QtGui.QImage.Format_ARGB32)
        sheet.fill(NATIVE.QtGui.QColor("#17232a"))
        painter = NATIVE.QtGui.QPainter(sheet)
        for index, image in enumerate(stills):
            painter.drawImage((index % 2) * image.width(), (index // 2) * image.height(), image)
        painter.end()
        sheet.save(str(output / "contact-sheet.png"))

        total_frames = 0
        if video and shutil.which("ffmpeg"):
            frames = Path(temporary) / "frames"
            frames.mkdir()
            timeline = 0.
            for scene in SCENES:
                count = math.ceil(scene[2] * fps)
                for index in range(count):
                    elapsed = min(scene[2] - .001, index / fps)
                    image = render(scene, elapsed, timeline + elapsed)
                    image.save(str(frames / f"frame-{total_frames:05d}.png"))
                    total_frames += 1
                timeline += scene[2]
            common = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(fps),
                      "-i", str(frames / "frame-%05d.png")]
            subprocess.run(common + ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset", "medium",
                                     "-crf", "19", "-pix_fmt", "yuv420p", str(output / "controlled-motion.mp4")], check=True)
            subprocess.run(common + ["-filter_complex", "split[a][b];[a]palettegen=max_colors=192[p];[b][p]paletteuse=dither=bayer:bayer_scale=3",
                                     "-loop", "0", str(output / "controlled-motion.gif")], check=True)
        widget.close()
        app.processEvents()

    report = {"scope": "controlled renderer fixtures, not autonomous runtime evidence", "live_state_accessed": False,
              "screen_or_apps_captured": False, "seed": 814, "renderer": "desktop/overlay.py", "scale": scale,
              "fps": fps if total_frames else None, "frames": total_frames,
              "duration_seconds": round(total_frames / fps, 3) if total_frames else None,
              "render_ms_median": round(statistics.median(frame_times), 3),
              "render_ms_p95": round(sorted(frame_times)[min(len(frame_times) - 1, int(len(frame_times) * .95))], 3),
              "scenes": [{"gesture": kind, "behavior": behavior, "duration": duration, "target_id": target}
                         for kind, behavior, duration, target in SCENES]}
    (output / "provenance.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "work" / "native-study")
    parser.add_argument("--fps", type=int, default=18)
    parser.add_argument("--scale", type=float, default=1.3)
    parser.add_argument("--stills-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.fps <= 60 or not math.isfinite(args.scale) or not .65 <= args.scale <= 2:
        parser.error("Use --fps 1..60 and --scale .65..2")
    run(args.output_dir.resolve(), args.fps, args.scale, not args.stills_only)
