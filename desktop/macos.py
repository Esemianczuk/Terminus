"""Cocoa window behavior for the native body. No screen or keyboard capture."""
import ctypes
from PyQt5 import QtCore,QtGui


class MacPresence:
    def __init__(self,widget):
        import AppKit,objc
        self.widget=widget
        AppKit.NSApplication.sharedApplication().setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        view=objc.objc_object(c_void_p=ctypes.c_void_p(int(widget.winId())))
        self.window=view.window()
        self.window.setHidesOnDeactivate_(False)
        self.window.setLevel_(AppKit.NSFloatingWindowLevel)
        self.window.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces |
                                          AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
        # Cocoa can relocate a freshly shown tool window while its activation
        # policy changes. Reapply the Qt placement after that transition.
        position=widget.roam_position.toPoint() if widget.roam_position is not None else widget.pos()
        QtCore.QTimer.singleShot(150,lambda:widget.move(position))
        self.timer=QtCore.QTimer(widget)
        self.timer.timeout.connect(self.update_hit_test)
        self.timer.start(40)
        self.update_hit_test()

    def update_hit_test(self):
        local=self.widget.mapFromGlobal(QtGui.QCursor.pos())
        interactive=(self.widget.press_global is not None or self.widget.menu_open
                     or self.widget.input_region.contains(local))
        self.window.setIgnoresMouseEvents_(not interactive)
