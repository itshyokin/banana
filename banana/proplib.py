"""Prop library and prop painting (phase 4).

- Library: point Banana at a folder of .glb/.gltf models. Each model becomes a
  prop entry; it is imported once (all its meshes joined into one mesh) and every
  placement shares that mesh, so each BSP exports it as one instance definition.
- Collections: in a BSP's instances collection every prop gets a collection named
  after it holding the master (main) object, with a `<name>_painted`
  sub-collection that painted copies always go into (never outside it).
- Names: a prop's Halo name is `%` + flags + base name (+ suffix), e.g. `%tree`,
  `%*tree`. Change the base name or a flag and the master, every copy and the
  collections are renamed.
- Prop brush: scatter copies on terrain/structure under the brush (random yaw and
  scale, optional align to the surface, minimum spacing), Ctrl+click erases.
"""

import math
import os
import random

import bmesh
import bpy
import gpu
from bpy.props import (
    BoolProperty, CollectionProperty, FloatProperty, IntProperty, PointerProperty, StringProperty,
)
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

from . import bsp as bsp_mod

PROP_KEY = "banana_prop"          # on objects and collections: the prop's uid
PAINTED_KEY = "banana_painted"    # on the painted sub-collection
MASTER_KEY = "banana_master"      # on the master object
MODEL_EXTS = (".glb", ".gltf")
THUMB_EXTS = (".png", ".jpg", ".jpeg")
NAV_EVENTS = {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM', 'MOUSEROTATE'}

_previews = None


# ------------------------------------------------------------------ data

def _rename(self, context):
    rename_prop(self)


class BananaProp(bpy.types.PropertyGroup):
    uid: IntProperty()
    file: StringProperty(subtype='FILE_PATH')
    base: StringProperty(name="Name", update=_rename,
                         description="Base name; the Halo instance name is % + flags + this")
    render_only: BoolProperty(name="* No Collision", update=_rename,
                              description="'*' prefix: render only, no collision")
    per_pixel: BoolProperty(name="! Per-Pixel Lighting", update=_rename, description="'!' prefix")
    per_vertex: BoolProperty(name="? Per-Vertex Lighting", update=_rename, description="'?' prefix")
    single_probe: BoolProperty(name="> Single Probe", update=_rename, description="'>' prefix")
    extra_flags: StringProperty(name="Other Flags", update=_rename,
                                description="Any other prefix symbols, placed right after %")
    suffix: StringProperty(name="Suffix", update=_rename,
                           description="Text after the name, e.g. (4) for lightmap resolution or @30-20 for fade")
    mesh: PointerProperty(type=bpy.types.Mesh)


def full_name(prop):
    flags = ("*" if prop.render_only else "") + ("!" if prop.per_pixel else "") + \
            ("?" if prop.per_vertex else "") + (">" if prop.single_probe else "") + prop.extra_flags
    return "%" + flags + (prop.base or "prop") + prop.suffix


def find_prop(scene, uid):
    for p in scene.banana_props:
        if p.uid == uid:
            return p
    return None


def prop_objects(uid):
    return [o for o in bpy.data.objects if o.get(PROP_KEY) == uid]


def rename_prop(prop):
    name = full_name(prop)
    if prop.mesh is not None:
        prop.mesh.name = name
    for obj in prop_objects(prop.uid):
        obj.name = name  # Blender adds .001, .002 ...; export turns those into _001, _002
    for coll in bpy.data.collections:
        if coll.get(PROP_KEY) == prop.uid:
            coll.name = name + ("_painted" if coll.get(PAINTED_KEY) else "")


# ------------------------------------------------------------------ library

def scan_folder(scene):
    folder = bpy.path.abspath(scene.banana.prop_folder)
    if not folder or not os.path.isdir(folder):
        return 0
    known = {os.path.normcase(os.path.abspath(bpy.path.abspath(p.file))) for p in scene.banana_props}
    added = 0
    for fname in sorted(os.listdir(folder)):
        if not fname.lower().endswith(MODEL_EXTS):
            continue
        path = os.path.join(folder, fname)
        if os.path.normcase(os.path.abspath(path)) in known:
            continue
        prop = scene.banana_props.add()
        prop.uid = random.randint(1, 2**31 - 1)
        prop.file = path
        stem = os.path.splitext(fname)[0]
        prop["base"] = bpy.path.clean_name(stem).lower()  # set without triggering a rename
        added += 1
    return added


def import_model(prop):
    """Import the model once and join every mesh in it into one mesh (world transforms applied)."""
    if prop.mesh is not None and prop.mesh.name in bpy.data.meshes:
        return prop.mesh
    before = set(bpy.data.objects)
    path = bpy.path.abspath(prop.file)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    bpy.context.view_layer.update()
    bm = bmesh.new()
    materials = []
    for obj in new:
        if obj.type != 'MESH':
            continue
        mats = [s.material for s in obj.material_slots]
        offset = len(materials)
        materials.extend(mats)
        start = len(bm.faces)
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        added_verts = [v for v in bm.verts if not v.tag]
        bmesh.ops.transform(bm, matrix=obj.matrix_world, verts=added_verts)
        for v in added_verts:
            v.tag = True
        for f in bm.faces[start:]:
            f.material_index += offset
    mesh = bpy.data.meshes.new(full_name(prop))
    bm.to_mesh(mesh)
    bm.free()
    for m in materials:
        mesh.materials.append(m)
    for obj in new:
        data = obj.data
        bpy.data.objects.remove(obj)
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)
    prop.mesh = mesh
    return mesh


