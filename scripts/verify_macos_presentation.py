#!/usr/bin/env python3
"""Verify real Cocoa-composited Metal pixels on a noninteractive test panel.

Only this process's own window is captured. No Screen Recording grant is needed,
no desktop contents are captured, and the live organism and its data stay alone.
"""
from __future__ import annotations
import argparse
import ctypes
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'work/mac-presentation')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('This verification requires a signed-in macOS desktop')
    args.output.mkdir(parents=True, exist_ok=True)
    from desktop.macos import prepare_macos_environment, configure_macos_application, MacPresence
    from desktop.background_macos import _CoreGraphics, _Rect, _Point, _Size
    from desktop.gpu import GpuScene
    from PySide6 import QtCore, QtGui, QtWidgets
    import AppKit
    prepare_macos_environment()
    app = QtWidgets.QApplication([])
    configure_macos_application()
    workspace = AppKit.NSWorkspace.sharedWorkspace()
    frontmost = int(workspace.frontmostApplication().processIdentifier())
    window = QtWidgets.QWidget(None, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint
                               | QtCore.Qt.WindowDoesNotAcceptFocus | QtCore.Qt.WindowStaysOnTopHint)
    window.setAttribute(QtCore.Qt.WA_TranslucentBackground)
    window.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
    window.setFocusPolicy(QtCore.Qt.NoFocus)
    window.resize(440, 340)
    window.move(600, 250)
    window.roam_position = None
    window.press_global = None
    window.menu_open = False
    window.input_region = QtGui.QRegion()
    # This ordering is the production contract: the GPU chooses the backing
    # store before MacPresence asks Qt for the native Cocoa view via winId().
    scene = GpuScene(window)
    scene.setGeometry(window.rect())
    presence = MacPresence(window)
    api = _CoreGraphics()
    report = {'captures': [], 'frontmost_before': frontmost, 'success': False}
    failed = []
    stage = [0]

    def draw():
        scene.setGeometry(window.rect())
        scene.set_scene(clip='idle', index=0, phase=0, body_rect=(28,-50,384,416),
                        clock=3, skin_weights=(0,0,0,0), skin_intensity=0)

    def capture():
        try:
            if not scene.available:
                raise RuntimeError(json.dumps(scene.diagnostics()))
            image = api.CGWindowListCreateImage(_Rect(_Point(0,0), _Size(0,0)),
                                                8, int(presence.window.windowNumber()), 1)
            if not image:
                raise RuntimeError('The native compositor returned no own-panel image')
            try:
                width, height = api.CGImageGetWidth(image), api.CGImageGetHeight(image)
                pixels = api.reduce(image, width, height)
            finally:
                api.release(image)
            if pixels is None:
                raise RuntimeError('Cannot inspect the native panel pixels')
            opaque = sum(value > 10 for value in pixels[3::4])
            transparent = sum(value == 0 for value in pixels[3::4])
            if opaque < 5000 or transparent < 5000:
                raise RuntimeError(f'Native panel missing creature or transparency: {opaque=}, {transparent=}')
            focus = presence.diagnostics()
            if any(focus[key] for key in ('can_become_key','can_become_main','is_key','is_main')):
                raise RuntimeError('The passive panel became eligible for keyboard focus')
            if QtWidgets.QWidget.keyboardGrabber() is not None:
                raise RuntimeError('A widget grabbed the keyboard')
            current_frontmost = int(workspace.frontmostApplication().processIdentifier())
            if current_frontmost != frontmost:
                raise RuntimeError('Frontmost application changed during the nonactivating probe')
            name = ('initial','moved','resized')[stage[0]]
            QtGui.QImage(pixels, width, height, width*4,
                         QtGui.QImage.Format_RGBA8888_Premultiplied).save(str(args.output/(name+'.png')))
            report['captures'].append({'stage': name, 'size': [width,height], 'opaque_pixels': opaque,
                                       'transparent_pixels': transparent, 'native_focus': focus,
                                       'frontmost': current_frontmost, 'graphics': scene.diagnostics()})
            stage[0] += 1
            if stage[0] == 1:
                window.move(680, 290)
                presence.bring_forward()
            elif stage[0] == 2:
                window.resize(550, 425)
                draw()
            else:
                report['success'] = True
                app.quit()
                return
            QtCore.QTimer.singleShot(500, capture)
        except Exception as error:
            failed.append(f'{type(error).__name__}: {error}')
            app.quit()

    draw()
    window.show()
    QtCore.QTimer.singleShot(900, capture)
    QtCore.QTimer.singleShot(10000, app.quit)
    app.exec()
    report['errors'] = failed
    report['scope'] = 'Native compositor pixels of our own noninteractive fixture; no other windows or input captured'
    (args.output/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
