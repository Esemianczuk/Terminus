# Startup and automatic recovery

Terminus keeps the organism core and desktop body in separate user processes. Restarting the body does not replace the private model or erase memory. Setup and updates preserve `.local/organism.sqlite3` and the pairing token.

```sh
uv run python scripts/setup.py
uv run python scripts/servicectl.py status
```

Setup installs only this checkout's managed services and shortcuts. It refuses to overwrite unrelated units, launch agents or shortcuts. The native body requires a logged-in graphical session.

## Bring Back Terminus

The desktop shortcut starts and enables the core, body and presence guardian, refreshes session information where needed, and verifies a fresh, exposed, connected native window. Healthy processes stay running. Explicit Quit/stop markers are cleared by a deliberate start or login restoration. The shortcut uses the approved artwork as its icon.

The quiet guardian checks about every thirty seconds. It respects intentional pauses and verifies checkout ownership before changing a process. An active service alone is not proof of a visible creature: native heartbeat freshness, exposure, connection and process identity matter too. A whole-system failure still needs the operating system and graphical session to recover first.

## Linux

`terminus-core.service` owns the authenticated loopback API on port 8769 and SQLite memory. `terminus-desktop.service` owns the native body. Both are systemd user services with `Restart=always`, a three-second delay and an event-loop watchdog. The desktop waits quietly for a usable graphical session; it does not launch a hidden offscreen body as a substitute.

`WatchdogSec=45` detects a live process whose real event loop has stalled. The core reports health from its asyncio ticker, and the body from its Qt status timer. A separate health thread cannot hide a frozen loop. Normal reconnect logic handles a core restart without repeatedly restarting a responsive desktop.

`terminus-presence.timer` runs a bounded guardian in addition to crash restart and watchdogs. A managed XDG login entry refreshes an allowlist of session/display connection variables, without copying the shell environment or pairing token. This also supports desktops whose `graphical-session.target` is inactive. Starting before graphical login depends on the user's systemd manager and any separately configured lingering; no system-wide service is installed.

```sh
systemctl --user status terminus-core.service terminus-desktop.service
journalctl --user -u terminus-core.service -u terminus-desktop.service -f
```

Current service logs go to the user journal. Older `.local/core.log` and `.local/desktop.log` files may remain as historical logs.

## macOS

Run setup while signed into the Mac desktop. It creates `org.terminus.core`, `org.terminus.desktop` and `org.terminus.presence` under the user's LaunchAgents directory, plus **Bring Back Terminus.app** on the desktop. The core and body use launchd KeepAlive. The separate guardian checks core health and the native heartbeat every thirty seconds. These are per-user GUI agents; the body cannot appear before login.

The same `scripts/servicectl.py` commands route to launchd. Logs are `.local/macos-core.log`, `.local/macos-desktop.log` and `.local/macos-presence.log`. The Cocoa panel is nonactivating and has no key/main-window eligibility; diagnostics report its actual focus state. Numerical-library thread pools are limited to one thread in the launch agents.

The optional collective exchange adds `org.terminus.collective`, a ten-minute agent. It uses only the separate category model and contribution outbox and does not expose the local API to other computers.

## Graphics failure and a quieter fallback

The normal Qt 6 RHI scene uses hardware rendering, offline flow textures and a GPU skin shader. If hardware setup, shader loading or native input shaping fails, the desktop selects cached raster GIF/PNG drawing. This compatibility path omits flow interpolation and procedural skin coloring. It preserves the creature, private memory, graph and direct interactions.

Before a GPU startup, a private `.local/.render-guard.json` marker records the attempt. Fifteen continuous seconds of visible, exposed, connected, fresh, actually rendered native frames clear a successful attempt. Two consecutive early failures within ten minutes latch raster mode across later starts. A detected initialization failure also latches raster immediately. A healthy raster restart does not clear the latch and reenter a graphics crash loop.

Use the simpler renderer explicitly for foreground diagnosis:

```sh
uv run python scripts/desktopctl.py stop
uv run python desktop/overlay.py --renderer raster --no-awareness
```

Stop that foreground process before starting the resident body again. After resolving a graphics problem, a deliberate hardware retry is:

```sh
uv run python scripts/desktopctl.py stop
uv run python -c 'from pathlib import Path; Path(".local/.render-guard.json").unlink(missing_ok=True)'
uv run python scripts/desktopctl.py start
```

Run those commands from the intended checkout. Removing this renderer marker does not remove memory. It permits another graphics attempt, so retain the fallback if the underlying driver problem remains.

## Observation and keyboard boundaries

The native window and its GPU child do not accept keyboard focus. A disposable process performs read-only OS metadata queries; the GUI never waits synchronously for those queries. The observer has no API to inject or grab input, activate apps, request accessibility access or open an audio stream. Stale or malformed output is discarded and a stalled child is terminated with bounded cleanup. Observation can be disabled from the menu or with `--no-awareness`.

On macOS, aggregate typing requires an Input Monitoring grant. Startup only checks it; the explicit menu command can request access. Linux microphone detection reads audio-server stream metadata and records no sound. No activity observer reads text, key identities or window titles. The separate opt-in camouflage worker briefly samples background pixels and returns only four averaged colors; those colors never enter memory. These boundaries reduce the application's ability to interfere with input; they are not a guarantee against faults elsewhere in the OS, driver or desktop session.

## Stop, restart and update

```sh
uv run python scripts/desktopctl.py stop
uv run python scripts/servicectl.py stop
uv run python scripts/servicectl.py start
uv run python scripts/servicectl.py disable
```

A body-only stop leaves the core running. A deliberate stop is respected until a start or login restoration. Disable keeps the managed services off across later logins while leaving learned state and the recovery shortcut intact. Run setup again to reinstall startup. `--part core` or `--part desktop` restricts service operations to that component.

```sh
uv run python scripts/update.py
```

The updater makes a consistent SQLite backup, pulls with `--ff-only`, rebuilds the environment and restores the installed services. Local source changes stop the update without being discarded. Each machine retains its own organism identity and private learning.

## Verification

`.local/desktop-status.json` reports native exposure, freshness, focus flags, graphics backend, real frame count, input shape and memory/cache diagnostics. `.local/desktop-presence.png` captures only the companion window. Offscreen smoke tests validate a raster/network path and do not establish hardware or native desktop success.

Tests cover process ownership, pause markers, event-loop watchdog health, graphics failure latching, observer validation and bounded cleanup. A separate synthetic Xvfb test checks typing through touch, drag and menus on its own display. Runtime recovery checks must target only verified Terminus PIDs and confirm the original identity and learning counters afterward. No synthetic activity should be inserted into the resident creature to demonstrate recovery.
