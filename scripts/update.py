#!/usr/bin/env python3
"""Update this checkout from GitHub, preserve memory, rebuild and restore services."""
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run(list(args),cwd=ROOT,check=True)


def main():
    changes=subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True)
    if changes.strip():raise SystemExit('Local source changes exist. Commit or stash them before updating; nothing was discarded.')
    python=str(ROOT/'.venv/bin/python')
    database=ROOT/'.local/organism.sqlite3'
    if database.is_file():
        backups=ROOT/'.local/backups';backups.mkdir(exist_ok=True,mode=0o700)
        target=backups/('before-update-'+str(time.time_ns())+'.sqlite3')
        source=sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True)
        destination=sqlite3.connect(target)
        source.backup(destination);destination.close();source.close();target.chmod(0o600)
    run('git','pull','--ff-only')
    stopped=False
    try:
        if (ROOT/'.local/service-install.json').is_file():
            run(python,'scripts/servicectl.py','stop');stopped=True
        uv=shutil.which('uv')
        if not uv:raise SystemExit('Install uv before updating.')
        run(uv,'sync','--frozen','--extra','desktop')
        run(python,'scripts/servicectl.py','install')
        print('Updated and rebuilt. The same Terminus is running with his memory intact.')
    except BaseException:
        if stopped:subprocess.run([python,'scripts/servicectl.py','start'],cwd=ROOT,check=False)
        raise

if __name__=='__main__':main()
