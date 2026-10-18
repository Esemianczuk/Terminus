"""Small presentation-only filters shared by the graph, arms and hit geometry."""
from __future__ import annotations

import math
import hashlib


def approach(current, target, blend, epsilon):
    value = current + (target-current)*blend
    return target if abs(target-value) < epsilon else value


def spring(current, velocity, target, dt, rate=12.):
    """Exact critically damped spring, independent of the caller's frame rate."""
    offset=current-target
    carry=velocity+rate*offset
    decay=math.exp(-rate*dt)
    return target+(offset+carry*dt)*decay, (velocity-rate*carry*dt)*decay


def seed(*parts):
    # Python's hash changes across processes. Geometry and flow keep their
    # identity even when the core reorders its bounded lists.
    return int.from_bytes(hashlib.blake2s(repr(parts).encode(),digest_size=4).digest(),'big') / 2**32


def smooth(low, high, value):
    t=max(0.,min(1.,(value-low)/(high-low)))
    return t*t*(3-2*t)


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
        self.contacts_known = False
        self.attention = None
        self.settling = False
        self.velocities = {}
        self.anchor_velocity = (0.,0.)
        self.edges = {}
        self.clock = 0.

    def edge(self, source, target):
        existing=self.edges.get((source,target))
        if existing is not None:return existing
        fraction=seed(source,target)
        return {'phase':fraction,'activation':0.,'weight':.3,'focus':0.,
                'visibility':.91,'bow':8*math.sin(fraction*math.tau),'pulse':0.}

    def set_contacts(self, contacts):
        self.contacts = set(contacts) & self.points.keys()
        if self.points and not self.contacts_known:
            # The first real scene has no preceding visible contact to ease
            # from. Startup should already be grasping its actual graph.
            self.contacts_known=True
            for key,value in self.values.items():value['contact']=float(key in self.contacts)
            return
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
            self.velocities={key:(0.,0.) for key in self.points}
            self.anchor_velocity=(0.,0.)
            self.edges={key:value for key,value in self.edges.items() if all(node in self.points for node in key)}
            self.settling = False
            return
        # Advance the previous targets before accepting a new snapshot. This
        # prevents a low-frequency snapshot from spending its whole preceding
        # interval moving toward a position that has only just arrived.
        blend = 1. if reduced_motion else 1-math.exp(-dt/.30)
        if not reduced_motion:self.clock+=dt
        for key, target in self.targets.items():
            axes=[spring(c,v,t,dt) for c,v,t in zip(self.points[key],self.velocities.get(key,(0.,0.)),target[:2])]
            self.points[key]=tuple(max(0.,min(1.,p)) for p,v in axes)
            self.velocities[key]=tuple(v for p,v in axes)
            value=self.values[key]
            for name, desired in (('activation',target[2]), ('focus',float(key==self.attention)),
                                  ('contact',float(key in self.contacts))):
                value[name]=approach(value[name],desired,blend,.002)
            if not reduced_motion:
                value['phase']=(value.get('phase',seed(key)*math.tau)+dt*(.65+.35*value['activation']))%math.tau
            value['breath']=.85+.15*math.sin(value.get('phase',seed(key)*math.tau))
        if self.anchor is not None and self.anchor_target is not None:
            axes=[spring(c,v,t,dt) for c,v,t in zip(self.anchor,self.anchor_velocity,self.anchor_target)]
            self.anchor=tuple(max(0.,min(1.,p)) for p,v in axes)
            self.anchor_velocity=tuple(v for p,v in axes)
        nodes=state.get('nodes',[])[:72]
        targets={n['id']:(n['x'],n['y'],max(0.,min(1.,n.get('activation',0.)))) for n in nodes}
        position=state.get('position',{'x':.5,'y':.62})
        anchor=(position['x'],position['y'])
        initial=self.anchor is None or not self.targets
        self.attention=state.get('attention')
        self.points={key:self.points.get(key,target[:2]) for key,target in targets.items()}
        self.values={key:self.values.get(key,{'activation':target[2] if initial else 0.,
                                             'focus':float(key==self.attention) if initial else 0.,
                                             'contact':0.,'phase':seed(key)*math.tau,
                                             'breath':.85+.15*math.sin(seed(key)*math.tau)}) for key,target in targets.items()}
        self.velocities={key:self.velocities.get(key,(0.,0.)) for key in targets}
        self.targets=targets;self.anchor_target=anchor
        if initial or reduced_motion:
            self.anchor=anchor
            self.anchor_velocity=(0.,0.)
            for key,target in targets.items():
                self.points[key]=target[:2]
                self.velocities[key]=(0.,0.)
                self.values[key].update(activation=target[2],focus=float(key==self.attention),contact=float(key in self.contacts))
        edges={}
        for raw in state.get('edges',[])[:320]:
            a,b=raw['source'],raw['target']
            if a not in self.values or b not in self.values:continue
            identity=(a,b)
            previous=self.edges.get(identity)
            fraction=previous['seed'] if previous else seed(a,b)
            weight=max(0.,min(1.,raw.get('weight',.3)))
            active=max(self.values[a]['activation'],self.values[b]['activation'])
            phase=previous['phase'] if previous else fraction
            # Integrate velocity. Multiplying the entire uptime by the current
            # activation teleports a pulse whenever activity changes.
            if previous and not reduced_motion:
                phase=(phase+dt*(.08+.15*(active+previous['activation'])*.5))%1.
            edges[identity]={'seed':fraction,'phase':phase,'activation':active,
                             'weight':weight if initial or reduced_motion or previous is None else approach(previous['weight'],weight,blend,.001),
                             'focus':max(self.values[a]['focus'],self.values[b]['focus']),
                             'visibility':.82+.18*(.5+.5*math.sin(self.clock*.31+fraction*math.tau)),
                             'bow':8*math.sin(fraction*math.tau),
                             'pulse':smooth(.02,.18,active)*smooth(0.,.09,phase)*smooth(0.,.09,1.-phase)}
        self.edges=edges
        self.contacts.intersection_update(targets)
        self.settling=not reduced_motion and (
            any(abs(c-t)>.0005 for c,t in zip(self.anchor,anchor)) or
            any(abs(v)>.003 for v in self.anchor_velocity) or
            any(any(abs(c-t)>.0005 for c,t in zip(self.points[key],target[:2])) or
                any(abs(v)>.003 for v in self.velocities[key]) or
                abs(self.values[key]['focus']-float(key==self.attention))>.02 or
                abs(self.values[key]['contact']-float(key in self.contacts))>.02 or
                abs(self.values[key]['activation']-target[2])>.04
                for key,target in targets.items()))
