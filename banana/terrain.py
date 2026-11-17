"""Terrain tiles and the height brush.

- New Terrain Tile: a flat grid in the active BSP's structure, optionally placed
  against another tile so the shared border matches vertex for vertex (and copies
  that border's heights).
- Height brush: Blender's sculpt brushes, but X and Y are locked so only height
  changes, and every terrain border is masked so seams and the sky shell stay
  sealed. Done Sculpting puts your sculpt settings back.
- Match Borders: makes heights identical wherever two BSPs' terrain borders share
  a vertex position.
"""

import bpy
import bmesh
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from mathutils import Vector

from . import bsp as bsp_mod

TILE_KEY = "banana_tile"   # {"size_x", "size_y", "spacing"}
MASK_ATTR = ".sculpt_mask"


def is_terrain(obj):
    return obj.type == 'MESH' and obj.get(TILE_KEY) is not None


def all_terrain(scene):
    out = []
    for bsp in bsp_mod.find_bsps(scene):
        for obj in bsp_mod.objects_for_role(bsp, 'STRUCTURE'):
            if is_terrain(obj):
                out.append((bsp, obj))
    return out


def _key(x, y):
    return (round(x, 4), round(y, 4))


# ------------------------------------------------------------------ tiles

def make_tile(name, size_x, size_y, spacing, location, material=None):
    nx = max(1, int(round(size_x / spacing)))
    ny = max(1, int(round(size_y / spacing)))
    xs = np.linspace(-size_x / 2.0, size_x / 2.0, nx + 1)
    ys = np.linspace(-size_y / 2.0, size_y / 2.0, ny + 1)
    verts = [(x, y, 0.0) for y in ys for x in xs]
    faces = []
    for j in range(ny):
        for i in range(nx):
            a = j * (nx + 1) + i
            faces.append((a, a + 1, a + nx + 2, a + nx + 1))  # counter-clockwise from above: normals up
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    if material:
        mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj[TILE_KEY] = {"size_x": size_x, "size_y": size_y, "spacing": spacing}
    return obj


def copy_border_heights(obj, neighbor):
    """Give obj's border vertices the heights of neighbor's vertices at the same XY."""
    nmw = neighbor.matrix_world
    heights = {}
    for v in neighbor.data.vertices:
        w = nmw @ v.co
        heights[_key(w.x, w.y)] = w.z
    mw, inv = obj.matrix_world, obj.matrix_world.inverted()
    count = 0
    for v in obj.data.vertices:
        w = mw @ v.co
        z = heights.get(_key(w.x, w.y))
        if z is not None:
            v.co = inv @ Vector((w.x, w.y, z))
            count += 1
    obj.data.update()
    return count


SIDES = (('+X', "East (+X)", ""), ('-X', "West (-X)", ""), ('+Y', "North (+Y)", ""), ('-Y', "South (-Y)", ""))


