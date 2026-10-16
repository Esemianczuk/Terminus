#!/usr/bin/env python3
"""Render controlled skin fixtures using real GIF frames; never sample a desktop."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt5 import QtCore,QtGui,QtWidgets
from desktop.animation import ClipLibrary,ClipPlayer,AnimationFrame
from desktop.skin import SkinAtlas,SkinEngine,rgba


def run(output, video):
    output.mkdir(parents=True,exist_ok=True)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    library = ClipLibrary.from_manifest(ROOT/'web/assets/clips/manifest.json')
    atlas = SkinAtlas.load(ROOT/'web/assets/clips/skin-atlas.json',library)
    if atlas.errors:
        raise ValueError(atlas.errors)
    modes = ('off','shimmer','cascade','camouflage','crimson','automatic')
    engines = {m:SkinEngine(atlas,m) for m in modes}
    player = ClipPlayer(library)
    width,height = 320,390
    sheet = QtGui.QImage(width*3,height*2,QtGui.QImage.Format_ARGB32)
    sheet.fill(QtGui.QColor('#242a31'))
    now = 0.
    timings = []
    with tempfile.TemporaryDirectory(prefix='terminus-skin-study-') as temporary:
        frames = Path(temporary)
        for index in range(180 if video else 60):
            now = index/15
            sample = player.advance(now,'idle')
            images = []
            for mode,engine in engines.items():
                engine.update(now,state={'behavior':'idle'},motion=0.)
                started = time.perf_counter()
                image = engine.shade(sample,width=288,height=312)
                timings.append((time.perf_counter()-started)*1000)
                images.append(image)
            # Side-by-side genuine clips, shared phase and protected expressions.
            painter = QtGui.QPainter(sheet)
            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
            for scene,(mode,image) in enumerate(zip(modes,images)):
                x,y = scene%3*width,scene//3*height
                painter.fillRect(x,y,width,height,QtGui.QColor('#242a31'))
                painter.setFont(QtGui.QFont('Sans Serif',12)); painter.setPen(QtGui.QColor('#d7ece8'))
                painter.drawText(x+18,y+27,mode.capitalize())
                painter.setFont(QtGui.QFont('Sans Serif',8)); painter.setPen(QtGui.QColor('#8ca9a6'))
                painter.drawText(x+18,y+46,'Procedural skin · original GIF / eyes')
                painter.drawImage(QtCore.QRectF(x+16,y+60,288,312),image)
            painter.end()
            if index == 59:
                sheet.save(str(output/'skin-contact-sheet.png'))
            if video:
                sheet.save(str(frames/f'frame-{index:04d}.png'))
        if video and shutil.which('ffmpeg'):
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-framerate','15','-i',str(frames/'frame-%04d.png'),
                            '-c:v','libx264','-crf','18','-pix_fmt','yuv420p',str(output/'living-skin.mp4')],check=True)
    # Every pose, including transitions: show the protected eye interiors.
    debug = QtGui.QImage(384*4,456*3,QtGui.QImage.Format_ARGB32)
    debug.fill(QtGui.QColor('#242a31')); painter = QtGui.QPainter(debug)
    engine = SkinEngine(atlas,'crimson'); engine.update(0)
    for i,(name,clip) in enumerate(library.clips.items()):
        n = len(clip.frames)//2
        sample = AnimationFrame(clip.frames[n],name,n,name,not clip.loop,False,100,clip.anchors,False)
        image = engine.shade(sample)
        painter.drawImage(i%4*384,i//4*456+40,image)
        s = next(reversed(engine.cache.values()))
        guard = QtGui.QImage(384,416,QtGui.QImage.Format_ARGB32); guard.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(guard); p.setBrush(QtGui.QColor(255,170,70,95)); p.setPen(QtCore.Qt.NoPen)
        for polygon in atlas.frames[name][n]:
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x*384,y*416) for x,y in polygon]))
        p.end(); painter.drawImage(i%4*384,i//4*456+40,guard)
        painter.setPen(QtGui.QColor('#d7ece8')); painter.drawText(i%4*384+15,i//4*456+25,name+' · eye guards highlighted')
    painter.end(); debug.save(str(output/'eye-guard-audit.png'))
    report = {'scope':'controlled fixtures using original GIF frames and native skin engine',
              'live_state_accessed':False,'screen_or_apps_captured':False,'new_art_frames':0,
              'registered_frames':sum(len(f) for f in atlas.frames.values()),'modes':list(modes),
              'fps':15,'preview_seconds':now,'mean_evaluation_ms':round(sum(timings)/len(timings),2),
              'cache_limit_bytes':engines['automatic'].max_cache_bytes,'video':video}
    (output/'skin-provenance.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'work/skin-study')
    parser.add_argument('--video',action='store_true')
    args=parser.parse_args(); run(args.output_dir.resolve(),args.video)
