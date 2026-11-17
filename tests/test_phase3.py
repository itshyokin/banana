"""Headless tests for terrain tiles, height brush setup, border matching and blend maps:
python tests/test_phase3.py"""

import os
import sys
import tempfile

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banana  # noqa: E402
from banana import blendmap, bsp as bsp_mod, export, sky, terrain, validate  # noqa: E402

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


def activate(obj):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    if obj is not None:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def border_heights(obj):
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    idx = {v.index for e in bm.edges if len(e.link_faces) == 1 for v in e.verts}
    bm.free()
    mw = obj.matrix_world
    return {terrain._key((mw @ obj.data.vertices[i].co).x, (mw @ obj.data.vertices[i].co).y): (mw @ obj.data.vertices[i].co).z for i in idx}


def test_tiles_and_borders():
    print("tiles, border lock, match borders, sealing across BSPs")
    s = reset()
    ctx = bpy.context
    a = bsp_mod.create_bsp(ctx.scene, "bsp_a")
    b = bsp_mod.create_bsp(ctx.scene, "bsp_b")
    s.active_bsp = a
    activate(None)
    check(bpy.ops.banana.new_tile('EXEC_DEFAULT', size_x=20, size_y=20, spacing=2, next_to_selected=False) == {'FINISHED'}, "first tile")
    t1 = ctx.active_object
    check(terrain.is_terrain(t1) and len(t1.data.polygons) == 100, "10x10 grid of quads")
    check(t1.data.polygons[0].normal.z > 0.99, "normals point up")
    check(t1.data.materials[0].name == "terrain", "uses the BSP's terrain shader material")

    # raise the east border, then add a tile to the east in the other BSP
    for v in t1.data.vertices:
        if v.co.x > 9.99:
            v.co.z = 1.0 + 0.1 * v.co.y
    t1.data.update()
    s.active_bsp = b
    activate(t1)
    bpy.ops.banana.new_tile('EXEC_DEFAULT', size_x=30, size_y=20, spacing=2, next_to_selected=True, side='+X')
    t2 = ctx.active_object
    check(abs(t2.location.x - 25.0) < 1e-6, "placed edge to edge (x = %.2f)" % t2.location.x)
    check(t2.name in bsp_mod.sub_collections(b, 'STRUCTURE')[0].objects, "went into bsp_b")
    h1, h2 = border_heights(t1), border_heights(t2)
    shared = set(h1) & set(h2)
    check(len(shared) == 11 and all(abs(h1[k] - h2[k]) < 1e-6 for k in shared), "shared border: 11 vertices, same heights")

    # border mask
    mask = terrain.border_mask(t1.data, rings=2)
    check(abs(mask.max() - 1.0) < 1e-6 and abs(sorted(set(np.round(mask, 3)))[1] - 0.333) < 1e-3, "mask: 1 on border, fading over 2 rings")
    interior = [i for i, v in enumerate(t1.data.vertices) if abs(v.co.x) < 3 and abs(v.co.y) < 3]
    check(all(mask[i] == 0 for i in interior), "interior unmasked")

    # height brush mode setup (brush switching needs a real 3D view; locks and mask are what matter)
    ts = ctx.tool_settings.sculpt
    ts.lock_x = ts.lock_y = False
    activate(t1)
    bpy.ops.banana.height_brush(brush='DRAW')
    check(t1.mode == 'SCULPT' and ts.lock_x and ts.lock_y, "sculpt mode with X/Y locked")
    m = t1.data.attributes.get(terrain.MASK_ATTR)
    check(m is not None and max(d.value for d in m.data) == 1.0, "border mask applied")
    bpy.ops.banana.done_sculpting()
    check(t1.mode == 'OBJECT' and not ts.lock_x and not ts.lock_y, "done: object mode, locks restored")
    check(t1.data.attributes.get(terrain.MASK_ATTR) is None, "mask cleared")

    # break the border, match it back
    t2.data.vertices[0].co.z += 0.5  # south-west corner sits on the shared border
    t2.data.update()
    activate(t1)
    moved = terrain.match_borders(ctx.scene, prefer=t1)
    h1, h2 = border_heights(t1), border_heights(t2)
    check(moved == 1 and all(abs(h1[k] - h2[k]) < 1e-6 for k in set(h1) & set(h2)), "match borders fixes the height (%d moved)" % moved)

    bpy.ops.banana.build_sky_shell(all_bsps=True)
    for bsp in (a, b):
        res = validate.validate_bsp(ctx, bsp)
        errs = [i for i in res.items if i[0] == 'ERROR']
        check(not errs, "%s sealed with its shell: %s" % (bsp.name, errs))
    check(not sky.check_seams(ctx, [a, b]) and not sky.check_border_alignment(ctx, [a, b]), "tiles seam together across BSPs")


