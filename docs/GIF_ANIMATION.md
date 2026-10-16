# GIF states and short transitions

The native body now plays real cached multi-frame GIFs. Idle, moving, sleep and typing are persistent loops. Takeoff, landing, turning, waking, settling to sleep, poking, stretching and yawning are finite clips. Repeated core snapshots do not restart a loop or replay a transition. Dragging can interrupt a gesture and start takeoff immediately, including when the core is asleep.

The graph remains a separate live view of actual memory. Graph contacts use registered clip anchors and facing; graph labels and inscriptions are never mirrored with the body. The default graph visibility is now **Bright**, with true 2.8× light gain and a higher minimum edge visibility. **Subtle / Clear / Bright** in the right-click menu persist with other view settings. Its unboosted input layer keeps the brighter glow from intercepting more desktop clicks.

## Assets and authoring

`web/assets/clips/manifest.json` registers a common transparent 384×416 canvas, clip roles and graph anchors. There are 12 GIFs with 129 decoded frames, approximately 7.67 MB compressed and 78.6 MiB decoded. Each clip uses a fixed palette, a reserved transparent index, full-canvas disposal and explicit frame delays. No graph, background, text or keyboard is baked into the body.

The existing approved clean PNG poses are the art sources. `scripts/build_animation_clips.py` authors registered pose, eyelid, fin and arm frames offline on the CPU, then encodes actual GIFs with Pillow. Its small image rig is a build tool; the resident body draws one decoded GIF frame and does not run the old mesh deformation or pose crossfades. The new runtime applies only position, small directional banking and a whole-frame mirror at the turn's narrow midpoint.

On this workstation, `/usr/bin/python3 scripts/build_animation_clips.py` uses the already installed PyQt5 and Pillow. Alternatively, `uv run --with Pillow python scripts/build_animation_clips.py` provides the optional authoring dependency. The runtime does not require Pillow, a diffusion model, a GPU or an image-generation API. No Stable Diffusion installation or new GPU workload was needed. All downloaded originals and approved PNGs remain intact. Source and clip hashes, actual decoded delays/counts and authoring scope are recorded in `web/assets/clips/provenance.json`.

The original downloaded idle/running GIFs retain their old face and baked planet graph, so they are preserved as source references rather than substituted into the new clean-body renderer.

## Playback boundaries

`desktop/animation.py` decodes GIFs once with Qt, caps frame count/duration/dimensions and total memory, validates paths inside the clip directory and rejects a static PNG renamed to GIF. The current cache uses 82,427,904 bytes of frame data, under the 96 MiB limit. Missing or corrupt optional clips fall back deterministically; an unusable bank uses the approved static PNG fallback, with diagnostics explaining the active backend.

One authoritative core still owns attention and behavior. The client chooses a visual loop from its state, actual carrying/roaming and fresh local observations. Typing remains gated by both the finite core imitation gesture and current activity. Reduced motion holds a first frame; stale/degraded core state freezes the last presented frame and does not accumulate a hidden animation backlog.

`uv run python scripts/render_clip_study.py` renders a labelled 22.889-second controlled preview using the real GIF player and native body renderer. It does not read the live organism, observe other apps or fabricate activity into history. Tests separately verify native input/state selection, persistent loops, finite transitions, interruption, midpoint facing, freezes and fallback behavior.

Independent Pillow and Qt review verified every clip's frame count, timing, alpha and loop flags. No frame touches a canvas edge; graph anchors stay on opaque body pixels even during the narrow turn. Takeoff/landing endpoints match their adjacent loops, and loop seam differences remain comparable to ordinary frame steps. Transitions use discrete keyposes, without a translucent dissolve between different silhouettes.
