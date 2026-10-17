# The desktop renderer

Terminus uses the Qt 6 scenegraph and its Rendering Hardware Interface. Qt picks
the platform graphics backend, including Metal on a Mac. The same shader package
contains SPIR-V, GLES, desktop GLSL, HLSL and Metal variants. The rendering code
does not select a GPU, initialize a separate compute workload or capture a screen.

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
Topology and node values change when the core state changes; uniform time moves
the signals. Three small tapered arm meshes follow actual attention contacts.
There is no raster canvas to shade, copy, brighten and upload on every tick.

An optional, faint sketch of the visible desktop uses normalized window
rectangles and cursor position. It contains no screenshots, titles or text. The
renderer only displays primitives supplied by the local awareness controller.
Missing platform permissions or unavailable sensors simply omit the sketch.

## Rebuilding and measuring

Generated assets are committed, so ordinary installation needs neither OpenCV
nor a shader compiler. To rebuild the textures during development, run the
authoring script in an environment with Pillow, NumPy and OpenCV:

```sh
uv run --extra art --extra desktop python scripts/build_gpu_assets.py
uv run --extra desktop python scripts/build_shaders.py
```

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
