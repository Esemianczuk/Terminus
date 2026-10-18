# Living skin

The native body has a procedural chromatophore layer over the approved artwork. Right-click **Living skin** to choose Automatic, Shimmer, Cascade, Camouflage, Crimson, Ascii or Off. The choice survives restart. **Release an ink cloud** starts a single ten-second display.

Automatic combines iridescence with moving color bands, softens during rest, favors mottled camouflage during inspection and imitation, and emphasizes the cascade while carried or roaming. A touch gives a brief wine-red response; agitation can also bring that display forward. Attentive periods occasionally reveal islands of symbols or release ink. Coloring never creates observations, edits affect or writes history.

When desktop color sampling is enabled and supported, camouflage adopts four coarse average colors from behind the creature. Chromatophore islands vary their coverage across the painted skin, while its shading and highlights remain visible. The field follows desktop coordinates even when the body banks or mirrors. The shader receives four colors, confidence and motion values. It never receives a screenshot. Sampling and its platform permissions are described in [Desktop awareness](DESKTOP_AWARENESS.md). Without an available color field, the original mottled palette remains usable.

Ascii dissolves the skin into an analytic monospace alphabet. Full mode uses the whole skin; the automatic display reveals and restores smaller regions with a slow moving boundary. The original eyes remain readable and continue to look around. Symbols are evaluated directly in the shader at the current display scale, so there are no extra sprite sequences or font textures.

Ink is a finite, layered cloud behind the body and graph. Three noise octaves drive a folded motion field with expanding lobes, curling wisps and a soft fade. Coarse background brightness changes its tone; underlying window geometry and motion gently bend the current. Window geometry is used as a flow influence, never drawn as rectangular outlines. The cloud fades completely at the view boundary and after ten seconds. It has no feedback texture, particle buffers, fluid solver or growing history.

## GPU material

`desktop/skin.py` keeps the small material controller: mode selection, weights, smoothing and the effect clock. `desktop/shaders/body.frag` evaluates the patterns and composition on the GPU. Shared noise, irregular cells, bands, glints and blended palettes preserve the painted shading and highlights. The runtime updates uniforms instead of creating a newly shaded image on the CPU every frame.

The shader also interpolates adjacent key poses with precomputed bidirectional motion fields. It shades the resulting body in normalized coordinates, then the scene applies banking and an instant mirror. Body alpha, material, eye protection and facing stay aligned. Graph, inscriptions and tendrils are separate scene items.

Eye regions are registered for every source frame in `web/assets/clips/skin-atlas.json`, tied to source SHA-256 hashes. The offline build expands and feathers their protective margins before packing masks into the motion atlases. The shader checks both contributing poses and vetoes pigment where either marks an eye. It does not regenerate the face. Missing or changed registrations fail asset construction rather than silently recoloring unregistered artwork. The original PNGs and GIFs remain intact.

Effect weights blend over about a second; the clock does not restart when the clip or facing changes. A stale or degraded connection freezes effect phase and uniforms without hidden catch-up. Reduced motion holds a static material while allowing a different mode to be selected, and suppresses ink. Normal frame pacing follows the body: four updates per second asleep, eight quietly awake, more during gestures, handling or an ink display.

## Fallback and diagnostics

Hardware, shader or native input-shape failure selects the simpler raster sprite renderer. It retains the authored body, instant facing and finite animation sequences, but omits procedural skin shading and optical-flow interpolation. The CPU material evaluator remains an explicit reference tool for deterministic tests and authoring comparisons; production fallback does not run it.

Native diagnostics report the actual graphics backend, readiness, frame count, material weights, submission cost and bounded texture/hit caches. Repeated early GPU failures are latched into raster mode across service restarts. [Recovery and renderer retry](SERVICE_RECOVERY.md).

## Rebuild and review

The repository includes the generated textures and baked shader package. Rebuild them only after changing artwork, eye registrations or shader source:

```sh
uv run --extra art --extra desktop python scripts/build_skin_atlas.py
uv run --extra art --extra desktop python scripts/build_gpu_assets.py
uv run --extra desktop python scripts/build_shaders.py
uv run --extra art --extra desktop python scripts/review_effects.py
uv run --extra test --extra desktop python -m pytest -q
```

Pillow and OpenCV are optional build dependencies. Optical flow runs offline on the CPU; no diffusion installation, model download or generation API is required. Shader rebuilding needs Qt Shader Tools. `review_effects.py` requires a hardware Qt display and writes a contact sheet, an animated preview and timing evidence under `work/effects-review`. Its readbacks capture only its own scene against a fictional desktop. Production rendering performs no framebuffer readbacks. Eye-mask validation, source hashes, alpha endpoints, bounded caches, stale/reduced-motion holds and native input behavior are tested separately from visual runtime inspection.
