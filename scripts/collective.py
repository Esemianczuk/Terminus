#!/usr/bin/env python3
"""Opt-in exchange of category-only neural updates through the public GitHub bank."""
from __future__ import annotations
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from terminus.collective import LocalLearner,MIN_SAMPLES,canonical,digest,validate_bank,validate_contribution,write_private

URL='https://raw.githubusercontent.com/Esemianczuk/Terminus/main/community/bank.json'
REPOSITORY='Esemianczuk/Terminus'


def bank(data,offline=False):
    cache=data/'collective-bank.json'
    if not offline:
        try:
            with urllib.request.urlopen(URL,timeout=8) as response:
                raw=response.read(512*1024+1)
            if len(raw)>512*1024:raise ValueError('Oversized bank')
            value=validate_bank(json.loads(raw));write_private(cache,value)
            return value
        except (OSError,ValueError):
            pass
    path=cache if cache.is_file() else ROOT/'community/bank.json'
    return validate_bank(json.loads(path.read_text()))


def train(data,offline=False):
    public=bank(data,offline)
    path=data/'collective-local.json'
    saved=json.loads(path.read_text()) if path.is_file() else None
    learner=LocalLearner(public,saved)
    database=data/'organism.sqlite3'
    if database.is_file():
        connection=sqlite3.connect('file:'+str(database.resolve())+'?mode=ro',uri=True,timeout=3)
        try:
            rows=connection.execute('SELECT seq,body FROM events WHERE seq>? ORDER BY seq LIMIT 512',(learner.last_sequence,)).fetchall()
            for sequence,body in rows:
                event=json.loads(body)
                if event.get('source')!='synthetic':learner.observe(event.get('kind'))
                learner.last_sequence=sequence
        finally:
            connection.close()
    if learner.samples>=MIN_SAMPLES:
        packet=learner.release()
        write_private(data/'collective-outbox'/(packet['id']+'.json'),packet)
    write_private(path,learner.dump())
    write_private(data/'collective-prior.json',learner.prior())
    return learner


def upload(packet):
    validate_contribution(packet)
    target=f'repos/{REPOSITORY}/contents/community/contributions/{packet["id"]}.json'
    encoded=base64.b64encode(canonical(packet)+b'\n').decode()
    result=subprocess.run(['gh','api',target,'--method','PUT','-f','message=Contribute category-only collective learning',
                           '-f','content='+encoded],capture_output=True,text=True,timeout=25)
    if result.returncode:
        existing=subprocess.run(['gh','api',target],capture_output=True,text=True,timeout=15)
        if existing.returncode:return False
        entry=json.loads(existing.stdout)
        if base64.b64decode(entry.get('content','')) != canonical(packet)+b'\n':return False
    return True


def flush(data):
    applied=set(bank(data,True)['applied']);sent=0
    directory=data/'collective-outbox'
    for path in sorted(directory.glob('*.json'))[:4]:
        packet=validate_contribution(json.loads(path.read_text()))
        if packet['id'] in applied:
            path.unlink();continue
        if upload(packet):
            archive=data/'collective-sent';archive.mkdir(exist_ok=True,mode=0o700)
            path.replace(archive/path.name);sent+=1
        else:break
    return sent


def relay(data,config):
    """Optional existing SSH pairing relays only validated numeric packets."""
    peer=config.get('peer_ssh');root=config.get('peer_root')
    if not peer or not root:return 0
    import re
    if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,160}',peer) or not root.startswith('/'):
        raise ValueError('Invalid private SSH relay configuration')
    remote=' '.join(shlex.quote(x) for x in (root+'/.venv/bin/python',root+'/scripts/collective.py','relay-export'))
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5',peer,remote],capture_output=True,text=True,timeout=25)
    if result.returncode:return 0
    if len(result.stdout)>256*1024:raise ValueError('Oversized relay')
    packets=json.loads(result.stdout)
    if not isinstance(packets,list) or len(packets)>4:raise ValueError('Invalid relay batch')
    for packet in packets:
        validate_contribution(packet)
        write_private(data/'collective-outbox'/(packet['id']+'.json'),packet)
    return len(packets)


