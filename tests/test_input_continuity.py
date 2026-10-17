"""Synthetic keyboard checks on a new private X server, never the live desktop."""
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(sys.platform != "linux" or not shutil.which("Xvfb") or not shutil.which("xdotool"),
                    reason="An isolated Xvfb server and xdotool are required")
@pytest.mark.parametrize("renderer", ["raster", "gpu"])
def test_touch_drag_and_menu_do_not_interrupt_another_windows_typing(tmp_path, renderer):
    # -displayfd asks Xvfb to reserve a fresh display atomically. No inherited
    # DISPLAY or arbitrary display number is ever used for synthetic input.
    server = subprocess.Popen(["Xvfb", "-displayfd", "1", "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(server.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=5), "Isolated X server did not start in time"
        display_number = server.stdout.readline().strip()
        assert display_number.isdecimal(), "Xvfb did not return a reserved display number"
        environment = {**os.environ, "DISPLAY": ":" + display_number,
                       "QT_QPA_PLATFORM": "xcb", "TERMINUS_CPU_REFERENCE": "0" if renderer == "gpu" else "1",
                       "LIBGL_ALWAYS_SOFTWARE": "1", "QSG_RHI_BACKEND": "opengl"}
        probe = subprocess.run([sys.executable, str(ROOT / "tests/helpers/input_continuity_probe.py"), str(tmp_path), renderer],
                               env=environment, cwd=ROOT, text=True, capture_output=True, timeout=20)
        assert probe.returncode == 0, probe.stdout + probe.stderr
        report = json.loads(probe.stdout.strip().splitlines()[-1])
        assert report["text_matches"] is True
        assert report["touch_drag_menu_preserved_focus"] is True
        assert report["native_window_accepts_focus"] is False
        assert report["renderer"] == renderer
        if renderer == "gpu":
            assert report["gpu_child_no_focus"] is True
            assert report["gpu_child_mouse_transparent"] is True
            assert report["input_shape_only"] is True
            assert report["gpu_frames_rendered"] > 0
        assert report["isolated_display"] == ":" + display_number
    finally:
        server.terminate()
        try:
            server.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=3)
        server.stdout.close()
        server.stderr.close()
