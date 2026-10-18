#!/usr/bin/env python3
"""Profile this creature's own RHI widget, without screen capture or input hooks.

The fixture is presentation-only and never writes observations into the core.
Run with the real desktop DISPLAY for hardware results; offscreen is not a GPU
benchmark. Optional screenshot is an explicit one-off readback after profiling.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6 import QtCore,QtWidgets
from desktop.gpu import GpuScene
from desktop.gaze import GazeAtlas


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--seconds",type=float,default=15)
    parser.add_argument("--fps",type=float,default=8)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--screenshot",type=Path)
    parser.add_argument("--clip",default="idle")
    args=parser.parse_args()
    if sys.platform=='darwin':
        from desktop.macos import prepare_macos_environment,configure_macos_application
        prepare_macos_environment()
    app=QtWidgets.QApplication([])
    if sys.platform=='darwin':configure_macos_application()
    parent=QtWidgets.QWidget(None,QtCore.Qt.WindowType.Tool | QtCore.Qt.WindowType.FramelessWindowHint |
                             QtCore.Qt.WindowType.WindowDoesNotAcceptFocus | QtCore.Qt.WindowType.WindowTransparentForInput)
    parent.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
    parent.resize(440,340)
    view=GpuScene(parent)
    view.setGeometry(parent.rect())
    if not view.available:
        raise SystemExit(json.dumps(view.diagnostics()))
    gaze=GazeAtlas(ROOT/'web/assets/gaze/manifest.json',view.playback_library())
    nodes=[dict(id=str(i),x=55+i%6*65,y=175+i//6*39,activation=.2+(i%5)*.13,focus=i==9,contact=i in (8,10,14)) for i in range(24)]
    edges=[]
    for i in range(24):
        for j in (i+1,i+6):
            if j>=24: continue
            a,b=nodes[i],nodes[j]
            edges.append(dict(x0=a['x'],y0=a['y'],cx=(a['x']+b['x'])/2+math.sin(i*2.4)*8,
                              cy=(a['y']+b['y'])/2+16,x1=b['x'],y1=b['y'],activation=max(a['activation'],b['activation']),weight=.4,focus=i==9,index=len(edges)))
    arms=[dict(x0=190+i*25,y0=190,cx0=160+i*45,cy0=225,cx1=nodes[j]['x'],cy1=nodes[j]['y']+22,
               x1=nodes[j]['x'],y1=nodes[j]['y'],activation=.6,index=i) for i,j in enumerate((8,10,14))]
    samples=[]; frames=[0]; begun=[None]; baseline=[None]
    view.quickWindow().afterRendering.connect(lambda:frames.__setitem__(0,frames[0]+1))
    clip=view.manifest['clips'][args.clip]
    duration=sum(clip['delays_ms'])/1000
    def draw():
        now=time.monotonic()
        if begun[0] is None:
            begun[0]=now
            baseline[0]=resource.getrusage(resource.RUSAGE_SELF)
        elapsed=now-begun[0]
        position=(elapsed%duration)*1000
        index=0
        for delay in clip['delays_ms']:
            if position<delay:break
            position-=delay; index+=1
        index=min(index,clip['count']-1)
        view.set_scene(clip=args.clip,index=index,phase=position/clip['delays_ms'][index],body_rect=(120,24,192,208),clock=elapsed,
                       nodes=nodes,edges=edges,tendrils=arms,skin_weights=(.2,.6,.2,0),skin_intensity=.8,
                       gaze_atlas=gaze,gaze_shift=(2.4,-.6,2.4,-.6))
        # Ignore initial PNG texture decode/upload while recording steady state.
        if elapsed>1:samples.append(view.upload_ms)
        if elapsed>=args.seconds:
            timer.stop()
            usage=resource.getrusage(resource.RUSAGE_SELF)
            cpu=(usage.ru_utime-baseline[0].ru_utime)+(usage.ru_stime-baseline[0].ru_stime)
            report=dict(seconds=round(elapsed,3),requested_fps=args.fps,rendered_frames=frames[0],
                        cpu_seconds=round(cpu,4),cpu_percent_one_core=round(cpu/elapsed*100,3),
                        submit_median_ms=round(statistics.median(samples),3),submit_p95_ms=round(sorted(samples)[int((len(samples)-1)*.95)],3),
                        rss_current_kib=int(subprocess.check_output(['ps','-o','rss=','-p',str(__import__('os').getpid())],text=True).strip()),
                        renderer=view.diagnostics(),
                        screenshot_readbacks=1 if args.screenshot else 0)
            if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps(report))
            if args.screenshot:view.grabFramebuffer().save(str(args.screenshot))
            app.quit()
    timer=QtCore.QTimer();timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
    timer.timeout.connect(draw);timer.setInterval(max(16,round(1000/max(1,min(60,args.fps)))))
    parent.show();draw();timer.start()
    app.exec()


if __name__=='__main__':main()
