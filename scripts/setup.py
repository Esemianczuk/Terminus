#!/usr/bin/env python3
"""Create a local runtime and install the native services for this checkout."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if sys.platform not in {'darwin','linux'}:
    raise SystemExit('Native installation currently supports macOS and Linux. The web habitat works in other browsers.')
subprocess.run(['uv','sync','--frozen','--extra','desktop'],cwd=ROOT,check=True)
if sys.platform == 'linux' and not (ROOT/'.local/organism.sqlite3').is_file():
    subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/termctl.py'),'start'],cwd=ROOT,check=True)
raise SystemExit(subprocess.call([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/servicectl.py'),'install'],cwd=ROOT))
