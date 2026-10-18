#!/usr/bin/env python3
"""Inspect actual RHI skin/ink fixtures using only this process's own pixels."""
from pathlib import Path
import json
import sys
import time
import numpy as np
from PIL import Image, ImageDraw
from PySide6 import QtCore, QtGui, QtWidgets, QtTest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from desktop.gpu import GpuScene


def pil(image):
    image=image.convertToFormat(QtGui.QImage.Format_RGBA8888)
    rgba=np.frombuffer(image.constBits(),np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*4]
    return Image.fromarray(rgba.reshape(image.height(),image.width(),4).copy(),'RGBA')


def main():
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    output=ROOT/'work/effects-review';output.mkdir(parents=True,exist_ok=True)
    flags=QtCore.Qt.Tool|QtCore.Qt.FramelessWindowHint|QtCore.Qt.WindowDoesNotAcceptFocus|QtCore.Qt.WindowTransparentForInput
    parent=QtWidgets.QWidget(None,flags);parent.setAttribute(QtCore.Qt.WA_TranslucentBackground)
    parent.resize(440,340);view=GpuScene(parent);view.setGeometry(parent.rect())
    parent.show();QtTest.QTest.qWait(150)
    if not view.available:raise RuntimeError(view.errors)
    field={'colors':[[.11,.16,.22],[.46,.20,.10],[.08,.30,.27],[.55,.48,.30]],'confidence':1.,
           'motion':[.12,-.04],'change':.3,'windows':[{'x':.12,'y':.2,'width':.6,'height':.5}]}
    base=dict(clip='idle',index=0,phase=0,body_rect=(120,20,192,208),morph_strength=0.,clock=2.,skin_clock=2.)
    cases=[('Original',{},[0,0,0,0],0),('Cuttlefish',{},[0,0,1,0],.97),
           ('Partial symbols',{'ascii':.54},[.6,.4,0,0],.8),('Symbols',{'ascii':1},[.6,.4,0,0],.8),
           ('Ink: opening',{'ink':.95,'ink_phase':1.7,'seed':.42},[.6,.4,0,0],.8),
           ('Ink: drifting',{'ink':.8,'ink_phase':5.,'seed':.42},[.6,.4,0,0],.8)]
    sheet=Image.new('RGB',(1320,736),(17,23,30));draw=ImageDraw.Draw(sheet)
    own=[];metrics=[]
    for i,(label,effects,weights,intensity) in enumerate(cases):
        view.set_scene(**base,skin_weights=weights,skin_intensity=intensity,screen_field=field,effects=effects)
        QtTest.QTest.qWait(80)
        result=pil(view.grabFramebuffer()).resize((440,340))
        own.append(np.asarray(result))
        x,y=(i%3)*440,(i//3)*368
        # Controlled two-tone fictional desktop; no desktop content is read.
        bg=Image.new('RGBA',(440,340),(22,35,44,255));d=ImageDraw.Draw(bg)
        d.rounded_rectangle((240,25,440,260),radius=18,fill=(94,57,29,255))
        bg.alpha_composite(result);sheet.paste(bg.convert('RGB'),(x,y+26));draw.text((x+12,y+8),label,fill=(214,235,231))
        metrics.append({'case':label,'opaque_border_pixels':int(np.count_nonzero(np.asarray(result)[[0,-1],:,3]))})
    # The eye interiors remain byte-identical while alpha and color elsewhere
    # can dissolve. The renderer's authored polygon masks cover larger areas.
    registrations=json.loads((ROOT/'web/assets/clips/skin-atlas.json').read_text())['clips']
    eyes=registrations['idle']['eyes'][0]
    maxeye=0
    for polygon in eyes:
        cx=round(120+sum(p[0] for p in polygon)/len(polygon)*192)
        cy=round(20+sum(p[1] for p in polygon)/len(polygon)*208)
        for changed in own[1:4]:
            maxeye=max(maxeye,int(np.max(np.abs(changed[cy-2:cy+3,cx-2:cx+3].astype(int)-own[0][cy-2:cy+3,cx-2:cx+3].astype(int)))))
    sheet.save(output/'effects-contact-sheet.png')
    eye_cases=0
    for name,entry in registrations.items():
        for index,polygons in enumerate(entry['eyes']):
            inputs=dict(base,clip=name,index=index)
            view.set_scene(**inputs,skin_intensity=0.,effects={})
            QtTest.QTest.qWait(10)
            original=np.asarray(pil(view.grabFramebuffer()).resize((440,340)))
            view.set_scene(**inputs,skin_intensity=1.,skin_weights=[0,0,1,0],screen_field=field,effects={'ascii':1.})
            QtTest.QTest.qWait(10)
            changed=np.asarray(pil(view.grabFramebuffer()).resize((440,340)))
            for polygon in polygons:
                cx=round(120+sum(p[0] for p in polygon)/len(polygon)*192)
                cy=round(20+sum(p[1] for p in polygon)/len(polygon)*208)
                maxeye=max(maxeye,int(np.max(np.abs(changed[cy-1:cy+2,cx-1:cx+2].astype(int)-original[cy-1:cy+2,cx-1:cx+2].astype(int)))))
                eye_cases+=1
    frames=[]
    for i in range(180):
        t=i/18
        ascii_level=max(0.,min(1.,(t-2.)/1.5))*max(0.,min(1.,(6.-t)/1.5))
        age=max(0.,t-4.5)
        ink=min(1.,age/1.15)*min(1.,max(0.,(7.-age)/3.)) if t>4.5 else 0.
        field['motion']=[.12*float(np.sin(t*.7)),-.04]
        view.set_scene(**dict(base,clock=t,skin_clock=t),skin_weights=[.15,.15,.7,0],skin_intensity=.9,
                       screen_field=field,effects={'ascii':ascii_level,'ink':ink,'ink_phase':age,'seed':.42})
        QtTest.QTest.qWait(22)
        own_frame=pil(view.grabFramebuffer()).resize((440,340))
        frame=Image.new('RGBA',(440,368),(22,35,44,255));drawing=ImageDraw.Draw(frame)
        drawing.rounded_rectangle((240,38,450,310),radius=18,fill=(94,57,29,255))
        frame.alpha_composite(own_frame,(0,28))
        drawing.text((12,10),'Coarse camouflage / living symbols / ink in water',fill=(214,235,231))
        frames.append(frame.convert('RGB'))
    # Fixed palette avoids per-frame GIF palette shimmer in review material.
    palette_sheet=Image.new('RGB',(440*6,368*3))
    for i,frame in enumerate(frames[::10]):palette_sheet.paste(frame,((i%6)*440,(i//6)*368))
    palette=palette_sheet.quantize(colors=224)
    indexed=[frame.quantize(palette=palette,dither=Image.Dither.NONE) for frame in frames]
    indexed[0].save(output/'living-displays.gif',save_all=True,append_images=indexed[1:],
                    duration=[60 if i%5==0 else 50 for i in range(len(indexed))],loop=0,disposal=1,optimize=False)
    # Measure caller work with live hardware. Own-frame readback above is an
    # audit only and is excluded from these production submission timings.
    timings=[];started=time.process_time();wall=time.perf_counter()
    for i in range(90):
        t=i/30
        tick=time.perf_counter()
        view.set_scene(**dict(base,clock=t,skin_clock=t),skin_weights=[0,0,1,0],skin_intensity=.9,screen_field=field,
                       effects={'ascii':.5,'ink':1.,'ink_phase':2+t,'seed':.42})
        timings.append((time.perf_counter()-tick)*1000)
        QtTest.QTest.qWait(33)
    report={'scope':'actual hardware fixture, no desktop capture','eye_core_maximum_difference':maxeye,
            'eye_core_cases':eye_cases,
            'border_checks':metrics,'submit_ms_median':float(np.median(timings)),
            'submit_ms_p95':float(np.percentile(timings,95)),
            'process_cpu_percent_one_core':100*(time.process_time()-started)/(time.perf_counter()-wall),
            'renderer':view.diagnostics()}
    (output/'metrics.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    parent.close()
    if maxeye>1 or view.errors or any(m['opaque_border_pixels'] for m in metrics):raise SystemExit(1)


if __name__=='__main__':main()
