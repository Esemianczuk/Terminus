#!/usr/bin/env python3
"""Fast-forward from GitHub, preserving private memory and intentional pauses."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from terminus import filelock
from terminus.runtime import python_path,find_uv,find_git


def run(*args):
    if args[0]=='git':args=(find_git(),*args[1:])
    return subprocess.run(list(map(str,args)),cwd=ROOT,check=True,text=True,capture_output=True,timeout=600)


def write_status(data,**values):
    path=data/'update-status.json';temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(dict(checked_at=time.time(),**values))+'\n');temporary.replace(path)


def needs_rebuild(paths):
    return any(not (p.startswith(('docs/','.github/')) or p in {'README.md','LICENSE','.gitignore'}) for p in paths)


def schedule(enabled):
    data=ROOT/'.local';data.mkdir(exist_ok=True)
    path=data/'update-config.json';path.write_text(json.dumps({'enabled':enabled})+'\n')
    if sys.platform=='win32':
        from terminus.platform_windows import register,task_operation
        if enabled:register('updates',ROOT)
        else:
            task_operation('updates','Disable',ROOT)
    elif sys.platform=='darwin':
        import plistlib
        from terminus.platform_macos import definition,paths,call,domain,LABELS
        if enabled:
            p=paths('updates')
            if p.exists() and plistlib.loads(p.read_bytes()).get('WorkingDirectory')!=str(ROOT):raise ValueError('Unrelated update job')
            p.write_bytes(plistlib.dumps(definition('updates',ROOT)));p.chmod(0o600)
            call('bootout',domain()+'/'+LABELS['updates'],check=False)
            call('enable',domain()+'/'+LABELS['updates']);call('bootstrap',domain(),str(p))
        else:call('bootout',domain()+'/'+LABELS['updates'],check=False)
    else:
        from scripts.servicectl import write_owned,quote
        config=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'systemd/user'
        header=f'# Managed by Terminus: {ROOT}\n'
        service=header+f'''[Unit]
Description=Update Terminus source without replacing local memories
[Service]
Type=oneshot
WorkingDirectory={str(ROOT).replace('%','%%')}
ExecStart={quote(python_path(ROOT))} {quote(ROOT/'scripts/update.py')} --automatic
TimeoutStartSec=900
UMask=0077
'''
        timer=header+'''[Unit]
Description=Check Terminus source on GitHub hourly
[Timer]
OnBootSec=300
OnUnitInactiveSec=3600
RandomizedDelaySec=300
[Install]
WantedBy=timers.target
'''
        if enabled:
            for name,text in (('terminus-updates.service',service),('terminus-updates.timer',timer)):
                write_owned(config/name,text,ROOT)
            run('systemctl','--user','daemon-reload');run('systemctl','--user','enable','--now','terminus-updates.timer')
        else:run('systemctl','--user','disable','--now','terminus-updates.timer')
    print('Automatic source updates '+('enabled (hourly).' if enabled else 'disabled.'))


def update(data,automatic=False):
    def defer(reason):
        write_status(data,state='deferred',reason=reason)
        print(reason)
        return 0 if automatic else 1
    if run('git','status','--porcelain').stdout.strip():
        return defer('Local source edits exist; no files or services were changed.')
    if run('git','branch','--show-current').stdout.strip()!='main':
        return defer('Updates follow main only. Switch branches deliberately before updating.')
    uv=find_uv()  # Preflight before changing services or source.
    run('git','fetch','origin','main')
    old=run('git','rev-parse','HEAD').stdout.strip()
    target=run('git','rev-parse','origin/main').stdout.strip()
    pending=data/'rebuild-pending.json'
    retry=pending.exists() and json.loads(pending.read_text()).get('commit')==target
    if old==target and not retry:
        write_status(data,state='current',commit=old);print('Already current.');return 0
    ancestry=subprocess.run([find_git(),'merge-base','--is-ancestor',old,target],cwd=ROOT,timeout=10)
    if ancestry.returncode:return defer('Local main has diverged; no commits were discarded.')
    paths=run('git','diff','--name-only',old,target).stdout.splitlines()
    if not retry and not needs_rebuild(paths):
        run('git','merge','--ff-only',target)
        write_status(data,state='updated-without-restart',commit=target)
        print('Updated documentation. The creature stayed running.');return 0
    database=data/'organism.sqlite3'
    if database.is_file():
        backups=data/'backups';backups.mkdir(exist_ok=True,mode=0o700)
        backup=backups/('before-update-'+str(time.time_ns())+'.sqlite3')
        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as source:
            with sqlite3.connect(backup) as destination: source.backup(destination)
        backup.chmod(0o600)
    python=python_path(ROOT)
    installed=(data/'service-install.json').is_file()
    paused={role:(data/(role+'-paused')).exists() for role in ('core','desktop')}
    stopped=False
    try:
        if installed:
            run(python,'scripts/servicectl.py','stop');stopped=True
        pending.write_text(json.dumps({'commit':target})+'\n')
        run('git','merge','--ff-only',target)
        run(uv,'sync','--frozen','--extra','desktop')
        run(python,'scripts/servicectl.py','install')
        for role,value in paused.items():
            if value:run(python,'scripts/servicectl.py','stop','--part',role)
        pending.unlink(missing_ok=True)
        write_status(data,state='updated',commit=target,previous=old)
        print('Updated and rebuilt. Local memory was preserved.');return 0
    except BaseException:
        if stopped:
            for role,value in paused.items():
                if not value:
                    subprocess.run([str(python),'scripts/servicectl.py','start','--part',role],cwd=ROOT,check=False,timeout=60)
        write_status(data,state='failed',commit=target,previous=old)
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--enable-auto',action='store_true');group.add_argument('--disable-auto',action='store_true')
    group.add_argument('--automatic',action='store_true');group.add_argument('--status',action='store_true')
    args=parser.parse_args(argv);data=ROOT/'.local';data.mkdir(exist_ok=True)
    config=data/'update-config.json'
    enabled=json.loads(config.read_text()).get('enabled',False) if config.exists() else False
    if args.enable_auto or args.disable_auto:schedule(args.enable_auto);return 0
    if args.status:
        status=data/'update-status.json'
        print(json.dumps({'automatic':enabled,'last_check':json.loads(status.read_text()) if status.exists() else None},indent=2));return 0
    if args.automatic and not enabled:return 0
    with (data/'update.lock').open('a') as lock:
        try:filelock.flock(lock,filelock.LOCK_EX|filelock.LOCK_NB)
        except BlockingIOError:print('An update is already running.');return 0
        return update(data,args.automatic)


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print('Update failed: '+str(error),file=sys.stderr);raise SystemExit(1)
