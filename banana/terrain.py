"""Terrain BSPs.

Every terrain is its own BSP: New Terrain BSP makes the BSP collection, a flat
grid tile and a sky shell over it. Placed next to a selected terrain, the shared
edge lines up vertex for vertex.

With two terrain BSPs selected:
- Match Edge snaps the other terrain's edge onto the active terrain's edge
  (position and height), like edge matching in the Titamas add-on.
- Generate Seam matches the edge, then rebuilds both sky shells so the shared
  edge becomes a +seam pair instead of two sky walls.
"""

import bpy
import bmesh
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from mathutils import Vector
from mathutils.kdtree import KDTree

from . import bsp as bsp_mod

TILE_KEY = "banana_tile"   # {"size_x", "size_y", "spacing"}


def is_terrain(obj):
    return obj is not None and obj.type == 'MESH' and obj.get(TILE_KEY) is not None


def terrain_of(bsp):
    for obj in bsp_mod.objects_for_role(bsp, 'STRUCTURE'):
        if is_terrain(obj):
            return obj
    return None


def all_terrain(scene):
    out = []
    for bsp in bsp_mod.find_bsps(scene):
        for obj in bsp_mod.objects_for_role(bsp, 'STRUCTURE'):
            if is_terrain(obj):
                out.append((bsp, obj))
    return out


def _key(x, y):
    return (round(x, 4), round(y, 4))


def border_indices(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    idx = sorted({v.index for e in bm.edges if len(e.link_faces) == 1 for v in e.verts})
    bm.free()
    return idx


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


def match_edge(target, source, tolerance):
    """Snap source's border vertices onto the nearest target border vertex (x, y and z)
    when it's within `tolerance` sideways. Returns how many moved."""
    t_idx = border_indices(target.data)
    if not t_idx:
        return 0
    tmw = target.matrix_world
    pts = [tmw @ target.data.vertices[i].co for i in t_idx]
    tree = KDTree(len(pts))
    for k, p in enumerate(pts):
        tree.insert(Vector((p.x, p.y, 0.0)), k)  # search in XY only
    tree.balance()
    smw = source.matrix_world
    inv = smw.inverted()
    moved = 0
    for i in border_indices(source.data):
        w = smw @ source.data.vertices[i].co
        _co, k, dist = tree.find(Vector((w.x, w.y, 0.0)))
        if k is None or dist > tolerance:
            continue
        if (pts[k] - w).length > 1e-7:
            source.data.vertices[i].co = inv @ pts[k]
            moved += 1
    source.data.update()
    return moved


def _two_terrains(context):
    """(active terrain, other terrain) from the selection, in two different BSPs."""
    active = context.active_object
    picked = [o for o in context.selected_objects if is_terrain(o)]
    if not is_terrain(active) or len(picked) != 2:
        return None, None, "Select two terrain tiles (the active one is kept as is)"
    other = picked[0] if picked[1] is active else picked[1]
    a_bsp = bsp_mod.bsp_of(active, context.scene)
    b_bsp = bsp_mod.bsp_of(other, context.scene)
    if a_bsp is None or b_bsp is None or a_bsp is b_bsp:
        return None, None, "The two terrains must be in two different BSPs"
    return active, other, None


SIDES = (('+X', "East (+X)", ""), ('-X', "West (-X)", ""), ('+Y', "North (+Y)", ""), ('-Y', "South (-Y)", ""))


class BANANA_OT_new_terrain(bpy.types.Operator):
    """Create a new terrain BSP: a flat tile with its own sky shell. Next to a selected terrain, the edges line up"""
    bl_idname = "banana.new_terrain"
    bl_label = "New Terrain BSP"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="BSP Name", default="")
    size_x: FloatProperty(name="Size X", default=100.0, min=1.0, subtype='DISTANCE')
    size_y: FloatProperty(name="Size Y", default=100.0, min=1.0, subtype='DISTANCE')
    spacing: FloatProperty(name="Vertex Spacing", default=2.0, min=0.05, subtype='DISTANCE')
    next_to_selected: BoolProperty(name="Next to Selected Terrain", default=True)
    side: EnumProperty(name="Side", items=SIDES, default='+X')

    @staticmethod
    def _default_name(context):
        existing = {b.name for b in bsp_mod.find_bsps(context.scene)}
        n = 0
        while "terrain_%03d" % n in existing:
            n += 1
        return "terrain_%03d" % n

    def invoke(self, context, event):
        self.name = self._default_name(context)
        active = context.active_object
        if is_terrain(active):
            info = active[TILE_KEY]
            self.size_x, self.size_y, self.spacing = info["size_x"], info["size_y"], info["spacing"]
        else:
            self.next_to_selected = False
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        from . import sky
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        neighbor = context.active_object if self.next_to_selected else None
        if neighbor is not None and not is_terrain(neighbor):
            self.report({'ERROR'}, "Select a terrain to place the new one next to, or untick Next to Selected Terrain")
            return {'CANCELLED'}
        location = Vector((0.0, 0.0, 0.0))
        if neighbor is not None:
            info = neighbor[TILE_KEY]
            location = neighbor.matrix_world.translation.copy()
            if self.side in ('+X', '-X'):
                self.size_y, self.spacing = info["size_y"], info["spacing"]
                step = (info["size_x"] + self.size_x) / 2.0
                location.x += step if self.side == '+X' else -step
            else:
                self.size_x, self.spacing = info["size_x"], info["spacing"]
                step = (info["size_y"] + self.size_y) / 2.0
                location.y += step if self.side == '+Y' else -step

        name = self.name.strip() or self._default_name(context)
        bsp = bsp_mod.create_bsp(context.scene, name)
        mat_name = bsp.banana.terrain_material or "terrain"
        material = bpy.data.materials.get(mat_name) or bpy.data.materials.new(mat_name)
        obj = make_tile("%s_ground" % bsp.name, self.size_x, self.size_y, self.spacing, location, material)
        bsp_mod.sub_collections(bsp, 'STRUCTURE')[0].objects.link(obj)
        context.view_layer.update()
        if neighbor is not None:
            match_edge(neighbor, obj, self.spacing * 0.25)
            context.view_layer.update()

        s = context.scene.banana
        if s.sky_height_auto:
            s.sky_height = sky.auto_sky_height(context)
        _shell, msgs = sky.build_shell(context, bsp, s.sky_height, neighbors=[])
        s.active_bsp = bsp
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        for m in [m for sev, m in msgs if sev == 'ERROR']:
            self.report({'WARNING'}, m)
        self.report({'INFO'}, "Created %s with a sky shell%s" % (
            bsp.name, (" next to %s; select both and press Generate Seam to join them" % neighbor.name) if neighbor else ""))
        return {'FINISHED'}


