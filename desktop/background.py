"""Opt-in, ephemeral four-color backdrop sensing, isolated from learning.

The GUI never calls a capture API. A disposable worker returns only twelve
color numbers, at most twice per second. Pixels never enter IPC or the core.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time


DEFAULT_COLORS = [[.12,.24,.27]]*4


def validate_colors(value):
    return (isinstance(value,list) and len(value)==4 and all(
        isinstance(row,list) and len(row)==3 and all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1 for v in row)
        for row in value))


class ColorField:
    """Smooth finite color targets. Never retains a pixel or screen path."""
    def __init__(self):
        self.clear()

    def clear(self):
        self.colors=[list(c) for c in DEFAULT_COLORS]
        self.target=[list(c) for c in DEFAULT_COLORS]
        self.observed=-math.inf
        self.last=None
        self.confidence=0.
        self.change=0.
        self.change_target=0.
        self.reason="disabled"

    def receive(self, payload, now):
        if payload.get("available") is not True or not validate_colors(payload.get("colors")):
            self.observed=-math.inf
            self.reason=str(payload.get("reason","unavailable"))[:80]
            return
        colors=payload["colors"]
        self.change_target=max(self.change_target,min(1.,sum(abs(a-b) for old,new in zip(self.target,colors) for a,b in zip(old,new))/4))
        self.target=[list(c) for c in colors]
        self.observed=now
        self.reason="available"

    def sample(self, now):
        dt=0. if self.last is None else max(0.,min(.25,now-self.last))
        self.last=now
        k=1-math.exp(-dt/.8)
        available=0<=now-self.observed<=2.5
        self.confidence+=(float(available)-self.confidence)*k
        for row,target in zip(self.colors,self.target):
            for i in range(3): row[i]+=(target[i]-row[i])*k
        self.change+=(self.change_target-self.change)*(1-math.exp(-dt/.45))
        self.change_target*=math.exp(-dt/1.2)
        return {"colors":[list(c) for c in self.colors],"confidence":self.confidence,
                "motion":[0.,0.],"change":self.change}


class BackgroundSampler:
    def __init__(self, parent):
        from PySide6 import QtCore
        self.process=QtCore.QProcess(parent)
        self.process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(lambda:self.process.readAllStandardError())
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.field=ColorField()
        self.pending=None
        self.pending_id=None
        self.sequence=0
        self.next_at=0.
        self.buffer=b""
        self.enabled=False
        self.samples=0

    def _finished(self,*_):
        self.pending=None
        self.pending_id=None
        self.buffer=b""
        if self.enabled:
            self.field.receive({"reason":"worker_stopped"},time.monotonic())
            self.next_at=max(self.next_at,time.monotonic()+30)

    def _process_error(self,error):
        from PySide6 import QtCore
        if error == QtCore.QProcess.ProcessError.FailedToStart and self.enabled:
            self._failed("worker_start_failed",time.monotonic())

    def _failed(self,reason,now):
        self.pending=None;self.pending_id=None;self.buffer=b""
        self.next_at=max(self.next_at,now+30)
        self.field.receive({"reason":reason},now)
        self.process.kill()

    def _read(self):
        incoming=bytes(self.process.readAllStandardOutput())
        if not self.enabled or self.pending is None:
            self.buffer=b""
            return
        self.buffer+=incoming
        if len(self.buffer)>4096:
            self._failed("invalid_worker_reply",time.monotonic()); return
        if b"\n" not in self.buffer: return
        line,self.buffer=self.buffer.split(b"\n",1)
        try:
            payload=json.loads(line)
            if (not isinstance(payload,dict) or self.buffer
                or type(payload.get("request_id")) is not int
                or payload["request_id"] != self.pending_id): raise ValueError()
            self.pending=None;self.pending_id=None
            self.field.receive(payload,time.monotonic())
            self.samples+=int(self.field.reason=="available")
        except (ValueError,TypeError): self._failed("invalid_worker_reply",time.monotonic())

    def poll(self, now, rect, *, enabled, own_pid):
        from PySide6 import QtCore
        if not enabled:
            if self.enabled: self.close()
            return
        self.enabled=True
        if self.pending is not None:
            if now-self.pending>3:
                self._failed("worker_timeout",now)
            return
        if now<self.next_at: return
        self.next_at=now+.5
        if self.process.state()==QtCore.QProcess.ProcessState.NotRunning:
            self.buffer=b""
            self.process.setWorkingDirectory(os.path.dirname(os.path.dirname(__file__)))
            self.process.start(sys.executable,["-m","desktop.background","--worker"])
        self.sequence+=1
        self.pending_id=self.sequence
        payload={"rect":list(rect),"own_pid":own_pid,"request_id":self.pending_id}
        self.pending=now
        if self.process.write((json.dumps(payload,separators=(",",":"))+"\n").encode())<0:
            self._failed("worker_write_failed",now)

    def close(self):
        self.enabled=False;self.pending=None;self.pending_id=None;self.buffer=b"";self.next_at=0.
        self.field.clear()
        self.process.kill()

    def diagnostics(self):
        return {"enabled":self.enabled,"available":self.field.reason=="available",
                "reason":self.field.reason,"samples":self.samples,"sample_hz_limit":2,
                "retained_pixels":0,"sent_to_learning":False}


def worker():
    backend=None
    try:
        # Capture/reduction never competes with the desktop's input/render loop.
        if hasattr(os,"nice"):
            try: os.nice(5)
            except OSError: pass
        if sys.platform=="darwin":
            from desktop.background_macos import MacBackground
            backend=MacBackground()
        elif sys.platform.startswith("linux") and os.environ.get("DISPLAY") and os.environ.get("XDG_SESSION_TYPE")!="wayland":
            from desktop.background_x11 import X11Background
            backend=X11Background()
        for line in sys.stdin:
            request_id=None
            try:
                if len(line)>1024: break
                data=json.loads(line);rect=data["rect"];pid=data["own_pid"];request_id=data["request_id"]
                if (len(rect)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>100000 for v in rect)
                    or not 1<=rect[2]<=4096 or not 1<=rect[3]<=4096 or type(pid) is not int or pid<=0
                    or type(request_id) is not int or not 0<request_id<=2**53): raise ValueError()
                result=backend.capture(rect,pid) if backend else {"available":False,"reason":"platform_unavailable"}
                # Explicit allowlist: no capture object, geometry, text, or identity leaves here.
                if result.get("available") and validate_colors(result.get("colors")):
                    out={"available":True,"colors":result["colors"]}
                else: out={"available":False,"reason":str(result.get("reason","unavailable"))[:80]}
            except (ValueError,KeyError,TypeError,OSError,RuntimeError): out={"available":False,"reason":"capture_unavailable"}
            out["request_id"]=request_id
            print(json.dumps(out,separators=(",",":")),flush=True)
    finally:
        if backend: backend.close()


if __name__=="__main__" and "--worker" in sys.argv:
    worker()
