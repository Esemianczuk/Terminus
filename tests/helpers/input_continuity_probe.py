"""Exercise only this process's widgets on the caller's isolated Xvfb display."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6 import QtCore, QtTest, QtWidgets
from desktop import overlay


def main():
    directory = Path(sys.argv[1])
    renderer = sys.argv[2] if len(sys.argv) > 2 else "raster"
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    QtWidgets.QSystemTrayIcon.isSystemTrayAvailable = lambda: False

    class Client(QtCore.QObject):
        snapshot = QtCore.Signal(dict)
        disconnected = QtCore.Signal(str)

        def __init__(self):
            super().__init__()
            self.data_dir = directory
            self.events = []

        def send_event(self, kind, **fields):
            self.events.append((kind, fields))

    client = Client()
    editor = QtWidgets.QPlainTextEdit()
    editor.setWindowTitle("Terminus isolated keyboard continuity fixture")
    editor.setGeometry(40, 40, 480, 360)
    editor.show()
    resident = overlay.Overlay(client, ROOT / "web/assets", 1.)
    resident.reference_renderer = renderer != "gpu"
    resident.awareness_enabled = False
    resident.roaming_paused = True
    resident.receive_state({"revision": 1, "behavior": "idle", "position": {"x": .5, "y": .62},
                            "attention": None, "nodes": [], "edges": []})
    for timer in (resident.animation, resident.asset_timer, resident.presence_timer, resident.awareness_timer):
        timer.stop()
    resident.move(650, 390)
    if renderer == "gpu":
        assert resident.enable_gpu(), getattr(resident, "gpu_error", "GPU initialization failed")
    resident.show()
    if renderer == "gpu":
        from desktop.x11_input import OwnWindowInputShape
        resident.clearMask()
        app.sync()
        resident.native_input_shape = OwnWindowInputShape(resident)
        assert resident.native_input_shape.available
        assert resident.native_input_shape.set_region(resident.input_region)
    QtTest.QTest.qWait(300)
    if renderer == "gpu":
        assert resident.gpu_scene.available, resident.gpu_scene.errors
        assert resident.gpu_scene.frames_rendered > 0
        assert resident.gpu_scene.focusPolicy() == QtCore.Qt.NoFocus
        assert resident.gpu_scene.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
    window = str(int(editor.winId()))

    def xdo(*arguments):
        return subprocess.run(["xdotool", *arguments], check=True, text=True,
                              capture_output=True, timeout=3).stdout.strip()

    def check_focus():
        observed = xdo("getwindowfocus")
        assert observed == window, {"expected": window, "observed": observed}
        assert QtWidgets.QWidget.keyboardGrabber() is None

    xdo("windowfocus", "--sync", window)
    QtTest.QTest.qWait(40)
    xdo("type", "--clearmodifiers", "--delay", "0", "before_")
    QtTest.QTest.qWait(40)
    check_focus()
    center = resident.creature_rect.center().toPoint()
    global_center = resident.mapToGlobal(center)
    # A real server-delivered click also passes through the noninteractive GPU
    # child. This display belongs exclusively to the fixture, never the user.
    xdo("mousemove", "--sync", str(global_center.x()), str(global_center.y()))
    xdo("click", "1")
    QtTest.QTest.qWait(40)
    check_focus()
    QtTest.QTest.mouseClick(resident, QtCore.Qt.LeftButton, pos=center)
    QtTest.QTest.qWait(30)
    check_focus()
    xdo("type", "--clearmodifiers", "--delay", "0", "after_touch_")
    QtTest.QTest.qWait(40)
    QtTest.QTest.mousePress(resident, QtCore.Qt.LeftButton, pos=center)
    QtTest.QTest.mouseMove(resident, center + QtCore.QPoint(30, -20), delay=20)
    QtTest.QTest.mouseRelease(resident, QtCore.Qt.LeftButton, pos=center + QtCore.QPoint(30, -20))
    QtTest.QTest.qWait(40)
    check_focus()
    xdo("type", "--clearmodifiers", "--delay", "0", "after_drag_")
    QtTest.QTest.qWait(40)
    menu = resident.make_menu()
    menu.popup(resident.mapToGlobal(center))
    QtTest.QTest.qWait(40)
    xdo("key", "Escape")
    QtTest.QTest.qWait(80)
    assert not menu.isVisible()
    check_focus()
    xdo("type", "--clearmodifiers", "--delay", "0", "after_menu")
    QtTest.QTest.qWait(40)
    expected = "before_after_touch_after_drag_after_menu"
    assert editor.toPlainText() == expected, repr(editor.toPlainText())
    report = {"renderer": renderer,
              "gpu_child_no_focus": resident.gpu_scene.focusPolicy() == QtCore.Qt.NoFocus if renderer == "gpu" else None,
              "gpu_child_mouse_transparent": resident.gpu_scene.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents) if renderer == "gpu" else None,
              "gpu_frames_rendered": resident.gpu_scene.frames_rendered if renderer == "gpu" else 0,
              "input_shape_only": bool(resident.native_input_shape is not None and resident.native_input_shape.available),
              "isolated_display": os.environ["DISPLAY"], "text_matches": True,
              "touch_drag_menu_preserved_focus": True, "keyboard_grabber": False,
              "native_window_accepts_focus": not bool(resident.windowFlags() & QtCore.Qt.WindowDoesNotAcceptFocus),
              "observes_real_devices": False, "network_requests": 0,
              "scope": "Linux Xvfb Qt native input flags; no window manager or macOS validation"}
    print(json.dumps(report))
    menu.deleteLater()
    resident.close()
    editor.close()
    app.processEvents()


if __name__ == "__main__":
    main()
