"""Checks that catch what makes Tool fail, before you export."""

import bmesh
import bpy

from . import bsp as bsp_mod, naming
from .export import material_name

DEBUG_NAME = "BANANA_PROBLEMS"
DEBUG_COLLECTION = "Banana Debug"

# world-space edge segments per BSP, for drawing the problem overlay
_problem_edges = {}


class Results:
    def __init__(self, bsp):
        self.bsp = bsp
        self.items = []    # (severity, message, object_name, count)
        self.edges = []    # ((x, y, z), (x, y, z))

    def add(self, severity, message, object_name="", count=1):
        self.items.append((severity, message, object_name, count))

    @property
    def errors(self):
        return sum(1 for i in self.items if i[0] == 'ERROR')


def _faces_without_material(obj, mesh):
    slots = obj.material_slots
    count = 0
    for poly in mesh.polygons:
        i = poly.material_index
        if i >= len(slots) or slots[i].material is None:
            count += 1
    return count


def check_structure(context, bsp, objs, res):
    depsgraph = context.evaluated_depsgraph_get()
    scale = context.scene.banana.scale()
    weld = 0.01 / scale  # 0.01 ASS units, in Blender units

    bm = bmesh.new()
    src = bm.faces.layers.int.new("banana_src")
    for index, obj in enumerate(objs):
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        try:
            missing = _faces_without_material(eval_obj, mesh)
            if missing:
                res.add('ERROR', "%d faces have no material" % missing, obj.name, missing)
            before_v = len(bm.verts)
            before = len(bm.faces)
            bm.from_mesh(mesh)
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            bmesh.ops.transform(bm, matrix=obj.matrix_world, verts=bm.verts[before_v:])
            for face in bm.faces[before:]:
                face[src] = index
        finally:
            eval_obj.to_mesh_clear()

    if not bm.faces:
        res.add('ERROR', "The BSP has no structure geometry")
        bm.free()
        return

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=weld)

    def owner(edge):
        faces = edge.link_faces
        return objs[faces[0][src]].name if faces else ""

    def tally(edges, severity, label):
        per_obj = {}
        for e in edges:
            per_obj.setdefault(owner(e), 0)
            per_obj[owner(e)] += 1
            res.edges.append((tuple(e.verts[0].co), tuple(e.verts[1].co)))
        for name, count in per_obj.items():
            res.add(severity, "%d %s" % (count, label), name, count)

    tally([e for e in bm.edges if len(e.link_faces) == 1], 'ERROR', "open edges (the BSP must be sealed)")
    tally([e for e in bm.edges if len(e.link_faces) > 2], 'ERROR', "ambiguous edges (shared by 3+ faces)")
    loose = [e for e in bm.edges if not e.link_faces]
    if loose:
        res.add('WARNING', "%d loose edges with no faces (ignored by export)" % len(loose))

    tiny = weld * weld * 0.5
    degenerate = [f for f in bm.faces if f.calc_area() < tiny]
    for f in degenerate:
        for e in f.edges:
            res.edges.append((tuple(e.verts[0].co), tuple(e.verts[1].co)))
    per_obj = {}
    for f in degenerate:
        per_obj[objs[f[src]].name] = per_obj.get(objs[f[src]].name, 0) + 1
    for name, count in per_obj.items():
        res.add('ERROR', "%d degenerate (zero-area) faces" % count, name, count)

    seen = {}
    dupes = 0
    for f in bm.faces:
        key = frozenset(f.verts)
        if key in seen:
            dupes += 1
            for e in f.edges:
                res.edges.append((tuple(e.verts[0].co), tuple(e.verts[1].co)))
        else:
            seen[key] = f
    if dupes:
        res.add('ERROR', "%d overlapping duplicate faces" % dupes, "", dupes)

    bm.free()


def check_materials(context, bsp, objs, has_portals, res):
    reported = set()
    skies = set()
    for obj in objs:
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or mat.name in reported:
                continue
            reported.add(mat.name)
            final = material_name(mat, bsp)
            if final.startswith("+sky"):
                skies.add(final)
            if final == "+seam":
                res.add('WARNING', "Seam material '%s' still has the default name; rename it (e.g. +seam:<bsp name>)" % mat.name, obj.name)
            if naming.has_blender_suffix(mat.name):
                res.add('WARNING', "Material '%s' is a duplicate; it exports as '%s'" % (mat.name, final), obj.name)
            base = final.split(":")[0]
            if len(final) > naming.MAX_MATERIAL_NAME and not naming.is_special_material(final):
                res.add('WARNING', "Material '%s' is longer than 32 characters" % final, obj.name)
            if final != final.lower() and not naming.is_special_material(final):
                res.add('WARNING', "Material '%s' should be lowercase" % final, obj.name)
            if not naming.is_special_material(final) and base[-1:].isdigit():
                res.add('WARNING', "Material '%s' ends in a digit (Tool may warn about duplicate shaders); use letters for variants" % final, obj.name)
    if len(skies) > 1 and not has_portals:
        res.add('WARNING', "This BSP uses %s with no portals; a cluster can only see one sky" % ", ".join(sorted(skies)))


