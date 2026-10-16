#!/usr/bin/env python3
"""Start, inspect or stop only this checkout's loopback Terminus core."""
from pathlib import Path
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / '.local'
RECORD = DATA / 'managed-core.json'


def owned_process(record):
    if not isinstance(record, dict):
        return False
    try:
        pid = int(record['pid'])
        stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        cwd = Path(f'/proc/{pid}/cwd').resolve()
        return stat[19] == record['start_ticks'] and cwd == ROOT and b'terminus' in command and b'serve' in command
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return False


def load_record():
    try:
        record = json.loads(RECORD.read_text())
    except (OSError, ValueError):
        return None
    return record if owned_process(record) else None


def health():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8769/api/health', timeout=1) as response:
            return json.load(response).get('service') == 'terminus'
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'status', 'stop'])
    args = parser.parse_args()
    record = load_record()
    if args.action == 'status':
        print('Managed core running and healthy' if record and health() else 'No healthy core managed by this checkout')
        return 0 if record and health() else 1
    if args.action == 'stop':
        if not record:
            print('No owned managed core to stop; nothing changed.')
            return 0
        os.kill(record['pid'], signal.SIGTERM)
        for _ in range(50):
            if not owned_process(record):
                RECORD.unlink(missing_ok=True)
                print('Managed core stopped; organism state retained.')
                return 0
            time.sleep(.1)
        print('Managed core is still stopping; no force-kill was issued.', file=sys.stderr)
        return 1
    if record:
        print('Managed core already running: http://127.0.0.1:8769')
        return 0 if health() else 1
    if health():
        print('A Terminus core already serves8769; it was not started by this manager. Nothing changed.', file=sys.stderr)
        return 1
    DATA.mkdir(exist_ok=True, mode=0o700)
    python = ROOT / '.venv/bin/python'
    if not python.exists():
        print('Run uv sync --extra test --extra desktop first.', file=sys.stderr)
        return 1
    with (DATA / 'core.log').open('ab') as log:
        os.chmod(DATA / 'core.log', 0o600)
        child = subprocess.Popen([str(python), '-m', 'terminus', 'serve', '--data-dir', str(DATA)],
                                 cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    try:
        start = Path(f'/proc/{child.pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
        record = {'pid': child.pid, 'start_ticks': start}
        RECORD.write_text(json.dumps(record))
        RECORD.chmod(0o600)
        for _ in range(50):
            if child.poll() is not None:
                break
            if health():
                print('Terminus running: http://127.0.0.1:8769 (loopback only)')
                return 0
            time.sleep(.1)
    except OSError:
        pass
    if owned_process(record):
        child.terminate()
    RECORD.unlink(missing_ok=True)
    print('Core did not become healthy; inspect .local/core.log. No unrelated process was stopped.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