class BANANA_OT_new_tile(bpy.types.Operator):
    """Add a flat terrain tile to the active BSP; next to the selected tile, its shared border matches exactly"""
    bl_idname = "banana.new_tile"
    bl_label = "New Terrain Tile"
    bl_options = {'REGISTER', 'UNDO'}

    size_x: FloatProperty(name="Size X", default=100.0, min=1.0, subtype='DISTANCE')
    size_y: FloatProperty(name="Size Y", default=100.0, min=1.0, subtype='DISTANCE')
    spacing: FloatProperty(name="Vertex Spacing", default=2.0, min=0.05, subtype='DISTANCE')
    next_to_selected: BoolProperty(name="Next to Selected Tile", default=True)
    side: EnumProperty(name="Side", items=SIDES, default='+X')

    def invoke(self, context, event):
        active = context.active_object
        if active is not None and is_terrain(active):
            info = active[TILE_KEY]
            self.size_x, self.size_y, self.spacing = info["size_x"], info["size_y"], info["spacing"]
        else:
            self.next_to_selected = False
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        bsp = context.scene.banana.active_bsp
        if bsp is None:
            self.report({'ERROR'}, "Pick or create a BSP first")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        neighbor = context.active_object if self.next_to_selected else None
        if neighbor is not None and not is_terrain(neighbor):
            self.report({'ERROR'}, "Select a terrain tile to place the new one next to, or untick Next to Selected Tile")
            return {'CANCELLED'}
        location = Vector((0.0, 0.0, 0.0))
        if neighbor is not None:
            info = neighbor[TILE_KEY]
            location = neighbor.matrix_world.translation.copy()
            location.z = neighbor.matrix_world.translation.z
            if self.side in ('+X', '-X'):
                if abs(self.size_y - info["size_y"]) > 1e-6 or abs(self.spacing - info["spacing"]) > 1e-6:
                    self.report({'WARNING'}, "Size Y and spacing were matched to the neighbor so the border lines up")
                self.size_y, self.spacing = info["size_y"], info["spacing"]
                step = (info["size_x"] + self.size_x) / 2.0
                location.x += step if self.side == '+X' else -step
            else:
                if abs(self.size_x - info["size_x"]) > 1e-6 or abs(self.spacing - info["spacing"]) > 1e-6:
                    self.report({'WARNING'}, "Size X and spacing were matched to the neighbor so the border lines up")
                self.size_x, self.spacing = info["size_x"], info["spacing"]
                step = (info["size_y"] + self.size_y) / 2.0
                location.y += step if self.side == '+Y' else -step

        mat_name = bsp.banana.terrain_material or "terrain"
        material = bpy.data.materials.get(mat_name) or bpy.data.materials.new(mat_name)
        obj = make_tile("%s_terrain" % bsp.name, self.size_x, self.size_y, self.spacing, location, material)
        structure = bsp_mod.sub_collections(bsp, 'STRUCTURE')
        (structure[0] if structure else bsp).objects.link(obj)
        context.view_layer.update()
        matched = copy_border_heights(obj, neighbor) if neighbor is not None else 0
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        self.report({'INFO'}, "Added %s%s" % (obj.name, (" (%d border vertices matched)" % matched) if matched else ""))
        return {'FINISHED'}


# ------------------------------------------------------------------ border lock

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


def set_mask(mesh, values):
    attr = mesh.attributes.get(MASK_ATTR) or mesh.attributes.new(MASK_ATTR, 'FLOAT', 'POINT')
    attr.data.foreach_set("value", values)
    mesh.update()


def clear_mask(mesh):
    attr = mesh.attributes.get(MASK_ATTR)
    if attr is not None:
        mesh.attributes.remove(attr)
        mesh.update()


BRUSHES = (
    ('DRAW', "Raise / Lower", "Draw", "builtin_brush.Draw", 'SCULPTMODE_HLT'),
    ('SMOOTH', "Smooth", "Smooth", "builtin_brush.Smooth", 'MOD_SMOOTH'),
    ('FLATTEN', "Flatten", "Flatten/Contrast", "builtin_brush.Flatten", 'DOT'),
    ('CLAY', "Clay", "Clay Strips", "builtin_brush.Clay Strips", 'BRUSH_CLAY_STRIPS'),
)


