"""Per-user, interactive Windows Task Scheduler jobs. No Windows service in Session 0.

Only tasks with this checkout's ownership marker may be changed. Process handles
are checked against their creation time before a forced recovery is allowed.
"""
from __future__ import annotations
import base64
from datetime import datetime
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

from .runtime import python_path

ROOT = Path(__file__).resolve().parents[1]
ROLES = ('core', 'desktop', 'presence', 'collective', 'updates')


def ps_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def powershell(script, *, check=True):
    wrapped = "$ProgressPreference='SilentlyContinue';$ErrorActionPreference='Stop';\ntry {\n"+script+"\n} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"
    encoded = base64.b64encode(wrapped.encode('utf-16le')).decode()
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            capture_output=True, text=True, timeout=30,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if check and result.returncode:
        raise RuntimeError('Windows task operation failed: '+result.stderr.strip()[:2000])
    return result


def marker(root):
    return 'Managed by Terminus: ' + str(Path(root).resolve())


def definition(role, root, user):
    """InteractiveToken never stores a password and never elevates the creature."""
    if role not in ROLES:
        raise ValueError('Unknown Terminus task')
    root = Path(root)
    task = ET.Element('Task', version='1.2', xmlns='http://schemas.microsoft.com/windows/2004/02/mit/task')
    def element(parent, tag, value=None):
        child = ET.SubElement(parent, tag)
        if value is not None: child.text = str(value)
        return child
    registration = element(task, 'RegistrationInfo')
    element(registration, 'Description', marker(root))
    triggers = element(task, 'Triggers')
    logon = element(triggers, 'LogonTrigger')
    element(logon, 'Enabled', 'true'); element(logon, 'UserId', user)
    if role in {'presence', 'collective', 'updates'}:
        trigger = element(triggers, 'TimeTrigger')
        repetition = element(trigger, 'Repetition')
        element(repetition, 'Interval', {'presence':'PT1M', 'collective':'PT10M', 'updates':'PT1H'}[role])
        element(repetition, 'StopAtDurationEnd', 'false')
        element(trigger, 'StartBoundary', datetime.now().isoformat(timespec='seconds'))
        element(trigger, 'Enabled', 'true')
    principals = element(task, 'Principals')
    principal = ET.SubElement(principals, 'Principal', id='User')
    element(principal, 'UserId', user)
    element(principal, 'LogonType', 'InteractiveToken')
    element(principal, 'RunLevel', 'LeastPrivilege')
    settings = element(task, 'Settings')
    for tag, value in {
        'MultipleInstancesPolicy':'IgnoreNew', 'DisallowStartIfOnBatteries':'false',
        'StopIfGoingOnBatteries':'false', 'AllowHardTerminate':'true', 'StartWhenAvailable':'true',
        'RunOnlyIfNetworkAvailable':'false', 'AllowStartOnDemand':'true', 'Enabled':'true',
        'Hidden':'false', 'RunOnlyIfIdle':'false', 'WakeToRun':'false',
        'ExecutionTimeLimit':'PT0S' if role in {'core','desktop'} else 'PT15M', 'Priority':'7',
    }.items(): element(settings, tag, value)
    if role in {'core', 'desktop'}:
        restart = element(settings, 'RestartOnFailure')
        element(restart, 'Interval', 'PT1M'); element(restart, 'Count', 3)
    actions = ET.SubElement(task, 'Actions', Context='User')
    command = element(actions, 'Exec')
    element(command, 'Command', python_path(root, windowless=True))
    element(command, 'Arguments', subprocess.list2cmdline([str(root/'scripts/windows_service.py'), role]))
    element(command, 'WorkingDirectory', root)
    return ET.tostring(task, encoding='unicode')


