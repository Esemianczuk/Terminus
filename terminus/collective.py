"""Content-free collective learning, separate from each creature's private RNN.

Only seven public event categories enter this model. Contexts, characters,
window metadata, timestamps, identities and private-model activations never do.
The public format contains bounded parameter deltas, not an observation log.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from .core import OnlineRNN

KINDS=('context','poke','drag','presence','git','activity','time')
SHAPES={'wx':(24,7),'wh':(24,24),'wy':(7,24),'bh':(24,),'by':(7,)}
MIN_SAMPLES=32


class KindModel(OnlineRNN):
    vocabulary=len(KINDS)


def parameters(model):
    return {name:getattr(model,name).tolist() for name in SHAPES}


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def arrays(value):
    if not isinstance(value,dict) or set(value)!=set(SHAPES):
        raise ValueError('Unexpected model fields')
    result={}
    for name,shape in SHAPES.items():
        a=np.asarray(value[name],dtype=object)
        if a.shape!=shape or any(type(v) not in (int,float) for v in a.flat):
            raise ValueError('Only numeric parameter arrays of the registered shape are accepted')
        a=a.astype(np.float64)
        if a.shape!=shape or not np.all(np.isfinite(a)) or np.max(np.abs(a))>8:
            raise ValueError('Invalid collective parameter array')
        result[name]=a
    return result


def initial_bank():
    return {'schema':1,'round':0,'kinds':list(KINDS),'model':parameters(KindModel(np.random.default_rng(46113))),
            'contributions':0,'ancestors':[],'applied':[]}


def validate_bank(bank):
    if not isinstance(bank,dict) or set(bank)!={'schema','round','kinds','model','contributions','ancestors','applied'}:
        raise ValueError('Unexpected bank fields')
    if bank['schema']!=1 or bank['kinds']!=list(KINDS):raise ValueError('Incompatible collective bank')
    for name in ('round','contributions'):
        if type(bank[name]) is not int or not 0<=bank[name]<=10**9:raise ValueError('Invalid bank counter')
    for name,limit in (('ancestors',16),('applied',4096)):
        if not isinstance(bank[name],list) or len(bank[name])>limit or any(not valid_hash(v) for v in bank[name]):
            raise ValueError('Invalid bank history')
    arrays(bank['model'])
    return bank


def valid_hash(value):
    return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def clipped(delta,limit=1.):
    norm=math.sqrt(sum(float(np.sum(a*a)) for a in delta.values()))
    return {k:v*min(1.,limit/max(norm,1e-12)) for k,v in delta.items()}


def contribution(model,anchor,base,samples):
    if samples<MIN_SAMPLES:raise ValueError('At least 32 category observations are needed')
    current=arrays(parameters(model));previous=arrays(anchor)
    delta=clipped({k:current[k]-previous[k] for k in SHAPES},.98)
    delta={k:(np.round(v*4096)/4096).tolist() for k,v in delta.items()}
    packet={'schema':1,'base':base,'sample_bin':min(512,samples//32*32),'delta':delta}
    packet['id']=digest(packet)
    return validate_contribution(packet)


def validate_contribution(packet):
    if not isinstance(packet,dict) or set(packet)!={'schema','base','sample_bin','delta','id'}:
        raise ValueError('Unexpected contribution fields; text and metadata are not accepted')
    if packet['schema']!=1 or not valid_hash(packet['base']) or not valid_hash(packet['id']):
        raise ValueError('Invalid contribution version or digest')
    n=packet['sample_bin']
    if type(n) is not int or not 32<=n<=512 or n%32:raise ValueError('Invalid sample bin')
    delta=arrays(packet['delta'])
    norm=math.sqrt(sum(float(np.sum(v*v)) for v in delta.values()))
    if norm>1.001:raise ValueError('Contribution exceeds the update budget')
    if digest({k:v for k,v in packet.items() if k!='id'})!=packet['id']:
        raise ValueError('Contribution digest mismatch')
    return packet


def merge(bank,packets):
    validate_bank(bank);base=digest(bank);accepted=[]
    known=set(bank['applied']);ancestors={base,*bank['ancestors']}
    for packet in packets:
        validate_contribution(packet)
        if packet['id'] in known:continue
        accepted.append(packet);known.add(packet['id'])
    if not accepted:return bank
    if len(accepted)>32:raise ValueError('At most 32 contributions per round')
    # Each release is clipped, each contributor has a bounded weight, and the
    # aggregate takes only a small step. This is not a poisoning-proof protocol.
    weights=np.array([p['sample_bin'] for p in accepted],dtype=float);weights/=weights.sum()
    # Offline learners can return after many rounds. Their updates still have
    # the fixed category schema, but receive one tenth of the normal influence.
    delta={k:sum(w*(1. if p['base'] in ancestors else .1)*np.asarray(p['delta'][k])
                 for w,p in zip(weights,accepted)) for k in SHAPES}
    delta=clipped(delta)
    model=arrays(bank['model'])
    result={'schema':1,'round':bank['round']+1,'kinds':list(KINDS),
            'model':{k:np.clip(model[k]+.2*delta[k],-4,4).tolist() for k in SHAPES},
            'contributions':bank['contributions']+len(accepted),
            'ancestors':[base,*bank['ancestors']][:16],
            'applied':[*bank['applied'],*(p['id'] for p in accepted)][-4096:]}
    return validate_bank(result)


def write_private(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_bytes(canonical(value)+b'\n');temporary.chmod(0o600);temporary.replace(path)


class LocalLearner:
    def __init__(self,bank,saved=None):
        validate_bank(bank)
        self.model=KindModel(np.random.default_rng(46113),saved=saved.get('model') if saved else None)
        self.base=bank
        self.last_sequence=saved.get('last_sequence',0) if saved else 0
        self.samples=saved.get('samples',0) if saved else 0
        self.total=saved.get('total',0) if saved else 0
        oldbase=arrays(saved['base']['model']) if saved else arrays(parameters(self.model))
        newbase=arrays(bank['model'])
        anchor=arrays(saved['anchor']) if saved else oldbase
        for k in SHAPES:
            shift=newbase[k]-oldbase[k]
            setattr(self.model,k,getattr(self.model,k)+shift)
        self.anchor={k:(anchor[k]+(newbase[k]-oldbase[k])).tolist() for k in SHAPES}

    def observe(self,kind):
        if kind not in KINDS:return
        self.model.observe(KINDS.index(kind));self.samples+=1;self.total+=1
        for name in SHAPES:
            setattr(self.model,name,np.clip(getattr(self.model,name),-4,4))

    def release(self):
        packet=contribution(self.model,self.anchor,digest(self.base),self.samples)
        self.anchor=parameters(self.model);self.samples=0
        return packet

    def dump(self):
        return {'schema':1,'model':self.model.dump(),'base':self.base,'anchor':self.anchor,
                'last_sequence':self.last_sequence,'samples':self.samples,'total':self.total}

    def prior(self):
        return {'schema':1,'round':self.base['round'],'contributions':self.base['contributions'],
                'probabilities':dict(zip(KINDS,map(float,self.model.probabilities())))}
