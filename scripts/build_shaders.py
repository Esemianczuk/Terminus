#!/usr/bin/env python3
"""Bake portable Qt RHI shader packages, including GLES, Metal and HLSL."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    from PySide6 import __file__ as pyside_path
    qsb = Path(pyside_path).parent / "qsb"
    executable = str(qsb) if qsb.is_file() else shutil.which("pyside6-qsb")
    if not executable:
        raise SystemExit("Qt Shader Tools is required only when rebuilding shader source.")
    for source in sorted((ROOT / "desktop/shaders").glob("*.frag")):
        subprocess.run([executable, "--glsl", "100 es,120,150", "--hlsl", "50", "--msl", "12",
                        "-o", str(source.with_suffix(source.suffix + ".qsb")), str(source)], check=True)


if __name__ == "__main__":
    main()
