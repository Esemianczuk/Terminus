# Terminus

A cute little cosmic horror, a Cthulhu-inspired Codex pet who found his way onto my desktop between prompts.

## How he got here

Terminus started with [a prompt to make my Codex pet](https://chatgpt.com/share/6ad16a28-23c0-83ea-bf9b-d18c26b81236). I wanted something cute and a little unsettling, somewhere between a cuttlefish, an octopus and a tiny Cthulhu. I work with graph theory a lot, so I gave him a network to lounge on. In my head it goes on in both directions without a natural end. He floats just outside it, a dimension up, lazily holding a few nodes and poking at others.

That is where the name came from. A *terminus* is the end of a route. Here is this little creature defining an endpoint for a graph that should not have one.

| The original Codex pet | Desktop renderer preview |
| --- | --- |
| ![The original blue and violet tentacled Codex pet](docs/screenshots/original-codex-pet.png) | ![Terminus resting, swimming and changing color on his graph](docs/screenshots/terminus.gif) |

I found myself looking at him between prompts, clicking him, dragging him around and waiting to see what he would do. Programming takes a lot of creativity, and sometimes a small, strange thing at the edge of the screen is enough to spark an idea. But the first pet was limited. Once I knew its moves, I could see the loop.

I wanted to keep *this* creature and give him more of a life on the actual desktop: room to notice things, develop habits, surprise me occasionally and go back to sleep. That became this project.

## What he does

He rests on a glowing graph, reaches toward nodes that draw his attention, and wanders off to inspect the desktop. The graph shows his contexts and associations, with light moving along its connections. His eyes can follow the pointer, converge when he looks nearby, study a node or simply look where he wants. Pick him up and he swims in the direction you carry him. His skin shimmers, ripples through color, borrows colors from the desktop on supported systems when you enable that sensor, or turns deep red. Sometimes he dissolves into symbols or releases a slow cloud of ink. He has a small invented language, and he is allowed to be quiet.

A private recurrent model learns short patterns in categories of events; familiarity and connections in his graph help steer attention and behavior. His poses, temperament and gestures are carefully made, while the timing and choices can change with experience. He keeps his local history between runs. The learning is small and specific: he can develop familiar responses, but he does not read or understand my work.

Each installation develops its own habits and keeps its history on that computer. The model stays local.

## Install

Windows 10/11, macOS and Linux are supported. You need Git, Python 3.10 or newer, and [uv](https://docs.astral.sh/uv/getting-started/installation/). The native body uses Qt 6 hardware graphics: Direct3D 11 on Windows, Metal on macOS and OpenGL on the tested Linux desktop. No model download or cloud inference account is needed.

```sh
git clone https://github.com/Esemianczuk/Terminus.git
cd Terminus
uv run python scripts/setup.py
```

On Windows, `py -m pip install --user uv` installs uv, and `py -m uv run python scripts/setup.py` works even when its executable is not on PATH.

The installer builds a local environment, starts his core and desktop body, sets up login startup and recovery, and adds **Bring Back Terminus** to your desktop. Windows uses interactive Task Scheduler jobs, macOS uses launch agents, and Linux uses systemd user services. Each runs as your desktop user. [Setup instructions for each OS and updates](docs/SETUP.md).

To try him before installing services:

```sh
uv sync --frozen --extra desktop
# First terminal:
uv run python -m terminus serve
# Second terminal:
uv run python desktop/overlay.py
```

The desktop needs a logged-in graphical session. Windows observes pointer position and window geometry; typing rhythm and sampled background colors are not implemented there yet. X11 can notice window bounds, pointer movement and aggregate typing. On macOS, window and pointer metadata work without text access; typing rhythm is available only when Input Monitoring permission was already granted. An explicit menu command can request that permission; startup never prompts. Native Wayland awareness is not implemented. Linux can also notice that an audio application has a microphone stream open, without opening a microphone or recording audio.

His body runs on Qt Quick's portable graphics layer. The artwork is packed with motion fields computed ahead of time, so adjacent poses can flow into each other while skin colors move independently. The same scene and shader assets give a future Android or iPhone version somewhere to start. There are no native mobile apps yet; the browser habitat runs only on the computer with the core.

## Living with him

Click to give him a nudge. Drag to carry him. Right-click for size, movement, facing and skin controls. Empty space around him lets clicks pass through to your other windows.

The desktop window does not accept keyboard focus. Its optional observer runs in a separate process and reports small, bounded summaries. Depending on the OS, it notices aggregate typing rhythm, pointer movement and window geometry. It never reads typed characters, key identities, window titles, clipboard contents or audio. Turn **Notice windows and typing** off in the menu to stop that observation. Waking visits and little excursions have time limits and cooldowns, so a busy day still leaves room for naps.

**Living skin → Match colors behind me** is a separate, optional visual sensor. It samples the background beneath him and immediately reduces it to four colors. The colors ease into his camouflage, preserving the painted light, texture and eyes. On macOS this needs Screen Recording permission; **Allow screen colors...** opens the system request. X11 uses the compositor's existing window images and leaves input alone. These temporary pixels and colors are never saved, sent to the core, uploaded, or used for learning. Turning the option off discards them.

His skin can also dissolve partly into ASCII, or become a whole little creature made of symbols with his eyes still intact. Occasionally he lets out an ink cloud. It curls and thins over several seconds, with currents influenced by nearby window edges and motion. Move a window beneath him and the cloud responds. **Release an ink cloud** lets you try it; **Reduced motion** suppresses it. The fluid is a bounded procedural shader, so it needs no simulation grid or growing trail of particles.

**Bring Back Terminus** checks both services and restores him if needed. Background checks also recover stopped or frozen processes. An explicit Quit or stop is respected until you bring him back.

The graph shows memory contexts and their associations. Brighter nodes are active; stronger connections draw more clearly. One tentacle follows attention and others find supporting nodes. Reaches linger before settling back, and the graph eases into changes with him. The moving lights express activity on those connections. Each connection keeps its own continuous travel phase, so a burst of activity brightens the flow without teleporting it. Their exact timing is animation, not a literal trace of each calculation. His body can bank and turn while the graph stays upright.

![Camouflage, partial ASCII and a drifting ink cloud in a controlled renderer preview](docs/screenshots/living-displays.gif)

His state lives in `.local/`, outside Git. Keep that folder. Updating the source does not give you a new creature.

## Update a machine

From its checkout:

```sh
uv run python scripts/update.py
```

This backs up the local memory database, pulls GitHub with `--ff-only`, rebuilds dependencies and restores the services. It refuses to discard local source changes. Each computer can update independently. To enable hourly checks, run `uv run python scripts/update.py --enable-auto`. `--status` shows the last result and `--disable-auto` turns them off. Documentation-only updates do not restart him. Automatic source updates are off by default.

For service status:

```sh
uv run python scripts/servicectl.py status
```

[Startup, recovery and stopping](docs/SERVICE_RECOVERY.md)

## Browser habitat

Open `http://127.0.0.1:8769` to see his wider graph, introduce a context or inspect learning. A browser on the same computer pairs automatically; there is no token to copy. The browser and desktop on one machine share that machine's core.

The core listens only on `127.0.0.1`. The browser and desktop body on that computer use the same local core. The browser receives a signed session cookie through a same-origin loopback request. Network clients cannot pair through Terminus. The local API is not an inter-computer connection.

## What he learns

The private predictor begins with random weights and learns event sequences. It can pick up a pattern such as activity followed by a quiet interval; it does not receive the words you typed during that activity. Familiarity changes responses; associations shape attention; sleep replays retained experience. His temperament, motives, gestures and symbol grammar are designed behavior, with learning influencing their choices.

He does not understand your screen or read what you type. The optional four-color camouflage sensor belongs entirely to the renderer. He will not grow new abilities just by being left running. A controlled repeating-sequence test demonstrates basic prediction learning; longer-term character is something to watch develop.

## Development

```sh
uv sync --frozen --extra test --extra desktop
uv run python -m pytest -q
uv run python scripts/evaluate.py
node --test tests/*.test.mjs
```

The GIF above is a controlled preview from the native GPU renderer. Original art and animation sources are documented in [the art notes](docs/ART.md). The checked-in GPU assets are ready to use; rebuilding optical flow needs only the optional art tools, and happens outside the running creature. Runtime memory, keys and local configuration stay out of the repository.

[Architecture](docs/ARCHITECTURE.md) · [Renderer](docs/GPU_RENDERING.md) · [Behavior](docs/ETHOLOGY.md) · [Skin effects](docs/LIVING_SKIN.md) · [Eye gaze](docs/GAZE.md) · [Desktop awareness](docs/DESKTOP_AWARENESS.md)

## License

[MIT](LICENSE). The character artwork was generated and refined for this project; its source and prompts are retained with the art notes. Dependencies keep their own licenses. [Qt for Python / PySide6](https://doc.qt.io/qtforpython-6/) is available under LGPLv3, GPLv3 or a commercial license. Redistributing an application must meet the terms of the Qt modules and other dependencies it includes.
