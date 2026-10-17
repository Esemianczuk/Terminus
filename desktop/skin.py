"""A bounded CPU fragment shader for the existing, immutable GIF body.

Pattern functions share normalized skin coordinates and a continuous clock.
Only RGB is shaded. Registered eye interiors and every alpha byte are copied
from the decoded frame, before the view applies its instant mirror and bank.
No screen sampling, new animations, GPU context, or organism events.
"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from PyQt5 import QtCore, QtGui

LUMA = np.array([.2126, .7152, .0722], dtype=np.float32)


def rgba(image):
    """Own the array; never borrow writable storage from the shared GIF cache."""
    converted = image.convertToFormat(QtGui.QImage.Format_RGBA8888)
    bits = converted.bits(); bits.setsize(converted.sizeInBytes())
    return np.frombuffer(bits, np.uint8).reshape(converted.height(), converted.bytesPerLine())[:, :converted.width()*4].reshape(converted.height(), converted.width(), 4).copy()


def smooth(a, b, x):
    t = np.clip((x-a)/(b-a), 0., 1.)
    return t*t*(3.-2.*t)


def noise(x, y, seed):
    """Deterministic interpolated lattice noise, evaluated once per geometry."""
    ix, iy = np.floor(x), np.floor(y)
    fx, fy = x-ix, y-iy
    fx, fy = fx*fx*(3-2*fx), fy*fy*(3-2*fy)
    def cell(a, b):
        v = np.sin(a*127.1+b*311.7+seed*19.19)*43758.5453
        return v-np.floor(v)
    return ((cell(ix,iy)*(1-fx)+cell(ix+1,iy)*fx)*(1-fy)
            +(cell(ix,iy+1)*(1-fx)+cell(ix+1,iy+1)*fx)*fy).astype(np.float32)


class SkinAtlas:
    """Fingerprinted eye geometry. Unknown or changed footage stays unshaded."""
    def __init__(self, frames=None, errors=None):
        self.frames = frames or {}
        self.errors = errors or {}

    @classmethod
    def load(cls, path, library):
        result = cls()
        try:
            path = Path(path)
            if path.stat().st_size > 512*1024:
                raise ValueError('Oversized skin atlas')
            data = json.loads(path.read_text())
            if data.get('version') != 1 or tuple(data.get('canvas', ())) != library.canvas:
                raise ValueError('Unsupported skin atlas')
            for name, clip in library.clips.items():
                try:
                    entry = data['clips'][name]
                    if hashlib.sha256(clip.path.read_bytes()).hexdigest() != entry['sha256']:
                        raise ValueError('Artwork fingerprint mismatch')
                    frames = entry['eyes']
                    if len(frames) != len(clip.frames):
                        raise ValueError('Frame count mismatch')
                    for polygons in frames:
                        if len(polygons) != 2:
                            raise ValueError('Two protected eyes required')
                        for polygon in polygons:
                            if not 3 <= len(polygon) <= 160:
                                raise ValueError('Invalid eye polygon')
                            for point in polygon:
                                if len(point) != 2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in point):
                                    raise ValueError('Invalid eye coordinate')
                    result.frames[name] = frames
                except (KeyError, TypeError, ValueError, OSError) as exc:
                    result.errors[name] = str(exc)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            result.errors['atlas'] = str(exc)
        return result


def eye_field(polygons, width, height):
    image = QtGui.QImage(width,height,QtGui.QImage.Format_RGBA8888)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(QtCore.Qt.NoPen); painter.setBrush(QtCore.Qt.white)
    for polygon in polygons:
        painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x*width,y*height) for x,y in polygon]))
    painter.end()
    protected = rgba(image)[:,:,3] > 0
    # Max-filter dilations, with a fully protected inner margin and a smooth
    # exterior falloff. No scipy, GL blur, wraparound or frame-sized history.
    def grow(a):
        p = np.pad(a,1)
        return np.maximum.reduce([p[y:y+height,x:x+width] for y in range(3) for x in range(3)])
    margin = max(1, round(height/208))
    for _ in range(margin):
        protected = grow(protected)
    shell = protected.copy()
    influence = np.ones((height,width),np.float32)
    influence[protected] = 0.
    feather = max(3, round(height*.025))
    for step in range(1,feather+1):
        outer = grow(shell)
        influence[outer & ~shell] = float(smooth(0.,1.,step/(feather+1)))
        shell = outer
    return protected, influence


@dataclass
class Surface:
    pixels: np.ndarray
    base: np.ndarray
    influence: np.ndarray
    active: np.ndarray
    light: np.ndarray
    highlights: np.ndarray
    x: np.ndarray
    y: np.ndarray
    broad: np.ndarray
    fine: np.ndarray
    cells: np.ndarray

    @property
    def nbytes(self):
        return sum(getattr(self,k).nbytes for k in ('pixels','base','influence','active','light','highlights'))


def spatial_fields(width, height):
    y,x = np.mgrid[0:height,0:width].astype(np.float32)
    x,y = x/width,y/height
    broad = noise(x*7,y*8,3)
    fine = noise(x*25,y*27,11)
    gx, gy = x*32, y*35
    cx = .5+.28*np.sin(np.floor(gy)*2.3+np.floor(gx)*4.1)
    cy = .5+.28*np.cos(np.floor(gx)*3.7-np.floor(gy)*2.9)
    cells = np.exp(-((gx%1-cx)**2+(gy%1-cy)**2)*18).astype(np.float32)
    return x,y,broad,fine,cells


def surface(image, polygons, width, height, fields=None):
    # The native path keeps the original GIF resolution and format, so Qt
    # samples exactly the same silhouette and eye detail with effects on/off.
    scaled = image.scaled(width,height,QtCore.Qt.IgnoreAspectRatio,QtCore.Qt.SmoothTransformation)
    pixels = rgba(scaled)
    protected, influence = eye_field(polygons,width,height)
    # Shade only painted, unprotected skin. Full-canvas arithmetic spent most
    # of each frame recomputing transparent pixels and then restoring them.
    active = np.flatnonzero((pixels[:,:,3] > 0) & ~protected).astype(np.int32)
    base = pixels.reshape(-1,4)[active,:3].astype(np.float32)/255
    light = np.einsum('ij,j->i',base,LUMA)
    highlights = smooth(.62,.96,light)[:,None]*.60
    return Surface(pixels,base,influence.ravel()[active],active,light,highlights,
                   *(fields if fields is not None else spatial_fields(width,height)))


def shimmer(s, t):
    band = .5+.5*np.sin(8*s.x+5*s.y-t*1.6+s.broad*3)
    tint = palette(band, (.09,.76,.83), (.56,.32,.94), (.82,.70,.98))
    glint = np.maximum(0,np.cos(15*s.y-8*s.x-t*1.8+s.broad*4))**12
    return tint, .20+.30*band+.26*glint*s.cells


def cascade(s, t):
    wave = .5+.5*np.sin(s.y*14-s.x*5-t*2.1+s.broad*3.5)
    tint = palette(wave, (.10,.78,.72), (.37,.24,.88), (.91,.42,.67))
    front = smooth(.48,.9,wave)
    return tint, .32+.52*front+.12*s.cells*front


def camouflage(s, t):
    reveal = smooth(.22,.78,.5+.5*np.sin(t*.48+s.broad*7+s.fine*1.3))
    tint = palette(s.broad*.72+reveal*.28, (.14,.25,.28), (.44,.56,.36), (.77,.62,.41))
    return tint, .50+.36*reveal+.13*s.cells


def crimson(s, t):
    # Deep wine/ember display; a travelling ember edge, never a flashing eye.
    pulse = .5+.5*np.sin(s.y*11+s.x*4-t*1.3+s.broad*3)
    tint = palette(pulse, (.30,.045,.16), (.74,.075,.18), (.98,.28,.16))
    return tint, .66+.25*pulse+.08*s.cells


# A layer is a pure (surface, clock) -> (RGB palette, coverage) function.
# Register another here to expose it in the menu without changing compositing.
PATTERNS = {'shimmer': shimmer, 'cascade': cascade, 'camouflage': camouflage, 'crimson': crimson}
LAYERS = tuple(PATTERNS)
MODES = ('automatic', *LAYERS, 'off')


def pattern(name, s, t):
    return PATTERNS[name](s,t)


def weights(**values):
    return np.array([values.get(name,0.) for name in LAYERS],np.float32)


def palette(t, low, mid, high):
    a = smooth(0.,.55,t)[...,None]
    b = smooth(.55,1.,t)[...,None]
    return ((np.asarray(low,dtype=np.float32)*(1-a)+np.asarray(mid,dtype=np.float32)*a)*(1-b)
            + np.asarray(high,dtype=np.float32)*b)


class SkinEngine:
    """Continuous, reversible uniforms driven by the view's real state."""
    def __init__(self, atlas=None, mode='automatic', max_cache_bytes=12*1024*1024):
        self.atlas = atlas or SkinAtlas()
        self.mode = mode if mode in MODES else 'automatic'
        self.cache = OrderedDict()
        self.fields = OrderedDict()
        self.max_cache_bytes = max_cache_bytes
        self.cache_bytes = 0
        self.weights = np.zeros(len(LAYERS),np.float32)
        self.intensity = 0.
        self.phase = 0.
        self.last_now = None
        self.last_live = False
        self.result_key = self.result = None
        self.material_key = self.material = None
        self.render_ms = 0.
        self.mask_valid = False

    def clear(self):
        self.cache.clear(); self.cache_bytes = 0
        self.fields.clear()
        self.result_key = self.result = None
        self.material_key = self.material = None

    def update(self, now, *, state=None, motion=0., touch_age=math.inf,
               gesture=None, fresh=True, reduced_motion=False):
        state = state or {}
        if not fresh:
            self.last_now, self.last_live = now, False
            return
        sleeping = state.get('behavior') in {'sleep','dream'}
        target = np.zeros(len(LAYERS),np.float32)
        strength, speed = .92, .75
        if self.mode == 'automatic':
            latent = state.get('latent') or {}
            agitation = latent.get('agitation',0.) if isinstance(latent,dict) else 0.
            agitation = (max(0.,min(1.,float(agitation))) if isinstance(agitation,(int,float))
                         and not isinstance(agitation,bool) and math.isfinite(agitation) else 0.)
            target = weights(shimmer=.64,cascade=.20,camouflage=.16)
            if sleeping:
                target = weights(shimmer=.85,cascade=.10,camouflage=.05); strength,speed = .40,.16
            elif state.get('behavior') in {'inspect','watch','orient'} or gesture in {'peer','tendril-inspect','imitate'}:
                target = weights(shimmer=.2,cascade=.15,camouflage=.65)
            movement = min(1.,max(0.,motion))
            target = target*(1-movement*.82)+weights(shimmer=.12,cascade=.88)*movement*.82
            # A touch is local feedback. It never writes affect into the core.
            flare = max(agitation*.65, .72*math.exp(-max(0.,touch_age)/1.2) if touch_age < 4.5 else 0.)
            target *= 1-flare; target[LAYERS.index('crimson')] += flare
            speed += movement*1.2
        elif self.mode in LAYERS:
            target[LAYERS.index(self.mode)] = 1.
        else:
            strength = 0.
        dt = 0. if self.last_now is None else min(.2,max(0.,now-self.last_now))
        resume = fresh and self.last_live
        if self.last_now is None or reduced_motion:
            # A static style is still selectable under Reduced motion.
            self.weights, self.intensity = target, strength
        elif resume:
            blend = 1-math.exp(-dt/1.1)
            self.weights += (target-self.weights)*blend
            self.intensity += (strength-self.intensity)*blend
        if resume and not reduced_motion:
            self.phase += dt*speed
        self.last_now, self.last_live = now, fresh

    def shade(self, sample, *, width=None, height=None):
        started = time.perf_counter()
        frames = self.atlas.frames.get(sample.clip)
        self.mask_valid = bool(frames and 0 <= sample.index < len(frames))
        if not self.mask_valid or self.mode == 'off':
            return sample.image
        width = max(32,min(sample.image.width(),round(width or sample.image.width())))
        height = max(32,min(sample.image.height(),round(height or sample.image.height())))
        key = (sample.image.cacheKey(),sample.clip,sample.index,width,height)
        s = self.cache.get(key)
        if s is None:
            # Spatial noise is shared by every frame at this size. Clear it
            # together with cached surfaces when the display scale changes.
            size = (width,height)
            if size not in self.fields:
                self.clear()
                self.fields[size] = spatial_fields(min(192,width),min(208,height))
            fields = self.fields[size]
            field_bytes = sum(v.nbytes for v in fields)
            output_bytes = width*height*20  # float RGBA material + owned QImage
            s = surface(sample.image,frames[sample.index],width,height,fields)
            if s.nbytes+field_bytes+output_bytes > self.max_cache_bytes:
                self.clear()
                return sample.image
            while self.cache and self.cache_bytes+s.nbytes+field_bytes+output_bytes > self.max_cache_bytes:
                _,old = self.cache.popitem(last=False); self.cache_bytes -= old.nbytes
            self.cache[key] = s; self.cache_bytes += s.nbytes
        else:
            self.cache.move_to_end(key)
        # Discrete shader ticks do not reset or seek the GIF player. The same
        # quantized clock freezes exactly when disconnected or motion-reduced.
        t = round(self.phase*15)/15
        uniforms = (t,tuple(np.round(self.weights,3)),round(self.intensity,3))
        result_key = (key,uniforms)
        if result_key == self.result_key:
            return self.result
        material_key = (width,height,uniforms)
        if self.material_key != material_key:
            # Evaluate smooth pigment fields at half the GIF's resolution,
            # then sample the material onto the full-resolution painted skin.
            # This retains exact source pixels for the eyes and silhouette.
            target = np.zeros((*s.x.shape,3),np.float32)
            coverage = np.zeros(s.x.shape,np.float32)
            for name, weight in zip(LAYERS,self.weights):
                if weight < .002:
                    continue
                tint, local = pattern(name,s,t)
                amount = local*float(weight)
                target += tint*amount[...,None]
                coverage += amount
            color = target/np.maximum(coverage[...,None],1e-6)
            packed = np.empty((*s.x.shape,4),np.uint8)
            packed[:,:,:3] = np.rint(np.clip(color,0,1)*255).astype(np.uint8)
            packed[:,:,3] = np.rint(np.clip(coverage,0,1)*255).astype(np.uint8)
            h,w = s.x.shape
            texture = QtGui.QImage(packed.data,w,h,packed.strides[0],QtGui.QImage.Format_RGBA8888)
            material = rgba(texture.scaled(width,height,QtCore.Qt.IgnoreAspectRatio,QtCore.Qt.SmoothTransformation)).astype(np.float32)/255
            self.material = material
            self.material_key = material_key
        material = self.material
        pigment = material.reshape(-1,4)[s.active]
        color = pigment[:,:3]*(.16+1.13*s.light[:,None])
        color = color*(1-s.highlights)+s.base*s.highlights
        amount = np.clip(pigment[:,3]*self.intensity*s.influence,0,.94)[:,None]
        pixels = s.pixels.copy()
        pixels.reshape(-1,4)[s.active,:3] = np.rint(np.clip(s.base*(1-amount)+color*amount,0,1)*255).astype(np.uint8)
        # Eyes, antialias guards, alpha and transparent RGB never enter the
        # scatter above. Their source bytes remain untouched by construction.
        self.result = QtGui.QImage(pixels.data,width,height,pixels.strides[0],QtGui.QImage.Format_RGBA8888).copy()
        self.result = self.result.convertToFormat(sample.image.format())
        self.result_key = result_key
        self.render_ms = (time.perf_counter()-started)*1000
        return self.result

    def diagnostics(self):
        return {'backend':'numpy-rgb-fragment-shader','mode':self.mode,'eye_mask_valid':self.mask_valid,
                'registered_clips':len(self.atlas.frames),'atlas_errors':self.atlas.errors,
                'layers':{name:round(float(w),3) for name,w in zip(LAYERS,self.weights)},
                'intensity':round(self.intensity,3),'phase':round(self.phase,3),
                'cache_bytes':(self.cache_bytes+sum(v.nbytes for fields in self.fields.values() for v in fields)
                               +(self.material.nbytes if self.material is not None else 0)
                               +(self.result.sizeInBytes() if self.result is not None else 0)),
                'cache_limit_bytes':self.max_cache_bytes,
                'evaluation_ms':round(self.render_ms,2)}
