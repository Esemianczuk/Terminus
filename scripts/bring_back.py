#!/usr/bin/env python3
"""Desktop button and quiet periodic guardian for this Terminus checkout."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from terminus import filelock as fcntl
from terminus import supervision as control
from scripts.service_session import save_session

TIMER='terminus-presence.timer'


def run(*arguments):
    subprocess.run(['systemctl','--user',*arguments],check=True,timeout=25)


def owned_properties(role):
    info=control.properties(role)
    if info.get('WorkingDirectory')!=str(ROOT):
        raise RuntimeError(f'{control.UNITS[role]} is missing or belongs to another checkout.')
    return info


def guardian():
    """Start enabled components stopped accidentally; respect explicit Quit."""
    data=ROOT/'.local'
    if not control.installed(ROOT,data) or control.is_paused('core',data):
        return
    missing=[]
    for role,unit in control.UNITS.items():
        if control.is_paused(role,data):
            continue
        info=owned_properties(role)
        if info.get('UnitFileState')=='enabled' and info.get('ActiveState') in {'inactive','failed'}:
            missing.append(unit)
    if missing:
        run('start',*missing)
        print('Restored stopped Terminus services: '+', '.join(missing),flush=True)


def ready():
    if not control.health():
        return False
    info=owned_properties('desktop')
    return (info.get('ActiveState')=='active' and
            control.desktop_ready(control.desktop_status(ROOT/'.local',int(info.get('MainPID') or 0))))


def wait_ready(seconds):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if ready():
            return True
        time.sleep(.25)
    return False


def bring_back():
    data=ROOT/'.local'
    if not control.installed(ROOT,data):
        raise RuntimeError('Run scripts/servicectl.py install to install Terminus services first.')
    save_session(os.environ,data)
    for role in control.UNITS:
        owned_properties(role)
        control.set_paused(role,data,False)
    run('enable',*control.UNITS.values(),TIMER)
    run('start',*control.UNITS.values(),TIMER)
    if wait_ready(8):
        return
    # A deliberate button press can recover a wedged component immediately;
    # the timer leaves active processes to their event-loop watchdogs.
    if not control.health():
        run('restart',control.UNITS['core'])
    run('restart',control.UNITS['desktop'])
    if not wait_ready(15):
        raise RuntimeError('Services were started, but desktop presence is not yet confirmed. Check the Terminus service journal.')


def notification(message, *, failure=False):
    try:
        if sys.platform == 'win32':
            return  # Recovery is windowless; details are in the local service log.
        if sys.platform == 'darwin':
            import json
            script='display notification '+json.dumps(message)+' with title \"Terminus\"'
            subprocess.run(['osascript','-e',script],timeout=5,check=False)
            return
        subprocess.run(['notify-send','--app-name=Terminus','--icon='+str(ROOT/'web/assets/terminus-refined.png'),
                        '--urgency='+('normal' if failure else 'low'),'Terminus',message],timeout=5,check=False)
    except (OSError,subprocess.SubprocessError):
        pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guardian',action='store_true',help='Quietly restore enabled, unpaused services')
    args=parser.parse_args()
    data=ROOT/'.local';data.mkdir(exist_ok=True,mode=0o700)
    try:
        with (data/'bring-back.lock').open('a') as lock:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                if not args.guardian:
                    notification('Already checking on the little fella.')
                return 0
            if args.guardian:
                if sys.platform == 'win32':
                    from terminus.platform_windows import guardian as windows_guardian
                    windows_guardian(ROOT)
                elif sys.platform == 'darwin':
                    from terminus.platform_macos import guardian as mac_guardian
                    mac_guardian(ROOT)
                else:
                    guardian()
            else:
                if sys.platform == 'win32':
                    from terminus.platform_windows import bring_back as windows_bring_back
                    if windows_bring_back(ROOT):raise RuntimeError('Desktop presence is not yet confirmed.')
                elif sys.platform == 'darwin':
                    from terminus.platform_macos import bring_back as mac_bring_back
                    if mac_bring_back(ROOT):raise RuntimeError('Desktop presence is not yet confirmed.')
                else:
                    bring_back()
                notification('He’s here. His core is healthy and he’s visible on your desktop.')
                print('Terminus is visible, connected, and protected by automatic recovery.')
        return 0
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print(f'Terminus: {error}',file=sys.stderr)
        if not args.guardian:
            notification(str(error),failure=True)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
