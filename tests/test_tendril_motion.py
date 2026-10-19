"""Elastic bend gates for hard-attached graph limbs."""

import math

from desktop.tendril_motion import TendrilMotion


def test_bend_follows_a_turn_without_teleporting_and_then_settles():
    limbs=TendrilMotion()
    first=limbs.update(0., {'node':(40.,12.,-30.,18.)})['node']
    moved=limbs.update(1/60, {'node':(-30.,-10.,25.,6.)})['node']
    assert first == (40.,12.,-30.,18.)
    assert all(abs(a-b)<2 for a,b in zip(first,moved))
    assert limbs.settling
    for frame in range(2,121):
        moved=limbs.update(frame/60, {'node':(-30.,-10.,25.,6.)})['node']
    assert all(abs(a-b)<.02 for a,b in zip(moved,(-30.,-10.,25.,6.)))
    assert not limbs.settling


def test_bend_state_is_bounded_to_current_contacts_and_reduced_motion_snaps():
    limbs=TendrilMotion()
    limbs.update(0., {'a':(40.,0.,-30.,0.),'b':(10.,5.,-8.,5.)})
    assert limbs.update(.1,{'a':(-40.,0.,30.,0.)},reduced_motion=True)['a']==(-40.,0.,30.,0.)
    assert list(limbs.handles)==['a']
    assert not limbs.settling
    assert limbs.update(.2,{},frozen=True)=={}
    assert not limbs.handles


def test_quiet_breath_does_not_request_interactive_frame_rate():
    limbs=TendrilMotion()
    for frame in range(120):
        now=frame/4
        limbs.update(now, {'node':(40.+math.sin(now)*.8,12.,-30.,18.)})
        assert not limbs.settling
