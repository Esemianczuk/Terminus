"""View-local continuous currents from coarse window geometry."""
from __future__ import annotations
import math


class WindowField:
    def __init__(self):
        self.rows=[]
        self.last=None

    def sample(self, targets, now):
        dt=0. if self.last is None else min(.25,max(0.,now-self.last))
        self.last=now
        targets=[dict(r) for r in targets[:4]]
        remaining=list(self.rows)
        rows=[];motion=[0.,0.]
        blend=1-math.exp(-dt/.45)
        for target in targets:
            cx=target['x']+target['width']/2;cy=target['y']+target['height']/2
            if remaining:
                row=min(remaining,key=lambda r:(r['x']+r['width']/2-cx)**2+(r['y']+r['height']/2-cy)**2)
                remaining.remove(row)
            else:
                row=dict(target)
            before=(row['x']+row['width']/2,row['y']+row['height']/2)
            for key in ('x','y','width','height'): row[key]+=(target[key]-row[key])*blend
            after=(row['x']+row['width']/2,row['y']+row['height']/2)
            if dt>0:
                for i in range(2):motion[i]+=(after[i]-before[i])/dt
            rows.append(row)
        # Vanishing windows lose their influence gradually in place.
        for row in remaining[:4-len(rows)]:
            row['width']*=1-blend;row['height']*=1-blend
            if min(row['width'],row['height'])>.002:rows.append(row)
        self.rows=rows
        return [dict(r) for r in rows],[max(-1.,min(1.,v/max(1,len(targets)))) for v in motion]

    def clear(self):
        self.rows=[];self.last=None