def enable(data,publish=False,peer=None,peer_root=None):
    config={'enabled':True,'publish':publish}
    if peer:config.update(peer_ssh=peer,peer_root=peer_root)
    write_private(data/'collective-config.json',config)
    if sys.platform=='darwin':
        from terminus.platform_macos import definition,paths,start
        import plistlib
        p=paths('collective');p.write_bytes(plistlib.dumps(definition('collective',ROOT)));p.chmod(0o600);start('collective')
    else:
        configdir=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'systemd/user'
        configdir.mkdir(parents=True,exist_ok=True)
        header=f'# Managed by Terminus: {ROOT}\n'
        service=header+f'''[Unit]
Description=Exchange Terminus category-only collective learning
[Service]
Type=oneshot
WorkingDirectory={ROOT}
ExecStart="{ROOT}/.venv/bin/python" "{ROOT}/scripts/collective.py" sync
TimeoutStartSec=180
UMask=0077
'''
        timer=header+'''[Unit]
Description=Occasional Terminus collective memory exchange
[Timer]
OnBootSec=120
OnUnitInactiveSec=600
AccuracySec=30
[Install]
WantedBy=timers.target
'''
        for name,text in (('terminus-collective.service',service),('terminus-collective.timer',timer)):
            p=configdir/name
            if p.exists() and not p.read_text().startswith(header):raise ValueError('Unrelated collective service already exists')
            p.write_text(text);p.chmod(0o644)
        subprocess.run(['systemctl','--user','daemon-reload'],check=True,timeout=15)
        subprocess.run(['systemctl','--user','enable','--now','terminus-collective.timer'],check=True,timeout=15)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('enable','sync','status','relay-export','disable'))
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--peer-ssh');parser.add_argument('--peer-root')
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args();data=ROOT/'.local';data.mkdir(exist_ok=True,mode=0o700)
    if args.action=='enable':
        enable(data,args.publish,args.peer_ssh,args.peer_root)
        print('Collective sharing enabled. Only fixed event categories enter the shared model.');return 0
    config_path=data/'collective-config.json'
    config=json.loads(config_path.read_text()) if config_path.is_file() else {}
    if args.action=='disable':
        write_private(config_path,{'enabled':False,'publish':False});print('Collective exchange disabled.');return 0
    if args.action=='status':
        p=data/'collective-local.json';s=json.loads(p.read_text()) if p.is_file() else {}
        print(json.dumps({'enabled':config.get('enabled',False),'publishing':config.get('publish',False),
                         'bank_round':s.get('base',{}).get('round',0),'local_category_observations':s.get('total',0),
                         'pending_observations':s.get('samples',0),'pending_contributions':len(list((data/'collective-outbox').glob('*.json')))},indent=2));return 0
    if not config.get('enabled'):
        print('[]' if args.action=='relay-export' else 'Collective sharing is disabled.');return 0
    with (data/'collective.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        learner=train(data,args.offline)
        applied=set(learner.base['applied'])
        for p in (data/'collective-outbox').glob('*.json'):
            if p.stem in applied:
                archive=data/'collective-sent';archive.mkdir(exist_ok=True,mode=0o700)
                p.replace(archive/p.name)
        if args.action=='relay-export':
            packets=[validate_contribution(json.loads(p.read_text())) for p in sorted((data/'collective-outbox').glob('*.json'))[:4]]
            print(json.dumps(packets,separators=(',',':')));return 0
        relayed=relay(data,config) if config.get('publish') else 0
        published=flush(data) if config.get('publish') else 0
        print(json.dumps({'round':learner.base['round'],'local_category_observations':learner.total,'published':published,'relayed':relayed}));return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print('Collective exchange deferred: '+type(error).__name__,file=sys.stderr);raise SystemExit(1)
