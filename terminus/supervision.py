"""Optional user-service integration; no daemon, model changes or shell commands.

Watchdog messages originate on each application's event loop. A wedged Qt or
asyncio loop therefore cannot keep claiming health through a separate thread.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

UNITS = {'core': 'terminus-core.service', 'desktop': 'terminus-desktop.service'}


def notify(status, *, healthy=True):
    """Nonblocking sd_notify, only for this unit's main process. No secrets."""
    address = os.environ.get('NOTIFY_SOCKET')
    if not address or os.environ.get('TERMINUS_SERVICE') not in UNITS:
        return False
    if os.environ.get('WATCHDOG_PID',str(os.getpid())) != str(os.getpid()):
        return False
    if not address.startswith(('/', '@')):
        return False
    message = 'STATUS=' + str(status).replace('\n',' ')[:240]
    if healthy:
        message += '\nWATCHDOG=1'
    if address.startswith('@'):
        address = '\0' + address[1:]
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as connection:
            connection.setblocking(False)
            connection.sendto(message.encode(),address)
        return True
    except OSError:
        return False


def installed(root, data):
    try:
        record = json.loads((Path(data)/'service-install.json').read_text())
        return record.get('version') == 1 and record.get('root') == str(Path(root).resolve())
    except (OSError,ValueError,AttributeError):
        return False


def properties(role):
    command = ['systemctl','--user','show',UNITS[role],
               '--property=MainPID,ActiveState,SubState,UnitFileState,NRestarts,WatchdogUSec,Result,WorkingDirectory']
    result = subprocess.run(command,text=True,capture_output=True,timeout=5)
    if result.returncode:
        return {}
    return dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)


def health():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8769/api/health',timeout=1) as response:
            value = json.load(response)
        return value.get('service') == 'terminus' and value.get('status') == 'ok'
    except (OSError,ValueError):
        return False


def desktop_status(data, pid, *, now=None):
    try:
        value = json.loads((Path(data)/'desktop-status.json').read_text())
        updated = value.get('updated_at')
        now = time.time() if now is None else now
        if (not isinstance(updated,(float,int)) or isinstance(updated,bool) or not math.isfinite(updated)
                or not 0 <= now-updated <= 8 or value.get('pid') != pid):
            return None
        return value
    except (OSError,ValueError,AttributeError):
        return None


def desktop_ready(value):
    return bool(value and value.get('visible') and value.get('exposed') and value.get('connected')
                and value.get('snapshot_fresh') and value.get('platform') not in {'offscreen','minimal',None})


def delegate(role, action, root, data, *, scale=None):
    """Existing manager CLIs hand control to systemd only after explicit install."""
    if not installed(root,data):
        return None
    unit = UNITS[role]
    if scale is not None and role == 'desktop' and action in {'start','restart'}:
        from PyQt5 import QtCore
        preferences = QtCore.QSettings(str(Path(data)/'desktop.ini'),QtCore.QSettings.IniFormat)
        preferences.setValue('scale',scale); preferences.sync()
        os.chmod(preferences.fileName(),0o600)
    if action != 'status':
        result = subprocess.run(['systemctl','--user',action,unit],timeout=25)
        if result.returncode:
            return result.returncode
        if action == 'stop':
            print(f'{unit} intentionally stopped. Automatic crash recovery resumes on its next start.')
            return 0
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            info = properties(role)
            if role == 'core' and info.get('ActiveState') == 'active' and health():
                print('Terminus core is healthy and supervised by systemd.')
                return 0
            if role == 'desktop' and desktop_ready(desktop_status(data,int(info.get('MainPID') or 0))):
                print('Terminus is present on the desktop and supervised by systemd.')
                return 0
            time.sleep(.25)
        print(f'{unit} was requested but readiness is not yet confirmed; inspect its journal.')
        return 1
    info = properties(role)
    if role == 'desktop':
        value = desktop_status(data,int(info.get('MainPID') or 0))
        print(json.dumps({'service':info, 'desktop':value},indent=2))
        return 0 if info.get('ActiveState') == 'active' and desktop_ready(value) else 1
    ready = info.get('ActiveState') == 'active' and health()
    print(json.dumps({'service':info,'healthy':ready},indent=2))
    return 0 if ready else 1
