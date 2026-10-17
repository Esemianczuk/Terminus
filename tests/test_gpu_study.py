"""The offline eye audit follows physical framebuffer dimensions on Retina."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PySide6 import QtCore
from scripts.render_gpu_study import protected_eye_mask

ROOT=Path(__file__).resolve().parents[1]


class GpuStudyTests(unittest.TestCase):
    def test_registered_eye_mask_scales_to_retina_framebuffer(self):
        atlas=json.loads((ROOT/'web/assets/clips/skin-atlas.json').read_text())
        polygons=atlas['clips']['idle']['eyes'][0]
        normal=protected_eye_mask(QtCore.QSize(440,340),polygons)
        retina=protected_eye_mask(QtCore.QSize(880,680),polygons)
        fractional=protected_eye_mask(QtCore.QSize(550,425),polygons)
        self.assertEqual(normal.shape,(340,440))
        self.assertEqual(retina.shape,(680,880))
        self.assertEqual(fractional.shape,(425,550))
        self.assertGreater(int(normal.sum()),2500)
        self.assertAlmostEqual(float(retina.sum())/normal.sum(),4,delta=.12)
        self.assertAlmostEqual(float(fractional.sum())/normal.sum(),1.25**2,delta=.08)
        for polygon in polygons:
            x=28+384*sum(p[0] for p in polygon)/len(polygon)
            y=-50+416*sum(p[1] for p in polygon)/len(polygon)
            self.assertTrue(normal[round(y),round(x)])
            self.assertTrue(retina[round(y*2),round(x*2)])

    def test_async_capture_failure_exits_nonzero_without_hanging(self):
        code='''
import sys
from PySide6 import QtWidgets
import desktop.macos as mac
import scripts.render_gpu_study as study
mac.prepare_macos_environment=lambda:None
mac.configure_macos_application=lambda:None
class FailedCapture(QtWidgets.QWidget):
    available=True
    def set_scene(self,**kwargs):pass
    def grabFramebuffer(self):raise RuntimeError('capture-failure-sentinel')
study.GpuScene=FailedCapture
sys.argv=['gpu-study','--output',sys.argv[1]]
raise SystemExit(study.main())
'''
        with tempfile.TemporaryDirectory(prefix='terminus-gpu-audit-failure-') as output:
            result=subprocess.run([sys.executable,'-c',code,output],cwd=ROOT,
                                  env={**os.environ,'QT_QPA_PLATFORM':'offscreen'},
                                  capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('capture-failure-sentinel',result.stderr)
        self.assertNotIn('Traceback',result.stderr)


if __name__=='__main__':unittest.main()
