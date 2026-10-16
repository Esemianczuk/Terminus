# Flight, looking and quiet imitation

The native body now uses actual drag/roaming velocity to bank, float and trail its arms. Facing moves continuously through a small squash before mirroring, while the graph and inscriptions retain their world orientation. Release eases back into a settled pose. Right-click **Look** for Automatic, Left or Right; that choice persists with other private view preferences. Reduced motion removes continuous flight, tapping and turning interpolation.

Autonomous excursions still require a fresh core motion intent. Some exploration paths can pause beside the focused window's edge, with monitor bounds and a cooldown. The body looks toward a fresh accessible text anchor when available, otherwise toward the focused window. It does not understand or inspect the window's contents.

## What the local observer reads

**Notice windows and typing** is enabled for this requested feature on the real X11 desktop. The checkbox or `--no-awareness` disables it. Disabled, offscreen and unsupported Wayland runs do not start the X11 observer. Turning it off closes the observer and its optional accessibility helper; it does not erase learned organism history.

- X11 contributes the active window's rectangle and whether it belongs to this native body. No title, application text, image, clipboard or file content is requested.
- XInput2 contributes aggregate keyboard-activity counts in a bounded four-second in-memory ring. The code decodes only the generic event header, never key identities, keycodes or typed characters. Keyboard activity can include shortcuts; it does not prove that meaningful text was entered.
- When system Python has `pyatspi`, a separate bounded helper listens only for focus/caret events. It queries the event source's focused/visible state, password role, caret offset and character geometry. It never requests text, names, titles, ancestor contents or a desktop accessibility-tree scan.
- Accessibility geometry is labelled `glyph-edge`: the leading edge of the current glyph or the trailing edge of a preceding glyph at end-of-text. This is a text anchor, not a guarantee of the exact cursor pixel in every app, writing direction or ligature. Samples expire after 2.8 seconds. No position is invented when the app exposes none.
- A known password source suppresses geometry and typing reactions. Without accessibility support, field sensitivity is unknown; the X11 observer still has only aggregate activity and window bounds, with no characters or key identities.

Coordinates, activity rates and accessibility objects stay in the local renderer. At most once per 45 seconds of fresh actual activity, it may send the fixed label `activity:typing`, intensity 0.16, to the same authenticated core. There is no automatic outbox and nothing is replayed as current typing after an outage. Automatic observations cannot send a pairing token to a new destination.

## Why he sometimes copies you

The authoritative core may choose a six-second `imitate` gesture after a recent real typing cue while awake and calm. Familiarity and learned surprise influence that choice, and a persisted 45-second cooldown prevents repeated gestures. Sleep, stale observations, zero intensity, manual labels and generic activity cannot trigger imitation. The body renders alternating tentacle taps only with a matching finite core gesture and fresh local keyboard activity; it eases out when activity stops.

This is a small explicit behavioral policy informed by a local recurrent predictor. It is not reading or predicting your text. The brighter graph remains the same actual associative network; a separate input layer preserves its previous click-through footprint.

The motion-study script renders labelled isolated fixtures for flight in both directions, turning, landing, window inspection and typing, in addition to the earlier gestures. Those fixtures do not access the live organism, observe other apps or prove autonomous runtime choices. Art prompts and original RGBA paths are recorded in [ART_DIRECTIONAL.md](ART_DIRECTIONAL.md).


Window geometry is currently verified on this workstation at device pixel ratio 1.0. High-DPI and mixed-scale X11/Qt coordinate mapping is not yet normalized or validated. Native presence and keyboard-activity counting are distinct from that geometry limitation.
