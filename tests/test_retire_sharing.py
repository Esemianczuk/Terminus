"""An upgrade removes only the exchange job and cache owned by this checkout."""

from pathlib import Path
import plistlib
import subprocess
import sys

import pytest

from scripts import retire_sharing


def test_linux_retirement_preserves_private_organism(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    root = tmp_path / 'Terminus'
    data = root / '.local'
    data.mkdir(parents=True)
    organism = data / 'organism.sqlite3'
    organism.write_bytes(b'private history')
    (data / 'collective-bank.json').write_text('{}')
    config = tmp_path / 'config/systemd/user'
    config.mkdir(parents=True)
    for suffix in ('timer', 'service'):
        (config / f'terminus-collective.{suffix}').write_text(f'# Managed by Terminus: {root}\n')
    calls = []
    monkeypatch.setattr(retire_sharing.subprocess, 'run', lambda command, **options: calls.append(command))

    retire_sharing.retire(root)

    assert organism.read_bytes() == b'private history'
    assert not (data / 'collective-bank.json').exists()
    assert not list(config.glob('terminus-collective.*'))
    assert ['systemctl', '--user', 'disable', '--now', 'terminus-collective.timer'] in calls


def test_linux_retirement_refuses_an_unowned_job(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    config = tmp_path / 'config/systemd/user'
    config.mkdir(parents=True)
    foreign = config / 'terminus-collective.timer'
    foreign.write_text('# Managed by Terminus: /another/checkout\n')
    monkeypatch.setattr(retire_sharing.subprocess, 'run', lambda *args, **options: pytest.fail('must not operate on foreign job'))
    with pytest.raises(ValueError):
        retire_sharing.retire(tmp_path / 'Terminus')
    assert foreign.exists()


def test_macos_retirement_checks_arguments_before_unlink(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    path = tmp_path / 'Library/LaunchAgents/org.terminus.collective.plist'
    path.parent.mkdir(parents=True)
    root = tmp_path / 'Terminus'
    path.write_bytes(plistlib.dumps({'Label': 'org.terminus.collective',
                                     'WorkingDirectory': str(root), 'ProgramArguments': ['/python']}))
    with pytest.raises(ValueError):
        retire_sharing.retire(root)
    assert path.exists()


def test_windows_retirement_is_safe_to_repeat_without_an_old_task(tmp_path, monkeypatch):
    from terminus import platform_windows as windows
    monkeypatch.setattr(sys, 'platform', 'win32')
    scripts = []
    monkeypatch.setattr(windows, 'powershell', lambda script: scripts.append(script))
    root = tmp_path / 'Terminus'
    data = root / '.local'
    data.mkdir(parents=True)
    (data / 'organism.sqlite3').write_bytes(b'private history')
    retire_sharing.retire(root)
    retire_sharing.retire(root)
    assert len(scripts) == 2
    assert all("Write-Output 'Exchange task checked.'" in script for script in scripts)
    assert (data / 'organism.sqlite3').read_bytes() == b'private history'
