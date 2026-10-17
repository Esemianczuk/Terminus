#!/usr/bin/env python3
"""Bridge XDG login to a supervised desktop; wait quietly without a display.

Only session connection metadata is saved. No credentials, screen pixels,
window titles, keyboard activity or organism observations are collected here.
"""
from __future__ import annotations
import argparse
import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from terminus.supervision import notify

DATA = ROOT/'.local'
SESSION_KEYS = ('DISPLAY','XAUTHORITY','WAYLAND_DISPLAY','XDG_RUNTIME_DIR',
                'DBUS_SESSION_BUS_ADDRESS','XDG_SESSION_TYPE','XDG_CURRENT_DESKTOP')


def save_session(environment, directory=None):
    values = {key:environment[key] for key in SESSION_KEYS if environment.get(key)
              and len(environment[key]) <= 4096 and '\0' not in environment[key]}
    if not (values.get('DISPLAY') or values.get('WAYLAND_DISPLAY')):
        raise ValueError('A graphical login session is required.')
    directory = Path(directory) if directory is not None else DATA
    directory.mkdir(exist_ok=True,parents=True,mode=0o700)
    path = directory/'desktop-session.json'
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(values)+'\n'); temporary.chmod(0o600); temporary.replace(path)
    return values


def load_session(directory=None):
    try:
        path = (Path(directory) if directory is not None else DATA)/'desktop-session.json'
        if path.stat().st_size > 32768:
            return {}
        values = json.loads(path.read_text())
        return {k:v for k,v in values.items() if k in SESSION_KEYS and isinstance(v,str)
                and v and len(v)<=4096 and '\0' not in v}
    except (OSError,ValueError,AttributeError):
        return {}


def display_available(environment):
    if environment.get('XDG_SESSION_TYPE') == 'wayland' or (not environment.get('DISPLAY') and environment.get('WAYLAND_DISPLAY')):
        runtime, display = environment.get('XDG_RUNTIME_DIR'),environment.get('WAYLAND_DISPLAY')
        return bool(runtime and display and Path(runtime,display).is_socket())
    if not environment.get('DISPLAY'):
        return False
    try:
        library = ctypes.CDLL(ctypes.util.find_library('X11') or 'libX11.so.6')
        library.XOpenDisplay.argtypes = [ctypes.c_char_p]; library.XOpenDisplay.restype = ctypes.c_void_p
        library.XCloseDisplay.argtypes = [ctypes.c_void_p]; library.XCloseDisplay.restype = ctypes.c_int
        connection = library.XOpenDisplay(environment['DISPLAY'].encode())
        if not connection:
            return False
        library.XCloseDisplay(connection)
        return True
    except (OSError,AttributeError):
        return False


def run_desktop():
    while True:
        os.environ.update(load_session())
        if display_available(os.environ):
            break
        notify('Waiting for graphical login; organism core remains independent')
        time.sleep(3)
    if os.environ.get('XDG_SESSION_TYPE') == 'x11':
        os.environ['QT_QPA_PLATFORM'] = 'xcb'
    # exec preserves the unit MainPID, cgroup and watchdog ownership.
    python = str(ROOT/'.venv/bin/python')
    command = [python,str(ROOT/'desktop/overlay.py'),'--data-dir',str(DATA),
               '--status-file',str(DATA/'desktop-status.json'),'--capture-file',str(DATA/'desktop-presence.png')]
    os.chdir(ROOT)
    notify('Graphical session available; starting native body')
    os.execv(python,command)


def login():
    values = save_session(os.environ)
    # Budgie does not activate graphical-session.target on this workstation.
    # XDG autostart therefore refreshes the session and starts our two units.
    subprocess.run(['systemctl','--user','import-environment',*values],check=True,timeout=10)
    subprocess.run(['systemctl','--user','start','terminus-core.service'],check=True,timeout=15)
    subprocess.run(['systemctl','--user','restart','terminus-desktop.service'],check=True,timeout=25)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('login','desktop'))
    args=parser.parse_args()
    try:
        login() if args.action == 'login' else run_desktop()
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print(f'Terminus session: {error}',file=sys.stderr)
        raise SystemExit(1)
