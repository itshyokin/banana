"""Headless tests for sky shells, seams and limit meters: python tests/test_phase2.py"""

import os
import sys
import tempfile

import bpy
import bmesh  # noqa: E402
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banana  # noqa: E402
from banana import bsp as bsp_mod, export, limits, sky, validate  # noqa: E402

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
    s = bpy.context.scene.banana
    s.export_root = tempfile.mkdtemp(prefix="banana_")
    return s


def terrain(name, bsp, x0, x1, bumps=True, segs=8):
    """Height-field grid from x0..x1, y -10..10, normals up."""
    mesh = bpy.data.meshes.new(name)
    verts, faces = [], []
    for j in range(segs + 1):
        for i in range(segs + 1):
            x = x0 + (x1 - x0) * i / segs
            y = -10 + 20 * j / segs
            z = (((i * 7 + j * 3) % 5) * 0.4) if bumps and 0 < i < segs else 0.0
            verts.append((x, y, z))
    for j in range(segs):
        for i in range(segs):
            a = j * (segs + 1) + i
            faces.append((a, a + 1, a + segs + 2, a + segs + 1))
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(bpy.data.materials.get("ground") or bpy.data.materials.new("ground"))
    obj = bpy.data.objects.new(name, mesh)
    bsp_mod.sub_collections(bsp, 'STRUCTURE')[0].objects.link(obj)
    return obj


def closed_volume(context, bsp):
    """Signed volume of the BSP's structure: negative when every face points inward."""
    bm = sky._world_bmesh(context, bsp_mod.objects_for_role(bsp, 'STRUCTURE'), 1e-4)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    vol = 0.0
    for f in bm.faces:
        a, b, c = (v.co for v in f.verts)
        vol += a.dot(b.cross(c)) / 6.0
    bm.free()
    return vol


def errors(res):
    return [i for i in res.items if i[0] == 'ERROR']


def test_single_shell():
    print("sky shell seals one terrain")
    s = reset()
    ctx = bpy.context
    bsp = bsp_mod.create_bsp(ctx.scene, "bsp_a")
    s.active_bsp = bsp
    terrain("ground_a", bsp, -10, 10)
    res = validate.validate_bsp(ctx, bsp)
    check(any("open edges" in e[1] for e in errors(res)), "open terrain fails validation first")

    check(bpy.ops.banana.build_sky_shell(all_bsps=True, auto_seams=True) == {'FINISHED'}, "build sky shell runs")
    shell = [o for o in bsp_mod.objects_for_role(bsp, 'STRUCTURE') if o.get(sky.SHELL_KEY)]
    check(len(shell) == 1, "one shell object")
    check(abs(s.sky_height - (1.6 + 30.0)) < 1e-4, "auto sky height 30 m above the top of the terrain (%s)" % s.sky_height)
    res = validate.validate_bsp(ctx, bsp)
    check(not errors(res), "sealed after shell: %s" % errors(res))
    check(closed_volume(ctx, bsp) < 0, "every face points inward")
    names = {m.name for m in shell[0].data.materials}
    check(names == {"+sky"}, "shell uses +sky only (%s)" % names)

    written, _r = export.export_bsp(ctx, bsp)
    text = open(written[0], encoding="utf-8").read()
    check('"+sky0"' in text, "+sky exports as +sky0")

    bpy.ops.banana.build_sky_shell(all_bsps=True, auto_seams=True)
    check(len([o for o in bsp_mod.objects_for_role(bsp, 'STRUCTURE') if o.get(sky.SHELL_KEY)]) == 1, "rebuilding replaces the old shell")


