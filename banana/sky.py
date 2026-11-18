"""Sky shells and seams.

Sky shell: seals a BSP's open terrain border with vertical walls up to the
scene's Sky Height plus a top cap, all using '+sky' (exported as +sky<index>).
Wall segments that sit on another BSP's terrain border become '+seam' instead
(exported as '+seam:<that BSP's name>' on each side). Both BSPs build those triangles from the same two border vertices
with the same diagonal, so the pair always has identical triangulation; each
side faces into its own BSP, which is what Tool's seam matching wants.

Seam mirroring: for seams that aren't terrain borders (a corridor between two
BSPs), mirror a seam object into the other BSP. The copy is rebuilt from the
original's triangles (winding flipped) every export, so they never drift.
"""

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import bsp as bsp_mod

SHELL_KEY = "banana_shell"
SEAM_SOURCE_KEY = "banana_seam_source"
SKY_MATERIAL = "+sky"


def _round(co, digits=4):
    return (round(co[0], digits), round(co[1], digits), round(co[2], digits))


def terrain_objects(bsp):
    return [o for o in bsp_mod.objects_for_role(bsp, 'STRUCTURE')
            if not o.get(SHELL_KEY) and not o.get(SEAM_SOURCE_KEY)]


def _world_bmesh(context, objs, weld):
    depsgraph = context.evaluated_depsgraph_get()
    bm = bmesh.new()
    for obj in objs:
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        try:
            before = len(bm.verts)
            bm.from_mesh(mesh)
            bm.verts.ensure_lookup_table()
            bmesh.ops.transform(bm, matrix=obj.matrix_world, verts=bm.verts[before:])
        finally:
            eval_obj.to_mesh_clear()
    if bm.verts:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=weld)
    return bm


def border_loops(bm):
    """Chains boundary edges into closed loops. Returns (loops, problems) where each
    loop is a list of (BMVert, BMVert, direction_in_face) edges in order."""
    boundary = [e for e in bm.edges if len(e.link_faces) == 1]
    by_vert = {}
    for e in boundary:
        for v in e.verts:
            by_vert.setdefault(v, []).append(e)
    problems = []
    if any(len(es) != 2 for es in by_vert.values()):
        problems.append("The terrain border touches itself (a vertex with more than two border edges)")
        return [], problems
    loops, used = [], set()
    for start in boundary:
        if start in used:
            continue
        loop = []
        edge = start
        v = start.verts[0]
        while edge not in used:
            used.add(edge)
            other = edge.other_vert(v)
            # which way does the terrain face walk this edge?
            face = edge.link_faces[0]
            fwd = any(l.edge == edge and l.vert == v for l in face.loops)
            loop.append((v, other, fwd))
            v = other
            nxt = [e for e in by_vert[v] if e is not edge]
            edge = nxt[0]
        loops.append(loop)
    return loops, problems


def _loop_area(loop):
    xs = [a.co.x for a, _b, _f in loop]
    ys = [a.co.y for a, _b, _f in loop]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def border_edge_keys(context, bsp, weld):
    bm = _world_bmesh(context, terrain_objects(bsp), weld)
    keys = set()
    for e in bm.edges:
        if len(e.link_faces) == 1:
            keys.add(frozenset((_round(e.verts[0].co), _round(e.verts[1].co))))
    bm.free()
    return keys


def border_verts(context, bsp, weld):
    bm = _world_bmesh(context, terrain_objects(bsp), weld)
    pts = list({_round(v.co, 6): v.co.copy() for e in bm.edges if len(e.link_faces) == 1 for v in e.verts}.values())
    bm.free()
    return pts


def existing_seam_partners(context, bsp, others, weld):
    """BSPs that already have seam faces sitting on this BSP's border."""
    border = {_round(p) for p in border_verts(context, bsp, weld)}
    partners = []
    for other in others:
        for key in seam_triangles(context, other):
            if sum(1 for p in key if p in border) >= 2:
                partners.append(other)
                break
    return partners


def check_overlaps(context, bsps):
    """Terrain BSPs lying on top of each other (e.g. a tile created in the same spot)."""
    from . import terrain
    boxes = []
    for b in bsps:
        t = terrain.terrain_of(b)
        if t is None:
            continue
        pts = [t.matrix_world @ Vector(c) for c in t.bound_box]
        boxes.append((b.name, min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts)))
    out = []
    for i, (an, ax0, ax1, ay0, ay1) in enumerate(boxes):
        for bn, bx0, bx1, by0, by1 in boxes[i + 1:]:
            ox = min(ax1, bx1) - max(ax0, bx0)
            oy = min(ay1, by1) - max(ay0, by0)
            if ox > 1e-3 and oy > 1e-3:
                out.append(('ERROR', "Terrains of %s and %s overlap (%.0f x %.0f m); move or delete one" % (an, bn, ox, oy), an))
    return out


