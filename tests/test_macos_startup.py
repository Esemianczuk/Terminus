"""The Mac launch policy must not activate a process with no typing window."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from desktop.macos import MacPresence,prepare_macos_environment,configure_macos_application
from desktop.macos_permission import request_input_monitoring

class MacStartupTests(unittest.TestCase):
    def test_gpu_is_selected_before_native_panel_creation(self):
        # Exercise the production main() bootstrap without a GUI event loop or
        # any native Mac calls. A premature winId() is the invisible-Metal bug.
        code = '''
import sys
from unittest.mock import patch
import desktop.macos as mac
import desktop.overlay as overlay
events=[]
def gpu(widget): events.append('gpu'); return True
def panel(widget):
    assert events == ['gpu'], events
    events.append('native-panel')
    return object()
with patch.object(sys,'platform','darwin'), \\
     patch.object(mac,'prepare_macos_environment',lambda:None), \\
     patch.object(mac,'configure_macos_application',lambda:None), \\
     patch.object(mac,'MacPresence',panel), \\
     patch.object(overlay.Overlay,'enable_gpu',gpu), \\
     patch.object(overlay.QtWidgets.QApplication,'exec',lambda self:0), \\
     patch.object(overlay.QtWidgets.QSystemTrayIcon,'isSystemTrayAvailable',lambda:False):
    assert overlay.main(['--data-dir',sys.argv[1],'--no-awareness','--no-roam']) == 0
assert events == ['gpu','native-panel'], events
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-c', code, directory],
                                    cwd=Path(__file__).resolve().parents[1],
                                    env={**os.environ, 'QT_QPA_PLATFORM':'offscreen'},
                                    text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_foreground_transform_is_disabled_in_this_process_only(self):
        with patch.dict(os.environ,{},clear=True):
            prepare_macos_environment()
            self.assertEqual(dict(os.environ),{'QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM':'1'})
            prepare_macos_environment()
            self.assertEqual(os.environ['QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM'],'1')

    def test_accessory_configuration_is_checked_without_activating(self):
        calls=[];state={'policy':0}
        def configure(policy):calls.append(policy);state['policy']=policy;return True
        application=SimpleNamespace(setActivationPolicy_=configure,activationPolicy=lambda:state['policy'])
        kit=SimpleNamespace(NSApplication=SimpleNamespace(sharedApplication=lambda:application),NSApplicationActivationPolicyAccessory=1)
        with patch.dict(sys.modules,{'AppKit':kit}):
            self.assertIs(configure_macos_application(),application)
        self.assertEqual(calls,[1])

    def test_a_failed_accessory_policy_cannot_silently_launch(self):
        application=SimpleNamespace(setActivationPolicy_=lambda policy:False,activationPolicy=lambda:0)
        kit=SimpleNamespace(NSApplication=SimpleNamespace(sharedApplication=lambda:application),NSApplicationActivationPolicyAccessory=1)
        with patch.dict(sys.modules,{'AppKit':kit}),self.assertRaisesRegex(RuntimeError,'background accessory'):
            configure_macos_application()

    def test_explicit_input_monitoring_request_uses_coregraphics(self):
        calls=[]
        def request():calls.append(True);return True
        with patch('desktop.macos_permission.ctypes.CDLL',return_value=SimpleNamespace(CGRequestListenEventAccess=request)) as load:
            self.assertTrue(request_input_monitoring())
        self.assertEqual(calls,[True])
        load.assert_called_once_with('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')

    def test_bring_forward_orders_only_the_nonactivating_body(self):
        calls=[]
        window=SimpleNamespace(setCollectionBehavior_=lambda value:calls.append(('collection',value)),
                               setLevel_=lambda value:calls.append(('level',value)),
                               orderFrontRegardless=lambda:calls.append(('front',)))
        presence=MacPresence.__new__(MacPresence)
        presence.window=window
        presence.collection_behavior=262417
        with patch.dict(sys.modules,{'AppKit':SimpleNamespace(NSDockWindowLevel=20)}):
            presence.bring_forward()
        self.assertEqual(calls,[('collection',262417),('level',21),('front',)])

    def test_presentation_capture_uses_only_this_native_window_and_releases_it(self):
        calls=[]
        api=SimpleNamespace(CGWindowListCreateImage=lambda rect,options,window,flags:
                            calls.append(('capture',options,window,flags)) or 73,
                            CGImageGetWidth=lambda image:2,CGImageGetHeight=lambda image:2,
                            reduce=lambda image,w,h:bytes((255,0,0,255,0,0,0,0)*2),
                            release=lambda image:calls.append(('release',image)))
        presence=MacPresence.__new__(MacPresence)
        presence.window=SimpleNamespace(windowNumber=lambda:321,isVisible=lambda:True)
        with patch('desktop.background_macos._CoreGraphics',return_value=api):
            image=presence.capture_image()
        self.assertFalse(image.isNull())
        self.assertEqual(image.pixelColor(0,0).red(),255)
        self.assertEqual(image.pixelColor(1,0).alpha(),0)
        self.assertEqual(calls,[('capture',8,321,1),('release',73)])
        self.assertTrue(presence.presentation_capture['presented'])
        self.assertEqual(presence.presentation_capture['visible_pixels'],2)

    def test_invisible_native_panel_is_not_confirmed_by_an_internal_frame(self):
        released=[]
        api=SimpleNamespace(CGWindowListCreateImage=lambda *args:73,
                            CGImageGetWidth=lambda image:2,CGImageGetHeight=lambda image:2,
                            reduce=lambda image,w,h:bytes(16),release=released.append)
        presence=MacPresence.__new__(MacPresence)
        presence.window=SimpleNamespace(windowNumber=lambda:321,isVisible=lambda:True)
        with patch('desktop.background_macos._CoreGraphics',return_value=api):
            image=presence.capture_image()
        self.assertTrue(image.isNull())
        self.assertFalse(presence.presentation_capture['presented'])
        self.assertEqual(presence.presentation_capture['reason'],'own_panel_has_no_visible_pixels')
        self.assertEqual(released,[73])


if __name__=='__main__':unittest.main()
