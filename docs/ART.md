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

Procedural breathing, tint, pose interpolation and appendage accents express current core state. They are visual interpolation, not an independent personality simulation. The native body maps the approved alpha art across a continuous 40-patch texture mesh: mantle movement, flowing arms, tilts and peering can move differently. Registered awake/sleep art supplies blink envelopes, and stretch/yawn art supplies sparse alternate poses. This is a 2D image mesh plus code-drawn tendrils, rather than a full anatomical skeletal rig. The original GIFs remain intact as genuine frame animation.

### Exact sleep-pose prompt

> Use case: precise-object-edit. Asset type: second frame/pose for the exact same 2D game creature, Terminus. Input image is the final approved alpha body asset. Keep every pixel of the body silhouette, tentacles, fins, spots, colors, texture, pose, composition, 1205x1306 canvas proportions, scale, position and transparent background as close to identical as possible. Change ONLY his two eyes to peacefully fully CLOSED sleeping eyes. The upper blue-green eyelids relax downward over the irises; each eye is now a single gentle sleepy dark-teal curved crease with blunt ends. No eyelashes or flicked wings, no makeup, no human eyebrows, no tears, no blush. His expression remains cute, cheeky and boyish/androgynous leaning male even asleep. Do not shift the head, tentacles or outline, do not recolor the body, do not alter the lighting. This image will cross-fade directly over the attached image, so registration and silhouette consistency matter enormously. No graph, no text, actual transparent background.

## Additional physical key poses

`web/assets/terminus-stretch.png` (1205×1306 RGBA) and `web/assets/terminus-yawn.png` (1204×1306 RGBA) were made with the built-in Image Generation tool from the approved refined body. The renderer registers their visible bounds and baseline; the source bitmaps remain intact. These supplement the continuous native texture rig rather than replacing it with unrelated frame generation. Eyes retain blunt edges, modest highlights and the same cheeky androgynous, subtly boyish expression.

### Exact stretch prompt

> Use case: identity-preserve. Asset type: additional animation key pose for Terminus, the exact cuttlefish cosmic-horror desktop pet in the attached approved image. Make a full-body LEISURELY STRETCH pose on actual alpha transparency. Preserve exact recognizable character, rounded mottled teal mantle, small ear fins, blue/cyan glowing spots, maroon-violet body shadows, detailed pixel-painterly bitmap texture, cute cheeky androgynous slightly boyish identity and subtly half-lidded eyes. The same creature lazily lowers and broadens his mantle a little as if sprawling on an invisible graph hammock, extends two side tentacles outward in loose curved stretches, other curls still support the body. One fin relaxes outward; tiny amused head tilt. No bodybuilder pose, no humanoid hands. Preserve refined simple blunt eye borders, small iris highlights, absolutely no eyelashes, eyeliner wings or purple makeup. Camera, body scale and feet/base line should closely match the reference, centered in a 1205x1306-proportion canvas, complete body and all stretched tentacles inside the frame with safe padding; do not crop. Only a moderate silhouette change so the pose can smoothly blend with the reference. Subject alone, no graph, no nodes, no floor, no text, no background, real transparent alpha. No new anatomy, costume or accessories.

### Exact yawn prompt

> Use case: identity-preserve. Asset type: matching YAWN / waking-up animation key pose for Terminus, exact approved cuttlefish cosmic-horror desktop companion in attached image. Preserve his recognizable rounded teal mantle, small ear fins, curling tentacles, blue/cyan bioluminescent spots, maroon-violet shadow palette and detailed bitmap/pixel-painterly surface. Make him perform one soft adorable sleepy yawn: eyes peacefully fully closed with simple blunt dark-teal crease lines, mantle gently raised, small fins fanning slightly, front tendrils delicately uncurling/spreading just enough to suggest a hidden tiny round dark mouth under them. Keep this a cuttlefish expression, not a human face; no teeth, tongue, eyebrows, exaggerated open cartoon jaw or scary snarl. Tentacle curls and posture remain almost registered to the original: same front camera, body size, centered location, feet/base line and 1205x1306 canvas proportions, all anatomy in frame with safe padding. Cute cheeky androgynous subtly boyish identity; no eyelashes, swept eyeliner, makeup or blush. This will be a sparse transition pose blended with the original body, so keep all non-expression body details extremely consistent, only a restrained yawn/stretch gesture. Subject alone, actual transparent alpha, no graph, no nodes, no floor, no text or background. No extra anatomy, clothes or props.
