"""Headless tests. Run with a Python that has the `bpy` module:

    python tests/run_tests.py

Builds small scenes, validates them, exports .ASS files and parses them back.
"""

import math
import os
import sys
import tempfile

import bpy
import bmesh
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banana  # noqa: E402
from banana import bsp as bsp_mod, export, validate  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# ------------------------------------------------------------ helpers

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        banana.register()
    except ValueError:
        pass  # already registered
    s = bpy.context.scene.banana
    s.export_root = tempfile.mkdtemp(prefix="banana_")
    s.level_name = "test_level"
    return s


def material(name):
    return bpy.data.materials.get(name) or bpy.data.materials.new(name)


def mesh_obj(name, build, coll, mats=("box_wall",)):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    build(bm)
    bm.to_mesh(mesh)
    bm.free()
    for m in mats:
        mesh.materials.append(material(m))
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    return obj


def room(bm, size=10.0):
    bmesh.ops.create_cube(bm, size=size)
    bmesh.ops.reverse_faces(bm, faces=bm.faces)  # normals point inward


def sub(bsp, role):
    return bsp_mod.sub_collections(bsp, role)[0]


def parse_ass(path):
    """Tiny tokenizer: drops ';' comment lines, keeps quoted strings whole."""
    tokens = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            if line.startswith('"'):
                tokens.append(line.strip('"'))
            else:
                tokens.extend(line.split())
    it = iter(tokens)
    nxt = lambda: next(it)
    data = {"version": int(nxt()), "app": nxt()}
    nxt(); nxt(); nxt()  # version string, user, device
    data["materials"] = []
    for _ in range(int(nxt())):
        name = nxt(); nxt()
        for _ in range(int(nxt())):
            nxt()
        data["materials"].append(name)
    data["objects"] = []
    for _ in range(int(nxt())):
        assert nxt() == "MESH"
        nxt(); nxt()
        verts = []
        for _ in range(int(nxt())):
            pos = [float(nxt()) for _ in range(3)]
            nrm = [float(nxt()) for _ in range(3)]
            [float(nxt()) for _ in range(3)]
            for _ in range(int(nxt())):
                nxt(); nxt()
            for _ in range(int(nxt())):
                nxt(); nxt(); nxt()
            verts.append((pos, nrm))
        tris = []
        for _ in range(int(nxt())):
            tris.append(tuple(int(nxt()) for _ in range(4)))
        data["objects"].append((verts, tris))
    data["instances"] = []
    for _ in range(int(nxt())):
        obj_index = int(nxt()); name = nxt(); uid = int(nxt()); parent = int(nxt()); nxt()
        rot = [float(nxt()) for _ in range(4)]
        loc = [float(nxt()) for _ in range(3)]
        scale = float(nxt())
        [nxt() for _ in range(8)]
        data["instances"].append(dict(obj=obj_index, name=name, uid=uid, parent=parent, rot=rot, loc=loc, scale=scale))
    rest = list(it)
    assert not rest, "trailing tokens: %r" % rest[:5]
    return data


def problems(res, severity='ERROR'):
    return [i for i in res.items if i[0] == severity]


# ------------------------------------------------------------ tests

def test_sealed_room_with_props():
    print("sealed room + props + design + portal")
    s = reset()
    ctx = bpy.context
    bsp = bsp_mod.create_bsp(ctx.scene, "bsp_a")
    s.active_bsp = bsp
    check(len(bsp.children) == 4, "BSP template has 4 sub-collections")

    mesh_obj("room", room, sub(bsp, 'STRUCTURE'))

    master = mesh_obj("%tree", lambda bm: bmesh.ops.create_cone(
        bm, cap_ends=True, segments=6, radius1=1, radius2=0, depth=3), sub(bsp, 'INSTANCES'), mats=("tree_bark",))
    painted = bpy.data.collections.new("trees_painted")  # nested, no role: inherits Instances
    sub(bsp, 'INSTANCES').children.link(painted)
    for i in range(3):
        copy = master.copy()  # linked duplicate: shares mesh data
        copy.location = (i * 2.0, 1.0, -3.0)
        copy.rotation_euler = (0, 0, math.radians(30 * i))
        copy.scale = (1.5, 1.5, 1.5)
        painted.objects.link(copy)

    soft = mesh_obj("ceiling", lambda bm: bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=4),
                    sub(bsp, 'DESIGN'), mats=("+soft_ceiling:main",))
    soft.location.z = 4
    mesh_obj("portal_mid", lambda bm: bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=4),
             sub(bsp, 'PORTALS'), mats=())

    res = validate.validate_bsp(ctx, bsp)
    check(not problems(res), "validation finds no errors (%s)" % problems(res))

    written, report = export.export_bsp(ctx, bsp)
    check(len(written) == 2, "writes structure + structure-design files")
    check(written[0].endswith(os.path.join("structure", "bsp_a.ass")), "structure path")
    check(written[1].endswith(os.path.join("structure-design", "bsp_a.ass")), "design path")

    a = parse_ass(written[0])
    check(a["version"] == 7, "ASS version 7")
    check(a["instances"][0]["name"] == "Scene Root" and a["instances"][0]["obj"] == -1, "Scene Root first")
    names = [i["name"] for i in a["instances"]]
    tree_insts = [i for i in a["instances"] if i["name"].startswith("%tree")]
    check(len(tree_insts) == 4, "4 tree placements (%s)" % names)
    check(len({i["obj"] for i in tree_insts}) == 1, "all trees share one instance definition")
    check(len({i["uid"] for i in a["instances"][1:]}) == len(a["instances"]) - 1, "unique ids are unique")
    check(all(i["parent"] == 0 for i in a["instances"][1:]), "everything parents to Scene Root")
    check(sorted(a["materials"]) == ["+portal", "box_wall", "tree_bark"], "materials %s" % a["materials"])
    scale = bpy.context.scene.banana.scale()
    t1 = [i for i in tree_insts if i["name"].endswith("_002")][0]  # second copy, x = 2
    check(abs(t1["loc"][0] - 2.0 * scale) < 1e-3 and abs(t1["scale"] - 1.5) < 1e-6, "instance transform scaled to ASS units")
    for verts, tris in a["objects"]:
        ok = all(0 <= v < len(verts) for t in tris for v in t[1:]) and all(0 <= t[0] < len(a["materials"]) for t in tris)
        if not ok:
            break
    check(ok, "all triangle indices valid")
    room_obj = a["objects"][a["instances"][1]["obj"]]
    check(len(room_obj[1]) == 12, "room has 12 triangles")
    xs = [v[0][0] for v in room_obj[0]]
    check(abs(max(xs) - 5.0 * scale) < 1e-3, "room baked to ASS scale")
    # winding agrees with normals (inward room)
    good = 0
    for _m, i0, i1, i2 in room_obj[1]:
        p0, p1, p2 = (Vector(room_obj[0][i][0]) for i in (i0, i1, i2))
        good += ((p1 - p0).cross(p2 - p0)).dot(Vector(room_obj[0][i0][1])) > 0
    check(good == 12, "triangle winding matches normals")

    d = parse_ass(written[1])
    check(d["materials"] == ["+soft_ceiling:main"], "design file holds the soft ceiling")
    check(bsp.banana.stat_instances == 4 and bsp.banana.stat_instance_defs == 1, "stats stored")


