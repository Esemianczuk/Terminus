"""Portable Qt RHI renderer. No keyboard hooks, native handles or render timer.

Qt Quick chooses Metal on macOS, D3D on Windows, and GLES/Vulkan where available.
The caller owns frame pacing. Only primitive geometry/uniforms change per tick;
sprite, eye guards and offline flow fields stay in resident immutable textures.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time

from PySide6 import QtCore, QtGui, QtQuick, QtQuickWidgets
from desktop.effects import screen_uniforms, unit

ROOT = Path(__file__).resolve().parents[1]
MAX_NODES=72
MAX_EDGES=320
MAX_DESKTOP_RECTS=8


def finite(value, default=0.0, limit=10000.0):
    try:
        result = float(value)
        return max(-limit, min(limit, result)) if math.isfinite(result) else default
    except (TypeError, ValueError, OverflowError):
        return default


def arm_outline(arm):
    """At most 114 points for three tapered arms; no raster work or readback."""
    left, right = [], []
    x0, y0, a, b, c, d, x1, y1 = [finite(arm.get(key)) for key in ("x0", "y0", "cx0", "cy0", "cx1", "cy1", "x1", "y1")]
    active = max(0.0, min(1.0, finite(arm.get("activation"))))
    for index in range(19):
        t = index / 18
        s = 1 - t
        x, y = s*s*s*x0 + 3*s*s*t*a + 3*s*t*t*c + t*t*t*x1, s*s*s*y0 + 3*s*s*t*b + 3*s*t*t*d + t*t*t*y1
        dx, dy = 3*s*s*(a-x0)+6*s*t*(c-a)+3*t*t*(x1-c), 3*s*s*(b-y0)+6*s*t*(d-b)+3*t*t*(y1-d)
        length = max(.001, math.hypot(dx, dy))
        half = s ** .85 * (7.5 + active * 1.5) + .7
        nx, ny = -dy / length * half, dx / length * half
        left.append((x+nx, y+ny)); right.append((x-nx, y-ny))
    points = left + right[::-1]
    return "M" + " L".join(f"{x:.3f},{y:.3f}" for x, y in points) + " Z"


def desktop_rectangles(rectangles):
    """Accept the observer's normalized width/height schema and legacy w/h."""
    result=[]
    for item in rectangles[:MAX_DESKTOP_RECTS]:
        if isinstance(item,dict):
            values=[item.get("x",0),item.get("y",0),item.get("width",item.get("w",0)),item.get("height",item.get("h",0))]
        elif isinstance(item,(tuple,list)) and len(item)>=4:
            values=item[:4]
        else:
            continue
        x,y,w,h=[max(0,min(1,finite(value))) for value in values]
        w,h=min(w,1-x),min(h,1-y)
        if w>0 and h>0:result.append({"x":x,"y":y,"w":w,"h":h})
    return result


class SceneRows(QtCore.QAbstractListModel):
    """Keep QML delegates alive while replacing only changed primitive data.

    Replacing a JS list resets a Repeater, destroying its Shapes and textures
    every frame. A fixed map role lets Qt retain those delegates and update
    bindings through dataChanged. Only actual topology changes insert/remove
    rows. There are no model resets, autonomous timers, or rendering callbacks.
    """
    EntryRole = int(QtCore.Qt.ItemDataRole.UserRole) + 1

    def __init__(self, maximum, parent=None):
        super().__init__(parent)
        self.maximum = maximum
        self.rows = []
        self.inserted = self.removed = self.changed = 0

    def roleNames(self):
        return {self.EntryRole: b"entry"}

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if role != self.EntryRole or not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        return dict(self.rows[index.row()])

    def update(self, entries):
        incoming = [dict(entry) for entry in entries[:self.maximum]]
        previous = len(self.rows)
        common = min(previous, len(incoming))
        changed = [row for row in range(common) if self.rows[row] != incoming[row]]
        if len(incoming) < previous:
            self.beginRemoveRows(QtCore.QModelIndex(), len(incoming), previous-1)
            del self.rows[len(incoming):]
            self.endRemoveRows()
            self.removed += previous-len(incoming)
        for row in changed:
            self.rows[row] = incoming[row]
        if len(incoming) > previous:
            self.beginInsertRows(QtCore.QModelIndex(), previous, len(incoming)-1)
            self.rows.extend(incoming[previous:])
            self.endInsertRows()
            self.inserted += len(incoming)-previous
        # Coalesce adjacent changes. The common case is one compact signal for
        # the moving graph, with no delegate construction or scene-tree churn.
        if changed:
            start = end = changed[0]
            for row in changed[1:]:
                if row == end+1:
                    end = row
                else:
                    self.dataChanged.emit(self.index(start,0), self.index(end,0), [self.EntryRole])
                    start = end = row
            self.dataChanged.emit(self.index(start,0), self.index(end,0), [self.EntryRole])
            self.changed += len(changed)
        return bool(changed or previous != len(incoming))


