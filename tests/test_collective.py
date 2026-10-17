"""Fixed-category learning, bounded public updates and private-data separation."""
from copy import deepcopy
import json
import sqlite3
import numpy as np
import pytest
from terminus.collective import (LocalLearner,initial_bank,contribution,validate_contribution,
                                 validate_bank,merge,digest,arrays,canonical,KINDS,SHAPES)
from scripts import collective as agent
from terminus.core import Organism


def trained(bank=None):
    bank=bank or initial_bank();learner=LocalLearner(bank)
    for i in range(64):learner.observe(KINDS[i%len(KINDS)])
    return learner


def test_category_model_learns_and_public_payload_has_no_private_fields():
    learner=trained();packet=learner.release()
    assert learner.model.updates==63
    assert set(packet)=={'schema','base','sample_bin','delta','id'}
    assert packet['sample_bin']==64 and learner.samples==0
    assert any(np.any(np.asarray(a)!=0) for a in packet['delta'].values())
    assert validate_contribution(packet)==packet
    assert len(canonical(packet))<64*1024
    before=learner.total
    learner.observe('a password or private document title')
    assert learner.total==before


def test_release_requires_a_real_cohort_and_does_not_repeat_old_training():
    learner=LocalLearner(initial_bank())
    for _ in range(31):learner.observe('presence')
    with pytest.raises(ValueError):learner.release()
    learner.observe('time');first=learner.release()
    with pytest.raises(ValueError):learner.release()
    for _ in range(32):learner.observe('presence')
    assert learner.release()['id']!=first['id']


def test_bank_rounds_are_deduplicated_and_keep_updates_bounded():
    bank=initial_bank();packet=trained(bank).release();result=merge(bank,[packet,packet])
    assert result['round']==1 and result['contributions']==1
    assert merge(result,[packet])==result
    a,b=arrays(bank['model']),arrays(result['model'])
    assert sum(np.sum((a[k]-b[k])**2) for k in SHAPES)<=.2**2+1e-6
    assert result['ancestors']==[digest(bank)]


def test_old_offline_updates_are_attenuated_instead_of_blocking_other_learners():
    bank=initial_bank();packet=trained(bank).release()
    current=merge(bank,[packet]);fresh=trained(current).release()
    old=deepcopy(fresh);old['base']='a'*64
    old['id']=digest({k:v for k,v in old.items() if k!='id'})
    normal=merge(current,[fresh]);stale=merge(current,[old])
    before=arrays(current['model']);normal=arrays(normal['model']);stale=arrays(stale['model'])
    for k in SHAPES:np.testing.assert_allclose(stale[k]-before[k],.1*(normal[k]-before[k]),atol=1e-12)


@pytest.mark.parametrize('change',[{'text':'secret'},{'sample_bin':True},{'sample_bin':1},{'base':'bad'}, {'schema':2}])
def test_unexpected_fields_and_bad_metadata_are_rejected(change):
    packet=trained().release();packet.update(change)
    with pytest.raises(ValueError):validate_contribution(packet)


def test_nonfinite_oversized_and_text_parameters_are_rejected():
    packet=trained().release()
    for value in (float('nan'),float('inf'),500.,'password',True):
        p=deepcopy(packet);p['delta']['wx'][0][0]=value
        with pytest.raises(ValueError):validate_contribution(p)
    p=deepcopy(packet);p['delta']['wx']=[[0]]
    with pytest.raises(ValueError):validate_contribution(p)


def test_rebase_preserves_unreleased_work_and_exact_restart_continuity():
    bank=initial_bank();learner=trained(bank);packet=learner.release()
    for i in range(9):learner.observe('activity')
    restored=LocalLearner(bank,json.loads(json.dumps(learner.dump())))
    assert restored.dump()==learner.dump()
    advanced=LocalLearner(merge(bank,[packet]),learner.dump())
    assert advanced.samples==9 and advanced.total==73
    before,after=arrays(learner.anchor),arrays(advanced.anchor)
    for k in SHAPES:
        np.testing.assert_allclose(getattr(learner.model,k)-before[k],getattr(advanced.model,k)-after[k],atol=1e-12)


def test_agent_ignores_context_text_ids_timestamps_and_synthetic_activity(tmp_path,monkeypatch):
    db=sqlite3.connect(tmp_path/'organism.sqlite3')
    db.execute('CREATE TABLE events(seq INTEGER,body TEXT)')
    for i in range(40):
        event={'kind':'activity','source':'live','context':'NEVER_EXPORT_THIS_PASSWORD',
               'id':'private-id','timestamp':'private-time','window':'private-title'}
        db.execute('INSERT INTO events VALUES(?,?)',(i+1,json.dumps(event)))
    db.execute('INSERT INTO events VALUES(?,?)',(41,json.dumps({'kind':'poke','source':'synthetic'})))
    db.commit();db.close()
    monkeypatch.setattr(agent,'bank',lambda data,offline=False:initial_bank())
    learner=agent.train(tmp_path)
    assert learner.total==40 and learner.last_sequence==41
    for path in tmp_path.glob('collective-*.json'):
        assert 'NEVER_EXPORT' not in path.read_text()
        assert 'private-title' not in path.read_text()
    packet=json.loads(next((tmp_path/'collective-outbox').glob('*.json')).read_text())
    validate_contribution(packet)
    assert agent.train(tmp_path).total==40


def test_shared_attention_prior_does_not_change_private_model_weights_or_event_history():
    creature=Organism(seed=22,now=0.)
    before=creature.dump();creature.data['collective_prior']={'probabilities':dict.fromkeys(KINDS,1/7),'round':1}
    creature._attention_scores(creature.data['nodes'][0],1.)
    assert creature.model.dump()==before['model']
    assert creature.data['events_seen']==before['data']['events_seen']
