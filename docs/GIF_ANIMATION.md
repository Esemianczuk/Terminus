# Key poses, motion fields and short transitions

The approved GIFs supply the native body's key poses and timing. Idle, moving, sleep and typing are persistent loops. Takeoff, landing, waking, settling, poking, stretching and yawning are finite sequences. Facing instantly mirrors the current pose without resetting playback. The unused turn sequence remains a reference asset; there is no turning dissolve. Repeated core snapshots do not restart a loop or replay a transition, and carrying can interrupt a gesture immediately.

Stretch and yawn use 2.6 times their source duration, giving each shipped one-second flourish 2.6 seconds to unfold. This is a playback-time adjustment; it changes neither source frames nor hashes. Idle, moving, sleep, typing and the other transition rates remain unchanged. The player supplies the exact normalized frame phase and scaled frame deadline, so the GPU morph follows the slower gesture instead of accelerating between its key poses.

The graph remains a separate view of actual memory. Contacts use registered anchors and facing; graph geometry and inscriptions are never mirrored with the body. Subtle, Clear and Bright graph settings persist separately from memory. Bright is the default. Extra light does not enlarge the input shape.

## Source assets

`web/assets/clips/manifest.json` registers twelve GIFs with 129 decoded key poses on a common transparent 384 by 416 canvas, finite/loop roles, delays and graph anchors. No graph, background, text or keyboard is baked into the body. Source hashes, delays, frame counts and authoring scope live in `web/assets/clips/provenance.json`. Eye registrations and source fingerprints live in `skin-atlas.json`.

The approved clean PNG poses remain the artwork source. `scripts/build_animation_clips.py` uses its small offline image rig to author eyelid, fin and arm poses and encode GIFs. The original downloads retain their earlier face and baked graph, so they remain references rather than being substituted into the clean-body renderer.

## Offline motion, live GPU rendering

`scripts/build_gpu_assets.py` computes forward and reverse optical flow between adjacent key poses, with consistency confidence and bounded displacement. It packs body images and low-resolution motion/eye data into immutable atlases under `web/assets/gpu/`. Texture gutters isolate adjacent tiles. A source-hash mismatch stops construction. This is an offline CPU build, not a task run by the resident creature.

The irises can move within the original painted eyes. [Gaze registration](GAZE.md) carries a small aperture field from each source pose through this same rig, including blink frames. The field moves existing iris, sclera and highlight pixels together; closed eyes have no motion field.

`desktop/gpu.py` provides validated timing metadata to the existing monotonic clip player. The normal GPU path does not decode the whole GIF bank into its image cache. Qt Quick's scene graph draws the graph and supporting limbs; `desktop/shaders/body.frag` uses the atlas phase to warp and interpolate the neighboring body poses, then applies [eye-protected skin coloration](LIVING_SKIN.md). Pose endpoints retain the authored source sampling. The result is an approximate optical-flow morph, with uncertain motion attenuated rather than treated as anatomical knowledge.

The shader is baked into a portable QSB package for Qt's graphics backends, including Metal and OpenGL. The scene and assets are suitable for reuse in a future mobile client, but this repository does not ship Android or iOS applications. Playback and material updates have one caller-controlled clock, with no QML animation timers or independent learner.

```sh
# Only needed after deliberately changing source art or registrations:
uv run --extra art --extra desktop python scripts/build_animation_clips.py
uv run --extra art --extra desktop python scripts/build_skin_atlas.py
uv run --extra art --extra desktop python scripts/build_gaze_assets.py
uv run --extra art --extra desktop python scripts/build_gpu_assets.py
uv run --extra desktop python scripts/build_shaders.py
```

Pillow and OpenCV are optional authoring dependencies. Normal installation uses the checked-in assets and does not need an art environment, diffusion model or image-generation API.

## Playback and failure boundaries

One authoritative core owns attention, finite gestures and behavior. The client selects a visual sequence from that state, actual carrying/roaming and fresh local observations. Typing requires both a finite core imitation gesture and recent real activity. Reduced motion holds a source pose and static material. Stale or degraded state freezes phase without an animation backlog on reconnection.

Native hit testing uses a bounded cache of source alpha and vector curves, without GPU readback or screen capture. Missing hardware, shader failure or unsupported input shaping selects the cached raster GIF/PNG renderer. That fallback omits flow and procedural color effects. The legacy decoder still validates paths, frame limits, dimensions, delays and total decoded memory before caching fallback frames. Repeated early graphics crashes latch fallback across restarts; [recovery instructions](SERVICE_RECOVERY.md) explain an explicit retry.

Tests check clip phase, finite transitions, interruption, instant facing, source hashes, flow/atlas bounds, eye guards, exact endpoint sampling, stale/reduced-motion holds, input shaping and fallback. Controlled render studies are fixtures, not observations inserted into the live organism. Offscreen raster smoke tests do not establish hardware-renderer or native desktop success.
