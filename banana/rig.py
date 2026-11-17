"""Rig Convert: move a body skinned to one Halo skeleton (e.g. Reach) onto another
(e.g. Halo 3) without regrouping vertices by hand.

Workflow: import both models with your JMS importer, point Rig Convert at the
Halo 3 armature (target) and the Reach armature (source), Auto Map, fix the
table if needed, then Convert. Meshes are edited in place (only vertex groups,
the armature modifier and the parent change), so importer data such as regions
survives for the JMS export.
"""

import difflib
import json
import os
import re

import bpy
from bpy.props import (
    BoolProperty, CollectionProperty, EnumProperty, IntProperty,
    PointerProperty, StringProperty,
)
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

# ------------------------------------------------------------------ naming

PREFIXES = ("bip01_", "frame_", "bone_", "node_", "jnt_", "b_")
SIDES = {"left": "l", "lft": "l", "right": "r", "rt": "r"}


def normalize(name):
    n = re.sub(r"[\s.\-]+", "_", name.lower().strip())
    for prefix in PREFIXES:
        if n.startswith(prefix):
            n = n[len(prefix):]
            break
    return "_".join(SIDES.get(t, t) for t in n.split("_") if t)


def _side(norm):
    tokens = set(norm.split("_"))
    return tokens & {"l", "r"}


def auto_map(source_names, target_names):
    """source bone name -> target bone name (or None)."""
    norm_t = {}
    for t in target_names:
        norm_t.setdefault(normalize(t), t)
    nodigit_t = {}
    for n, t in norm_t.items():
        nodigit_t.setdefault(re.sub(r"\d+", "", n), t)
    result, taken = {}, set()
    pending = []
    for s in source_names:
        n = normalize(s)
        if s in target_names:
            result[s] = s
        elif n in norm_t:
            result[s] = norm_t[n]
        elif re.sub(r"\d+", "", n) in nodigit_t and re.sub(r"\d+", "", n) != n:
            result[s] = nodigit_t[re.sub(r"\d+", "", n)]
        else:
            pending.append((s, n))
            continue
        taken.add(result[s])
    for s, n in pending:  # fuzzy pass: same side only, never steal a matched target
        options = [k for k, t in norm_t.items() if t not in taken and _side(k) == _side(n)]
        close = difflib.get_close_matches(n, options, n=1, cutoff=0.82)
        if close:
            result[s] = norm_t[close[0]]
            taken.add(result[s])
        else:
            result[s] = None
    return result


# ------------------------------------------------------------------ settings

MODE_ITEMS = (
    ('MAP', "Map", "Weights go to the matched Halo 3 bone"),
    ('MERGE', "Merge", "Extra bone: weights merge into the nearest mapped parent"),
    ('COPY', "Copy", "Take this area's weights from the Halo 3 body instead"),
)


class BananaBoneMapItem(bpy.types.PropertyGroup):
    source: StringProperty(name="Reach Bone")
    target: StringProperty(name="Halo 3 Bone")
    mode: EnumProperty(name="Mode", items=MODE_ITEMS, default='MAP')


class BananaReportLine(bpy.types.PropertyGroup):
    severity: StringProperty()
    message: StringProperty()


def _is_armature(self, obj):
    return obj.type == 'ARMATURE'


def _is_mesh(self, obj):
    return obj.type == 'MESH'


class BananaRig(bpy.types.PropertyGroup):
    target: PointerProperty(name="Halo 3 Rig", type=bpy.types.Object, poll=_is_armature,
                            description="The skeleton the body should end up on")
    source: PointerProperty(name="Reach Rig", type=bpy.types.Object, poll=_is_armature,
                            description="The skeleton the body is skinned to now")
    weight_source: PointerProperty(name="Halo 3 Body", type=bpy.types.Object, poll=_is_mesh,
                                   description="Optional: Halo 3 body mesh used by bones set to Copy")
    bone_map: CollectionProperty(type=BananaBoneMapItem)
    bone_map_index: IntProperty()
    influence_limit: IntProperty(name="Max Influences", default=4, min=1, max=8)
    conform: EnumProperty(
        name="Conform",
        items=(
            ('FULL', "Positions + Directions", "Move and rotate each limb onto the Halo 3 bones"),
            ('POSITIONS', "Positions Only", "Only move joints onto the Halo 3 bone positions"),
            ('OFF', "Off", "Keep the body's shape exactly as it is"),
        ),
        default='FULL',
    )
    hide_source: BoolProperty(name="Hide Reach Rig After", default=True)
    report: CollectionProperty(type=BananaReportLine)