def test_open_and_ambiguous():
    print("open edges / ambiguous edges / overlaps / missing material")
    reset()
    ctx = bpy.context
    bsp = bsp_mod.create_bsp(ctx.scene, "bsp_b")

    def open_room(bm):
        room(bm)
        bmesh.ops.delete(bm, geom=[bm.faces[:][0]], context='FACES')
    mesh_obj("open_room", open_room, sub(bsp, 'STRUCTURE'))
    res = validate.validate_bsp(ctx, bsp)
    check(any("open edges" in p[1] and p[2] == "open_room" for p in problems(res)), "open edges reported on the right object")
    check(len(res.edges) == 4, "4 problem edges drawn")

    reset()
    bsp = bsp_mod.create_bsp(ctx.scene, "bsp_c")
    mesh_obj("room_a", room, sub(bsp, 'STRUCTURE'))
    mesh_obj("room_b", room, sub(bsp, 'STRUCTURE')).location.x = 10.0  # shares a wall
    res = validate.validate_bsp(ctx, bsp)
    check(any("ambiguous" in p[1] or "overlapping" in p[1] for p in problems(res)), "back-to-back shared wall reported")

    reset()
    bsp = bsp_mod.create_bsp(ctx.scene, "bsp_d")
    mesh_obj("bare", room, sub(bsp, 'STRUCTURE'), mats=())
    res = validate.validate_bsp(ctx, bsp)
    check(any("no material" in p[1] for p in problems(res)), "missing material is an error")
    try:
        export.export_bsp(ctx, bsp)
        check(False, "export refuses faces without material")
    except RuntimeError:
        check(True, "export refuses faces without material")


def test_mirror_and_sky():
    print("mirrored structure + sky index + duplicate material names")
    s = reset()
    ctx = bpy.context
    bsp = bsp_mod.create_bsp(ctx.scene, "bsp_e")
    bsp.banana.sky_index = 2
    obj = mesh_obj("mirrored", room, sub(bsp, 'STRUCTURE'), mats=("+sky",))
    obj.scale = (-1.0, 1.0, 1.0)
    dup = material("box_wall.001")
    obj.data.materials.append(dup)
    obj.data.polygons[0].material_index = 1
    written, _r = export.export_bsp(ctx, bsp)
    a = parse_ass(written[0])
    check(sorted(a["materials"]) == ["+sky2", "box_wall"], "+sky -> +sky2 and '.001' stripped (%s)" % a["materials"])
    verts, tris = a["objects"][0]
    good = 0
    for _m, i0, i1, i2 in tris:
        p0, p1, p2 = (Vector(verts[i][0]) for i in (i0, i1, i2))
        good += ((p1 - p0).cross(p2 - p0)).dot(Vector(verts[i0][1])) > 0
    check(good == len(tris), "mirrored object keeps winding consistent with normals")
    res = validate.validate_bsp(ctx, bsp)
    check(any("duplicate" in p[1] for p in problems(res, 'WARNING')), "duplicate material warned")


if __name__ == "__main__":
    test_sealed_room_with_props()
    test_open_and_ambiguous()
    test_mirror_and_sky()
    print("\n%s" % ("ALL PASSED" if not FAILS else "%d FAILED" % len(FAILS)))
    sys.exit(1 if FAILS else 0)
