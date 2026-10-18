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
    for step in range(1,61):
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
    assert graph.values['one']['contact']==1.
    graph.set_contacts(set())
    graph.sample(state(),.1)
    assert 0<graph.values['one']['contact']<1
    graph.sample(state(.8),.2,reduced_motion=True)
    assert graph.points['one'][0]==.8
    assert not graph.settling
    graph.sample({'nodes':[]},.3)
    assert graph.points==graph.values=={}
    assert not graph.contacts


def test_first_real_snapshot_is_initialized_without_startup_animation():
    graph=GraphMotion();graph.sample({'nodes':[]},0.)
    graph.sample(connected_state(),.1)
    graph.set_contacts({'one'})
    assert graph.points['one']==(.2,.4)
    assert graph.values['one']['activation']==.1
    assert graph.values['one']['contact']==1.
    assert not graph.settling


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


def connected_state(activation=.1):
    result=state(activation=activation)
    result['nodes'].append({'id':'two','x':.8,'y':.6,'activation':activation})
    result['edges']=[{'source':'one','target':'two','weight':.6}]
    return result


def test_particle_speed_change_never_teleports_after_long_uptime():
    graph=GraphMotion();graph.sample(connected_state(),100000.)
    graph.sample(connected_state(1.),100000.1)
    previous=graph.edge('one','two')['phase']
    for i in range(1,61):
        graph.sample(connected_state(1.),100000.1+i/60)
        flow=graph.edge('one','two')
        distance=(flow['phase']-previous)%1.
        assert 0<distance<=.23/60+1e-10
        previous=flow['phase']


def test_graph_identity_survives_reordering_and_activity_wrap_fades():
    original=connected_state(.8)
    original['nodes'].append({'id':'three','x':.5,'y':.1,'activation':.6})
    original['edges'].append({'source':'one','target':'three','weight':.7})
    graph=GraphMotion();graph.sample(original,0.)
    shapes={key:(flow['phase'],flow['bow']) for key,flow in graph.edges.items()}
    reordered=deepcopy(original);reordered['nodes'].reverse();reordered['edges'].reverse()
    graph.sample(reordered,0.)
    assert shapes=={key:(flow['phase'],flow['bow']) for key,flow in graph.edges.items()}
    for i in range(1,600):
        graph.sample(reordered,i/60)
        for flow in graph.edges.values():
            if min(flow['phase'],1-flow['phase'])<.001:
                assert flow['pulse']<.001
            assert 0<=flow['pulse']<=1
    assert original['nodes'][0]['id']=='one'


def test_retarget_keeps_position_and_velocity_continuous():
    graph=GraphMotion();graph.sample(state(.2),0.)
    graph.sample(state(.8),0.)
    graph.sample(state(.8),.10)
    position,velocity=graph.points['one'],graph.velocities['one']
    graph.sample(state(.1),.10)
    assert graph.points['one']==position
    assert graph.velocities['one']==velocity
    graph.sample(state(.1),.101)
    assert abs(graph.points['one'][0]-position[0]-velocity[0]*.001)<.0001


def test_frozen_graph_holds_flow_and_reduced_motion_has_no_phase_clock():
    graph=GraphMotion();graph.sample(connected_state(),0.)
    graph.sample(connected_state(),.1)
    before=deepcopy(graph.edges)
    graph.sample(connected_state(.9),30.,frozen=True)
    assert graph.edges==before
    graph.sample(connected_state(.9),30.,reduced_motion=True)
    phase=graph.edge('one','two')['phase']
    graph.sample(connected_state(.1),60.,reduced_motion=True)
    assert graph.edge('one','two')['phase']==phase
    assert not graph.settling