def settings(context):
    return context.scene.banana_rig


# ------------------------------------------------------------------ core

def _world_head(arm, bone):
    return arm.matrix_world @ bone.head_local


def resolve(source_arm, items):
    """Returns (weight_target, mode) per source bone. MERGE bones walk up their
    parents until they reach a bone with a target."""
    by_name = {i.source: i for i in items}
    out = {}
    for bone in source_arm.data.bones:
        item = by_name.get(bone.name)
        mode = item.mode if item else 'MERGE'
        b = bone
        target = None
        while b is not None:
            it = by_name.get(b.name)
            if it and it.mode in ('MAP', 'COPY') and it.target:
                target = it.target
                break
            b = b.parent
        out[bone.name] = (target, mode)
    return out


def bone_deforms(source_arm, target_arm, items, conform):
    """World-space matrix per source bone that carries the Reach rest pose onto
    the Halo 3 rest pose. Bones without their own target follow their parent."""
    by_name = {i.source: i for i in items}
    tbones = target_arm.data.bones
    own = {}
    for bone in source_arm.data.bones:
        it = by_name.get(bone.name)
        if not it or it.mode == 'MERGE' or not it.target or it.target not in tbones:
            continue
        sh = _world_head(source_arm, bone)
        th = _world_head(target_arm, tbones[it.target])
        rot = Matrix.Identity(4)
        if conform == 'FULL':
            for child in bone.children:
                cit = by_name.get(child.name)
                if cit and cit.mode != 'MERGE' and cit.target in tbones:
                    ds = _world_head(source_arm, child) - sh
                    dt = _world_head(target_arm, tbones[cit.target]) - th
                    if ds.length > 1e-6 and dt.length > 1e-6:
                        rot = ds.rotation_difference(dt).to_matrix().to_4x4()
                    break
        own[bone.name] = Matrix.Translation(th) @ rot @ Matrix.Translation(-sh)
    deforms = {}
    for bone in source_arm.data.bones:
        b = bone
        while b is not None and b.name not in own:
            b = b.parent
        deforms[bone.name] = own[b.name] if b is not None else Matrix.Identity(4)
    return deforms


def _read_weights(obj, bone_names):
    """vertex index -> {source bone: weight}, only for groups named after bones."""
    names = {g.index: g.name for g in obj.vertex_groups if g.name in bone_names}
    weights = [dict() for _ in obj.data.vertices]
    for v in obj.data.vertices:
        for g in v.groups:
            name = names.get(g.group)
            if name is not None and g.weight > 0.0:
                weights[v.index][name] = weights[v.index].get(name, 0.0) + g.weight
    return weights


class _BodySampler:
    """Nearest-surface weight lookup on the Halo 3 body, in world space."""

    def __init__(self, body, target_names):
        mesh = body.data
        mw = body.matrix_world
        self.verts = [mw @ v.co for v in mesh.vertices]
        self.polys = [list(p.vertices) for p in mesh.polygons]
        self.tree = BVHTree.FromPolygons(self.verts, self.polys)
        groups = {g.index: g.name for g in body.vertex_groups if g.name in target_names}
        self.weights = []
        for v in mesh.vertices:
            w = {}
            for g in v.groups:
                if g.group in groups and g.weight > 0.0:
                    w[groups[g.group]] = g.weight
            self.weights.append(w)

    def sample(self, point):
        loc, _n, index, _d = self.tree.find_nearest(point)
        if index is None:
            return {}
        out = {}
        total = 0.0
        for vi in self.polys[index]:
            k = 1.0 / max((self.verts[vi] - loc).length, 1e-6)
            total += k
            for name, w in self.weights[vi].items():
                out[name] = out.get(name, 0.0) + w * k
        s = sum(out.values())
        return {n: w / s for n, w in out.items()} if s > 0 else {}


def _limit(weights, limit):
    items = sorted(((w, n) for n, w in weights.items() if w > 1e-4), reverse=True)[:limit]
    total = sum(w for w, _n in items)
    return {n: w / total for w, n in items} if total > 0 else {}


