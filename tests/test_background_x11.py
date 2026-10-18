"""Window selection and secure top-window failures never reveal a lower image."""
from types import SimpleNamespace

from desktop.background_x11 import X11Background


def setup(*, top_available=True, own_present=True):
    instance=X11Background.__new__(X11Background)
    instance.root=1;instance.display=2
    # Bottom source, another workspace, own panel, and an alert above us.
    stack=[10,11,12,13] if own_present else [10,11,13]
    records={(1,'_NET_CLIENT_LIST_STACKING'):stack,(1,'_NET_CURRENT_DESKTOP'):[0],
             (10,'_NET_WM_PID'):[999],(11,'_NET_WM_PID'):[998],
             (12,'_NET_WM_PID'):[123],(13,'_NET_WM_PID'):[997],
             (10,'WM_STATE'):[1],(11,'WM_STATE'):[1],(13,'WM_STATE'):[1],
             (10,'_NET_WM_DESKTOP'):[0],(11,'_NET_WM_DESKTOP'):[1],(13,'_NET_WM_DESKTOP'):[0]}
    instance.prop=lambda window,name:records.get((window,name),[])
    instance.geometry=lambda window:(0,0,500,500)
    instance.frame_window=lambda window:window
    calls=[]
    instance.composite=SimpleNamespace(XCompositeNameWindowPixmap=lambda display,window:calls.append(('name',window)) or (window+100 if top_available else 0))
    instance.x=SimpleNamespace(XFreePixmap=lambda display,pixmap:calls.append(('free',pixmap)))
    instance.color=lambda *args:[1.,.5,0.]
    return instance,records,calls


def test_sample_only_below_own_panel_on_current_workspace():
    instance,records,calls=setup()
    assert instance.capture((0,0,440,340),123)['colors']==[[1.,.5,0.]]*4
    assert calls==[('name',10),('free',110)]*4


def test_missing_own_panel_fails_without_sampling_other_windows():
    instance,records,calls=setup(own_present=False)
    assert instance.capture((0,0,440,340),123)=={'available':False,'reason':'own_panel_unavailable'}
    assert not calls


def test_unreadable_top_window_never_falls_through_to_lower_content():
    instance,records,calls=setup(top_available=False)
    records[(1,'_NET_CLIENT_LIST_STACKING')]=[9,10,12]
    records[(9,'_NET_WM_PID')]=[800];records[(9,'WM_STATE')]=[1]
    assert not instance.capture((0,0,440,340),123)['available']
    assert calls==[('name',10)]