class PackedArtwork:
    """GPU playback metadata plus at most one CPU atlas for native hit testing."""
    def __init__(self,asset_root):
        self.asset_root=Path(asset_root)
        path=self.asset_root/"manifest.json"
        if path.stat().st_size>128*1024:raise ValueError("Oversized GPU atlas manifest")
        self.manifest=json.loads(path.read_text())
        if self.manifest.get("version")!=1 or self.manifest.get("canvas")!=[384,416]:
            raise ValueError("Unsupported GPU atlas")
        for name,entry in self.manifest["clips"].items():
            original=self.asset_root.parent/"clips"/f"{name}.gif"
            if original.is_file() and hashlib.sha256(original.read_bytes()).hexdigest()!=entry["sha256"]:
                raise ValueError("GPU atlas does not match the approved source footage")
        self._library=None
        self.cached_clip=None
        self._atlas=QtGui.QImage()
        self._frame=QtGui.QImage()
        self._frame_key=None

    def playback_library(self):
        from desktop.animation import ClipLibrary
        if self._library is None:
            self._library=ClipLibrary.from_gpu_metadata(self.asset_root.parent/"clips/manifest.json",self.manifest)
        return self._library

    def clear_hit_cache(self):
        self.cached_clip=None
        self._atlas=QtGui.QImage()
        self._frame=QtGui.QImage()
        self._frame_key=None

    @property
    def hit_cache_bytes(self):
        return self._atlas.sizeInBytes()+self._frame.sizeInBytes()

    def hit_frame(self,clip,index):
        """Read source alpha from disk, never the GPU or another window."""
        entry=self.manifest["clips"].get(clip)
        if entry is None or type(index) is not int or not 0<=index<entry["count"]:
            raise ValueError("Invalid hit-test frame")
        if self.cached_clip!=clip:
            self.clear_hit_cache()
            reader=QtGui.QImageReader(str(self.asset_root/f"{clip}-body.png"))
            size=reader.size()
            if (size.width()<=0 or size.height()<=0 or max(size.width(),size.height())>4096
                    or size.width()*size.height()*4>18*1024*1024):
                raise ValueError("Invalid bounded hit-test atlas")
            image=reader.read()
            if image.isNull():raise ValueError("Cannot read the hit-test atlas")
            self._atlas=image.convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            self.cached_clip=clip
        key=(clip,index)
        if key!=self._frame_key:
            x,y,w,h=entry["body_rects"][index]
            rect=QtCore.QRect(round(x*self._atlas.width()),round(y*self._atlas.height()),
                              round(w*self._atlas.width()),round(h*self._atlas.height()))
            if (rect.size()!=QtCore.QSize(*self.manifest["canvas"]) or not self._atlas.rect().contains(rect)):
                raise ValueError("Invalid hit-test atlas frame rectangle")
            self._frame=self._atlas.copy(rect)
            self._frame_key=key
        return self._frame


