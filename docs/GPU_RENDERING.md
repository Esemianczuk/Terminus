# The desktop renderer

Terminus uses the Qt 6 scenegraph and its Rendering Hardware Interface. Qt picks
the platform graphics backend, including Metal on a Mac. The same shader package
contains SPIR-V, GLES, desktop GLSL, HLSL and Metal variants. The rendering code
does not select a GPU or initialize a separate compute workload. Optional background color sampling runs in a separate bounded process and supplies twelve RGB values, never a screen texture.

The existing native presence window still owns dragging and the small input
shape. Its transparent `QQuickWidget` child renders the complete scene: the
creature, memory network, traveling signals, tapered arms, glyphs and brief status
label. The child has no focus, input handlers or autonomous render timer. The
presence controller supplies a bounded frame rate and can freeze its clock.

## The body and its eyes

The approved GIFs remain the source artwork. An offline packing tool copies their
129 decoded frames into twelve atlases. A test compares every packed frame with
Qt's GIF decoder, including premultiplied transparency. The largest current clip
uses about 17 MiB of GPU texture storage. Images have caching disabled so changing
clips releases the previous atlas rather than keeping every clip resident.

GPU playback keeps timing and anchor metadata rather than 129 decoded GIF
images. All frame slots share one transparent 624 KiB canvas. At the native hit
test interval, a separate CPU cache crops the exact source pixels from only the
current clip's PNG atlas. That cache holds at most one atlas and one frame, less
than 18 MiB, and never reads the GPU framebuffer. The complete GIF decoder stays
available for the explicit reference renderer and graphics compatibility path.

Two much smaller opaque data atlases contain forward and backward optical flow,
flow confidence and the registered eye guard. The guard includes an expanded soft
margin. The shader refuses to recolor an eye when either contributing pose marks
it as protected. Data textures always have opaque alpha so Qt's premultiplication
cannot corrupt their vector channels.

The pigment shader produces shimmer, traveling color, camouflage and crimson
displays from a small set of uniforms. It retains the painted shading and
highlights. There is no per-frame NumPy material, CPU recoloring, texture upload
or GPU readback.

## Movement between authored frames

The interpolation follows the bidirectional advection approach used in Weather
Smear. OpenCV DIS estimates both directions once during asset authoring. The
runtime shader reconstructs an intermediate image by sampling the two source
poses along their motion fields. Forward/backward disagreement attenuates the
warp locally. Each displacement component is bounded to 64 source pixels and quantized to
8-bit channels. Uncertain or newly appearing details blend instead of receiving
an unchecked displacement.

The interpolation preserves exact authored endpoints. Mirroring is an immediate
transform of the whole creature. Color, eyes, flow and silhouette therefore turn
together without a flip animation. This is display interpolation, not generated
artwork or a new observation added to the creature's memory.

## Network and perception

The graph uses scenegraph curve geometry and a single reusable glow texture.
Persistent list models keep node, edge, arm and glyph delegates alive while their
primitive values change. Updating a frame does not replace a JavaScript list and
rebuild the scene. Rows are inserted or removed only as needed; uniform time
moves the signals. Three small tapered arm meshes follow actual attention
contacts. There is no raster canvas to shade, copy, brighten and upload on every
tick.

`desktop/graph_motion.py` eases the visible anchor, node positions, activation,
focus and contact strength toward real core targets with damped position easing and smooth activity envelopes. Graph curves, limbs and hit geometry use the same
filtered coordinates, so a limb cannot trail behind a separately moving node.
Connection travel phases integrate velocity independently of activity; stable connection IDs also keep curve shape and signal phase intact when snapshot ordering changes. The view temporarily uses about thirty updates per second while those changes
settle, then returns to its quiet cadence. Reduced motion applies targets
directly; stale state freezes the presentation. This filter changes no organism
state, creates no events and owns no timer or second simulation.

Coarse window rectangles remain private awareness used for gaze and exploration;
they are not drawn as boxes behind the memory graph. Cursor movement and an
available microphone-use flag can have small visual cues. These are metadata. The independent opt-in color worker samples the background only for rendering; it does not send images or colors to learning. Neither observer reads window titles, typed text or recorded audio. Missing platform
permissions or unavailable sensors leave the relevant cues absent.

## Rebuilding and measuring

Generated assets are committed, so ordinary installation needs neither OpenCV
nor a shader compiler. To rebuild the textures during development, run the
authoring script in an environment with Pillow, NumPy and OpenCV:

```sh
uv run --extra art --extra desktop python scripts/build_gpu_assets.py
uv run --extra desktop python scripts/build_shaders.py
```

The eye materials are separate registered textures in `web/assets/gaze/`. They hold fixed apertures, sclera backplates and rigid iris layers in small tiles. Rebuild them with `scripts/build_gaze_assets.py` after changing source art or eye annotations. See [Eye gaze](GAZE.md) for the full authoring order and automated visual review.

To profile a presentation fixture with the real desktop's graphics backend:

```sh
uv run --extra desktop python scripts/profile_gpu.py --seconds 20 --fps 8
```

This launches only its own noninteractive widget. It does not read the desktop or
write observations to the organism. The report includes the actual RHI backend,
rendered-frame count, process CPU time, resident memory and submission latency.
`--screenshot path.png` explicitly reads back the fixture once after profiling.
An offscreen software result is not evidence of hardware rendering.

The hardware scene requires a functioning graphics driver. A rendering failure
must select the controller's quiet compatibility path rather than repeatedly
restarting the graphics backend. No software can guarantee that a driver, input
stack or operating system will never fail.

Qt's graphics portability does not supply mobile application integration. A
future Android or iOS app can reuse the scene, shader and asset format, but still
needs platform packaging, lifecycle management and permissions. An iPhone app
cannot provide an unrestricted overlay above other applications.

## macOS native presentation

Create the GPU child before creating the top-level native window. On macOS, calling `winId()` first creates a raster-backed native window; adding a Metal `QQuickWidget` afterward can render internally while the compositor sees an empty panel. The startup sequence now establishes the GPU backing store before configuring the nonactivating panel.

`python scripts/verify_macos_presentation.py --output work/mac-presentation` checks the actual compositor image of its own panel, then moves and resizes it and checks again. It also checks that the frontmost application and keyboard-focus eligibility are unchanged. This own-window test does not need permission to capture other applications. GPU frame counts alone are not treated as visibility proof.
