"""Small presentation-only filters shared by the graph, arms and hit geometry."""
from __future__ import annotations

import math


def approach(current, target, blend, epsilon):
    value = current + (target-current)*blend
    return target if abs(target-value) < epsilon else value


class GraphMotion:
    """Ease real state targets without changing or creating organism events.

    Targets arriving on a core snapshot start from the last visible values.
    Every consumer uses this same presentation, so an arm cannot lag behind its
    displayed node. No timer or second simulation is owned by this filter.
    """
    def __init__(self):
        self.points = {}
        self.values = {}
        self.anchor = None
        self.targets = {}
        self.anchor_target = None
        self.last_at = None
        self.contacts = set()
        self.attention = None
        self.settling = False

    def set_contacts(self, contacts):
        self.contacts = set(contacts) & self.points.keys()
        if any(abs(value['contact'] - float(key in self.contacts)) > .02
               for key, value in self.values.items()):
            self.settling = True

    def sample(self, state, now, *, frozen=False, reduced_motion=False):
        dt = max(0., min(1., now-self.last_at)) if self.last_at is not None else 0.
        self.last_at = now
        if frozen and self.anchor is not None:
            # A degraded core may still prune its bounded graph. Keep IDs in
            # sync even while holding existing presentation coordinates.
            nodes=state.get('nodes',[])[:72]
            self.points={n['id']:self.points.get(n['id'],(n['x'],n['y'])) for n in nodes}
            self.values={n['id']:self.values.get(n['id'],{'activation':0.,'focus':0.,'contact':0.}) for n in nodes}
            self.targets={key:target for key,target in self.targets.items() if key in self.points}
            self.contacts.intersection_update(self.points)
            self.settling = False
            return
        # Advance the previous targets before accepting a new snapshot. This
        # prevents a low-frequency snapshot from spending its whole preceding
        # interval moving toward a position that has only just arrived.
        blend = 1. if reduced_motion else 1-math.exp(-dt/.18)
        for key, target in self.targets.items():
            self.points[key] = tuple(approach(c,t,blend,.0005)
                                     for c,t in zip(self.points[key],target[:2]))
            value=self.values[key]
            for name, desired in (('activation',target[2]), ('focus',float(key==self.attention)),
                                  ('contact',float(key in self.contacts))):
                value[name]=approach(value[name],desired,blend,.002)
        if self.anchor is not None and self.anchor_target is not None:
            self.anchor=tuple(approach(c,t,blend,.0005) for c,t in zip(self.anchor,self.anchor_target))
        nodes=state.get('nodes',[])[:72]
        targets={n['id']:(n['x'],n['y'],max(0.,min(1.,n.get('activation',0.)))) for n in nodes}
        position=state.get('position',{'x':.5,'y':.62})
        anchor=(position['x'],position['y'])
        initial=self.anchor is None
        self.attention=state.get('attention')
        self.points={key:self.points.get(key,target[:2]) for key,target in targets.items()}
        self.values={key:self.values.get(key,{'activation':target[2] if initial else 0.,
                                             'focus':float(key==self.attention) if initial else 0.,
                                             'contact':0.}) for key,target in targets.items()}
        self.targets=targets;self.anchor_target=anchor
        if initial or reduced_motion:
            self.anchor=anchor
            for key,target in targets.items():
                self.points[key]=target[:2]
                self.values[key].update(activation=target[2],focus=float(key==self.attention),contact=float(key in self.contacts))
        self.contacts.intersection_update(targets)
        self.settling=not reduced_motion and (
            any(abs(c-t)>.0005 for c,t in zip(self.anchor,anchor)) or
            any(any(abs(c-t)>.0005 for c,t in zip(self.points[key],target[:2])) or
                abs(self.values[key]['focus']-float(key==self.attention))>.02 or
                abs(self.values[key]['contact']-float(key in self.contacts))>.02 or
                abs(self.values[key]['activation']-target[2])>.08
                for key,target in targets.items()))
