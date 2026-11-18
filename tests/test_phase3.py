"""Headless tests for terrain BSPs, the terrain brush math and blend maps:
python tests/test_phase3.py"""

import os
import sys
import tempfile

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banana  # noqa: E402
from banana import blendmap, brush, bsp as bsp_mod, export, naming, sky, terrain, validate  # noqa: E402

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


def select(active, *others):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in (active,) + others:
        if o is not None:
            o.select_set(True)
    bpy.context.view_layer.objects.active = active


def errors(res):
    return [i for i in res.items if i[0] == 'ERROR']


def border_heights(obj):
    mw = obj.matrix_world
    out = {}
    for i in terrain.border_indices(obj.data):
        w = mw @ obj.data.vertices[i].co
        out[terrain._key(w.x, w.y)] = w.z
    return out


def test_terrain_bsps():
    print("terrain BSPs, sky, match edge, generate seam")
    s = reset()
    ctx = bpy.context
    select(None)
    check(bpy.ops.banana.new_terrain('EXEC_DEFAULT', name="terrain_a", size_x=20, size_y=20, spacing=2,
                                     next_to_selected=False) == {'FINISHED'}, "new terrain BSP")
    a_obj = ctx.active_object
    a = bsp_mod.bsp_of(a_obj, ctx.scene)
    check(a is not None and a.name == "terrain_a" and s.active_bsp == a, "it is its own BSP and becomes active")
    check(len(a_obj.data.polygons) == 100 and a_obj.data.polygons[0].normal.z > 0.99, "10x10 tile, normals up")
    check(any(o.get(sky.SHELL_KEY) for o in bsp_mod.objects_for_role(a, 'STRUCTURE')), "came with a sky shell")
    check(not errors(validate.validate_bsp(ctx, a)), "sealed right away")

    # raise A's east edge, then add B to the east
    for v in a_obj.data.vertices:
        if v.co.x > 9.99:
            v.co.z = 1.0 + 0.1 * v.co.y
    a_obj.data.update()
    select(a_obj)
    bpy.ops.banana.new_terrain('EXEC_DEFAULT', name="terrain_b", size_x=30, size_y=20, spacing=2,
                               next_to_selected=True, side='+X')
    b_obj = ctx.active_object
    b = bsp_mod.bsp_of(b_obj, ctx.scene)
    check(b.name == "terrain_b" and abs(b_obj.location.x - 25.0) < 1e-6, "second terrain BSP placed edge to edge")
    ha, hb = border_heights(a_obj), border_heights(b_obj)
    shared = set(ha) & set(hb)
    check(len(shared) == 11 and all(abs(ha[k] - hb[k]) < 1e-6 for k in shared), "shared edge lined up, heights copied")
    check(not errors(validate.validate_bsp(ctx, b)), "new BSP sealed by its own sky")
    check(not sky.seam_triangles(ctx, a) and not sky.seam_triangles(ctx, b), "no seam until asked")

    # knock B's edge out of place, Match Edge puts it back
    b_obj.data.vertices[0].co.x += 0.3   # south-west corner is on the shared edge
    b_obj.data.vertices[0].co.z += 2.0
    b_obj.data.update()
    select(a_obj, b_obj)
    bpy.ops.banana.match_edge(tolerance=1.0)
    ha, hb = border_heights(a_obj), border_heights(b_obj)
    shared = set(ha) & set(hb)
    check(len(shared) == 11 and all(abs(ha[k] - hb[k]) < 1e-6 for k in shared), "Match Edge snapped position and height")

    select(a_obj, b_obj)
    check(bpy.ops.banana.generate_seam() == {'FINISHED'}, "Generate Seam runs")
    check(len(sky.seam_triangles(ctx, a)) == 20 and len(sky.seam_triangles(ctx, b)) == 20, "10 seam segments on each side")
    check(not sky.check_seams(ctx, [a, b]), "seam pair matches")
    for bsp in (a, b):
        check(not errors(validate.validate_bsp(ctx, bsp)), "%s still sealed" % bsp.name)
    mats_a = {m for o in bsp_mod.objects_for_role(a, 'STRUCTURE') for m in o.data.materials if m and naming.is_seam(m.name)}
    mats_b = {m for o in bsp_mod.objects_for_role(b, 'STRUCTURE') for m in o.data.materials if m and naming.is_seam(m.name)}
    check(len(mats_a) == 1 and len(mats_b) == 1 and mats_a != mats_b, "each BSP has its own default seam material")
    check({m.name for m in mats_a | mats_b} == {"+seam", "+seam.001"}, "named +seam / +seam.001 until renamed")
    res = validate.validate_bsp(ctx, a)
    check(any("default name" in i[1] for i in res.items if i[0] == 'WARNING'), "Validate reminds you to name it")
    a.banana.seam_material.name = "+seam:my_name"
    select(a_obj, b_obj)
    bpy.ops.banana.generate_seam()
    check({m.name for o in bsp_mod.objects_for_role(a, 'STRUCTURE') for m in o.data.materials if m and naming.is_seam(m.name)}
          == {"+seam:my_name"}, "rebuilding keeps your name")
    written, _r = export.export_bsp(ctx, a)
    text = open(written[0]).read()
    check(text.count('"+seam:my_name"') == 1 and '"+seam"' not in text, "exports your name exactly")

    # a third terrain north of A keeps A's seam with B when joined
    select(a_obj)
    bpy.ops.banana.new_terrain('EXEC_DEFAULT', name="terrain_c", size_x=20, size_y=20, spacing=2,
                               next_to_selected=True, side='+Y')
    c_obj = ctx.active_object
    select(a_obj, c_obj)
    bpy.ops.banana.generate_seam()
    c = bsp_mod.bsp_of(c_obj, ctx.scene)
    check(not sky.check_seams(ctx, [a, b, c]), "A keeps its seam with B after joining C")