def thumbnail(prop):
    """Icon id: a same-named .png/.jpg next to the model, else the model's first texture."""
    global _previews
    if _previews is None:
        return 0
    stem = os.path.splitext(bpy.path.abspath(prop.file))[0]
    for ext in THUMB_EXTS:
        path = stem + ext
        if os.path.exists(path):
            if path not in _previews:
                _previews.load(path, path, 'IMAGE')
            return _previews[path].icon_id
    if prop.mesh is not None:
        for mat in prop.mesh.materials:
            if mat and mat.use_nodes:
                for node in mat.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image is not None:
                        node.image.preview_ensure()
                        return node.image.preview.icon_id
    return 0


# ------------------------------------------------------------------ collections

def prop_collections(bsp, prop, create=True):
    """(prop collection, painted sub-collection) for this prop inside this BSP's instances."""
    holders = bsp_mod.sub_collections(bsp, 'INSTANCES')
    if not holders:
        if not create:
            return None, None
        holder = bpy.data.collections.new("%s_instances" % bsp.name)
        holder.banana.role = 'INSTANCES'
        bsp.children.link(holder)
    else:
        holder = holders[0]
    main = next((c for c in holder.children if c.get(PROP_KEY) == prop.uid and not c.get(PAINTED_KEY)), None)
    if main is None:
        if not create:
            return None, None
        main = bpy.data.collections.new(full_name(prop))
        main[PROP_KEY] = prop.uid
        holder.children.link(main)
    painted = next((c for c in main.children if c.get(PAINTED_KEY)), None)
    if painted is None and create:
        painted = bpy.data.collections.new(full_name(prop) + "_painted")
        painted[PROP_KEY] = prop.uid
        painted[PAINTED_KEY] = True
        main.children.link(painted)
    return main, painted


def add_master(context, prop, bsp, location):
    import_model(prop)
    main, _painted = prop_collections(bsp, prop)
    obj = bpy.data.objects.new(full_name(prop), prop.mesh)
    obj[PROP_KEY] = prop.uid
    obj[MASTER_KEY] = True
    obj.location = location
    main.objects.link(obj)
    return obj


# ------------------------------------------------------------------ painting (no UI, tested)

def surfaces(scene):
    """Meshes props can be painted on: structure of every BSP, without sky shells or mirrored seams."""
    from . import sky
    out = []
    for bsp in bsp_mod.find_bsps(scene):
        for obj in bsp_mod.objects_for_role(bsp, 'STRUCTURE'):
            if not obj.get(sky.SHELL_KEY) and not obj.get(sky.SEAM_SOURCE_KEY):
                out.append(obj)
    return out


