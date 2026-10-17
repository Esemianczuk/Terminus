#!/usr/bin/env python3
"""Offline, bounded sprite/eye/optical-flow packing. Never run in the pet loop.

Needs Pillow, NumPy and OpenCV. Original GIFs and eye registrations remain the
source of truth. The runtime needs only Qt and the generated PNG/QSB assets.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageSequence

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "web/assets/clips"
OUTPUT = ROOT / "web/assets/gpu"
WIDTH, HEIGHT = 384, 416
FLOW_WIDTH, FLOW_HEIGHT = 96, 104
MAX_FLOW_PIXELS = 64.0
PAD, COLUMNS = 2, 4


def pack(frames, width, height, background=(0,0,0,0)):
    """Two transparent/replicated gutter pixels isolate bilinear atlas taps."""
    rows = math.ceil(len(frames) / COLUMNS)
    tile_w, tile_h = width + PAD * 2, height + PAD * 2
    atlas = Image.new("RGBA", (COLUMNS * tile_w, rows * tile_h), background)
    rects = []
    for index, frame in enumerate(frames):
        x, y = index % COLUMNS * tile_w + PAD, index // COLUMNS * tile_h + PAD
        # Replicate edges: data textures must retain exactly encoded zero flow.
        gutter = np.pad(np.asarray(frame), ((PAD, PAD), (PAD, PAD), (0, 0)), mode="edge")
        atlas.paste(Image.fromarray(gutter), (x - PAD, y - PAD))
        rects.append([x / atlas.width, y / atlas.height, width / atlas.width, height / atlas.height])
    return atlas, rects


def influence(polygons):
    mask = Image.new("L", (WIDTH, HEIGHT))
    painter = ImageDraw.Draw(mask)
    for polygon in polygons:
        painter.polygon([(x * WIDTH, y * HEIGHT) for x, y in polygon], fill=255)
    # A larger-than-CPU guard protects rims even after low-resolution sampling.
    guard = mask.filter(ImageFilter.MaxFilter(17))
    soft = guard.filter(ImageFilter.GaussianBlur(4))
    protected = np.maximum(np.asarray(guard), np.asarray(soft))
    allowed = Image.fromarray(255 - protected).resize((FLOW_WIDTH, FLOW_HEIGHT), Image.Resampling.BILINEAR)
    return np.asarray(allowed)


def feature(image):
    rgba = np.asarray(image.resize((FLOW_WIDTH, FLOW_HEIGHT), Image.Resampling.LANCZOS), dtype=np.float32)
    alpha = rgba[:, :, 3] / 255
    gray = (rgba[:, :, :3] @ np.array([.2126, .7152, .0722], np.float32)) * alpha
    return np.clip(gray * .65 + alpha * 80, 0, 255).astype(np.uint8)


def encode(flow, third):
    scale = np.array([WIDTH / FLOW_WIDTH, HEIGHT / FLOW_HEIGHT], np.float32)
    actual = np.clip(flow * scale, -MAX_FLOW_PIXELS, MAX_FLOW_PIXELS)
    encoded = np.empty((FLOW_HEIGHT, FLOW_WIDTH, 4), np.uint8)
    encoded[:, :, :2] = np.rint(actual / MAX_FLOW_PIXELS * 127 + 128).astype(np.uint8)
    encoded[:, :, 2] = third
    # Qt image sources premultiply RGB by alpha. Data alpha is always opaque.
    encoded[:, :, 3] = 255
    return Image.fromarray(encoded)


def build():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((SOURCE / "manifest.json").read_text())
    eyes = json.loads((SOURCE / "skin-atlas.json").read_text())
    result = {"version": 1, "canvas": [WIDTH, HEIGHT], "flow_canvas": [FLOW_WIDTH, FLOW_HEIGHT],
              "max_flow_pixels": MAX_FLOW_PIXELS, "method": "offline bidirectional DIS; GPU backward advection", "clips": {}}
    cv2.setNumThreads(1)
    for name, entry in manifest["clips"].items():
        path = SOURCE / entry["file"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        registered = eyes["clips"][name]
        if registered["sha256"] != digest:
            raise ValueError(f"{name}: eye registration does not match the artwork")
        with Image.open(path) as gif:
            frames = [frame.convert("RGBA") for frame in ImageSequence.Iterator(gif)]
            delays = [max(20, min(1000, frame.info.get("duration", 100))) for frame in ImageSequence.Iterator(gif)]
        if len(frames) != len(registered["eyes"]) or len(frames) > 32:
            raise ValueError(f"{name}: invalid bounded frame registration")
        features = [feature(frame) for frame in frames]
        forward, backward, metrics = [], [], []
        for index, first in enumerate(features):
            following = (index + 1) % len(frames) if entry["loop"] else min(index + 1, len(frames) - 1)
            second = features[following]
            estimator = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
            estimator.setUseSpatialPropagation(True)
            fwd = estimator.calc(first, second, None)
            bwd = estimator.calc(second, first, None)
            # Consistency attenuates unreliable warps instead of flinging limbs.
            yy, xx = np.mgrid[:FLOW_HEIGHT, :FLOW_WIDTH].astype(np.float32)
            reverse = cv2.remap(bwd, xx + fwd[:, :, 0], yy + fwd[:, :, 1], cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_REPLICATE)
            error = np.linalg.norm(fwd + reverse, axis=2)
            confidence = np.rint(np.clip(1 - error / 3.0, 0, 1) * 255).astype(np.uint8)
            forward.append(encode(fwd, influence(registered["eyes"][index])))
            backward.append(encode(bwd, confidence))
            metrics.append(round(float(np.percentile(np.linalg.norm(fwd, axis=2) * 4, 99)), 3))
        body, rects = pack(frames, WIDTH, HEIGHT)
        flow_a, flow_rects = pack(forward, FLOW_WIDTH, FLOW_HEIGHT, (128,128,255,255))
        flow_b, _ = pack(backward, FLOW_WIDTH, FLOW_HEIGHT, (128,128,255,255))
        for suffix, atlas in (("body", body), ("forward", flow_a), ("backward", flow_b)):
            atlas.save(OUTPUT / f"{name}-{suffix}.png", optimize=True)
        result["clips"][name] = {"sha256": digest, "count": len(frames), "loop": entry["loop"],
                                 "delays_ms": delays, "body_rects": rects, "flow_rects": flow_rects,
                                 "flow_p99_pixels": metrics,
                                 "texture_bytes": body.width * body.height * 4 + flow_a.width * flow_a.height * 8}
    # A single shared glow texture replaces per-frame radial gradient images.
    yy, xx = np.mgrid[-1:1:64j, -1:1:64j]
    alpha = np.clip(1 - np.hypot(xx, yy), 0, 1) ** 2.3
    glow = np.empty((64, 64, 4), np.uint8)
    glow[:, :, :3] = [118, 243, 219]
    glow[:, :, 3] = np.rint(alpha * 255).astype(np.uint8)
    Image.fromarray(glow).save(OUTPUT / "glow.png")
    (OUTPUT / "manifest.json").write_text(json.dumps(result, separators=(",", ":")) + "\n")
    print(json.dumps({"clips": len(result["clips"]), "frames": sum(c["count"] for c in result["clips"].values()),
                      "largest_resident_clip_bytes": max(c["texture_bytes"] for c in result["clips"].values()),
                      "compressed_bytes": sum(p.stat().st_size for p in OUTPUT.glob("*.png"))}))


if __name__ == "__main__":
    build()
