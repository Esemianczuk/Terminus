"""Remove the former exchange job and its separate cache during an upgrade."""
from __future__ import annotations

import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def retire(root=ROOT):
    root = Path(root).resolve()
    data = root / '.local'
    if sys.platform == 'win32':
        from terminus.platform_windows import marker, powershell, ps_string
        powershell(fr"""
$task = Get-ScheduledTask -TaskPath '\Terminus\' -TaskName 'collective' -ErrorAction SilentlyContinue
if ($task) {{
    if ($task.Description -ne {ps_string(marker(root))}) {{ throw 'Exchange task belongs to another checkout.' }}
    if ($task.State -eq 'Running') {{ Stop-ScheduledTask -InputObject $task }}
    Unregister-ScheduledTask -InputObject $task -Confirm:$false
}}
Write-Output 'Exchange task checked.'
""")
    elif sys.platform == 'darwin':
        path = Path.home() / 'Library/LaunchAgents/org.terminus.collective.plist'
        if path.exists():
            if path.is_symlink():
                raise ValueError('Refusing to remove a linked launch agent.')
            value = plistlib.loads(path.read_bytes())
            arguments = value.get('ProgramArguments')
            if (value.get('Label') != 'org.terminus.collective'
                    or value.get('WorkingDirectory') != str(root)
                    or not isinstance(arguments, list) or len(arguments) < 2
                    or arguments[1] != str(root / 'scripts/collective.py')):
                raise ValueError('Exchange agent belongs to another checkout.')
            label = f'gui/{os.getuid()}/org.terminus.collective'
            subprocess.run(['launchctl', 'bootout', label], check=False, timeout=20)
            subprocess.run(['launchctl', 'disable', label], check=False, timeout=20)
            path.unlink()
    else:
        config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'systemd/user'
        paths = [config / f'terminus-collective.{suffix}' for suffix in ('service', 'timer')]
        for path in paths:
            if path.is_symlink() or (path.exists() and not path.read_text().startswith(f'# Managed by Terminus: {root}\n')):
                raise ValueError(f'Exchange unit belongs to another checkout: {path}')
        if any(path.exists() for path in paths):
            subprocess.run(['systemctl', '--user', 'disable', '--now', 'terminus-collective.timer'], check=True, timeout=20)
            subprocess.run(['systemctl', '--user', 'stop', 'terminus-collective.service'], check=False, timeout=20)
            for path in paths:
                path.unlink(missing_ok=True)
            subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True, timeout=20)
    for name in ('collective-bank.json', 'collective-local.json', 'collective-prior.json',
                 'collective-config.json', 'collective-status.json', 'collective-relay-status.json',
                 'collective.lock', 'macos-collective.log', 'windows-collective.log'):
        path = data / name
        if path.is_symlink():
            raise ValueError(f'Refusing to remove a linked file: {path}')
        if path.is_file():
            path.unlink()
    for name in ('collective-outbox', 'collective-sent'):
        path = data / name
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f'Refusing to remove an unexpected path: {path}')
        if path.is_dir():
            shutil.rmtree(path)


if __name__ == '__main__':
    retire()
