import math
import unittest
import numpy as np
from desktop.effects import DisplayEffects, screen_uniforms


class DisplayEffectsTests(unittest.TestCase):
    def test_screen_field_rejects_images_and_invalid_colors(self):
        for value in (None, b'image', {'colors': [[0,0,0]]*999},
                      {'colors': [[math.nan,0,0]]*4,'confidence':1}):
            self.assertEqual(screen_uniforms(value)['confidence'],0)
        result=screen_uniforms({'colors':[[.1,.2,.3]]*4,'confidence':2,'motion':[99,-99]})
        self.assertEqual(result['confidence'],1)
        self.assertEqual(result['motion'],(1,-1))

    def test_ink_has_smooth_bounded_lifetime_and_cooldown(self):
        effect=DisplayEffects()
        self.assertTrue(effect.release_ink())
        self.assertFalse(effect.release_ink())
        levels=[]
        for _ in range(720):
            effect.update(1/60)
            levels.append(effect.ink)
        self.assertEqual(levels[-1],0)
        self.assertGreater(max(levels),.99)
        self.assertLess(np.max(np.abs(np.diff(levels))),.025)
        self.assertTrue(effect.release_ink())

    def test_reduced_motion_is_static_and_suppresses_ink(self):
        effect=DisplayEffects()
        effect.release_ink()
        effect.update(.1,mode='ascii',reduced=True)
        before=effect.uniforms()
        for _ in range(100): effect.update(.1,mode='ascii',reduced=True)
        self.assertEqual(before,effect.uniforms())
        self.assertEqual(effect.ink,0)
        self.assertEqual(effect.ascii,1)
        self.assertFalse(effect.release_ink())

    def test_auto_display_remains_sparse_and_sleep_suppresses_it(self):
        effect=DisplayEffects()
        releases=0
        previous=99
        for _ in range(4000):
            effect.update(.1,activity=1.)
            if effect.ink_age<previous:releases+=1
            previous=effect.ink_age
        self.assertEqual(releases,2)
        sleeper=DisplayEffects()
        for _ in range(2000):sleeper.update(.1,sleeping=True,activity=1.)
        self.assertEqual(sleeper.ink,0)
        self.assertEqual(sleeper.ascii,0)
