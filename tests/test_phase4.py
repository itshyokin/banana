"""Headless tests for the prop library, prop painting and name sync: python tests/test_phase4.py"""

import os
import re
import sys
import tempfile

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banana  # noqa: E402
from banana import bsp as bsp_mod, export, proplib  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def make_library():
    """A folder with two GLB models: a two-part tree (trunk + crown) and a rock."""
    folder = tempfile.mkdtemp(prefix="banana_props_")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=2, location=(0, 0, 1))
    trunk = bpy.context.object
    trunk.data.materials.append(bpy.data.materials.new("bark"))
    bpy.ops.mesh.primitive_cone_add(radius1=1.5, depth=3, location=(0, 0, 3.5))
    crown = bpy.context.object
    crown.data.materials.append(bpy.data.materials.new("leaves"))
    bpy.ops.export_scene.gltf(filepath=os.path.join(folder, "Pine Tree.glb"), export_format='GLB')
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    bpy.ops.mesh.primitive_ico_sphere_add(radius=0.5)
    bpy.ops.export_scene.gltf(filepath=os.path.join(folder, "rock.glb"), export_format='GLB')
    open(os.path.join(folder, "notes.txt"), "w").write("not a model")
    return folder


def reset(folder):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        banana.register()
    except ValueError:
        pass
    s = bpy.context.scene.banana
    s.export_root = tempfile.mkdtemp(prefix="banana_")
    s.prop_folder = folder
    return s


def select(active):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    if active is not None:
        active.select_set(True)
    bpy.context.view_layer.objects.active = active


