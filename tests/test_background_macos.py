"""Mac colour sampling stays bounded, behind our panel and permission-gated."""
import os
from types import SimpleNamespace

import pytest

from desktop.background_macos import MacBackground, _rectangle


def backend(*, permitted=True, pixels=None):
    calls=[]
    sample=MacBackground.__new__(MacBackground)
    sample.reason=None
    def capture(rect,options,window,flags):
        calls.append(('capture',rect.origin.x,rect.origin.y,rect.size.width,rect.size.height,options,window,flags))
        return 101
    sample._api=SimpleNamespace(CGPreflightScreenCaptureAccess=lambda:permitted,
                               CGWindowListCreateImage=capture,
                               reduce=lambda image:pixels,
                               release=lambda image:calls.append(('release',image)))
    sample._own_window=lambda pid:73
    return sample,calls


@pytest.mark.parametrize('rect',[(0,0,0,12),(0,0,1025,12),(0,0,12,float('nan')),
                                  (float('inf'),0,2,2),(0,0,2),(0,0,2,2,5)])
def test_invalid_or_excessive_crops_are_rejected(rect):
    assert _rectangle(rect) is None


def test_denied_permission_does_not_capture_or_prompt():
    sample,calls=backend(permitted=False)
    assert sample.capture((0,0,440,340),os.getpid()) == {
        'available':False,'reason':'screen_recording_permission_required'}
    assert not calls


def test_unrelated_pid_cannot_be_used_as_the_exclusion_window():
    sample,calls=backend()
    assert not sample.capture((0,0,440,340),-1)['available']
    assert not calls


def test_only_four_colours_leave_capture_and_native_image_is_released():
    pixels=bytes((255,0,0,255, 0,255,0,255, 0,0,255,255, 127,127,127,255))
    sample,calls=backend(pixels=pixels)
    result=sample.capture((100,200,440,340),os.getppid())
    assert result=={'available':True,'colors':[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.],[127/255]*3]}
    # Below-window, excluding its image; nominal resolution bounds temporary RAM.
    assert calls==[('capture',100.,200.,440.,340.,4,73,17),('release',101)]


def test_native_buffer_is_released_after_failed_reduction():
    sample,calls=backend(pixels=None)
    assert not sample.capture((0,0,440,340),os.getpid())['available']
    assert calls[-1]==('release',101)


def test_transparent_gaps_do_not_become_false_black_background():
    sample,calls=backend(pixels=bytes(16))
    assert sample.capture((0,0,440,340),os.getpid())=={
        'available':False,'reason':'background_transparent'}
    assert calls[-1]==('release',101)