def test_blend_map():
    print("blend map")
    s = reset()
    ctx = bpy.context
    a = bsp_mod.create_bsp(ctx.scene, "bsp_a")
    s.active_bsp = a
    a.banana.blend_resolution = 64
    activate(None)
    bpy.ops.banana.new_tile('EXEC_DEFAULT', size_x=40, size_y=20, spacing=4, next_to_selected=False)
    tile = ctx.active_object
    check(bpy.ops.banana.blend_setup() == {'FINISHED'}, "setup runs")
    uv = tile.data.uv_layers[0]
    check(uv.name == "blend_uv", "blend_uv is the first UV map")
    us = [d.uv[0] for d in uv.data]
    vs = [d.uv[1] for d in uv.data]
    check(abs(min(us)) < 1e-5 and abs(max(us) - 1) < 1e-5 and abs(min(vs)) < 1e-5 and abs(max(vs) - 1) < 1e-5, "UVs span 0-1")
    mat = tile.data.materials[0]
    check(mat.name == "terrain" and any(n.name.startswith("BANANA_mix") for n in mat.node_tree.nodes), "preview nodes in the terrain material")
    check(all(bpy.data.images.get("bsp_a_layer%d" % n) for n in (2, 3, 4)), "three paint layers")

    # paint: layer 2 on the left half, layer 4 in the bottom-left quarter
    def paint(n, fn):
        img = bpy.data.images["bsp_a_layer%d" % n]
        w, h = img.size
        px = np.zeros((h, w, 4), np.float32)
        px[..., 3] = 1
        for y in range(h):
            for x in range(w):
                if fn(x / w, y / h):
                    px[y, x, :3] = 1
        img.pixels.foreach_set(px.ravel())
    paint(2, lambda u, v: u < 0.5)
    paint(4, lambda u, v: u < 0.25 and v < 0.25)

    # paint layer operator picks the right slot
    activate(tile)
    bpy.ops.banana.paint_layer(layer=3)
    images = list(mat.texture_paint_images)
    check(tile.mode == 'TEXTURE_PAINT' and images and images[mat.paint_active_slot].name == "bsp_a_layer3", "paint layer 3 is the active slot")
    bpy.ops.object.mode_set(mode='OBJECT')

    written, report = export.export_bsp(ctx, a)
    path = report.blend_map
    check(path and path.endswith(os.path.join("bitmaps", "bsp_a_blend.tif")) and os.path.exists(path), "export writes bitmaps/bsp_a_blend.tif")
    img = bpy.data.images.load(path, check_existing=False)
    img.alpha_mode = 'STRAIGHT'
    img.colorspace_settings.name = 'Non-Color'
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)

    def at(u, v):
        return tuple(round(float(c), 2) for c in px[int(v * h), int(u * w)])
    check(at(0.75, 0.75) == (1.0, 0.0, 0.0, 0.0), "base only -> R (%s)" % (at(0.75, 0.75),))
    check(at(0.4, 0.75) == (0.0, 1.0, 0.0, 0.0), "layer 2 -> G (%s)" % (at(0.4, 0.75),))
    check(at(0.1, 0.1) == (0.0, 0.0, 0.0, 1.0), "layer 4 over layer 2 -> A (%s)" % (at(0.1, 0.1),))
    check(abs(px.sum(axis=2) - 1).max() < 0.02, "channels add up to 1 everywhere")


if __name__ == "__main__":
    test_tiles_and_borders()
    test_blend_map()
    print("\n%s" % ("ALL PASSED" if not FAILS else "%d FAILED" % len(FAILS)))
    sys.exit(1 if FAILS else 0)
