"""Service recovery, session ownership and watchdog boundaries, without live units."""
import asyncio
import json
import os
from pathlib import Path
import socket
import tempfile
import time

import pytest

from terminus import supervision as control
from scripts import service_session as session
from scripts import servicectl as installer


def test_watchdog_datagrams_are_from_main_process_and_sanitize_status(tmp_path,monkeypatch):
    # macOS limits Unix socket paths to 104 bytes; pytest's normal temporary
    # directory can exceed that before a filename is added.
    directory=tempfile.TemporaryDirectory(prefix='term-',dir='/tmp')
    path=str(Path(directory.name)/'notify.sock')
    with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as listener:
        listener.bind(path);listener.settimeout(.1)
        monkeypatch.setenv('NOTIFY_SOCKET',path)
        monkeypatch.setenv('TERMINUS_SERVICE','desktop')
        monkeypatch.setenv('WATCHDOG_PID',str(os.getpid()))
        assert control.notify('responsive\nREADY=1')
        assert listener.recv(1024) == b'STATUS=responsive READY=1\nWATCHDOG=1'
        assert control.notify('degraded',healthy=False)
        assert listener.recv(1024) == b'STATUS=degraded'
        monkeypatch.setenv('WATCHDOG_PID',str(os.getpid()+10000))
        assert not control.notify('a child must not keep a frozen parent healthy')
        with pytest.raises(TimeoutError):listener.recv(1024)
        monkeypatch.delenv('WATCHDOG_PID')
        monkeypatch.delenv('TERMINUS_SERVICE')
        assert not control.notify('not a Terminus unit')


def test_missing_notify_socket_is_nonfatal(monkeypatch,tmp_path):
    monkeypatch.setenv('NOTIFY_SOCKET',str(tmp_path/'missing'))
    monkeypatch.setenv('TERMINUS_SERVICE','core')
    monkeypatch.setenv('WATCHDOG_PID',str(os.getpid()))
    assert not control.notify('ok')
    monkeypatch.delenv('NOTIFY_SOCKET')
    assert not control.notify('standalone mode')


def test_session_bridge_saves_only_graphical_metadata_privately(tmp_path):
    values={'DISPLAY':':test','XAUTHORITY':'/tmp/test-auth','XDG_SESSION_TYPE':'x11',
            'DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/1000/bus','PAIRING_TOKEN':'never copy',
            'AWS_SECRET_ACCESS_KEY':'never copy','QT_QPA_PLATFORM':'offscreen'}
    assert session.save_session(values,tmp_path) == {k:v for k,v in values.items() if k in session.SESSION_KEYS}
    path=tmp_path/'desktop-session.json'
    assert path.stat().st_mode&0o777 == 0o600
    assert session.load_session(tmp_path)['DISPLAY'] == ':test'
    assert 'never copy' not in path.read_text()
    path.write_text(json.dumps({'DISPLAY':':test','DANGEROUS':'ignored'}))
    assert session.load_session(tmp_path)=={'DISPLAY':':test'}
    path.write_text('[]')
    assert session.load_session(tmp_path)=={}
    with pytest.raises(ValueError):session.save_session({'TOKEN':'x'},tmp_path)


def test_wayland_gate_requires_an_actual_session_socket(tmp_path):
    directory=tempfile.TemporaryDirectory(prefix='term-',dir='/tmp')
    tmp_path=Path(directory.name)
    environment={'XDG_SESSION_TYPE':'wayland','XDG_RUNTIME_DIR':str(tmp_path),'WAYLAND_DISPLAY':'wayland-test'}
    assert not session.display_available(environment)
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
        listener.bind(str(tmp_path/'wayland-test'))
        assert session.display_available(environment)
    assert not session.display_available({})


def test_units_restart_every_exit_and_watch_the_actual_event_loop():
    root=Path('/example/a project%name')
    for role in control.UNITS:
        text=installer.unit_text(role,root)
        assert 'Restart=always' in text and 'StartLimitIntervalSec=0' in text
        assert 'WatchdogSec=45' in text and 'NotifyAccess=main' in text
        assert 'WatchdogSignal=SIGTERM' in text and 'TimeoutStopSec=15' in text
        assert 'KillMode=control-group' in text and 'UMask=0077' in text
        assert 'WantedBy=default.target' in text
        assert 'a project%%name' in text
        assert '--host' not in text and '--allow-network' not in text
        assert 'TERMINUS_SERVICE='+role in text
    assert 'After=terminus-core.service' in installer.unit_text('desktop',root)
    assert 'Requires=' not in installer.unit_text('desktop',root)
    bridge=installer.autostart_text(root)
    assert 'service_session.py' in bridge and ' login\n' in bridge
    assert 'X-GNOME-Autostart-enabled=true' in bridge


def test_installer_never_overwrites_an_unrelated_unit_or_symlink(tmp_path):
    root=Path('/example/Terminus');path=tmp_path/'unit.service'
    path.write_text('unrelated service\n')
    with pytest.raises(ValueError):installer.write_owned(path,installer.unit_text('core',root),root)
    assert path.read_text()=='unrelated service\n'
    link=tmp_path/'link';link.symlink_to(path)
    with pytest.raises(ValueError):installer.write_owned(link,installer.unit_text('core',root),root)
    path.unlink();text=installer.unit_text('core',root)
    installer.write_owned(path,text,root)
    installer.write_owned(path,text,root)
    assert path.read_text()==text


