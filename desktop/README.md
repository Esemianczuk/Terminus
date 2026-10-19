# Terminus, present on the desktop

The companion is a translucent, frameless, always-on-top PySide6 window. Qt Quick renders his body, skin and graph through Qt 6's Rendering Hardware Interface. He stays on the desktop independently of the browser.

From the repository root:

```sh
uv run python scripts/setup.py
uv run python scripts/desktopctl.py status
```

Setup installs the local environment, native services, login startup and **Bring Back Terminus** shortcut. Linux uses systemd user services; macOS uses per-user launch agents. The launchers verify an exposed, connected native window before reporting success. Starting again reuses the resident process, with one body per private data directory. [Startup and recovery](../docs/SERVICE_RECOVERY.md).

## Body and graphics

The approved GIFs remain source key poses. Offline tools pack them into texture atlases with bidirectional optical flow and eye masks. The GPU shader interpolates adjacent poses and applies skin coloration without running optical flow, image generation or NumPy shading in the live frame loop. Facing still mirrors instantly. Idle, moving, sleep and typing loops retain their phase; takeoff, landing, waking, settling and touch remain finite sequences. [Animation pipeline](../docs/GIF_ANIMATION.md).

Qt chooses an available hardware backend, such as Metal on macOS or OpenGL on X11. The scene, baked shader package and immutable textures can be reused by a future mobile shell. This repository currently installs desktop apps on Linux and macOS; it does not ship Android or iOS apps.

The normal GPU path uses timing metadata instead of decoding every GIF frame into the live image cache. Only the selected clip's textures and bounded source-alpha hit masks are needed. Graph nodes, curves, pulses, tendrils and inscriptions are scene-graph items. A shared glow texture replaces repeated CPU gradient allocation. Native hit testing uses artwork alpha and local curves, without GPU readback or desktop capture.

Frame pacing follows activity: quiet sleep uses four updates per second, quiet wakefulness eight, gestures or roaming about fifteen, and direct handling up to twenty. Reduced motion holds the body and material still. Stale or degraded core state freezes autonomous motion and effect phase.

If hardware initialization, shader loading or the native input shape fails, the body falls back to cached raster sprites without procedural skin shading or flow interpolation. Repeated early graphics failures latch that fallback across restarts instead of retrying a broken driver indefinitely. `--renderer raster` also selects it explicitly. Diagnostics report the actual backend and error.

## Interaction and attention

- Click to nudge; drag to carry. Alt-drag changes his position within the organism graph. Some window managers reserve Alt-drag for their own use.
- Right-click or use the tray for size, monitor, position, roaming, reduced motion, facing, graph visibility, skin, observation and quit controls.
- Empty space passes clicks through. The window does not accept keyboard focus; the GPU child has no input handlers or focus scope. The context menu has ordinary temporary menu interaction.
- The graph projects actual core nodes, associations, activation and attention. Supporting limbs grip selected nodes. Moving lights express graph activity; their timing is visual expression, not a trace of every calculation.
- Roaming stays within monitor bounds and pauses for rest, hover, dragging, menus or stale state. View movement never generates synthetic training events.

View preferences live separately in `.local/desktop.ini`. The default transparent canvas is 440 by 340 logical pixels. Explicit `--scale` overrides saved size. Quitting the body leaves the private organism database intact.

## Read-only surroundings

**Notice windows and typing** enables a disposable observer process. The GUI reads its bounded cache; OS or audio-server queries never run in the GUI loop. A stalled observer becomes unavailable and is terminated with bounded cleanup. It cannot inject input, grab the keyboard, activate another app, request accessibility access or open an audio stream.

X11 supplies window bounds, pointer motion and aggregate raw-keypress counts without key identities. macOS supplies on-screen window geometry and cursor position; aggregate typing pulses require an existing Input Monitoring grant, checked without requesting permission. Linux can query microphone-use metadata through `pactl`; no audio is recorded. Mac microphone-use metadata and native Wayland observation are unavailable. No titles, text, screenshots or accessible text anchors are read.

Window rectangles and pointer geometry remain in the local renderer. Only rate-limited fixed activity labels and coarse intensity reach the private core. Sustained typing or microphone use can invite a waking visit; a pause can invite a short inspection. Hard visit budgets and cooldowns preserve rest. [Observation boundaries](../docs/DESKTOP_AWARENESS.md) and [behavior](../docs/ETHOLOGY.md).

## Diagnostics and development

`.local/desktop-status.json` records native visibility, exposure, freshness, focus eligibility, organism identity, graphics backend, scene-graph readiness, frame count, cache sizes and submission cost. `.local/desktop-presence.png` captures only this companion window. Neither file captures other applications.

```sh
uv run python desktop/overlay.py
uv run python desktop/overlay.py --renderer raster --no-awareness
uv run python desktop/overlay.py --smoke-test
uv run --extra test --extra desktop python -m pytest -q
```

An offscreen smoke test checks the raster/network path. It does not verify hardware rendering or native desktop exposure. The isolated Xvfb typing test checks focus continuity around touch, drag and menus on its own synthetic display, without sending input to the live desktop. Platform runtime checks remain separate.
