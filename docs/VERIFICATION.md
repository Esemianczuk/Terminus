# Verification record

2026-10-15, local workstation. Resident desktop revision plus end-to-end behavior and animation review, with explicit limits below.

## Automated checks

- `uv sync --extra test --extra desktop` completed in an isolated `.venv`; `uv.lock` records exact dependencies. Runtime used CPython 3.13.14. The project supports Python 3.10+.
- `uv run python -m pytest -q`: 134 passed, plus 36 native/animation subtests. Core cases cover learning beyond event frequency, habituation, zero-intensity silence, ignored presence, quiet sleep cycles, real scaffold activation, exact restored RNG/model continuity, bounded state, one-writer locking, atomic failure rollback and authenticated concurrent WebSockets.
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


## Directional flight and desktop awareness — 2026-10-16

The new gate is 116 Python tests plus 14 native subtests and six browser-client tests. New cases cover actual drag direction, bank/settling, body mirroring with world-oriented graph contacts and glyphs, finite typing imitation with real-activity gates, safe window-edge perches, unchanged input footprint despite brighter graph, event-only caret geometry, privacy whitelists, expiry, secure-source suppression, observer shutdown and unsupported/XWayland session startup.

A new controlled study renders 1,007 frames at 18 fps (55.944 seconds), including flight left/right, turning, landing, window inspection and typing. Render time was median 3.315 ms, p95 4.223 ms at scale 1.3. [Directional contact sheet](screenshots/directional-vocabulary.png) is an isolated fixture, not a desktop capture or autonomous-runtime recording. Additional RGBA poses and exact built-in generation prompts are in [ART_DIRECTIONAL.md](ART_DIRECTIONAL.md).

The real X11 backend reported available, found an active-window rectangle, received aggregate keyboard-activity headers without decoding key details, and closed cleanly. The optional AT-SPI helper registered successfully; its read-only probe correctly reported no caret before a fresh accessibility event. The live resident reported `caret_source=window-fallback`; exact application text-anchor tracking was not claimed as observed in that sample. A separate backend/helper teardown probe took 0.016 seconds and reaped its helper.

The actual workstation was measured at device pixel ratio 1.0 on DP-0. X11 and Qt coordinates therefore agree on this host. High-DPI or mixed-scale coordinate mapping remains unverified and is a current limitation; geometry-based gazing/perches should be rechecked before claiming scaled-display support.

Before upgrade, both owned processes stopped cleanly and a fresh private SQLite backup was saved. Loading that exact state into the new core preserved organism identity, learned model and RNG values exactly before ticking. After restart, the real native body was visible, exposed, topmost, frameless, translucent, no-focus and connected, with desktop awareness available. A subsequent body restart reaped the old owned caret helper and restored the same view preferences while leaving the core running.

A 26-second live sleep sample included finite curl/sleep gestures and used 4.96% of one CPU core for the native process, with one caret helper. This is a short workload-specific observation, not a universal performance bound or typing/flight benchmark. Core health reported zero tick/persistence errors. No synthetic typing was injected into the live organism to manufacture a reaction. Actual drag behavior and typing rendering were verified in isolated native tests and labelled fixtures.

The live browser observatory reloaded and reconnected with the clearer graph. Native graph brightness uses 1.8× gain, with a separate original-alpha input layer; regression tests compare input shapes directly. Both observer types remain absent from offscreen studies and smoke tests, and an explicit xcb-on-Wayland test prevents accidental accessibility-helper startup in an unsupported session.


## Cached GIF state revision — 2026-10-16

The gate now passes 133 Python tests plus 32 subtests and six browser-client tests. Four real GIF loops (idle/moving/sleep/typing) and eight finite clips decode once with Qt. Tests exercise frame delays/disposal/transparency, loop phase across repeated core snapshots, takeoff/landing/turn completion, drag interruption, one-shot gesture/poke IDs, reduced motion, exact stale-frame freeze, reconnect without old transition replay, corrupt/missing/path-escape/static-image rejection and decoded-memory caps. Native tests prove direct single-GIF-frame drawing with no body mesh/crossfade and unchanged graph input footprint at different visibility settings.

The shipped bank has 12 GIFs, 129 decoded frames, 7,669,812 compressed bytes and 82,427,904 decoded frame bytes. Independent Pillow and Qt readers agree on counts, loop flags and delays. Every frame has clear canvas borders and opaque pixels at its registered graph anchors, including the narrow turn. Palette transparency preserves the pupils. Loop seams have differences comparable to ordinary adjacent frames; takeoff/moving and moving/landing endpoints differ only slightly after palette encoding (mean absolute difference 1.39, down from roughly 22 in the rejected intermediate build). The rejected clipped/jumping frames were regenerated before launch.

Frames were authored locally on the CPU from approved clean PNG poses using the saved builder and a fixed palette per GIF. Original downloaded GIF/video assets and source PNGs remain unchanged. No diffusion model, image API, GPU service or unrelated workload was used for this revision. The body now consumes actual GIF frames; the image rig exists only in the offline authoring script.

[GIF state contact sheet](screenshots/gif-states.png) and the 22.889-second, 412-frame controlled preview use the actual native GIF player and graph renderer. They do not access the live organism or sample other desktop apps. Frame-wise metadata is retained under the ignored study output; GIF/source hashes and decoded timings are in the committed clip provenance.

Only the owned desktop body was restarted; its original core and learned history kept running. On the actual X11 session the resident reported backend=gif, sleep/idle/moving clips, changing frame indices, fallback=false and clip_errors=0. Bright visibility reports gain 2.8. It remains exposed, connected, translucent, topmost, frameless and no-focus, with the same organism ID. An offscreen network/render smoke also passed.

A 22-second live sample observed idle and inspect behavior with actual idle/moving GIFs. The process used 11.82% of one CPU core during that active interval and rendered the sampled frame in 3.02 ms. This is a short workload-specific observation, not a controlled speedup claim. Core state and observation collection were unchanged. The graph's higher default brightness preserves the unboosted input layer; Subtle/Clear/Bright preferences persist privately.


## Immediate facing change — 2026-10-16

Facing now mirrors the current full-width GIF frame immediately, without selecting the turn GIF, interpolating body width or restarting playback. The mouse handler applies the new direction on the reversal event rather than waiting for smoothed flight velocity or a direction cooldown. Forced Left/Right controls still take precedence; reduced motion also flips immediately.

The regression gate passes 134 Python tests and 36 subtests. New checks reverse an actual isolated native mouse-move event by one pixel while the prior flight velocity is still rightward, verify immediate mirroring with normal/reduced motion and forced facing, and preserve GIF frame/index/loop phase when flipping idle, moving and takeoff clips. Stale-state freezing and graph/inscription orientation checks still pass. Only the owned desktop body was restarted; live native presence, GIF backend, memory identity and Bright graph preferences remain intact. The old turn asset stays preserved as an unused reference.
