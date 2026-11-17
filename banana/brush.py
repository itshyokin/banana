"""The Banana terrain brush: a viewport brush that only touches terrain.

HEIGHT mode: Set Height. Every vertex under the brush moves toward the target
height (Strength = how far per dab, soft falloff to the edge of the circle).
Ctrl+click samples the height under the cursor. Terrain borders are locked
(with a soft falloff) so seams and sky shells stay sealed.

BLEND mode: paints the active BSP's blend layers. Paint makes the chosen layer
show (layers above it fade out, so painting layer 1 brings the base back);
Blur softens the transitions between layers. Opacity sets how strong each dab is.

Keys while the brush is active: LMB paint, Ctrl+LMB (height) sample height,
[ / ] radius, Ctrl+Z undo last stroke (blend), Right-click / Esc to finish.
Middle mouse, wheel and numpad still move the view.
"""

import math

import bmesh
import bpy
import gpu
import numpy as np
from bpy.props import EnumProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from . import blendmap, bsp as bsp_mod, terrain

NAV_EVENTS = {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM', 'MOUSEROTATE'}


# ------------------------------------------------------------------ math (no UI, unit tested)

def falloff(u):
    """1 at the center, 0 at the edge, smooth both ends."""
    u = np.clip(u, 0.0, 1.0)
    return (1.0 - u * u) ** 2


def border_mask(mesh, rings=2):
    """1.0 on border vertices, fading to 0 over `rings` rings of neighbors."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    mask = np.zeros(len(bm.verts), np.float32)
    front = {v for e in bm.edges if len(e.link_faces) == 1 for v in e.verts}
    seen = set(front)
    for v in front:
        mask[v.index] = 1.0
    for ring in range(1, rings + 1):
        value = 1.0 - ring / (rings + 1.0)
        nxt = set()
        for v in front:
            for e in v.link_edges:
                o = e.other_vert(v)
                if o not in seen:
                    seen.add(o)
                    nxt.add(o)
                    mask[o.index] = value
        front = nxt
    bm.free()
    return mask


def height_dab(obj, center, radius, target, strength, mask=None):
    """Move vertices within `radius` (XY) of `center` toward world height `target`."""
    mesh = obj.data
    n = len(mesh.vertices)
    co = np.empty(n * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    m = np.array(obj.matrix_world)
    world = co @ m[:3, :3].T + m[:3, 3]
    d = np.hypot(world[:, 0] - center[0], world[:, 1] - center[1])
    sel = d < radius
    if not sel.any():
        return False
    w = strength * falloff(d[sel] / radius)
    if mask is not None:
        w = w * (1.0 - mask[sel])
    world[sel, 2] += (target - world[sel, 2]) * w
    inv = np.linalg.inv(m)
    local = world @ inv[:3, :3].T + inv[:3, 3]
    mesh.vertices.foreach_set("co", local.astype(np.float32).ravel())
    mesh.update()
    return True


def _box_blur(a, k):
    """Separable box blur with edge clamping."""
    if k < 1:
        return a.copy()
    pad = np.pad(a, k, mode='edge')
    c = np.cumsum(np.cumsum(pad, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    s = 2 * k + 1
    total = c[s:, s:] - c[:-s, s:] - c[s:, :-s] + c[:-s, :-s]
    return total / (s * s)


def blend_dab(layers, cx, cy, rad_px, layer, mode, opacity):
    """layers: {2: HxW, 3: HxW, 4: HxW} float arrays (edited in place).
    cx, cy in pixels. Returns the touched (y0, y1, x0, x1) box or None."""
    h, w = layers[2].shape
    r = max(rad_px, 0.5)
    x0, x1 = max(int(cx - r), 0), min(int(cx + r) + 2, w)
    y0, y1 = max(int(cy - r), 0), min(int(cy + r) + 2, h)
    if x0 >= x1 or y0 >= y1:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    a = opacity * falloff(np.hypot(xx + 0.5 - cx, yy + 0.5 - cy) / r)
    if mode == 'PAINT':
        if layer >= 2:
            region = layers[layer][y0:y1, x0:x1]
            region += (1.0 - region) * a
        for upper in range(max(layer + 1, 2), 5):
            region = layers[upper][y0:y1, x0:x1]
            region -= region * a
    else:  # BLUR
        k = max(1, int(r / 4))
        by0, by1 = max(y0 - k, 0), min(y1 + k, h)
        bx0, bx1 = max(x0 - k, 0), min(x1 + k, w)
        for n in (2, 3, 4):
            big = layers[n][by0:by1, bx0:bx1]
            blurred = _box_blur(big, k)[y0 - by0:y1 - by0, x0 - bx0:x1 - bx0]
            region = layers[n][y0:y1, x0:x1]
            region += (blurred - region) * a
    return (y0, y1, x0, x1)


def read_layers(bsp):
    out, images = {}, {}
    for n in (2, 3, 4):
        img = bpy.data.images.get(blendmap.layer_image_name(bsp, n))
        w, h = img.size
        px = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(px)
        out[n] = px.reshape(h, w, 4)[:, :, 0].copy()
        images[n] = img
    return out, images


def write_layers(layers, images, which=(2, 3, 4)):
    for n in which:
        g = np.clip(layers[n], 0.0, 1.0)
        rgba = np.empty(g.shape + (4,), np.float32)
        rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = g
        rgba[..., 3] = 1.0
        images[n].pixels.foreach_set(rgba.ravel())
        images[n].update()


# ------------------------------------------------------------------ modal operator

def _circle_points(center, radius, z, segments=48):
    return [(center[0] + radius * math.cos(2 * math.pi * i / segments),
             center[1] + radius * math.sin(2 * math.pi * i / segments), z) for i in range(segments + 1)]


def _draw_cursor(op, _context):
    if op.hit is None:
        return
    try:
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    except Exception:
        shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
    pts = _circle_points(op.hit, op.radius, op.hit[2] + 0.02)
    batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": pts})
    gpu.state.line_width_set(2.0)
    gpu.state.depth_test_set('NONE')
    shader.bind()
    color = (1.0, 0.8, 0.15, 1.0) if op.mode == 'HEIGHT' else (0.3, 0.8, 1.0, 1.0)
    shader.uniform_float("color", color)
    batch.draw(shader)
    if op.mode == 'HEIGHT':  # small ring at the target height
        ring = _circle_points(op.hit, op.radius * 0.15, op.target_height)
        batch_for_shader(shader, 'LINE_STRIP', {"pos": ring}).draw(shader)
    gpu.state.line_width_set(1.0)


class BANANA_OT_terrain_brush(bpy.types.Operator):
    """Paint terrain: Set Height or blend layers. Right-click or Esc when done"""
    bl_idname = "banana.terrain_brush"
    bl_label = "Terrain Brush"
    bl_options = {'REGISTER'}

    mode: EnumProperty(items=(('HEIGHT', "Set Height", ""), ('BLEND', "Blend", "")), default='HEIGHT')

    # ---- helpers
    def _raycast(self, context, event):
        region, rv3d = context.region, context.region_data
        coord = (event.mouse_region_x, event.mouse_region_y)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        best = None
        for obj in self.objects:
            inv = obj.matrix_world.inverted()
            o_local = inv @ origin
            d_local = (inv.to_3x3() @ direction).normalized()
            ok, loc, _n, _i = obj.ray_cast(o_local, d_local)
            if ok:
                world = obj.matrix_world @ loc
                dist = (world - origin).length
                if best is None or dist < best[0]:
                    best = (dist, world, obj)
        return (best[1], best[2]) if best else (None, None)

    def _header(self, context):
        s = context.scene.banana
        if self.mode == 'HEIGHT':
            text = "Set Height %.2f m · radius %.1f · strength %.2f   LMB paint · Ctrl+LMB pick height · [ ] radius · RMB/Esc done" % (
                self.target_height, self.radius, s.brush_strength)
        else:
            what = "Blur" if s.blend_mode == 'BLUR' else "Paint layer %s" % s.blend_layer
            text = "%s · radius %.1f · opacity %.2f   LMB paint · [ ] radius · Ctrl+Z undo stroke · RMB/Esc done" % (
                what, self.radius, s.blend_opacity)
        context.area.header_text_set(text)

    def _dab(self, context, point):
        s = context.scene.banana
        if self.mode == 'HEIGHT':
            for obj in self.objects:
                height_dab(obj, point, self.radius, self.target_height, s.brush_strength, self.masks.get(obj.name))
        else:
            b = self.bsp.banana
            (x0, y0), (x1, y1) = b.blend_min, b.blend_max
            h, w = self.layers[2].shape
            cx = (point[0] - x0) / ((x1 - x0) or 1.0) * w
            cy = (point[1] - y0) / ((y1 - y0) or 1.0) * h
            rad_px = self.radius / ((x1 - x0) or 1.0) * w
            if blend_dab(self.layers, cx, cy, rad_px, int(s.blend_layer), s.blend_mode, s.blend_opacity):
                write_layers(self.layers, self.images)
        self.last_dab = point.copy()

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    # ---- lifecycle
    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'ERROR'}, "Start the brush from the 3D View's sidebar")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        s = context.scene.banana
        self.radius = s.brush_radius
        self.target_height = s.brush_height
        self.hit = None
        self.painting = False
        self.last_dab = None
        self.undo = []
        if self.mode == 'HEIGHT':
            self.objects = [obj for _b, obj in terrain.all_terrain(context.scene)]
            for bsp in bsp_mod.find_bsps(context.scene):
                for obj in blendmap.terrain_objects(bsp):
                    if obj not in self.objects:
                        self.objects.append(obj)
            self.masks = {o.name: border_mask(o.data, s.border_rings) for o in self.objects} if s.lock_borders else {}
        else:
            self.bsp = s.active_bsp
            if self.bsp is None:
                self.report({'ERROR'}, "Pick a BSP")
                return {'CANCELLED'}
            if not self.bsp.banana.blend_set or bpy.data.images.get(blendmap.layer_image_name(self.bsp, 2)) is None:
                blendmap.setup(self.bsp)
            self.objects = blendmap.terrain_objects(self.bsp)
            self.layers, self.images = read_layers(self.bsp)
        if not self.objects:
            self.report({'ERROR'}, "No terrain to paint")
            return {'CANCELLED'}
        self._handle = bpy.types.SpaceView3D.draw_handler_add(_draw_cursor, (self, context), 'WINDOW', 'POST_VIEW')
        context.window_manager.modal_handler_add(self)
        self._header(context)
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        if getattr(self, "_handle", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        if context.area is not None:
            context.area.header_text_set(None)
        s = context.scene.banana
        s.brush_radius = self.radius
        context.area.tag_redraw()
        if self.mode == 'HEIGHT':
            top = max((max((o.matrix_world @ Vector(c)).z for c in o.bound_box) for o in self.objects), default=0.0)
            if top > s.sky_height - 1.0:
                self.report({'WARNING'}, "Terrain now reaches the sky (%.1f m); press Rebuild All Skies" % top)

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except Exception as err:
            self._finish(context)
            self.report({'ERROR'}, "Terrain brush stopped: %s" % err)
            return {'CANCELLED'}

    def _modal(self, context, event):
        context.area.tag_redraw()
        s = context.scene.banana
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._finish(context)
            return {'FINISHED'}
        if event.type in NAV_EVENTS or event.type.startswith('NDOF') or event.type.startswith('NUMPAD'):
            return {'PASS_THROUGH'}
        if event.type in {'LEFT_BRACKET', 'RIGHT_BRACKET'} and event.value == 'PRESS':
            self.radius *= 0.85 if event.type == 'LEFT_BRACKET' else 1.0 / 0.85
            self._header(context)
            return {'RUNNING_MODAL'}
        if event.type == 'Z' and event.ctrl and event.value == 'PRESS' and self.mode == 'BLEND':
            if self.undo:
                for n, arr in self.undo.pop().items():
                    self.layers[n][:] = arr
                write_layers(self.layers, self.images)
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            point, _obj = self._raycast(context, event)
            self.hit = point
            if self.painting and point is not None:
                if self.last_dab is None or (point - self.last_dab).length > self.radius * 0.15:
                    self._dab(context, point)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                point, _obj = self._raycast(context, event)
                if point is None:
                    return {'RUNNING_MODAL'}
                if self.mode == 'HEIGHT' and event.ctrl:
                    self.target_height = s.brush_height = point.z
                    self._header(context)
                    return {'RUNNING_MODAL'}
                if self.mode == 'HEIGHT':
                    self.target_height = s.brush_height  # pick up edits made in the panel
                else:
                    self.undo.append({n: a.copy() for n, a in self.layers.items()})
                    del self.undo[:-5]
                self.painting = True
                self._dab(context, point)
            elif event.value == 'RELEASE' and self.painting:
                self.painting = False
                self.last_dab = None
                if self.mode == 'HEIGHT':
                    try:
                        bpy.ops.ed.undo_push(message="Banana Set Height")
                    except Exception:
                        pass  # undo is a nicety; never break the stroke over it
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}


CLASSES = (BANANA_OT_terrain_brush,)
