"""Synthetic windows on a caller-owned Xvfb; never attach to a user display."""
import ctypes as C
import json
import os
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from PySide6 import QtCore,QtGui,QtTest,QtWidgets
from desktop.background_x11 import X11Background

app=QtWidgets.QApplication([])


class Quadrants(QtWidgets.QWidget):
    def paintEvent(self,event):
        painter=QtGui.QPainter(self)
        for x,y,colour in ((0,0,'red'),(200,0,'green'),(0,200,'blue'),(200,200,'white')):
            painter.fillRect(x,y,200,200,QtGui.QColor(colour))


source=Quadrants();source.setGeometry(100,100,400,400)
body=QtWidgets.QWidget();body.setGeometry(100,100,400,400)
body.setStyleSheet('background:#ff00ff')
alert=QtWidgets.QWidget();alert.setGeometry(100,100,400,400)
alert.setStyleSheet('background:#ffff00')
sample=X11Background()
sample.composite.XCompositeRedirectWindow.argtypes=[C.c_void_p,C.c_ulong,C.c_int]
sample.composite.XCompositeRedirectWindow.restype=None
sample.x.XChangeProperty.argtypes=[C.c_void_p,C.c_ulong,C.c_ulong,C.c_ulong,C.c_int,C.c_int,C.c_void_p,C.c_int]
sample.x.XChangeProperty.restype=C.c_int


def prop(window,name,values,type_name='CARDINAL'):
    atom=sample.x.XInternAtom(sample.display,name.encode(),0)
    type_atom=sample.x.XInternAtom(sample.display,type_name.encode(),0)
    data=(C.c_ulong*len(values))(*values)
    sample.x.XChangeProperty(sample.display,window,atom,type_atom,32,0,data,len(values))


windows=[int(widget.winId()) for widget in (source,body,alert)]
for index,(widget,window) in enumerate(zip((source,body,alert),windows)):
    sample.composite.XCompositeRedirectWindow(sample.display,window,0)
    widget.show()
    prop(window,'WM_STATE',[1,0],'WM_STATE')
    prop(window,'_NET_WM_DESKTOP',[0xffffffff if widget is source else 0])
    prop(window,'_NET_WM_PID',[os.getpid() if widget is body else os.getpid()+index+1])
prop(sample.root,'_NET_CLIENT_LIST_STACKING',windows,'WINDOW')
prop(sample.root,'_NET_CURRENT_DESKTOP',[0])
sample.x.XSync(sample.display,0)
QtTest.QTest.qWait(150)
latencies=[]
for _ in range(20):
    started=time.perf_counter()
    result=sample.capture((100,100,400,400),os.getpid())
    latencies.append((time.perf_counter()-started)*1000)
    assert result['available'],result
expected=[[1,0,0],[0,128/255,0],[0,0,1],[1,1,1]]
assert all(abs(a-b)<.01 for row,want in zip(result['colors'],expected) for a,b in zip(row,want)),result
print(json.dumps({'colors':result['colors'],'excluded_own_magenta':True,'excluded_above_yellow':True,
                  'median_ms':statistics.median(latencies),'maximum_ms':max(latencies),
                  'samples':len(latencies),'display':os.environ['DISPLAY'],'synthetic_windows_only':True}))
sample.close()
for widget in (source,body,alert):widget.close()