def convert_mesh(obj, rig, deforms, resolved, sampler, stats):
    source, target = rig.source, rig.target
    src_names = set(b.name for b in source.data.bones)
    old = _read_weights(obj, src_names)
    mw = obj.matrix_world
    mw_inv = mw.inverted()

    # 1. conform the shape (every shape key gets the same move)
    if rig.conform != 'OFF':
        key_blocks = obj.data.shape_keys.key_blocks if obj.data.shape_keys else None
        layers = ([kb.data for kb in key_blocks] if key_blocks else []) + [obj.data.vertices]
        for layer in layers:
            for i, item in enumerate(layer):
                w = old[i]
                total = sum(w.values())
                if total <= 0.0:
                    continue
                p = mw @ item.co
                moved = Vector((0.0, 0.0, 0.0))
                for name, wt in w.items():
                    moved += (deforms[name] @ p) * (wt / total)
                item.co = mw_inv @ moved
        obj.data.update()

    # 2. new weights
    new = []
    for i, w in enumerate(old):
        total = sum(w.values())
        if total <= 0.0:
            stats["unweighted"] += 1
            new.append({})
            continue
        out, copy_part = {}, 0.0
        for name, wt in w.items():
            tgt, mode = resolved.get(name, (None, 'MERGE'))
            if mode == 'COPY' and sampler is not None:
                copy_part += wt / total
            elif tgt:
                out[tgt] = out.get(tgt, 0.0) + wt / total
            else:
                stats["lost"] += 1
        if copy_part > 0.0:
            for name, wt in sampler.sample(mw @ obj.data.vertices[i].co).items():
                out[name] = out.get(name, 0.0) + wt * copy_part
        if sum(1 for x in out.values() if x > 1e-4) > rig.influence_limit:
            stats["trimmed"] += 1
        new.append(_limit(out, rig.influence_limit))

    # 3. swap the groups (other groups are left alone)
    tgt_names = set(b.name for b in target.data.bones)
    for g in list(obj.vertex_groups):
        if g.name in src_names or g.name in tgt_names:
            obj.vertex_groups.remove(g)
    groups = {}
    for i, w in enumerate(new):
        for name, wt in w.items():
            g = groups.get(name) or obj.vertex_groups.new(name=name)
            groups[name] = g
            g.add([i], wt, 'REPLACE')

    # 4. rebind
    mods = [m for m in obj.modifiers if m.type == 'ARMATURE']
    for m in mods:
        if m.object in (source, None):
            m.object = target
    if not mods:
        obj.modifiers.new("Armature", 'ARMATURE').object = target
    if obj.parent is source:
        world = obj.matrix_world.copy()
        obj.parent = target
        obj.parent_type = 'OBJECT'
        obj.matrix_world = world


def meshes_for(context, source):
    picked = [o for o in context.selected_objects if o.type == 'MESH']
    if picked:
        return picked
    found = []
    for o in context.scene.objects:
        if o.type != 'MESH':
            continue
        if o.parent is source or any(m.type == 'ARMATURE' and m.object is source for m in o.modifiers):
            found.append(o)
    return found


def _report(rig, lines):
    rig.report.clear()
    for severity, message in lines:
        line = rig.report.add()
        line.severity = severity
        line.message = message


# ------------------------------------------------------------------ operators

def _check_rigs(op, rig):
    if not rig.source or not rig.target:
        op.report({'ERROR'}, "Pick both the Reach rig and the Halo 3 rig")
        return False
    if rig.source is rig.target:
        op.report({'ERROR'}, "The two rigs must be different objects")
        return False
    return True


class BANANA_OT_rig_auto_map(bpy.types.Operator):
    """Match Reach bones to Halo 3 bones by name; unmatched bones are set to Merge"""
    bl_idname = "banana.rig_auto_map"
    bl_label = "Auto Map"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = settings(context)
        if not _check_rigs(self, rig):
            return {'CANCELLED'}
        keep = {i.source: (i.target, i.mode) for i in rig.bone_map}
        mapping = auto_map([b.name for b in rig.source.data.bones], [b.name for b in rig.target.data.bones])
        rig.bone_map.clear()
        matched = 0
        for bone in rig.source.data.bones:
            item = rig.bone_map.add()
            item.source = bone.name
            item.target = mapping[bone.name] or ""
            item.mode = 'MAP' if item.target else 'MERGE'
            matched += bool(item.target)
        self.report({'INFO'}, "Matched %d of %d bones; the rest merge into their parents" % (
            matched, len(rig.bone_map)))
        return {'FINISHED'}


