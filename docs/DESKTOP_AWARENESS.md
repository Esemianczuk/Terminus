# Desktop awareness without taking input

Terminus notices the rhythm of local activity. His activity observer does not receive text, images of other applications, window titles, clipboard contents, passwords, key identities or audio. The separate optional background-color sensor is described below. The switch in his menu and `--no-awareness` disable this observation. Turning it off reaps its helper and stops current observations; it does not erase the creature's earlier learned history.

The body never needs keyboard focus. His window is nonactivating, accepts no keyboard focus and has no keyboard shortcut registration. The observer cannot activate another application, select a text field, send input, change cursor position or acquire an input grab. Observation and the native window's focus policy are separate boundaries and are tested separately.

## How observation is isolated

All operating-system metadata calls run in one disposable child process. The renderer reads an in-memory snapshot, never waits for that process and never makes a keyboard IPC call while painting. The child runs at a lower CPU priority. It emits bounded JSON at most five times per second; the parent accepts only a fixed schema. Unknown fields, strings outside fixed enums, nonfinite numbers, stale timestamps and oversized messages are rejected. A silent or stalled child becomes unavailable after four seconds and is terminated. A child that ignores termination is killed by its owned PID. There is no automatic restart loop.

The native body can continue breathing, roaming and learning from its existing organism when an observer is missing, denied permission or unavailable. Native Wayland currently has this fallback. Android and iOS need platform-specific, permission-respecting adapters in the future.

## What each platform can see

On X11, a private XCB connection reads the active window's rectangle and passive XInput2 raw-key-press event headers. The event reader copies only ten header bytes and never decodes a key identity or keycode. Passive selection does not own, suppress, replay or redirect keyboard events. This module binds no input-grab, focus-setting, event-injection or pointer-warp API. It does not open `/dev/input`.

The X11 worker also queries cursor coordinates and a bounded set of normal mapped window rectangles on the current workspace. These rectangles are reduced to a coarse count, normalized bounds and clipped area estimate. It does not read application names or titles, identify controls, capture other applications or reconstruct their contents. The area estimate sums rectangles and clips at one; overlapping windows make it an approximation, not a measurement of visible pixels.

On macOS, CoreGraphics supplies cursor position and on-screen window geometry. The first normal window is a coarse inspection target, not a claim that an accessibility text field was located. No event tap, accessibility API or application activation is used. Keyboard rhythm uses an aggregate idle-time query only when Input Monitoring was already granted. Startup checks existing permission without prompting. The explicit **Allow typing awareness...** menu command can ask macOS for it; the app cannot grant permission itself. If permission is missing, pointer and geometry observation still work and keyboard awareness is explicitly unavailable. Window titles and owner names are never accessed. Normalized coordinates currently use the main display; precise gaze across mixed-DPI, multiple-monitor configurations remains approximate.

The former AT-SPI caret helper has been retired. It no longer starts a process or opens an accessibility text interface. The creature looks toward a window region, not a character position. This removes an unnecessary IPC dependency from typing interaction.

On Linux, an optional 3-second poll of the audio server's short list of recording streams reports only whether a recording stream is already in use. This is a microphone-use hint, not voice detection: a stream may be silent or record a monitor source instead of a physical microphone. The query opens no recording stream, requests no audio permission, reads no sound samples and stores no application metadata. Output is capped at 64 KiB and the query has a 250 ms deadline. The macOS adapter reports microphone status unavailable rather than requesting microphone access.

## Activity, behavior and memory

Typing is held as aggregate buckets in a four-second ring. A bout begins with activity, reaches a pause after 1.1 seconds without a pulse and expires to idle after eight seconds. A single key or shortcut cannot count as heavy use: the intensity requires sustained activity over at least 1.2 seconds. macOS idle timestamps produce coarser pulses than X11 event counts, so their intensity is an approximation.

The private rendering snapshot contains these fixed shapes:

```text
typing: {active, last_at, rate, pulse, sequence} or unavailable
bout: {phase: active|pause|idle, duration_s, level, pause_age_s, sequence}
pointer: {available, x, y, motion}                 # normalized, coarse
windows: {available, count, coverage, rects}      # at most eight rectangles
microphone: {available, in_use}                  # no audio
```

Window and pointer geometry stay in the native body. The only observations sent to the authenticated local core are rate-limited activity cues with fixed contexts: `typing`, `typing-pause`, `pointer`, `microphone` and `desktop`. They use the existing event kind, source, intensity and timestamp fields. A cue describes fresh real activity; failed connections do not queue observations for replay as current activity.

The local learner can associate these activity categories with quiet intervals and occasionally respond between bouts. It cannot infer what was typed or spoken. Private geometry and precise pointer paths stay in the desktop body; coarse activity cues reach only this computer's core.

## Optional background colors

**Living skin → Match colors behind me** starts a separate disposable worker, at most twice per second. X11 samples small patches from existing compositor window pixmaps behind the creature, excluding his own process. macOS captures only the panel-sized region below his window, then reduces it through CoreGraphics to a two-by-two color field. macOS Screen Recording permission is required and requested only through **Allow screen colors...**. Native Wayland is unsupported and returns unavailable.

Capture pixels exist briefly inside that worker. Only twelve RGB numbers cross its pipe. Neither pixels nor colors are written to disk or delivered to the organism or its predictor. There is no OCR, title lookup or text extraction. The palette and confidence ease into the shader over time. Missing permission, stale samples or a worker timeout fade back to the authored palette. Turning the switch off kills the owned worker and clears the palette immediately. Background colors and the activity observer have separate switches.

Coarse window geometry also supplies smooth local currents to the ink shader. That geometry stays in the body and is discarded on exit. No fluid effect can activate a window or intercept an input event.

## Verification

The observer tests exercise bounded aggregates, sustained-bout thresholds, stale snapshots, schema rejection, passive API bindings, and retirement of the accessibility text helper. Separate child-process tests cover a silent worker, an oversized pipe and a worker that ignores termination. They verify that the renderer's snapshot calls remain responsive and only the owned child is reaped. Those checks do not prove that unrelated applications or operating-system bugs cannot disrupt input.
