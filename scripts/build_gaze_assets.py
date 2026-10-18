#!/usr/bin/env python3
"""Bake fixed apertures, rigid iris materials and pose-local orbit geometry.

Entirely offline. The native runtime translates each iris behind its fixed lid
and applies a neutral-relative color delta to the untouched original GIF.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PIL import Image, ImageSequence
from PySide6 import QtGui, QtWidgets
from build_animation_clips import FrameAuthor, ROOT, SOURCES, SPECS, WIDTH, HEIGHT
from gaze_source_layers import source_layers

SOURCE=ROOT/'web/assets/clips'
OUTPUT=ROOT/'web/assets/gaze'
TILE_WIDTH,TILE_HEIGHT=96,64
PAD,COLUMNS=2,4


def pixmap(values):
    values=np.ascontiguousarray(values,dtype=np.uint8)
    h,w=values.shape[:2]
    if values.shape[-1]==3:values=np.dstack((values,np.full((h,w),255,np.uint8)))
    image=QtGui.QImage(values.data,w,h,w*4,QtGui.QImage.Format_RGBA8888).copy()
    return QtGui.QPixmap.fromImage(image)


def material_sources(eye,kind,layers):
    result={}
    for name,path in SOURCES.items():
        with Image.open(path) as image:w,h=image.size
        layer=layers[name][eye] if layers[name] else None
        if kind=='mask':
            values=np.zeros((h,w,4),np.uint8);values[:,:,3]=255
            if layer is not None:values[:,:,:3]=layer['aperture'][:,:,None]
        elif kind=='marker':
            values=np.zeros((h,w,4),np.uint8)
            if layer is not None:
                cx,cy=np.asarray(layer['centre'])*[w,h]
                rx,ry=np.asarray(layer['radii'])*[w,h]
                theta=math.radians(layer.get('angle',0.))
                # The fitted ellipse's eigenvector angle is not head facing.
                # Orbit left/right in the painted facial plane, then let the
                # pose rig supply the real bank, squash and local deformation.
                horizontal=math.hypot(rx*math.cos(theta),ry*math.sin(theta))
                vertical=math.hypot(rx*math.sin(theta),ry*math.cos(theta))
                xstep=np.array([horizontal*.24,0.])
                ystep=np.array([0.,vertical*.09])
                points=[np.array([cx,cy]),np.array([cx,cy])+xstep,np.array([cx,cy])+ystep]
                yy,xx=np.mgrid[:h,:w]
                for channel,point in enumerate(points):
                    values[:,:,channel]=np.rint(np.exp(-((xx-point[0])**2+(yy-point[1])**2)/(2*3.5**2))*255).astype(np.uint8)
                values[:,:,3]=255
        elif layer is None:values=np.zeros((h,w,4),np.uint8)
        else:values=layer[kind]
        result[name]=pixmap(values)
    return result


def register_marker(image):
    array=np.asarray(image).astype(np.float64);points=[]
    for channel in range(3):
        values=array[:,:,channel];total=values.sum()
        if total<2:return None
        yy,xx=np.mgrid[:values.shape[0],:values.shape[1]]
        points.append(np.array([(xx*values).sum()/total,(yy*values).sum()/total]))
    return points[0],np.r_[points[1]-points[0],points[2]-points[0]]


def pack(frames):
    cell_w,cell_h=(TILE_WIDTH+PAD*2)*3,TILE_HEIGHT+PAD*2
    rows=math.ceil(len(frames)*2/COLUMNS)
    atlas=Image.new('RGBA',(COLUMNS*cell_w,rows*cell_h));textures=[]
    for frame_index,eyes in enumerate(frames):
        registered=[]
        for eye_index,materials in enumerate(eyes):
            index=frame_index*2+eye_index
            x,y=index%COLUMNS*cell_w+PAD,index//COLUMNS*cell_h+PAD
            registered.append([x/atlas.width,y/atlas.height,TILE_WIDTH/atlas.width,TILE_HEIGHT/atlas.height])
            for kind,image in enumerate(materials):
                padded=np.pad(np.asarray(image),((PAD,PAD),(PAD,PAD),(0,0)),mode='edge')
                atlas.paste(Image.fromarray(padded),(x+kind*(TILE_WIDTH+PAD*2)-PAD,y-PAD))
        textures.append(registered)
    return atlas,textures,(TILE_WIDTH+PAD*2)/atlas.width


def match_visible_material(plate,iris,aperture,original):
    """Exact alpha matting against decoded GIF colors prevents an old-iris halo.

    Source segmentation supplies the geometry and hidden cap. The foreground
    is then solved against its backplate at every visible boundary pixel, so
    partial alpha does not leave the original limbus behind during movement.
    """
    background=np.asarray(plate).copy().astype(np.float32)/255.
    foreground=np.asarray(iris).copy().astype(np.float32)/255.
    observed=np.asarray(original).astype(np.float32)[:,:,:3]/255.
    inside=np.asarray(aperture)[:,:,0]>.99*255
    alpha=foreground[:,:,3]
    outside=inside&(alpha<.01)
    background[outside,:3]=observed[outside]
    b=background[:,:,:3]
    required=np.where(observed<b,1-observed/np.maximum(b,.00001),
                      (observed-b)/np.maximum(1-b,.00001)).max(axis=2)
    corrected=np.ceil(np.maximum(alpha,required)*255)/255.
    corrected=np.clip(corrected,0,1)
    premultiplied=observed-b*(1-corrected[:,:,None])
    color=np.clip(premultiplied/np.maximum(corrected[:,:,None],1/255),0,1)
    foreground[inside,:3]=color[inside];foreground[inside,3]=corrected[inside]
    return Image.fromarray(np.rint(background*255).clip(0,255).astype(np.uint8)),Image.fromarray(np.rint(foreground*255).clip(0,255).astype(np.uint8))


def build():
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    OUTPUT.mkdir(parents=True,exist_ok=True)
    layers={name:source_layers(name) for name in SOURCES}
    author=FrameAuthor()
    materials={(eye,kind):material_sources(eye,kind,layers) for eye in range(2) for kind in ('plate','iris','mask','marker')}
    result={'version':2,'canvas':[WIDTH,HEIGHT],'tile_canvas':[TILE_WIDTH,TILE_HEIGHT],
            'method':'fixed aperture, rigid iris and neutral-relative sclera composite through original pose rig',
            'sources':{name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in SOURCES.items()},'clips':{}}
    for name,(count,delay,_) in SPECS.items():
        authored={}
        for eye in range(2):
            for kind in ('plate','iris','mask','marker'):
                author.art=materials[eye,kind]
                authored[eye,kind]=[author.render(name,index,count,blink_layer=kind=='mask') for index in range(count)]
        path=SOURCE/f'{name}.gif'
        with Image.open(path) as gif:
            decoded=[frame.convert('RGBA') for frame in ImageSequence.Iterator(gif)]
            durations=[max(20,min(1000,frame.info.get('duration',delay))) for frame in ImageSequence.Iterator(gif)]
        frames,bounds,centres,orbits,openness=[],[],[],[],[];first=0
        for decoded_index,duration in enumerate(durations):
            end=first+duration//delay
            if end<=first or end>count:raise ValueError(f'{name}: GIF clock differs from pose rig')
            frame_eyes,frame_bounds,frame_centres,frame_orbits,frame_open=[],[],[],[],[]
            for eye in range(2):
                mask=np.max([np.asarray(im)[:,:,0] for im in authored[eye,'mask'][first:end]],axis=0)
                maximum=int(mask.max())
                if maximum<90:mask[:]=0
                marker=register_marker(authored[eye,'marker'][first])
                if marker is None:center=np.array([WIDTH*.5,HEIGHT*.4]);orbit=np.zeros(4)
                else:center,orbit=marker
                x0,y0=round(center[0]-TILE_WIDTH*.5),round(center[1]-TILE_HEIGHT*.5)
                box=(x0,y0,x0+TILE_WIDTH,y0+TILE_HEIGHT)
                aperture=Image.fromarray(mask).convert('RGBA');aperture.putalpha(255)
                plate=authored[eye,'plate'][first].crop(box);plate.putalpha(255)
                iris=authored[eye,'iris'][first].crop(box)
                aperture=aperture.crop(box)
                if maximum>=250:
                    plate,iris=match_visible_material(plate,iris,aperture,decoded[decoded_index].crop(box))
                frame_eyes.append((plate,iris,aperture))
                frame_bounds.append([x0/WIDTH,y0/HEIGHT,TILE_WIDTH/WIDTH,TILE_HEIGHT/HEIGHT])
                frame_centres.append([round(float(center[0]/WIDTH),7),round(float(center[1]/HEIGHT),7)])
                frame_orbits.append([round(float(value),7) for value in orbit])
                frame_open.append(round(maximum/255,5) if maximum>=90 else 0.)
            frames.append(frame_eyes);bounds.append(frame_bounds);centres.append(frame_centres);orbits.append(frame_orbits);openness.append(frame_open);first=end
        if first!=count:raise ValueError(f'{name}: incomplete pose registration')
        atlas,rects,stride=pack(frames)
        destination=OUTPUT/f'{name}.png';atlas.save(destination,optimize=True)
        result['clips'][name]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                               'field_sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
                               'frames':len(frames),'rects':rects,'bounds':bounds,'centres':centres,'orbits':orbits,
                               'openness':openness,'stride':stride,'texture_size':list(atlas.size)}
    (OUTPUT/'manifest.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    print(json.dumps({'clips':len(result['clips']),'frames':sum(c['frames'] for c in result['clips'].values()),
                      'compressed_bytes':sum(p.stat().st_size for p in OUTPUT.glob('*.png')),
                      'largest_texture_bytes':max(math.prod(c['texture_size'])*4 for c in result['clips'].values())}))


if __name__=='__main__':build()
