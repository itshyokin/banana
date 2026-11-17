"""Turn a Banana BSP collection into .ASS files, and optionally run Tool on them."""

import getpass
import os
import random
import socket
import subprocess

import bpy
import numpy as np
from mathutils import Matrix

from . import ass_writer, bsp as bsp_mod, naming
from .props import prefs

UID_KEY = "banana_uid"
WELD_DIGITS = 6  # rounding used to share identical vertices


# ---------------------------------------------------------------- materials

def bsp_file_name(bsp):
    """The .ass file name (without extension) = the BSP tag name Tool will create."""
    return bpy.path.clean_name(bsp.name)


def material_name(mat, bsp):
    if mat is None:
        return None
    name = naming.strip_suffix(mat.name)
    if name.startswith("+seam"):
        # c20: the seam material name must match the BSP it ends up in, so each half of a
        # pair is named after its own BSP no matter what the Blender material is called
        return "+seam:" + bsp_file_name(bsp)
    return naming.sky_material(name, bsp.banana.sky_index)


# ---------------------------------------------------------------- meshes

def mesh_object(obj, depsgraph, bake, scene, bsp, force_material=None):
    """Read one evaluated mesh into an ass_writer.MeshObject.

    bake: 4x4 matrix applied to positions (scale, and for structure the full
    world transform). Normals use its inverse-transpose; mirrored transforms
    get their winding flipped so faces keep pointing the right way.
    Returns (MeshObject, faces_without_material)."""
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    result = ass_writer.MeshObject()
    try:
        mesh.calc_loop_triangles()
        n_tris = len(mesh.loop_triangles)
        if n_tris == 0:
            return result, 0
        n_loops = len(mesh.loops)

        # material slot -> ASS material index
        if force_material:
            forced = scene.material_index(force_material)
            slot_map = np.full(max(1, len(eval_obj.material_slots)), forced, np.int64)
        else:
            slot_map = np.full(max(1, len(eval_obj.material_slots)), -1, np.int64)
            for i, slot in enumerate(eval_obj.material_slots):
                name = material_name(slot.material, bsp)
                if name:
                    slot_map[i] = scene.material_index(name)
        tri_mat = np.empty(n_tris, np.int32)
        mesh.loop_triangles.foreach_get("material_index", tri_mat)
        in_range = tri_mat < len(slot_map)
        mats = np.where(in_range, slot_map[np.clip(tri_mat, 0, len(slot_map) - 1)], -1)
        if force_material:
            mats[:] = forced
        missing = int(np.count_nonzero(mats == -1))

        # per-corner data
        corner = np.empty(n_tris * 3, np.int32)
        mesh.loop_triangles.foreach_get("loops", corner)
        loop_vert = np.empty(n_loops, np.int32)
        mesh.loops.foreach_get("vertex_index", loop_vert)
        co = np.empty(len(mesh.vertices) * 3, np.float32)
        mesh.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3).astype(np.float64)
        cn = np.empty(n_loops * 3, np.float32)
        mesh.corner_normals.foreach_get("vector", cn)
        cn = cn.reshape(-1, 3).astype(np.float64)

        m = np.array(bake, dtype=np.float64)
        nm = np.array(bake.to_3x3().inverted_safe().transposed(), dtype=np.float64)
        cv = loop_vert[corner]
        pos = co[cv] @ m[:3, :3].T + m[:3, 3]
        nrm = cn[corner] @ nm.T
        length = np.linalg.norm(nrm, axis=1, keepdims=True)
        nrm = nrm / np.where(length > 0, length, 1.0)

        uv_cols = []
        for layer in mesh.uv_layers:
            arr = np.empty(n_loops * 2, np.float32)
            layer.data.foreach_get("uv", arr)
            uv_cols.append(arr.reshape(-1, 2)[corner].astype(np.float64))
        uvs = np.hstack(uv_cols) if uv_cols else np.zeros((len(corner), 0))

        color_attr = mesh.color_attributes.active_color
        if color_attr is not None:
            arr = np.empty(len(color_attr.data) * 4, np.float32)
            color_attr.data.foreach_get("color", arr)
            arr = arr.reshape(-1, 4)[:, :3].astype(np.float64)
            colors = arr[cv] if color_attr.domain == 'POINT' else arr[corner]
        else:
            colors = np.zeros((len(corner), 3))

        # share identical corners
        key = np.hstack((np.round(pos, WELD_DIGITS), np.round(nrm, 4), np.round(uvs, 6), np.round(colors, 4)))
        _u, first, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
        inverse = inverse.reshape(-1)
        n_uv = uvs.shape[1] // 2
        for i in first:
            result.vertices.append(ass_writer.Vertex(
                tuple(pos[i]), tuple(nrm[i]), tuple(colors[i]),
                tuple((uvs[i, 2 * k], uvs[i, 2 * k + 1]) for k in range(n_uv))))
        tris = inverse.reshape(-1, 3)
        if np.linalg.det(m[:3, :3]) < 0.0:
            tris = tris[:, ::-1]  # mirrored: keep faces pointing the same way
        result.triangles = [(int(mt), int(a), int(b), int(c)) for mt, (a, b, c) in zip(mats, tris)]
    finally:
        eval_obj.to_mesh_clear()
    return result, missing


