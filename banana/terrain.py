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
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
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


def terrain_for(obj, scene):
    """The terrain tile an object stands for: itself, or the terrain of the BSP it belongs to
    (so clicking a sky shell, prop or anything else in a terrain BSP picks that terrain)."""
    if obj is None:
        return None
    if is_terrain(obj):
        return obj
    bsp = bsp_mod.bsp_of(obj, scene)
    return terrain_of(bsp) if bsp is not None else None


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


def _xy_tree(obj):
    mw = obj.matrix_world
    pts = [mw @ v.co for v in obj.data.vertices]
    tree = KDTree(len(pts))
    for i, p in enumerate(pts):
        tree.insert(Vector((p.x, p.y, 0.0)), i)
    tree.balance()
    return tree, pts


def shared_edge(a_obj, b_obj):
    """[(index in a, index in b, world xy)] for border vertices both terrains share,
    ordered along the edge."""
    amw, bmw = a_obj.matrix_world, b_obj.matrix_world
    b_border = {}
    for i in border_indices(b_obj.data):
        w = bmw @ b_obj.data.vertices[i].co
        b_border[_key(w.x, w.y)] = i
    pairs = []
    for i in border_indices(a_obj.data):
        w = amw @ a_obj.data.vertices[i].co
        j = b_border.get(_key(w.x, w.y))
        if j is not None:
            pairs.append((i, j, Vector((w.x, w.y))))
    if len(pairs) < 2:
        return pairs
    # order along the edge's main direction
    xs = [p[2].x for p in pairs]
    ys = [p[2].y for p in pairs]
    axis = 0 if (max(xs) - min(xs)) >= (max(ys) - min(ys)) else 1
    pairs.sort(key=lambda p: p[2][axis])
    return pairs


def blend_edge(a_obj, b_obj, rows):
    """Lift the shared edge to meet both terrains: the edge goes to the average of the first
    free row on each side, and `rows` rows on each side ramp smoothly to it. The edge's two
    end vertices stay put (they may be corners shared with other BSPs). Returns vertices moved."""
    pairs = shared_edge(a_obj, b_obj)
    if len(pairs) < 3:
        return 0
    spacing = min(a_obj[TILE_KEY].get("spacing", 1.0), b_obj[TILE_KEY].get("spacing", 1.0))
    direction = (pairs[-1][2] - pairs[0][2]).normalized()
    perp = Vector((-direction.y, direction.x))
    mid = (pairs[0][2] + pairs[-1][2]) / 2
    a_center = (a_obj.matrix_world @ Vector(a_obj.bound_box[0]) + a_obj.matrix_world @ Vector(a_obj.bound_box[6])) / 2
    a_in = perp if (Vector((a_center.x, a_center.y)) - mid).dot(perp) > 0 else -perp
    sides = ((a_obj, a_in), (b_obj, -a_in))
    trees = {obj.name: _xy_tree(obj) for obj, _d in sides}
    changes = {a_obj.name: {}, b_obj.name: {}}
    for ia, ib, e in pairs[1:-1]:
        columns = []
        for obj, inward in sides:
            tree, pts = trees[obj.name]
            col = []
            for k in range(1, rows + 2):
                target = e + inward * spacing * k
                _co, idx, dist = tree.find(Vector((target.x, target.y, 0.0)))
                if idx is None or dist > spacing * 0.3:
                    col = None
                    break
                col.append(idx)
            if col is None:
                break
            columns.append((obj, col, pts))
        if len(columns) != 2:
            continue
        free = [pts[col[-1]].z for _obj, col, pts in columns]
        h = (free[0] + free[1]) / 2.0
        changes[a_obj.name][ia] = h
        changes[b_obj.name][ib] = h
        for (obj, col, pts), z_free in zip(columns, free):
            for k, idx in enumerate(col[:-1], start=1):
                changes[obj.name][idx] = h + (z_free - h) * k / (rows + 1)
    moved = 0
    for obj, _d in sides:
        mw = obj.matrix_world
        inv = mw.inverted()
        for idx, z in changes[obj.name].items():
            w = mw @ obj.data.vertices[idx].co
            if abs(w.z - z) > 1e-7:
                obj.data.vertices[idx].co = inv @ Vector((w.x, w.y, z))
                moved += 1
        obj.data.update()
    return moved


def safe_tolerance(a, b, wanted):
    """Never snap farther than 40% of the finer vertex spacing, or vertices next to the
    edge could collapse onto it."""
    spacing = min(a[TILE_KEY].get("spacing", wanted * 2.5), b[TILE_KEY].get("spacing", wanted * 2.5))
    return min(wanted, 0.4 * spacing)


def _two_terrains(context):
    """(active terrain, other terrain) from the selection, in two different BSPs."""
    active = terrain_for(context.active_object, context.scene)
    picked = []
    for obj in context.selected_objects:
        t = terrain_for(obj, context.scene)
        if t is not None and t not in picked:
            picked.append(t)
    if active is None or active not in picked:
        if active is not None:
            picked.insert(0, active)
    if active is None or len(picked) != 2:
        return None, None, "Select two terrains in two different BSPs (the active one is kept as is)"
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
        active = terrain_for(context.active_object, context.scene)
        if active is not None:
            info = active[TILE_KEY]
            self.size_x, self.size_y, self.spacing = info["size_x"], info["size_y"], info["spacing"]
            self.next_to_selected = True
        else:
            self.next_to_selected = False
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "name")
        neighbor = terrain_for(context.active_object, context.scene)
        row = layout.row()
        row.enabled = neighbor is not None
        row.prop(self, "next_to_selected", text="Next to %s" % neighbor.name if neighbor else "Next to Selected Terrain (none selected)")
        if self.next_to_selected and neighbor is not None:
            layout.prop(self, "side", expand=True)
            layout.label(text="Size and spacing are matched along the shared edge", icon='INFO')
        layout.prop(self, "size_x")
        layout.prop(self, "size_y")
        layout.prop(self, "spacing")

    def execute(self, context):
        from . import sky
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        neighbor = terrain_for(context.active_object, context.scene) if self.next_to_selected else None
        if self.next_to_selected and neighbor is None:
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
        if s.sky_height_auto and s.sky_height < sky.auto_sky_height(context) - 1e-6:
            # only happens if this tile starts above everything else
            _rebuild(context, {})
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