class GpuScene(QtQuickWidgets.QQuickWidget):
    """Transparent noninteractive child of the existing native presence widget."""
    def __init__(self, parent=None, *, asset_root=None):
        # Request transparency before QQuickWidget creates its internal window,
        # including the Metal path where an RGB-only default can turn it black.
        QtQuick.QQuickWindow.setDefaultAlphaBuffer(True)
        super().__init__(parent)
        self.asset_root = Path(asset_root or ROOT / "web/assets/gpu")
        self.available = False
        self.errors = []
        self.upload_ms = 0.0
        self.current_clip = None
        self.eye_texture_bytes = 0
        self.effect_state = {'ascii': 0., 'ink': 0., 'screen_confidence': 0.}
        self.frames_rendered = 0
        self.scene_graph_initialized = False
        self._properties = {}
        self._models = {"nodes": SceneRows(MAX_NODES,self), "edges": SceneRows(MAX_EDGES,self),
                        "tendrils": SceneRows(3,self), "glyphs": SceneRows(8,self)}
        self.manifest = {}
        self.artwork=None
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # QQuickWidget renders into an offscreen surface. The top-level window
        # is translucent, so its composited child must request alpha too.
        # WA_AlwaysStackOnTop is only for seeing sibling widgets underneath a
        # QQuickWidget; it breaks normal stacking for this single-scene panel.
        surface_format = self.format()
        surface_format.setAlphaBufferSize(8)
        self.setFormat(surface_format)
        self.setClearColor(QtGui.QColor(0, 0, 0, 0))
        self.setResizeMode(QtQuickWidgets.QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.quickWindow().sceneGraphError.connect(self._graphics_error)
        self.quickWindow().sceneGraphInitialized.connect(self._check_backend)
        self.quickWindow().afterRendering.connect(self._rendered)
        self.quickWindow().sceneGraphInvalidated.connect(self._invalidated)
        try:
            self.artwork=PackedArtwork(self.asset_root)
            self.manifest=self.artwork.manifest
            self.setSource(QtCore.QUrl.fromLocalFile(str(ROOT / "desktop/qml/CreatureScene.qml")))
            self.errors.extend(error.toString() for error in self.errors_qml())
            self.available = self.status() == self.Status.Ready and not self.errors
            if self.available:
                for key,model in self._models.items():
                    self.rootObject().setProperty(key,model)
                self.rootObject().rendererError.connect(lambda message:self._graphics_error(None,message))
                self._set("glowSourceUrl", QtCore.QUrl.fromLocalFile(str(self.asset_root / "glow.png")).toString())
                maximum=finite(self.manifest.get("max_flow_pixels"),64,64)
                self._set("flowRange",QtGui.QVector2D(maximum/384,maximum/416))
                self._check_backend()
        except (OSError, ValueError, TypeError) as exc:
            self.errors.append(str(exc))

    def errors_qml(self):
        return super().errors()

    def playback_library(self):
        if self.artwork is None:raise ValueError("GPU artwork is unavailable")
        return self.artwork.playback_library()

    def hit_frame(self,clip,index):
        if self.artwork is None:raise ValueError("GPU artwork is unavailable")
        return self.artwork.hit_frame(clip,index)

    def _graphics_error(self, error, message):
        self.errors.append(str(message))
        self.available = False
        self.hide()

    def _check_backend(self):
        backend = self.quickWindow().rendererInterface().graphicsApi()
        if backend in (QtQuick.QSGRendererInterface.GraphicsApi.Software,QtQuick.QSGRendererInterface.GraphicsApi.Null):
            self._graphics_error(None,"Qt RHI hardware rendering is unavailable")
        elif backend != QtQuick.QSGRendererInterface.GraphicsApi.Unknown:
            self.scene_graph_initialized = self.quickWindow().isSceneGraphInitialized()

    def _rendered(self):
        self.frames_rendered += 1
        self.scene_graph_initialized = True

    def _invalidated(self):
        self.scene_graph_initialized = False

    def _set(self, key, value):
        model = self._models.get(key)
        if model is not None:
            model.update(value)
            return
        if self._properties.get(key) != value:
            self.rootObject().setProperty(key, value)
            self._properties[key] = value

    def set_scene(self, *, clip, index, phase, body_rect, mirror=False, bank=0, pivot_offset=30,
                  clock=0, skin_weights=(.64,.20,.16,0), skin_intensity=.75, opacity=1,
                  graph_gain=2.8, nodes=(), edges=(), tendrils=(), glyphs=(), status=None,
                  morph_strength=1, body_visible=True, desktop_rects=(), cursor=None,
                  mic_active=False,skin_clock=None,gaze_atlas=None,gaze_shift=(0,0,0,0),
                  screen_field=None,effects=None):
        if not self.available:
            return False
        started = time.perf_counter()
        entry = self.manifest["clips"].get(clip)
        if not entry:
            return False
        index = max(0, min(int(index), entry["count"] - 1))
        following = (index+1) % entry["count"] if entry["loop"] else min(index+1,entry["count"]-1)
        gaze_entry=gaze_atlas.clips.get(clip) if gaze_atlas is not None else None
        gaze_ready=(gaze_entry is not None and any(max(pair)>0 for pair in gaze_entry['openness'])
                    and gaze_atlas.ensure_texture(clip))
        if clip != self.current_clip:
            if self.artwork.cached_clip!=clip:self.artwork.clear_hit_cache()
            for property_name, suffix in (("bodySourceUrl","body"),("forwardSourceUrl","forward"),("backwardSourceUrl","backward")):
                self._set(property_name, QtCore.QUrl.fromLocalFile(str(self.asset_root / f"{clip}-{suffix}.png")).toString())
            self.current_clip = clip
        source=gaze_atlas.path.parent/f"{clip}.png" if gaze_ready else self.asset_root/"glow.png"
        self._set("gazeSourceUrl",QtCore.QUrl.fromLocalFile(str(source)).toString())
        registered=gaze_atlas.clips[clip] if gaze_ready else None
        self.eye_texture_bytes=math.prod(registered['texture_size'])*4 if registered else 0
        self._set("gazeStride",registered['stride'] if registered else 0.)
        for prefix,frame_index in (("first",index),("second",following)):
            for eye,label in enumerate(("Left","Right")):
                rect=registered['rects'][frame_index][eye] if registered else (0.,0.,1.,1.)
                bounds=registered['bounds'][frame_index][eye] if registered else (-2.,-2.,.1,.1)
                self._set(prefix+label+"EyeRect",QtGui.QVector4D(*rect))
                self._set(prefix+label+"EyeBounds",QtGui.QVector4D(*bounds))
            shifts=gaze_atlas.displacements(clip,frame_index,gaze_shift) if registered else (0.,0.,0.,0.)
            self._set(prefix+"EyeShift",QtGui.QVector4D(shifts[0]/384,shifts[1]/416,shifts[2]/384,shifts[3]/416))
        for key, value in (("firstRect",entry["body_rects"][index]),("secondRect",entry["body_rects"][following]),
                           ("firstFlowRect",entry["flow_rects"][index]),("secondFlowRect",entry["flow_rects"][following]),
                           ("bodyRect",body_rect),("pigment",skin_weights)):
            self._set(key, QtGui.QVector4D(*(finite(x) for x in value)))
        for key, value in (("phase",max(0,min(1,finite(phase)))),("clock",finite(clock,limit=1e9)),
                           ("skinClock",finite(clock if skin_clock is None else skin_clock,limit=1e9)),
                           ("skinIntensity",max(0,min(1,finite(skin_intensity)))),("morphStrength",max(0,min(1,finite(morph_strength)))),
                           ("graphGain",max(0,min(4,finite(graph_gain)))),("bank",max(-16,min(16,finite(bank)))),
                           ("pivotOffset",finite(pivot_offset)),("opacity",max(0,min(1,finite(opacity)))),
                           ("mirror",bool(mirror)),("bodyVisible",bool(body_visible))):
            self._set(key,value)
        self._set("nodes",[dict(node, index=i) for i,node in enumerate(nodes[:MAX_NODES])])
        self._set("edges",list(edges[:MAX_EDGES]))
        self._set("tendrils",[dict(arm,outline=arm_outline(arm)) for arm in tendrils[:3]])
        self._set("glyphs",list(glyphs[:8]))
        self._set("statusLabel",status or {})
        self._set("desktopRects",desktop_rectangles(desktop_rects))
        if cursor is not None:
            if isinstance(cursor,dict):
                values = [cursor.get(key,0) for key in ("x","y","motion")]
            else:
                values = list(cursor)[:3]
            if len(values) == 3:
                self._set("cursorState",{key:max(0,min(1,finite(value))) for key,value in zip(("x","y","motion"),values)})
        else:
            self._set("cursorState",{})
        self._set("micActive",bool(mic_active))
        field = screen_uniforms(screen_field)
        effects = effects if isinstance(effects,dict) else {}
        for key,color in zip(('backgroundTL','backgroundTR','backgroundBL','backgroundBR'),field['colors']):
            self._set(key,QtGui.QVector4D(*color,1.))
        self._set('backgroundState',QtGui.QVector4D(field['confidence'],field['change'],*field['motion']))
        ascii_amount, ink = unit(effects.get('ascii')), unit(effects.get('ink'))
        if effects.get('reduced_motion'):
            ink = 0.
        self._set('displayEffects',QtGui.QVector4D(ascii_amount,ink,max(0.,min(10.,finite(effects.get('ink_phase')))),unit(effects.get('seed'),.37)))
        window_field = screen_field.get('windows',()) if isinstance(screen_field,dict) else ()
        rects = desktop_rectangles(window_field if isinstance(window_field,(list,tuple)) else ())
        for index in range(4):
            rect = rects[index] if index<len(rects) else {'x':-2.,'y':-2.,'w':0.,'h':0.}
            self._set('windowField'+str(index),QtGui.QVector4D(*(rect[k] for k in ('x','y','w','h'))))
        self.effect_state = {'ascii':round(ascii_amount,3),'ink':round(ink,3),'screen_confidence':round(field['confidence'],3)}
        self.upload_ms = (time.perf_counter()-started)*1000
        return True

    def diagnostics(self):
        backend = self.quickWindow().rendererInterface().graphicsApi()
        return {"backend":"qt6-rhi-scenegraph", "graphics_api":getattr(backend,"name",str(backend)),
                "available":self.available,"clip":self.current_clip,"submit_ms":round(self.upload_ms,3),
                "errors":list(self.errors),"runtime_texture_readbacks":0,"runtime_optical_flow":False,
                "scene_graph_initialized":self.scene_graph_initialized,"frames_rendered":self.frames_rendered,
                "maximum_clip_texture_bytes":max((c["texture_bytes"] for c in self.manifest.get("clips",{}).values()),default=0),
                "current_eye_texture_bytes":self.eye_texture_bytes,
                "effects":dict(self.effect_state),"effect_simulation_buffers":0,
                "metadata_playback":bool(self.artwork and self.artwork._library is not None),
                "playback_decoded_bytes":self.artwork._library.decoded_bytes if self.artwork and self.artwork._library else 0,
                "hit_cache_bytes":self.artwork.hit_cache_bytes if self.artwork else 0,
                "hit_cached_clip":self.artwork.cached_clip if self.artwork else None,
                "maximum_nodes":MAX_NODES,"maximum_edges":MAX_EDGES,
                "persistent_models":True,"model_resets":0,
                "model_rows":{key:model.rowCount() for key,model in self._models.items()},
                "model_insertions":sum(model.inserted for model in self._models.values()),
                "model_removals":sum(model.removed for model in self._models.values()),
                "input_handlers":0,"autonomous_timers":0}