def test_selection_via_shell():
    print("New Terrain / Generate Seam work when the sky shell (or anything in the BSP) is selected")
    s = reset()
    ctx = bpy.context
    select(None)
    bpy.ops.banana.new_terrain('EXEC_DEFAULT', name="t0", size_x=100, size_y=100, spacing=2, next_to_selected=False)
    t0 = ctx.active_object
    shell = [o for o in bsp_mod.objects_for_role(s.active_bsp, 'STRUCTURE') if o.get(sky.SHELL_KEY)][0]
    check(shell.hide_select, "sky shells can't be clicked")
    shell.hide_select = False  # simulate an old file where the shell was selectable
    select(shell)
    for side, expect in (('+X', (100, 0)), ('-X', (-100, 0)), ('+Y', (0, 100)), ('-Y', (0, -100))):
        select(shell)
        bpy.ops.banana.new_terrain('EXEC_DEFAULT', name="t_%s" % side, next_to_selected=True, side=side)
        loc = ctx.active_object.location
        check(abs(loc.x - expect[0]) < 1e-6 and abs(loc.y - expect[1]) < 1e-6 and abs(loc.z) < 1e-6,
              "side %s lands at %s (got %.1f, %.1f, %.1f)" % (side, expect, loc.x, loc.y, loc.z))
    east = bpy.data.objects["t_+X_ground"]
    select(shell, east)
    bpy.ops.banana.generate_seam()
    a, b = bsp_mod.bsp_of(t0, ctx.scene), bsp_mod.bsp_of(east, ctx.scene)
    everyone = bsp_mod.find_bsps(ctx.scene)
    check(len(sky.seam_triangles(ctx, a)) == 100 and not sky.check_seams(ctx, everyone),
          "seam only between the two selected; the other touching terrains get no unpaired seam")
    for bsp in everyone:
        check(not errors(validate.validate_bsp(ctx, bsp)), "%s sealed" % bsp.name)

    # an existing seam survives joining a second neighbor
    north = bpy.data.objects["t_+Y_ground"]
    select(t0, north)
    bpy.ops.banana.generate_seam()
    c = bsp_mod.bsp_of(north, ctx.scene)
    check(len(sky.seam_triangles(ctx, a)) == 200 and not sky.check_seams(ctx, everyone), "A keeps its east seam and gains a north one")
    bpy.ops.banana.build_sky_shell(all_bsps=True)
    check(len(sky.seam_triangles(ctx, a)) == 200 and not sky.check_seams(ctx, everyone),
          "Rebuild All Skies keeps exactly the seams made with Generate Seam")

    # overlapping terrains are refused and reported
    select(None)
    bpy.ops.banana.new_terrain('EXEC_DEFAULT', name="dup", size_x=100, size_y=100, spacing=2, next_to_selected=False)
    dup = ctx.active_object
    select(t0, dup)
    try:
        bpy.ops.banana.generate_seam()
        check(False, "overlapping terrains refused")
    except RuntimeError as err:
        check("overlap" in str(err), "overlapping terrains refused")
    check(any("overlap" in m for _s, m, _b in sky.check_overlaps(ctx, bsp_mod.find_bsps(ctx.scene))), "Validate reports the overlap")


