import pytest

from desktop.directional_motion import DirectionalMotion


def settle(vx,vy,facing=1):
    motion=DirectionalMotion()
    for frame in range(121):motion.sample(frame/60,vx,vy,facing=facing,active=1.)
    return motion.bank


def test_heading_distinguishes_horizontal_rise_and_dive_with_bounded_bank():
    banks=[settle(180.,vy) for vy in (-180.,0.,180.)]
    assert banks[0]<banks[1]<banks[2]
    assert all(abs(bank)<=15.5 for bank in banks)
    assert settle(-180.,0.,-1)==pytest.approx(-settle(180.,0.))


def test_flip_is_immediate_and_follow_through_is_continuous():
    motion=DirectionalMotion()
    motion.sample(0.,0.,0.,facing=1)
    motion.sample(.1,0.,0.,facing=-1)
    assert motion.facing==-1
    assert motion.bank==0.
    values=[motion.sample(.1+i/60,0.,0.,facing=-1) for i in range(1,109)]
    assert min(values)<-1.
    assert max(abs(b-a) for a,b in zip([0.]+values,values))<.2
    assert abs(values[-1])<.05
    assert len({round(value,3) for value in values[:30]})>25


def test_quiet_pose_returns_to_zero_and_freeze_never_backlogs():
    motion=DirectionalMotion()
    for frame in range(60):motion.sample(frame/60,200.,-90.,active=1.)
    bank=motion.bank
    motion.sample(9.,-100.,0.,facing=-1,frozen=True)
    assert motion.bank==bank
    assert not motion.settling
    for frame in range(1,181):motion.sample(9.+frame/60,0.,0.)
    assert motion.bank==0.
    assert not motion.settling
    motion.sample(20.,200.,200.,reduced_motion=True)
    assert motion.bank==motion.velocity==0.


def test_fixed_heading_uses_frame_rate_independent_spring():
    a,b=DirectionalMotion(),DirectionalMotion()
    for motion in (a,b):motion.sample(0.,200.,-80.)
    for i in range(1,31):a.sample(i/30,200.,-80.)
    for i in range(1,61):b.sample(i/60,200.,-80.)
    assert a.bank==pytest.approx(b.bank,abs=1e-12)
