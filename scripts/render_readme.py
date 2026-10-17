#!/usr/bin/env python3
"""Render a small GIF from controlled native-body fixtures, without desktop capture."""
import math
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['QT_QPA_PLATFORM']='offscreen'
from PyQt5 import QtCore,QtGui,QtWidgets
from PIL import Image
from terminus.core import Organism
from desktop.overlay import CoreClient,Overlay

app=QtWidgets.QApplication([])
with tempfile.TemporaryDirectory(prefix='terminus-readme-') as directory:
    widget=Overlay(CoreClient('http://127.0.0.1:1',Path(directory)),ROOT/'web/assets',1.25)
    for timer in (widget.animation,widget.asset_timer,widget.presence_timer,widget.awareness_timer):timer.stop()
    creature=Organism(seed=814,now=1000)
    for i in range(14):
        creature.event({'id':str(i),'kind':('context','activity','presence')[i%3],
                        'context':('making','typing','company')[i%3],'source':'synthetic',
                        'device_id':'preview','intensity':.35},1001+i)
    widget.state=creature.state();widget.state.update(behavior='idle',gesture=None)
    widget.connected=True;widget.roaming_paused=True;widget.status_until=0;widget.glyph_sequence=[]
    request={'desired':'idle','facing':1,'fresh':True}
    widget.prepare_clip=lambda now:setattr(widget,'clip_sample',widget.clip_player.advance(now,**request))
    frames=[]
    for i in range(96):
        t=i/12;now=widget.started+t;widget.last_seen=now
        request['desired']='moving' if 2<=t<5 else 'idle'
        request['facing']=-1 if 3.5<=t<6 else 1
        widget.flight_strength=.35 if 2<=t<5 else 0.
        widget.flight_bank=4*math.sin(t*2) if 2<=t<5 else 0.
        widget.render_frame(now)
        image=QtGui.QImage(widget.size(),QtGui.QImage.Format_RGB32);image.fill(QtGui.QColor('#142027'))
        painter=QtGui.QPainter(image);painter.drawImage(0,0,widget.frame);painter.end()
        path=Path(directory)/'frame.png';image.save(str(path));frames.append(Image.open(path).convert('RGB'))
    output=ROOT/'docs/screenshots/terminus.gif'
    frames[0].save(output,save_all=True,append_images=frames[1:],duration=80,loop=0,optimize=True)
    widget.close();print(f'{output}: {output.stat().st_size} bytes, 96 controlled native frames')
