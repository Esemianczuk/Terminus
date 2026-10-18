"""Source-pose eye layers, authored once and transported by the animation rig.

All coordinates below are source pixels, independently of the runtime scale.
A small source annotation is preferable to a trained segmenter here: the four
approved open poses are immutable, and every animation frame has a known rig.
Only sclera that was hidden by the iris is reconstructed. The visible iris
and plate are alpha-matted back to the approved PNG; catchlight pixels retain
their exact original RGB. Hidden pigment extends from the existing iris.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

# A tight interior boundary follows the underside of the upper lid and the
# inside of the lower dark rim. The fitted iris ellipse uses its visible lower
# contour; its hidden upper half is completed conservatively in dark pigment.
# (aperture polygon, iris centre, ellipse diameters, OpenCV angle degrees)
EYES = {
    "refined": (
        ([(493,565),(518,560),(545,553),(574,547),(603,542),(629,538),(643,538),(651,541),
          (650,547),(641,558),(629,568),(613,578),(591,586),(568,590),(545,588),(524,582),(507,575)],
         (584.82,536.64),(95.23,102.93),170.61),
        ([(805,492),(824,483),(847,476),(873,470),(896,466),(903,468),(901,474),(893,490),
          (881,505),(862,516),(840,521),(820,519),(808,513),(804,501)],
         (837.13,478.41),(62.14,87.35),18.99),
    ),
    "flight": (
        ([(690,565),(720,557),(750,550),(780,544),(810,538),(832,536),(844,539),(848,545),
          (840,554),(826,567),(809,578),(788,585),(763,589),(739,587),(718,581),(701,573)],
         (777.79,549.26),(72.05,97.05),83.99),
        ([(977,497),(992,488),(1015,479),(1036,471),(1055,467),(1066,465),(1070,468),
          (1067,481),(1056,500),(1038,513),(1019,519),(1000,518),(986,511),(979,501)],
         (1016.42,480.12),(56.06,77.76),12.47),
    ),
    "typing": (
        ([(495,582),(519,577),(547,570),(576,564),(605,560),(631,555),(645,556),(652,560),
          (650,567),(640,580),(624,592),(606,601),(583,606),(560,608),(538,603),(517,595),(502,587)],
         (585.50,554.80),(95.50,104.0),170.61),
        ([(805,512),(824,503),(847,497),(873,490),(897,487),(906,486),(904,495),(896,512),
          (883,526),(864,538),(841,541),(821,540),(808,533),(804,520)],
         (837.60,498.50),(62.8,87.8),18.99),
    ),
    "stretch": (
        ([(551,691),(578,681),(608,672),(638,664),(667,656),(686,653),(695,660),(697,666),
          (692,676),(678,688),(655,700),(632,707),(606,711),(581,710),(565,703)],
         (615.98,673.24),(60.83,82.23),56.62),
        ([(791,611),(809,601),(831,592),(854,582),(878,575),(896,573),(902,575),(901,581),
          (894,597),(881,611),(864,621),(844,627),(826,628),(808,622),(798,611)],
         (833.78,581.68),(56.64,83.08),17.33),
    ),
}


def _aperture(size, polygon):
    width, height = size
    # Supersample only the small ROI, keeping the offline build light.
    vertices = np.asarray(polygon, np.float32)
    low = np.floor(vertices.min(axis=0)-2).astype(int)
    high = np.ceil(vertices.max(axis=0)+3).astype(int)
    scale = 4
    small = np.zeros(((high[1]-low[1])*scale,(high[0]-low[0])*scale),np.uint8)
    cv2.fillPoly(small,[np.rint((vertices-low)*scale).astype(np.int32)],255)
    matte = np.zeros((height,width),np.uint8)
    matte[low[1]:high[1],low[0]:high[0]] = cv2.resize(small,tuple(high-low),interpolation=cv2.INTER_AREA)
    return matte


def _ellipse(size, centre, diameters, angle):
    width,height = size
    yy,xx = np.mgrid[:height,:width].astype(np.float32)
    theta = np.deg2rad(angle)
    x,y = xx-centre[0],yy-centre[1]
    u,v = x*np.cos(theta)+y*np.sin(theta),-x*np.sin(theta)+y*np.cos(theta)
    radii = np.asarray(diameters,np.float32)*.5
    rho = np.sqrt((u/radii[0])**2+(v/radii[1])**2)
    # One source-pixel feather, less than a third of a runtime pixel.
    return np.clip((1-rho)*min(radii)+.5,0,1)


def _visible_iris(rgb, aperture, ellipse):
    values = rgb.astype(np.float32)
    chroma = np.maximum(values[:,:,1],values[:,:,2])-values[:,:,0]
    dark = (values.max(axis=2)<25)|((values.max(axis=2)<62)&(values[:,:,0]<=values[:,:,1]+3))
    candidate = ((chroma>9)|dark)&(aperture>.7)&(ellipse>.02)
    # The painted white specular is a hole inside the colored iris. Filling
    # external contours retains its original RGB rather than coloring it.
    contours,_ = cv2.findContours(candidate.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    mask=np.zeros(aperture.shape,np.uint8)
    if contours:
        cv2.drawContours(mask,[max(contours,key=cv2.contourArea)],-1,255,cv2.FILLED)
    mask=cv2.dilate(mask,np.ones((3,3),np.uint8))
    mask=cv2.GaussianBlur(mask,(0,0),.35)
    return mask.astype(np.float32)/255.


def _sclera(rgb, aperture, iris):
    """Continue existing shaded sclera across the hidden central area."""
    plate=rgb.copy().astype(np.float32)
    known=(aperture>.7)&(iris<.03)
    # Keep away from the dark iris edge and the fixed lid rim.
    known &= cv2.erode((1-(iris>.03)).astype(np.uint8),np.ones((17,17),np.uint8)).astype(bool)
    known &= cv2.erode((aperture>.7).astype(np.uint8),np.ones((3,3),np.uint8)).astype(bool)
    rows=np.flatnonzero(known.any(axis=1))
    ys,xs=np.nonzero(aperture>.001)
    if not len(rows):
        raise ValueError('Eye aperture contains no clean source sclera')
    row_colours={}
    for y in rows:
        xx=np.flatnonzero(known[y])
        # Median samples immediately beside the iris retain the painted
        # vertical gray/pink shadow and cream lower-eye light.
        gap=np.flatnonzero(np.diff(xx)>1)
        split=int(gap[np.argmax(np.diff(xx)[gap])]+1) if len(gap) else len(xx)
        left,right=xx[:split],xx[split:]
        if len(right):
            lx,rx=float(np.median(left[-5:])),float(np.median(right[:5]))
            lc,rc=np.median(rgb[y,left[-5:]],axis=0),np.median(rgb[y,right[:5]],axis=0)
        else:
            lx=rx=float(np.median(xx));lc=rc=np.median(rgb[y,xx],axis=0)
        row_colours[y]=(lx,rx,lc,rc)
    for y in range(int(ys.min()),int(ys.max())+1):
        lower=rows[rows<=y];upper=rows[rows>=y]
        ya=int(lower[-1]) if len(lower) else int(rows[0]);yb=int(upper[0]) if len(upper) else int(rows[-1])
        def color_line(row):
            lx,rx,lc,rc=row_colours[row]
            weight=np.clip((np.arange(rgb.shape[1])-lx)/max(1.,rx-lx),0,1)[:,None]
            return lc[None,:]*(1-weight)+rc[None,:]*weight
        w=(y-ya)/max(1,yb-ya)
        fill=color_line(ya)*(1-w)+color_line(yb)*w
        region=(iris[y]>.001)&(aperture[y]>.001)
        plate[y,region]=fill[region]
    # Solve a small harmonic extension from the existing sclera. Keeping the
    # boundary fixed removes scan-line bands without importing teal lid pixels.
    x0,x1=int(xs.min()),int(xs.max())+1;y0,y1=int(ys.min()),int(ys.max())+1
    patch=plate[y0:y1,x0:x1].copy()
    unknown=(iris[y0:y1,x0:x1]>.001)&(aperture[y0:y1,x0:x1]>.001)
    for _ in range(600):
        average=cv2.blur(patch,(3,3),borderType=cv2.BORDER_REPLICATE)
        change=float(np.max(np.abs(average[unknown]-patch[unknown])))
        patch[unknown]=average[unknown]
        if change<.02:break
    plate[y0:y1,x0:x1]=patch
    return np.rint(plate).clip(0,255).astype(np.uint8)



@lru_cache(maxsize=6)
def source_layers(name):
    """Return two source-resolution straight-alpha eye layers, or [] if closed.

    Keys: aperture (uint8 HxW), iris (uint8 HxWx4), plate (uint8 HxWx3),
    centre/radii (normalized source coordinates), angle (degrees). Returned
    arrays are cached authoring data and callers must not mutate them.
    """
    if name in {'sleep','yawn'}:
        return []
    if name not in EYES:
        raise ValueError(f'Open source pose {name!r} needs eye annotations')
    image=Image.open(ROOT/'web/assets'/f'terminus-{name}.png').convert('RGBA')
    rgb=np.asarray(image)[:,:,:3]
    layers=[]
    for polygon,centre,diameters,angle in EYES[name]:
        aperture=_aperture(image.size,polygon)
        ap=aperture.astype(np.float32)/255.
        ellipse=_ellipse(image.size,centre,diameters,angle)
        guide=_ellipse(image.size,centre,(diameters[0]+6,diameters[1]+6),angle)
        visible=_visible_iris(rgb,ap,guide)
        # Complete the occluded cap as one convex silhouette. The source
        # aperture must not leave a stepped notch in the movable iris.
        alpha=ellipse*(1-ap)+visible*ap
        points=cv2.findNonZero((alpha>.5).astype(np.uint8))
        silhouette=np.zeros(alpha.shape,np.uint8)
        cv2.fillConvexPoly(silhouette,cv2.convexHull(points),255)
        alpha=cv2.GaussianBlur(silhouette,(0,0),.65).astype(np.float32)/255.
        pigment=(visible>.7)&(ap>.9)&~np.all(rgb>170,axis=2)
        # Complete hidden pixels from nearest real pigment without ever using
        # the white catchlight as a synthesis seed. Restore visible texture
        # after smoothing so the cap has no old-lid-shaped flat-color seam.
        _,labels=cv2.distanceTransformWithLabels((~pigment).astype(np.uint8),cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_PIXEL)
        seeds=rgb[pigment]
        iris_rgb=seeds[np.maximum(0,labels-1)].astype(np.float32)
        iris_rgb=cv2.GaussianBlur(iris_rgb,(0,0),3.)
        texture=visible*ap
        iris_rgb=iris_rgb*(1-texture[:,:,None])+rgb*texture[:,:,None]

        plate=_sclera(rgb,ap,alpha)
        original=rgb.astype(np.float32)/255.
        background=plate.astype(np.float32)/255.
        # Exact alpha matting in the visible aperture. A geometric mask alone
        # leaves a stationary fringe when its feather meets the limbus. Solve
        # the smallest valid foreground coverage against the shaded plate,
        # then raise it to the geometric silhouette and quantize upward.
        amin=np.where(original<background,
                      1-original/np.maximum(background,1e-6),
                      (original-background)/np.maximum(1-background,1e-6)).max(axis=2)
        covered=np.maximum(alpha,np.clip(amin,0,1))
        alpha=alpha*(1-ap)+covered*ap
        alpha_u8=np.ceil(np.clip(alpha,0,1)*255).astype(np.uint8)
        alpha=alpha_u8.astype(np.float32)/255.
        foreground=np.clip((original-(1-alpha[:,:,None])*background)/np.maximum(alpha[:,:,None],1e-6),0,1)
        iris_rgb=iris_rgb*(1-ap[:,:,None])+foreground*255*ap[:,:,None]
        iris=np.dstack([np.rint(iris_rgb).clip(0,255).astype(np.uint8),alpha_u8])
        layer={'aperture':aperture,'iris':iris,'plate':plate,
               'centre':(centre[0]/image.width,centre[1]/image.height),
               'radii':(diameters[0]/2/image.width,diameters[1]/2/image.height),'angle':angle}
        for value in (aperture,iris,plate):value.flags.writeable=False
        layers.append(layer)
    return layers


def source_preview(name, dx, dy):
    """Proof of the same neutral-exact delta composition used at runtime."""
    image=np.asarray(Image.open(ROOT/'web/assets'/f'terminus-{name}.png').convert('RGBA')).copy()
    output=image[:,:,:3].astype(np.float32)/255.
    for layer in source_layers(name):
        iris=layer['iris'].astype(np.float32)/255.
        premul=iris.copy();premul[:,:,:3]*=iris[:,:,3:4]
        moved=cv2.warpAffine(premul,np.float32([[1,0,dx],[0,1,dy]]),(image.shape[1],image.shape[0]),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
        plate=layer['plate'].astype(np.float32)/255.
        delta=(moved[:,:,:3]-plate*moved[:,:,3:4])-(premul[:,:,:3]-plate*premul[:,:,3:4])
        output+=layer['aperture'][:,:,None].astype(np.float32)/255.*delta
    image[:,:,:3]=np.rint(output*255).clip(0,255).astype(np.uint8)
    return Image.fromarray(image)


def _proof(path):
    from PIL import ImageDraw
    canvas=Image.new('RGB',(1800,340*len(EYES)),'#16212b')
    labels=[(-12,-6),(0,0),(12,6)]
    for row,name in enumerate(EYES):
        source_layers(name)
        polygon=np.array([p for eye in EYES[name] for p in eye[0]])
        l,t=polygon.min(axis=0)-[24,40];r,b=polygon.max(axis=0)+[24,35]
        for col,(dx,dy) in enumerate(labels):
            im=source_preview(name,dx,dy)
            crop=im.crop((int(l),int(t),int(r),int(b))).convert('RGB');crop.thumbnail((590,300))
            canvas.paste(crop,(col*600,row*340+30))
            ImageDraw.Draw(canvas).text((col*600+5,row*340+5),f'{name} gaze ({dx}, {dy})',fill='white')
        # Source zero-gaze identity is a hard authoring invariant.
        assert np.array_equal(np.asarray(source_preview(name,0,0)),np.asarray(Image.open(ROOT/'web/assets'/f'terminus-{name}.png').convert('RGBA')))
    canvas.save(path)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--proof',default='/tmp/terminus-eye-layers.png')
    args=parser.parse_args();_proof(args.proof);print(args.proof)
