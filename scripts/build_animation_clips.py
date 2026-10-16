#!/usr/bin/env python3
"""Author registered transparent GIF clips offline from the approved body art.

Run with a Python containing PyQt5 and Pillow (the workstation's /usr/bin/python3
has both), or: uv run --with Pillow python scripts/build_animation_clips.py
No model, GPU, network service, live organism or screen capture is involved.
The body renderer consumes these discrete frames; this rig is an asset tool.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtCore, QtGui, QtWidgets
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 384, 416
SAFETY_SCALE = .90
SOURCES = {name: ROOT / "web/assets" / ("terminus-" + name + ".png")
           for name in ("refined", "sleep", "flight", "typing", "stretch", "yawn")}
# Frame duration is a GIF-native multiple of ten milliseconds. The shared
# canvas and roots keep the body and live graph registered across states.
SPECS = {"idle": (24, 130, True), "moving": (16, 80, True),
         "sleep": (16, 200, True), "typing": (12, 100, True),
         "takeoff": (6, 80, False), "landing": (8, 80, False),
         "turn": (7, 60, False), "wake": (8, 80, False),
         "poke": (6, 70, False), "sleep-in": (8, 80, False),
         "stretch": (10, 100, False), "yawn": (10, 100, False)}


def ease(value):
    value = max(0., min(1., value))
    return value * value * (3 - 2 * value)


def wave(value):
    return math.sin(2 * math.pi * value)


class FrameAuthor:
    def __init__(self):
        self.art = {name: QtGui.QPixmap(str(path)) for name, path in SOURCES.items()}
        if any(image.isNull() for image in self.art.values()):
            raise ValueError("All approved source PNG poses are required")

    def render(self, name, index, count):
        phase = index / count if SPECS[name][2] else 0.
        progress = index / max(1, count - 1)
        source, lid = "refined", 0.
        breath, arms, flight, tap = wave(phase), .45, 0., 0.
        tilt, lift, squash, stretch, curl = 0., 0., 1., 0., 0.
        if name == "idle":
            # One short eyelid closure in an otherwise settled multi-second
            # loop. The face uses registered art, rather than distorting eyes.
            lid = max(0., 1 - abs(phase - .70) / .055)
            tilt = .8 * wave(phase)
        elif name == "moving":
            source, arms, flight = "flight", 1., 1.
            tilt, lift = 1.8 * wave(phase), 2.5 * wave(phase)
        elif name == "sleep":
            source, arms, breath = "sleep", .17, wave(phase)
            curl = .18
        elif name == "typing":
            source, arms, tap = "typing", .3, 1.
            tilt = .7 * wave(phase)
        elif name == "takeoff":
            # Anticipate, lift, then adopt the swimming silhouette. A brief
            # narrow pose at the key change avoids translucent double limbs.
            source = "refined" if progress < .5 else "flight"
            squash = 1 - .13 * math.sin(math.pi * progress)
            flight = ease(progress)
            lift, arms = 7 * math.sin(math.pi * progress), .45 + .55 * flight
            curl = .18 * math.sin(math.pi * progress)
        elif name == "landing":
            source = "flight" if progress < .5 else "refined"
            flight = 1 - ease(progress)
            lift, arms = -2 * math.sin(math.pi * progress), .45 + .55 * flight
            squash = 1 - .10 * math.sin(math.pi * progress)
        elif name == "turn":
            # Both ends have the same canonical orientation. ClipPlayer flips
            # the frame once at the narrow middle, never the graph or glyphs.
            squash = .28 + .72 * abs(math.cos(math.pi * progress))
            lift, arms = 2 * math.sin(math.pi * progress), .45
        elif name in {"wake", "sleep-in"}:
            wake = progress if name == "wake" else 1 - progress
            source = "sleep" if wake < .5 else "refined"
            curl, arms = .18 * (1 - wake), .17 + .28 * wake
            lift = 2 * math.sin(math.pi * progress)
        elif name == "poke":
            bump = math.sin(math.pi * progress) * math.exp(-progress * 1.7)
            lid = 1. if .16 < progress < .42 else 0.
            squash, lift, tilt = 1 + .07 * bump, 5 * bump, -3 * bump
            arms = .6
        elif name in {"stretch", "yawn"}:
            # Discrete anticipation/held key/recovery frames, with no alpha
            # dissolve. The exact approved expression is retained throughout.
            source = name if .18 <= progress <= .82 else "refined"
            stretch = math.sin(math.pi * progress) * (.25 if name == "stretch" else .05)
            tilt = 1.5 * math.sin(math.pi * progress)
            arms = .45
        canvas = QtGui.QImage(WIDTH, HEIGHT, QtGui.QImage.Format_ARGB32)
        canvas.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(canvas)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        # Every state shares this safety margin; fins and extended arm tips
        # cannot be clipped by an animation frame boundary.
        painter.translate(WIDTH * .5, HEIGHT * .5)
        painter.scale(SAFETY_SCALE, SAFETY_SCALE)
        painter.translate(-WIDTH * .5, -HEIGHT * .5)
        painter.translate(WIDTH * .5, HEIGHT * .73 - lift)
        painter.rotate(tilt)
        painter.scale(squash, 1. if name == "turn" else 1 / math.sqrt(squash))
        painter.translate(-WIDTH * .5, -HEIGHT * .73)

        def vertex(u, v):
            mantle = 1 - ease((v - .38) / .28)
            lower = ease((v - .46) / .49)
            fin = max(0., 1 - abs(v - .42) / .20) * abs(u - .5) * 2
            x = u + .010 * breath * (u - .5) * mantle
            y = v - .004 * breath * (1 - v) * mantle
            # Independent fin beat and alternating travelling arm ripples;
            # the facial plane stays registered and nearly rigid.
            x += fin * .008 * wave(phase + .1) * (1 if u > .5 else -1)
            y += fin * .007 * wave(phase + .2)
            x += lower * .016 * math.sin(phase * math.tau - v * 5 + u * 5) * arms
            y += lower * .012 * math.sin(phase * math.tau + u * 7 - v * 3) * arms
            x -= lower * .018 * flight * math.sin(phase * math.tau + v * 4)
            y += lower * .008 * flight * math.sin(phase * math.tau * 2 + u * 4)
            y += lower * .022 * tap * math.sin(phase * math.tau * 2 + u * 10)
            x += lower * (u - .5) * (.15 * stretch - .09 * curl)
            y -= lower * .025 * curl
            return QtCore.QPointF(x * WIDTH, y * HEIGHT)

        def layer(texture, opacity=1.):
            painter.setOpacity(opacity)
            columns, rows = 4, 10
            points = [[vertex(c / columns, r / rows) for c in range(columns + 1)] for r in range(rows + 1)]
            for r in range(rows):
                for c in range(columns):
                    box = QtCore.QRectF(c * texture.width() / columns, r * texture.height() / rows,
                                       texture.width() / columns, texture.height() / rows)
                    src = QtGui.QPolygonF([box.topLeft(), box.topRight(), box.bottomRight(), box.bottomLeft()])
                    dst = QtGui.QPolygonF([points[r][c], points[r][c + 1], points[r + 1][c + 1], points[r + 1][c]])
                    transform = QtGui.QTransform()
                    if QtGui.QTransform.quadToQuad(src, dst, transform):
                        painter.save(); painter.setTransform(transform, True)
                        patch = box.adjusted(-.25, -.25, .25, .25).intersected(QtCore.QRectF(texture.rect()))
                        painter.drawPixmap(patch, texture, patch); painter.restore()

        layer(self.art[source])
        if lid > 0 and source == "refined":
            # The matching sleep asset changes the eyelids alone. This is an
            # authored blink frame, not a runtime pose crossfade.
            layer(self.art["sleep"], lid)
        painter.end()
        buffer = QtCore.QBuffer(); buffer.open(QtCore.QIODevice.WriteOnly)
        canvas.save(buffer, "PNG")
        return Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA")


def encode(frames, path, delay, loop):
    # One fixed palette per clip, with index 255 reserved for transparency.
    # No temporal error diffusion: spots and glow do not shimmer between frames.
    thumbnail_strip = Image.new("RGB", (WIDTH, HEIGHT * len(frames)))
    for index, frame in enumerate(frames):
        thumbnail_strip.paste(frame.convert("RGB"), (0, HEIGHT * index))
    palette = thumbnail_strip.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    # A unique reserved color prevents opaque near-black eye pixels from being
    # quantized to the transparent index by a duplicate black palette entry.
    palette.putpalette((palette.getpalette()[:765] + [255, 0, 255]))
    indexed = []
    for frame in frames:
        result = frame.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE)
        alpha = frame.getchannel("A").point(lambda value: 255 if value < 96 else 0)
        result.paste(255, mask=alpha)
        result.info["transparency"] = 255
        indexed.append(result)
    kwargs = {"save_all": True, "append_images": indexed[1:], "duration": delay,
              "disposal": 2, "transparency": 255, "optimize": False}
    if loop:
        kwargs["loop"] = 0
    indexed[0].save(path, **kwargs)


def build(output):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    author = FrameAuthor()
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"version": 1, "canvas": [WIDTH, HEIGHT], "clips": {}}
    proof = {"method": "offline CPU key-pose and appendage frame authoring", "live_state_accessed": False,
             "gpu_used": False, "runtime_mesh": False, "sources": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCES.values()}, "clips": {}}
    for name, (count, delay, loop) in SPECS.items():
        frames = [author.render(name, index, count) for index in range(count)]
        path = output / (name + ".gif")
        encode(frames, path, delay, loop)
        anchors = {"left": [.34, .64 if name in {"moving", "takeoff", "landing"} else .75],
                   "right": [.66, .64 if name in {"moving", "takeoff", "landing"} else .75], "center": [.5, .69]}
        if name == "turn":
            anchors.update(left=[.46, .75], right=[.54, .75])
        anchors = {key: [.5 + (u - .5) * SAFETY_SCALE, .5 + (v - .5) * SAFETY_SCALE]
                   for key, (u, v) in anchors.items()}
        manifest["clips"][name] = {"file": path.name, "loop": loop, "anchors": anchors}
        with Image.open(path) as decoded:
            durations, hashes = [], []
            for index in range(decoded.n_frames):
                decoded.seek(index); durations.append(decoded.info.get("duration", 0)); hashes.append(hashlib.sha256(decoded.convert("RGBA").tobytes()).hexdigest())
        if len(hashes) < 2 or len(set(hashes)) < 2:
            raise ValueError(f"{name} must contain distinct real animation frames")
        proof["clips"][name] = {"frames": len(hashes), "distinct_frames": len(set(hashes)), "duration_ms": sum(durations),
                                "delays_ms": durations, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "provenance.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps({"output": str(output), "clips": len(SPECS), "frames": sum(p["frames"] for p in proof["clips"].values()),
                      "bytes": sum(p["bytes"] for p in proof["clips"].values())}, indent=2))
    app.quit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "web/assets/clips")
    build(parser.parse_args().output_dir.resolve())
