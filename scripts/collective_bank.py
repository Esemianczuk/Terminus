#!/usr/bin/env python3
"""Validate and merge bounded numeric contributions. Used by a serialized workflow."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from terminus.collective import merge,validate_contribution


def main(root=ROOT):
    root=Path(root);path=root/'community/bank.json'
    bank=json.loads(path.read_text());files=sorted((root/'community/contributions').glob('*.json'))[:32]
    packets=[]
    for p in files:
        if p.stat().st_size>64*1024:raise ValueError('Oversized contribution')
        packet=validate_contribution(json.loads(p.read_text()))
        if p.stem!=packet['id']:raise ValueError('Contribution filename does not match its digest')
        packets.append(packet)
    result=merge(bank,packets)
    path.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    for p in files:p.unlink()
    print(json.dumps({'round':result['round'],'contributions':result['contributions'],'processed':len(files)}))

if __name__=='__main__':main()