def test_fine_spacing_seam():
    print("generate seam on 1 m terrain doesn't collapse vertices")
    s = reset()
    ctx = bpy.context
    select(None)
    bpy.ops.banana.new_terrain('EXEC_DEFAULT', name="fa", size_x=10, size_y=10, spacing=1, next_to_selected=False)
    fa = ctx.active_object
    bpy.ops.banana.new_terrain('EXEC_DEFAULT', name="fb", size_x=10, size_y=10, spacing=1, next_to_selected=True, side='+X')
    fb = ctx.active_object
    before = sorted(tuple(round(c, 4) for c in (fb.matrix_world @ v.co)) for v in fb.data.vertices)
    select(fa, fb)
    bpy.ops.banana.generate_seam()
    after = sorted(tuple(round(c, 4) for c in (fb.matrix_world @ v.co)) for v in fb.data.vertices)
    check(before == after, "no vertex moved (they already matched)")
    a, b = (bsp_mod.bsp_of(o, ctx.scene) for o in (fa, fb))
    check(len(sky.seam_triangles(ctx, a)) == 20 and not sky.check_seams(ctx, [a, b]), "10-segment seam pairs up")
    for bsp in (a, b):
        check(not errors(validate.validate_bsp(ctx, bsp)), "%s sealed" % bsp.name)


def _paint(obj, target, strength=0.8, steps=30, rings=2, shared=frozenset()):
    mask = brush.border_mask(obj.data, rings, shared)
    c = obj.matrix_world.translation
    for _ in range(steps):
        brush.height_dab(obj, (c.x, c.y), 1000.0, target, strength, mask)


