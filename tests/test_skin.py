"""Living skin contracts against every real clip, including eye-safe transitions."""
import json
import os
from pathlib import Path
import tempfile
from dataclasses import replace
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PySide6 import QtCore,QtGui,QtWidgets
from desktop.animation import ClipLibrary,ClipPlayer,AnimationFrame
from desktop.skin import SkinAtlas,SkinEngine,LAYERS,rgba,eye_field

ROOT = Path(__file__).resolve().parents[1]


class SkinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.library = ClipLibrary.from_manifest(ROOT/'web/assets/clips/manifest.json')
        cls.atlas = SkinAtlas.load(ROOT/'web/assets/clips/skin-atlas.json',cls.library)

    def sample(self,name='idle',index=0):
        c = self.library.clips[name]
        return AnimationFrame(c.frames[index],name,index,name,not c.loop,False,100,c.anchors,False)

    def test_all_real_frames_preserve_eyes_alpha_and_original_cache(self):
        self.assertEqual(self.atlas.errors,{})
        self.assertEqual(len(self.atlas.frames),12)
        engine = SkinEngine(self.atlas,'crimson')
        engine.update(0.)
        count = 0
        for name,clip in self.library.clips.items():
            for index,original in enumerate(clip.frames):
                with self.subTest(clip=name,frame=index):
                    before = rgba(original)
                    output = rgba(engine.shade(self.sample(name,index)))
                    baseline = before
                    guard,_ = eye_field(self.atlas.frames[name][index],384,416)
                    self.assertGreater(int(guard.sum()),30)
                    np.testing.assert_array_equal(output[guard],baseline[guard])
                    np.testing.assert_array_equal(output[:,:,3],baseline[:,:,3])
                    np.testing.assert_array_equal(output[baseline[:,:,3]==0],baseline[baseline[:,:,3]==0])
                    np.testing.assert_array_equal(rgba(original),before)
                    self.assertGreater(np.abs(output[:,:,:3].astype(float)-baseline[:,:,:3]).sum(),1000)
                    self.assertLessEqual(engine.diagnostics()['cache_bytes'],engine.max_cache_bytes)
                    count += 1
        self.assertEqual(count,129)

    def test_patterns_are_distinct_and_move_without_advancing_the_gif(self):
        sample = self.sample()
        results = []
        for mode in LAYERS:
            engine = SkinEngine(self.atlas,mode)
            engine.update(0.)
            first = rgba(engine.shade(sample,width=192,height=208))
            for i in range(1,31):
                engine.update(i/15)
            later = rgba(engine.shade(sample,width=192,height=208))
            self.assertGreater(np.abs(first.astype(float)-later).sum(),1000)
            results.append(later)
        for a,b in zip(results,results[1:]):
            self.assertGreater(np.abs(a.astype(float)-b).sum(),10000)

    def test_stale_state_and_resume_do_not_jump_or_invent_animation_time(self):
        engine = SkinEngine(self.atlas,'cascade')
        sample = self.sample()
        engine.update(0.); engine.update(.1)
        before = rgba(engine.shade(sample)); phase = engine.phase; weights = engine.weights.copy()
        for now in (1.,30.,300.):
            engine.update(now,state={'behavior':'sleep'},fresh=False)
            np.testing.assert_array_equal(rgba(engine.shade(sample)),before)
            np.testing.assert_array_equal(engine.weights,weights)
            self.assertEqual(engine.phase,phase)
        engine.update(301.,fresh=True)
        self.assertEqual(engine.phase,phase)
        engine.update(301.1,fresh=True)
        self.assertGreater(engine.phase,phase)

    def test_reduced_motion_is_static_but_still_allows_style_selection(self):
        engine = SkinEngine(self.atlas,'camouflage')
        sample = self.sample()
        engine.update(0.,reduced_motion=True)
        before = rgba(engine.shade(sample))
        for now in (1.,10.,100.):
            engine.update(now,reduced_motion=True)
            np.testing.assert_array_equal(rgba(engine.shade(sample)),before)
        engine.mode = 'crimson'; engine.update(101.,reduced_motion=True)
        self.assertFalse(np.array_equal(rgba(engine.shade(sample)),before))

    def test_missing_changed_or_malformed_eye_atlas_fails_closed(self):
        engine = SkinEngine(SkinAtlas(),'crimson'); engine.update(0.)
        self.assertIs(engine.shade(self.sample()),self.sample().image)
        data = json.loads((ROOT/'web/assets/clips/skin-atlas.json').read_text())
        data['clips']['idle']['sha256'] = 'wrong'
        data['clips']['moving']['eyes'][0][0][0] = [float('nan'),.2]
        data['clips']['sleep']['eyes'] = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'atlas.json'; path.write_text(json.dumps(data))
            atlas = SkinAtlas.load(path,self.library)
            self.assertEqual(set(atlas.errors),{'idle','moving','sleep'})
            self.assertNotIn('idle',atlas.frames)
            path.write_text('[]')
            self.assertIn('atlas',SkinAtlas.load(path,self.library).errors)

    def test_blends_are_continuous_and_react_to_real_motion_touch_and_rest(self):
        engine = SkinEngine(self.atlas)
        engine.update(0.,state={'behavior':'idle'})
        initial = engine.weights.copy()
        engine.update(.1,motion=1.,touch_age=0.)
        self.assertGreater(engine.weights[3],0.)
        self.assertLess(np.max(np.abs(engine.weights-initial)),.1)
        for i in range(1,50):
            engine.update(.1+i*.1,motion=1.)
        self.assertGreater(engine.weights[1],.65)
        for i in range(50,120):
            engine.update(.1+i*.1,state={'behavior':'sleep'})
        self.assertLess(engine.intensity,.42)
        self.assertGreater(engine.weights[0],.8)
        engine.update(12.2,state={'behavior':'inspect'})
        for i in range(1,60):
            engine.update(12.2+i*.1,state={'behavior':'inspect'})
        self.assertGreater(engine.weights[2],.6)
        for latent in (None,[],{'agitation':None},{'agitation':float('nan')}):
            engine.update(20.,state={'latent':latent})
            self.assertTrue(np.all(np.isfinite(engine.weights)))

    def test_mirroring_reuses_same_shaded_frame_and_never_resets_gif_phase(self):
        player = ClipPlayer(self.library)
        player.advance(0.,'moving')
        sample = player.advance(.2,'moving')
        engine = SkinEngine(self.atlas,'cascade'); engine.update(.2)
        first = engine.shade(sample)
        flipped = player.advance(.2,'moving',facing=-1)
        self.assertEqual((sample.clip,sample.index),(flipped.clip,flipped.index))
        self.assertTrue(flipped.mirror)
        self.assertIs(engine.shade(flipped),first)
        self.assertEqual(engine.phase,0.)

    def test_cache_and_resolution_are_bounded_and_off_restores_original(self):
        engine = SkinEngine(self.atlas,'crimson',max_cache_bytes=3*1024*1024)
        engine.update(0.)
        for i in range(24):
            result = engine.shade(self.sample('idle',i),width=192,height=208)
            self.assertEqual((result.width(),result.height()),(192,208))
            self.assertLessEqual(engine.diagnostics()['cache_bytes'],engine.max_cache_bytes)
        result = engine.shade(self.sample(),width=9999,height=9999)
        self.assertEqual((result.width(),result.height()),(384,416))
        self.assertLessEqual(engine.diagnostics()['cache_bytes'],engine.max_cache_bytes)
        engine.mode = 'off'
        self.assertIs(engine.shade(self.sample()),self.sample().image)
        engine.clear(); self.assertEqual(engine.diagnostics()['cache_bytes'],0)

    def test_shading_retains_relief_instead_of_flat_paint(self):
        engine = SkinEngine(self.atlas,'crimson'); engine.update(0.)
        original = rgba(self.sample().image)
        output = rgba(engine.shade(self.sample()))
        _,influence = eye_field(self.atlas.frames['idle'][0],384,416)
        mask = (original[:,:,3]>0)&(influence>.9)
        a = original[:,:,:3][mask].astype(float).mean(axis=1)
        b = output[:,:,:3][mask].astype(float).mean(axis=1)
        self.assertGreater(np.corrcoef(a,b)[0,1],.85)
        self.assertGreater(np.std(b),25)
