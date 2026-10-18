"""Tiny color probes of existing compositor pixmaps in a disposable process.

Never redirect windows, hide the pet, grab input, or read the composited root
screen (which would feed the creature's own colors back into itself).
"""
from __future__ import annotations

import ctypes as C
import ctypes.util


class Image(C.Structure):
    _fields_ = [("width", C.c_int), ("height", C.c_int), ("xoffset", C.c_int),
                ("format", C.c_int), ("data", C.c_void_p), ("byte_order", C.c_int),
                ("bitmap_unit", C.c_int), ("bitmap_bit_order", C.c_int),
                ("bitmap_pad", C.c_int), ("depth", C.c_int),
                ("bytes_per_line", C.c_int), ("bits_per_pixel", C.c_int),
                ("red_mask", C.c_ulong), ("green_mask", C.c_ulong), ("blue_mask", C.c_ulong)]


class Visual(C.Structure):
    _fields_ = [("ext_data",C.c_void_p),("visualid",C.c_ulong),("visual_class",C.c_int),
                ("red_mask",C.c_ulong),("green_mask",C.c_ulong),("blue_mask",C.c_ulong)]


class X11Background:
    source = "x11-compositor-colors"

    def __init__(self):
        self.x = C.CDLL(C.util.find_library("X11"))
        self.composite = C.CDLL(C.util.find_library("Xcomposite"))
        p, u, i = C.c_void_p, C.c_ulong, C.c_int
        def bind(lib, name, args, result):
            f = getattr(lib, name); f.argtypes, f.restype = args, result
        bind(self.x, "XOpenDisplay", [C.c_char_p], p)
        bind(self.x, "XDefaultRootWindow", [p], u)
        bind(self.x, "XDefaultScreen", [p], i)
        bind(self.x, "XDefaultVisual", [p,i], C.POINTER(Visual))
        bind(self.x, "XInternAtom", [p, C.c_char_p, i], u)
        bind(self.x, "XGetWindowProperty", [p,u,u,C.c_long,C.c_long,i,u,C.POINTER(u),C.POINTER(i),C.POINTER(u),C.POINTER(u),C.POINTER(p)], i)
        bind(self.x, "XGetGeometry", [p,u,C.POINTER(u),C.POINTER(i),C.POINTER(i),C.POINTER(C.c_uint),C.POINTER(C.c_uint),C.POINTER(C.c_uint),C.POINTER(C.c_uint)], i)
        bind(self.x, "XTranslateCoordinates", [p,u,u,i,i,C.POINTER(i),C.POINTER(i),C.POINTER(u)], i)
        bind(self.x, "XQueryTree", [p,u,C.POINTER(u),C.POINTER(u),C.POINTER(p),C.POINTER(C.c_uint)], i)
        bind(self.x, "XGetImage", [p,u,i,i,C.c_uint,C.c_uint,u,i], C.POINTER(Image))
        bind(self.x, "XGetPixel", [C.POINTER(Image),i,i], u)
        bind(self.x, "XDestroyImage", [C.POINTER(Image)], i)
        bind(self.x, "XFree", [p], i)
        bind(self.x, "XFreePixmap", [p,u], i)
        bind(self.x, "XSync", [p,i], i)
        bind(self.x, "XCloseDisplay", [p], i)
        bind(self.composite, "XCompositeNameWindowPixmap", [p,u], u)
        # Only this isolated worker owns the Xlib error callback.
        self.handler = C.CFUNCTYPE(i,p,p)(lambda *_: 0)
        self.x.XSetErrorHandler.argtypes = [C.c_void_p]
        self.x.XSetErrorHandler(self.handler)
        self.display = self.x.XOpenDisplay(None)
        if not self.display: raise OSError("display_unavailable")
        self.root = self.x.XDefaultRootWindow(self.display)
        visual=self.x.XDefaultVisual(self.display,self.x.XDefaultScreen(self.display)).contents
        self.masks=[visual.red_mask,visual.green_mask,visual.blue_mask]
        self.atoms = {}

    def prop(self, window, name):
        atom = self.atoms.setdefault(name, self.x.XInternAtom(self.display,name.encode(),1))
        actual, fmt, count, after, data = C.c_ulong(),C.c_int(),C.c_ulong(),C.c_ulong(),C.c_void_p()
        status = self.x.XGetWindowProperty(self.display,window,atom,0,256,0,0,C.byref(actual),C.byref(fmt),C.byref(count),C.byref(after),C.byref(data))
        try:
            if status or fmt.value != 32 or not data: return []
            # Xlib stores format32 words in native longs; some CARDINALs such
            # as the sticky-workspace sentinel arrive sign-extended on LP64.
            return [value & 0xffffffff for value in C.cast(data,C.POINTER(C.c_ulong))[:min(256,count.value)]]
        finally:
            if data: self.x.XFree(data)

    def geometry(self, window):
        root, x, y, w, h, border, depth = C.c_ulong(),C.c_int(),C.c_int(),C.c_uint(),C.c_uint(),C.c_uint(),C.c_uint()
        if not self.x.XGetGeometry(self.display,window,C.byref(root),C.byref(x),C.byref(y),C.byref(w),C.byref(h),C.byref(border),C.byref(depth)): return None
        child = C.c_ulong()
        if not self.x.XTranslateCoordinates(self.display,window,self.root,0,0,C.byref(x),C.byref(y),C.byref(child)): return None
        return x.value,y.value,w.value,h.value

    def color(self, drawable, x, y, w, h):
        # At most 64x64 pixels are transiently read, then reduced to RGB.
        size_x,size_y = min(64,w),min(64,h)
        if min(size_x,size_y)<=0: return None
        x,y = max(0,min(w-size_x,round(x-size_x/2))),max(0,min(h-size_y,round(y-size_y/2)))
        image = self.x.XGetImage(self.display,drawable,x,y,size_x,size_y,C.c_ulong(-1).value,2)
        if not image: return None
        try:
            masks=[image.contents.red_mask,image.contents.green_mask,image.contents.blue_mask]
            if not any(masks): masks=self.masks
            if not all(masks): return None
            shifts=[(m & -m).bit_length()-1 for m in masks]
            sums=[0.,0.,0.]
            for j in range(8):
                for k in range(8):
                    pixel=self.x.XGetPixel(image,min(size_x-1,(2*k+1)*size_x//16),min(size_y-1,(2*j+1)*size_y//16))
                    for c,(mask,shift) in enumerate(zip(masks,shifts)):
                        sums[c]+=((pixel&mask)>>shift)/(mask>>shift)
            return [round(value/64,5) for value in sums]
        finally: self.x.XDestroyImage(image)

    def frame_window(self, window):
        # A reparenting window manager redirects the decoration frame, not
        # necessarily the application child in _NET_CLIENT_LIST_STACKING.
        # Walk only that selected window's ancestors, stopping before root.
        current=window
        for _ in range(8):
            root,parent,children,count=C.c_ulong(),C.c_ulong(),C.c_void_p(),C.c_uint()
            ok=self.x.XQueryTree(self.display,current,C.byref(root),C.byref(parent),C.byref(children),C.byref(count))
            if children:self.x.XFree(children)
            if not ok:return None
            if parent.value in (0,self.root):return current
            if parent.value==current:return None
            current=parent.value
        return None

    def capture(self, rect, own_pid):
        stack=self.prop(self.root,"_NET_CLIENT_LIST_STACKING")
        owners={window:self.prop(window,"_NET_WM_PID") for window in stack}
        own_positions=[index for index,window in enumerate(stack) if owners[window]==[own_pid]]
        if not own_positions:
            return {"available":False,"reason":"own_panel_unavailable"}
        current_desktop=self.prop(self.root,"_NET_CURRENT_DESKTOP")[:1]
        windows=[]
        # EWMH stacking order is bottom-to-top. Exclude our entire process and
        # windows above the panel, including menus, notifications and alerts.
        for window in reversed(stack[:max(own_positions)]):
            if owners[window]==[own_pid]: continue
            if self.prop(window,"WM_STATE")[:1]!=[1]: continue
            desktop=self.prop(window,"_NET_WM_DESKTOP")[:1]
            if current_desktop and desktop and desktop not in (current_desktop,[0xffffffff]): continue
            frame=self.frame_window(window)
            geometry=self.geometry(frame or window)
            if geometry: windows.append((frame,geometry))
        wallpaper=self.prop(self.root,"_XROOTPMAP_ID") or self.prop(self.root,"ESETROOT_PMAP_ID")
        root_geo=self.geometry(self.root)
        result=[]
        for fx,fy in ((.25,.25),(.75,.25),(.25,.75),(.75,.75)):
            px,py=rect[0]+rect[2]*fx,rect[1]+rect[3]*fy
            color=None
            for window,(x,y,w,h) in windows:
                if not x<=px<x+w or not y<=py<y+h: continue
                pixmap=self.composite.XCompositeNameWindowPixmap(self.display,window) if window else 0
                if pixmap:
                    try: color=self.color(pixmap,px-x,py-y,w,h)
                    finally: self.x.XFreePixmap(self.display,pixmap)
                # Never look through an unavailable/secure top window.
                break
            else:
                if wallpaper and root_geo:
                    color=self.color(wallpaper[0],px,py,root_geo[2],root_geo[3])
            if color is None: return {"available":False,"reason":"background_unavailable"}
            result.append(color)
        return {"available":True,"colors":result,"source":self.source}

    def close(self):
        if self.display: self.x.XCloseDisplay(self.display); self.display=None
