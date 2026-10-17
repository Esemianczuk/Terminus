# Terminus, present on the desktop

The native companion is a translucent, frameless, always-on-top PyQt5 window. It stays present independently of the browser. Its body and ephemeral graph appear directly over your applications, with no permanent panel, floor or status bar.

From the repository root:

```sh
uv sync --extra test --extra desktop
uv run python scripts/desktopctl.py start
uv run python scripts/desktopctl.py status
uv run python scripts/desktopctl.py stop
```

The launcher starts the local core only if needed, then detaches the native body so it stays running after the terminal closes. It verifies a real exposed desktop window connected to the core before reporting success. Starting again reuses the same resident process. Stop/restart validates PID, process start time, boot identity, ownership, exact script and checkout; it never stops the organism core. `--scale 1.2` selects a larger starting size.

A real graphical session and PyQt5 are required. On the current X11 desktop the launcher explicitly selects Qt's `xcb` backend, rather than inheriting a test's offscreen setting. Wayland behavior depends on compositor support for always-on-top windows and positioning.

## Presence and interaction

- The graph uses actual core nodes, edges, activation and attention. Branches softly emerge, pulse and fade; some remain faint under him as a resting surface.
- Procedural tendrils extend from the bitmap body toward the attention region and active nodes, curling over the graph. They express shared state; they are not an independent organism model.
- Actual transparent GIF loops maintain idle, moving, sleep and typing states. Short GIF clips handle takeoff, landing, waking, settling, pokes, stretches and yawns. Direction changes instantly mirror the current frame without a turning effect. A decoded frame is drawn directly; loops keep their phase across core updates. The old live body mesh and pose crossfades are removed. [Clip details and local authoring](../docs/GIF_ANIMATION.md).
- He makes bounded, accelerating excursions along the monitor's edges, settles while resting, and pauses roaming while hovered, dragged, using a menu, or receiving stale/degraded state. You can pause roaming or enable reduced motion explicitly.
- Click the creature to poke. Drag to move the whole presence: he banks into actual movement, trails his arms and settles on release. He instantly flips left/right with movement or gaze; **Look** also offers explicit Left, Right and Automatic controls. Alt-drag changes his position within the shared graph. Some window managers reserve Alt-drag; their modifier shortcut may take precedence.
- Right-click the body or use the tray icon for roaming, reduced motion, size, monitor, position, observatory and quit controls. These view preferences persist privately in `.local/desktop.ini`; explicit `--scale` overrides saved size.
- Empty transparent regions are click-through. The input shape follows the rendered body, visible graph and tendrils. Status appears only on hover, briefly after changes, or when disconnected.

The default canvas is 440×340 logical pixels, most of it transparent. The visible creature occupies roughly 190–200 pixels and carries its network with it. A per-data-directory lock prevents duplicate native bodies; smoke tests do not acquire the resident lock.

The web habitat at `http://127.0.0.1:8769` remains available as an observatory and phone view. Quitting a browser does not remove the desktop body. Quitting the body does not erase learning.

The body sends low-frequency observations of its own visible/exposed habitat and coarse local time. These indicate a running habitat. **Notice windows and typing** adds local X11 active-window geometry and aggregate keyboard activity, with an optional event-only AT-SPI text anchor. It can look toward your work, sometimes perch beside a window during exploration, and occasionally imitate actual typing. No titles, text, individual key identities or screenshots are read. Turn the feature off in the menu or use `--no-awareness`; see [the exact scope and fallbacks](../docs/DESKTOP_AWARENESS.md). Automatic observations are never queued during an outage.

## Runtime evidence

`.local/desktop-status.json` records the native process, exposed/visible state, X11 platform, window flags, bounds, core revision, graph/tendril counts and roaming state. `.local/desktop-presence.png` is a capture of the companion's own window after it is exposed and connected; it does not capture the surrounding desktop or other applications. Logs and runtime files are ignored by Git.

For foreground development or an offscreen check:

```sh
uv run python desktop/overlay.py
uv run python desktop/overlay.py --smoke-test
uv run python -m pytest -q tests/test_overlay.py tests/test_desktopctl.py
```

The offscreen check tests network and rendering paths; it is distinct from the resident launcher's verification of an exposed desktop window. Assets are watched for updates; missing/corrupt GIFs have deterministic clip or approved-PNG fallbacks, reported in native diagnostics. Bearer authentication remains local and redirects cannot forward its token. No login autostart is installed automatically.

`uv run python scripts/render_motion_study.py --output-dir work/motion-study` produces labelled, isolated gesture fixtures for visual review. These are controlled renderer studies, not live autonomous behavior or desktop screenshots.

`uv run python scripts/render_clip_study.py` exercises the current GIF state player through its loops and transitions. Right-click **Graph visibility** for Subtle, Clear or Bright; Bright is the default.

## Persistent startup and recovery

Run `uv run python scripts/servicectl.py install` after initializing the runtime. The core and native body become user services with automatic restart, event-loop watchdogs and login restoration. The existing `desktopctl.py` and `termctl.py` commands then control these services. See [service recovery](../docs/SERVICE_RECOVERY.md) for logs, reboot behavior and intentional stop/disable commands.
