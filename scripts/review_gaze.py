#!/usr/bin/env python3
"""Reproduce native eye-material visual checks without observing a desktop.

Writes native and magnified contact sheets, a 30fps controlled gaze preview,
and pixel-integrity/performance evidence for every registered animation frame.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if "--gpu-parity" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PySide6 import QtGui, QtWidgets

from desktop.animation import ClipLibrary
from desktop.gaze import GazeAtlas, GazeController, compose_eye_layers


BACKGROUND = (23, 31, 38, 255)
DIRECTIONS = (
    ("neutral", (0., 0., 0., 0.)),
    ("left", (-3.6, 0., -3.6, 0.)),
    ("right", (3.6, 0., 3.6, 0.)),
    ("up", (0., -2.5, 0., -2.5)),
    ("down", (0., 2.5, 0., 2.5)),
)
FIXTURES = (("idle", 0), ("idle", 16), ("idle", 17), ("idle", 18),
            ("moving", 0), ("typing", 3), ("stretch", 5),
            ("turn", 2), ("turn", 3), ("turn", 4))


def pixels(image):
    """Compare the exact premultiplied representation used by compositing."""
    converted = image.convertToFormat(QtGui.QImage.Format_RGBA8888_Premultiplied)
    return np.frombuffer(converted.constBits(), np.uint8).reshape(
        converted.height(), converted.bytesPerLine())[:, :converted.width()*4].reshape(
            converted.height(), converted.width(), 4).copy()


def pil(image):
    converted = image.convertToFormat(QtGui.QImage.Format_RGBA8888)
    values = np.frombuffer(converted.constBits(), np.uint8).reshape(
        converted.height(), converted.bytesPerLine())[:, :converted.width()*4].reshape(
            converted.height(), converted.width(), 4)
    return Image.fromarray(values.copy(), "RGBA")


def font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/System/Library/Fonts/Supplemental/Arial.ttf"):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def crop_bounds(materials, canvas):
    left = min(material.bounds[0] for material in materials)-8
    top = min(material.bounds[1] for material in materials)-8
    right = max(material.bounds[0]+material.bounds[2] for material in materials)+8
    bottom = max(material.bounds[1]+material.bounds[3] for material in materials)+8
    return (max(0, left), max(0, top), min(canvas[0], right), min(canvas[1], bottom))


def aperture_mask(materials, canvas):
    result = np.zeros((canvas[1], canvas[0]), dtype=bool)
    for material in materials:
        x, y, width, height = material.bounds
        left, top = max(0, x), max(0, y)
        right, bottom = min(canvas[0], x+width), min(canvas[1], y+height)
        if right > left and bottom > top:
            result[top:bottom, left:right] |= material.aperture[
                top-y:bottom-y, left-x:right-x] > 0
    return result


def contact_sheets(library, atlas, output):
    native_cell = (384, 450)
    zoom_cell = (450, 230)
    native = Image.new("RGBA", (native_cell[0]*5, native_cell[1]*len(FIXTURES)), BACKGROUND)
    zoom = Image.new("RGBA", (zoom_cell[0]*5, zoom_cell[1]*len(FIXTURES)), BACKGROUND)
    native_draw, zoom_draw = ImageDraw.Draw(native), ImageDraw.Draw(zoom)
    label = font(16)
    for row, (clip, index) in enumerate(FIXTURES):
        image = library.clips[clip].frames[index]
        materials = atlas.frame(clip, index)
        bounds = crop_bounds(materials, library.canvas)
        for col, (name, canonical) in enumerate(DIRECTIONS):
            changed = compose_eye_layers(image, materials, atlas.displacements(clip, index, canonical))
            authored = pil(changed)
            native.alpha_composite(authored, (col*native_cell[0], row*native_cell[1]+28))
            native_draw.text((col*native_cell[0]+12, row*native_cell[1]+6),
                             f"{clip} {index:02d} / {name}", font=label, fill="#d5eae7")
            detail = authored.crop(bounds)
            factor = min((zoom_cell[0]-16)/detail.width, (zoom_cell[1]-42)/detail.height)
            detail = detail.resize((round(detail.width*factor), round(detail.height*factor)), Image.Resampling.LANCZOS)
            zoom.alpha_composite(detail, (col*zoom_cell[0]+8, row*zoom_cell[1]+34))
            zoom_draw.text((col*zoom_cell[0]+12, row*zoom_cell[1]+7),
                           f"{clip} {index:02d} / {name}", font=label, fill="#d5eae7")
    native.convert("RGB").save(output/"native-contact-sheet.png")
    zoom.convert("RGB").save(output/"eye-contact-sheet.png")


def preview(library, atlas, path):
    """Use real GIF timings for the body and the production gaze controller."""
    idle = library.clips["idle"]
    duration = max(8., idle.duration_ms/1000*2)
    count = math.ceil(duration*30)
    gaze = GazeController("controlled-gaze-review")
    frames = []
    label = font(14)
    gaze_modes = set()
    body = (0., 0., 384., 416.)
    screen = (-800., -600., 2000., 1600.)
    bounds = crop_bounds(atlas.frame("idle", 0), library.canvas)
    for step in range(count):
        now = step/30
        index, _ = idle.frame_at(now)
        # Continuous targets alternate distant pursuit, near convergence and a
        # quiet hold. No source artwork is repainted or animation frame added.
        cycle = now/duration
        if cycle < .70:
            angle = cycle/.70*math.tau
            target = (214.+650.*math.cos(angle), 159.+380.*math.sin(angle))
        elif cycle < .86:
            target = (225., 166.)
        else:
            target = (820., 115.)
        pointer = ((target[0]-screen[0])/screen[2], (target[1]-screen[1])/screen[3], 1. if step == 0 else 0.)
        canonical = gaze.update(now, body=body, screen=screen, pointer=pointer,
                                eye_centres=atlas.centres("idle", index))
        gaze_modes.add(gaze.mode)
        changed = compose_eye_layers(idle.frames[index], atlas.frame("idle", index),
                                     atlas.displacements("idle", index, canonical))
        authored = pil(changed)
        frame = Image.new("RGBA", (744, 450), BACKGROUND)
        frame.alpha_composite(authored, (0, 25))
        detail = authored.crop(bounds)
        factor = min(340/detail.width, 240/detail.height)
        detail = detail.resize((round(detail.width*factor), round(detail.height*factor)), Image.Resampling.LANCZOS)
        frame.alpha_composite(detail, (394, 94))
        draw = ImageDraw.Draw(frame)
        draw.text((14, 8), "Terminus / original clip + rigid iris layers", font=label, fill="#d5eae7")
        draw.text((394, 54), "Eye detail", font=label, fill="#d5eae7")
        draw.text((394, 351), f"{gaze.mode} / idle frame {index:02d}", font=label, fill="#9bb9b5")
        draw.text((394, 375), "30 fps gaze / original body frame clock", font=font(12), fill="#9bb9b5")
        frames.append(frame.convert("RGB"))
    # A single palette prevents GIF re-quantization from flickering between
    # frames. GIF timings are centiseconds, so 30/30/40ms repeats preserve 30 fps.
    palette_source = Image.new("RGB", (744, 450*min(12, len(frames))))
    for row, frame in enumerate(frames[::max(1, len(frames)//12)][:12]):
        palette_source.paste(frame, (0, row*450))
    palette = palette_source.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    indexed = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    path.parent.mkdir(parents=True, exist_ok=True)
    indexed[0].save(path, save_all=True, append_images=indexed[1:], loop=0, optimize=False,
                    duration=[(30, 30, 40)[index%3] for index in range(count)], disposal=1)
    optimizer=shutil.which('gifsicle')
    if optimizer:
        temporary=path.with_suffix('.optimized.gif')
        try:
            subprocess.run([optimizer,'-O3',str(path),'-o',str(temporary)],check=True,capture_output=True)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return {"path": str(path), "frames": count, "render_fps": 30,
            "file_bytes":path.stat().st_size,
            "gif_timing_ms": [30, 30, 40], "duration_seconds": round(count/30, 3),
            "body_clock": "original idle GIF frame durations", "controller_modes": sorted(gaze_modes)}


def gpu_parity(library, atlas, output):
    """Compare the optional hardware renderer's own framebuffer with raster.

    Requires a hardware-capable Qt platform and a 1x physical render surface.
    No desktop screenshot, observer, service or input interception is involved.
    """
    from PySide6 import QtCore, QtTest
    from desktop.gpu import GpuScene

    result = {"requested": True, "available": False, "verified": False,
              "backend": None, "errors": [], "cases": [], "threshold_rgb_lsb": 2}
    flags = (QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint
             | QtCore.Qt.WindowDoesNotAcceptFocus | QtCore.Qt.WindowTransparentForInput)
    parent = QtWidgets.QWidget(None, flags)
    parent.setAttribute(QtCore.Qt.WA_TranslucentBackground)
    parent.resize(440, 476)
    view = GpuScene(parent)
    view.setGeometry(parent.rect())
    try:
        if not view.available:
            result["errors"] = list(view.errors)
            return result
        parent.show()
        QtTest.QTest.qWait(200)
        diagnostics = view.diagnostics()
        result["backend"] = diagnostics["graphics_api"]
        result["device_pixel_ratio"] = view.devicePixelRatioF()
        if not view.available:
            result["errors"] = list(view.errors)
            return result
        if abs(view.devicePixelRatioF()-1.) > .001:
            result["errors"] = ["Exact pixel parity requires a 1x render surface; set QT_SCALE_FACTOR=1 and QT_AUTO_SCREEN_SCALE_FACTOR=0."]
            return result
        result["available"] = True
        fixtures = (("idle", 0), ("idle", 16), ("idle", 17), ("moving", 0),
                    ("typing", 3), ("stretch", 5), ("turn", 3))
        shifts = ((0.,)*4, (3.6, 2.5, 3.6, 2.5), (-3.6, -2.5, -3.6, -2.5))
        for clip, index in fixtures:
            materials = atlas.frame(clip, index)
            mask = aperture_mask(materials, library.canvas)
            eye_bounds = np.zeros_like(mask)
            for material in materials:
                x, y, width, height = material.bounds
                left, top, right, bottom = max(0, x), max(0, y), min(384, x+width), min(416, y+height)
                if right > left and bottom > top:
                    eye_bounds[top:bottom, left:right] = True
            for shift in shifts:
                view.set_scene(clip=clip, index=index, phase=0., body_rect=(0, 0, 384, 416),
                               skin_intensity=0., morph_strength=0., gaze_atlas=atlas, gaze_shift=shift)
                QtTest.QTest.qWait(100)
                framebuffer = view.grabFramebuffer()
                gpu = pixels(framebuffer)[:416, :384]
                cpu_image = compose_eye_layers(library.clips[clip].frames[index], materials,
                                               atlas.displacements(clip, index, shift))
                cpu = pixels(cpu_image)
                if gpu.shape != cpu.shape:
                    result["errors"].append(f"Unexpected framebuffer size: {gpu.shape}; expected {cpu.shape}")
                    return result
                delta = np.abs(cpu.astype(np.int16)-gpu.astype(np.int16))
                eye_rgb = delta[mask, :3]
                maximum = int(eye_rgb.max()) if eye_rgb.size else 0
                bounds_maximum = int(delta[eye_bounds, :3].max()) if eye_bounds.any() else 0
                case = {"clip": clip, "frame": index, "canonical_shift": list(shift),
                        "eye_rgb_mean": round(float(eye_rgb.mean()), 5) if eye_rgb.size else 0.,
                        "eye_rgb_p99": round(float(np.percentile(eye_rgb, 99)), 5) if eye_rgb.size else 0.,
                        "eye_rgb_maximum": maximum,
                        "eye_bounds_rgb_maximum": bounds_maximum,
                        "eye_alpha_maximum": int(delta[mask, 3].max()) if mask.any() else 0,
                        "passed": max(maximum, bounds_maximum) <= 2}
                result["cases"].append(case)
                if clip == "idle" and index == 0 and shift[0] > 0:
                    framebuffer.save(str(output/"gpu-reference.png"))
                    cpu_image.save(str(output/"raster-reference.png"))
        result["errors"] = list(view.errors)
        result["maximum_rgb_difference"] = max(case["eye_rgb_maximum"] for case in result["cases"])
        result["verified"] = not result["errors"] and all(case["passed"] for case in result["cases"])
        return result
    finally:
        parent.close()
        parent.deleteLater()
        QtWidgets.QApplication.processEvents()


def run(output, preview_path=None, check_gpu=False):
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    output.mkdir(parents=True, exist_ok=True)
    library = ClipLibrary.from_manifest(ROOT/"web/assets/clips/manifest.json")
    atlas = GazeAtlas(ROOT/"web/assets/gaze/manifest.json", library)
    if library.errors or atlas.errors:
        raise ValueError({"clips": dict(library.errors), "eyes": atlas.errors})
    timings = []
    report = {"scope": "controlled source-art fixtures using the native raster compositor",
              "live_state_accessed": False, "desktop_or_external_apps_captured": False,
              "registered_clips": len(library.clips), "registered_frames": 0,
              "direction_samples": 0, "neutral_identity": True, "alpha_unchanged": True,
              "outside_aperture_unchanged": True, "closed_frames_unchanged": True,
              "maximum_outside_changed_pixels": 0, "maximum_alpha_changed_pixels": 0,
              "changed_pixels_max": 0, "failures": []}
    for clip_name, clip in library.clips.items():
        for index, original in enumerate(clip.frames):
            materials = atlas.frame(clip_name, index)
            if materials is None or len(materials) != 2:
                raise ValueError(f"Missing eye pair: {clip_name} {index}")
            before = pixels(original)
            aperture = aperture_mask(materials, library.canvas)
            report["registered_frames"] += 1
            for name, canonical in DIRECTIONS:
                displacement = atlas.displacements(clip_name, index, canonical)
                started = time.perf_counter()
                changed = compose_eye_layers(original, materials, displacement)
                timings.append((time.perf_counter()-started)*1000)
                after = pixels(changed)
                differences = np.any(before != after, axis=2)
                outside = int(np.count_nonzero(differences & ~aperture))
                alpha = int(np.count_nonzero(before[:, :, 3] != after[:, :, 3]))
                report["maximum_outside_changed_pixels"] = max(report["maximum_outside_changed_pixels"], outside)
                report["maximum_alpha_changed_pixels"] = max(report["maximum_alpha_changed_pixels"], alpha)
                report["changed_pixels_max"] = max(report["changed_pixels_max"], int(differences.sum()))
                report["direction_samples"] += 1
                neutral_ok = name != "neutral" or not differences.any()
                closed_ok = aperture.any() or not differences.any()
                report["neutral_identity"] &= bool(neutral_ok)
                report["alpha_unchanged"] &= alpha == 0
                report["outside_aperture_unchanged"] &= outside == 0
                report["closed_frames_unchanged"] &= bool(closed_ok)
                if outside or alpha or not neutral_ok or not closed_ok:
                    report["failures"].append({"clip": clip_name, "frame": index, "direction": name,
                                                "outside": outside, "alpha": alpha,
                                                "neutral": bool(neutral_ok), "closed": bool(closed_ok)})
    report["compositor_ms"] = {"median": round(float(np.median(timings)), 4),
                                "p95": round(float(np.quantile(timings, .95)), 4),
                                "samples": len(timings), "includes_neutral_fast_path": True}
    contact_sheets(library, atlas, output)
    report["preview"] = preview(library, atlas, (preview_path or output/"eye-gaze.gif").resolve())
    report["gpu_parity"] = (gpu_parity(library, atlas, output) if check_gpu
                            else {"requested": False, "available": None, "verified": False})
    report["atlas_errors"] = dict(atlas.errors)
    (output/"metrics.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))
    if report["failures"] or atlas.errors:
        raise SystemExit(1)
    if check_gpu and not report["gpu_parity"]["verified"]:
        raise SystemExit(2)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT/"work/gaze-review")
    parser.add_argument("--preview", type=Path, help="Optional destination for the shareable GIF preview")
    parser.add_argument("--gpu-parity", action="store_true",
                        help="Also verify 21 hardware/raster eye cases using an input-transparent Qt fixture")
    args = parser.parse_args()
    run(args.output_dir.resolve(), args.preview, args.gpu_parity)
