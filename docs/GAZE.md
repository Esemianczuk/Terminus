# Eye gaze

Terminus moves the irises already painted in the approved source art. Each iris and its white catchlight travel together behind a fixed eyelid opening. A glance reveals a little of the shaded sclera that would have been hidden behind the iris.

![The same painted eyes glancing across the idle clip and blinking](screenshots/eye-gaze.gif)

`scripts/gaze_source_layers.py` annotates two eye openings and iris contours for each of the four open source poses. The visible iris and catchlight come from the original pixels. The hidden iris cap continues their dark pigment without adding a catchlight; the sclera backplate extends the existing shaded eye whites. These reconstructed portions are used only where moving an iris reveals them.

`scripts/build_gaze_assets.py` passes these layers and three registration markers through the original `FrameAuthor` rig. It produces the aperture, iris, backplate, true eye centers and local orbit axes for all 129 decoded frames. Each eye has three compact 96 by 64 tiles. The hash-checked atlas occupies less than 4 MB for the largest active clip. No source PNG or GIF is re-encoded.

The renderer adds the difference between the moved and neutral iris composites to the original body. Zero gaze therefore preserves the exact GIF pixels. The aperture keeps eyelid and skin pixels fixed, while a closed blink suppresses the eye layer entirely. Translation preserves the iris shape and catchlight rather than bending them with a displacement field. Travel follows the pose's local scale and bank, including the narrow middle of a turn. Raster and GPU paths use the same materials, clipping and compositing equation.

The gaze controller can watch a moving pointer when desktop awareness is enabled and healthy. A read-only Qt cursor query avoids losing short moves between coarse awareness summaries. Short eased saccades lead into smooth pursuit, then settle into quiet holds. Faster frame pacing runs only while the gaze moves. He can also look toward the core's graph attention, a focused window, somewhere nearby, or rest. Nearby screen points bring the irises slightly inward; far points keep their axes almost parallel. This is a screen-distance cue, not a depth sensor. Bank, mirroring and user scale are accounted for. Disabling desktop awareness discards pointer and window targets. Reduced motion freezes the eyes.

To add a future source pose, give each open eye an aperture outline and iris ellipse in `gaze_source_layers.EYES`. Closed poses need no annotations. The build rejects an unannotated open pose. Then regenerate the GIFs, skin atlas, eye materials, GPU assets and shaders in this order:

```sh
uv run --extra art --extra desktop python scripts/build_animation_clips.py
uv run --extra art --extra desktop python scripts/build_skin_atlas.py
uv run --extra art --extra desktop python scripts/build_gaze_assets.py
uv run --extra art --extra desktop python scripts/build_gpu_assets.py
uv run --extra desktop python scripts/build_shaders.py
```

Review future changes with:

```sh
uv run --extra art --extra desktop python scripts/review_gaze.py
# In a graphical desktop session, also compare the actual GPU framebuffer:
uv run --extra art --extra desktop python scripts/review_gaze.py --gpu-parity
```

The tool renders neutral and extreme gazes across every frame, checks alpha and fixed-lid invariants, and exports contact sheets, a 30 fps preview and timing metrics. The optional GPU comparison reads only its own fixture framebuffer and fails if hardware is unavailable or differs from raster by more than two RGB levels. The live renderer performs no such readbacks. Runtime rejects mismatched texture fingerprints and falls back to the original eyes. Eye motion does not record cursor paths, read text, install input hooks, or change the organism's learned weights.
