"""Private natural gaze intent for the native desktop creature."""
from __future__ import annotations
import math
import random

from desktop.gaze_layers import GazeAtlas, compose_eye_layers


class GazeController:
    """Private gaze intent with short saccades, smooth pursuit and quiet holds.

    All shifts are in the original 384 x 416 sprite coordinate system. World
    targets are transformed back through body bank and mirroring before they
    become binocular eye motion. Pointer samples are read-only presentation
    inputs and are discarded as soon as observation becomes unavailable.
    """
    def __init__(self, seed=0):
        self.random = random.Random(str(seed))
        self.shift = (0., 0., 0., 0.)
        self.last_at = None
        self.pointer_at = -math.inf
        self.pointer_xy = None
        self._pointer_previous = None
        self.next_glance = 0.
        self.rest = (0., 0.)
        self.rest_mode = "rest"
        self.mode = "rest"
        self.settling = False
        self._goal = self.shift
        self._saccade_start = self.shift
        self._saccade_at = -math.inf
        self._saccade_duration = 0.
        self._last_saccade = -math.inf

    def forget_pointer(self):
        """Immediately discard optional desktop observation, including its hold."""
        self.pointer_at = -math.inf
        self.pointer_xy = None
        self._pointer_previous = None

    @staticmethod
    def _valid_point(point):
        return (isinstance(point, (tuple, list)) and len(point) == 2
                and all(isinstance(v, (int, float)) and math.isfinite(v) for v in point))

    def update(self, now, *, body, screen, mirror=False, pointer=None,
               graph_target=None, inspection_target=None, typing=False,
               sleeping=False, reduced_motion=False, eye_centres=None,
               bank=0., pivot_offset=30.):
        dt = 0. if self.last_at is None else max(0., min(.15, now-self.last_at))
        self.last_at = now
        if reduced_motion:
            self.shift = self._goal = (0., 0., 0., 0.)
            self._saccade_duration = 0.
            self.mode = "reduced-motion"
            self.settling = False
            self.forget_pointer()
            return self.shift

        old_mode = self.mode
        target = None
        if pointer is not None and len(pointer) >= 2 and all(math.isfinite(v) for v in pointer):
            px = screen[0] + pointer[0]*screen[2]
            py = screen[1] + pointer[1]*screen[3]
            position = (px, py)
            previous = self._pointer_previous
            moved = previous is not None and math.hypot(px-previous[0], py-previous[1]) >= .75
            initial_motion = previous is None and len(pointer) > 2 and pointer[2] > .004
            if moved or initial_motion:
                self.pointer_at = now
            self._pointer_previous = position
            self.pointer_xy = position
            if now-self.pointer_at < 2.2:
                target = position
                self.mode = "pointer"
        else:
            self.forget_pointer()
        if target is None and typing and self._valid_point(inspection_target):
            target = inspection_target
            self.mode = "typing-window"
        if target is None:
            if now >= self.next_glance:
                choices = (["graph"]*5 if self._valid_point(graph_target) else [])
                choices += (["window"]*2 if self._valid_point(inspection_target) else [])
                self.rest_mode = self.random.choice(choices + ["wander"]*2 + ["rest"]*2)
                self.rest = ((self.random.uniform(-.65, .65), self.random.uniform(-.35, .35))
                             if self.rest_mode == "wander" else (0., 0.))
                self.next_glance = now + self.random.uniform(2.8, 7.2)
            if self.rest_mode == "graph" and self._valid_point(graph_target):
                target = graph_target
                self.mode = "graph"
            elif self.rest_mode == "window" and self._valid_point(inspection_target):
                target = inspection_target
                self.mode = "window"
        if sleeping:
            desired = (0., 0., 0., 0.)
            self.mode = "sleep"
        elif target is None:
            x, y = self.rest
            desired = (x*3.3, y*2.1, x*3.3, y*2.1)
            self.mode = "autonomous" if x or y else "rest"
        else:
            bx, by, bw, bh = body
            centres = eye_centres
            if (not isinstance(centres, (tuple, list)) or len(centres) != 2
                    or not all(self._valid_point(c) for c in centres)
                    or any(not 0 < v < 1 for c in centres for v in c)):
                centres = ((.47, .43), (.69, .37))
            # Use this frame's registered eye midpoint, then the exact native
            # body's mirror/rotation pivot. Scaling is already present in body.
            u = (centres[0][0]+centres[1][0])*.5
            v = (centres[0][1]+centres[1][1])*.5
            ex, ey = (u-.5)*bw, (v-.5)*bh-pivot_offset
            angle = math.radians(max(-16., min(16., bank)))
            cosine, sine = math.cos(angle), math.sin(angle)
            if mirror:
                ex = -ex
            origin = (bx+bw*.5+cosine*ex-sine*ey,
                      by+bh*.5+pivot_offset+sine*ex+cosine*ey)
            wx, wy = target[0]-origin[0], target[1]-origin[1]
            # Inverse bank, followed by inverse mirror, maps the gaze back to
            # the painted eyes, including while flying or dragging diagonally.
            dx, dy = cosine*wx+sine*wy, -sine*wx+cosine*wy
            if mirror:
                dx = -dx
            x = math.tanh(dx/max(1., bw*.7))
            y = math.tanh(dy/max(1., bh*.56))
            proximity = max(0., min(1., (.84-math.hypot(wx, wy)/max(1., bw))/.63))
            convergence = proximity*proximity*(3.-2.*proximity)*.72
            desired = (x*3.6+convergence, y*2.5, x*3.6-convergence, y*2.5)

        change = max(abs(want-old) for want, old in zip(desired, self._goal))
        if ((self.mode != old_mode or change > 1.65)
                and now-self._last_saccade >= .24 and not sleeping):
            self._saccade_start = self.shift
            self._saccade_at = self._last_saccade = now
            amplitude = max(abs(want-old) for want, old in zip(desired, self.shift))
            self._saccade_duration = .14 + min(.08, math.sqrt(amplitude)*.025)
        self._goal = desired
        elapsed = now-self._saccade_at
        if 0 <= elapsed < self._saccade_duration:
            t = elapsed/self._saccade_duration
            blend = t*t*t*(10.-15.*t+6.*t*t)
            self.shift = tuple(start+(goal-start)*blend
                               for start, goal in zip(self._saccade_start, self._goal))
        else:
            # Pursuit remains continuous when a moving target changes between
            # samples. The short finite saccade above never overshoots a lid.
            alpha = 1.-math.exp(-dt*(16. if self.mode == "pointer" else 10.))
            self.shift = tuple(current+(want-current)*alpha
                               for current, want in zip(self.shift, self._goal))
        error = max(abs(want-current) for want, current in zip(self._goal, self.shift))
        if error < .012:
            self.shift = self._goal
        self.settling = not sleeping and error >= .012
        return self.shift
