"""Registered, texture-preserving eye motion for native desktop renderers.

The mask atlas is generated once from source-pose aperture annotations by the
same rig as the GIFs. At runtime a small backward warp moves original painted
iris, sclera and specular pixels together. No new eye texture is synthesized.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import random

import numpy as np
from PySide6 import QtCore, QtGui


class GazeAtlas:
    def __init__(self, path, library):
        self.path = Path(path)
        self.library = library
        self.clips = {}
        self.errors = {}
        self._clip = None
        self._image = QtGui.QImage()
        self._fields = {}
        try:
            if self.path.stat().st_size > 256 * 1024:
                raise ValueError("Gaze manifest exceeds its size budget")
            data = json.loads(self.path.read_text())
            if (data.get("version") != 1 or tuple(data.get("canvas", ())) != library.canvas
                    or data.get("field_canvas") != [192, 208]):
                raise ValueError("Unsupported gaze atlas")
            for name, clip in library.clips.items():
                try:
                    entry = data["clips"][name]
                    if hashlib.sha256(clip.path.read_bytes()).hexdigest() != entry["sha256"]:
                        raise ValueError("Gaze field does not match the GIF")
                    count = len(clip.frames)
                    if (entry["frames"] != count or len(entry["rects"]) != count
                            or len(entry["centres"]) != count or len(entry["openness"]) != count):
                        raise ValueError("Gaze frame count mismatch")
                    for rect, centers, openings in zip(entry["rects"],entry["centres"],entry["openness"]):
                        if len(rect) != 4 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in rect):
                            raise ValueError("Invalid gaze atlas rectangle")
                        if (len(centers) != 2 or any(len(c) != 2 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in c) for c in centers)
                                or len(openings) != 2 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in openings)):
                            raise ValueError("Invalid gaze eye registration")
                    self.clips[name] = entry
                except (KeyError, TypeError, ValueError, OSError) as exc:
                    self.errors[name] = str(exc)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self.errors["atlas"] = str(exc)

    def rect(self, clip, index):
        entry = self.clips.get(clip)
        if entry is None or not 0 <= index < entry["frames"]:
            return None
        return entry["rects"][index]

    def ensure_texture(self, clip):
        entry = self.clips.get(clip)
        if entry is None or clip in self.errors:return False
        if clip != self._clip:
            self._clip, self._fields = None, {}
            image_path = self.path.parent / f"{clip}.png"
            try:
                if image_path.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError("Gaze texture exceeds its size budget")
                if hashlib.sha256(image_path.read_bytes()).hexdigest() != entry["field_sha256"]:
                    raise ValueError("Gaze texture fingerprint mismatch")
                image = QtGui.QImage(str(image_path))
                if image.isNull() or image.width() > 2048 or image.height() > 2048:
                    raise ValueError("Invalid gaze texture")
                self._image = image.convertToFormat(QtGui.QImage.Format_RGBA8888)
                self._clip = clip
            except (OSError, KeyError, ValueError) as exc:
                self.errors[clip] = str(exc)
                return False
        return True

    def field(self, clip, index):
        entry = self.clips.get(clip)
        if entry is None or not 0 <= index < entry["frames"] or not self.ensure_texture(clip):
            return None
        if index not in self._fields:
            x, y, w, h = entry["rects"][index]
            bounds = QtCore.QRect(round(x*self._image.width()),round(y*self._image.height()),
                                  round(w*self._image.width()),round(h*self._image.height()))
            if bounds.size() != QtCore.QSize(192,208) or not self._image.rect().contains(bounds):
                self.errors[clip] = "Invalid gaze frame boundary"
                return None
            frame = self._image.copy(bounds).scaled(*self.library.canvas,QtCore.Qt.IgnoreAspectRatio,QtCore.Qt.SmoothTransformation)
            pixels = np.frombuffer(frame.constBits(),np.uint8).reshape(frame.height(),frame.bytesPerLine())[:,:frame.width()*4]
            self._fields[index] = pixels.reshape(frame.height(),frame.width(),4)[:,:,:2].astype(np.float32)/255.
            if len(self._fields) > 3:
                self._fields.pop(next(iter(self._fields)))
        return self._fields[index]


def warp_eye_pixels(image, field, shifts):
    """Remap only the eye bounding box; zero displacement is pixel-identical."""
    if field is None or max(abs(value) for value in shifts) < .015:
        return image
    if image.width() != field.shape[1] or image.height() != field.shape[0]:
        return image
    valid = (field[:,:,0] + field[:,:,1]) > .005
    yy, xx = np.nonzero(valid)
    if not len(xx):
        return image
    left, right = max(0,int(xx.min())-5), min(image.width(),int(xx.max())+6)
    top, bottom = max(0,int(yy.min())-5), min(image.height(),int(yy.max())+6)
    base = image.convertToFormat(QtGui.QImage.Format_ARGB32_Premultiplied)
    source = np.frombuffer(base.constBits(),np.uint8).reshape(base.height(),base.bytesPerLine())[:,:base.width()*4].reshape(base.height(),base.width(),4)
    output = base.copy()
    target = np.frombuffer(output.bits(),np.uint8).reshape(output.height(),output.bytesPerLine())[:,:output.width()*4].reshape(output.height(),output.width(),4)
    area = field[top:bottom,left:right]
    dx = area[:,:,0]*shifts[0] + area[:,:,1]*shifts[2]
    dy = area[:,:,0]*shifts[1] + area[:,:,1]*shifts[3]
    y, x = np.mgrid[top:bottom,left:right].astype(np.float32)
    x = np.clip(x-dx,0,image.width()-1.00001)
    y = np.clip(y-dy,0,image.height()-1.00001)
    x0, y0 = x.astype(np.int32), y.astype(np.int32)
    xf, yf = (x-x0)[:,:,None],(y-y0)[:,:,None]
    sampled = ((source[y0,x0].astype(np.float32)*(1-xf)+source[y0,x0+1]*xf)*(1-yf)
               +(source[y0+1,x0].astype(np.float32)*(1-xf)+source[y0+1,x0+1]*xf)*yf)
    target[top:bottom,left:right] = np.rint(sampled).astype(np.uint8)
    return output


class GazeController:
    """Private, bounded presentation intent; never records cursor coordinates."""
    def __init__(self, seed=0):
        self.random = random.Random(str(seed))
        self.shift = (0.,0.,0.,0.)
        self.last_at = None
        self.pointer_at = -math.inf
        self.pointer_xy = None
        self.next_glance = 0.
        self.rest = (0.,0.)
        self.rest_mode = "rest"
        self.mode = "rest"

    def update(self, now, *, body, screen, mirror=False, pointer=None,
               graph_target=None, inspection_target=None, typing=False,
               sleeping=False, reduced_motion=False):
        dt = 0. if self.last_at is None else max(0.,min(.15,now-self.last_at))
        self.last_at = now
        if reduced_motion:
            self.shift=(0.,0.,0.,0.);self.mode="reduced-motion"
            return self.shift
        target = None
        if pointer is not None:
            px, py, motion = pointer
            if all(math.isfinite(v) for v in (px,py,motion)):
                if motion > .004:
                    self.pointer_at=now
                    self.pointer_xy=(screen[0]+max(0.,min(1.,px))*screen[2],screen[1]+max(0.,min(1.,py))*screen[3])
                if now-self.pointer_at < 1.8:
                    target=self.pointer_xy
                    self.mode="pointer"
        if target is None and typing and inspection_target is not None:
            target=inspection_target;self.mode="typing-window"
        if target is None:
            if now >= self.next_glance:
                choices = (["graph"]*5 if graph_target is not None else []) + (["window"]*2 if inspection_target is not None else []) + ["wander"]*2 + ["rest"]*2
                self.rest_mode = self.random.choice(choices)
                self.rest = (self.random.uniform(-.65,.65),self.random.uniform(-.35,.35)) if self.rest_mode == "wander" else (0.,0.)
                self.next_glance = now + self.random.uniform(2.4,6.8)
            if self.rest_mode == "graph" and graph_target is not None:
                target=graph_target;self.mode="graph"
            elif self.rest_mode == "window" and inspection_target is not None:
                target=inspection_target;self.mode="window"
        if sleeping:
            desired=(0.,0.,0.,0.);self.mode="sleep"
        elif target is None:
            x,y=self.rest
            desired=(x*3.3,y*2.1,x*3.3,y*2.1)
            self.mode="autonomous" if x or y else "rest"
        else:
            bx,by,bw,bh=body
            origin=(bx+(.45 if mirror else .55)*bw,by+.41*bh)
            dx,dy=target[0]-origin[0],target[1]-origin[1]
            distance=math.hypot(dx,dy)
            x=math.tanh((-dx if mirror else dx)/max(65.,bw*.7))
            y=math.tanh(dy/max(54.,bh*.56))
            convergence=max(0.,min(1.,(160.-distance)/120.))*.72
            desired=(x*3.6+convergence,y*2.5,x*3.6-convergence,y*2.5)
        alpha=1-math.exp(-dt*11.)
        self.shift=tuple(current+(want-current)*alpha for current,want in zip(self.shift,desired))
        return self.shift