def ensure_uid(obj, used):
    uid = obj.get(UID_KEY)
    if not isinstance(uid, int) or uid <= 0 or uid in used:
        uid = random.randint(1, 2**31 - 1)
        while uid in used:
            uid = random.randint(1, 2**31 - 1)
        obj[UID_KEY] = uid  # duplicated objects copy the id, so collisions get a fresh one
    used.add(uid)
    return uid


def instance_key(obj):
    """Placements that can share one ASS object (one instance definition)."""
    if len(obj.modifiers):
        return ("unique", obj.name)
    mats = tuple(s.material.name if s.material else "" for s in obj.material_slots)
    return ("mesh", obj.data.name, mats)


# ---------------------------------------------------------------- scenes

class BuildReport:
    def __init__(self):
        self.warnings = []
        self.missing_material_faces = 0


def add_baked(scene, objs, depsgraph, scale_mat, bsp, used_uids, report, force_material=None):
    for obj in objs:
        mobj, missing = mesh_object(obj, depsgraph, scale_mat @ obj.matrix_world, scene, bsp, force_material)
        report.missing_material_faces += missing
        if not mobj.triangles:
            continue
        scene.objects.append(mobj)
        if not hasattr(scene, "_names"):
            scene._names = set()
        name = naming.structure_name(obj.name, scene._names)
        scene.instances.append(ass_writer.Instance(name, len(scene.objects) - 1, ensure_uid(obj, used_uids)))


def add_instances(scene, objs, depsgraph, scale, scale_mat, bsp, used_uids, report):
    defs = {}
    for obj in objs:
        loc, rot, sca = obj.matrix_world.decompose()
        if max(sca) - min(sca) > 1e-4:
            report.warnings.append("%s has non-uniform scale; Halo keeps only X" % obj.name)
        key = instance_key(obj)
        if key not in defs:
            mobj, missing = mesh_object(obj, depsgraph, scale_mat, scene, bsp)
            report.missing_material_faces += missing
            if not mobj.triangles:
                defs[key] = None
                continue
            scene.objects.append(mobj)
            defs[key] = len(scene.objects) - 1
        if defs[key] is None:
            continue
        scene.instances.append(ass_writer.Instance(
            naming.instance_name(obj.name), defs[key], ensure_uid(obj, used_uids),
            rotation=(rot.x, rot.y, rot.z, rot.w),
            translation=tuple(v * scale for v in loc),
            scale=sca.x,
        ))
    return sum(1 for v in defs.values() if v is not None)


def build_bsp_scenes(context, bsp):
    """Returns (structure_scene, design_scene_or_None, BuildReport, stats)."""
    settings = context.scene.banana
    scale = settings.scale()
    scale_mat = Matrix.Scale(scale, 4)
    depsgraph = context.evaluated_depsgraph_get()
    report = BuildReport()
    used = set()

    structure = ass_writer.AssScene()
    add_baked(structure, bsp_mod.objects_for_role(bsp, 'STRUCTURE'), depsgraph, scale_mat, bsp, used, report)
    portals = bsp_mod.objects_for_role(bsp, 'PORTALS')
    add_baked(structure, portals, depsgraph, scale_mat, bsp, used, report, force_material="+portal")
    instance_objs = bsp_mod.objects_for_role(bsp, 'INSTANCES')
    defs = add_instances(structure, instance_objs, depsgraph, scale, scale_mat, bsp, used, report)

    design = None
    design_objs = bsp_mod.objects_for_role(bsp, 'DESIGN')
    if design_objs:
        target = structure if settings.design_mode == 'COMBINED' else ass_writer.AssScene()
        add_baked(target, design_objs, depsgraph, scale_mat, bsp, used, report)
        if target is not structure:
            design = target

    stats = {
        "tris": sum(len(o.triangles) for o in structure.objects),
        "verts": sum(len(o.vertices) for o in structure.objects),
        "instances": len(instance_objs),
        "instance_defs": defs,
        "materials": len(structure.materials),
        "portals": len(portals),
    }
    return structure, design, report, stats


def store_stats(bsp, stats):
    b = bsp.banana
    b.stat_tris = stats["tris"]
    b.stat_verts = stats["verts"]
    b.stat_instances = stats["instances"]
    b.stat_instance_defs = stats["instance_defs"]
    b.stat_materials = stats["materials"]
    b.stat_portals = stats["portals"]


# ---------------------------------------------------------------- paths

def h3ek_root(context):
    p = prefs(context)
    path = bpy.path.abspath(p.h3ek_path) if p and p.h3ek_path else ""
    return os.path.normpath(path) if path else ""


