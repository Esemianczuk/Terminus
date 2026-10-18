#!/usr/bin/env python3
"""Bake iris motion fields through the approved pose rig.

The source annotations describe only the visible eye openings and iris
centres. The original pixels, including their painted highlights, are never
segmented, repainted, or re-encoded. Run after build_animation_clips.py and
before build_gpu_assets.py. This is an offline authoring step.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import cv2
import numpy as np
from PIL import Image, ImageSequence
from PySide6 import QtGui, QtWidgets

from build_animation_clips import FrameAuthor, ROOT, SOURCES, SPECS, WIDTH, HEIGHT

SOURCE = ROOT / "web/assets/clips"
OUTPUT = ROOT / "web/assets/gaze"
FIELD_WIDTH, FIELD_HEIGHT = 192, 208
PAD, COLUMNS = 2, 4

# Visible aperture outlines, once per approved source pose. Coordinates are
# normalized in source art, and travel through the exact original pose rig.
# The centres are the painted iris centres, not invented eyeball geometry.
OPENINGS = {
    "refined": (
        ((.458, .434), ((.378,.417),(.410,.408),(.465,.402),(.515,.404),(.529,.411),(.523,.422),(.501,.440),(.464,.452),(.418,.455),(.392,.444))),
        ((.688, .373), ((.640,.370),(.661,.359),(.703,.350),(.743,.349),(.750,.356),(.741,.376),(.718,.394),(.677,.401),(.651,.394))),
    ),
    "flight": (
        ((.590, .437), ((.514,.415),(.549,.409),(.608,.402),(.679,.404),(.711,.415),(.709,.428),(.682,.448),(.638,.458),(.574,.459),(.538,.450))),
        ((.839, .372), ((.804,.365),(.826,.351),(.864,.342),(.895,.338),(.897,.352),(.886,.378),(.858,.398),(.827,.404),(.810,.393))),
    ),
    "typing": (
        ((.465, .452), ((.380,.436),(.414,.425),(.468,.422),(.518,.422),(.535,.433),(.528,.447),(.504,.460),(.466,.470),(.420,.471),(.392,.459))),
        ((.692, .394), ((.644,.389),(.666,.377),(.706,.369),(.747,.368),(.756,.377),(.748,.396),(.724,.415),(.683,.421),(.657,.412))),
    ),
    "stretch": (
        ((.502, .520), ((.424,.510),(.451,.500),(.503,.489),(.559,.488),(.582,.498),(.581,.511),(.558,.527),(.518,.540),(.468,.541),(.438,.530))),
        ((.677, .465), ((.644,.462),(.659,.445),(.699,.428),(.735,.421),(.744,.429),(.741,.448),(.723,.471),(.693,.489),(.661,.486))),
    ),
}


def source_field(size, opening):
    width, height = size
    (cx, cy), polygon = opening
    aperture = np.zeros((height, width), np.uint8)
    points = np.rint(np.asarray(polygon) * [width, height]).astype(np.int32)
    cv2.fillPoly(aperture, [points], 255)
    distance = cv2.distanceTransform(aperture, cv2.DIST_L2, 3)
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    radius = np.sqrt(((xx / width - cx) / .079) ** 2 + ((yy / height - cy) / .042) ** 2)
    radial = np.clip((1.13 - radius) / .72, 0, 1)
    radial = radial * radial * (3 - 2 * radial)
    edge = np.clip((distance - 1.5) / 15, 0, 1)
    edge = edge * edge * (3 - 2 * edge)
    return np.rint(radial * edge * 255).astype(np.uint8)


def packed(frames):
    rows = (len(frames) + COLUMNS - 1) // COLUMNS
    tile_w, tile_h = FIELD_WIDTH + PAD * 2, FIELD_HEIGHT + PAD * 2
    atlas = Image.new("RGBA", (tile_w * COLUMNS, tile_h * rows), (0,0,0,255))
    rects = []
    for index, channels in enumerate(frames):
        x, y = index % COLUMNS * tile_w + PAD, index // COLUMNS * tile_h + PAD
        rgba = np.empty((FIELD_HEIGHT, FIELD_WIDTH, 4), np.uint8)
        rgba[:,:,0:2] = channels
        rgba[:,:,2] = 0
        rgba[:,:,3] = 255
        padded = np.pad(rgba, ((PAD,PAD),(PAD,PAD),(0,0)), mode="edge")
        atlas.paste(Image.fromarray(padded), (x-PAD,y-PAD))
        rects.append([x/atlas.width,y/atlas.height,FIELD_WIDTH/atlas.width,FIELD_HEIGHT/atlas.height])
    return atlas, rects


def build():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    if set(SOURCES)-set(OPENINGS)-{"sleep","yawn"}:
        raise ValueError("Every open-eye source pose needs two aperture annotations")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    author = FrameAuthor()
    source_images = {}
    for name, path in SOURCES.items():
        size = Image.open(path).size
        source_images[name] = []
        for eye in range(2):
            values = source_field(size, OPENINGS[name][eye]) if name in OPENINGS else np.zeros((size[1],size[0]),np.uint8)
            # Full opaque black source permits the existing sleep overlay to
            # attenuate the field during blink frames via painter opacity.
            rgba = np.empty((size[1],size[0],4),np.uint8)
            rgba[:,:,:3] = values[:,:,None]
            rgba[:,:,3] = 255
            image = QtGui.QImage(rgba.data,size[0],size[1],size[0]*4,QtGui.QImage.Format_RGBA8888).copy()
            source_images[name].append(QtGui.QPixmap.fromImage(image))
    manifest = {"version":1,"canvas":[WIDTH,HEIGHT],"field_canvas":[FIELD_WIDTH,FIELD_HEIGHT],
                "method":"authored aperture fields propagated through the original pose rig",
                "source_openings":OPENINGS,"sources":{name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in SOURCES.items()},
                "clips":{}}
    for name, (count, delay, _) in SPECS.items():
        channels = []
        for eye in range(2):
            author.art = {source:source_images[source][eye] for source in SOURCES}
            channels.append([np.asarray(author.render(name,index,count))[:,:,0] for index in range(count)])
        gif_path = SOURCE / f"{name}.gif"
        with Image.open(gif_path) as gif:
            durations = [max(20,min(1000,frame.info.get("duration",delay))) for frame in ImageSequence.Iterator(gif)]
        frames, centres, openness = [], [], []
        first = 0
        for duration in durations:
            end = first + duration // delay
            if end <= first or end > count:
                raise ValueError(f"{name}: GIF clock differs from pose rig")
            masks = [np.max(channel[first:end],axis=0) for channel in channels]
            # The source lid can hide the iris before it reaches full opacity.
            # Once visually closed, do not deform even a faint residual field.
            masks = [mask if mask.max() >= 90 else np.zeros_like(mask) for mask in masks]
            pair = np.stack([cv2.resize(mask,(FIELD_WIDTH,FIELD_HEIGHT),interpolation=cv2.INTER_AREA) for mask in masks],axis=-1)
            frames.append(pair)
            frame_centres, frame_open = [], []
            for mask in masks:
                maximum = int(mask.max())
                yy, xx = np.nonzero(mask >= max(32,maximum*.85))
                frame_centres.append([round(float(xx.mean()/WIDTH),6),round(float(yy.mean()/HEIGHT),6)] if len(xx) and maximum >= 32 else [0.,0.])
                frame_open.append(round(maximum/255,4))
            centres.append(frame_centres);openness.append(frame_open)
            first = end
        if first != count:raise ValueError(f"{name}: incomplete pose registration")
        atlas, rects = packed(frames)
        destination = OUTPUT / f"{name}.png"
        atlas.save(destination,optimize=True)
        manifest["clips"][name] = {"sha256":hashlib.sha256(gif_path.read_bytes()).hexdigest(),
                                    "field_sha256":hashlib.sha256(destination.read_bytes()).hexdigest(),
                                    "frames":len(frames),"rects":rects,"centres":centres,"openness":openness}
    (OUTPUT/"manifest.json").write_text(json.dumps(manifest,separators=(",",":"))+"\n")
    print(json.dumps({"clips":len(manifest["clips"]),"frames":sum(c["frames"] for c in manifest["clips"].values()),
                      "compressed_bytes":sum(p.stat().st_size for p in OUTPUT.glob("*.png"))}))


if __name__ == "__main__":
    build()
