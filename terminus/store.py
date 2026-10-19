"""Transactional SQLite snapshots, bounded event history and private pairing secret."""

from __future__ import annotations

import json
from . import filelock as fcntl
from contextlib import suppress
import os
from pathlib import Path
import secrets
import sqlite3

from .core import Organism


class Store:
    history_limit = 512
    dedup_limit = 4096

    def __init__(self, directory, now, seed=814):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        self.lockfile = None
        self.db = None
        try:
            self.lockfile = (self.directory / "organism.lock").open("a")
            try:
                fcntl.flock(self.lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("This runtime directory already has a running Terminus") from None
            self.db = sqlite3.connect(self.directory / "organism.sqlite3", check_same_thread=False)
            os.chmod(self.directory / "organism.sqlite3", 0o600)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA auto_vacuum=INCREMENTAL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS snapshot (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS dedup (seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL);
            """)
            row = self.db.execute("SELECT body FROM snapshot WHERE id=1").fetchone()
            self.organism = Organism(saved=json.loads(row[0])) if row else Organism(seed=seed, now=now)
            self.token = self._token()
            if not row:
                self.save()
        except BaseException:
            with suppress(Exception):
                self._release()
            raise

    def _token(self):
        path = self.directory / "token"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if path.is_symlink() or not path.is_file():
                raise ValueError("Local authentication token must be a regular private file")
            os.chmod(path, 0o600)
            token = path.read_text().strip()
            if len(token) < 32:
                raise ValueError("Local authentication token file is invalid")
            return token
        token = secrets.token_urlsafe(32)
        with os.fdopen(fd, "w") as out:
            out.write(token + "\n")
        return token

    def contains(self, event_id):
        return self.db.execute("SELECT 1 FROM dedup WHERE id=?", (event_id,)).fetchone() is not None

    def save(self, event=None):
        body = json.dumps(self.organism.dump(), separators=(",", ":"), allow_nan=False)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO snapshot VALUES (1, ?)", (body,))
            if event:
                self.db.execute("INSERT INTO events(id,body) VALUES (?,?)",
                                (event["id"], json.dumps(event, separators=(",", ":"))))
                self.db.execute("INSERT INTO dedup(id) VALUES (?)", (event["id"],))
                self.db.execute("DELETE FROM events WHERE seq NOT IN (SELECT seq FROM events ORDER BY seq DESC LIMIT ?)", (self.history_limit,))
                self.db.execute("DELETE FROM dedup WHERE seq NOT IN (SELECT seq FROM dedup ORDER BY seq DESC LIMIT ?)", (self.dedup_limit,))

    def _release(self):
        """Release every handle even when another cleanup operation fails."""
        try:
            if self.db is not None:
                try:
                    self.db.close()
                finally:
                    self.db = None
        finally:
            if self.lockfile is not None:
                try:
                    fcntl.flock(self.lockfile, fcntl.LOCK_UN)
                finally:
                    self.lockfile.close()
                    self.lockfile = None

    def close(self):
        if self.db is None:
            return
        try:
            self.save()
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except BaseException:
            # Preserve the save/checkpoint error for an honest failed shutdown,
            # while allowing the next process to recover the durable snapshot.
            with suppress(Exception):
                self._release()
            raise
        self._release()
