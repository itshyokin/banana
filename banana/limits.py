"""Per-BSP limit meters.

Counts are estimates taken from the evaluated meshes (before Tool splits
vertices by UVs/normals or cuts geometry at portals), recounted shortly after
you stop editing. Only objects that changed are recounted. The budgets are
editable per project and can be saved as your defaults.
"""

import json
import os
import time

import blf
import bpy
import numpy as np
from bpy.app.handlers import persistent
from bpy.props import FloatProperty, IntProperty
from mathutils import Vector

from . import bsp as bsp_mod
from .export import instance_key

# key, label, default budget
METERS = (
    ("tris", "Structure Triangles", 150000),
    ("verts", "Structure Vertices", 150000),
    ("instances", "Instance Placements", 2000),
    ("instance_defs", "Instance Definitions", 512),
    ("materials", "Materials", 128),
    ("portals", "Portals", 512),
    ("extent", "World Extent (WU)", 1000.0),
)
QUIET_SECONDS = 0.6


class BananaLimits(bpy.types.PropertyGroup):
    tris: IntProperty(name="Structure Triangles", default=150000, min=1)
    verts: IntProperty(name="Structure Vertices", default=150000, min=1)
    instances: IntProperty(name="Instance Placements", default=2000, min=1)
    instance_defs: IntProperty(name="Instance Definitions", default=512, min=1)
    materials: IntProperty(name="Materials", default=128, min=1)
    portals: IntProperty(name="Portals", default=512, min=1)
    extent: FloatProperty(name="World Extent (WU)", default=1000.0, min=1.0,
                          description="Largest distance from the origin along any axis, in Halo world units")


# ------------------------------------------------------------------ counting

_cache = {}      # object name -> (tris, verts, material names, world bbox corners)
_results = {}    # bsp name -> {meter key: value}
_dirty = set()
_state = {"last_change": 0.0, "timer": False, "all_dirty": True}


def _object_stats(obj, depsgraph):
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.data
    n_polys = len(mesh.polygons)
    loop_total = np.empty(n_polys, np.int32)
    mesh.polygons.foreach_get("loop_total", loop_total)
    tris = int(loop_total.sum() - 2 * n_polys) if n_polys else 0
    mats = tuple(s.material.name for s in eval_obj.material_slots if s.material)
    corners = [obj.matrix_world @ Vector(c) for c in eval_obj.bound_box]
    return tris, len(mesh.vertices), mats, corners


def _stats(obj, depsgraph):
    entry = _cache.get(obj.name)
    if entry is None:
        entry = _object_stats(obj, depsgraph)
        _cache[obj.name] = entry
    return entry


def count_bsp(context, bsp):
    depsgraph = context.evaluated_depsgraph_get()
    scale = context.scene.banana.scale()
    structure = bsp_mod.objects_for_role(bsp, 'STRUCTURE')
    instances = bsp_mod.objects_for_role(bsp, 'INSTANCES')
    design = bsp_mod.objects_for_role(bsp, 'DESIGN')
    portals = bsp_mod.objects_for_role(bsp, 'PORTALS')
    tris = verts = 0
    materials = set()
    extent = 0.0
    for obj in structure:
        t, v, mats, corners = _stats(obj, depsgraph)
        tris += t
        verts += v
        materials.update(mats)
        extent = max([extent] + [max(abs(c.x), abs(c.y), abs(c.z)) for c in corners])
    for obj in instances + design:
        _t, _v, mats, corners = _stats(obj, depsgraph)
        materials.update(mats)
        extent = max([extent] + [max(abs(c.x), abs(c.y), abs(c.z)) for c in corners])
    defs = len({instance_key(o) for o in instances})
    result = {
        "tris": tris, "verts": verts, "instances": len(instances), "instance_defs": defs,
        "materials": len(materials), "portals": len(portals),
        "extent": extent * scale / 100.0,
    }
    _results[bsp.name] = result
    return result


def recount(context, everything=False):
    if everything or _state["all_dirty"]:
        _cache.clear()
        _state["all_dirty"] = False
    else:
        for name in _dirty:
            _cache.pop(name, None)
    _dirty.clear()
    for bsp in bsp_mod.find_bsps(context.scene):
        count_bsp(context, bsp)


def results(bsp):
    return _results.get(bsp.name)


def _redraw():
    wm = bpy.context.window_manager
    for window in wm.windows if wm else []:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _timer():
    wait = QUIET_SECONDS - (time.time() - _state["last_change"])
    if wait > 0:
        return wait + 0.05
    _state["timer"] = False
    try:
        recount(bpy.context)
        _redraw()
    except Exception as err:  # never let a meter break editing
        print("Banana meters:", err)
    return None


def _schedule():
    _state["last_change"] = time.time()
    if not _state["timer"]:
        _state["timer"] = True
        bpy.app.timers.register(_timer, first_interval=QUIET_SECONDS)


@persistent
def _on_depsgraph(scene, depsgraph):
    settings = getattr(scene, "banana", None)
    if settings is None or not settings.live_meters:
        return
    changed = False
    for update in depsgraph.updates:
        idv = update.id
        if isinstance(idv, bpy.types.Object):
            _dirty.add(idv.original.name)
            changed = True
        elif isinstance(idv, (bpy.types.Mesh, bpy.types.Collection, bpy.types.Material)):
            _state["all_dirty"] = True
            changed = True
    if changed:
        _schedule()


@persistent
def _on_load(_dummy):
    _cache.clear()
    _results.clear()
    _state["all_dirty"] = True
    _schedule()