class BANANA_OT_match_edge(bpy.types.Operator):
    """Snap the other selected terrain's edge onto the active terrain's edge (position and height)"""
    bl_idname = "banana.match_edge"
    bl_label = "Match Edge"
    bl_options = {'REGISTER', 'UNDO'}

    tolerance: FloatProperty(name="Snap Distance", default=1.0, min=0.0, subtype='DISTANCE',
                             description="Edge vertices this close (sideways) to the active terrain's edge get snapped")

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        active, other, err = _two_terrains(context)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        moved = match_edge(active, other, self.tolerance)
        self.report({'INFO'}, "Matched %d edge vertices of %s to %s" % (moved, other.name, active.name))
        return {'FINISHED'}


class BANANA_OT_generate_seam(bpy.types.Operator):
    """Join two selected terrain BSPs: match the shared edge and rebuild both sky shells with a seam there"""
    bl_idname = "banana.generate_seam"
    bl_label = "Generate Seam"
    bl_options = {'REGISTER', 'UNDO'}

    tolerance: FloatProperty(name="Snap Distance", default=1.0, min=0.0, subtype='DISTANCE')

    def execute(self, context):
        from . import sky
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        active, other, err = _two_terrains(context)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        match_edge(active, other, self.tolerance)
        context.view_layer.update()
        a = bsp_mod.bsp_of(active, context.scene)
        b = bsp_mod.bsp_of(other, context.scene)
        s = context.scene.banana
        if s.sky_height_auto:
            s.sky_height = sky.auto_sky_height(context)
        weld = 0.01 / s.scale()
        everyone = bsp_mod.find_bsps(context.scene)
        keys = {x.name: sky.border_edge_keys(context, x, weld) for x in everyone}
        lines = []
        # rebuild both against every neighbor they touch, so their other seams survive
        for bsp in (a, b):
            neighbors = [(o, keys[o.name]) for o in everyone if o is not bsp]
            _obj, msgs = sky.build_shell(context, bsp, s.sky_height, neighbors)
            lines.extend(msgs)
        problems = [m for sev, m in lines if sev == 'ERROR']
        problems += [m for _s, m, _b in sky.check_border_alignment(context, [a, b])]
        for m in problems[:4]:
            self.report({'WARNING'}, m)
        shared = len(sky.seam_triangles(context, a)) // 2
        if shared == 0:
            self.report({'WARNING'}, "No shared edge between %s and %s; are they touching?" % (a.name, b.name))
            return {'FINISHED'}
        self.report({'INFO'}, "Seam between %s and %s (%d edge segments)" % (a.name, b.name, shared))
        return {'FINISHED'}


class BANANA_PT_terrain(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Banana"
    bl_label = "Terrain"

    def draw(self, context):
        s = context.scene.banana
        layout = self.layout
        layout.operator("banana.new_terrain", icon='MESH_GRID')

        box = layout.box()
        box.label(text="Two Terrains Selected", icon='SNAP_EDGE')
        row = box.row(align=True)
        row.operator("banana.match_edge", icon='SNAP_ON')
        row.operator("banana.generate_seam", icon='AUTOMERGE_ON')
        box.operator("banana.build_sky_shell", text="Rebuild All Skies", icon='WORLD').all_bsps = True

        box = layout.box()
        box.label(text="Set Height Brush", icon='BRUSH_DATA')
        box.prop(s, "brush_height")
        row = box.row(align=True)
        row.prop(s, "brush_radius")
        row.prop(s, "brush_strength", slider=True)
        row = box.row(align=True)
        row.prop(s, "lock_borders")
        sub = row.row(align=True)
        sub.enabled = s.lock_borders
        sub.prop(s, "border_rings", text="Falloff")
        box.operator("banana.terrain_brush", text="Paint Height", icon='SCULPTMODE_HLT').mode = 'HEIGHT'
        box.label(text="Ctrl+click: pick height · [ ] radius · Right-click: done")


CLASSES = (BANANA_OT_new_terrain, BANANA_OT_match_edge, BANANA_OT_generate_seam, BANANA_PT_terrain)
