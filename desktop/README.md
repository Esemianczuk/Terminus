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
- Awake and closed-eye bitmaps blend during sleep/dream transitions. Breathing, appendage motion and light are visual interpolation.
- He makes slow, bounded excursions while awake, settles while resting, and pauses roaming while hovered, dragged, or using a menu. You can pause roaming explicitly.
- Click the creature to poke. Drag to move the whole presence. Alt-drag changes his position within the shared graph. Some window managers reserve Alt-drag; their modifier shortcut may take precedence.
- Right-click the body or use the tray icon for roaming, size, position, observatory and quit controls.
- Empty transparent regions are click-through. The input shape follows the rendered body, visible graph and tendrils. Status appears only on hover, briefly after changes, or when disconnected.

The default canvas is 440×340 logical pixels, most of it transparent. The visible creature occupies roughly 190–200 pixels and carries its network with it. A per-data-directory lock prevents duplicate native bodies; smoke tests do not acquire the resident lock.

The web habitat at `http://127.0.0.1:8769` remains available as an observatory and phone view. Quitting a browser does not remove the desktop body. Quitting the body does not erase learning.

## Runtime evidence

`.local/desktop-status.json` records the native process, exposed/visible state, X11 platform, window flags, bounds, core revision, graph/tendril counts and roaming state. `.local/desktop-presence.png` is a capture of the companion's own window after it is exposed and connected; it does not capture the surrounding desktop or other applications. Logs and runtime files are ignored by Git.

For foreground development or an offscreen check:

```sh
uv run python desktop/overlay.py
uv run python desktop/overlay.py --smoke-test
uv run python -m pytest -q tests/test_overlay.py tests/test_desktopctl.py
```

The offscreen check tests network and rendering paths; it is distinct from the resident launcher's verification of an exposed desktop window. Assets are watched for updates; the refined body and matching sleep pose are preferred, with original GIF fallback. Bearer authentication remains local and redirects cannot forward its token. No login autostart is installed automatically.