def level_dir(context):
    s = context.scene.banana
    if s.export_root:
        return os.path.normpath(bpy.path.abspath(s.export_root))
    root = h3ek_root(context)
    if not root:
        return ""
    return os.path.join(root, "data", "levels", s.level_type, s.level_name)


def ass_paths(context, bsp):
    base = level_dir(context)
    if not base:
        return None, None
    name = bsp_file_name(bsp)
    return (os.path.join(base, "structure", name + ".ass"),
            os.path.join(base, "structure_design", name + ".ass"))


def header():
    try:
        user = getpass.getuser()
    except Exception:
        user = "banana"
    try:
        device = socket.gethostname().upper()
    except Exception:
        device = "BANANA"
    return {"app_version": "%d.%d" % bpy.app.version[:2], "user": user, "device": device}


def export_bsp(context, bsp):
    """Writes the files. Returns (written_paths, BuildReport)."""
    structure, design, report, stats = build_bsp_scenes(context, bsp)
    store_stats(bsp, stats)
    s_path, d_path = ass_paths(context, bsp)
    if not s_path:
        raise RuntimeError("Set your H3EK folder in the add-on preferences, or an export folder override")
    if report.missing_material_faces:
        raise RuntimeError("%d faces in '%s' have no material; run Validate to find them" % (
            report.missing_material_faces, bsp.name))
    written = []
    os.makedirs(os.path.dirname(s_path), exist_ok=True)
    ass_writer.write_file(structure, s_path, **header())
    written.append(s_path)
    if design is not None:
        os.makedirs(os.path.dirname(d_path), exist_ok=True)
        ass_writer.write_file(design, d_path, **header())
        written.append(d_path)
    return written, report


# ---------------------------------------------------------------- Tool

def run_tool(context, ass_path, design=False):
    """Runs Tool's structure import. Returns (ok, output)."""
    root = h3ek_root(context)
    if not root:
        return False, "H3EK folder is not set in the add-on preferences."
    if os.name != 'nt':
        return False, "Tool only runs on Windows."
    tool = os.path.join(root, prefs(context).tool_exe)
    data = os.path.join(root, "data")
    rel = os.path.relpath(ass_path, data)
    if rel.startswith(".."):
        return False, "The .ass file is outside H3EK\\data, so Tool can't import it."
    cmd = [tool, "structure-design" if design else "structure", rel]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, errors="replace")
    output = "> %s\n%s%s" % (" ".join(cmd), proc.stdout, proc.stderr)
    failed = proc.returncode != 0 or "### ERROR" in output or "-ERROR-" in output
    return not failed, output


def log_tool(output):
    text = bpy.data.texts.get("Banana Tool Log") or bpy.data.texts.new("Banana Tool Log")
    text.write(output.rstrip() + "\n\n")


# ---------------------------------------------------------------- operators

def _bsps_to_export(context, all_bsps):
    if all_bsps:
        return [b for b in bsp_mod.find_bsps(context.scene) if b.banana.export_enabled]
    bsp = context.scene.banana.active_bsp
    return [bsp] if bsp else []


class BANANA_OT_export(bpy.types.Operator):
    """Export BSP(s) to .ASS (and run Tool if enabled)"""
    bl_idname = "banana.export"
    bl_label = "Export BSP"

    all_bsps: bpy.props.BoolProperty(name="All BSPs", default=False)

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bsps = _bsps_to_export(context, self.all_bsps)
        if not bsps:
            self.report({'ERROR'}, "No BSP to export")
            return {'CANCELLED'}
        from . import sky
        sky.sync_all_seams(context)  # mirrored seams always match their source
        exported = 0
        for bsp in bsps:
            try:
                written, report = export_bsp(context, bsp)
            except RuntimeError as err:
                self.report({'ERROR'}, str(err))
                return {'CANCELLED'}
            for warning in report.warnings[:10]:
                self.report({'WARNING'}, warning)
            exported += 1
            if context.scene.banana.run_tool_after_export:
                for i, path in enumerate(written):
                    ok, output = run_tool(context, path, design=(i == 1))
                    log_tool(output)
                    if not ok:
                        self.report({'ERROR'}, "Tool reported a problem with %s; see the 'Banana Tool Log' text" % os.path.basename(path))
                        return {'CANCELLED'}
        self.report({'INFO'}, "Exported %d BSP(s)" % exported)
        return {'FINISHED'}


class BANANA_OT_refresh_stats(bpy.types.Operator):
    """Recount triangles, instances and materials for the active BSP"""
    bl_idname = "banana.refresh_stats"
    bl_label = "Refresh Stats"

    def execute(self, context):
        bsp = context.scene.banana.active_bsp
        if not bsp:
            return {'CANCELLED'}
        _s, _d, _r, stats = build_bsp_scenes(context, bsp)
        store_stats(bsp, stats)
        return {'FINISHED'}


CLASSES = (BANANA_OT_export, BANANA_OT_refresh_stats)
