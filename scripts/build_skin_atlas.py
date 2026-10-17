#!/usr/bin/env python3
"""Register vector eye protection with the existing offline GIF rig.

Authoring only: /usr/bin/python3 scripts/build_skin_atlas.py (Qt, Pillow, OpenCV).
Writes geometry and clip fingerprints, never edits or re-encodes the artwork.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from build_animation_clips import FrameAuthor, SOURCES, SPECS, WIDTH, HEIGHT, ROOT

# Normalized, hand-traced eye regions include pupils, whites and dark rims.
# The runtime adds a soft exterior guard; it never changes these interiors.
REFINED = [
    [[.395,.426],[.445,.405],[.522,.397],[.572,.404],[.576,.446],[.55,.473],[.492,.484],[.429,.476],[.398,.454]],
    [[.642,.376],[.666,.354],[.715,.336],[.778,.33],[.787,.376],[.767,.413],[.716,.431],[.662,.425],[.642,.403]],
]
EYES = {
    'refined': REFINED, 'sleep': REFINED, 'yawn': REFINED,
    'typing': [[[x,y+.019] for x,y in polygon] for polygon in REFINED],
    'flight': [
        [[.548,.428],[.585,.407],[.656,.396],[.718,.403],[.724,.447],[.697,.478],[.633,.49],[.576,.478],[.55,.458]],
        [[.807,.371],[.833,.344],[.878,.328],[.922,.331],[.938,.37],[.931,.408],[.899,.434],[.85,.444],[.819,.423]],
    ],
    'stretch': [
        [[.427,.522],[.465,.5],[.531,.488],[.581,.493],[.59,.534],[.56,.564],[.506,.578],[.455,.567],[.43,.548]],
        [[.661,.468],[.687,.442],[.733,.426],[.785,.424],[.795,.464],[.776,.497],[.735,.515],[.69,.511],[.668,.491]],
    ],
}


def build():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    author = FrameAuthor()
    for name, path in SOURCES.items():
        image = QtGui.QImage(str(path))
        mask = QtGui.QPixmap(image.size()); mask.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(mask)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtCore.Qt.NoPen); painter.setBrush(QtCore.Qt.white)
        for polygon in EYES[name]:
            painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x*image.width(), y*image.height()) for x,y in polygon]))
        painter.end(); author.art[name] = mask
    provenance = json.loads((ROOT/'web/assets/clips/provenance.json').read_text())
    atlas = {'version': 1, 'canvas': [WIDTH,HEIGHT], 'method': 'eye polygons through the original offline pose rig; no artwork changes',
             'source_eyes': EYES, 'clips': {}}
    for name, (count, delay, _) in SPECS.items():
        source_masks = [np.asarray(author.render(name, i, count))[:,:,3] for i in range(count)]
        frames, first = [], 0
        for duration in provenance['clips'][name]['delays_ms']:
            end = first + duration//delay
            mask = np.max(source_masks[first:end], axis=0)
            contours, _ = cv2.findContours((mask>0).astype('uint8'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            polygons = [cv2.approxPolyDP(c, .6, True).reshape(-1,2) for c in contours if cv2.contourArea(c)>3]
            frames.append([[[round(float(x)/WIDTH,5),round(float(y)/HEIGHT,5)] for x,y in p] for p in polygons])
            first = end
        if first != count or any(len(p)!=2 for p in frames):
            raise ValueError(f'{name}: cannot register decoded eye frames')
        path = ROOT/'web/assets/clips'/f'{name}.gif'
        atlas['clips'][name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'eyes': frames}
    output = ROOT/'web/assets/clips/skin-atlas.json'
    output.write_text(json.dumps(atlas, separators=(',',':'))+'\n')
    print(json.dumps({'frames':sum(len(c['eyes']) for c in atlas['clips'].values()), 'bytes':output.stat().st_size}))

if __name__ == '__main__':
    build()
