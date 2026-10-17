"""The Mac launch policy must not activate a process with no typing window."""
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from desktop.macos import prepare_macos_environment,configure_macos_application,request_input_monitoring

class MacStartupTests(unittest.TestCase):
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
        with patch('desktop.macos.ctypes.CDLL',return_value=SimpleNamespace(CGRequestListenEventAccess=request)) as load:
            self.assertTrue(request_input_monitoring())
        self.assertEqual(calls,[True])
        load.assert_called_once_with('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')


if __name__=='__main__':unittest.main()