def test_only_this_checkout_explicit_install_can_delegate(tmp_path,monkeypatch):
    monkeypatch.setattr(control.subprocess,'run',lambda *a,**k:pytest.fail('Standalone must not call systemd'))
    assert control.delegate('core','start',tmp_path,tmp_path) is None
    marker=tmp_path/'service-install.json'
    marker.write_text(json.dumps({'version':1,'root':'/unrelated'}))
    assert not control.installed(tmp_path,tmp_path)
    marker.write_text(json.dumps({'version':1,'root':str(tmp_path.resolve())}))
    assert control.installed(tmp_path,tmp_path)
    marker.write_text('[]')
    assert not control.installed(tmp_path,tmp_path)


def test_service_status_rejects_stale_foreign_or_disconnected_body(tmp_path):
    value={'pid':7,'updated_at':99.,'platform':'xcb','visible':True,'exposed':True,
           'connected':True,'snapshot_fresh':True}
    path=tmp_path/'desktop-status.json';path.write_text(json.dumps(value))
    assert control.desktop_ready(control.desktop_status(tmp_path,7,now=100.))
    assert control.desktop_status(tmp_path,8,now=100.) is None
    assert control.desktop_status(tmp_path,7,now=110.) is None
    assert not control.desktop_ready({**value,'connected':False})
    assert not control.desktop_ready({**value,'snapshot_fresh':False})
    assert not control.desktop_ready({**value,'platform':'offscreen'})
    path.write_text('[]')
    assert control.desktop_status(tmp_path,7,now=100.) is None


def test_stop_is_an_intentional_unit_stop_without_direct_process_signals(tmp_path,monkeypatch):
    monkeypatch.setattr(control.sys,'platform','linux')
    (tmp_path/'service-install.json').write_text(json.dumps({'version':1,'root':str(tmp_path.resolve())}))
    calls=[]
    def run(command,**kwargs):
        calls.append(command)
        return type('Result',(),{'returncode':0})()
    monkeypatch.setattr(control.subprocess,'run',run)
    assert control.delegate('desktop','stop',tmp_path,tmp_path)==0
    assert calls==[['systemctl','--user','stop','terminus-desktop.service']]


def test_core_event_loop_withholds_watchdog_on_degraded_health(monkeypatch):
    from terminus import api
    messages=[]
    monkeypatch.setattr(api,'notify',lambda status,**kwargs:messages.append((status,kwargs)))
    class Dummy:
        count=0
        async def step(self):
            self.count+=1
            if self.count>2:raise asyncio.CancelledError()
        def diagnostics(self):
            return {'status':'ok' if self.count==1 else 'degraded'}
    with pytest.raises(asyncio.CancelledError):asyncio.run(api.Service.ticker(Dummy(),0.))
    assert [m[1]['healthy'] for m in messages]==[True,False]


def test_session_gate_feeds_watchdog_until_display_exists_then_execs_native(monkeypatch):
    values={'DISPLAY':':fake','XDG_SESSION_TYPE':'x11'}
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    for key,value in values.items():monkeypatch.setenv(key,value)
    available=iter([False,True]);messages=[];executions=[]
    monkeypatch.setattr(session,'load_session',lambda:values)
    monkeypatch.setattr(session,'display_available',lambda env:next(available))
    monkeypatch.setattr(session,'notify',lambda message:messages.append(message))
    monkeypatch.setattr(session.time,'sleep',lambda seconds:None)
    monkeypatch.setattr(session.os,'chdir',lambda root:None)
    class Executed(Exception):pass
    def execute(python,command):
        executions.append((python,command))
        raise Executed()
    monkeypatch.setattr(session.os,'execv',execute)
    with pytest.raises(Executed):session.run_desktop()
    assert messages[0].startswith('Waiting for graphical login')
    assert len(executions)==1
    python,command=executions[0]
    assert command[0]==python and command[1]==str(session.ROOT/'desktop/overlay.py')
    assert '--status-file' in command and '--data-dir' in command


def test_login_bridge_refreshes_session_and_starts_only_our_units(tmp_path,monkeypatch):
    monkeypatch.setattr(session,'DATA',tmp_path)
    monkeypatch.setenv('DISPLAY',':test')
    monkeypatch.setenv('XDG_SESSION_TYPE','x11')
    calls=[]
    monkeypatch.setattr(session.subprocess,'run',lambda command,**kwargs:calls.append(command))
    session.login()
    assert calls[0][:3]==['systemctl','--user','import-environment']
    assert 'DISPLAY' in calls[0] and ':test' not in calls[0]
    assert calls[1]==['systemctl','--user','start','terminus-core.service']
    assert calls[2]==['systemctl','--user','restart','terminus-desktop.service']
    assert session.load_session()['DISPLAY']==':test'