class BANANA_OT_rig_convert(bpy.types.Operator):
    """Move the selected (or all) Reach-skinned meshes onto the Halo 3 rig"""
    bl_idname = "banana.rig_convert"
    bl_label = "Match to Halo 3"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = settings(context)
        if not _check_rigs(self, rig):
            return {'CANCELLED'}
        if not rig.bone_map:
            bpy.ops.banana.rig_auto_map()
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        meshes = meshes_for(context, rig.source)
        if not meshes:
            self.report({'ERROR'}, "No meshes found: select the body meshes, or parent/skin them to the Reach rig")
            return {'CANCELLED'}
        tbones = rig.target.data.bones
        bad = [i.target for i in rig.bone_map if i.mode != 'MERGE' and i.target and i.target not in tbones]
        if bad:
            self.report({'ERROR'}, "These Halo 3 bones don't exist: %s" % ", ".join(sorted(set(bad))[:8]))
            return {'CANCELLED'}
        wants_copy = any(i.mode == 'COPY' for i in rig.bone_map)
        sampler = None
        lines = []
        if wants_copy:
            if rig.weight_source:
                sampler = _BodySampler(rig.weight_source, set(b.name for b in tbones))
            else:
                lines.append(('WARNING', "Copy bones need a Halo 3 Body; they were merged instead"))

        resolved = resolve(rig.source, rig.bone_map)
        if wants_copy and sampler is None:
            resolved = {k: (t, 'MERGE' if m == 'COPY' else m) for k, (t, m) in resolved.items()}
        deforms = bone_deforms(rig.source, rig.target, rig.bone_map, rig.conform)
        stats = {"unweighted": 0, "trimmed": 0, "lost": 0}
        for obj in meshes:
            if obj is rig.weight_source:
                continue
            convert_mesh(obj, rig, deforms, resolved, sampler, stats)
        if rig.hide_source:
            rig.source.hide_set(True)

        merged = [i.source for i in rig.bone_map if i.mode == 'MERGE']
        lines.insert(0, ('INFO', "Converted %d mesh(es)" % len(meshes)))
        if merged:
            lines.append(('INFO', "%d extra bones merged: %s" % (len(merged), ", ".join(merged[:6]) + ("..." if len(merged) > 6 else ""))))
        if stats["unweighted"]:
            lines.append(('WARNING', "%d vertices had no bone weights" % stats["unweighted"]))
        if stats["trimmed"]:
            lines.append(('INFO', "%d vertices trimmed to %d influences" % (stats["trimmed"], rig.influence_limit)))
        if stats["lost"]:
            lines.append(('ERROR', "%d weights had no Halo 3 bone to go to (map a root bone)" % stats["lost"]))
        _report(rig, lines)
        self.report({'INFO'}, lines[0][1])
        return {'FINISHED'}


TEST_POSE = (
    ("upperarm", 45), ("forearm", 60), ("thigh", -35), ("calf", 50), ("shin", 50),
    ("jaw", 20), ("mandible", 20), ("head", 20), ("neck", 15), ("spine", 10), ("hand", 30), ("foot", 20),
)
TEST_KEY = "banana_test_pose"


class BANANA_OT_rig_test_pose(bpy.types.Operator):
    """Bend limbs on the Halo 3 rig to check deformation; run again to return to rest"""
    bl_idname = "banana.rig_test_pose"
    bl_label = "Test Pose"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = settings(context).target
        if not arm:
            self.report({'ERROR'}, "Pick the Halo 3 rig first")
            return {'CANCELLED'}
        posed = bool(arm.get(TEST_KEY))
        import math
        for pb in arm.pose.bones:
            name = normalize(pb.name)
            angle = next((a for key, a in TEST_POSE if key in name), None)
            if angle is None:
                continue
            pb.rotation_mode = 'QUATERNION'
            if posed:
                pb.rotation_quaternion = (1, 0, 0, 0)
            else:
                pb.rotation_quaternion = Matrix.Rotation(math.radians(angle), 4, 'X').to_quaternion()
        arm[TEST_KEY] = not posed
        return {'FINISHED'}


