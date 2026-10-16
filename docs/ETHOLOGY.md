# An organism with a body

Terminus's visible life has two clocks: the authoritative core chooses finite actions and attention targets; the native body interpolates their physical expression. A gesture is `{id, kind, started_at, duration, strength, target_id}`. A motion intent is a finite request to rest, perch, drift or explore. A renderer does not invent new core gestures when a snapshot goes stale.

## Character and causes

Stable temperament biases are derived from the organism identity and persist. They are explicit policy parameters, not pretrained knowledge or scores earned through interaction. Slow exploration, comfort and affiliation motives interact with restfulness, curiosity, agitation, learned prediction surprise, familiarity and the graph. They can produce a brief survey during a long nap, lingering attention, a return to a known association or a sleepy stretch.

Attention uses activation, learned links, next-event expectation, lingering and experience. Familiar cues partly recover their novelty after absence; familiarity is not erased. Unseen scaffold nodes are intrinsic structure, not memories of things that happened. Dreams revisit experienced contexts, and consolidation counts only actual recorded replay. With no experience, no memories or learned model updates are fabricated.

The compact recurrent model still starts from random weights. Its prediction signal influences an explicit stochastic policy. It is not a language model, screen comprehension system or evidence of consciousness. A two-context prediction test establishes limited learnability; long-term intrigue remains something to observe.

## Physical vocabulary

The native body has an articulated texture mesh: the mantle breathes and shifts separately from flowing tentacles; head tilt and peering respond to a target. Registered awake/sleep art expresses blink envelopes. Additional identity-preserving stretch and yawn poses blend into the same body. Curled appendages grip actual graph nodes; gestures change their reaching and curling shapes. A direct touch produces a damped physical response, while dragging gives the body a short springy settle.

The graph remains ephemeral. Soft branches and pulses are driven by actual node/edge state; contact pearls support the body; glyphs arrive from core utterances. There is no permanent status panel. Empty transparent space passes clicks through.

Desktop paths make deliberate excursions around the available monitor. Motion accelerates and settles, stays within bounds, and pauses for hover, dragging, menus, rest, reduced-motion preference or stale/degraded core state. When desktop awareness is enabled, some exploration paths can inspect a focused window's edge using its rectangle. Window content and screen images are not sampled. Actual movement drives directional swimming and smooth facing transitions.

## Real observations and history

The desktop supplies low-frequency observations of its own visible/exposed body and coarse local time. These indicate a running habitat, not a human typing or being productive. Explicit touches/drags and opted-in collector observations remain separate sources. No screenshots, titles, key identities or file contents are captured.

Desktop awareness additionally supplies occasional aggregate keyboard-activity cues under the fixed label `typing`. Only fresh actual activity can invite a finite core-selected imitation while awake; manual labels, silence and old events cannot. Window and optional accessible text-anchor coordinates stay local. The body eases out of tapping when current activity stops. [Details and limitations](DESKTOP_AWARENESS.md).

Events retain observed and received times. Historical observations can contribute recorded associations without claiming current presence, waking the creature or moving it now. A large observation gap does not teach a false adjacent transition. Recent reordered direct manipulation remains responsive, while its out-of-order timing cannot corrupt the current learned sequence.

## Quiet, durable operation

Accepted events commit immediately with the model and idempotency record in one SQLite transaction. Idle dynamics checkpoint every 15 seconds and on clean shutdown. A crash can lose up to that interval of uncommitted autonomous motion/state; acknowledged events remain durable. Checkpoint failures retry without killing the life loop, and health reports degraded state instead of pretending progress. There is no cloud inference or GPU requirement.

Renderer caches downsampled art, glow textures and graph geometry, and adapts its frame rate. Scale, monitor, position, roaming and reduced-motion preferences persist separately from the organism. Restored placements are clamped to current screen bounds. A controlled motion-study script renders isolated fixtures for visual regression review; its output is labelled as fixtures and is not autonomous-runtime evidence.