def check_instances(context, objs, res):
    depsgraph = context.evaluated_depsgraph_get()
    checked = set()
    for obj in objs:
        loc, rot, sca = obj.matrix_world.decompose()
        if max(sca) - min(sca) > 1e-4:
            res.add('WARNING', "Non-uniform scale; Halo keeps only the X scale", obj.name)
        if obj.data.name in checked:
            continue
        checked.add(obj.data.name)
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        try:
            missing = _faces_without_material(eval_obj, mesh)
            if missing:
                res.add('ERROR', "%d faces have no material" % missing, obj.name, missing)
            bm = bmesh.new()
            bm.from_mesh(mesh)
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
            open_edges = sum(1 for e in bm.edges if len(e.link_faces) == 1)
            bm.free()
            if open_edges:
                res.add('WARNING', "Instance mesh has %d open edges, so it won't have collision" % open_edges, obj.name, open_edges)
        finally:
            eval_obj.to_mesh_clear()


def validate_bsp(context, bsp):
    res = Results(bsp)
    structure = bsp_mod.objects_for_role(bsp, 'STRUCTURE')
    instances = bsp_mod.objects_for_role(bsp, 'INSTANCES')
    design = bsp_mod.objects_for_role(bsp, 'DESIGN')
    portals = bsp_mod.objects_for_role(bsp, 'PORTALS')
    check_structure(context, bsp, structure, res)
    check_materials(context, bsp, structure + instances + design, bool(portals), res)
    check_instances(context, instances, res)
    for obj in design:
        if not obj.material_slots or all(s.material is None for s in obj.material_slots):
            res.add('ERROR', "Design object has no material (use +soft_ceiling:name, +soft_kill:name, ...)", obj.name)
    return res


def store_results(scene, results_list):
    problems = scene.banana.problems
    problems.clear()
    _problem_edges.clear()
    for res in results_list:
        _problem_edges[res.bsp.name] = res.edges
        for severity, message, obj_name, count in res.items:
            item = problems.add()
            item.severity = severity
            item.message = message
            item.object_name = obj_name
            item.bsp_name = res.bsp.name
            item.count = count
    if not problems:
        item = problems.add()
        item.severity = 'INFO'
        item.message = "No problems found"


def build_problem_overlay(scene):
    edges = [seg for segs in _problem_edges.values() for seg in segs]
    coll = bpy.data.collections.get(DEBUG_COLLECTION)
    obj = bpy.data.objects.get(DEBUG_NAME)
    if not edges:
        if obj:
            bpy.data.objects.remove(obj)
        return None
    if coll is None:
        coll = bpy.data.collections.new(DEBUG_COLLECTION)
        scene.collection.children.link(coll)
    mesh = bpy.data.meshes.new(DEBUG_NAME)
    verts = []
    for a, b in edges:
        verts.extend((a, b))
    mesh.from_pydata(verts, [(i, i + 1) for i in range(0, len(verts), 2)], [])
    if obj is None:
        obj = bpy.data.objects.new(DEBUG_NAME, mesh)
        coll.objects.link(obj)
    else:
        old = obj.data
        obj.data = mesh
        bpy.data.meshes.remove(old)
    obj.show_in_front = True
    obj.display_type = 'WIRE'
    obj.color = (1.0, 0.1, 0.1, 1.0)
    obj.hide_select = True
    return obj


class BANANA_OT_validate(bpy.types.Operator):
    """Check the BSP(s) for open edges, ambiguous edges, bad materials and instance problems"""
    bl_idname = "banana.validate"
    bl_label = "Validate"

    all_bsps: bpy.props.BoolProperty(name="All BSPs", default=False)

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if self.all_bsps:
            bsps = bsp_mod.find_bsps(context.scene)
        else:
            bsps = [context.scene.banana.active_bsp] if context.scene.banana.active_bsp else []
        if not bsps:
            self.report({'ERROR'}, "No BSP selected")
            return {'CANCELLED'}
        from . import sky
        sky.sync_all_seams(context)
        results = [validate_bsp(context, b) for b in bsps]
        by_name = {r.bsp.name: r for r in results}
        everyone = bsp_mod.find_bsps(context.scene)
        for severity, message, bsp_name in sky.check_seams(context, everyone) + sky.check_border_alignment(context, everyone) + sky.check_overlaps(context, everyone):
            if bsp_name in by_name:
                by_name[bsp_name].add(severity, message)
        store_results(context.scene, results)
        build_problem_overlay(context.scene)
        errors = sum(r.errors for r in results)
        if errors:
            self.report({'WARNING'}, "%d errors found; problem edges are drawn in red (BANANA_PROBLEMS)" % errors)
        else:
            self.report({'INFO'}, "No errors found")
        return {'FINISHED'}


class BANANA_OT_clear_problems(bpy.types.Operator):
    """Remove the red problem overlay and clear the list"""
    bl_idname = "banana.clear_problems"
    bl_label = "Clear Problems"

    def execute(self, context):
        context.scene.banana.problems.clear()
        _problem_edges.clear()
        build_problem_overlay(context.scene)
        return {'FINISHED'}


class BANANA_OT_select_problem_object(bpy.types.Operator):
    """Select the object this problem belongs to"""
    bl_idname = "banana.select_problem_object"
    bl_label = "Select Object"

    object_name: bpy.props.StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.object_name)
        if obj is None:
            return {'CANCELLED'}
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


CLASSES = (BANANA_OT_validate, BANANA_OT_clear_problems, BANANA_OT_select_problem_object)
