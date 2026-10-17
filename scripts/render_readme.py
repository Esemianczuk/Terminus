#!/usr/bin/env python3
"""Render a small GIF from controlled native-body fixtures, without desktop capture."""
import math
import argparse
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6 import QtCore,QtGui,QtWidgets
from PIL import Image
from terminus.core import Organism
from desktop.overlay import CoreClient,Overlay

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,default=ROOT/'docs/screenshots/terminus.gif')
args=parser.parse_args()
if sys.platform=='darwin':
    from desktop.macos import prepare_macos_environment,configure_macos_application
    prepare_macos_environment()
app=QtWidgets.QApplication([])
if sys.platform=='darwin':configure_macos_application()
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
    widget.awareness_enabled=False
    widget.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
    widget.setWindowFlag(QtCore.Qt.WindowTransparentForInput,True)
    if sys.platform=='darwin':
        from desktop.macos import MacPresence
        widget.mac_presence=MacPresence(widget)
    if not widget.enable_gpu():raise SystemExit('GPU preview unavailable: '+str(widget.gpu_error))
    widget.show()
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
        # Explicit offline artwork export. This never runs in the desktop
        # service and captures only our own fixture's framebuffer.
        app.processEvents()
        foreground=widget.gpu_scene.grabFramebuffer()
        if foreground.isNull():raise SystemExit('GPU preview capture failed')
        image=QtGui.QImage(widget.size(),QtGui.QImage.Format_RGB32);image.fill(QtGui.QColor('#142027'))
        painter=QtGui.QPainter(image);painter.drawImage(image.rect(),foreground);painter.end()
        path=Path(directory)/'frame.png';image.save(str(path));frames.append(Image.open(path).convert('RGB'))
    output=args.output;output.parent.mkdir(parents=True,exist_ok=True)
    frames[0].save(output,save_all=True,append_images=frames[1:],duration=80,loop=0,optimize=True)
    widget.close();print(f'{output}: {output.stat().st_size} bytes, 96 controlled native frames')