def check_border_alignment(context, bsps):
    """Terrain borders that nearly meet another BSP's border but don't line up exactly
    get plain +sky walls instead of seams, leaving the BSPs unconnected there."""
    from mathutils.kdtree import KDTree
    scale = context.scene.banana.scale()
    weld = 0.01 / scale
    near = 16.0 / scale  # about half a meter
    pts = {b.name: border_verts(context, b, weld) for b in bsps}
    out = []
    names = [b.name for b in bsps]
    for i, an in enumerate(names):
        for bn in names[i + 1:]:
            if not pts[an] or not pts[bn]:
                continue
            tree = KDTree(len(pts[bn]))
            for k, p in enumerate(pts[bn]):
                tree.insert(p, k)
            tree.balance()
            off = sum(1 for p in pts[an] if 1e-4 < tree.find(p)[2] < near)
            if off:
                out.append(('ERROR', "Terrain borders of %s and %s almost meet, but %d vertices don't line up exactly; "
                            "no seam is made there" % (an, bn, off), an))
    return out


SEAM_DEFAULT = "+seam"


def bsp_seam_material(bsp):
    """This BSP's own seam material. Created once as '+seam' (Blender makes it '+seam.001' etc.
    if that name is taken); after that whatever the user renames it to is kept and exported as is."""
    mat = bsp.banana.seam_material
    if mat is None or mat.name not in bpy.data.materials:
        mat = bpy.data.materials.new(SEAM_DEFAULT)
        mat.diffuse_color = (1.0, 0.2, 0.8, 1.0)  # easy to spot in solid view
        bsp.banana.seam_material = mat
    return mat


def seam_name(bsp, _other):
    return bsp_seam_material(bsp).name


def material(name):
    return bpy.data.materials.get(name) or bpy.data.materials.new(name)


def auto_sky_height(context):
    top = None
    for bsp in bsp_mod.find_bsps(context.scene):
        for obj in terrain_objects(bsp):
            for corner in obj.bound_box:
                z = (obj.matrix_world @ Vector(corner)).z
                top = z if top is None else max(top, z)
    return (top or 0.0) + 30.0


def build_shell(context, bsp, sky_height, neighbors):
    """neighbors: [(other_bsp, border_edge_keys)]. Returns (object_or_None, messages)."""
    weld = 0.01 / context.scene.banana.scale()
    msgs = []
    bm = _world_bmesh(context, terrain_objects(bsp), weld)
    loops, problems = border_loops(bm)
    msgs.extend(('ERROR', p) for p in problems)
    if not loops:
        bm.free()
        if not problems:
            msgs.append(('INFO', "%s is already sealed; no shell needed" % bsp.name))
        return None, msgs
    loops.sort(key=_loop_area, reverse=True)
    if len(loops) > 1:
        msgs.append(('ERROR', "%s has %d holes in its terrain; fill them (only the outer border was sealed)" % (
            bsp.name, len(loops) - 1)))
    loop = loops[0]
    if max(a.co.z for a, _b, _f in loop) >= sky_height:
        bm.free()
        msgs.append(('ERROR', "Sky Height is below the terrain border of %s" % bsp.name))
        return None, msgs

    names = [SKY_MATERIAL]
    verts, faces, face_mats = [], [], []
    index = {}

    def vid(co):
        key = _round(co, 6)
        if key not in index:
            index[key] = len(verts)
            verts.append(tuple(co))
        return index[key]

    seam_count = 0
    for a, b, fwd in loop:
        ka, kb = _round(a.co), _round(b.co)
        mat = 0
        for other, keys in neighbors:
            if frozenset((ka, kb)) in keys:
                name = seam_name(bsp, other)
                if name not in names:
                    names.append(name)
                mat = names.index(name)
                seam_count += 1
                break
        lo, hi = (a, b) if ka <= kb else (b, a)
        lo_t = Vector((lo.co.x, lo.co.y, sky_height))
        hi_t = Vector((hi.co.x, hi.co.y, sky_height))
        t1 = [vid(lo.co), vid(hi.co), vid(hi_t)]
        t2 = [vid(lo.co), vid(hi_t), vid(lo_t)]
        # t1 walks lo->hi; the terrain must walk that edge the other way
        terrain_lo_to_hi = fwd if lo is a else not fwd
        if terrain_lo_to_hi:
            t1.reverse()
            t2.reverse()
        faces.extend((t1, t2))
        face_mats.extend((mat, mat))

    # top cap, oriented against the first wall's top edge
    cap = [vid(Vector((a.co.x, a.co.y, sky_height))) for a, _b, _f in loop]
    a0, b0, fwd0 = loop[0]
    lo_is_a = _round(a0.co) <= _round(b0.co)
    first_t2 = faces[1]
    top_lo = vid(Vector(((a0 if lo_is_a else b0).co.x, (a0 if lo_is_a else b0).co.y, sky_height)))
    top_hi = vid(Vector(((b0 if lo_is_a else a0).co.x, (b0 if lo_is_a else a0).co.y, sky_height)))
    i = first_t2.index(top_hi)
    wall_walks_hi_to_lo = first_t2[(i + 1) % 3] == top_lo
    ci = cap.index(top_hi)
    cap_walks_hi_to_lo = cap[(ci + 1) % len(cap)] == top_lo
    if wall_walks_hi_to_lo == cap_walks_hi_to_lo:
        cap.reverse()
    bm.free()

    mesh = bpy.data.meshes.new("%s_sky_shell" % bsp.name)
    mesh.from_pydata(verts, [], faces + [cap])
    for name in names:
        mesh.materials.append(material(name))
    mesh.polygons.foreach_set("material_index", face_mats + [0])
    # triangulate the cap only (walls are already triangles)
    sbm = bmesh.new()
    sbm.from_mesh(mesh)
    big = [f for f in sbm.faces if len(f.verts) > 3]
    if big:
        bmesh.ops.triangulate(sbm, faces=big, quad_method='BEAUTY', ngon_method='BEAUTY')
    sbm.to_mesh(mesh)
    sbm.free()
    mesh.update()

    structure = bsp_mod.sub_collections(bsp, 'STRUCTURE')
    target = structure[0] if structure else bsp
    old = [o for o in bsp_mod.objects_for_role(bsp, 'STRUCTURE') if o.get(SHELL_KEY)]
    for o in old:
        old_mesh = o.data
        bpy.data.objects.remove(o)
        if old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
    obj = bpy.data.objects.new("%s_sky_shell" % bsp.name, mesh)
    obj[SHELL_KEY] = True
    target.objects.link(obj)
    obj.display_type = 'WIRE'
    obj.hide_select = True  # generated; keep clicks going to the terrain underneath
    msgs.append(('INFO', "%s: sky shell built (%d seam wall segments)" % (bsp.name, seam_count)))
    return obj, msgs


