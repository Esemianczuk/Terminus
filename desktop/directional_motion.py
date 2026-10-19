"""Small body-only steering dynamics; facing remains an immediate mirror."""
from __future__ import annotations

import math

from desktop.graph_motion import spring


class FacingFocus:
    """Hold a look direction through small target motion and attention jitter."""

    def __init__(self):
        self.candidate = None
        self.since = -math.inf

    def choose(self, now, target_x, body_x, scale, facing):
        if target_x is None:
            self.candidate = None
            return None
        delta = target_x - body_x
        threshold = 72. * scale
        direction = (1 if delta > threshold else -1 if delta < -threshold else facing)
        if direction == facing:
            self.candidate = None
            return facing
        if direction != self.candidate:
            self.candidate = direction
            self.since = now
        if now - self.since >= .36:
            self.candidate = None
            return direction
        return facing


class DirectionalMotion:
    """Add continuous pitch/roll and a soft turn follow-through to key poses.

    The caller shares ``bank`` with the body, gaze inverse and tendril roots.
    No graph coordinates, clips, source pixels or organism state are modified.
    """
    def __init__(self):
        self.bank=0.
        self.velocity=0.
        self.facing=None
        self.last_at=None
        self.turn_at=-math.inf
        self.turn_amount=0.
        self.settling=False

    def sample(self, now, vx, vy, *, facing=1, active=0., look=0., reduced_motion=False, frozen=False):
        dt=0. if self.last_at is None else max(0.,min(.25,now-self.last_at))
        self.last_at=now
        facing=-1 if facing<0 else 1
        if reduced_motion:
            self.bank=self.velocity=self.turn_amount=0.
            self.turn_at=-math.inf
            self.facing=facing
            self.settling=False
            return self.bank
        if frozen:
            self.velocity=0.
            self.turn_at=-math.inf
            self.settling=False
            return self.bank
        amount=max(0.,min(1.,active))
        if self.facing is not None and facing!=self.facing:
            self.turn_at=now
            self.turn_amount=facing*(2.1+1.6*amount)
        self.facing=facing
        # Horizontal glide, rising and diving are distinct, but a single shared
        # rotation keeps the artwork, eye orbits and physical roots registered.
        roll=math.tanh(vx/235.)*8.5
        pitch=math.degrees(math.atan2(vy,90.+abs(vx)))*.18*facing
        target=max(-12.,min(12.,roll+pitch+max(-4.,min(4.,look))))
        age=max(0.,now-self.turn_at)
        if age<1.5:
            t=age/.20
            target+=self.turn_amount*t*math.exp(1.-t)
        target=max(-15.5,min(15.5,target))
        self.bank,self.velocity=spring(self.bank,self.velocity,target,dt,12.)
        self.bank=max(-15.5,min(15.5,self.bank))
        self.settling=(abs(self.bank-target)>.04 or abs(self.velocity)>.12 or age<1.)
        if not self.settling and abs(self.bank)<.03 and abs(target)<.03:
            self.bank=self.velocity=0.
        return self.bank
