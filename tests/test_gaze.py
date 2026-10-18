"""Eye registration, blink safety, bounded pixel warping and gaze intent."""
from __future__ import annotations

import math
from pathlib import Path
import unittest

import numpy as np
from desktop.animation import ClipLibrary
from desktop.gaze import GazeAtlas, GazeController, warp_eye_pixels
from desktop.skin import rgba

ROOT=Path(__file__).resolve().parents[1]


class GazeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library=ClipLibrary.from_manifest(ROOT/'web/assets/clips/manifest.json')
        cls.atlas=GazeAtlas(ROOT/'web/assets/gaze/manifest.json',cls.library)

    def test_every_authored_frame_has_registered_pair_and_closed_eyes_are_static(self):
        self.assertEqual(self.atlas.errors,{})
        self.assertEqual(sum(entry['frames'] for entry in self.atlas.clips.values()),129)
        for name,clip in self.library.clips.items():
            self.assertEqual(self.atlas.clips[name]['frames'],len(clip.frames))
            for index in range(len(clip.frames)):
                field=self.atlas.field(name,index)
                with self.subTest(clip=name,index=index):
                    self.assertEqual(field.shape,(416,384,2))
                    self.assertTrue(np.isfinite(field).all())
                    self.assertGreaterEqual(float(field.min()),0.)
                    self.assertLessEqual(float(field.max()),1.)
        for name,index in [('sleep',0),('poke',2),('idle',17)]:
            self.assertFalse(np.any(self.atlas.field(name,index)))

    def test_original_highlights_move_only_inside_eye_fields(self):
        image=self.library.clips['idle'].frames[0]
        field=self.atlas.field('idle',0)
        self.assertIs(warp_eye_pixels(image,field,(0.,0.,0.,0.)),image)
        original=rgba(image)
        shifted=rgba(warp_eye_pixels(image,field,(3.6,.8,3.6,.8)))
        changed=np.any(original!=shifted,axis=2)
        self.assertGreater(int(changed.sum()),100)
        self.assertFalse(np.any(changed & (field.sum(axis=2)==0)))
        np.testing.assert_array_equal(original[:,:,3],shifted[:,:,3])
        closed=self.library.clips['idle'].frames[17]
        self.assertIs(warp_eye_pixels(closed,self.atlas.field('idle',17),(3.6,0,3.6,0)),closed)

    def test_eye_intent_tracks_pointer_without_hooks_and_converges_when_near(self):
        body=(700.,400.,190.,206.);screen=(0.,0.,1920.,1080.)
        far=GazeController(4);near=GazeController(4)
        for step in range(20):
            now=step*.1
            far.update(now,body=body,screen=screen,pointer=(.9,.5,.2))
            near.update(now,body=body,screen=screen,pointer=((body[0]+body[2]*.55)/screen[2],(body[1]+body[3]*.41)/screen[3],.2))
        self.assertEqual(far.mode,'pointer')
        self.assertGreater(far.shift[0],2.)
        self.assertAlmostEqual(far.shift[0],far.shift[2],places=3)
        self.assertGreater(near.shift[0]-near.shift[2],.8)
        mirrored=GazeController(4)
        for step in range(20):
            mirrored.update(step*.1,body=body,screen=screen,mirror=True,pointer=(.9,.5,.2))
        self.assertLess(mirrored.shift[0],-2.)
        self.assertTrue(all(math.isfinite(value) and abs(value)<5 for value in mirrored.shift))
        self.assertEqual(mirrored.update(3.,body=body,screen=screen,reduced_motion=True),(0.,0.,0.,0.))


if __name__=='__main__':unittest.main()
