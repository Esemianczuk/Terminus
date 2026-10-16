# Verification record

2026-10-15, local workstation. Resident desktop revision plus end-to-end behavior and animation review, with explicit limits below.

## Automated checks

- `uv sync --extra test --extra desktop` completed in an isolated `.venv`; `uv.lock` records exact dependencies. Runtime used CPython 3.13.14. The project supports Python 3.10+.
- `uv run python -m pytest -q`: 86 passed, plus 14 native overlay subtests. Core cases cover learning beyond event frequency, habituation, zero-intensity silence, ignored presence, quiet sleep cycles, real scaffold activation, exact restored RNG/model continuity, bounded state, one-writer locking, atomic failure rollback and authenticated concurrent WebSockets.
- `node --test tests/*.test.mjs`: 6 passed. Actual client code runs in an inert DOM harness; covers cached offline/auth-unknown queuing, confirmed 401 blocking, same-ID replay without internal metadata, isolation from stale client outboxes, bounds/expiry and service-worker access boundaries, plus graceful loading of aligned sleep artwork.
- `node --check web/app.js` and `node --check web/service-worker.js` passed with bundled modern Node.
- `uv run python scripts/evaluate.py --output docs/evaluation-v3.json` records the current isolated synthetic experiment; `docs/evaluation.json` retains the earlier result. After 600 balanced work/break events (599 gradient updates), frozen next-event inference is 100% accurate on 120 additional alternating events; cold model accuracy is 0.83%. This is temporal continuation of the same simple pattern, not held-out worlds, general understanding or proof of long-term intrigue. Evaluation never accesses the live organism.
- The schema-3 seed 814 quiet simulation spends 84.6% of 1,000 seconds asleep, with 40 seconds inspecting and 114 seconds idle. No experience was supplied, so it does not invent a dream memory. The earlier schema-2 result was 86.6% resting. This is a bounded seeded simulation result, not a measurement of a month of real usage.

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

The core, authenticated multi-client protocol, responsive cached phone habitat, resident transparent native companion, learning/association policy and metadata collector are implemented. The refined native body has a continuous 40-patch texture mesh, gesture-driven graph contacts and registered rest/stretch/yawn art; it does not have a full anatomical skeletal rig. Remote HTTPS/tunnel configuration, physical phone installation, native phone telemetry, widgets and live wallpaper remain deployment/platform work. No claim of biological cognition, semantic screen understanding or long-term emergent personality is made.


## Behavior and animation review

The review added stable identity-derived temperament, slow exploration/comfort/affiliation motives, finite core gestures and motion intents, lingering attention, learned-association revisits and novelty recovery after absence. No-input tests confirm there are no invented external observations, memory nodes, learning updates or dream replays. Longer controlled sleep tests confirm occasional short surveys instead of permanent inactivity. Exact JSON restoration continues the same future stochastic sequence.

The native body adds head peering, double blinks, separate mantle/arm deformation, curling, touch/drag springs and identity-preserving stretch/yawn poses. Motion follows core intent along longer bounded monitor-edge paths. Tests cover stale/degraded state, expired gestures, monotonic gesture playback, retained roaming destinations during sleep, reduced-motion stillness, clamped persistent view settings and network boundaries.

[Gesture vocabulary contact sheet](screenshots/native-vocabulary.png) comes from `scripts/render_motion_study.py`. It is a labelled controlled fixture study, not evidence of autonomous live behavior or a full-desktop capture. The generated art and exact prompts are recorded in [ART.md](ART.md).

The audit found and fixed these reliability issues:

- Every idle tick wrote the full model to SQLite. An isolated identical 60-tick replay now performs 4 periodic saves rather than 60, reducing measured WAL writes from 4,223,032 to 692,192 bytes. Accepted events still persist immediately; clean shutdown saves the final state.
- A failed checkpoint could kill the life loop while health stayed green. Injected storage and tick failures now verify retry, rollback, truthful degraded health and recovery. Store initialization/close failures release resources and preserve the original exception.
- Delayed outbox events lost their observation time. Collector/web replay now preserves it, including legacy queue timestamps. Historical inputs cannot wake/move the current creature, and reordered/gapped inputs cannot create a false adjacent model transition.
- A backward wall clock could appear healthy despite no core progress. Tests now require degraded clock-blocked health, unchanged state and automatic recovery when wall time catches up.
- An initial WebSocket send could leak registration. Failure, timeout and cancellation tests verify bounded cleanup and a usable subsequent connection.
- Process identity could be queried before a new child completed exec. Manager startup now retries identity verification; ownership and concurrent-start checks prevent signalling or adopting unrelated processes.
- An unfinished roam destination could keep sleep rendering at 25 fps. Cadence now uses the same motion eligibility predicate as movement, while keeping finite gestures responsive.

Before the live upgrade the owned body/core were cleanly stopped and a private SQLite backup was retained in ignored runtime storage. An isolated migration of that exact saved creature preserved identity, all model values, RNG state and revision exactly while moving schema 2 to 3. Subsequent live ticks and genuine habitat events naturally continue changing that state.

The new resident body was verified on the actual X11 `xcb` session, exposed/visible, transparent, topmost, frameless, connected and refusing focus. It retained the existing placement and organism ID. Live sampling observed self-chosen curls, stretches and dream gestures; this observation is separate from the controlled gallery. The browser observatory reloaded, reconnected and displayed the same current habitat events. Only this checkout's managed processes were restarted.


A final 46-second resident sample included an awake survey, tendril inspection, curling, stretching and a return to sleep. The window moved from x=4539/y=1008 to x=4277/y=1040, then settled. The process used 10.24% of one CPU core across that mixed active/rest interval. This is a short live sample, not an idle average or a controlled before/after comparison. Sleeping without an active gesture returned to a 167 ms repaint interval; faster gesture/travel intervals were also observed. Final core health reported zero tick/persistence errors and the 15-second checkpoint interval. An isolated identical 22-node/23-edge sleep-frame benchmark measured 3.124 to 2.417 CPU ms per frame, separate from the live-process measurement.