def drop(objs, x, y):
    """Highest surface hit straight down at (x, y): (point, normal, object) or None."""
    best = None
    for obj in objs:
        top = max((obj.matrix_world @ Vector(c)).z for c in obj.bound_box) + 1.0
        inv = obj.matrix_world.inverted()
        origin = inv @ Vector((x, y, top))
        direction = (inv.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
        ok, loc, normal, _i = obj.ray_cast(origin, direction)
        if ok:
            world = obj.matrix_world @ loc
            n = (obj.matrix_world.to_3x3().inverted().transposed() @ normal).normalized()
            if best is None or world.z > best[0].z:
                best = (world, n, obj)
    return best


class Scatter:
    """One painting session for one prop: keeps a spatial index of its placements."""

    def __init__(self, context, prop, seed=None):
        self.context = context
        self.prop = prop
        self.rng = random.Random(seed)
        self.surfaces = surfaces(context.scene)
        self.points = [o.matrix_world.translation.copy() for o in prop_objects(prop.uid)]
        self._tree = None

    def _too_close(self, p, spacing):
        if spacing <= 0:
            return False
        if self._tree is None:
            self._tree = KDTree(max(1, len(self.points)))
            for i, q in enumerate(self.points):
                self._tree.insert(Vector((q.x, q.y, 0.0)), i)
            self._tree.balance()
        if self.points:
            _co, _i, dist = self._tree.find(Vector((p.x, p.y, 0.0)))
            if dist is not None and dist < spacing:
                return True
        return any((Vector((q.x - p.x, q.y - p.y))).length < spacing for q in self.recent)

    def dab(self, center, radius, count, settings):
        """Place up to `count` copies at random spots in the circle. Returns the new objects."""
        import_model(self.prop)
        self.recent = getattr(self, "recent", [])
        made = []
        for _ in range(count):
            r = radius * math.sqrt(self.rng.random())
            a = self.rng.random() * 2 * math.pi
            x, y = center[0] + r * math.cos(a), center[1] + r * math.sin(a)
            hit = drop(self.surfaces, x, y)
            if hit is None:
                continue
            point, normal, surface = hit
            if self._too_close(point, settings.prop_spacing):
                continue
            bsp = bsp_mod.bsp_of(surface, self.context.scene)
            if bsp is None:
                continue
            _main, painted = prop_collections(bsp, self.prop)
            obj = bpy.data.objects.new(full_name(self.prop), self.prop.mesh)
            obj[PROP_KEY] = self.prop.uid
            yaw = self.rng.random() * 2 * math.pi if settings.prop_random_yaw else 0.0
            scale = self.rng.uniform(settings.prop_scale_min, max(settings.prop_scale_min, settings.prop_scale_max))
            rot = Matrix.Rotation(yaw, 4, 'Z')
            if settings.prop_align:
                rot = Vector((0, 0, 1)).rotation_difference(normal).to_matrix().to_4x4() @ rot
            obj.matrix_world = Matrix.Translation(point - normal * settings.prop_sink) @ rot @ Matrix.Scale(scale, 4)
            painted.objects.link(obj)
            self.recent.append(point)
            made.append(obj)
        return made

    def end_stroke(self):
        self.points.extend(self.recent)
        self.recent = []
        self._tree = None


def erase(prop, center, radius, include_master=False):
    removed = 0
    for obj in prop_objects(prop.uid):
        if obj.get(MASTER_KEY) and not include_master:
            continue
        p = obj.matrix_world.translation
        if Vector((p.x - center[0], p.y - center[1])).length <= radius:
            bpy.data.objects.remove(obj)
            removed += 1
    return removed


# ------------------------------------------------------------------ operators

def active_prop(context):
    s = context.scene
    if 0 <= s.banana_props_index < len(s.banana_props):
        return s.banana_props[s.banana_props_index]
    return None


class BANANA_OT_prop_scan(bpy.types.Operator):
    """Find .glb/.gltf models in the prop folder"""
    bl_idname = "banana.prop_scan"
    bl_label = "Scan Folder"

    def execute(self, context):
        folder = bpy.path.abspath(context.scene.banana.prop_folder)
        if not folder or not os.path.isdir(folder):
            self.report({'ERROR'}, "Pick a prop folder first")
            return {'CANCELLED'}
        added = scan_folder(context.scene)
        self.report({'INFO'}, "%d new prop(s) found" % added)
        return {'FINISHED'}


class BANANA_OT_prop_add(bpy.types.Operator):
    """Import this prop (once) and place its main object at the 3D cursor in the active BSP"""
    bl_idname = "banana.prop_add"
    bl_label = "Add to BSP"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        prop = active_prop(context)
        bsp = context.scene.banana.active_bsp
        if prop is None or bsp is None:
            self.report({'ERROR'}, "Pick a prop and a BSP")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            obj = add_master(context, prop, bsp, context.scene.cursor.location.copy())
        except Exception as err:
            self.report({'ERROR'}, "Couldn't import %s: %s" % (os.path.basename(prop.file), err))
            return {'CANCELLED'}
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        self.report({'INFO'}, "Added %s to %s" % (obj.name, bsp.name))
        return {'FINISHED'}


class BANANA_OT_prop_remove(bpy.types.Operator):
    """Remove this prop from the list (objects already placed stay)"""
    bl_idname = "banana.prop_remove"
    bl_label = "Remove From List"

    def execute(self, context):
        s = context.scene
        if 0 <= s.banana_props_index < len(s.banana_props):
            s.banana_props.remove(s.banana_props_index)
            s.banana_props_index = max(0, s.banana_props_index - 1)
        return {'FINISHED'}


def _draw_cursor(op, _context):
    if op.hit is None:
        return
    try:
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    except Exception:
        shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
    c = op.hit
    pts = [(c.x + op.radius * math.cos(2 * math.pi * i / 48), c.y + op.radius * math.sin(2 * math.pi * i / 48), c.z + 0.05)
           for i in range(49)]
    gpu.state.line_width_set(2.0)
    gpu.state.depth_test_set('NONE')
    shader.bind()
    shader.uniform_float("color", (1.0, 0.35, 0.35, 1.0) if op.erasing else (0.4, 1.0, 0.4, 1.0))
    batch_for_shader(shader, 'LINE_STRIP', {"pos": pts}).draw(shader)
    gpu.state.line_width_set(1.0)


class BANANA_OT_prop_brush(bpy.types.Operator):
    """Paint the selected prop onto terrain/structure. Ctrl+click erases, [ ] radius, right-click/Esc done"""
    bl_idname = "banana.prop_brush"
    bl_label = "Paint Props"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def _raycast(self, context, event):
        region, rv3d = context.region, context.region_data
        coord = (event.mouse_region_x, event.mouse_region_y)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        best = None
        for obj in self.scatter.surfaces:
            inv = obj.matrix_world.inverted()
            ok, loc, _n, _i = obj.ray_cast(inv @ origin, (inv.to_3x3() @ direction).normalized())
            if ok:
                world = obj.matrix_world @ loc
                d = (world - origin).length
                if best is None or d < best[0]:
                    best = (d, world)
        return best[1] if best else None

    def _header(self, context):
        s = context.scene.banana
        context.area.header_text_set(
            "Paint %s · radius %.1f · %d per dab · spacing %.1f   LMB paint · Ctrl+LMB erase · [ ] radius · RMB/Esc done"
            % (full_name(self.prop), self.radius, s.prop_density, s.prop_spacing))

    def invoke(self, context, event):
        self.prop = active_prop(context)
        if self.prop is None:
            self.report({'ERROR'}, "Pick a prop in the list")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            import_model(self.prop)
        except Exception as err:
            self.report({'ERROR'}, "Couldn't import %s: %s" % (os.path.basename(self.prop.file), err))
            return {'CANCELLED'}
        self.scatter = Scatter(context, self.prop)
        if not self.scatter.surfaces:
            self.report({'ERROR'}, "Nothing to paint on: add terrain or structure to a BSP first")
            return {'CANCELLED'}
        self.radius = context.scene.banana.prop_radius
        self.hit = None
        self.painting = False
        self.erasing = False
        self.last = None
        self._handle = bpy.types.SpaceView3D.draw_handler_add(_draw_cursor, (self, context), 'WINDOW', 'POST_VIEW')
        context.window_manager.modal_handler_add(self)
        self._header(context)
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        if getattr(self, "_handle", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        if context.area is not None:
            context.area.header_text_set(None)
            context.area.tag_redraw()
        context.scene.banana.prop_radius = self.radius

    def _dab(self, context, point):
        s = context.scene.banana
        if self.erasing:
            erase(self.prop, point, self.radius)
        else:
            self.scatter.dab(point, self.radius, s.prop_density, s)
        self.last = point.copy()
        context.area.tag_redraw()

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except Exception as err:
            self._finish(context)
            self.report({'ERROR'}, "Prop brush stopped: %s" % err)
            return {'CANCELLED'}

    def _modal(self, context, event):
        context.area.tag_redraw()
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._finish(context)
            return {'FINISHED'}
        if event.type in NAV_EVENTS or event.type.startswith('NDOF') or event.type.startswith('NUMPAD'):
            return {'PASS_THROUGH'}
        if event.type in {'LEFT_BRACKET', 'RIGHT_BRACKET'} and event.value == 'PRESS':
            self.radius *= 0.85 if event.type == 'LEFT_BRACKET' else 1.0 / 0.85
            self._header(context)
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            self.hit = self._raycast(context, event)
            if self.painting and self.hit is not None:
                if self.last is None or (self.hit - self.last).length > self.radius * 0.5:
                    self._dab(context, self.hit)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self.hit = self._raycast(context, event)
                if self.hit is None:
                    return {'RUNNING_MODAL'}
                self.erasing = event.ctrl
                self.painting = True
                self._dab(context, self.hit)
            elif event.value == 'RELEASE' and self.painting:
                self.painting = False
                self.erasing = False
                self.last = None
                self.scatter.end_stroke()
                try:
                    bpy.ops.ed.undo_push(message="Banana Paint Props")
                except Exception:
                    pass
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}


class BANANA_UL_props(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        icon_id = thumbnail(item)
        row = layout.row(align=True)
        if icon_id:
            row.label(text=full_name(item), icon_value=icon_id)
        else:
            row.label(text=full_name(item), icon='MESH_DATA' if item.mesh else 'FILE_3D')
        count = len(prop_objects(item.uid))
        if count:
            row.label(text=str(count))


class BANANA_PT_props(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Banana"
    bl_label = "Props"

    def draw(self, context):
        scene = context.scene
        s = scene.banana
        layout = self.layout
        row = layout.row(align=True)
        row.prop(s, "prop_folder", text="")
        row.operator("banana.prop_scan", text="", icon='FILE_REFRESH')
        row = layout.row()
        row.template_list("BANANA_UL_props", "", scene, "banana_props", scene, "banana_props_index", rows=4)
        row.operator("banana.prop_remove", text="", icon='X')
        prop = active_prop(context)
        if prop is None:
            layout.label(text="Pick a folder of .glb models and press refresh")
            return
        icon_id = thumbnail(prop)
        if icon_id:
            layout.template_icon(icon_value=icon_id, scale=5.0)
        box = layout.box()
        box.prop(prop, "base")
        grid = box.grid_flow(columns=2, align=True)
        grid.prop(prop, "render_only")
        grid.prop(prop, "per_pixel")
        grid.prop(prop, "per_vertex")
        grid.prop(prop, "single_probe")
        row = box.row(align=True)
        row.prop(prop, "extra_flags")
        row.prop(prop, "suffix")
        box.label(text="Exports as: %s" % full_name(prop), icon='COPY_ID')

        layout.operator("banana.prop_add", icon='ADD')
        box = layout.box()
        box.label(text="Prop Brush", icon='BRUSH_DATA')
        row = box.row(align=True)
        row.prop(s, "prop_radius")
        row.prop(s, "prop_density")
        box.prop(s, "prop_spacing")
        row = box.row(align=True)
        row.prop(s, "prop_scale_min")
        row.prop(s, "prop_scale_max")
        row = box.row(align=True)
        row.prop(s, "prop_random_yaw")
        row.prop(s, "prop_align")
        box.prop(s, "prop_sink")
        box.operator("banana.prop_brush", text="Paint Props", icon='OUTLINER_OB_POINTCLOUD')
        box.label(text="Ctrl+click erases · [ ] radius · Right-click done")


CLASSES = (BananaProp, BANANA_OT_prop_scan, BANANA_OT_prop_add, BANANA_OT_prop_remove,
           BANANA_OT_prop_brush, BANANA_UL_props, BANANA_PT_props)


def register():
    global _previews
    import bpy.utils.previews
    _previews = bpy.utils.previews.new()
    bpy.types.Scene.banana_props = CollectionProperty(type=BananaProp)
    bpy.types.Scene.banana_props_index = IntProperty()


def unregister():
    global _previews
    del bpy.types.Scene.banana_props_index
    del bpy.types.Scene.banana_props
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
