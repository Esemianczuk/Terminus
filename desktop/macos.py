"""Cocoa window behavior for the native body. No screen or keyboard capture."""
import ctypes
import os
from PySide6 import QtCore,QtGui


def prepare_macos_environment():
    """Keep Qt's launch delegate from activating this background creature.

    Qt 6.10.3's qcocoaapplicationdelegate.mm::applicationDidFinishLaunching
    explicitly activates the process, including all windows on Sonoma+, unless
    this flag is set. Window nonfocus flags do not prevent app-level activation.
    This affects only the current process and must run before QApplication.
    """
    os.environ["QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM"]="1"


def configure_macos_application():
    """Set the accessory policy before constructing any presence windows."""
    import AppKit
    application=AppKit.NSApplication.sharedApplication()
    application.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    if application.activationPolicy()!=AppKit.NSApplicationActivationPolicyAccessory:
        raise RuntimeError("Could not configure Terminus as a background accessory")
    return application


class MacPresence:
    def __init__(self,widget):
        import AppKit,objc
        self.widget=widget
        application=AppKit.NSApplication.sharedApplication()
        if application.activationPolicy()!=AppKit.NSApplicationActivationPolicyAccessory:
            configure_macos_application()
        view=objc.objc_object(c_void_p=ctypes.c_void_p(int(widget.winId())))
        self.window=view.window()
        # Configure the tool panel before its first show. Mouse interaction
        # must never promote the creature to a typing destination.
        self.window.setBecomesKeyOnlyIfNeeded_(True)
        self.nonactivating_mask = AppKit.NSWindowStyleMaskNonactivatingPanel
        self.window.setStyleMask_(self.window.styleMask() | self.nonactivating_mask)
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
        self.last_interactive = None
        self.timer.start(60)
        self.update_hit_test()

    def update_hit_test(self):
        local=self.widget.mapFromGlobal(QtGui.QCursor.pos())
        interactive=(self.widget.press_global is not None or self.widget.menu_open
                     or self.widget.input_region.contains(local))
        if interactive != self.last_interactive:
            self.window.setIgnoresMouseEvents_(not interactive)
            self.last_interactive = interactive

    def diagnostics(self):
        return {'can_become_key':bool(self.window.canBecomeKeyWindow()),
                'can_become_main':bool(self.window.canBecomeMainWindow()),
                'is_key':bool(self.window.isKeyWindow()),
                'is_main':bool(self.window.isMainWindow()),
                'nonactivating':bool(self.window.styleMask() & self.nonactivating_mask),
                'ignores_mouse':bool(self.window.ignoresMouseEvents())}
