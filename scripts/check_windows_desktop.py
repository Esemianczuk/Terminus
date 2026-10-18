"""Run inside the Windows desktop session to check this checkout's own window.

Captures only Terminus's rectangle when --capture is supplied. Does not move
focus, type, click, or inspect application text. Output stays in .local.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',action='store_true');parser.add_argument('--seconds',type=int,default=15)
    args=parser.parse_args()
    from terminus.platform_windows import kernel,record,creation
    from PySide6 import QtGui
    app=QtGui.QGuiApplication([])
    data=ROOT/'.local'
    before=json.loads((data/'desktop-status.json').read_text())
    user=C.WinDLL('user32',use_last_error=True)
    user.GetForegroundWindow.restype=W.HWND
    user.SendMessageTimeoutW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM,W.UINT,W.UINT,C.POINTER(C.c_size_t)]
    foreground=user.GetForegroundWindow()
    result=C.c_size_t()
    delivered=user.SendMessageTimeoutW(before['nativewinid'],0x21,0,0,2,1000,C.byref(result))
    handles={};lib=kernel()
    def cpu(handle):
        times=[W.FILETIME() for _ in range(4)]
        if not lib.GetProcessTimes(handle,*(C.byref(t) for t in times)):raise OSError('Process times unavailable')
        return sum((t.dwHighDateTime<<32)|t.dwLowDateTime for t in times[2:])/1e7
    try:
        for role in ('core','desktop'):
            identity=record(role,ROOT)
            if not identity:raise RuntimeError('Owned service missing')
            handle=lib.OpenProcess(0x1000,False,identity['pid'])
            if not handle or creation(lib,handle)!=identity['created']:raise RuntimeError('Process identity changed')
            handles[role]=(handle,cpu(handle))
        start=time.monotonic()
        while time.monotonic()-start<max(2,min(args.seconds,60)):
            app.processEvents();time.sleep(.05)
        elapsed=time.monotonic()-start
        report={'elapsed_seconds':elapsed,'cpu_percent_one_core':{role:round((cpu(h)-old)/elapsed*100,2) for role,(h,old) in handles.items()},
                'mouse_activate_result':result.value if delivered else None,
                'foreground_unchanged':foreground==user.GetForegroundWindow()}
        after=json.loads((data/'desktop-status.json').read_text())
        report['desktop']=after
        report['same_organism']=before.get('organism_id')==after.get('organism_id')
        if args.capture:
            r=after['geometry'];screen=app.screenAt(QtGui.QCursor.pos()) or app.primaryScreen()
            # Screen coordinates are logical; Qt supplies a DPR-aware pixmap.
            target=QtGui.QGuiApplication.screenAt(__import__('PySide6.QtCore',fromlist=['QPoint']).QPoint(r['x'],r['y'])) or screen
            origin=target.geometry()
            report['capture_saved']=target.grabWindow(0,r['x']-origin.x(),r['y']-origin.y(),r['width'],r['height']).save(str(data/'windows-screen-proof.png'))
        (data/'windows-check.json').write_text(json.dumps(report,indent=2))
    finally:
        for handle,_ in handles.values():lib.CloseHandle(handle)


if __name__=='__main__':main()