class BANANA_OT_build_sky_shell(bpy.types.Operator):
    """Seal the terrain border with +sky walls and a top cap (seams where BSPs meet)"""
    bl_idname = "banana.build_sky_shell"
    bl_label = "Build Sky Shell"
    bl_options = {'REGISTER', 'UNDO'}

    all_bsps: bpy.props.BoolProperty(name="All BSPs", default=True)
    auto_seams: bpy.props.BoolProperty(
        name="Auto Seams", default=False,
        description="Also turn every exactly-shared edge into a seam. Off: only keep the seams made with Generate Seam")

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        s = context.scene.banana
        bsps = bsp_mod.find_bsps(context.scene) if self.all_bsps else [s.active_bsp] if s.active_bsp else []
        if not bsps:
            self.report({'ERROR'}, "No BSP")
            return {'CANCELLED'}
        if s.sky_height_auto:
            s.sky_height = auto_sky_height(context)
        weld = 0.01 / s.scale()
        everyone = bsp_mod.find_bsps(context.scene)
        keys = {b.name: border_edge_keys(context, b, weld) for b in everyone}
        # decide every BSP's seam partners before any shell is replaced
        plans = {}
        for bsp in bsps:
            others = [o for o in everyone if o is not bsp]
            plans[bsp.name] = others if self.auto_seams else existing_seam_partners(context, bsp, others, weld)
        lines = []
        for bsp in bsps:
            neighbors = [(o, keys[o.name]) for o in plans[bsp.name]]
            _obj, msgs = build_shell(context, bsp, s.sky_height, neighbors)
            lines.extend(msgs)
        lines.extend((sev, msg) for sev, msg, _b in check_border_alignment(context, everyone))
        lines.extend((sev, msg) for sev, msg, _b in check_overlaps(context, everyone))
        errors = [m for sev, m in lines if sev == 'ERROR']
        for m in errors[:5]:
            self.report({'ERROR'}, m)
        if not errors:
            self.report({'INFO'}, "; ".join(m for _s, m in lines))
        return {'FINISHED'}


# ------------------------------------------------------------------ seam mirroring

def _seam_materials(obj):
    return [s.material.name for s in obj.material_slots if s.material and s.material.name.startswith("+seam")]


