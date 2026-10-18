"""Native XComposite fixture in an isolated display with no user's windows."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform!='linux' or not shutil.which('Xvfb'),reason='Requires isolated Xvfb')
def test_native_quadrants_exclude_own_and_higher_windows():
    server=subprocess.Popen(['Xvfb','-displayfd','1','-screen','0','1280x800x24','-nolisten','tcp'],
                            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        number=server.stdout.readline().strip()
        assert number.isdecimal()
        result=subprocess.run([sys.executable,'tests/helpers/background_x11_probe.py'],
                              cwd=Path(__file__).resolve().parents[1],
                              env={**os.environ,'DISPLAY':':'+number,'QT_QPA_PLATFORM':'xcb'},
                              capture_output=True,text=True,timeout=15)
        assert result.returncode==0,result.stderr
        report=json.loads(result.stdout)
        assert report['excluded_own_magenta'] and report['excluded_above_yellow']
        assert report['synthetic_windows_only'] and report['samples']==20
    finally:
        server.terminate()
        try:server.communicate(timeout=3)
        except subprocess.TimeoutExpired:server.kill();server.communicate()
