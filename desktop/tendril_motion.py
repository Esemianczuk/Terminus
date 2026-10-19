"""Endpoint-constrained elastic bends for the creature's graph contacts."""
from __future__ import annotations

from desktop.graph_motion import spring


class TendrilMotion:
    """Spring only cubic handles; body roots and graph tips stay exact."""

    def __init__(self):
        self.handles = {}
        self.settling = False

    def update(self, now, guides, *, reduced_motion=False, frozen=False):
        result = {}
        settling = False
        for key, desired in guides.items():
            previous = self.handles.get(key)
            if previous is None or reduced_motion:
                values = tuple(desired)
                velocity = (0.,) * 4
            elif frozen:
                values, velocity = previous[0], (0.,) * 4
            else:
                dt = max(0., min(.15, now - previous[2]))
                axes = [spring(value, speed, goal, dt, 11.)
                        for value, speed, goal in zip(previous[0], previous[1], desired)]
                values = tuple(max(-120., min(120., value)) for value, _ in axes)
                velocity = tuple(speed for _, speed in axes)
                # Tiny continuous breathing must not force a sleeping pet
                # into the interactive frame rate. Large turns still do.
                settling |= any(abs(value - goal) > 1.25 or abs(speed) > 8.
                                for value, speed, goal in zip(values, velocity, desired))
            self.handles[key] = (values, velocity, now)
            result[key] = values
        self.handles = {key: self.handles[key] for key in guides}
        self.settling = settling and not frozen and not reduced_motion
        return result