def register(role, root=ROOT):
    user = powershell('[System.Security.Principal.WindowsIdentity]::GetCurrent().Name').stdout.strip()
    xml = definition(role, root, user)
    powershell(fr"""
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$sid = $identity.User.Value
$security = "D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;$sid)"
$scheduler = New-Object -ComObject Schedule.Service
$scheduler.Connect()
try {{ $folder = $scheduler.GetFolder('\Terminus') }}
catch {{ $folder = $scheduler.GetFolder('\').CreateFolder('Terminus', $security) }}
# SSH often runs with an elevated token. Explicit per-user task rights let
# the non-elevated guardian and updater manage their own jobs afterwards.
foreach ($entry in $folder.GetTasks(0)) {{
    if ($entry.Definition.RegistrationInfo.Description -ne {ps_string(marker(root))}) {{
        throw 'Terminus task folder contains an unrelated job; permissions were not changed.'
    }}
}}
# Convert inherited rights on existing owned jobs before protecting the folder.
# Otherwise the CIM registrar can deny updates to an older periodic task.
foreach ($entry in $folder.GetTasks(0)) {{ $entry.SetSecurityDescriptor($security, 0) }}
$folder.SetSecurityDescriptor($security, 0)
$old = Get-ScheduledTask -TaskPath '\Terminus\' -TaskName {ps_string(role)} -ErrorAction SilentlyContinue
if ($old -and $old.Description -ne {ps_string(marker(root))}) {{ throw 'Task belongs to another checkout.' }}
Register-ScheduledTask -TaskPath '\Terminus\' -TaskName {ps_string(role)} -Xml {ps_string(xml)} -Force | Out-Null
$folder.GetTask({ps_string(role)}).SetSecurityDescriptor($security, 0)
""")


def task_operation(role, operation, root=ROOT):
    if role not in ROLES or operation not in {'Start', 'Stop', 'Disable', 'Enable'}:
        raise ValueError('Invalid task operation')
    powershell(fr"""
$task = Get-ScheduledTask -TaskPath '\Terminus\' -TaskName {ps_string(role)}
if ($task.Description -ne {ps_string(marker(root))}) {{ throw 'Task belongs to another checkout.' }}
{operation}-ScheduledTask -InputObject $task | Out-Null
""")


def kernel():
    lib = C.WinDLL('kernel32', use_last_error=True)
    lib.OpenProcess.argtypes = [W.DWORD,W.BOOL,W.DWORD]; lib.OpenProcess.restype = W.HANDLE
    lib.GetProcessTimes.argtypes = [W.HANDLE,*([C.POINTER(W.FILETIME)]*4)]; lib.GetProcessTimes.restype = W.BOOL
    lib.GetExitCodeProcess.argtypes = [W.HANDLE,C.POINTER(W.DWORD)]; lib.GetExitCodeProcess.restype = W.BOOL
    lib.CloseHandle.argtypes = [W.HANDLE]; lib.CloseHandle.restype = W.BOOL
    lib.TerminateProcess.argtypes = [W.HANDLE,W.UINT]; lib.TerminateProcess.restype = W.BOOL
    return lib


def creation(lib, handle):
    times = [W.FILETIME() for _ in range(4)]
    code = W.DWORD()
    if not lib.GetProcessTimes(handle, *(C.byref(t) for t in times)) or not lib.GetExitCodeProcess(handle,C.byref(code)) or code.value != 259:
        return None
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


def identity(pid):
    lib = kernel(); handle = lib.OpenProcess(0x1000,False,pid)
    if not handle: return None
    try:
        born = creation(lib,handle)
        return {'pid':pid,'created':born} if born else None
    finally: lib.CloseHandle(handle)


def record(role, root=ROOT):
    try:
        value = json.loads((Path(root)/'.local'/('windows-'+role+'.json')).read_text())
        current = identity(value['pid'])
        return value if value.get('root') == str(Path(root).resolve()) and current and all(value.get(k)==v for k,v in current.items()) else None
    except (OSError,ValueError,KeyError,TypeError): return None


def properties(role, root=ROOT):
    value = record(role,root)
    return {'WorkingDirectory':str(root), 'MainPID':str(value['pid'] if value else 0),
            'ActiveState':'active' if value else 'inactive', 'UnitFileState':'enabled',
            'Supervisor':'Windows Task Scheduler (interactive user)'}


def stop(role, root=ROOT):
    """Ask the owning event loop to close before considering forced recovery."""
    root = Path(root); data = root/'.local'
    value = record(role,root)
    if not value: return
    (data/('windows-'+role+'.stop')).write_text(str(value['pid']))
    deadline = time.monotonic()+15
    while time.monotonic()<deadline:
        if record(role,root) != value: return
        time.sleep(.2)
    # Re-check creation time on the SAME handle used to terminate. No PID race.
    lib = kernel(); handle = lib.OpenProcess(0x1001,False,value['pid'])
    if handle:
        try:
            if creation(lib,handle)==value['created']:
                if not lib.TerminateProcess(handle,0): raise OSError('Could not stop owned Terminus process')
        finally: lib.CloseHandle(handle)
    deadline = time.monotonic()+3
    while record(role,root) == value and time.monotonic()<deadline: time.sleep(.1)
    if record(role,root) == value: raise RuntimeError('Owned process did not exit')


