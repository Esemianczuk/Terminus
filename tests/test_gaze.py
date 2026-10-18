"""Eye material registration, fixed lids, rigid highlights and safe fallback."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PySide6 import QtGui
from desktop.animation import ClipLibrary
from desktop.gaze import GazeAtlas,compose_eye_layers
from desktop.gaze_layers import EyeMaterial
from desktop.skin import SkinAtlas,eye_field,rgba

ROOT=Path(__file__).resolve().parents[1]


class GazeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library=ClipLibrary.from_manifest(ROOT/'web/assets/clips/manifest.json')
        cls.atlas=GazeAtlas(ROOT/'web/assets/gaze/manifest.json',cls.library)

    def test_every_frame_has_fixed_eye_apertures_inside_protected_face(self):
        self.assertEqual(self.atlas.errors,{})
        self.assertEqual(sum(entry['frames'] for entry in self.atlas.clips.values()),129)
        skin=SkinAtlas.load(ROOT/'web/assets/clips/skin-atlas.json',self.library)
        for name,clip in self.library.clips.items():
            for index in range(len(clip.frames)):
                frame=self.atlas.frame(name,index)
                protected,_=eye_field(skin.frames[name][index],384,416)
                for eye in frame:
                    x,y,w,h=eye.bounds
                    with self.subTest(clip=name,index=index):
                        self.assertEqual(eye.iris.shape,(64,96,4))
                        self.assertTrue(np.isfinite(eye.iris).all())
                        self.assertTrue(np.all(eye.iris[:,:,:3]<=eye.iris[:,:,3:4]))
                        ys,xs=np.nonzero(eye.aperture>.001)
                        if len(xs):self.assertTrue(protected[ys+y,xs+x].all())
        for name,index in [('sleep',0),('poke',2),('idle',17)]:
            self.assertTrue(all(not np.any(eye.aperture) for eye in self.atlas.frame(name,index)))

    def test_gaze_never_changes_lids_or_silhouette_and_neutral_is_exact(self):
        for name,index in [('idle',0),('idle',16),('idle',17),('moving',0),('typing',3),('stretch',5),('turn',3)]:
            image=self.library.clips[name].frames[index];original=rgba(image)
            materials=self.atlas.frame(name,index)
            self.assertIs(compose_eye_layers(image,materials,(0.,)*4),image)
            aperture=np.zeros((416,384),bool)
            for eye in materials:
                x,y,w,h=eye.bounds
                aperture[y:y+h,x:x+w]|=eye.aperture>0
            for gaze in [(3.6,2.5,3.6,2.5),(-3.6,-2.5,-3.6,-2.5)]:
                shifts=self.atlas.displacements(name,index,gaze)
                rendered=rgba(compose_eye_layers(image,materials,shifts))
                changed=np.any(original!=rendered,axis=2)
                with self.subTest(clip=name,frame=index,gaze=gaze):
                    self.assertFalse(np.any(changed&~aperture))
                    np.testing.assert_array_equal(original[:,:,3],rendered[:,:,3])
                    if name=='idle' and index==17:self.assertFalse(changed.any())

    def test_iris_and_catchlight_translate_without_stretching_or_foldover(self):
        h,w=64,96
        plate=np.full((h,w,3),120,np.float32);iris=np.zeros((h,w,4),np.float32)
        iris[23:42,30:49,:]=[15,85,91,255]
        iris[27:30,35:39,:]=[255,255,255,255]
        original=np.dstack((plate,np.full((h,w),255,np.float32)))
        original[:,:,:3]=plate*(1-iris[:,:,3:4]/255)+iris[:,:,:3]
        pixels=original.astype(np.uint8)
        image=QtGui.QImage(pixels.data,w,h,w*4,QtGui.QImage.Format_RGBA8888_Premultiplied).copy()
        material=EyeMaterial((0,0,w,h),plate,iris,np.ones((h,w),np.float32),(1,0,0,1))
        moved=rgba(compose_eye_layers(image,(material,),(5.,3.)))
        before=np.all(pixels[:,:,:3]==255,axis=2);after=np.all(moved[:,:,:3]==255,axis=2)
        self.assertEqual(before.sum(),after.sum())
        by,bx=np.nonzero(before);ay,ax=np.nonzero(after)
        np.testing.assert_array_equal(ax,bx+5);np.testing.assert_array_equal(ay,by+3)

    def test_travel_follows_turn_squash_and_is_positive_right_in_all_poses(self):
        idle=self.atlas.displacements('idle',0,(3.6,0,3.6,0))
        narrow=self.atlas.displacements('turn',3,(3.6,0,3.6,0))
        self.assertLess(narrow[0],idle[0]*.45)
        for name,index in [('idle',0),('moving',0),('typing',0),('stretch',5)]:
            shift=self.atlas.displacements(name,index,(3.6,0,3.6,0))
            self.assertGreater(shift[0],0);self.assertGreater(shift[2],0)
            self.assertLess(abs(shift[1]),.4);self.assertLess(abs(shift[3]),.4)

    def test_changed_material_fails_closed_without_repeated_decode(self):
        data=json.loads((ROOT/'web/assets/gaze/manifest.json').read_text())
        data['clips']['idle']['field_sha256']='0'*64
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'manifest.json';path.write_text(json.dumps(data))
            (path.parent/'idle.png').write_bytes((ROOT/'web/assets/gaze/idle.png').read_bytes())
            atlas=GazeAtlas(path,self.library)
            self.assertIsNone(atlas.frame('idle',0));self.assertIn('idle',atlas.errors)
            self.assertIsNone(atlas.frame('idle',0))


if __name__=='__main__':unittest.main()