def test_blend_edge_and_paint_across():
    print("Match Edge blends heights; the brush paints across joined edges")
    s = reset()
    ctx = bpy.context
    select(None)
    bpy.ops.banana.new_terrain('EXEC_DEFAULT', name="ea", size_x=40, size_y=40, spacing=2, next_to_selected=False)
    ea = ctx.active_object
    bpy.ops.banana.new_terrain('EXEC_DEFAULT', name="eb", size_x=40, size_y=40, spacing=2, next_to_selected=True, side='+X')
    eb = ctx.active_object
    _paint(ea, 8.0)
    _paint(eb, 4.0)
    mw = ea.matrix_world
    mid_i = [v.index for v in ea.data.vertices if abs((mw @ v.co).x - 20.0) < 1e-4 and abs((mw @ v.co).y) < 1e-4][0]
    zmid = lambda: (ea.matrix_world @ ea.data.vertices[mid_i].co).z
    check(abs(zmid()) < 1e-6, "before: locked edge sits at the bottom (the valley)")
    select(ea, eb)
    bpy.ops.banana.generate_seam(rows=3)
    z = zmid()
    check(abs(z - 6.0) < 0.05, "edge lifted to the average of both sides (%.2f, want 6)" % z)
    row = sorted(((mw @ v.co).x, (mw @ v.co).z) for v in ea.data.vertices if abs((mw @ v.co).y) < 1e-4 and (mw @ v.co).x > 10)
    zs = [z for _x, z in row]
    check(all(abs(zs[i + 1] - zs[i]) < 1.5 for i in range(len(zs) - 1)), "smooth ramp, no cliff: %s" % [round(z, 1) for z in zs[-6:]])
    a, b = bsp_mod.bsp_of(ea, ctx.scene), bsp_mod.bsp_of(eb, ctx.scene)
    check(not sky.check_seams(ctx, [a, b]), "seam rebuilt and still pairs")
    shell = [o for o in bsp_mod.objects_for_role(a, 'STRUCTURE') if o.get(sky.SHELL_KEY)][0]
    sealer = [i for i, m in enumerate(shell.data.materials) if m and m.name == "+seamsealer"]
    top = s.sky_height
    sealed = [p for p in shell.data.polygons if sealer and p.material_index == sealer[0]]
    check(sealed and all(abs((shell.matrix_world @ shell.data.vertices[v].co).z - top) < 1e-5 for p in sealed for v in p.vertices),
          "cap strip along the seam's top uses +seamsealer (%d faces)" % len(sealed))
    seam_idx = [i for i, m in enumerate(shell.data.materials) if m and naming.is_seam(m.name)][0]
    top_edges = {frozenset(e) for p in shell.data.polygons if p.material_index == seam_idx for e in p.edge_keys
                 if all(abs(shell.data.vertices[v].co.z - top) < 1e-5 for v in e)}
    sealer_edges = {frozenset(e) for p in sealed for e in p.edge_keys}
    check(top_edges and top_edges <= sealer_edges, "every seam top edge touches the sealer, not +sky")
    for bsp in (a, b):
        check(not errors(validate.validate_bsp(ctx, bsp)), "%s sealed after blending" % bsp.name)
    ends = [v for v in ea.data.vertices if abs((mw @ v.co).x - 20.0) < 1e-4 and abs(abs((mw @ v.co).y) - 20.0) < 1e-4]
    check(all(abs((mw @ v.co).z) < 1e-6 for v in ends), "edge end corners stay put")

    # brush across the joined edge: shared edge is free, both sides move together
    shared = brush.shared_vertices([ea, eb])
    check(len(shared[ea.name]) == 21 and len(shared[eb.name]) == 21, "21 shared edge vertices found on each side")
    masks = {o.name: brush.border_mask(o.data, 2, shared[o.name]) for o in (ea, eb)}
    check(masks[ea.name][mid_i] == 0.0, "shared edge isn't locked")
    import types
    fake = types.SimpleNamespace(objects=[ea, eb], shared=shared,
                                 shared_before={o.name: [o.data.vertices[i].co.z for i in sorted(shared[o.name])] for o in (ea, eb)},
                                 report=lambda *a: None)
    weld = 0.01 / s.scale()
    everyone = bsp_mod.find_bsps(ctx.scene)
    fake.seam_plans = {x.name: sky.existing_seam_partners(ctx, x, [o for o in everyone if o is not x], weld) for x in everyone}
    for o in (ea, eb):
        brush.height_dab(o, (20.0, 0.0), 6.0, 12.0, 1.0, masks[o.name])
    za = zmid()
    vb = [v for v in eb.data.vertices if abs((eb.matrix_world @ v.co).x - 20.0) < 1e-4 and abs((eb.matrix_world @ v.co).y) < 1e-4][0]
    zb = (eb.matrix_world @ vb.co).z
    check(abs(za - 12.0) < 1e-4 and za == zb, "edge painted to 12 m on both sides, identical (%.3f / %.3f)" % (za, zb))
    brush.BANANA_OT_terrain_brush._rebuild_moved_edges(fake, ctx)
    check(not sky.check_seams(ctx, [a, b]), "skies rebuilt after the stroke; seam still pairs")
    for bsp in (a, b):
        check(not errors(validate.validate_bsp(ctx, bsp)), "%s sealed after painting across" % bsp.name)


def test_height_dab():
    print("set height brush math")
    reset()
    obj = terrain.make_tile("t", 20, 20, 1, Vector((5, 0, 2)))
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.update()
    mask = brush.border_mask(obj.data, rings=2)
    check(mask.max() == 1.0 and abs(sorted(set(np.round(mask, 3)))[1] - 0.333) < 1e-3, "border mask fades over 2 rings")
    for _ in range(40):
        brush.height_dab(obj, (5, 0), 4.0, 7.0, 0.5, mask)
    mw = obj.matrix_world
    center = min(obj.data.vertices, key=lambda v: (v.co.x) ** 2 + (v.co.y) ** 2)
    check(abs((mw @ center.co).z - 7.0) < 1e-3, "center reaches the target height (world Z, object at z=2)")
    far = [v for v in obj.data.vertices if (Vector((v.co.x, v.co.y)).length > 4.01)]
    check(all(abs((mw @ v.co).z - 2.0) < 1e-6 for v in far), "nothing outside the radius moves")
    xs = sorted({round((mw @ v.co).x, 4) for v in obj.data.vertices})
    check(len(xs) == 21, "X/Y never move")
    brush.height_dab(obj, (-5, 0), 4.0, 7.0, 1.0, mask)  # radius reaches the west border at x = -5
    edge = [v for v in obj.data.vertices if abs((mw @ v.co).x + 5.0) < 1e-4]
    check(all(abs((mw @ v.co).z - 2.0) < 1e-6 for v in edge), "locked border doesn't move")


