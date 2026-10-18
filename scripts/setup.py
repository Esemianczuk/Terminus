#!/usr/bin/env python3
"""Create a local runtime and install the native services for this checkout."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from terminus.runtime import python_path,find_uv
if sys.platform not in {'darwin','linux','win32'}:
    raise SystemExit('Native installation currently supports Windows, macOS and Linux. The web habitat works in other browsers.')
subprocess.run([find_uv(),'sync','--frozen','--extra','desktop'],cwd=ROOT,check=True)
if sys.platform == 'linux' and not (ROOT/'.local/organism.sqlite3').is_file():
    subprocess.run([str(python_path(ROOT)),str(ROOT/'scripts/termctl.py'),'start'],cwd=ROOT,check=True)
raise SystemExit(subprocess.call([str(python_path(ROOT)),str(ROOT/'scripts/servicectl.py'),'install'],cwd=ROOT))
