"""Paths shared by native installers and scheduled jobs."""
import os
from pathlib import Path
import shutil
import sys


def python_path(root, *, windowless=False):
    root = Path(root)
    if sys.platform == 'win32':
        return root / '.venv/Scripts' / ('pythonw.exe' if windowless else 'python.exe')
    return root / '.venv/bin/python'


def find_uv():
    candidates = [shutil.which('uv'), str(Path.home()/'.local/bin/uv'),
                  str(Path.home()/'.cargo/bin/uv'), '/opt/homebrew/bin/uv',
                  str(Path(sys.executable).parent/'uv.exe')]
    if os.name == 'nt':
        candidates.extend(str(p) for p in (Path(os.environ['APPDATA'])/'Python').glob('Python*/Scripts/uv.exe'))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError('Install uv and add it to PATH before installing or updating Terminus.')


def find_git():
    path=shutil.which('git')
    if path:return path
    if os.name=='nt':
        for base in (os.environ.get('ProgramFiles','C:/Program Files'),str(Path.home()/'AppData/Local/Programs')):
            path=Path(base)/'Git/cmd/git.exe'
            if path.is_file():return str(path)
    raise RuntimeError('Install Git before updating Terminus.')