def start(role, root=ROOT):
    if role in {'core','desktop'} and record(role,root): return
    task_operation(role,'Enable',root)
    task_operation(role,'Start',root)


def action(role, operation, root, data, scale=None):
    from .supervision import set_paused,health,desktop_ready,desktop_status
    root = Path(root); data = Path(data)
    if operation in {'start','stop','restart'}:
        set_paused(role,data,True if operation in {'stop','restart'} else False)
        if operation in {'stop','restart'}: stop(role,root)
        if operation=='stop': return 0
        set_paused(role,data,False)
        if role=='desktop':
            set_paused('core',data,False); start('core',root)
        if scale is not None:
            from PySide6.QtCore import QSettings
            preferences=QSettings(str(data/'desktop.ini'),QSettings.IniFormat)
            preferences.setValue('scale',scale); preferences.sync()
        start(role,root)
    deadline = time.monotonic() + (25 if operation!='status' else 0)
    while True:
        info = properties(role,root)
        view = desktop_status(data,int(info['MainPID'])) if role=='desktop' else None
        ready = bool(record(role,root)) and (health() if role=='core' else desktop_ready(view))
        if ready or time.monotonic()>=deadline:
            print(json.dumps({'service':info,'healthy':ready,'desktop':view},indent=2))
            return 0 if ready else 1
        time.sleep(.3)


def shortcut(root):
    root=Path(root)
    # Resolve Windows' actual Desktop (including OneDrive redirection).
    powershell(fr"""
$path = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Bring Back Terminus.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($path)
if ((Test-Path $path) -and $link.Description -ne {ps_string(marker(root))}) {{ throw 'Unrelated shortcut already exists.' }}
$link.TargetPath = {ps_string(python_path(root,windowless=True))}
$link.Arguments = {ps_string(subprocess.list2cmdline([str(root/'scripts/windows_service.py'),'recover']))}
$link.WorkingDirectory = {ps_string(root)}
$link.Description = {ps_string(marker(root))}
$link.WindowStyle = 7
$link.Save()
""")


def install(root):
    from .collective import write_private
    from .supervision import set_paused
    root=Path(root).resolve(); data=root/'.local'; data.mkdir(parents=True,exist_ok=True)
    for role in ('core','desktop','presence'): register(role,root)
    shortcut(root)
    write_private(data/'service-install.json',{'version':1,'root':str(root),'platform':'win32'})
    for role in ('core','desktop'): set_paused(role,data,False)
    start('core',root)
    result=action('desktop','start',root,data)
    start('presence',root)
    return result


def guardian(root):
    from .supervision import is_paused,desktop_status,health
    root=Path(root); data=root/'.local'
    if is_paused('core',data): return
    for role in ('core','desktop'):
        if is_paused(role,data): continue
        value=record(role,root)
        if not value: start(role,root); continue
        if time.time()-value.get('started',time.time())<75: continue
        okay=health() if role=='core' else desktop_status(data,value['pid']) is not None
        if not okay:
            # A second probe avoids restarting on a brief load spike.
            time.sleep(2)
            okay=health() if role=='core' else desktop_status(data,value['pid']) is not None
            if not okay: action(role,'restart',root,data)


def bring_back(root):
    from .supervision import set_paused
    root=Path(root)
    for role in ('core','desktop'): set_paused(role,root/'.local',False); start(role,root)
    (root/'.local/windows-desktop.bring').touch()
    guardian(root)
    return action('desktop','start',root,root/'.local')


def main(root,args):
    from .supervision import installed,set_paused
    if args.action=='install': return install(root)
    if not installed(root,Path(root)/'.local'): raise ValueError('Install Terminus services first')
    roles=('core','desktop') if args.part=='all' else (args.part,)
    if args.action=='disable':
        for role in roles: set_paused(role,Path(root)/'.local',True); stop(role,root); task_operation(role,'Disable',root)
        if args.part=='all': task_operation('presence','Disable',root)
        return 0
    result=0
    for role in reversed(roles) if args.action=='stop' else roles:
        result=max(result,action(role,args.action,root,Path(root)/'.local'))
    return result
