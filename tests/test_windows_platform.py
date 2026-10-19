"""Portable contract checks plus native locking tests on Windows CI."""
import json
import subprocess
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from terminus import filelock,platform_windows as windows
from terminus.runtime import python_path
from scripts import update


def test_tasks_use_interactive_unprivileged_sessions_without_passwords(tmp_path,monkeypatch):
    monkeypatch.setattr(sys,'platform','win32')
    for role in windows.ROLES:
        root=ET.fromstring(windows.definition(role,tmp_path,'TEST\\Person'))
        def text(name):return root.find('.//{*}'+name).text
        assert text('LogonType')=='InteractiveToken'
        assert text('RunLevel')=='LeastPrivilege'
        assert text('MultipleInstancesPolicy')=='IgnoreNew'
        assert text('WorkingDirectory')==str(tmp_path)
        assert text('Command').endswith('pythonw.exe')
        assert text('Description')==windows.marker(tmp_path)
        assert 'Password' not in windows.definition(role,tmp_path,'TEST\\Person')
        if role in {'core','desktop'}:assert text('ExecutionTimeLimit')=='PT0S'


def test_runtime_paths_follow_host(monkeypatch,tmp_path):
    monkeypatch.setattr(sys,'platform','win32')
    assert python_path(tmp_path)==tmp_path/'.venv/Scripts/python.exe'
    monkeypatch.setattr(sys,'platform','darwin')
    assert python_path(tmp_path)==tmp_path/'.venv/bin/python'


def test_lock_excludes_a_second_process_and_releases_on_close(tmp_path):
    path=tmp_path/'lock'
    code="from terminus import filelock as f; import sys; h=open(sys.argv[1],'a'); f.flock(h,f.LOCK_EX|f.LOCK_NB)"
    with path.open('a') as handle:
        filelock.flock(handle,filelock.LOCK_EX|filelock.LOCK_NB)
        result=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True)
        assert result.returncode!=0 and b'BlockingIOError' in result.stderr
    assert subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True).returncode==0


def test_document_changes_do_not_restart_the_creature():
    assert not update.needs_rebuild(['README.md','docs/SETUP.md'])
    assert update.needs_rebuild(['desktop/gpu.py'])
    assert update.needs_rebuild(['uv.lock'])


def test_auto_update_preserves_dirty_source_and_does_not_touch_services(tmp_path,monkeypatch):
    calls=[]
    def run(*args):
        calls.append(args)
        return subprocess.CompletedProcess(args,0,' M desktop/overlay.py\n')
    monkeypatch.setattr(update,'run',run)
    assert update.update(tmp_path,automatic=True)==0
    assert calls==[('git','status','--porcelain')]
    assert json.loads((tmp_path/'update-status.json').read_text())['state']=='deferred'


def test_windows_observer_never_polls_or_hooks_keys():
    source=(Path(__file__).parents[1]/'desktop/perception_windows.py').read_text()
    for name in ('GetAsyncKeyState','GetKeyboardState','SetWindowsHookEx','RegisterRawInputDevices','GetWindowText','SendInput'):
        assert name not in source


def test_native_mouse_activation_guard_uses_the_actual_win32_message_layout():
    import ctypes as C
    from ctypes import wintypes as W
    from types import SimpleNamespace
    from desktop.windows import WindowsPresence
    message=W.MSG();message.hWnd=77;message.message=0x21
    owner=SimpleNamespace(hwnd=77)
    assert WindowsPresence.nativeEventFilter(owner,b'windows_generic_MSG',C.addressof(message))==(True,3)
    message.hWnd=88
    assert WindowsPresence.nativeEventFilter(owner,b'windows_generic_MSG',C.addressof(message))==(False,0)
