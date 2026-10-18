"""Small registered eye materials shared by the raster and GPU renderers."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PySide6 import QtCore,QtGui

TILE=(96,64)


def _numbers(values,count,low=-10.,high=10.):
    return (isinstance(values,list) and len(values)==count
            and all(type(v) in (int,float) and math.isfinite(v) and low<=v<=high for v in values))


@dataclass
class EyeMaterial:
    bounds: tuple
    plate: np.ndarray
    iris: np.ndarray
    aperture: np.ndarray
    orbit: tuple


class GazeAtlas:
    """Hash-checked compact eye tiles; invalid assets keep the original eyes."""
    def __init__(self,path,library):
        self.path=Path(path);self.library=library
        self.clips={};self.errors={};self._clip=None
        self._image=QtGui.QImage();self._frames={}
        try:
            if self.path.stat().st_size>256*1024:raise ValueError('Oversized gaze manifest')
            data=json.loads(self.path.read_text())
            if data.get('version')!=2 or tuple(data.get('canvas',()))!=library.canvas or data.get('tile_canvas')!=list(TILE):
                raise ValueError('Unsupported eye material atlas')
            for name,clip in library.clips.items():
                try:
                    entry=data['clips'][name];count=len(clip.frames)
                    if hashlib.sha256(clip.path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('Eye materials do not match GIF')
                    if entry['frames']!=count or any(len(entry[key])!=count for key in ('rects','bounds','centres','orbits','openness')):
                        raise ValueError('Eye frame count mismatch')
                    if not _numbers(entry['texture_size'],2,1,2048) or not 0<float(entry['stride'])<1:
                        raise ValueError('Invalid eye texture geometry')
                    for index in range(count):
                        for key,n,lo,hi in (('rects',4,0,1),('bounds',4,-1,2),('centres',2,0,1),('orbits',4,-20,20)):
                            pair=entry[key][index]
                            if len(pair)!=2 or any(not _numbers(v,n,lo,hi) for v in pair):raise ValueError('Invalid eye registration')
                        if not _numbers(entry['openness'][index],2,0,1):raise ValueError('Invalid eye visibility')
                        for rect,bounds in zip(entry['rects'][index],entry['bounds'][index]):
                            if rect[2]<=0 or rect[3]<=0 or rect[0]+entry['stride']*2+rect[2]>1.000001 or rect[1]+rect[3]>1.000001:
                                raise ValueError('Eye tile exceeds atlas')
                            if abs(bounds[2]*library.canvas[0]-TILE[0])>.01 or abs(bounds[3]*library.canvas[1]-TILE[1])>.01:
                                raise ValueError('Eye crop dimensions mismatch')
                    self.clips[name]=entry
                except (KeyError,TypeError,ValueError,OSError,OverflowError) as exc:self.errors[name]=str(exc)
        except (OSError,ValueError,TypeError,AttributeError) as exc:self.errors['atlas']=str(exc)

    def centres(self,clip,index):
        entry=self.clips.get(clip)
        return entry['centres'][index] if entry is not None and type(index) is int and 0<=index<entry['frames'] else None

    def displacements(self,clip,index,shifts):
        entry=self.clips.get(clip)
        if entry is None or type(index) is not int or not 0<=index<entry['frames']:return (0.,0.,0.,0.)
        result=[]
        for eye,orbit in enumerate(entry['orbits'][index]):
            sx=max(-1.2,min(1.2,float(shifts[eye*2])/3.6));sy=max(-1.,min(1.,float(shifts[eye*2+1])/2.5))
            if entry['openness'][index][eye]<=0:sx=sy=0.
            result.extend((orbit[0]*sx+orbit[2]*sy,orbit[1]*sx+orbit[3]*sy))
        return tuple(result)

    def ensure_texture(self,clip):
        entry=self.clips.get(clip)
        if entry is None or clip in self.errors:return False
        if self._clip==clip:return True
        self._clip=None;self._frames={}
        try:
            path=self.path.parent/f'{clip}.png'
            if path.stat().st_size>8*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['field_sha256']:
                raise ValueError('Eye texture fingerprint mismatch')
            reader=QtGui.QImageReader(str(path))
            if reader.size()!=QtCore.QSize(*entry['texture_size']):raise ValueError('Eye texture dimensions mismatch')
            image=reader.read()
            if image.isNull():raise ValueError('Cannot decode eye texture')
            self._image=image.convertToFormat(QtGui.QImage.Format_RGBA8888_Premultiplied);self._clip=clip
            return True
        except (OSError,ValueError,KeyError) as exc:self.errors[clip]=str(exc);return False

    def frame(self,clip,index):
        entry=self.clips.get(clip)
        if entry is None or type(index) is not int or not 0<=index<entry['frames'] or not self.ensure_texture(clip):return None
        if index not in self._frames:
            result=[]
            for eye,rect in enumerate(entry['rects'][index]):
                images=[]
                for material in range(3):
                    x=round((rect[0]+material*entry['stride'])*self._image.width());y=round(rect[1]*self._image.height())
                    image=self._image.copy(x,y,*TILE)
                    array=np.frombuffer(image.constBits(),np.uint8).reshape(TILE[1],image.bytesPerLine())[:,:TILE[0]*4].reshape(TILE[1],TILE[0],4).astype(np.float32)
                    images.append(array)
                bounds=entry['bounds'][index][eye]
                pixels=(round(bounds[0]*self.library.canvas[0]),round(bounds[1]*self.library.canvas[1]),*TILE)
                result.append(EyeMaterial(pixels,images[0][:,:,:3],images[1],images[2][:,:,0]/255.,tuple(entry['orbits'][index][eye])))
            self._frames[index]=tuple(result)
            if len(self._frames)>3:self._frames.pop(next(iter(self._frames)))
        return self._frames[index]


def _translate(pixels,dx,dy):
    h,w=pixels.shape[:2];y,x=np.mgrid[:h,:w].astype(np.float32)
    x=np.clip(x-dx,0,w-1.00001);y=np.clip(y-dy,0,h-1.00001)
    ix,iy=x.astype(np.int32),y.astype(np.int32);fx,fy=(x-ix)[:,:,None],(y-iy)[:,:,None]
    return ((pixels[iy,ix]*(1-fx)+pixels[iy,ix+1]*fx)*(1-fy)
            +(pixels[iy+1,ix]*(1-fx)+pixels[iy+1,ix+1]*fx)*fy)


def compose_eye_layers(image,materials,displacements):
    """Rigid iris translations, fixed lid pixels, exact neutral and alpha."""
    if materials is None or max(abs(v) for v in displacements)<.0001:return image
    base=image.convertToFormat(QtGui.QImage.Format_RGBA8888_Premultiplied)
    output=base.copy()
    pixels=np.frombuffer(output.bits(),np.uint8).reshape(output.height(),output.bytesPerLine())[:,:output.width()*4].reshape(output.height(),output.width(),4)
    for eye,material in enumerate(materials):
        dx,dy=displacements[eye*2:eye*2+2]
        if max(abs(dx),abs(dy))<.0001 or not np.any(material.aperture):continue
        moved=_translate(material.iris,dx,dy)
        neutral=material.iris
        delta=(moved[:,:,:3]-material.plate*(moved[:,:,3:4]/255.))-(neutral[:,:,:3]-material.plate*(neutral[:,:,3:4]/255.))
        x,y,w,h=material.bounds
        x0,y0=max(0,x),max(0,y);x1,y1=min(image.width(),x+w),min(image.height(),y+h)
        if x1<=x0 or y1<=y0:continue
        sx,sy=x0-x,y0-y;delta=delta[sy:sy+y1-y0,sx:sx+x1-x0]
        aperture=material.aperture[sy:sy+y1-y0,sx:sx+x1-x0,None]
        area=pixels[y0:y1,x0:x1]
        area[:,:,:3]=np.rint(np.clip(area[:,:,:3].astype(np.float32)+delta*aperture,0,area[:,:,3:4])).astype(np.uint8)
    return output