def _plan_seams(context, a, b, join):
    """Seam partners for every BSP that will be rebuilt, captured *before* any height changes
    (afterwards old seams no longer line up with the moved edge, so they couldn't be found)."""
    from . import sky
    s = context.scene.banana
    weld = 0.01 / s.scale()
    everyone = bsp_mod.find_bsps(context.scene)
    plans = {}
    for bsp, partner in ((a, b), (b, a)):
        others = [o for o in everyone if o is not bsp]
        current = sky.existing_seam_partners(context, bsp, others, weld)
        if join and partner not in current:
            current = [partner] + current
        plans[bsp.name] = current
    return plans


def raise_sky_if_needed(context):
    """Auto sky height only ever goes up, so existing seams keep their top edge.
    Returns True if it went up (then every sky must be rebuilt)."""
    from . import sky
    s = context.scene.banana
    if not s.sky_height_auto:
        return False
    needed = sky.auto_sky_height(context)
    if needed > s.sky_height + 1e-6:
        s.sky_height = needed
        return True
    return False


def _rebuild(context, plans):
    """Rebuild the planned skies. If the sky had to go up, rebuild every sky (keeping each
    one's seams) so all tops stay level."""
    from . import sky
    s = context.scene.banana
    weld = 0.01 / s.scale()
    everyone = bsp_mod.find_bsps(context.scene)
    plans = dict(plans)
    if s.sky_height_auto and sky.auto_sky_height(context) > s.sky_height + 1e-6:
        for b in everyone:  # plan before any shell is replaced
            if b.name not in plans and sky.terrain_objects(b):
                plans[b.name] = sky.existing_seam_partners(context, b, [o for o in everyone if o is not b], weld)
        raise_sky_if_needed(context)
    lines = []
    by_name = {b.name: b for b in everyone}
    for name, partners in plans.items():
        bsp = by_name.get(name)
        if bsp is None:
            continue
        neighbors = [(o, sky.border_edge_keys(context, o, weld)) for o in partners]
        _obj, msgs = sky.build_shell(context, bsp, s.sky_height, neighbors)
        lines.extend(msgs)
    return lines


class _EdgeOptions:
    tolerance: FloatProperty(name="Snap Distance", default=1.0, min=0.0, subtype='DISTANCE',
                             description="Edge vertices this close (sideways) to the active terrain's edge get snapped")
    blend: BoolProperty(name="Blend Heights", default=True,
                        description="Lift the shared edge to meet both terrains, with a smooth ramp on each side")
    rows: IntProperty(name="Blend Rows", default=3, min=1, max=50,
                      description="How many rows of vertices on each side ramp up to the edge")

    def _prepare(self, context, join):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        active, other, err = _two_terrains(context)
        if err:
            return None, None, None, None, err
        from . import sky
        a = bsp_mod.bsp_of(active, context.scene)
        b = bsp_mod.bsp_of(other, context.scene)
        overlaps = sky.check_overlaps(context, [a, b])
        if overlaps:
            return None, None, None, None, overlaps[0][1]
        plans = _plan_seams(context, a, b, join)
        match_edge(active, other, safe_tolerance(active, other, self.tolerance))
        blended = blend_edge(active, other, self.rows) if self.blend else 0
        context.view_layer.update()
        return active, other, plans, blended, None


class BANANA_OT_match_edge(_EdgeOptions, bpy.types.Operator):
    """Snap the other terrain's edge onto the active one and blend the heights across it (skies and existing seams are rebuilt to fit)"""
    bl_idname = "banana.match_edge"
    bl_label = "Match Edge"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        active, other, plans, blended, err = self._prepare(context, join=False)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        for sev, m in _rebuild(context, plans):
            if sev == 'ERROR':
                self.report({'WARNING'}, m)
        self.report({'INFO'}, "Matched %s and %s%s" % (
            active.name, other.name, (" (%d vertices blended)" % blended) if blended else ""))
        return {'FINISHED'}


class BANANA_OT_generate_seam(_EdgeOptions, bpy.types.Operator):
    """Join two selected terrain BSPs: match and blend the shared edge, then rebuild both skies with a seam there"""
    bl_idname = "banana.generate_seam"
    bl_label = "Generate Seam"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from . import sky
        active, other, plans, _blended, err = self._prepare(context, join=True)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        a = bsp_mod.bsp_of(active, context.scene)
        b = bsp_mod.bsp_of(other, context.scene)
        lines = _rebuild(context, plans)
        problems = [m for sev, m in lines if sev == 'ERROR']
        problems += [m for _s, m, _b in sky.check_border_alignment(context, [a, b])]
        for m in problems[:4]:
            self.report({'WARNING'}, m)
        shared = len(sky.seam_triangles(context, a)) // 2
        if shared == 0:
            self.report({'WARNING'}, "No shared edge between %s and %s; are they touching?" % (a.name, b.name))
            return {'FINISHED'}
        self.report({'INFO'}, "Seam between %s and %s" % (a.name, b.name))
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