def test_blend_brush_and_preview():
    print("blend brush, blur, preview textures, bake")
    s = reset()
    ctx = bpy.context
    select(None)
    bpy.ops.banana.new_terrain('EXEC_DEFAULT', name="terrain_a", size_x=40, size_y=40, spacing=4, next_to_selected=False)
    bsp = s.active_bsp
    bsp.banana.blend_resolution = 64
    check(bpy.ops.banana.blend_setup() == {'FINISHED'}, "blend setup")
    layers, images = brush.read_layers(bsp)
    check(set(layers) == {2, 3, 4} and layers[2].shape == (64, 64), "layers read as 64x64 arrays")

    brush.blend_dab(layers, 16, 32, 8, 4, 'PAINT', 1.0)
    check(layers[4][32, 16] > 0.97, "paint layer 4")
    brush.blend_dab(layers, 16, 32, 8, 2, 'PAINT', 1.0)
    check(layers[2][32, 16] > 0.97 and layers[4][32, 16] < 0.03, "painting layer 2 over it shows layer 2")
    brush.blend_dab(layers, 16, 32, 8, 1, 'PAINT', 1.0)
    check(max(layers[n][32, 16] for n in (2, 3, 4)) < 0.03, "painting layer 1 brings the base back")
    brush.blend_dab(layers, 48, 32, 10, 3, 'PAINT', 0.3)
    v = layers[3][32, 48]
    check(0.25 < v < 0.35, "opacity 0.3 gives a partial layer (%.2f)" % v)
    for n in (2, 3, 4):
        layers[n][:] = 0
    layers[3][:, 32:] = 1.0  # hard edge down the middle
    brush.blend_dab(layers, 32, 32, 8, 2, 'BLUR', 1.0)
    check(0.2 < layers[3][32, 31] < 0.8 and 0.2 < layers[3][32, 32] < 0.8, "blur softens the edge")
    check(layers[3][32, 60] == 1.0 and layers[3][32, 2] == 0.0, "blur stays inside the brush")
    brush.write_layers(layers, images)

    # preview texture on layer 3: nodes appear, export is still plain RGBA
    tex = bpy.data.images.new("rock_preview", 8, 8)
    bsp.banana.layer3_image = tex
    bsp.banana.layer3_tile = 10.0
    mat = bpy.data.materials[bsp.banana.terrain_material]
    nodes = mat.node_tree.nodes
    check(nodes.get("BANANA_tex3") is not None and nodes["BANANA_tex3"].image == tex, "layer 3 shows its preview texture")
    scale = tuple(round(x, 3) for x in nodes["BANANA_map3"].inputs["Scale"].default_value)
    check(scale == (4.0, 4.0, 1.0), "tiles every 10 m over the 40 m area %s" % (scale,))
    check(nodes.get("BANANA_color3") is None and nodes.get("BANANA_color2") is not None, "other layers keep flat colors")

    written, report = export.export_bsp(ctx, bsp)
    img = bpy.data.images.load(report.blend_map, check_existing=False)
    img.alpha_mode = 'STRAIGHT'
    img.colorspace_settings.name = 'Non-Color'
    px = np.empty(64 * 64 * 4, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(64, 64, 4)
    check(tuple(np.round(px[32, 60], 2)) == (0.0, 0.0, 1.0, 0.0), "layer 3 -> B in the bake")
    check(tuple(np.round(px[10, 2], 2)) == (1.0, 0.0, 0.0, 0.0), "base -> R in the bake")
    check(abs(px.sum(axis=2) - 1).max() < 0.02, "channels add up to 1")
    check(bpy.data.materials[bsp.banana.terrain_material].name == "terrain", "material name (shader) unchanged")


if __name__ == "__main__":
    test_terrain_bsps()
    test_selection_via_shell()
    test_fine_spacing_seam()
    test_blend_edge_and_paint_across()
    test_height_dab()
    test_blend_brush_and_preview()
    print("\n%s" % ("ALL PASSED" if not FAILS else "%d FAILED" % len(FAILS)))
    sys.exit(1 if FAILS else 0)
