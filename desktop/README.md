# Terminus desktop overlay

This small, translucent, always-on-top window displays the organism and graph from the running Terminus core. The core owns behavior, memory, learning, position, and symbols. The overlay polls authenticated snapshots once per second and sends explicit interactions; it runs no organism model. Breathing and GIF playback are presentation animation only.

From the repository root, start the core, then run:

```sh
/usr/bin/python3 desktop/overlay.py --url http://127.0.0.1:8769 --data-dir .local
```

Use a Python interpreter with PyQt5 and QtNetwork installed. On this machine `/usr/bin/python3` provides PyQt5. The core creates `.local/token`; the overlay reads it without displaying it. It does not create a second core or token. Missing tokens and failed connections show a disconnected indicator, dim the last received state, and disable interactions until reconnection.

- Click the creature to poke it.
- Drag the window to place it on your desktop. A normal window drag does not move the organism.
- Hold **Alt** while dragging to choose a graph position; release to send the position to the core. The target marker is only a preview. Some Linux window managers reserve Alt-drag for moving windows; adjust their shortcut if needed.
- Right-click for **Open full habitat**, window repositioning, connection detail, or **Quit overlay**. Opening the habitat uses its ordinary URL; pair in the browser if necessary. The token never appears in a browser URL.
- Add `--scale 0.8` for a smaller window, or another multiplier between 0.65 and 2.

The default footprint is 320 × 282 logical pixels. The overlay prefers `web/assets/terminus-refined.png`, then `terminus.png`, then `idle.gif`, and notices newly available artwork every five seconds. When `terminus-sleep.png` is present, it smoothly blends the matching closed-eye pose during shared sleep/dream states. If `terminus-sleep.png` is available, it smoothly blends to the closed-eye image when the core reports sleep or dream, using the same image rectangle and breathing transform. Without it, the ordinary artwork remains visible. It never changes these files. Transparent image padding is included in the displayed bounds.

An explicitly supplied `--url` may connect to a remote core. Requests carry the local bearer token, so use the intended server and HTTPS when crossing a network. Automatic redirects are refused. Without `--url`, the only destination is `127.0.0.1:8769`.

## Verification

```sh
/usr/bin/python3 desktop/overlay.py --url http://127.0.0.1:8769 --data-dir .local --smoke-test
/usr/bin/python3 -m unittest discover -s tests -p test_overlay.py -v
```

The smoke test forces Qt's offscreen platform, fetches a real authenticated snapshot, renders a frame, and exits. It sends no interactions. Failure to authenticate, connect, load the artwork, or render exits nonzero. A successful offscreen check confirms the network and drawing paths; it does not verify visible desktop integration.

X11 supports the requested frameless/translucent/always-on-top behavior. Wayland compositors may limit programmatic positioning and always-on-top hints; behavior depends on the compositor. If Qt's Wayland backend is unavailable, `QT_QPA_PLATFORM=xcb` can use an existing XWayland display. The overlay does not install desktop autostart entries or launch itself persistently.
