"""Bounded, view-local displays. No observations, timers, files or core writes."""
from __future__ import annotations
import math


def unit(value, default=0.):
    try:
        result = float(value)
        return max(0., min(1., result)) if math.isfinite(result) else default
    except (TypeError, ValueError, OverflowError):
        return default


def screen_uniforms(field=None):
    """Accept four already-averaged colors. Never accepts a screen image."""
    field = field if isinstance(field, dict) else {}
    colors = field.get('colors', [])
    valid = isinstance(colors, (tuple, list)) and len(colors) == 4
    valid = valid and all(isinstance(c, (tuple, list)) and len(c) == 3
                          and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                  and math.isfinite(v) and 0 <= v <= 1 for v in c) for c in colors)
    if not valid:
        colors = ((.14, .25, .28), (.44, .56, .36), (.22, .37, .39), (.77, .62, .41))
    motion = field.get('motion', (0., 0.))
    if not isinstance(motion, (tuple, list)) or len(motion) != 2:
        motion = (0., 0.)
    return {'colors': tuple(tuple(c) for c in colors),
            'confidence': unit(field.get('confidence')) if valid else 0.,
            'motion': tuple(unit((v+1)/2)*2-1 if isinstance(v, (int, float)) and math.isfinite(v) else 0. for v in motion),
            'change': unit(field.get('change')) if valid else 0.}


class DisplayEffects:
    """Slow envelopes, finite ink lifetime and sparse optional auto displays."""
    def __init__(self):
        self.clock = 0.
        self.ascii = 0.
        self.ink_age = 99.
        self.ink = 0.
        self.seed = .37
        self.reduced = False
        self.last_auto = -1
        self.last_release = -99.

    def release_ink(self, now=None):
        # Uses the view's animation clock: wall-clock jumps cannot resurrect ink.
        if self.reduced or self.clock-self.last_release < 3.:
            return False
        self.ink_age = 0.
        self.last_release = self.clock
        self.seed = (self.seed+.61803398875) % 1.
        return True

    def update(self, dt, *, mode='automatic', sleeping=False, activity=0., reduced=False):
        self.reduced = bool(reduced)
        dt = min(.2, max(0., float(dt)))
        if self.reduced:
            self.ascii = 1. if mode == 'ascii' else 0.
            self.ink = 0.
            self.ink_age = 99.
            return
        self.clock += dt
        cycle = int(self.clock/173.)
        within = self.clock % 173.
        # The skin may briefly reveal symbols while attentive. Quiet desktops
        # do not continually trigger displays, and manual styles remain stable.
        target = 1. if mode == 'ascii' else 0.
        if mode == 'automatic' and not sleeping:
            if 72. < within < 83.:
                target = .62*math.sin((within-72.)/11.*math.pi)**2
            if cycle != self.last_auto and within > 121. and activity > .12:
                self.release_ink()
                self.last_auto = cycle
        self.ascii += (target-self.ascii)*(1.-math.exp(-dt/1.4))
        self.ink_age += dt
        age = self.ink_age
        rise = min(1., max(0., age/1.15))
        fall = min(1., max(0., (10.-age)/5.))
        self.ink = (rise*rise*(3.-2.*rise))*(fall*fall*(3.-2.*fall)) if age < 10. else 0.

    def uniforms(self):
        return {'ascii': self.ascii, 'ink': self.ink, 'ink_phase': min(10., self.ink_age),
                'seed': self.seed, 'reduced_motion': self.reduced}
