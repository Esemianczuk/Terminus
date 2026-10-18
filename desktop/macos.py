"""Cocoa body behavior and explicit own-panel diagnostics. No input capture."""
import ctypes
import os
from PySide6 import QtCore,QtGui
from desktop.macos_permission import request_input_monitoring


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
        self.presentation_capture=None
        # Configure the tool panel before its first show. Mouse interaction
        # must never promote the creature to a typing destination.
        self.window.setBecomesKeyOnlyIfNeeded_(True)
        self.nonactivating_mask = AppKit.NSWindowStyleMaskNonactivatingPanel
        self.window.setStyleMask_(self.window.styleMask() | self.nonactivating_mask)
        self.window.setHidesOnDeactivate_(False)
        # Dock can place a full-screen desktop layer above ordinary floating
        # panels. Keep the creature above that layer but below menus and alerts.
        self.window.setLevel_(AppKit.NSDockWindowLevel + 1)
        self.collection_behavior = (AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces |
                                    AppKit.NSWindowCollectionBehaviorCanJoinAllApplications |
                                    AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary |
                                    AppKit.NSWindowCollectionBehaviorStationary)
        self.window.setCollectionBehavior_(self.collection_behavior)
        # Cocoa can relocate a freshly shown tool window while its activation
        # policy changes. Reapply the Qt placement after that transition.
        position=widget.roam_position.toPoint() if widget.roam_position is not None else widget.pos()
        QtCore.QTimer.singleShot(150,lambda:widget.move(position))
        QtCore.QTimer.singleShot(250,self.bring_forward)
        self.timer=QtCore.QTimer(widget)
        self.timer.timeout.connect(self.update_hit_test)
        self.last_interactive = None
        self.timer.start(60)
        self.update_hit_test()

    def bring_forward(self):
        """Reorder the existing nonactivating body on the current Space."""
        import AppKit
        self.window.setCollectionBehavior_(self.collection_behavior)
        self.window.setLevel_(AppKit.NSDockWindowLevel + 1)
        self.window.orderFrontRegardless()

    def update_hit_test(self):
        local=self.widget.mapFromGlobal(QtGui.QCursor.pos())
        interactive=(self.widget.press_global is not None or self.widget.menu_open
                     or self.widget.input_region.contains(local))
        if interactive != self.last_interactive:
            self.window.setIgnoresMouseEvents_(not interactive)
            self.last_interactive = interactive

    def capture_image(self):
        """Inspect this NSPanel's actual composited pixels, only on request.

        QWidget.grab() can look correct even when a Metal scene is invisible
        in Cocoa. IncludeWindow captures only this instance's native window,
        including alpha; it never captures other apps or the desktop beneath.
        This is a one-off diagnostic, never the frame rendering path.
        """
        from desktop.background_macos import _CoreGraphics,_Rect,_Point,_Size
        self.presentation_capture={'method':'own-panel-compositor','presented':False}
        image=None
        try:
            api=_CoreGraphics()
            window_id=int(self.window.windowNumber())
            if window_id<=0 or not self.window.isVisible():
                self.presentation_capture['reason']='own_panel_not_visible'
                return QtGui.QImage()
            image=api.CGWindowListCreateImage(_Rect(_Point(0,0),_Size(0,0)),8,window_id,1)
            if not image:
                self.presentation_capture['reason']='own_panel_capture_unavailable'
                return QtGui.QImage()
            width,height=api.CGImageGetWidth(image),api.CGImageGetHeight(image)
            if not 1<=width<=4096 or not 1<=height<=4096 or width*height>8_000_000:
                self.presentation_capture['reason']='own_panel_capture_size_invalid'
                return QtGui.QImage()
            pixels=api.reduce(image,width,height)
            if pixels is None:
                self.presentation_capture['reason']='own_panel_capture_reduction_failed'
                return QtGui.QImage()
            visible=sum(alpha>8 for alpha in pixels[3::4])
            self.presentation_capture.update(presented=visible>0,visible_pixels=visible,
                                             width=width,height=height)
            if not visible:
                self.presentation_capture['reason']='own_panel_has_no_visible_pixels'
                return QtGui.QImage()
            return QtGui.QImage(pixels,width,height,width*4,
                                QtGui.QImage.Format_RGBA8888_Premultiplied).copy()
        except (OSError,RuntimeError,ValueError) as error:
            self.presentation_capture['reason']=type(error).__name__
            return QtGui.QImage()
        finally:
            if image:api.release(image)

    def diagnostics(self):
        return {'can_become_key':bool(self.window.canBecomeKeyWindow()),
                'can_become_main':bool(self.window.canBecomeMainWindow()),
                'is_key':bool(self.window.isKeyWindow()),
                'is_main':bool(self.window.isMainWindow()),
                'nonactivating':bool(self.window.styleMask() & self.nonactivating_mask),
                'ignores_mouse':bool(self.window.ignoresMouseEvents()),
                'cocoa_visible':bool(self.window.isVisible()),
                'on_active_space':bool(self.window.isOnActiveSpace()),
                'collection_behavior':int(self.window.collectionBehavior()),
                'level':int(self.window.level()),
                'window_class':str(self.window.className()),
                'presentation_capture':getattr(self,'presentation_capture',None)}
