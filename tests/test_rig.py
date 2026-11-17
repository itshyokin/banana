"""Headless tests for Rig Convert: python tests/test_rig.py"""

import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banana  # noqa: E402
from banana import rig as rig_mod  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        banana.register()
    except ValueError:
        pass


def armature(name, bones):
    """bones: [(name, head, tail, parent)]"""
    data = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    for bname, head, tail, parent in bones:
        eb = data.edit_bones.new(bname)
        eb.head, eb.tail = head, tail
        if parent:
            eb.parent = data.edit_bones[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    return obj


REACH = [
    ("b_pelvis", (0, 0, 1.0), (0, 0, 1.2), None),
    ("b_spine", (0, 0, 1.5), (0, 0, 1.7), "b_pelvis"),
    ("b_l_upperarm", (0.3, 0, 1.8), (0.6, 0, 1.8), "b_spine"),
    ("b_l_forearm", (0.7, 0, 1.8), (0.9, 0, 1.8), "b_l_upperarm"),
    ("b_l_hand", (1.0, 0, 1.8), (1.1, 0, 1.8), "b_l_forearm"),
    ("b_l_finger_extra", (1.15, 0, 1.8), (1.25, 0, 1.8), "b_l_hand"),
    ("b_r_forearm", (-0.7, 0, 1.8), (-0.9, 0, 1.8), "b_spine"),
]
H3 = [
    ("pelvis", (0, 0, 1.0), (0, 0, 1.2), None),
    ("spine1", (0, 0, 1.5), (0, 0, 1.7), "pelvis"),
    ("left_upperarm", (0.3, 0, 1.85), (0.6, 0, 1.85), "spine1"),
    ("l_forarm", (0.7, 0, 1.75), (0.9, 0, 1.7), "left_upperarm"),
    ("l_hand", (1.0, 0, 1.65), (1.1, 0, 1.65), "l_forarm"),
    ("r_forearm", (-0.7, 0, 1.8), (-0.9, 0, 1.8), "spine1"),
]


def body(name, points, weights, arm, extra_group=None):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(points, [], [])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    for i, w in enumerate(weights):
        for g, wt in w.items():
            vg = obj.vertex_groups.get(g) or obj.vertex_groups.new(name=g)
            vg.add([i], wt, 'REPLACE')
    if extra_group:
        vg = obj.vertex_groups.new(name=extra_group)
        vg.add([0], 0.5, 'REPLACE')
    obj.parent = arm
    obj.modifiers.new("Armature", 'ARMATURE').object = arm
    return obj


def weights_of(obj, i):
    names = {g.index: g.name for g in obj.vertex_groups}
    return {names[g.group]: g.weight for g in obj.data.vertices[i].groups}


def test_auto_map():
    print("auto map")
    m = rig_mod.auto_map([b[0] for b in REACH], [b[0] for b in H3])
    check(m["b_pelvis"] == "pelvis", "prefix stripped")
    check(m["b_spine"] == "spine1", "digit-insensitive match")
    check(m["b_l_upperarm"] == "left_upperarm", "left == l")
    check(m["b_l_forearm"] == "l_forarm", "fuzzy match (%s)" % m["b_l_forearm"])
    check(m["b_r_forearm"] == "r_forearm", "right side kept separate")
    check(m["b_l_finger_extra"] is None, "extra bone unmatched")


def test_convert():
    print("convert")
    reset()
    ctx = bpy.context
    src = armature("reach", REACH)
    tgt = armature("h3", H3)
    off = Vector((0.0, 0.1, 0.0))
    pts = [
        Vector((0.7, 0, 1.8)) + off,          # 0: forearm
        Vector((1.15, 0, 1.8)) + off,         # 1: extra finger bone
        Vector((0.0, 0, 1.0)) + off,          # 2: five influences
        Vector((5, 5, 5)),                    # 3: unweighted
        Vector((0.8, 0, 1.8)),                # 4: along the forearm
    ]
    w = [
        {"b_l_forearm": 1.0},
        {"b_l_finger_extra": 1.0},
        {"b_pelvis": 0.3, "b_spine": 0.25, "b_l_upperarm": 0.2, "b_l_forearm": 0.15, "b_r_forearm": 0.1},
        {},
        {"b_l_forearm": 1.0},
    ]
    obj = body("reach_body", pts, w, src, extra_group="region_keep")

    rig = ctx.scene.banana_rig
    rig.source, rig.target = src, tgt
    check(bpy.ops.banana.rig_auto_map() == {'FINISHED'}, "auto map runs")
    check(sum(1 for i in rig.bone_map if i.mode == 'MERGE') == 1, "one merge bone")
    check(bpy.ops.banana.rig_convert() == {'FINISHED'}, "convert runs")

    tnames = {b.name for b in tgt.data.bones}
    groups = {g.name for g in obj.vertex_groups}
    check(groups - tnames == {"region_keep"}, "only Halo 3 groups left (+ untouched others): %s" % sorted(groups))
    check(abs(weights_of(obj, 0).get("region_keep", 0) - 0.5) < 1e-6, "non-bone group untouched")
    check(weights_of(obj, 1) == {"l_hand": 1.0}, "extra bone merged into hand: %s" % weights_of(obj, 1))
    w2 = {k: v for k, v in weights_of(obj, 2).items() if k in tnames}
    check(len(w2) == 4 and abs(sum(w2.values()) - 1) < 1e-5, "trimmed to 4 influences and normalized: %s" % w2)
    check(not any(k in tnames for k in weights_of(obj, 3)), "unweighted vertex stays unweighted")

    p0 = obj.matrix_world @ obj.data.vertices[0].co
    check((p0 - (Vector((0.7, 0, 1.75)) + off)).length < 1e-4, "forearm vertex moved onto the H3 forearm joint (%s)" % str(tuple(p0)))
    p4 = obj.matrix_world @ obj.data.vertices[4].co
    d_h3 = (Vector((1.0, 0, 1.65)) - Vector((0.7, 0, 1.75))).normalized()
    d_v = (p4 - Vector((0.7, 0, 1.75))).normalized()
    check(d_v.dot(d_h3) > 0.999, "forearm rotated to follow the H3 bone direction")
    check(obj.parent is tgt and obj.modifiers[0].object is tgt, "rebound to the Halo 3 rig")
    check(any(l.severity == 'WARNING' and "no bone weights" in l.message for l in rig.report), "report lists unweighted vertices")

    # test pose toggles on and back to rest
    bpy.ops.banana.rig_test_pose()
    posed = tgt.pose.bones["left_upperarm"].rotation_quaternion.angle
    bpy.ops.banana.rig_test_pose()
    check(posed > 0.5 and tgt.pose.bones["left_upperarm"].rotation_quaternion.angle < 1e-6, "test pose on/off")


def test_copy_mode():
    print("copy weights from the Halo 3 body")
    reset()
    ctx = bpy.context
    src = armature("reach", REACH)
    tgt = armature("h3", H3)
    # Halo 3 body: a quad around the H3 hand, split hand/forearm weights
    hb = bpy.data.meshes.new("h3_body")
    hb.from_pydata([(0.95, -1, 1.6), (1.05, -1, 1.6), (1.05, 1, 1.7), (0.95, 1, 1.7)], [], [(0, 1, 2, 3)])
    h3_body = bpy.data.objects.new("h3_body", hb)
    ctx.scene.collection.objects.link(h3_body)
    for name, wt in (("l_hand", 0.7), ("l_forarm", 0.3)):
        h3_body.vertex_groups.new(name=name).add([0, 1, 2, 3], wt, 'REPLACE')
    obj = body("reach_body", [Vector((1.0, 0, 1.8))], [{"b_l_hand": 1.0}], src)

    rig = ctx.scene.banana_rig
    rig.source, rig.target, rig.weight_source = src, tgt, h3_body
    bpy.ops.banana.rig_auto_map()
    for item in rig.bone_map:
        if item.source == "b_l_hand":
            item.mode = 'COPY'
    for o in ctx.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.ops.banana.rig_convert()
    w = weights_of(obj, 0)
    check(abs(w.get("l_hand", 0) - 0.7) < 1e-4 and abs(w.get("l_forarm", 0) - 0.3) < 1e-4, "copied H3 weights %s" % w)
    check(h3_body.vertex_groups.get("l_hand") is not None, "Halo 3 body itself untouched")


if __name__ == "__main__":
    test_auto_map()
    test_convert()
    test_copy_mode()
    print("\n%s" % ("ALL PASSED" if not FAILS else "%d FAILED" % len(FAILS)))
    sys.exit(1 if FAILS else 0)
