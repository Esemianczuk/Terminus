#!/usr/bin/env python3
"""Start, inspect or stop only this checkout's loopback Terminus core."""
from __future__ import annotations
from pathlib import Path
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from terminus import filelock as fcntl
from terminus.supervision import delegate
DATA = ROOT / '.local'
RECORD = DATA / 'managed-core.json'


def process_identity(pid):
    try:
        proc = Path(f'/proc/{int(pid)}')
        if proc.stat().st_uid != os.getuid():
            return None
        fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
        command = (proc / 'cmdline').read_bytes().split(b'\0')
        if fields[0] == 'Z' or command[1:4] != [b'-m', b'terminus', b'serve']:
            return None
        if (proc / 'cwd').resolve() != ROOT:
            return None
        if b'--data-dir' in command:
            index = command.index(b'--data-dir') + 1
            if not command[index] or (ROOT / os.fsdecode(command[index])).resolve() != DATA.resolve():
                return None
        return {'pid': int(pid), 'start_ticks': fields[19], 'uid': os.getuid(),
                'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (OSError, ValueError, TypeError, IndexError):
        return None


def matching_identity(record, identity):
    if not isinstance(record, dict):
        return False
    return bool(identity and all(record.get(key, value) == value for key, value in identity.items())
                and record.get('start_ticks') == identity['start_ticks'])


def owned_process(record):
    return isinstance(record, dict) and matching_identity(record, process_identity(record.get('pid')))


def save_record(record):
    temp = RECORD.with_suffix('.json.tmp')
    temp.write_text(json.dumps(record))
    temp.chmod(0o600)
    temp.replace(RECORD)


def load_record():
    try:
        record = json.loads(RECORD.read_text())
    except (OSError, ValueError):
        return None
    identity = process_identity(record.get('pid')) if isinstance(record, dict) else None
    if not matching_identity(record, identity):
        return None
    # Safely upgrade a legacy pid/start record after verifying its exact process.
    if identity != record:
        save_record(identity)
    return identity


def health():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8769/api/health', timeout=1) as response:
            body = json.load(response)
            return body.get('service') == 'terminus' and body.get('status') == 'ok'
    except (OSError, ValueError):
        return False


def stop(record):
    if not record:
        print('No owned managed core to stop; nothing changed.')
        return 0
    if not owned_process(record):
        print('Core ownership changed before termination; no signal was sent.', file=sys.stderr)
        return 1
    try:
        os.kill(record['pid'], signal.SIGTERM)
    except ProcessLookupError:
        RECORD.unlink(missing_ok=True)
        return 0
    for _ in range(80):
        if not owned_process(record):
            RECORD.unlink(missing_ok=True)
            print('Managed core stopped; organism state retained.')
            return 0
        time.sleep(.1)
    print('Managed core is still stopping; no force-kill was issued.', file=sys.stderr)
    return 1


def start(record):
    if record:
        print('Managed core already running: http://127.0.0.1:8769')
        return 0 if health() else 1
    if health():
        print('An existing healthy Terminus core serves 8769; its ownership was not changed.')
        return 0
    python = ROOT / '.venv/bin/python'
    if not python.exists():
        print('Run uv sync --extra test --extra desktop first.', file=sys.stderr)
        return 1
    with (DATA / 'core.log').open('ab') as log:
        os.chmod(DATA / 'core.log', 0o600)
        child = subprocess.Popen([str(python), '-m', 'terminus', 'serve', '--data-dir', str(DATA)],
                                 cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    identity = None
    for _ in range(100):
        if child.poll() is not None:
            break
        # Popen can return before /proc exposes the Python invocation. Retry
        # verification instead of leaving a healthy child permanently unmanaged.
        if identity is None:
            identity = process_identity(child.pid)
            if identity:
                save_record(identity)
        if identity and health():
            print('Terminus running: http://127.0.0.1:8769 (loopback only)')
            return 0
        time.sleep(.1)
    if identity and owned_process(identity):
        stop(identity)
    else:
        RECORD.unlink(missing_ok=True)
    print('Core did not become healthy; inspect .local/core.log. No unrelated process was stopped.', file=sys.stderr)
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'status', 'stop', 'restart'])
    args = parser.parse_args()
    DATA.mkdir(exist_ok=True, mode=0o700)
    with (DATA / 'core-manager.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        supervised = delegate('core', args.action, ROOT, DATA)
        if supervised is not None:
            return supervised
        record = load_record()
        if args.action == 'status':
            print('Managed core running and healthy' if record and health() else 'No healthy core managed by this checkout')
            return 0 if record and health() else 1
        if args.action in {'stop', 'restart'}:
            result = stop(record)
            if result or args.action == 'stop':
                return result
            record = None
        return start(record)


if __name__ == '__main__':
    raise SystemExit(main())
