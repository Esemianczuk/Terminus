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


def protected_eye_mask(size,polygons,*,logical_size=(440,340),body_rect=(28,-50,384,416)):
    """Match framebuffer pixels at Retina/fractional DPR using logical poses."""
    mask=QtGui.QImage(size,QtGui.QImage.Format.Format_RGBA8888)
    mask.fill(QtCore.Qt.GlobalColor.transparent)
    painter=QtGui.QPainter(mask)
    painter.scale(size.width()/logical_size[0],size.height()/logical_size[1])
    painter.setPen(QtCore.Qt.PenStyle.NoPen);painter.setBrush(QtCore.Qt.GlobalColor.white)
    x0,y0,width,height=body_rect
    for polygon in polygons:
        painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x*width+x0,y*height+y0) for x,y in polygon]))
    painter.end()
    return rgba(mask)[:,:,3]>0


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'work/gpu-study')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    if sys.platform=='darwin':
        from desktop.macos import prepare_macos_environment,configure_macos_application
        prepare_macos_environment()
    app=QtWidgets.QApplication([])
    if sys.platform=='darwin':configure_macos_application()
    window=QtWidgets.QWidget(None,QtCore.Qt.WindowType.Tool|QtCore.Qt.WindowType.FramelessWindowHint|
                            QtCore.Qt.WindowType.WindowDoesNotAcceptFocus|QtCore.Qt.WindowType.WindowTransparentForInput)
    window.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
    window.resize(440,340)
    view=GpuScene(window);view.setGeometry(window.rect())
    if not view.available:raise SystemExit(json.dumps(view.diagnostics()))
    configurations=[('source',0,0,(0,0,0,0),0),('crimson',0,0,(0,0,0,1),1),
                    ('cascade',0,.5,(0,1,0,0),1),('shimmer',0,.75,(1,0,0,0),1)]
    captures={};index=[0];finished=[False]
    def fail(error):
        finished[0]=True
        print(f'GPU study failed: {type(error).__name__}: {error}',file=sys.stderr)
        app.exit(1)
    def guarded(callback):
        def invoke():
            if finished[0]:return
            try:callback()
            except Exception as error:fail(error)
        return invoke
    @guarded
    def set_frame():
        name,frame,phase,weights,intensity=configurations[index[0]]
        view.set_scene(clip='idle',index=frame,phase=phase,body_rect=(28,-50,384,416),clock=3,
                       skin_weights=weights,skin_intensity=intensity)
        QtCore.QTimer.singleShot(120,capture)
    @guarded
    def capture():
        name=configurations[index[0]][0]
        captures[name]=view.grabFramebuffer()
        if captures[name].isNull():raise RuntimeError('The GPU framebuffer is empty')
        if not captures[name].save(str(args.output/f'{name}.png')):raise OSError('Cannot save the GPU study capture')
        index[0]+=1
        if index[0]<len(configurations):set_frame();return
        atlas=json.loads((ROOT/'web/assets/clips/skin-atlas.json').read_text())
        protected=protected_eye_mask(captures['source'].size(),atlas['clips']['idle']['eyes'][0])
        source,red=rgba(captures['source']),rgba(captures['crimson'])
        if source.shape!=red.shape:raise RuntimeError('Framebuffer dimensions changed during the eye audit')
        difference=np.abs(source.astype(np.int16)-red.astype(np.int16))
        report={'protected_eye_pixels':int(protected.sum()),'maximum_eye_channel_change':int(difference[protected].max()),
                'changed_body_pixels':int(np.count_nonzero(np.any(difference[:,:,:3]>0,axis=2))),
                'renderer':view.diagnostics(),'explicit_verification_readbacks':4,
                'framebuffer_size':[captures['source'].width(),captures['source'].height()]}
        (args.output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))
        finished[0]=True
        app.quit()
    window.show();QtCore.QTimer.singleShot(100,set_frame)
    QtCore.QTimer.singleShot(10000,lambda:None if finished[0] else fail(TimeoutError('The GPU study did not complete in ten seconds')))
    return app.exec()


if __name__=='__main__':raise SystemExit(main())
