"""Read-only window geometry and pointer polling. No keyboard APIs or hooks.

Typing and microphone sensing are deliberately unavailable on this backend.
Titles, executable names and window contents are never queried.
"""
import ctypes as C
from ctypes import wintypes as W


class WindowsMetadataBackend:
    source = 'windows-readonly'
    typing_available = False

    def __init__(self, stop, own_pid):
        self.stop, self.own_pid = stop, own_pid
        self.user = C.WinDLL('user32',use_last_error=True)
        self.callback = C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        signatures = {
            'GetForegroundWindow':([],W.HWND), 'GetWindowRect':([W.HWND,C.POINTER(W.RECT)],W.BOOL),
            'GetWindowThreadProcessId':([W.HWND,C.POINTER(W.DWORD)],W.DWORD),
            'IsWindowVisible':([W.HWND],W.BOOL), 'IsIconic':([W.HWND],W.BOOL),
            'GetCursorPos':([C.POINTER(W.POINT)],W.BOOL), 'GetSystemMetrics':([C.c_int],C.c_int),
            'EnumWindows':([self.callback,W.LPARAM],W.BOOL),
        }
        for name,(arguments,result) in signatures.items():
            fn=getattr(self.user,name); fn.argtypes=arguments; fn.restype=result
        # Match the physical desktop coordinate system in this disposable worker.
        if hasattr(self.user,'SetProcessDpiAwarenessContext'):
            self.user.SetProcessDpiAwarenessContext.argtypes=[C.c_void_p]
            self.user.SetProcessDpiAwarenessContext(C.c_void_p(-4))
        self.screen={key:self.user.GetSystemMetrics(i) for key,i in zip(('x','y','width','height'),(76,77,78,79))}

    def rectangle(self, hwnd):
        if not hwnd or not self.user.IsWindowVisible(hwnd) or self.user.IsIconic(hwnd): return None
        r=W.RECT(); pid=W.DWORD()
        if not self.user.GetWindowRect(hwnd,C.byref(r)) or r.right<=r.left or r.bottom<=r.top: return None
        self.user.GetWindowThreadProcessId(hwnd,C.byref(pid))
        return {'x':r.left,'y':r.top,'width':r.right-r.left,'height':r.bottom-r.top,'own':pid.value==self.own_pid}

    def focused_window(self, now):
        return self.rectangle(self.user.GetForegroundWindow())

    def pointer(self):
        p=W.POINT()
        if self.user.GetCursorPos(C.byref(p)):
            return {'x':p.x,'y':p.y,'screen':self.screen}

    def visible_windows(self, now):
        rows=[]
        @self.callback
        def collect(hwnd, _):
            if self.stop.is_set() or len(rows)>=64: return False
            rect=self.rectangle(hwnd)
            if rect and not rect.pop('own'): rows.append(rect)
            return True
        self.user.EnumWindows(collect,0)
        return rows

    def keypresses(self):
        return 0

    def close(self):
        pass


def pipe_ready(pipe):
    """select() only accepts sockets on Windows; peek at our own child pipe."""
    import msvcrt
    kernel=C.WinDLL('kernel32',use_last_error=True)
    kernel.PeekNamedPipe.argtypes=[W.HANDLE,C.c_void_p,W.DWORD,C.c_void_p,C.POINTER(W.DWORD),C.c_void_p]
    kernel.PeekNamedPipe.restype=W.BOOL
    available=W.DWORD()
    if not kernel.PeekNamedPipe(msvcrt.get_osfhandle(pipe.fileno()),None,0,None,C.byref(available),None):
        raise OSError('Observer pipe closed')
    return available.value>0
