#!/usr/bin/env python3
"""Keep this checkout's native Terminus present on the desktop."""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from terminus.supervision import delegate
DATA = ROOT / ".local"
RECORD = DATA / "managed-desktop.json"
STATUS = DATA / "desktop-status.json"
CAPTURE = DATA / "desktop-presence.png"


def process_identity(pid: int) -> dict | None:
    """Reject stale PIDs, other checkouts and processes owned by another user."""
    try:
        proc = Path(f"/proc/{pid}")
        if proc.stat().st_uid != os.getuid():
            return None
        stat = (proc / "stat").read_text().rsplit(")", 1)[1].split()
        if stat[0] == "Z":
            return None
        command = (proc / "cmdline").read_bytes().split(b"\0")
        if len(command) < 2 or command[1] != str(ROOT / "desktop" / "overlay.py").encode():
            return None
        if (proc / "cwd").resolve() != ROOT:
            return None
        return {"pid": pid, "start_ticks": stat[19],
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}
    except (OSError, ValueError, IndexError):
        return None


def owned_record() -> dict | None:
    try:
        record = json.loads(RECORD.read_text())
        current = process_identity(int(record["pid"]))
        return record if current and all(record.get(k) == v for k, v in current.items()) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_record(record: dict) -> None:
    temporary = RECORD.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record))
    temporary.chmod(0o600)
    temporary.replace(RECORD)


def live_status(record: dict | None) -> dict | None:
    if not record:
        return None
    try:
        status = json.loads(STATUS.read_text())
        if not isinstance(status, dict):
            return None
        updated = status.get("updated_at")
        if not isinstance(updated, (int, float)) or isinstance(updated, bool) or not math.isfinite(updated):
            return None
        if status.get("pid") != record["pid"] or not 0 <= time.time() - updated <= 8:
            return None
        return status
    except (OSError, ValueError, TypeError):
        return None


def ready(status: dict | None) -> bool:
    return bool(status and status.get("visible") and status.get("exposed")
                and status.get("connected") and status.get("platform") not in {"offscreen", "minimal"})


def stop(record: dict | None) -> int:
    if not record:
        print("No desktop process managed by this checkout; nothing changed.")
        return 0
    expected = {key: record[key] for key in ("pid", "start_ticks", "boot_id")}
    if process_identity(record["pid"]) != expected:
        print("Desktop ownership changed before termination; no signal was sent.", file=sys.stderr)
        return 1
    try:
        os.kill(record["pid"], signal.SIGTERM)
    except ProcessLookupError:
        RECORD.unlink(missing_ok=True)
        print("Desktop body already exited. The organism core was not changed.")
        return 0
    for _ in range(60):
        if process_identity(record["pid"]) != expected:
            RECORD.unlink(missing_ok=True)
            print("Desktop body stopped. The organism core and its memory remain running.")
            return 0
        time.sleep(.1)
    print("Desktop body is still stopping; no force-kill was issued.", file=sys.stderr)
    return 1


def start(record: dict | None, scale: float | None) -> int:
    if record:
        status = live_status(record)
        print("Terminus is already present on the desktop." if ready(status)
              else "The managed desktop process is running but is not reporting connected desktop presence; inspect .local/desktop.log.")
        return 0 if ready(status) else 1
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("A graphical desktop session is required.", file=sys.stderr)
        return 1
    python = ROOT / ".venv/bin/python"
    if not python.is_file():
        print("Run uv sync --extra test --extra desktop first.", file=sys.stderr)
        return 1
    try:
        with urllib.request.urlopen("http://127.0.0.1:8769/api/health", timeout=1) as response:
            core_ready = json.load(response).get("service") == "terminus"
    except (OSError, ValueError):
        core_ready = False
    if not core_ready:
        core = subprocess.run([str(python), str(ROOT / "scripts" / "termctl.py"), "start"], cwd=ROOT)
        if core.returncode:
            print("The organism core could not be started; desktop body was not launched.", file=sys.stderr)
            return core.returncode
    STATUS.unlink(missing_ok=True)
    CAPTURE.unlink(missing_ok=True)
    environment = os.environ.copy()
    if environment.get("XDG_SESSION_TYPE") == "x11" and environment.get("DISPLAY"):
        environment["QT_QPA_PLATFORM"] = "xcb"
    command = [str(python), str(ROOT / "desktop" / "overlay.py"), "--data-dir", str(DATA),
               "--status-file", str(STATUS), "--capture-file", str(CAPTURE)]
    if scale is not None:
        command.extend(["--scale", str(scale)])
    with (DATA / "desktop.log").open("ab") as log:
        os.chmod(DATA / "desktop.log", 0o600)
        child = subprocess.Popen(
            command,
            cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
            stdout=log, stderr=log, start_new_session=True)
    record = None
    for _ in range(100):
        if child.poll() is not None:
            break
        # The child may still be entering Python when Popen returns. Verify it
        # during readiness polling instead of leaving it alive but unmanaged.
        if record is None:
            record = process_identity(child.pid)
            if record:
                save_record(record)
        status = live_status(record) if record else None
        if ready(status):
            print("Terminus is present on the desktop: transparent, floating, and connected.")
            return 0
        time.sleep(.1)
    print("Desktop presence was not confirmed; inspect .local/desktop.log and desktop-status.json.", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status", "restart"])
    parser.add_argument("--scale", type=float, default=None)
    args = parser.parse_args()
    if args.scale is not None and not .65 <= args.scale <= 2:
        parser.error("--scale must be between .65 and 2")
    DATA.mkdir(exist_ok=True, mode=0o700)
    with (DATA / "desktop-manager.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        supervised = delegate("desktop", args.action, ROOT, DATA, scale=args.scale)
        if supervised is not None:
            return supervised
        record = owned_record()
        if args.action == "status":
            status = live_status(record)
            print(json.dumps(status, indent=2) if status else "No desktop body managed by this checkout is reporting presence.")
            return 0 if ready(status) else 1
        if args.action in {"stop", "restart"}:
            result = stop(record)
            if result or args.action == "stop":
                return result
            record = None
        return start(record, args.scale)


if __name__ == "__main__":
    raise SystemExit(main())
