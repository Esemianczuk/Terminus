"""Optional offline-art checks for original pigment and catchlight fidelity."""
from pathlib import Path
import numpy as np
import pytest

pytest.importorskip('cv2')
Image=pytest.importorskip('PIL.Image')
from scripts.gaze_source_layers import EYES,source_layers

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('name',tuple(EYES))
def test_visible_iris_reconstructs_original_and_hidden_cap_adds_no_catchlight(name):
    original=np.asarray(Image.open(ROOT/f'web/assets/terminus-{name}.png').convert('RGBA'))[:,:,:3]
    for eye in source_layers(name):
        alpha=eye['iris'][:,:,3:4].astype(np.float32)/255
        visible=eye['aperture']==255
        reconstructed=eye['iris'][:,:,:3]*alpha+eye['plate']*(1-alpha)
        assert np.max(np.abs(reconstructed[visible]-original[visible]))<=1.5
        solid=visible&(eye['iris'][:,:,3]==255)
        np.testing.assert_array_equal(eye['iris'][:,:,:3][solid],original[solid])
        catchlight=solid&(original.min(axis=2)>215)
        assert np.count_nonzero(catchlight)>4
        hidden=(eye['aperture']==0)&(eye['iris'][:,:,3]>0)
        assert not np.any(hidden&(eye['iris'][:,:,:3].min(axis=2)>215))
