#!/usr/bin/env python3
"""Opt-in metadata sensors and a durable, bounded event outbox. No screen/key capture."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

KINDS = {'context', 'presence', 'git', 'activity', 'time'}


def normalized_url(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    if p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError('Use an HTTP(S) core URL without credentials, query or fragment')
    if p.scheme == 'http' and p.hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise ValueError('Remote collectors require HTTPS (for example a private Tailscale HTTPS endpoint)')
    return url.rstrip('/')


def command(args: list[str], cwd: Path | None = None) -> str | None:
    try:
        return subprocess.check_output(args, cwd=cwd, text=True, timeout=3, stderr=subprocess.DEVNULL).strip()
    except (subprocess.SubprocessError, OSError):
        return None


def active_app() -> str | None:
    """X11 WM_CLASS only. Never read window titles or keyboard input."""
    raw = command(['xprop', '-root', '_NET_ACTIVE_WINDOW'])
    if not raw:
        return None
    match = re.search(r'0x[0-9a-fA-F]+', raw)
    if not match or match.group() == '0x0':
        return None
    raw = command(['xprop', '-id', match.group(), 'WM_CLASS'])
    if not raw:
        return None
    classes = re.findall(r'"([^"\n]+)"', raw)
    return re.sub(r'[^\w .+-]', '', classes[-1])[:64] if classes else None


class Outbox:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.execute('CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, created REAL, payload TEXT)')
        self.db.commit()

    def add(self, payload: dict) -> None:
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO outbox VALUES (?, ?, ?)', (payload['id'], time.time(), json.dumps(payload)))
            self.db.execute('DELETE FROM outbox WHERE created < ?', (time.time() - 86400,))
            self.db.execute('DELETE FROM outbox WHERE id NOT IN (SELECT id FROM outbox ORDER BY created DESC LIMIT 256)')

    def flush(self, url: str, token: str) -> int:
        sent = 0
        with self.db:
            self.db.execute('DELETE FROM outbox WHERE created < ?', (time.time() - 86400,))
        for event_id, payload in self.db.execute('SELECT id, payload FROM outbox ORDER BY created').fetchall():
            req = urllib.request.Request(url + '/api/events', data=payload.encode(), headers={
                'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method='POST')
            try:
                with urllib.request.urlopen(req, timeout=4) as response:
                    result = json.load(response)
                if not isinstance(result.get('accepted'), bool):
                    break
            except urllib.error.HTTPError as exc:
                # Invalid input can never succeed on retry. Keep auth/rate/transient failures.
                if exc.code in (400, 413, 422):
                    with self.db:
                        self.db.execute('DELETE FROM outbox WHERE id=?', (event_id,))
                    continue
                break
            except (OSError, ValueError):
                break
            with self.db:
                self.db.execute('DELETE FROM outbox WHERE id=?', (event_id,))
            sent += 1
        return sent

    def count(self) -> int:
        return self.db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]


def load_token(data_dir: Path) -> str:
    token_file = data_dir / 'token'
    try:
        token = token_file.read_text().strip()
    except OSError:
        raise SystemExit('Start the core first, or copy its token to your private --data-dir/token file.')
    if not token:
        raise SystemExit('Core token file is empty')
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8769')
    parser.add_argument('--data-dir', type=Path, default=Path('.local'))
    parser.add_argument('--device-id', help='Opaque device identity; default persistent local random ID')
    parser.add_argument('--repo', action='append', type=Path, default=[], help='Opt in a repository (name, commit changes and edit counts only)')
    parser.add_argument('--focus', action='store_true', help='Opt in X11 app-class transitions only; never titles')
    parser.add_argument('--interval', type=float, default=15)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--send', metavar='CONTEXT', help='Send one explicit context label and exit')
    args = parser.parse_args()
    try:
        url = normalized_url(args.url)
    except ValueError as exc:
        parser.error(str(exc))
    if args.interval < 5:
        parser.error('--interval must be at least 5 seconds')
    args.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    identity_path = args.data_dir / 'collector-device'
    if not identity_path.exists():
        identity_path.write_text('collector-' + uuid.uuid4().hex[:16])
        identity_path.chmod(0o600)
    device = args.device_id or identity_path.read_text().strip()
    if not re.fullmatch(r'[\w.-]{1,64}', device):
        parser.error('device ID must be a short opaque label (letters, digits, underscore, dot, hyphen)')
    token = load_token(args.data_dir)
    queue = Outbox(args.data_dir / 'collector-outbox.sqlite3')
    repos = []
    for path in args.repo:
        path = path.expanduser().resolve()
        if command(['git', 'rev-parse', '--show-toplevel'], path) != str(path):
            parser.error('--repo must point at a Git repository root')
        repos.append(path)
    previous: dict[str, str] = {}

    def emit(kind: str, context: str, intensity: float = .3, source: str = 'live') -> None:
        queue.add({'id': str(uuid.uuid4()), 'kind': kind, 'device_id': device,
                   'context': context[:100], 'intensity': intensity, 'source': source})

    if args.send:
        emit('context', args.send, .65, 'manual')
        sent = queue.flush(url, token)
        print(f'Context queued; delivered {sent}; pending {queue.count()}.')
        return 0 if queue.count() == 0 else 2
    print(f'Collecting time/presence; app class={args.focus}; opted-in repos={len(repos)}. Ctrl+C stops.')
    try:
        while True:
            now = time.localtime()
            period = ('night', 'morning', 'afternoon', 'evening')[((now.tm_hour + 2) % 24) // 6]
            if previous.get('time') != period:
                emit('time', period, .2)
                previous['time'] = period
            bucket = str(int(time.time() // 300))
            if previous.get('presence') != bucket:
                emit('presence', 'personal-device', .15)
                previous['presence'] = bucket
            if args.focus:
                app = active_app()
                if app and previous.get('app') != app:
                    emit('context', 'app:' + app, .45)
                    previous['app'] = app
            for repo in repos:
                label = 'project:' + re.sub(r'[^\w .+-]', '', repo.name)[:60]
                head = command(['git', 'rev-parse', 'HEAD'], repo)
                key = str(repo) + ':head'
                if head and key in previous and previous[key] != head:
                    emit('git', label, .75)
                if head:
                    previous[key] = head
                # Hash the porcelain listing locally; no paths/content leave the collector.
                dirty = command(['git', 'status', '--porcelain', '--untracked-files=no'], repo)
                if dirty is not None:
                    # Include tracked file metadata so repeated edits in an already-dirty file count.
                    tracked = command(['git', 'ls-files', '-z'], repo) or ''
                    mtimes = []
                    for name in tracked.split('\0')[:10000]:
                        if name:
                            try:
                                st = (repo / name).stat()
                                mtimes.append((name, st.st_mtime_ns, st.st_size))
                            except OSError:
                                pass
                    signature = hashlib.sha256((dirty + repr(mtimes)).encode()).hexdigest()
                    key = str(repo) + ':edits'
                    if key in previous and previous[key] != signature:
                        emit('activity', label, .4)
                    previous[key] = signature
            queue.flush(url, token)
            if args.once:
                print(f'Pending events: {queue.count()}')
                return 0 if queue.count() == 0 else 2
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(f'Stopped. Pending events retained: {queue.count()}')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
