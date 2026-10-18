from desktop.window_field import WindowField


def test_window_currents_follow_moving_geometry_without_jump():
    field=WindowField()
    start=dict(x=.1,y=.2,width=.4,height=.5)
    field.sample([start],0.)
    target={**start,'x':.6}
    first,motion=field.sample([target],.033)
    assert .1<first[0]['x']<.14
    assert 0<motion[0]<=1
    for i in range(1,80): result,motion=field.sample([target],i*.033)
    assert abs(result[0]['x']-.6)<.002
    assert abs(motion[0])<.01


def test_window_reordering_preserves_identity_and_disable_clears():
    field=WindowField()
    a=dict(x=.1,y=.1,width=.2,height=.3)
    b=dict(x=.7,y=.1,width=.2,height=.3)
    field.sample([a,b],0)
    rows,motion=field.sample([b,a],.1)
    assert rows==[b,a]
    assert motion==[0.,0.]
    field.clear()
    assert field.sample([],1)==([],[0.,0.])