def presets_dir():
    return bpy.utils.user_resource('CONFIG', path=os.path.join("banana", "rig_presets"), create=True)


def _preset_items(self, context):
    try:
        files = sorted(f[:-5] for f in os.listdir(presets_dir()) if f.endswith(".json"))
    except OSError:
        files = []
    return [(f, f, "") for f in files] or [('NONE', "No presets saved", "")]


class BANANA_OT_rig_save_preset(bpy.types.Operator):
    """Save the bone table so this pair of rigs maps instantly next time"""
    bl_idname = "banana.rig_save_preset"
    bl_label = "Save Bone Map"

    name: StringProperty(name="Name", default="Reach Elite to H3 Elite")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        rig = settings(context)
        data = [{"source": i.source, "target": i.target, "mode": i.mode} for i in rig.bone_map]
        path = os.path.join(presets_dir(), bpy.path.clean_name(self.name) + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"name": self.name, "map": data}, fh, indent=1)
        self.report({'INFO'}, "Saved %s" % os.path.basename(path))
        return {'FINISHED'}


class BANANA_OT_rig_load_preset(bpy.types.Operator):
    """Load a saved bone table"""
    bl_idname = "banana.rig_load_preset"
    bl_label = "Load Bone Map"
    bl_property = "preset"

    preset: EnumProperty(name="Preset", items=_preset_items)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if self.preset == 'NONE':
            return {'CANCELLED'}
        with open(os.path.join(presets_dir(), self.preset + ".json"), encoding="utf-8") as fh:
            data = json.load(fh)
        rig = settings(context)
        rig.bone_map.clear()
        for entry in data.get("map", []):
            item = rig.bone_map.add()
            item.source = entry.get("source", "")
            item.target = entry.get("target", "")
            item.mode = entry.get("mode", 'MAP') if entry.get("mode") in ('MAP', 'MERGE', 'COPY') else 'MAP'
        return {'FINISHED'}


# ------------------------------------------------------------------ UI

class BANANA_UL_bone_map(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        rig = settings(context)
        row = layout.row(align=True)
        row.label(text=item.source, icon='BONE_DATA')
        if rig.target and item.mode != 'MERGE':
            row.prop_search(item, "target", rig.target.data, "bones", text="")
        elif item.mode == 'MERGE':
            row.label(text="(into parent)")
        row.prop(item, "mode", text="")


class BANANA_PT_rig(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Banana"
    bl_label = "Rig Convert"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        rig = settings(context)
        layout = self.layout
        col = layout.column(align=True)
        col.prop(rig, "source")
        col.prop(rig, "target")
        col.prop(rig, "weight_source")

        row = layout.row(align=True)
        row.operator("banana.rig_auto_map", icon='LINKED')
        row.operator("banana.rig_load_preset", text="", icon='IMPORT')
        row.operator("banana.rig_save_preset", text="", icon='EXPORT')
        if rig.bone_map:
            layout.template_list("BANANA_UL_bone_map", "", rig, "bone_map", rig, "bone_map_index", rows=6)

        col = layout.column(align=True)
        col.prop(rig, "conform")
        col.prop(rig, "influence_limit")
        col.prop(rig, "hide_source")
        layout.label(text="Uses selected meshes, or all meshes on the Reach rig")
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("banana.rig_convert", icon='ARMATURE_DATA')
        row.operator("banana.rig_test_pose", text="", icon='POSE_HLT')

        if rig.report:
            box = layout.box()
            icons = {'ERROR': 'ERROR', 'WARNING': 'INFO', 'INFO': 'CHECKMARK'}
            for line in rig.report:
                box.label(text=line.message, icon=icons.get(line.severity, 'DOT'))


CLASSES = (
    BananaBoneMapItem, BananaReportLine, BananaRig,
    BANANA_OT_rig_auto_map, BANANA_OT_rig_convert, BANANA_OT_rig_test_pose,
    BANANA_OT_rig_save_preset, BANANA_OT_rig_load_preset,
    BANANA_UL_bone_map, BANANA_PT_rig,
)


def register():
    bpy.types.Scene.banana_rig = PointerProperty(type=BananaRig)


def unregister():
    del bpy.types.Scene.banana_rig
