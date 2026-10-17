#!/usr/bin/env python3
"""Render only the creature's own GPU widget and audit eye pigment protection."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from PySide6 import QtCore,QtGui,QtWidgets
from desktop.gpu import GpuScene


def rgba(image):
    converted=image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    return np.frombuffer(converted.bits(),np.uint8).reshape(converted.height(),converted.bytesPerLine())[:,:converted.width()*4].reshape(converted.height(),converted.width(),4).copy()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'work/gpu-study')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    app=QtWidgets.QApplication([])
    window=QtWidgets.QWidget(None,QtCore.Qt.WindowType.Tool|QtCore.Qt.WindowType.FramelessWindowHint|
                            QtCore.Qt.WindowType.WindowDoesNotAcceptFocus|QtCore.Qt.WindowType.WindowTransparentForInput)
    window.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
    window.resize(440,340)
    view=GpuScene(window);view.setGeometry(window.rect())
    if not view.available:raise SystemExit(json.dumps(view.diagnostics()))
    configurations=[('source',0,0,(0,0,0,0),0),('crimson',0,0,(0,0,0,1),1),
                    ('cascade',0,.5,(0,1,0,0),1),('shimmer',0,.75,(1,0,0,0),1)]
    captures={};index=[0]
    def set_frame():
        name,frame,phase,weights,intensity=configurations[index[0]]
        view.set_scene(clip='idle',index=frame,phase=phase,body_rect=(28,-50,384,416),clock=3,
                       skin_weights=weights,skin_intensity=intensity)
        QtCore.QTimer.singleShot(120,capture)
    def capture():
        name=configurations[index[0]][0]
        captures[name]=view.grabFramebuffer()
        captures[name].save(str(args.output/f'{name}.png'))
        index[0]+=1
        if index[0]<len(configurations):set_frame();return
        atlas=json.loads((ROOT/'web/assets/clips/skin-atlas.json').read_text())
        mask=QtGui.QImage(440,340,QtGui.QImage.Format.Format_RGBA8888);mask.fill(QtCore.Qt.GlobalColor.transparent)
        painter=QtGui.QPainter(mask);painter.setPen(QtCore.Qt.PenStyle.NoPen);painter.setBrush(QtCore.Qt.GlobalColor.white)
        for polygon in atlas['clips']['idle']['eyes'][0]:
            painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x*384+28,y*416-50) for x,y in polygon]))
        painter.end()
        protected=rgba(mask)[:,:,3]>0
        source,red=rgba(captures['source']),rgba(captures['crimson'])
        difference=np.abs(source.astype(np.int16)-red.astype(np.int16))
        report={'protected_eye_pixels':int(protected.sum()),'maximum_eye_channel_change':int(difference[protected].max()),
                'changed_body_pixels':int(np.count_nonzero(np.any(difference[:,:,:3]>0,axis=2))),
                'renderer':view.diagnostics(),'explicit_verification_readbacks':4}
        (args.output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))
        app.quit()
    window.show();QtCore.QTimer.singleShot(100,set_frame);app.exec()


if __name__=='__main__':main()