def sync_seam_partner(context, partner):
    """Rebuild a mirrored seam from its source: same triangles, flipped winding."""
    source = partner.get(SEAM_SOURCE_KEY)
    if source is None or not isinstance(source, bpy.types.Object) or source.name not in bpy.data.objects:
        return False
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = source.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    try:
        mesh.calc_loop_triangles()
        mw = source.matrix_world
        verts = [tuple(mw @ v.co) for v in mesh.vertices]
        tris = [tuple(reversed(t.vertices)) for t in mesh.loop_triangles]
        mats = [t.material_index for t in mesh.loop_triangles]
        # .original: never store the depsgraph's temporary copies (they get freed -> crash)
        slots = [s.material.original if s.material else None for s in eval_obj.material_slots]
    finally:
        eval_obj.to_mesh_clear()
    new = bpy.data.meshes.new(partner.name)
    new.from_pydata(verts, [], tris)
    kept = list(partner.data.materials)
    if len(kept) == len(slots) and all(m is not None for m in kept):
        slots = kept  # keep whatever the user named the mirrored side
    else:
        # first sync: give the mirrored side its own seam material(s) to rename
        slots = [m.copy() if (m is not None and m.name.startswith("+seam")) else m for m in slots]
    for m in slots:
        new.materials.append(m)
    if mats:
        new.polygons.foreach_set("material_index", mats)
    new.update()
    old = partner.data
    partner.data = new
    partner.matrix_world = Matrix.Identity(4)
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return True


def sync_all_seams(context):
    count = 0
    for obj in list(bpy.data.objects):
        if obj.get(SEAM_SOURCE_KEY) is not None and sync_seam_partner(context, obj):
            count += 1
    return count


def _bsp_items(self, context):
    items = [(b.name, b.name, "") for b in bsp_mod.find_bsps(context.scene)]
    return items or [('NONE', "No BSPs", "")]


class BANANA_OT_mirror_seam(bpy.types.Operator):
    """Copy the selected +seam object(s) into another BSP, facing the other way, kept in sync on export"""
    bl_idname = "banana.mirror_seam"
    bl_label = "Mirror Seam to BSP"
    bl_options = {'REGISTER', 'UNDO'}

    target: bpy.props.EnumProperty(name="Other BSP", items=_bsp_items)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        target = bpy.data.collections.get(self.target)
        if target is None or target.banana.role != 'BSP':
            self.report({'ERROR'}, "Pick the BSP on the other side of the seam")
            return {'CANCELLED'}
        made = 0
        for obj in [o for o in context.selected_objects if o.type == 'MESH']:
            if not _seam_materials(obj):
                self.report({'WARNING'}, "%s has no +seam:<name> material; skipped" % obj.name)
                continue
            if bsp_mod.bsp_of(obj, context.scene) is target:
                self.report({'WARNING'}, "%s is already in %s" % (obj.name, target.name))
                continue
            structure = bsp_mod.sub_collections(target, 'STRUCTURE')
            coll = structure[0] if structure else target
            partner = bpy.data.objects.new("%s_mirror" % obj.name, bpy.data.meshes.new("%s_mirror" % obj.name))
            partner[SEAM_SOURCE_KEY] = obj
            coll.objects.link(partner)
            sync_seam_partner(context, partner)
            made += 1
        self.report({'INFO'}, "Mirrored %d seam object(s) into %s" % (made, target.name))
        return {'FINISHED'} if made else {'CANCELLED'}


# ------------------------------------------------------------------ seam validation

def seam_triangles(context, bsp):
    """{triangle key: normal} for every +seam face in one BSP (world space)."""
    depsgraph = context.evaluated_depsgraph_get()
    out = {}
    for obj in bsp_mod.objects_for_role(bsp, 'STRUCTURE'):
        if not _seam_materials(obj):
            continue
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        try:
            mesh.calc_loop_triangles()
            mw = obj.matrix_world
            slots = eval_obj.material_slots
            for tri in mesh.loop_triangles:
                if tri.material_index >= len(slots) or slots[tri.material_index].material is None:
                    continue
                if not slots[tri.material_index].material.name.startswith("+seam"):
                    continue
                pts = [mw @ mesh.vertices[i].co for i in tri.vertices]
                normal = (pts[1] - pts[0]).cross(pts[2] - pts[0])
                out[frozenset(_round(p) for p in pts)] = normal
        finally:
            eval_obj.to_mesh_clear()
    return out


def check_seams(context, bsps):
    """Every seam triangle needs an identical triangle in exactly one other BSP, facing the
    other way. Returns [(severity, message, bsp_name)]."""
    per = {b.name: seam_triangles(context, b) for b in bsps}
    out = []
    for name, tris in per.items():
        unmatched = same_way = 0
        for key, normal in tris.items():
            hits = [other for other in per if other != name and key in per[other]]
            if len(hits) != 1:
                unmatched += 1
            elif per[hits[0]][key].dot(normal) > 0:
                same_way += 1
        if unmatched:
            out.append(('ERROR', "%d seam triangles in %s have no identical partner in another BSP" % (unmatched, name), name))
        if same_way:
            out.append(('ERROR', "%d seam triangles in %s face the same way as their partner (each side must face into its own BSP)" % (same_way, name), name))
    return out


CLASSES = (BANANA_OT_build_sky_shell, BANANA_OT_mirror_seam)
