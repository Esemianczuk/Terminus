# Living skin

The native companion has a procedural chromatophore layer over his existing GIFs. Right-click → **Living skin** chooses **Automatic**, **Shimmer**, **Cascade**, **Camouflage**, **Crimson**, or **Off**. The selection survives restart. No extra animation footage, diffusion installation, GPU context, desktop capture or network service is needed.

Automatic mixes iridescence with quieter travelling colors, slows and softens during rest, brings out mottled camouflage during inspection and imitation, and emphasizes the cascade while carried or roaming. Real touch gives a brief wine-red response; the core's agitation can also bring out that display. These are visual projections of actual state and local handling; the shader never creates observations, edits affect or writes organism history. It does not sample window colors. Manual modes let the full character of each material show.

`desktop/skin.py` is a small NumPy software fragment shader. Each pattern returns a palette and local coverage in shared normalized coordinates. Smooth lattice noise and irregular chromatophore islands break up the travelling bands. Materials combine before shading so the original painted relief, highlights and surface detail remain visible. New patterns return the same palette/coverage pair and register in `PATTERNS`; `LAYERS`, `MODES` and the menu derive from that registry. The compositor is independent of the GIF state machine.

The pigment fields are evaluated at up to 192×208, then sampled onto the full 384×416 GIF frame. Its original alpha and the registered eye pixels are retained byte for byte, and its premultiplied image format is restored before Qt draws it. The body is mirrored and banked only after shading, so the effect, eye guards and instant facing stay aligned. Graph, inscriptions, tendrils and input shaping remain separate; integration tests compare the final native alpha and input region with effects off/on.

Eye masks are hand-traced vector regions, carried through the original offline pose rig. `scripts/build_skin_atlas.py` registers both eyes for every one of the 129 decoded frames, including closed lids and pose transitions. It handles merged GIF holds by unioning their protection regions. `web/assets/clips/skin-atlas.json` contains vectors and SHA-256 fingerprints, not new artwork frames. Missing, changed or invalid geometry leaves that clip unshaded. A fully protected interior margin and smooth exterior feather avoid hard color boundaries around the eyes. Original PNG and GIF files remain unchanged.

The shader clock never resets on pose or facing changes. Effect weights blend over about a second; a stale/degraded connection freezes both uniforms and phase, and reconnection accrues no hidden time. Reduced motion holds a static material while allowing a different style to be selected. Effects request 15 presentation ticks per second awake and six during sleep; existing GIF deadlines, dragging and gesture animation can render more frequently. Persistent shader buffers, shared noise, current material and output are capped at 12 MiB, in addition to the existing GIF cache. Diagnostics report the active mode, weights, eye registration, cache usage and evaluation cost.

Validation:

```sh
uv run python -m pytest -q
uv run python desktop/overlay.py --smoke-test
uv run python scripts/render_skin_study.py --video --output-dir work/skin-study
```

The preview renders controlled fixtures using real GIFs; it neither reads the resident organism nor captures desktop applications. The test suite checks all 129 frames for eye/alpha fidelity and source immutability, pattern motion on a fixed GIF frame, distinct materials, continuous automatic blends, rest/touch/movement reactions, exact stale/reduced-motion holds, instant mirroring, corrupted-atlas fallback, relief preservation, bounded memory and native menu/preferences/input-shape integration.

To regenerate geometry after deliberately changing source footage, use `/usr/bin/python3 scripts/build_skin_atlas.py` on this workstation (Qt, Pillow and OpenCV are already installed). These are optional authoring tools, not runtime dependencies. Review `eye-guard-audit.png` from the preview before accepting new geometry.