def _view3d_override(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                return {"window": window, "area": area, "region": region}
    return None


def _activate_brush(context, key):
    entry = next(b for b in BRUSHES if b[0] == key)
    _key_, _label, asset_name, tool_id, _icon = entry
    override = _view3d_override(context)
    ok = False
    if override is not None:
        with context.temp_override(**override):
            try:  # Blender 4.1/4.2
                bpy.ops.wm.tool_set_by_id(name=tool_id)
                ok = True
            except Exception:
                pass
            if not ok:
                try:  # Blender 4.3+: brushes are assets
                    bpy.ops.brush.asset_activate(
                        asset_library_type='ESSENTIALS',
                        relative_asset_identifier="brushes/essentials_brushes-mesh_sculpt.blend/Brush/%s" % asset_name)
                    ok = True
                except Exception:
                    pass
    brush = context.tool_settings.sculpt.brush
    if brush is not None and hasattr(brush, "sculpt_plane"):
        try:
            brush.sculpt_plane = 'Z'  # push straight up/down
        except Exception:
            pass
    return ok


class BANANA_OT_height_brush(bpy.types.Operator):
    """Sculpt the selected terrain with height-only brushes; borders are locked so seams stay sealed"""
    bl_idname = "banana.height_brush"
    bl_label = "Height Brush"
    bl_options = {'REGISTER', 'UNDO'}

    brush: EnumProperty(items=[(b[0], b[1], "") for b in BRUSHES], default='DRAW')

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a terrain mesh")
            return {'CANCELLED'}
        s = context.scene.banana
        sculpt_settings = context.tool_settings.sculpt
        if obj.mode != 'SCULPT':
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            if s.lock_borders:
                set_mask(obj.data, border_mask(obj.data, s.border_rings))
            if not s.height_brush_active:
                s.saved_lock_x, s.saved_lock_y = sculpt_settings.lock_x, sculpt_settings.lock_y
            bpy.ops.object.mode_set(mode='SCULPT')
        sculpt_settings.lock_x = True
        sculpt_settings.lock_y = True
        s.height_brush_active = True
        if not _activate_brush(context, self.brush):
            self.report({'WARNING'}, "Couldn't switch brush automatically; pick it from the toolbar (height lock is on)")
        return {'FINISHED'}


class BANANA_OT_done_sculpting(bpy.types.Operator):
    """Leave the height brush: back to Object Mode, sculpt axis locks restored"""
    bl_idname = "banana.done_sculpting"
    bl_label = "Done Sculpting"
    bl_options = {'REGISTER', 'UNDO'}

    keep_mask: BoolProperty(name="Keep Border Mask", default=False)

    def execute(self, context):
        s = context.scene.banana
        obj = context.active_object
        if obj is not None and obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if obj is not None and obj.type == 'MESH' and not self.keep_mask:
            clear_mask(obj.data)
        if s.height_brush_active:
            context.tool_settings.sculpt.lock_x = s.saved_lock_x
            context.tool_settings.sculpt.lock_y = s.saved_lock_y
            s.height_brush_active = False
        return {'FINISHED'}


# ------------------------------------------------------------------ match borders

def match_borders(scene, prefer=None):
    """Same XY on borders of different BSPs -> same height (prefer's height if it's one of them,
    otherwise the average). Returns the number of vertices moved."""
    groups = {}
    for bsp, obj in all_terrain(scene):
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        border = {v.index for e in bm.edges if len(e.link_faces) == 1 for v in e.verts}
        bm.free()
        mw = obj.matrix_world
        for i in border:
            w = mw @ obj.data.vertices[i].co
            groups.setdefault(_key(w.x, w.y), []).append((bsp.name, obj, i, w.z))
    moved = 0
    touched = set()
    for members in groups.values():
        if len({m[0] for m in members}) < 2:
            continue
        zs = [m[3] for m in members]
        preferred = [m[3] for m in members if m[1] is prefer]
        z = preferred[0] if preferred else sum(zs) / len(zs)
        for _b, obj, i, old_z in members:
            if abs(old_z - z) > 1e-7:
                w = obj.matrix_world @ obj.data.vertices[i].co
                obj.data.vertices[i].co = obj.matrix_world.inverted() @ Vector((w.x, w.y, z))
                moved += 1
                touched.add(obj)
    for obj in touched:
        obj.data.update()
    return moved


class BANANA_OT_match_borders(bpy.types.Operator):
    """Make terrain heights identical where two BSPs' borders meet (the active tile wins, otherwise the average)"""
    bl_idname = "banana.match_borders"
    bl_label = "Match Borders"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        moved = match_borders(context.scene, prefer=context.active_object)
        self.report({'INFO'}, "Matched %d border vertices; rebuild sky shells if borders moved" % moved)
        return {'FINISHED'}


class BANANA_PT_terrain(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Banana"
    bl_label = "Terrain"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        s = context.scene.banana
        layout = self.layout
        layout.operator("banana.new_tile", icon='MESH_GRID')

        box = layout.box()
        box.label(text="Height Brush", icon='SCULPTMODE_HLT')
        grid = box.grid_flow(columns=2, align=True)
        for key, label, _a, _t, _i in BRUSHES:
            grid.operator("banana.height_brush", text=label).brush = key
        row = box.row(align=True)
        row.prop(s, "lock_borders")
        sub = row.row(align=True)
        sub.enabled = s.lock_borders
        sub.prop(s, "border_rings", text="Falloff")
        box.operator("banana.done_sculpting", icon='CHECKMARK')
        layout.operator("banana.match_borders", icon='SNAP_EDGE')


CLASSES = (BANANA_OT_new_tile, BANANA_OT_height_brush, BANANA_OT_done_sculpting,
           BANANA_OT_match_borders, BANANA_PT_terrain)
