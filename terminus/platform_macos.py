"""Per-user launchd services and a Finder shortcut. No system-wide installation."""
from __future__ import annotations
import json
import os
from pathlib import Path
import plistlib
import shlex
import subprocess
import tempfile
import time

LABELS={r:'org.terminus.'+r for r in ('core','desktop','presence','collective')}


def domain():
    return f'gui/{os.getuid()}'


def call(*args,check=True):
    return subprocess.run(['launchctl',*args],capture_output=True,text=True,timeout=25,check=check)


def paths(role):
    return Path.home()/'Library/LaunchAgents'/(LABELS[role]+'.plist')


def properties(role):
    path=paths(role)
    if not path.is_file():return {}
    data=plistlib.loads(path.read_bytes())
    result=call('print',domain()+'/'+LABELS[role],check=False)
    pid=0
    for line in result.stdout.splitlines():
        if line.strip().startswith('pid = '):pid=int(line.split('=',1)[1])
    return {'WorkingDirectory':data.get('WorkingDirectory',''),'MainPID':str(pid),
            'ActiveState':'active' if pid else 'inactive','UnitFileState':'enabled',
            'SubState':'running' if pid else 'waiting','Label':LABELS[role]}


def start(role):
    label=domain()+'/'+LABELS[role]
    if call('print',label,check=False).returncode:
        call('enable',label)
        call('bootstrap',domain(),str(paths(role)))
    call('kickstart',label)


def action(role,operation,root,data,scale=None):
    from .supervision import set_paused,desktop_status,desktop_ready,health
    label=domain()+'/'+LABELS[role]
    if operation in {'start','restart','stop'}:
        set_paused(role,data,operation=='stop')
        if role=='desktop' and operation!='stop':
            set_paused('core',data,False);start('core')
    if operation=='stop':
        result=call('bootout',label,check=False)
        return 0 if result.returncode==0 or not int(properties(role).get('MainPID',0)) else 1
    if operation in {'start','restart'}:
        start(role)
        if operation=='restart':call('kickstart','-k',label)
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            p=properties(role)
            if role=='core' and health() or role=='desktop' and desktop_ready(desktop_status(data,int(p.get('MainPID') or 0))):
                print(f'Terminus {role} is running under launchd.');return 0
            time.sleep(.25)
        return 1
    p=properties(role)
    view=desktop_status(data,int(p.get('MainPID') or 0)) if role=='desktop' else None
    ready=health() if role=='core' else desktop_ready(view)
    print(json.dumps({'service':p,'healthy':ready,'desktop':view},indent=2))
    return 0 if ready else 1


def definition(role,root):
    root=Path(root);python=str(root/'.venv/bin/python');data=root/'.local'
    commands={'core':[python,'-m','terminus','serve','--data-dir',str(data)],
              # The GPU child is created before the native panel so Qt chooses
              # a Metal-capable backing store. The normal crash guard retains
              # raster recovery if hardware rendering is unavailable.
              'desktop':[python,str(root/'desktop/overlay.py'),'--renderer','auto','--data-dir',str(data),
                         '--status-file',str(data/'desktop-status.json'),'--capture-file',str(data/'desktop-presence.png')],
              'presence':[python,str(root/'scripts/bring_back.py'),'--guardian'],
              'collective':[python,str(root/'scripts/collective.py'),'sync']}
    definition={'Label':LABELS[role],'ProgramArguments':commands[role],'WorkingDirectory':str(root),
                'RunAtLoad':True,'LimitLoadToSessionType':'Aqua','ThrottleInterval':3,'ExitTimeOut':15,
                'EnvironmentVariables':{'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
                                        'PYTHONUNBUFFERED':'1','TERMINUS_SERVICE':role,
                                        'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1',
                                        'VECLIB_MAXIMUM_THREADS':'1','MKL_NUM_THREADS':'1'},
                'StandardOutPath':str(data/('macos-'+role+'.log')),
                'StandardErrorPath':str(data/('macos-'+role+'.log')),'Umask':63}
    if role in {'core','desktop'}:definition['KeepAlive']=True
    else:definition['StartInterval']=30 if role=='presence' else 600
    return definition


