# Art and animation

## Preserved source assets

The user downloaded these from the original Terminus build:

| File | Properties | Use |
| --- | --- | --- |
| `web/assets/reference/original-terminus.png` | 1205×1305 RGB, magenta background | Unmodified identity reference |
| `web/assets/idle.gif` | 192×208, six transparent frames | Original idle animation / fallback |
| `web/assets/running.gif` | 192×208, six transparent frames | Original running animation / fallback |
| `web/assets/reference/all-states.mp4` | 288×264, 57 frames, 5 fps | Original labelled state preview |

The video is a preview with labels and an opaque background. It is not presented as a transparent atlas. The original Downloads files remain unchanged. The two GIFs retain their frame timings and binary alpha.

## Refined body

`web/assets/terminus-refined.png` is a new transparent 1205×1306 body asset without the baked graph. The app renders the actual memory graph beneath it. A first-pass sibling `terminus-refined-v1.png` is retained for comparison. All three generated assets (including `terminus-sleep.png`) were made with the built-in Image Generation tool; no local Stable Diffusion job was run. The final asset has real 0..255 alpha. No API key was needed.

The first pass preserved the character and removed the graph. The second pass removed eyeliner-like eye corners and purple eye-socket shading, reduced the iris/gloss and retained a warm half-lidded boyish expression. The final art is the default; the original remains available for comparison and future animation studies.

A matching `terminus-sleep.png` closes only the eyelids. Both renderers crossfade it over the awake body during sleep/dream. The two poses share the same 1205×1306 canvas and retain real alpha.

### Exact first-pass prompt

> Use case: identity-preserve. Asset type: transparent high-resolution 2D game creature body, for a local digital pet named Terminus. Edit target: the attached existing Terminus mascot. Preserve its exact distinctive identity, sleepy adorable miniature Cthulhu/cuttlefish shape, large rounded teal mantle, little ear fins, curling tentacles, moderately detailed bitmap/pixel-painterly texture, turquoise bioluminescent spots and restrained violet/maroon shading. Make ONLY these functional refinements: (1) the eyes should read cute, cheeky, moderately androgynous leaning male. Reduce iris size and glossy highlights a little; soften thick purple makeup-like upper lid accents; no eyelashes, eyeliner wings or feminine eye styling. Keep subtly asymmetrical half-lidded mischievous eyes and gentle expression, understated anime influence invisible unless you know. Do not make stern, angry, chiseled, human or macho. (2) Remove the four spherical graph nodes and rigid connecting rods so this is JUST the intact creature and all of its curled tentacles, floating/resting naturally as if it will drape on a separately rendered modular graph. Restore any small tentacle portions occluded by the graph. (3) Replace solid magenta background with true alpha transparency. Center the complete full creature on a transparent canvas, all tentacles and fins in frame, generous 6 percent padding. Preserve original palette, proportions, complex glowing mottled cuttlefish surface and warmth. No text, no floor, no background, no grid, no shadow rectangle. Final asset must be usable at 200px and 400px.

### Exact refinement prompt

> Use case: precise-object-edit. Edit target: attached transparent Terminus cuttlefish creature game asset. Keep the entire body, fins, tentacles, spots, pose, texture, palette, dimensions, transparent background and shape exactly unchanged. Change ONLY the eyes in a restrained way. The current eyes have little pointed black eyeliner-like wings at their outer corners; completely remove those wings and any eyelashes. Make the upper eye border a clean simple dark teal curved line with blunt ends confined to each eye socket, no black swept up edges. Remove lavender/purple makeup shading immediately around the eyes; lids remain the same textured blue-green as his face. Slightly narrower sleepy eye openings with moderately smaller teal irises and smaller restrained highlights. Expression should be cheeky and boyish, moderately androgynous leaning male, like a sly sleepy little creature, cute and gentle with hidden mischief, not feminine, not stern. No human eyebrows or added features. Very subtle anime influence. Preserve warmth and adorable proportions. Do not add anything else; no text, no graph, actual transparency.

## Local diffusion workflow

The current runtime does not use diffusion. No ComfyUI/Stable Diffusion service was active during setup, and existing Kestrel/CocoIndex GPU workloads were preserved.

For a future *offline* local image-to-image study, use the final body as the identity reference and a low denoising strength, change one pose or expression at a time, and retain the seed/model/workflow metadata alongside every candidate. Keep graph and glyphs in code. Do not ask diffusion to redraw an entire frame sequence independently: temporal consistency and identity drift are difficult to control. Treat output as reference frames for a segmented rig or carefully validated atlas, not a live generator.

Identity constraints: rounded teal mantle; small fins; eight-ish flowing curls; teal/cyan spots; purple/maroon shadow accents away from the eyes; cute half-lidded eyes with blunt simple edges and small highlights; no eyeliner/eyelashes; no human brow or macho jaw; no text, baked graph, background or HUD. Compare every candidate at 200px and 400px before promoting it. A later local SD setup should inventory GPU owners before allocating VRAM and avoid existing services.

## Motion boundary

Procedural breathing, tint, pose interpolation and appendage accents express current core state. They are visual interpolation, not an independent personality simulation. The current body is a single alpha texture, so it does not yet have independently rigged eyelids and tentacles. The original GIFs are genuine frame animation; the refined body uses smooth procedural motion. This distinction is deliberate and visible in the code.

### Exact sleep-pose prompt

> Use case: precise-object-edit. Asset type: second frame/pose for the exact same 2D game creature, Terminus. Input image is the final approved alpha body asset. Keep every pixel of the body silhouette, tentacles, fins, spots, colors, texture, pose, composition, 1205x1306 canvas proportions, scale, position and transparent background as close to identical as possible. Change ONLY his two eyes to peacefully fully CLOSED sleeping eyes. The upper blue-green eyelids relax downward over the irises; each eye is now a single gentle sleepy dark-teal curved crease with blunt ends. No eyelashes or flicked wings, no makeup, no human eyebrows, no tears, no blush. His expression remains cute, cheeky and boyish/androgynous leaning male even asleep. Do not shift the head, tentacles or outline, do not recolor the body, do not alter the lighting. This image will cross-fade directly over the attached image, so registration and silhouette consistency matter enormously. No graph, no text, actual transparent background.
