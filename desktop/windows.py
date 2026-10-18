"""Nonactivating Windows overlay and own-window-only pointer hit testing.

No input hooks, synthetic input, focus calls or changes to other windows.
"""
import ctypes as C
from ctypes import wintypes as W
from PySide6 import QtCore,QtGui,QtWidgets

NOACTIVATE=0x08000000
TOOLWINDOW=0x80
TRANSPARENT=0x20


class WindowsPresence(QtCore.QAbstractNativeEventFilter):
    def __init__(self, widget):
        super().__init__()
        self.widget=widget; self.hwnd=int(widget.winId())
        self.user=C.WinDLL('user32',use_last_error=True)
        self.user.GetWindowLongPtrW.argtypes=[W.HWND,C.c_int]; self.user.GetWindowLongPtrW.restype=C.c_ssize_t
        self.user.SetWindowLongPtrW.argtypes=[W.HWND,C.c_int,C.c_ssize_t]; self.user.SetWindowLongPtrW.restype=C.c_ssize_t
        self.user.GetForegroundWindow.argtypes=[]; self.user.GetForegroundWindow.restype=W.HWND
        self.user.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
        self.user.SetWindowPos.argtypes=[W.HWND,W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT]
        self.user.SetWindowLongPtrW(self.hwnd,-20,self.user.GetWindowLongPtrW(self.hwnd,-20)|NOACTIVATE|TOOLWINDOW)
        # SWP_NOACTIVATE | NOMOVE | NOSIZE. Topmost without taking foreground.
        self.user.SetWindowPos(self.hwnd,W.HWND(-1),0,0,0,0,0x13)
        QtWidgets.QApplication.instance().installNativeEventFilter(self)
        self.timer=QtCore.QTimer(widget); self.timer.timeout.connect(self.update_hit_test); self.timer.start(33)
        self.update_hit_test()

    def nativeEventFilter(self, event_type, message):
        msg=W.MSG.from_address(int(message))
        if msg.hwnd==self.hwnd and msg.message==0x21:  # WM_MOUSEACTIVATE
            return True,3  # MA_NOACTIVATE: allow the click, never keyboard focus.
        return False,0

    def update_hit_test(self):
        inside=self.widget.input_region.contains(self.widget.mapFromGlobal(QtGui.QCursor.pos()))
        interactive=inside or self.widget.press_global is not None or self.widget.menu_open
        old=self.user.GetWindowLongPtrW(self.hwnd,-20)
        new=(old & ~TRANSPARENT) if interactive else (old | TRANSPARENT)
        new |= NOACTIVATE|TOOLWINDOW
        if new!=old: self.user.SetWindowLongPtrW(self.hwnd,-20,new)

    def diagnostics(self):
        style=self.user.GetWindowLongPtrW(self.hwnd,-20)
        foreground=self.user.GetForegroundWindow(); pid=W.DWORD()
        self.user.GetWindowThreadProcessId(foreground,C.byref(pid))
        import os
        return {'no_activate':bool(style&NOACTIVATE),'tool_window':bool(style&TOOLWINDOW),
                'empty_space_passthrough':bool(style&TRANSPARENT),
                'foreground_is_terminus':pid.value==os.getpid(),'keyboard_hooks':False}

    def close(self):
        self.timer.stop()
        QtWidgets.QApplication.instance().removeNativeEventFilter(self)
