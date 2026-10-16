# Verification record

2026-10-15, local workstation. This is a working first implementation, with explicit limits below.

## Automated checks

- `uv sync --extra test --extra desktop` completed in an isolated `.venv`; `uv.lock` records exact dependencies. Runtime used CPython 3.13.14. The project supports Python 3.10+.
- `uv run python -m pytest -q`: 42 passed, including 10 native overlay subtests. Core cases cover learning beyond event frequency, habituation, zero-intensity silence, ignored presence, quiet sleep cycles, real scaffold activation, exact restored RNG/model continuity, bounded state, one-writer locking, atomic failure rollback and authenticated concurrent WebSockets.
- `node --test tests/*.test.mjs`: 6 passed. Actual client code runs in an inert DOM harness; covers cached offline/auth-unknown queuing, confirmed 401 blocking, same-ID replay without internal metadata, isolation from stale client outboxes, bounds/expiry and service-worker access boundaries, plus graceful loading of aligned sleep artwork.
- `node --check web/app.js` and `node --check web/service-worker.js` passed with bundled modern Node.
- `uv run python scripts/evaluate.py --output docs/evaluation.json` records an isolated synthetic experiment. After 600 balanced work/break events (599 gradient updates), frozen next-event inference is 100% accurate on 120 additional alternating events; cold model accuracy is 0.83%. This is temporal continuation of the same simple pattern, not held-out worlds, general understanding or proof of long-term intrigue. Evaluation never accesses the live organism.
- The seed 814 quiet simulation spends 86.6% of 1,000 seconds in sleep/dream. This is a bounded seeded simulation result, not a measurement of a month of real usage.

The first GitHub CI run caught a test harness launching the system Python instead of the locked environment for native subprocess checks. The harness now uses `sys.executable`, so subprocesses use the same dependency environment as the test runner.

The installed FastAPI TestClient emits an upstream Starlette/httpx deprecation warning. It did not fail the checks.

## Live browser evidence

The habitat was paired via a local token file without exposing its secret in URLs or logs. Browser actions verified:

1. Live state and a graph rendered with the refined transparent body.
2. Click generated an accepted `poke`; introducing `Terminus build` created a manual context and a visible sparse utterance.
3. Pointer dragging changed the authoritative normalized position and a second browser window rendered the same state.
4. A 390×844 viewport showed a usable phone layout without horizontal overflow. This is browser responsive testing, not installation on a physical phone.
5. Stopping only this project's core and reloading loaded the cached app with a dated saved-view/reconnecting indicator, paused visual motion and no independent organism updates.
6. An explicit `Offline continuity verified` context queued after the offline reload. After restarting the same core, natural reconnect restored sync; SQLite event history contained exactly 1 delivery of that context. The organism retained its identity, position, learned weights and history.

An initial offline-reload test exposed auth-unknown being mistaken for pairing-required. A second development test exposed an old open tab consuming a newer outbox schema. These were fixed with distinct auth-unknown/required states, server-authorized replay, and a versioned organism-scoped outbox. The initial failed test was not counted as a success; the final distinct-label delivery was verified in SQLite.

Captured live browser screenshots: [desktop habitat](screenshots/desktop.jpg), [390-pixel phone layout](screenshots/phone.jpg).

## Native body and collectors

The initial native check was offscreen only. The desktop-presence revision was subsequently launched as a resident native application on the real X11/Budgie session using Qt `xcb`. Its own heartbeat confirmed `visible=true`, `exposed=true`, `translucent=true`, `topmost=true`, `frameless=true`, `accepts_focus=false` and `connected=true`. The 440×340 window appeared at the lower right of the 5120×1352 available screen. It rendered the same organism ID as the core, with 29 actual graph nodes, 38 edges and three touching tendrils at the time of verification.

The desktop body stays running independently of the browser or launching terminal. Starting it twice reused the same process. Stop/restart affected only the owned native process; the original organism core remained running with the same identity and continuing revision. No login autostart was installed.

Eight native tests cover click/native drag/graph drag separation, transparent input shape, real node/tendril contacts, sparse utterances, bounded roaming, hover/menu/rest/pause behavior and authentication/redirect boundaries. Eleven launcher tests reject unrelated processes and stale/malformed presence heartbeats, check exposed native connection requirements, and verify that changed process ownership cannot receive a stop signal.

The resident captures its own widget after exposure and connection. [Native companion preview](screenshots/native-presence.png) shows that capture composited onto a neutral background; [transparent capture](screenshots/native-transparent.png) preserves the original alpha. This capture does not include other applications or the surrounding desktop. Neutral-background previews are rendering checks rather than full-desktop screenshots. Inactive transparent corners and the former permanent status area are outside its input region, so they pass clicks to applications underneath.

The metadata collector's `--once` mode delivered real time/presence events and emptied its outbox. Tests cover private file permissions, expiry, 256-event retention, deduplication/replay and refusal to send a token over remote plain HTTP. Continuous app-focus or project monitoring was not enabled.

No existing GPU workload was stopped or reused. Kestrel and CocoIndex services remained untouched. No Stable Diffusion process was started. New art used the built-in Image Generation tool; originals in Downloads stayed unchanged.

## Current scope

The core, authenticated multi-client protocol, responsive cached phone habitat, resident transparent native companion, learning/association policy and metadata collector are implemented. The refined body has smooth procedural visual motion and alternate rest art; it does not yet have a fully segmented skeletal rig. Remote HTTPS/tunnel configuration, physical phone installation, native phone telemetry, widgets and live wallpaper remain deployment/platform work. No claim of biological cognition, semantic screen understanding or long-term emergent personality is made.