def test_two_bsps_seam():
    print("two BSPs meeting at a border get matching seams")
    s = reset()
    ctx = bpy.context
    a = bsp_mod.create_bsp(ctx.scene, "bsp_a")
    b = bsp_mod.create_bsp(ctx.scene, "bsp_b")
    terrain("ground_a", a, -20, 0)
    terrain("ground_b", b, 0, 20)
    bpy.ops.banana.build_sky_shell(all_bsps=True, auto_seams=True)
    for bsp in (a, b):
        res = validate.validate_bsp(ctx, bsp)
        check(not errors(res), "%s sealed: %s" % (bsp.name, errors(res)))
        check(closed_volume(ctx, bsp) < 0, "%s faces inward" % bsp.name)
    seams = sky.check_seams(ctx, [a, b])
    check(not seams, "seams match between BSPs: %s" % seams)
    check(len(sky.seam_triangles(ctx, a)) == 16, "16 seam triangles on the shared border")
    written_a, _r = export.export_bsp(ctx, a)
    written_b, _r = export.export_bsp(ctx, b)
    ta, tb = open(written_a[0]).read(), open(written_b[0]).read()
    ma, mb = a.banana.seam_material, b.banana.seam_material
    check(ma is not None and mb is not None and ma is not mb, "each BSP got its own seam material")
    ma.name, mb.name = "+seam:my_a", "+seam:my_b"  # the user names them
    written_a, _r = export.export_bsp(ctx, a)
    written_b, _r = export.export_bsp(ctx, b)
    ta, tb = open(written_a[0]).read(), open(written_b[0]).read()
    check('"+seam:my_a"' in ta and '"+seam:my_b"' in tb and "my_b" not in ta,
          "export writes the names the user chose")

    # break the edge match: nudge a border vertex in B, rebuild, seams must complain
    g = bpy.data.objects["ground_b"]
    g.data.vertices[9 * 4].co.x += 0.3  # first column of row 4 sits on x = 0
    try:
        bpy.ops.banana.build_sky_shell(all_bsps=True, auto_seams=True)
        check(False, "shell build reports the misaligned border")
    except RuntimeError as err:  # error reports raise in background mode
        check("line up" in str(err), "shell build reports the misaligned border")
    seams = sky.check_seams(ctx, [a, b]) + sky.check_border_alignment(ctx, [a, b])
    check(bool(seams), "a mismatched border is reported: %s" % [m for _s, m, _b in seams])

    bpy.ops.banana.validate(all_bsps=True)
    check(any("line up" in p.message for p in ctx.scene.banana.problems), "Validate shows the border problem in the list")


def test_mirror_seam():
    print("mirrored seam objects")
    s = reset()
    ctx = bpy.context
    a = bsp_mod.create_bsp(ctx.scene, "bsp_a")
    b = bsp_mod.create_bsp(ctx.scene, "bsp_b")
    mesh = bpy.data.meshes.new("door")
    mesh.from_pydata([(0, -2, 0), (0, 2, 0), (0, 2, 3), (0, -2, 3), (0, 0, 4)], [], [(0, 1, 2, 4, 3)])
    mesh.materials.append(bpy.data.materials.new("+seam:hall"))
    door = bpy.data.objects.new("door", mesh)
    bsp_mod.sub_collections(a, 'STRUCTURE')[0].objects.link(door)
    for o in ctx.selected_objects:
        o.select_set(False)
    door.select_set(True)
    check(bpy.ops.banana.mirror_seam(target="bsp_b") == {'FINISHED'}, "mirror runs")
    partner = [o for o in bsp_mod.objects_for_role(b, 'STRUCTURE') if o.get(sky.SEAM_SOURCE_KEY)]
    check(len(partner) == 1, "partner made in the other BSP")
    check(not sky.check_seams(ctx, [a, b]), "mirrored seam matches and faces the other way")
    mats = partner[0].data.materials
    check(all(m is not None and not m.is_evaluated for m in mats), "partner uses the real material, not a temporary copy (crash fix)")

    pm = partner[0].data.materials[0]
    check(pm is not door.data.materials[0], "mirrored side has its own seam material to rename")
    pm.name = "+seam:side_b"
    wa, _r = export.export_bsp(ctx, a)
    wb, _r = export.export_bsp(ctx, b)
    check('"+seam:hall"' in open(wa[0]).read() and '"+seam:side_b"' in open(wb[0]).read(),
          "each side exports with its own name")
    door.location.y = 1.0  # move the original; export re-syncs the partner
    bpy.ops.banana.export(all_bsps=True)
    check(not sky.check_seams(ctx, [a, b]), "partner follows the original after export")
    check(partner[0].data.materials[0].name == "+seam:side_b", "re-sync keeps the name you gave the mirrored side")


def test_meters():
    print("limit meters")
    s = reset()
    ctx = bpy.context
    bsp = bsp_mod.create_bsp(ctx.scene, "bsp_a")
    s.active_bsp = bsp
    terrain("ground_a", bsp, -10, 10, segs=10)
    limits.recount(ctx, everything=True)
    r = limits.results(bsp)
    check(r["tris"] == 200 and r["verts"] == 121, "terrain counted: %s" % r)
    check(abs(r["extent"] - 10 * s.scale() / 100.0) < 0.01, "world extent in world units (%.2f)" % r["extent"])
    ctx.scene.banana_limits.tris = 100
    check(r["tris"] / ctx.scene.banana_limits.tris > 1.0, "over-budget detected")
    # only changed objects are recounted
    other = terrain("ground_b", bsp, 20, 30, segs=2)
    limits._dirty.add(other.name)
    limits.recount(ctx)
    check(limits.results(bsp)["tris"] == 208, "incremental recount picks up new geometry")


if __name__ == "__main__":
    test_single_shell()
    test_two_bsps_seam()
    test_mirror_seam()
    test_meters()
    print("\n%s" % ("ALL PASSED" if not FAILS else "%d FAILED" % len(FAILS)))
    sys.exit(1 if FAILS else 0)
