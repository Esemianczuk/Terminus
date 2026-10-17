from copy import deepcopy
import pytest
from desktop.graph_motion import GraphMotion


def state(x=.2, activation=.1):
    return {'position':{'x':x,'y':.5},'attention':'one','nodes':[{'id':'one','x':x,'y':.4,'activation':activation}]}


def test_new_snapshot_starts_at_visible_position_and_settles_without_overshoot():
    graph=GraphMotion();graph.sample(state(),0)
    graph.sample(state(.8,.9),.25)
    assert graph.points['one'][0]==.2
    assert graph.anchor[0]==.2
    assert graph.settling
    previous=.2
    for step in range(1,31):
        graph.sample(state(.8,.9),.25+step/30)
        current=graph.points['one'][0]
        assert previous<=current<=.8
        previous=current
    assert current==pytest.approx(.8,abs=.003)
    assert graph.values['one']['activation']==pytest.approx(.9,abs=.004)


def test_filter_is_independent_of_frame_rate_and_holds_when_disconnected():
    a,b=GraphMotion(),GraphMotion()
    for graph in (a,b):graph.sample(state(),0);graph.sample(state(.7),0)
    a.sample(state(.7),.4)
    for i in range(1,13):b.sample(state(.7),i/30)
    assert a.points['one']==pytest.approx(b.points['one'])
    before=deepcopy(a.points);a.sample(state(.9),8,frozen=True)
    assert a.points==before
    assert not a.settling


def test_reduced_motion_prunes_old_nodes_and_contact_values_remain_bounded():
    graph=GraphMotion();graph.sample(state(),0);graph.set_contacts({'one','missing'})
    graph.sample(state(),.1)
    assert 0<graph.values['one']['contact']<1
    graph.sample(state(.8),.2,reduced_motion=True)
    assert graph.points['one'][0]==.8
    assert not graph.settling
    graph.sample({'nodes':[]},.3)
    assert graph.points==graph.values=={}
    assert not graph.contacts


def test_degraded_snapshot_can_prune_ids_without_moving_surviving_nodes():
    graph=GraphMotion();original=state();graph.sample(original,0)
    replacement=state(.9)
    replacement['nodes'].append({'id':'two','x':.6,'y':.7,'activation':.8})
    before=deepcopy(replacement)
    graph.sample(replacement,1,frozen=True)
    assert graph.points['one'][0]==.2
    assert set(graph.points)=={'one','two'}
    assert graph.values['two']['activation']==0
    replacement['nodes']=replacement['nodes'][1:]
    graph.sample(replacement,2,frozen=True)
    assert set(graph.points)=={'two'}
    assert before['nodes'][0]['x']==.9
    assert original==state()