def test_library_and_names(folder):
    print("library, master, collections, name sync, export")
    s = reset(folder)
    ctx = bpy.context
    select(None)
    bpy.ops.banana.new_terrain('EXEC_DEFAULT', name="ta", size_x=60, size_y=60, spacing=2, next_to_selected=False)
    ta = bsp_mod.bsp_of(ctx.active_object, ctx.scene)
    select(ctx.active_object)
    bpy.ops.banana.new_terrain('EXEC_DEFAULT', name="tb", size_x=60, size_y=60, spacing=2, next_to_selected=True, side='+X')
    tb = bsp_mod.bsp_of(ctx.active_object, ctx.scene)

    check(bpy.ops.banana.prop_scan() == {'FINISHED'}, "scan runs")
    props = ctx.scene.banana_props
    check([p.base for p in props] == ["pine_tree", "rock"], "two models found, names cleaned: %s" % [p.base for p in props])
    bpy.ops.banana.prop_scan()
    check(len(props) == 2, "scanning again doesn't duplicate")

    ctx.scene.banana_props_index = 0
    tree = props[0]
    s.active_bsp = ta
    ctx.scene.cursor.location = (-10, 0, 0)
    check(bpy.ops.banana.prop_add() == {'FINISHED'}, "add master")
    master = ctx.active_object
    check(master.name == "%pine_tree" and master.get(proplib.MASTER_KEY), "master named %pine_tree")
    check(len(master.data.polygons) > 40 and len(master.data.materials) == 2, "both GLB meshes joined into one mesh, 2 materials")
    main, painted = proplib.prop_collections(ta, tree, create=False)
    check(master.name in main.objects and painted is not None and painted.name in [c.name for c in main.children],
          "master in its prop collection, with a painted sub-collection under it")
    instances = bsp_mod.sub_collections(ta, 'INSTANCES')[0]
    check(main.name in instances.children, "prop collection lives in the BSP's instances")

    # paint across both terrains
    sc = proplib.Scatter(ctx, tree, seed=1)
    s.prop_spacing = 3.0
    made = []
    for x in range(-25, 30, 5):
        made += sc.dab((x, 0.0), 8.0, 6, s)
        made += sc.dab((x + 60, 0.0), 8.0, 6, s)
    sc.end_stroke()
    check(len(made) > 20, "painted %d trees" % len(made))
    check(all(o.data is tree.mesh for o in made), "every copy shares the master's mesh")
    _m, painted_a = proplib.prop_collections(ta, tree, create=False)
    _m2, painted_b = proplib.prop_collections(tb, tree, create=False)
    in_a = [o for o in made if o.name in painted_a.objects]
    in_b = [o for o in made if o.name in painted_b.objects]
    check(len(in_a) + len(in_b) == len(made) and in_a and in_b,
          "copies land in the painted sub-collection of the BSP they're on (%d / %d)" % (len(in_a), len(in_b)))
    check(all(o.matrix_world.translation.x < 30 for o in in_a) and all(o.matrix_world.translation.x > 30 for o in in_b),
          "...by position")
    pts = [o.matrix_world.translation for o in made]
    closest = min((a - b).to_2d().length for i, a in enumerate(pts) for b in pts[i + 1:])
    check(closest >= 3.0 - 1e-6, "minimum spacing respected (closest %.2f m)" % closest)
    on_ground = all(abs(o.matrix_world.translation.z) < 1e-4 for o in made)
    check(on_ground, "copies sit on the terrain surface")

    # name sync
    tree.render_only = True
    names = {o.name.split(".")[0] for o in proplib.prop_objects(tree.uid)}
    check(names == {"%*pine_tree"}, "ticking * renames master and copies: %s" % names)
    check(main.name == "%*pine_tree" and painted_a.name == "%*pine_tree_painted", "collections renamed too")
    tree.base = "tree"
    tree.suffix = "@30-20"
    check(master.name == "%*tree@30-20", "base name + suffix: %s" % master.name)

    written, _r = export.export_bsp(ctx, ta)
    text = open(written[0]).read()
    insts = re.findall(r';INSTANCE \d+\n(-?\d+)\n"([^"]*)"', text)
    trees = [(int(i), n) for i, n in insts if n.startswith("%*tree")]
    check(len(trees) == len(in_a) + 1, "export: master + %d copies as instances" % len(in_a))
    check(len({i for i, _n in trees}) == 1, "all share one instance definition")
    check(len({n for _i, n in trees}) == len(trees), "instance names unique (%s ...)" % [n for _i, n in trees][:3])

    # erase
    before = len(proplib.prop_objects(tree.uid))
    removed = proplib.erase(tree, (-10.0, 0.0), 6.0)
    check(removed > 0 and len(proplib.prop_objects(tree.uid)) == before - removed, "erase removed %d" % removed)
    check(master.name in bpy.data.objects, "erase never removes the master")


def test_align_and_sink(folder):
    print("align to slope, sink, scale, rotation")
    s = reset(folder)
    ctx = bpy.context
    select(None)
    bpy.ops.banana.new_terrain('EXEC_DEFAULT', name="slope", size_x=40, size_y=40, spacing=2, next_to_selected=False)
    t = ctx.active_object
    for v in t.data.vertices:
        v.co.z = v.co.x * 0.5  # a 26.6 degree slope
    t.data.update()
    bpy.ops.banana.prop_scan()
    rock = ctx.scene.banana_props[1]
    s.prop_align, s.prop_sink, s.prop_scale_min, s.prop_scale_max = True, 0.2, 2.0, 2.0
    sc = proplib.Scatter(ctx, rock, seed=3)
    made = sc.dab((0.0, 0.0), 5.0, 5, s)
    check(made, "placed on a slope")
    o = made[0]
    up = (o.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
    check(abs(up.angle(Vector((-0.5, 0, 1)).normalized())) < 1e-3, "aligned to the slope's normal")
    check(abs(o.matrix_world.to_scale().x - 2.0) < 1e-4, "scale 2")
    p = o.matrix_world.translation
    surface_z = p.x * 0.5
    check(p.z < surface_z, "sunk below the surface")


if __name__ == "__main__":
    lib = make_library()
    test_library_and_names(lib)
    test_align_and_sink(lib)
    print("\n%s" % ("ALL PASSED" if not FAILS else "%d FAILED" % len(FAILS)))
    sys.exit(1 if FAILS else 0)
