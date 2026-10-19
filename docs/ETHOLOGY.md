# An organism with a body

Terminus's visible life has two clocks: the authoritative core chooses finite actions and attention targets; the native body interpolates their physical expression. A gesture is `{id, kind, started_at, duration, strength, target_id}`. A motion intent is a finite request to rest, perch, drift or explore. A renderer does not invent new core gestures when a snapshot goes stale.

## Character and causes

Stable temperament biases are derived from the organism identity and persist. They are explicit policy parameters, not pretrained knowledge or scores earned through interaction. Slow exploration, comfort and affiliation motives interact with restfulness, curiosity, agitation, learned prediction surprise, familiarity and the graph. They can produce a brief survey during a long nap, lingering attention, a return to a known association or a sleepy stretch.

Attention uses activation, learned links, next-event expectation, lingering and experience. Familiar cues partly recover their novelty after absence; familiarity is not erased. Unseen scaffold nodes are intrinsic structure, not memories of things that happened. Dreams revisit experienced contexts, and consolidation counts only actual recorded replay. With no experience, no memories or learned model updates are fabricated.

The compact recurrent model still starts from random weights. Its prediction signal influences an explicit stochastic policy. It is not a language model, screen comprehension system or evidence of consciousness. A two-context prediction test establishes limited learnability; long-term intrigue remains something to observe.

## Physical vocabulary

Transparent GIF key poses remain the immutable source art for idle, moving, sleep and typing loops, transitions and gestures. An offline build computes bidirectional optical flow and protective masks between adjacent poses. The native GPU ShaderEffect uses those fields to warp and interpolate the artwork continuously, then blends procedural skin coloration while protecting the eyes. Mirroring stays instantaneous. Per-frame CPU shading has been retired. This renderer expresses the core's finite actions; it is not a second learner and creates no observations of its own. Curled appendages still grip actual graph nodes through registered clip anchors. Direct touch selects a poke sequence, and dragging and release select takeoff, moving and landing sequences.

An inspecting tendril takes 10.8 seconds: 3.24 seconds reaching outward, 2.70 seconds holding, and 4.86 seconds returning. Its envelope has smooth velocity at the boundaries. Nonurgent memory revisits wait until an existing reach finishes. The finite gesture keeps its own real target if global attention changes meanwhile. Supporting contacts linger for at least 1.5 seconds and need a meaningful activation advantage before swapping, so small rank crossings do not make the hammock twitch. Touch and carrying remain interruptible.

The authored stretch and yawn sequences play at 2.6 times their source duration while idle, swimming and typing keep their existing rates. Separately, a shared presentation filter eases the body anchor, graph geometry, activation, focus and contact strength. Limbs and hit testing use those same visible coordinates. Neither contact hysteresis nor interpolation adds learned associations, changes graph weights or creates observations.

The graph remains ephemeral. Soft branches and pulses are driven by actual node/edge state; contact pearls support the body; glyphs arrive from core utterances. There is no permanent status panel. Empty transparent space passes clicks through.

Desktop paths make deliberate excursions around the available monitor. Motion accelerates and settles, stays within bounds, and pauses for hover, dragging, menus, rest, reduced-motion preference or stale/degraded core state. When desktop awareness is enabled, some exploration paths can inspect a focused window's edge using its rectangle. Window content and screen images are not sampled. Actual movement drives directional swimming and instant facing changes.

## Real observations and history

The desktop supplies low-frequency observations of its own visible/exposed body and coarse local time. These indicate a running habitat, not a human typing or being productive. Explicit touches/drags and opted-in collector observations remain separate sources. No screenshots, titles, key identities or file contents are captured.

Desktop awareness supplies coarse observations under five fixed activity labels: `typing`, `typing-pause`, `pointer`, `microphone` and `desktop`. These can acquire private graph associations and participate in the same next-event learner as other actual observations. They contain no key identities, text, audio, screenshots or application titles. `microphone` means the device appears to be in use, not that Terminus heard speech. Pointer and desktop cues indicate motion and visible-window coverage; actual window rectangles stay in the local renderer.

A sustained typing bout or microphone-use cue can invite a short waking visit. Weak background typing remains quiet. A visit lasts at most ninety seconds, followed by a forty-five-second activity wake cooldown; repeated refreshes cannot keep extending the same visit. While already awake, tapping has its own forty-five-second cooldown. Passive pointer and desktop observations never wake the creature, move it or seize its attention.

After typing pauses, the core can inspect a nearby memory and make a small exploratory excursion. This waits until at least two and a half seconds after the observed activity, ends after a short finite motion, and occurs at most once every seventy-five seconds. Resumed typing cancels a pending interlude. If a pause transition is lost, the bounded activity expiry can still invite one. Old, reordered or delayed passive events cannot wake him or reenact a missed interlude after resume. No timer creates new training examples; only acknowledged observations train the predictor. The bounded policy, pending deadlines and cooldowns survive restart without replacing the creature's identity, learned weights or random stream. [Details and limitations](DESKTOP_AWARENESS.md).

Events retain observed and received times. Historical observations can contribute recorded associations without claiming current presence, waking the creature or moving it now. A large observation gap does not teach a false adjacent transition. Recent reordered direct manipulation remains responsive, while its out-of-order timing cannot corrupt the current learned sequence.

## Quiet, durable operation

Accepted events commit immediately with the model and idempotency record in one SQLite transaction. Idle dynamics checkpoint every 15 seconds and on clean shutdown. A crash can lose up to that interval of uncommitted autonomous motion/state; acknowledged events remain durable. Checkpoint failures retry without killing the life loop, and health reports degraded state instead of pretending progress. There is no cloud inference or GPU requirement.

Renderer caches downsampled art, glow textures and graph geometry, and adapts its frame rate. Scale, monitor, position, roaming and reduced-motion preferences persist separately from the organism. Restored placements are clamped to current screen bounds. A controlled motion-study script renders isolated fixtures for visual regression review; its output is labelled as fixtures and is not autonomous-runtime evidence.
