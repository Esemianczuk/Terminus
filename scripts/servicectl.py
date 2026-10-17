#!/usr/bin/env python3
"""Install and control Terminus user services, preserving this organism's data."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from terminus.supervision import UNITS,delegate,installed,set_paused
from scripts.service_session import save_session


def quote(value):
    return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'


def unit_text(role,root):
    root=Path(root); python=root/'.venv/bin/python'; data=root/'.local'
    if any(c in str(root) for c in '\n\r\0'):
        raise ValueError('Service paths cannot contain control characters.')
    command = ([python,'-m','terminus','serve','--data-dir',data] if role=='core' else
               [python,root/'scripts/service_session.py','desktop'])
    dependencies = 'Wants=terminus-core.service\nAfter=terminus-core.service\n' if role == 'desktop' else ''
    return f'''# Managed by Terminus: {root}
[Unit]
Description=Terminus {'persistent organism core' if role=='core' else 'resident desktop companion'}
{dependencies}StartLimitIntervalSec=0

[Service]
Type=exec
WorkingDirectory={str(root).replace('%','%%')}
ExecStart={' '.join(quote(p) for p in command)}
Environment=PYTHONUNBUFFERED=1
Environment=TERMINUS_SERVICE={role}
Restart=always
RestartSec=3
NotifyAccess=main
WatchdogSec=45
WatchdogSignal=SIGTERM
TimeoutStopSec=15
KillMode=control-group
LimitCORE=0
UMask=0077
SyslogIdentifier=terminus-{role}

[Install]
WantedBy=default.target
'''


def autostart_text(root):
    root=Path(root)
    # Desktop Entry Exec quoting also requires literal dollars and backticks.
    def argument(value):
        return quote(value).replace('$','\\$').replace('`','\\`')
    return f'''# Managed by Terminus: {root}
[Desktop Entry]
Type=Application
Name=Terminus desktop companion
Comment=Restore the same Terminus at login with automatic crash recovery
Exec={argument(root/'.venv/bin/python')} {argument(root/'scripts/service_session.py')} login
Terminal=false
X-GNOME-Autostart-enabled=true
'''


def shortcut_text(root):
    root=Path(root)
    return f'''# Managed by Terminus: {root}
[Desktop Entry]
Type=Application
Name=Bring Back Terminus
Comment=Make sure the little fella is healthy and here on your desktop
Exec={quote(root/'.venv/bin/python')} {quote(root/'scripts/bring_back.py')}
Icon={root/'web/assets/terminus-refined.png'}
Terminal=false
StartupNotify=false
Categories=Utility;
'''


def presence_units(root):
    root=Path(root)
    return {
        'terminus-presence.service':f'''# Managed by Terminus: {root}
[Unit]
Description=Keep Terminus present by restoring accidentally stopped services

[Service]
Type=oneshot
WorkingDirectory={str(root).replace('%','%%')}
ExecStart={quote(root/'.venv/bin/python')} {quote(root/'scripts/bring_back.py')} --guardian
TimeoutStartSec=30
UMask=0077
''',
        'terminus-presence.timer':f'''# Managed by Terminus: {root}
[Unit]
Description=Check that Terminus services remain running

[Timer]
OnBootSec=30
OnUnitInactiveSec=30
AccuracySec=5
Unit=terminus-presence.service

[Install]
WantedBy=timers.target
'''}


def desktop_directory():
    try:
        result=subprocess.run(['xdg-user-dir','DESKTOP'],capture_output=True,text=True,timeout=5,check=True)
        path=Path(result.stdout.strip())
        if path.is_absolute() and path!=Path.home():
            return path
    except (OSError,ValueError,subprocess.SubprocessError):
        pass
    return Path.home()/'Desktop'


def write_owned(path,text,root):
    path=Path(path)
    marker=f'# Managed by Terminus: {root}\n'
    if path.is_symlink() or (path.exists() and not path.read_text().startswith(marker)):
        raise ValueError(f'Refusing to replace an unrelated file: {path}')
    path.parent.mkdir(exist_ok=True,parents=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(text); temporary.chmod(0o644); temporary.replace(path)


def install(root=ROOT,config=None):
    root=Path(root).resolve();data=root/'.local'
    if root != ROOT:
        raise ValueError('Run servicectl.py from the checkout being installed; legacy handoff must match that checkout.')
    if not (root/'.venv/bin/python').is_file() or not (data/'organism.sqlite3').is_file():
        raise ValueError('An existing Terminus runtime and memory database are required.')
    config=Path(config) if config else Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))
    files={config/'systemd/user'/unit:unit_text(role,root) for role,unit in UNITS.items()}
    files.update({config/'systemd/user'/unit:text for unit,text in presence_units(root).items()})
    files[config/'autostart/terminus.desktop']=autostart_text(root)
    shortcut=desktop_directory()/'Bring Back Terminus.desktop'
    files[shortcut]=shortcut_text(root)
    applications=Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'applications'
    files[applications/'terminus-bring-back.desktop']=shortcut_text(root)
    # Check every destination before changing any files or running services.
    for path in files:
        if path.is_symlink() or (path.exists() and not path.read_text().startswith(f'# Managed by Terminus: {root}\n')):
            raise ValueError(f'Refusing to replace an unrelated file: {path}')
    save_session(os.environ,data)
    for path,text in files.items():
        write_owned(path,text,root)
    shortcut.chmod(0o755)
    try:
        subprocess.run(['gio','set',str(shortcut),'metadata::trusted','true'],check=True,timeout=5)
    except (OSError,subprocess.SubprocessError):
        print('Desktop shortcut created; the desktop may ask to allow launching it once.')
    subprocess.run(['systemctl','--user','daemon-reload'],check=True,timeout=15)
    subprocess.run(['systemctl','--user','enable',*UNITS.values(),'terminus-presence.timer'],check=True,timeout=15)
    # Gracefully hand off only the legacy managers' verified owned processes.
    from scripts import desktopctl,termctl
    if desktopctl.stop(desktopctl.owned_record()) or termctl.stop(termctl.load_record()):
        raise RuntimeError('Could not safely hand off the legacy processes; no new body was launched.')
    marker=data/'service-install.json'
    temporary=marker.with_suffix('.json.tmp')
    temporary.write_text(json.dumps({'version':1,'root':str(root),'units':UNITS})+'\n')
    temporary.chmod(0o600);temporary.replace(marker)
    subprocess.run(['systemctl','--user','start',*UNITS.values(),'terminus-presence.timer'],check=True,timeout=25)
    print('Enabled Terminus services, periodic presence checks, and the Bring Back Terminus desktop shortcut.')
    return delegate('desktop','start',root,data)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('install','status','start','stop','restart','disable'))
    parser.add_argument('--part',choices=('all','core','desktop'),default='all')
    args=parser.parse_args()
    try:
        if sys.platform == 'darwin':
            from terminus.platform_macos import main as mac_main
            return mac_main(ROOT,args)
        if args.action=='install':
            return install()
        if not installed(ROOT,ROOT/'.local'):
            raise ValueError('This checkout has no installed Terminus services; run install first.')
        roles=tuple(UNITS) if args.part=='all' else (args.part,)
        if args.action=='disable':
            for role in roles:
                set_paused(role,ROOT/'.local',True)
            if args.part=='all':
                subprocess.run(['systemctl','--user','disable','--now','terminus-presence.timer'],check=True,timeout=15)
                subprocess.run(['systemctl','--user','stop','terminus-presence.service'],check=True,timeout=15)
            subprocess.run(['systemctl','--user','disable','--now',*(UNITS[r] for r in roles)],check=True,timeout=25)
            if 'desktop' in roles:
                config=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))
                path=config/'autostart/terminus.desktop'
                if path.is_file() and path.read_text().startswith(f'# Managed by Terminus: {ROOT}\n'):
                    path.unlink()
            return 0
        if args.action=='stop':
            roles=tuple(reversed(roles))
        result=0
        for role in roles:
            code=delegate(role,args.action,ROOT,ROOT/'.local')
            if code is None:
                raise ValueError('Install services with: python scripts/servicectl.py install')
            result=max(result,code)
        return result
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print(f'Terminus services: {error}',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
