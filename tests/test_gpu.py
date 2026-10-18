"""Portable asset/eye/input contracts; hardware timing uses profile_gpu.py."""
import hashlib
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np
from PySide6 import QtGui

from desktop.gpu import GpuScene,PackedArtwork,arm_outline,desktop_rectangles,finite
from desktop.animation import ClipError,ClipLibrary,ClipPlayer

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'web/assets/gpu'


def pixels(image):
    rgba=image.convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    return np.frombuffer(rgba.bits(),np.uint8).reshape(rgba.height(),rgba.bytesPerLine()).copy()


class GpuAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest=json.loads((ASSETS/'manifest.json').read_text())
        cls.eyes=json.loads((ROOT/'web/assets/clips/skin-atlas.json').read_text())

    def test_all_authored_pixels_survive_offline_packing(self):
        self.assertEqual(len(self.manifest['clips']),12)
        count=0
        for name,entry in self.manifest['clips'].items():
            path=ROOT/f'web/assets/clips/{name}.gif'
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),entry['sha256'])
            atlas=QtGui.QImage(str(ASSETS/f'{name}-body.png'))
            reader=QtGui.QImageReader(str(path))
            for index,rect in enumerate(entry['body_rects']):
                with self.subTest(clip=name,frame=index):
                    x,y,w,h=rect
                    tile=atlas.copy(round(x*atlas.width()),round(y*atlas.height()),round(w*atlas.width()),round(h*atlas.height()))
                    np.testing.assert_array_equal(pixels(tile),pixels(reader.read()))
                    count+=1
        self.assertEqual(count,129)

    def test_closed_eye_clips_do_not_decode_or_upload_eye_materials(self):
        registered=json.loads((ROOT/'web/assets/gaze/manifest.json').read_text())
        atlas=SimpleNamespace(clips=registered['clips'],ensure_texture=lambda clip:(_ for _ in ()).throw(AssertionError('Closed eyes must not load materials')))
        scene=SimpleNamespace(available=True,manifest=self.manifest,current_clip='sleep',asset_root=ASSETS,
                              _set=lambda name,value:None)
        self.assertTrue(GpuScene.set_scene(scene,clip='sleep',index=0,phase=0,body_rect=(0,0,192,208),gaze_atlas=atlas))
        self.assertEqual(scene.eye_texture_bytes,0)

    def test_data_textures_are_opaque_and_bound_gpu_memory(self):
        for name,entry in self.manifest['clips'].items():
            with self.subTest(clip=name):
                self.assertLess(entry['texture_bytes'],18*1024*1024)
                for suffix in ('body','forward','backward'):
                    image=QtGui.QImage(str(ASSETS/f'{name}-{suffix}.png'))
                    self.assertFalse(image.isNull())
                    self.assertLessEqual(max(image.width(),image.height()),4096)
                    if suffix!='body':
                        array=pixels(image).reshape(image.height(),image.width(),4)
                        self.assertTrue(np.all(array[:,:,3]==255))

    def test_eye_centers_are_completely_protected_in_all_frames(self):
        for name,entry in self.manifest['clips'].items():
            forward=QtGui.QImage(str(ASSETS/f'{name}-forward.png'))
            for index,polygons in enumerate(self.eyes['clips'][name]['eyes']):
                rect=entry['flow_rects'][index]
                for polygon in polygons:
                    x=sum(p[0] for p in polygon)/len(polygon)
                    y=sum(p[1] for p in polygon)/len(polygon)
                    point=forward.pixelColor(round((rect[0]+x*rect[2])*forward.width()),round((rect[1]+y*rect[3])*forward.height()))
                    self.assertEqual(point.blue(),0,(name,index))

    def test_motion_fields_have_both_directions_and_bounded_displacement(self):
        entry=self.manifest['clips']['moving']
        self.assertEqual(self.manifest['max_flow_pixels'],64)
        means=[]
        for suffix in ('forward','backward'):
            atlas=QtGui.QImage(str(ASSETS/f'moving-{suffix}.png'))
            rect=entry['flow_rects'][0]
            tile=atlas.copy(round(rect[0]*atlas.width()),round(rect[1]*atlas.height()),96,104)
            image=tile.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
            array=np.frombuffer(image.bits(),np.uint8).reshape(104,96,4)
            flow=(array[:,:,:2].astype(np.float32)-128)/127*64
            self.assertLessEqual(float(np.abs(flow).max()),64.51)
            self.assertGreater(int(np.count_nonzero(np.abs(flow)>.2)),100)
            means.append(flow.mean(axis=(0,1)))
        self.assertLess(float(np.linalg.norm(means[0]+means[1])),2)

    def test_geometry_is_finite_and_bounded(self):
        self.assertEqual(finite(float('nan')),0)
        self.assertEqual(finite(float('inf')),0)
        self.assertEqual(finite('garbage'),0)
        arm=dict(x0=40,y0=10,cx0=100,cy0=60,cx1=0,cy1=100,x1=110,y1=120,activation=.6)
        outline=arm_outline(arm)
        self.assertTrue(outline.startswith('M'))
        self.assertTrue(outline.endswith(' Z'))
        self.assertEqual(outline.count(' L'),37)
        self.assertNotIn('nan',outline)

    def test_metadata_playback_decodes_no_gifs_and_shares_one_small_canvas(self):
        artwork=PackedArtwork(ASSETS)
        with patch.object(ClipLibrary,'_decode',side_effect=AssertionError('GIF decoding is forbidden')):
            library=artwork.playback_library()
        self.assertTrue(library.metadata_only)
        self.assertEqual(library.decoded_bytes,384*416*4)
        self.assertEqual(len({id(frame) for clip in library.clips.values() for frame in clip.frames}),1)
        self.assertIs(artwork.playback_library(),library)
        self.assertEqual(artwork.hit_cache_bytes,0)
        self.assertTrue(all(frame.pixelColor(180,180).alpha()==0 for clip in library.clips.values() for frame in clip.frames))

    def test_metadata_clocks_and_state_transitions_match_full_decoding(self):
        full=ClipLibrary.from_manifest(ROOT/'web/assets/clips/manifest.json')
        lightweight=PackedArtwork(ASSETS).playback_library()
        self.assertFalse(full.metadata_only)
        self.assertGreater(full.decoded_bytes,lightweight.decoded_bytes*100)
        for name,clip in full.clips.items():
            packed=lightweight.clips[name]
            self.assertEqual((clip.delays_ms,clip.ends_ms,clip.duration_ms,clip.loop,dict(clip.anchors)),
                             (packed.delays_ms,packed.ends_ms,packed.duration_ms,packed.loop,dict(packed.anchors)))
            for elapsed in (0,.019,.071,.129,.499,1.099,2.001,4.9,20):
                self.assertEqual(clip.frame_at(elapsed),packed.frame_at(elapsed))
        a,b=ClipPlayer(full),ClipPlayer(lightweight)
        for now,state,facing in ((0,'idle',1),(.03,'moving',1),(.15,'moving',-1),(.6,'moving',-1),
                                 (1.1,'idle',-1),(1.6,'sleep',1),(2.3,'sleep',1),(4,'typing',1),(4.8,'typing',-1)):
            first,second=a.advance(now,state,facing=facing),b.advance(now,state,facing=facing)
            self.assertEqual((first.clip,first.index,first.state,first.transition,first.mirror,first.next_frame_ms,dict(first.anchors)),
                             (second.clip,second.index,second.state,second.transition,second.mirror,second.next_frame_ms,dict(second.anchors)))

    def test_native_hit_frames_are_exact_and_only_one_atlas_is_cached(self):
        artwork=PackedArtwork(ASSETS)
        for name,entry in self.manifest['clips'].items():
            reader=QtGui.QImageReader(str(ROOT/f'web/assets/clips/{name}.gif'))
            for index in range(entry['count']):
                expected=reader.read()
                actual=artwork.hit_frame(name,index)
                with self.subTest(clip=name,frame=index):
                    np.testing.assert_array_equal(pixels(actual),pixels(expected))
                    self.assertEqual(artwork.cached_clip,name)
                    self.assertLess(artwork.hit_cache_bytes,18*1024*1024)
                    self.assertIs(artwork.hit_frame(name,index),actual)
        artwork.clear_hit_cache()
        self.assertEqual(artwork.hit_cache_bytes,0)
        self.assertIsNone(artwork.cached_clip)
        with self.assertRaises(ValueError):artwork.hit_frame('no-such-clip',0)
        with self.assertRaises(ValueError):artwork.hit_frame('idle',-1)
        with self.assertRaises(ValueError):artwork.hit_frame('idle',True)

    def test_metadata_rejects_invalid_timing_role_and_fingerprints(self):
        for field,value in (('count',500),('delays_ms',[False]*24),('loop',False),('sha256','0'*64)):
            altered=copy.deepcopy(self.manifest)
            altered['clips']['idle'][field]=value
            with self.subTest(field=field),self.assertRaises(ClipError):
                ClipLibrary.from_gpu_metadata(ROOT/'web/assets/clips/manifest.json',altered)

    def test_desktop_geometry_accepts_the_real_observer_schema_and_clips_safely(self):
        expected={"x":.1,"y":.2,"w":.3,"h":.4}
        self.assertEqual(desktop_rectangles([dict(x=.1,y=.2,width=.3,height=.4)]),[expected])
        self.assertEqual(desktop_rectangles([dict(x=.1,y=.2,w=.3,h=.4)]),[expected])
        self.assertEqual(desktop_rectangles([[.1,.2,.3,.4]]),[expected])
        clipped=desktop_rectangles([dict(x=.8,y=.9,width=.5,height=.5)])[0]
        self.assertAlmostEqual(clipped['x']+clipped['w'],1)
        self.assertAlmostEqual(clipped['y']+clipped['h'],1)
        self.assertEqual(desktop_rectangles([None,'garbage',{},dict(width=float('nan'),height=1)]),[])
        self.assertEqual(len(desktop_rectangles([dict(width=.5,height=.5)]*20)),8)

    def test_submission_keeps_every_primitive_at_the_core_limits(self):
        properties={}
        # Exercise the real submission method without constructing a native Qt
        # widget or asking a headless test runner to initialize a graphics API.
        scene=SimpleNamespace(available=True,manifest=self.manifest,current_clip='idle',asset_root=ASSETS,
                              _set=lambda name,value:properties.__setitem__(name,value))
        nodes=[dict(id=str(i),x=1,y=2,activation=.1,focus=False,contact=False) for i in range(80)]
        edges=[dict(index=i,x0=1,y0=2,cx=3,cy=4,x1=5,y1=6,activation=.1,weight=.2,focus=False) for i in range(340)]
        self.assertTrue(GpuScene.set_scene(scene,clip='idle',index=0,phase=0,body_rect=(10,20,192,208),
                                          nodes=nodes,edges=edges,desktop_rects=[dict(x=.1,y=.2,width=.3,height=.4)]))
        self.assertEqual(len(properties['nodes']),72)
        self.assertEqual(properties['nodes'][-1]['id'],'71')
        self.assertEqual(len(properties['edges']),320)
        self.assertEqual(properties['edges'][-1]['index'],319)
        self.assertEqual(properties['desktopRects'],[dict(x=.1,y=.2,w=.3,h=.4)])


if __name__=='__main__':unittest.main()