def shortcut(root):
    root=Path(root);app=Path.home()/'Desktop/Bring Back Terminus.app'
    marker=app/'Contents/terminus-root.txt'
    if app.exists() and (not marker.is_file() or marker.read_text().strip()!=str(root)):
        raise ValueError('Refusing to overwrite an unrelated desktop application.')
    executable=app/'Contents/MacOS/bring-back';executable.parent.mkdir(parents=True,exist_ok=True)
    resources=app/'Contents/Resources';resources.mkdir(exist_ok=True)
    marker.write_text(str(root)+'\n')
    executable.write_text('#!/bin/zsh\nexec '+shlex.quote(str(root/'.venv/bin/python'))+' '+shlex.quote(str(root/'scripts/bring_back.py'))+'\n')
    executable.chmod(0o755)
    info={'CFBundleIdentifier':'org.terminus.bring-back','CFBundleName':'Bring Back Terminus',
          'CFBundleExecutable':'bring-back','CFBundlePackageType':'APPL','LSUIElement':True,
          'CFBundleIconFile':'Terminus.icns','NSHighResolutionCapable':True}
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    with tempfile.TemporaryDirectory() as temporary:
        icons=Path(temporary)/'Terminus.iconset';icons.mkdir()
        for size in (16,32,128,256,512):
            for scale in (1,2):
                name=f'icon_{size}x{size}'+('@2x' if scale==2 else '')+'.png'
                subprocess.run(['sips','-z',str(size*scale),str(size*scale),str(root/'web/assets/terminus-refined.png'),
                                '--out',str(icons/name)],check=True,stdout=subprocess.DEVNULL,timeout=10)
        subprocess.run(['iconutil','-c','icns',str(icons),'-o',str(resources/'Terminus.icns')],check=True,timeout=15)
    return app


def install(root):
    root=Path(root).resolve();data=root/'.local';data.mkdir(exist_ok=True,mode=0o700)
    if call('print',domain(),check=False).returncode:
        raise ValueError('Sign into the macOS desktop before installing its launch agents.')
    for role in ('core','desktop','presence'):
        path=paths(role)
        if path.exists() and plistlib.loads(path.read_bytes()).get('WorkingDirectory')!=str(root):
            raise ValueError('Refusing to replace a launch agent from another checkout.')
    for role in ('core','desktop','presence'):
        path=paths(role);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(plistlib.dumps(definition(role,root)));path.chmod(0o600)
    shortcut(root)
    marker=data/'service-install.json'
    marker.write_text(json.dumps({'version':1,'root':str(root),'platform':'darwin'})+'\n');marker.chmod(0o600)
    from .supervision import set_paused
    for role in ('core','desktop'):
        set_paused(role,data,False)
        call('bootout',domain()+'/'+LABELS[role],check=False)
        start(role)
    start('presence')
    return action('desktop','start',root,data)


def guardian(root):
    from .supervision import is_paused,desktop_status,health
    root=Path(root);data=root/'.local'
    if is_paused('core',data):return
    failure_path=data/'macos-health.json'
    try:failures=json.loads(failure_path.read_text())
    except (OSError,ValueError):failures={}
    for role in ('core','desktop'):
        if is_paused(role,data):continue
        p=properties(role)
        if p.get('WorkingDirectory')!=str(root):continue
        pid=int(p.get('MainPID') or 0)
        if not pid:start(role);continue
        if role=='core':
            count=failures.get('core_failures',0) if failures.get('core_pid')==pid else 0
            count=0 if health() else count+1
            failures={'core_pid':pid,'core_failures':count}
            if count>=2:
                call('kickstart','-k',domain()+'/'+LABELS[role]);failures['core_failures']=0
        if role=='desktop':
            # A stalled native event loop stops writing this heartbeat.
            try:
                view=json.loads((data/'desktop-status.json').read_text())
                age=time.time()-view['updated_at'] if view.get('pid')==pid else 0
            except (OSError,ValueError,KeyError):age=0
            if age>50:call('kickstart','-k',domain()+'/'+LABELS[role])
    from .collective import write_private
    write_private(failure_path,failures)


def bring_back(root):
    from .supervision import set_paused,health,desktop_ready,desktop_status
    root=Path(root);data=root/'.local'
    for role in ('core','desktop'):
        if properties(role).get('WorkingDirectory')!=str(root):
            raise ValueError('Recovery agent belongs to another checkout.')
        set_paused(role,data,False);start(role)
    start('presence')
    # A deliberate shortcut click can recover a frozen component immediately.
    # The periodic guardian waits for repeated failures instead.
    if not health():call('kickstart','-k',domain()+'/'+LABELS['core'])
    pid=int(properties('desktop').get('MainPID') or 0)
    if not desktop_ready(desktop_status(data,pid)):
        call('kickstart','-k',domain()+'/'+LABELS['desktop'])
    return action('desktop','start',root,data)


def main(root,args):
    from .supervision import set_paused
    operation=args.action
    if operation=='install':return install(root)
    roles=('core','desktop') if args.part=='all' else (args.part,)
    if operation=='disable':
        for role in (*roles,'presence'):
            call('bootout',domain()+'/'+LABELS[role],check=False)
            call('disable',domain()+'/'+LABELS[role])
        return 0
    result=0
    for role in reversed(roles) if operation=='stop' else roles:
        result=max(result,action(role,operation,root,Path(root)/'.local'))
    return result
