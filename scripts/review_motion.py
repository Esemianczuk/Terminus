#!/usr/bin/env python3
"""Render a bounded synthetic motion fixture through the real raster graph code.

No core is started or contacted. Fixture observations never enter memory.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from types import MethodType, SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets
from desktop.animation import ClipLibrary, ClipPlayer
from desktop.directional_motion import DirectionalMotion
from desktop.graph_motion import GraphMotion
from desktop.overlay import Overlay


def fixture(t):
    nodes=[]
    for i in range(10):
        angle=i*math.tau/10
        nodes.append({'id':str(i),'x':.5+.42*math.cos(angle)+.025*math.sin(t*.8+i),
                      'y':.5+.40*math.sin(angle)+.02*math.cos(t*.7+i),
                      'activation':.85 if 2<=t<5 and i%3==0 else .12})
    return {'position':{'x':.5,'y':.62},'attention':str(0 if t<4 else 6),'nodes':nodes,
            'edges':[{'source':str(i),'target':str((i+j)%10),'weight':.4+j*.1}
                     for i in range(10) for j in (1,3)]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'work/motion-review')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    library=ClipLibrary.from_manifest(ROOT/'web/assets/clips/manifest.json')
    player=ClipPlayer(library);steering=DirectionalMotion()
    view=SimpleNamespace(state=fixture(0),graph_motion=GraphMotion(),graph_cache_key=None,
                         graph_points={},graph_paths=[],reduced_motion=False,glow_cache={},
                         fresh=lambda now:True,graph_point=Overlay.graph_point,
                         creature_rect=QtCore.QRectF(125,24,190,206))
    for name in ('cache_graph','draw_graph','draw_glow','body_transform'):
        setattr(view,name,MethodType(getattr(Overlay,name),view))
    images=[];max_step=0.;previous={};banks=[]
    for frame in range(160):
        t=frame/20
        if frame%5==0:view.state=fixture(t)
        view.cache_graph(view.state,t)
        view.graph_motion.set_contacts({'0' if t<4 else '6'})
        vx=130*math.cos(t*.65);vy=90*math.sin(t*.9)
        facing=1 if vx>=0 else -1
        view.flight_bank=steering.sample(t,vx,vy,facing=facing,active=.7)
        banks.append(view.flight_bank)
        view.clip_sample=player.advance(t,desired='moving',facing=facing)
        image=QtGui.QImage(440,340,QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtGui.QColor('#101c26'))
        graph=QtGui.QImage(440,340,QtGui.QImage.Format_ARGB32_Premultiplied);graph.fill(QtCore.Qt.transparent)
        painter=QtGui.QPainter(graph);painter.setRenderHint(QtGui.QPainter.Antialiasing)
        view.draw_graph(painter,view.graph_points,t,set());painter.end()
        painter=QtGui.QPainter(image);painter.setRenderHint(QtGui.QPainter.Antialiasing)
        for opacity in (1.,1.,.8):painter.setOpacity(opacity);painter.drawImage(0,0,graph)
        painter.setOpacity(1.);painter.save();painter.setTransform(view.body_transform({}))
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.drawImage(view.creature_rect,view.clip_sample.image);painter.restore()
        painter.setPen(QtGui.QColor('#acc5cc'))
        painter.drawText(QtCore.QRect(12,313,416,20),QtCore.Qt.AlignCenter,'Controlled motion fixture · synthetic activity')
        painter.end()
        rgba=image.convertToFormat(QtGui.QImage.Format_RGBA8888)
        images.append(Image.frombytes('RGBA',(440,340),bytes(rgba.constBits())).convert('RGB'))
        for key,flow in view.graph_motion.edges.items():
            if key in previous:max_step=max(max_step,(flow['phase']-previous[key])%1.)
            previous[key]=flow['phase']
    palette=Image.new('RGB',(440,340*8))
    for i,frame in enumerate(images[::20]):palette.paste(frame,(0,i*340))
    palette=palette.quantize(colors=256)
    frames=[frame.quantize(palette=palette,dither=Image.Dither.NONE) for frame in images]
    frames[0].save(args.output/'motion.gif',save_all=True,append_images=frames[1:],duration=50,loop=0,disposal=1,optimize=False)
    sheet=Image.new('RGB',(440*3,340*2))
    for index,frame in enumerate((images[0],images[40],images[60],images[80],images[100],images[140])):
        sheet.paste(frame,((index%3)*440,(index//3)*340))
    sheet.save(args.output/'contact-sheet.png')
    metrics={'frames':len(images),'fps':20,'maximum_edge_phase_step':max_step,
             'maximum_allowed_edge_step':.23/20,'bank_range_degrees':[min(banks),max(banks)],
             'real_memory_contacted':False}
    assert max_step<=.23/20+1e-10
    (args.output/'metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
    print(json.dumps(metrics))


if __name__=='__main__':main()