# ------------------------------------------------------------------ drawing

def draw_meters(layout, context, bsp):
    values = results(bsp)
    if values is None:
        layout.label(text="Counting...", icon='TIME')
        return
    limits = context.scene.banana_limits
    for key, label, _default in METERS:
        value, limit = values[key], getattr(limits, key)
        factor = value / limit if limit else 0.0
        row = layout.row()
        row.alert = factor > 1.0
        if key == "extent":
            text = "%s: %.0f / %.0f" % (label, value, limit)
        else:
            text = "%s: %s / %s" % (label, format(value, ","), format(limit, ","))
        if hasattr(row, "progress"):
            row.progress(factor=min(factor, 1.0), type='BAR', text=text)
        else:
            row.label(text="%s (%d%%)" % (text, factor * 100))


def _overlay():
    context = bpy.context
    scene = context.scene
    if scene is None or not scene.banana.meter_overlay or scene.banana.active_bsp is None:
        return
    bsp = scene.banana.active_bsp
    values = results(bsp)
    if values is None:
        return
    limits = scene.banana_limits
    font = 0
    size = int(12 * context.preferences.system.ui_scale)
    blf.size(font, size)
    x, y = 20, 60
    lines = []
    for key, label, _d in METERS:
        pct = values[key] / getattr(limits, key) * 100.0
        lines.append((("%s  %d%%" % (label, pct)), pct))
    lines.append(("Banana: %s" % bsp.name, 0.0))
    for text, pct in lines:
        if pct > 100:
            blf.color(font, 1.0, 0.3, 0.3, 1.0)
        elif pct > 90:
            blf.color(font, 1.0, 0.8, 0.2, 1.0)
        else:
            blf.color(font, 0.9, 0.9, 0.9, 0.9)
        blf.position(font, x, y, 0)
        blf.draw(font, text)
        y += size + 4


# ------------------------------------------------------------------ operators / panel

def _defaults_path():
    folder = bpy.utils.user_resource('CONFIG', path="banana", create=True)
    return os.path.join(folder, "limits.json")


class BANANA_OT_save_limits(bpy.types.Operator):
    """Save these budgets as your defaults for new projects"""
    bl_idname = "banana.save_limits"
    bl_label = "Save as My Defaults"

    def execute(self, context):
        lim = context.scene.banana_limits
        with open(_defaults_path(), "w", encoding="utf-8") as fh:
            json.dump({k: getattr(lim, k) for k, _l, _d in METERS}, fh, indent=1)
        self.report({'INFO'}, "Saved budgets")
        return {'FINISHED'}


class BANANA_OT_load_limits(bpy.types.Operator):
    """Load your saved default budgets into this project"""
    bl_idname = "banana.load_limits"
    bl_label = "Load My Defaults"

    def execute(self, context):
        try:
            with open(_defaults_path(), encoding="utf-8") as fh:
                data = json.load(fh)
        except OSError:
            self.report({'ERROR'}, "No saved defaults yet")
            return {'CANCELLED'}
        lim = context.scene.banana_limits
        for key, _l, _d in METERS:
            if key in data:
                setattr(lim, key, data[key])
        return {'FINISHED'}


class BANANA_OT_recount(bpy.types.Operator):
    """Recount every BSP's meters now"""
    bl_idname = "banana.recount"
    bl_label = "Recount"

    def execute(self, context):
        recount(context, everything=True)
        return {'FINISHED'}


class BANANA_PT_limits(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Banana"
    bl_label = "Limits"
    bl_parent_id = "BANANA_PT_bsps"

    def draw(self, context):
        s = context.scene.banana
        layout = self.layout
        row = layout.row(align=True)
        row.prop(s, "live_meters")
        row.prop(s, "meter_overlay", text="Overlay")
        row.operator("banana.recount", text="", icon='FILE_REFRESH')
        if s.active_bsp:
            draw_meters(layout.column(), context, s.active_bsp)


class BANANA_PT_limit_budgets(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Banana"
    bl_label = "Budgets"
    bl_parent_id = "BANANA_PT_limits"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        lim = context.scene.banana_limits
        col = self.layout.column(align=True)
        for key, _label, _d in METERS:
            col.prop(lim, key)
        row = self.layout.row(align=True)
        row.operator("banana.save_limits", icon='EXPORT')
        row.operator("banana.load_limits", icon='IMPORT')
        self.layout.label(text="Estimates: Tool's final counts can differ", icon='INFO')


CLASSES = (BananaLimits, BANANA_OT_save_limits, BANANA_OT_load_limits, BANANA_OT_recount,
           BANANA_PT_limits, BANANA_PT_limit_budgets)

_draw_handle = None


def register():
    global _draw_handle
    bpy.types.Scene.banana_limits = bpy.props.PointerProperty(type=BananaLimits)
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    bpy.app.handlers.load_post.append(_on_load)
    _draw_handle = bpy.types.SpaceView3D.draw_handler_add(_overlay, (), 'WINDOW', 'POST_PIXEL')
    _state["all_dirty"] = True


def unregister():
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    for lst, fn in ((bpy.app.handlers.depsgraph_update_post, _on_depsgraph), (bpy.app.handlers.load_post, _on_load)):
        if fn in lst:
            lst.remove(fn)
    if bpy.app.timers.is_registered(_timer):
        bpy.app.timers.unregister(_timer)
    _state["timer"] = False
    del bpy.types.Scene.banana_limits
