# Startup and automatic recovery

Terminus runs as two systemd **user** services:

- `terminus-core.service` owns the persistent organism, local SQLite database and authenticated loopback port 8769.
- `terminus-desktop.service` owns the native transparent window. It waits for an available graphical session, then replaces its session gate with the real Qt application at the same service PID.

Both use `Restart=always`, a three-second restart delay, and unlimited restart attempts. `WatchdogSec=45` detects a process that remains alive but stops responding. The core sends watchdog messages from its asyncio ticker only while its health diagnostics are OK. The desktop sends them from Qt's own status timer while its native window is visible. A separate health thread cannot conceal a frozen event loop. A watchdog failure requests termination; systemd can force-stop after a further 15 seconds if graceful termination fails.

The units are independent after startup. Desktop connection failures use the existing reconnect logic; they do not repeatedly restart an otherwise responsive body. A core restart reloads the same organism and the desktop reconnects. Core memory and all visual features are retained.

## Install and use

From an initialized checkout with its existing `.local/organism.sqlite3`:

```sh
uv run python scripts/servicectl.py install
uv run python scripts/servicectl.py status
```

The installer refuses to overwrite unrelated user-service or autostart files. It gracefully hands off only processes whose exact identity the existing launchers can verify. It retains the private pairing token and SQLite database. On this workstation, a consistent SQLite backup was taken before installation and the database passed `PRAGMA quick_check`.

After installation the existing commands delegate to systemd, preventing duplicate unmanaged processes:

```sh
uv run python scripts/desktopctl.py start
uv run python scripts/desktopctl.py status
uv run python scripts/desktopctl.py restart
uv run python scripts/termctl.py status
```

Or use systemd directly:

```sh
systemctl --user status terminus-core.service terminus-desktop.service
journalctl --user -u terminus-core.service -u terminus-desktop.service -f
```

Logs now go to the user journal. Old `.local/core.log` / `desktop.log` files remain as historical logs. The latest `.local/desktop-status.json` still reports real native presence, connection, organism identity, GIF backend, skin state and rendering diagnostics.

## Login, reboot and logout

Both units are enabled under the user manager's `default.target`. User lingering is already enabled on this workstation: the core can start at boot before graphical login. The desktop waits quietly for a usable display and continues feeding its watchdog while waiting.

Budgie's `graphical-session.target` is inactive here, so startup does not depend on that target. A managed XDG autostart entry, `~/.config/autostart/terminus.desktop`, refreshes the graphical session metadata and restores the desktop service at login. Its helper saves only an allowlist of display/session connection variables to a private file; it never copies the shell environment wholesale or saves the organism's pairing token there. X11 availability is checked by opening and closing a display connection without requesting screen contents. Session loss or a compositor/display restart causes the native process to exit or freeze; normal restart/watchdog handling restores it once the display is usable.

Startup settings were installed and verified without rebooting the workstation or ending the user's session. A whole-system failure still needs the operating system to recover before a service can run.

## Intentionally stopping him

Unexpected exits, including a clean process exit, recover automatically. An explicit service stop is respected:

```sh
uv run python scripts/desktopctl.py stop   # body stops; core retains its life
uv run python scripts/servicectl.py stop   # stop both until a start or next login
uv run python scripts/servicectl.py start
```

**Quit desktop companion** in the native menu intentionally stops its unit, so the menu remains usable under automatic restart. To keep Terminus off across future logins and user-manager starts:

```sh
uv run python scripts/servicectl.py disable
```

This disables/stops both units and removes only the managed login bridge. It leaves all learned state intact. Run `install` again to re-enable persistent startup. `--part core` or `--part desktop` restricts a control operation to that component; starting the desktop also requests its core dependency.

## Verification

Unit files are checked by the workstation's own systemd parser before installation. Automated tests cover watchdog ownership, degraded health, private session metadata, native heartbeat validity, service routing and refusal to replace unrelated files. Runtime recovery checks target only verified Terminus service PIDs: a killed desktop, an unexpected core termination and a frozen desktop event loop must all return to an exposed, connected native body with the original organism identity and retained learning counters. No synthetic activity is inserted into the creature's history.
