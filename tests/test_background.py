"""Privacy boundary, stale sensing and finite color interpolation."""
import math
import io
import json
from types import SimpleNamespace

from PySide6 import QtCore

from desktop import background
from desktop.background import BackgroundSampler, ColorField, validate_colors


def test_palette_strict_and_bounded():
    assert validate_colors([[0.,.5,1.]]*4)
    for value in (None,[[0,0,0]]*3,[[True,0,0]]*4,[[math.nan,0,0]]*4,[[2,0,0]]*4):
        assert not validate_colors(value)


def test_colors_ease_and_stale_confidence_disappears():
    field=ColorField();field.sample(0)
    field.receive({"available":True,"colors":[[1.,0.,0.]]*4},0)
    early=field.sample(.1)
    assert 0<early["confidence"]<.2
    assert .12<early["colors"][0][0]<1
    for index in range(1,60): field.sample(index*.1)
    assert field.sample(6)["confidence"]<.02
    field.clear()
    assert field.sample(7)["confidence"]==0
    assert field.reason=="disabled"


def test_bad_payload_cannot_keep_previous_palette_active():
    field=ColorField();field.sample(0)
    field.receive({"available":True,"colors":[[1.,0.,0.]]*4},0)
    field.sample(.2)
    field.receive({"available":True,"colors":[[float("inf"),0,0]]*4},.3)
    assert not math.isfinite(field.observed)


class Process:
    def __init__(self):
        self.output=b"";self.kills=0;self.starts=0;self.writes=[]
        self.running=QtCore.QProcess.ProcessState.NotRunning
    def readAllStandardOutput(self):
        result=self.output;self.output=b"";return result
    def kill(self):
        self.kills+=1;self.running=QtCore.QProcess.ProcessState.NotRunning
    def state(self): return self.running
    def setWorkingDirectory(self,path): pass
    def start(self,*arguments):
        self.starts+=1;self.running=QtCore.QProcess.ProcessState.Running
    def write(self,data): self.writes.append(data);return len(data)


def sampler():
    value=BackgroundSampler.__new__(BackgroundSampler)
    value.process=Process();value.field=ColorField();value.pending=None;value.pending_id=None
    value.sequence=0;value.next_at=0.;value.buffer=b"";value.enabled=False;value.samples=0
    return value


def reply(value,**payload):
    value.process.output=json.dumps(payload).encode()+b'\n'
    value._read()


def test_late_reply_after_close_cannot_reactivate_screen_colors():
    value=sampler();value.poll(1,(0,0,440,340),enabled=True,own_pid=123)
    request_id=value.pending_id
    value.close()
    reply(value,request_id=request_id,available=True,colors=[[1.,0.,0.]]*4)
    assert value.field.reason=='disabled' and value.samples==0
    assert value.field.confidence==0 and value.pending is None
    value._finished()
    assert value.field.reason=='disabled'


def test_timeout_discards_fragments_and_obeys_restart_cooldown(monkeypatch):
    now=[1.]
    monkeypatch.setattr(background.time,'monotonic',lambda:now[0])
    value=sampler();value.poll(1,(0,0,440,340),enabled=True,own_pid=123)
    first=value.pending_id;value.buffer=b'{"available":'
    now[0]=4.1;value.poll(now[0],(0,0,440,340),enabled=True,own_pid=123)
    assert value.pending is None and value.buffer==b''
    assert value.field.reason=='worker_timeout' and value.process.kills==1
    reply(value,request_id=first,available=True,colors=[[1.,0.,0.]]*4)
    assert value.samples==0
    value._finished()
    value.poll(34,(0,0,440,340),enabled=True,own_pid=123)
    assert value.process.starts==1
    now[0]=34.2;value.poll(now[0],(0,0,440,340),enabled=True,own_pid=123)
    assert value.process.starts==2 and value.pending_id>first
    # Even after restarting, an old request cannot poison this new response.
    reply(value,request_id=first,available=True,colors=[[1.,0.,0.]]*4)
    assert value.field.reason=='invalid_worker_reply' and value.samples==0


def test_permission_denial_clears_availability_without_restart_loop():
    value=sampler();value.poll(1,(0,0,440,340),enabled=True,own_pid=123)
    reply(value,request_id=value.pending_id,available=False,reason='screen_recording_permission_required')
    assert value.field.reason=='screen_recording_permission_required'
    assert value.process.kills==0 and value.pending is None
    value.poll(1.6,(0,0,440,340),enabled=True,own_pid=123)
    assert value.process.starts==1


def test_failed_start_does_not_retry_every_frame(monkeypatch):
    monkeypatch.setattr(background.time,'monotonic',lambda:10.)
    value=sampler();value.poll(10,(0,0,440,340),enabled=True,own_pid=123)
    value._process_error(QtCore.QProcess.ProcessError.FailedToStart)
    for now in (10.1,11,20,39.9):value.poll(now,(0,0,440,340),enabled=True,own_pid=123)
    assert value.process.starts==1 and value.field.reason=='worker_start_failed'


def test_unsolicited_extra_reply_is_rejected_instead_of_buffered():
    value=sampler();value.poll(1,(0,0,440,340),enabled=True,own_pid=123)
    record=json.dumps(dict(request_id=value.pending_id,available=True,colors=[[1.,0.,0.]]*4)).encode()+b'\n'
    value.process.output=record*2;value._read()
    assert value.field.reason=='invalid_worker_reply' and value.buffer==b''
    assert value.samples==0


def test_worker_protocol_removes_images_text_geometry_and_identity(monkeypatch):
    payload={'request_id':7,'rect':[0,0,440,340],'own_pid':123}
    closed=[]
    class Backend:
        def capture(self,rect,own_pid):
            assert rect==payload['rect'] and own_pid==123
            return {'available':True,'colors':[[.1,.2,.3]]*4,'image':'private pixels',
                    'title':'private title','rect':rect,'owner':own_pid}
        def close(self):closed.append(True)
    monkeypatch.setitem(__import__('sys').modules,'desktop.background_macos',SimpleNamespace(MacBackground=Backend))
    monkeypatch.setattr(background.sys,'platform','darwin')
    monkeypatch.setattr(background.sys,'stdin',io.StringIO(json.dumps(payload)+'\n'))
    output=io.StringIO();monkeypatch.setattr(background.sys,'stdout',output)
    monkeypatch.setattr(background.os,'nice',lambda _:None)
    background.worker()
    assert json.loads(output.getvalue())=={'available':True,'colors':[[.1,.2,.3]]*4,'request_id':7}
    assert closed==[True]
