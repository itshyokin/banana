"""Terrain blend painting with vertex colors (like the Titamas add-on).

Halo 3 terrain shaders blend up to four materials using a blend map bitmap whose
R/G/B/A channels are layers 1/2/3/4, read through the terrain's first UV map.

In Blender each terrain BSP has:
- its own terrain material (named after the BSP: every BSP needs its own
  shader_terrain, because every BSP has its own blend map),
- a point color attribute `blend` painted in Blender's Vertex Paint mode:
  red = layer 1, green = layer 2, blue = layer 3, black = layer 4
  (layer 4 is whatever red + green + blue leave over),
- a top-down `blend_uv` UV map over the terrain (0-1), which is what Halo samples
  the blend map with,
- preview nodes inside the terrain material that show each layer's flat color or
  preview texture, weighted by the paint (viewport only; the export only uses the
  material's name).

Save Blend Map (and every export) turns the vertex colors into the RGBA TIFF:
  w4 = max(0, 1 - (r + g + b)), then (r, g, b, w4) / their sum.
Blend detail follows the vertex spacing; the bake interpolates smoothly between vertices.
"""

import os

import bpy
import numpy as np

from . import bsp as bsp_mod, naming

UV_NAME = "blend_uv"
COLOR_NAME = "blend"
NODE_PREFIX = "BANANA_"
LAYER_COLORS = {1: (1.0, 0.0, 0.0), 2: (0.0, 1.0, 0.0), 3: (0.0, 0.0, 1.0), 4: (0.0, 0.0, 0.0)}


def default_material_name(bsp):
    return "%s_terrain" % bpy.path.clean_name(bsp.name)


def terrain_objects(bsp):
    name = bsp.banana.terrain_material
    out = []
    for obj in bsp_mod.objects_for_role(bsp, 'STRUCTURE'):
        if any(s.material and naming.strip_suffix(s.material.name) == name for s in obj.material_slots):
            out.append(obj)
    return out


def fit_area(bsp, objs):
    xs, ys = [], []
    for obj in objs:
        mw = obj.matrix_world
        for v in obj.data.vertices:
            w = mw @ v.co
            xs.append(w.x)
            ys.append(w.y)
    b = bsp.banana
    b.blend_min = (min(xs), min(ys))
    b.blend_max = (max(xs), max(ys))
    b.blend_set = True


def _world_xy(obj):
    co = np.empty(len(obj.data.vertices) * 3, np.float32)
    obj.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    m = np.array(obj.matrix_world)
    return (co @ m[:3, :3].T + m[:3, 3])[:, :2]


def apply_uvs(bsp, objs):
    """Top-down projection of the blend area onto 0-1. Returns objects whose
    blend_uv isn't the first UV map."""
    b = bsp.banana
    x0, y0 = b.blend_min
    x1, y1 = b.blend_max
    sx = (x1 - x0) or 1.0
    sy = (y1 - y0) or 1.0
    not_first = []
    for obj in objs:
        mesh = obj.data
        layer = mesh.uv_layers.get(UV_NAME) or mesh.uv_layers.new(name=UV_NAME)
        if mesh.uv_layers[0].name != UV_NAME:
            not_first.append(obj.name)
        loop_vert = np.empty(len(mesh.loops), np.int32)
        mesh.loops.foreach_get("vertex_index", loop_vert)
        xy = _world_xy(obj)
        uv = np.empty((len(mesh.loops), 2), np.float32)
        uv[:, 0] = (xy[loop_vert, 0] - x0) / sx
        uv[:, 1] = (xy[loop_vert, 1] - y0) / sy
        layer.data.foreach_set("uv", uv.ravel())
        mesh.update()
    return not_first


# ------------------------------------------------------------------ colors <-> weights

def weights_from_colors(rgb):
    """(n, 3) painted colors -> (n, 4) layer weights that add up to 1."""
    rgb = np.clip(rgb, 0.0, 1.0)
    w4 = np.clip(1.0 - rgb.sum(axis=1), 0.0, 1.0)
    w = np.column_stack((rgb, w4))
    return w / np.maximum(w.sum(axis=1, keepdims=True), 1e-6)


def ensure_colors(obj, base=(1.0, 0.0, 0.0)):
    mesh = obj.data
    attr = mesh.color_attributes.get(COLOR_NAME)
    if attr is None:
        attr = mesh.color_attributes.new(COLOR_NAME, 'FLOAT_COLOR', 'POINT')
        fill = np.tile(np.array((*base, 1.0), np.float32), len(mesh.vertices))
        attr.data.foreach_set("color", fill)
    mesh.color_attributes.active_color = attr
    try:
        mesh.color_attributes.render_color_index = mesh.color_attributes.active_color_index
    except Exception:
        pass
    return attr


def read_colors(obj):
    attr = obj.data.color_attributes.get(COLOR_NAME)
    n = len(obj.data.vertices)
    if attr is None or attr.domain != 'POINT':
        return np.tile(np.array((1.0, 0.0, 0.0)), (n, 1))
    px = np.empty(n * 4, np.float32)
    attr.data.foreach_get("color", px)
    return px.reshape(-1, 4)[:, :3].astype(np.float64)


def convert_old_layers(bsp, objs):
    """v0.5 painted three grayscale images; turn them into vertex colors once."""
    imgs = [bpy.data.images.get("%s_layer%d" % (bsp.name, n)) for n in (2, 3, 4)]
    if any(i is None for i in imgs):
        return False
    b = bsp.banana
    (x0, y0), (x1, y1) = b.blend_min, b.blend_max
    w, h = imgs[0].size
    layers = []
    for img in imgs:
        px = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(px)
        layers.append(px.reshape(h, w, 4)[:, :, 0])
    for obj in objs:
        xy = _world_xy(obj)
        u = np.clip(((xy[:, 0] - x0) / ((x1 - x0) or 1.0) * w).astype(int), 0, w - 1)
        v = np.clip(((xy[:, 1] - y0) / ((y1 - y0) or 1.0) * h).astype(int), 0, h - 1)
        w2, w3, w4 = (np.clip(L[v, u], 0, 1) for L in layers)
        rgb = np.column_stack(((1 - w2) * (1 - w3) * (1 - w4), w2 * (1 - w3) * (1 - w4), w3 * (1 - w4)))
        attr = ensure_colors(obj)
        rgba = np.column_stack((rgb, np.ones(len(rgb)))).astype(np.float32)
        attr.data.foreach_set("color", rgba.ravel())
        obj.data.update()
    for img in imgs:
        img["banana_converted"] = True
    return True


# ------------------------------------------------------------------ preview nodes

def _node(nodes, kind, name, location):
    node = nodes.new(kind)
    node.name = node.label = NODE_PREFIX + name
    node.location = location
    return node


def _layer_source(nodes, links, uv, b, n, location):
    """A color for layer n: its preview texture (tiled in meters) if set, else its flat color."""
    image = getattr(b, "layer%d_image" % n)
    if image is None:
        rgb = _node(nodes, "ShaderNodeRGB", "color%d" % n, location)
        rgb.outputs[0].default_value = (*getattr(b, "layer%d_color" % n), 1.0)
        return rgb.outputs[0]
    tile = getattr(b, "layer%d_tile" % n)
    (x0, y0), (x1, y1) = b.blend_min, b.blend_max
    mapping = _node(nodes, "ShaderNodeMapping", "map%d" % n, (location[0] - 200, location[1]))
    mapping.inputs["Scale"].default_value = (max(x1 - x0, 1e-3) / tile, max(y1 - y0, 1e-3) / tile, 1.0)
    links.new(uv.outputs[0], mapping.inputs["Vector"])
    tex = _node(nodes, "ShaderNodeTexImage", "tex%d" % n, location)
    tex.image = image
    links.new(mapping.outputs[0], tex.inputs[0])
    return tex.outputs["Color"]


def build_preview(bsp, _unused=None):
    """Adds/rebuilds the BANANA_ preview nodes inside this BSP's terrain material."""
    b = bsp.banana
    mat = bpy.data.materials.get(b.terrain_material) or bpy.data.materials.new(b.terrain_material)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    for node in [n for n in nodes if n.name.startswith(NODE_PREFIX)]:
        nodes.remove(node)
    bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        out = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None) or nodes.new("ShaderNodeOutputMaterial")
        links.new(bsdf.outputs[0], out.inputs[0])

    def math(op, a, b_, name, loc):
        node = _node(nodes, "ShaderNodeMath", name, loc)
        node.operation = op
        for i, src in enumerate((a, b_)):
            if isinstance(src, (int, float)):
                node.inputs[i].default_value = src
            else:
                links.new(src, node.inputs[i])
        return node.outputs[0]

    uv = _node(nodes, "ShaderNodeUVMap", "uv", (-1700, 300))
    uv.uv_map = UV_NAME
    paint = _node(nodes, "ShaderNodeVertexColor", "paint", (-1700, -200))
    paint.layer_name = COLOR_NAME
    sep = _node(nodes, "ShaderNodeSeparateColor", "split", (-1500, -200))
    links.new(paint.outputs["Color"], sep.inputs[0])
    r, g, bl = sep.outputs[0], sep.outputs[1], sep.outputs[2]
    rgb_sum = math('ADD', math('ADD', r, g, "sum_rg", (-1300, -150)), bl, "sum_rgb", (-1150, -150))
    w4 = math('MAXIMUM', math('SUBTRACT', 1.0, rgb_sum, "rest", (-1000, -250)), 0.0, "w4", (-850, -250))
    total = math('ADD', rgb_sum, w4, "total", (-700, -250))
    inv = math('DIVIDE', 1.0, math('MAXIMUM', total, 1e-6, "total_safe", (-550, -250)), "inv", (-400, -250))

    current = None
    for n, weight in ((1, r), (2, g), (3, bl), (4, w4)):
        src = _layer_source(nodes, links, uv, b, n, (-900, 500 - 220 * n))
        scaled = _node(nodes, "ShaderNodeVectorMath", "scale%d" % n, (-600, 500 - 220 * n))
        scaled.operation = 'SCALE'
        links.new(src, scaled.inputs[0])
        links.new(weight, scaled.inputs["Scale"])
        if current is None:
            current = scaled.outputs[0]
        else:
            add = _node(nodes, "ShaderNodeVectorMath", "add%d" % n, (-400, 500 - 220 * n))
            add.operation = 'ADD'
            links.new(current, add.inputs[0])
            links.new(scaled.outputs[0], add.inputs[1])
            current = add.outputs[0]
    final = _node(nodes, "ShaderNodeVectorMath", "normalize", (-200, 0))
    final.operation = 'SCALE'
    links.new(current, final.inputs[0])
    links.new(inv, final.inputs["Scale"])
    links.new(final.outputs[0], bsdf.inputs["Base Color"])
    return mat


def setup(bsp):
    """UVs + paint colors + preview. Returns (objects, warnings)."""
    objs = terrain_objects(bsp)
    if not objs:
        return [], ["No terrain in %s uses the '%s' material" % (bsp.name, bsp.banana.terrain_material)]
    warnings = []
    if not bsp.banana.blend_set:
        fit_area(bsp, objs)
    not_first = apply_uvs(bsp, objs)
    if not_first:
        warnings.append("blend_uv isn't the first UV map on %s; Halo reads the blend map from the first one"
                        % ", ".join(not_first[:4]))
    if not any(o.data.color_attributes.get(COLOR_NAME) for o in objs):
        convert_old_layers(bsp, objs)
    for obj in objs:
        ensure_colors(obj)
    build_preview(bsp)
    return objs, warnings


# ------------------------------------------------------------------ bake

def _tile_grid(obj):
    """(nx, ny, size_x, size_y) if obj is an untouched-topology Banana terrain tile."""
    from .terrain import TILE_KEY
    info = obj.get(TILE_KEY)
    if info is None:
        return None
    sx, sy, sp = info["size_x"], info["size_y"], info["spacing"]
    nx, ny = max(1, int(round(sx / sp))), max(1, int(round(sy / sp)))
    if len(obj.data.vertices) != (nx + 1) * (ny + 1):
        return None
    return nx, ny, sx, sy


def bake_pixels(bsp):
    """RGBA blend map from the vertex colors, size = Blend Map Size, over the blend area."""
    b = bsp.banana
    objs = terrain_objects(bsp)
    if not b.blend_set or not objs:
        return None, None, []
    res = b.blend_resolution
    (x0, y0), (x1, y1) = b.blend_min, b.blend_max
    out = np.zeros((res, res, 4), np.float32)
    out[..., 0] = 1.0  # outside any tile: layer 1
    px = x0 + (np.arange(res) + 0.5) / res * (x1 - x0)
    py = y0 + (np.arange(res) + 0.5) / res * (y1 - y0)
    gx, gy = np.meshgrid(px, py)
    skipped = []
    for obj in objs:
        grid = _tile_grid(obj)
        if grid is None:
            skipped.append(obj.name)
            continue
        nx, ny, sx, sy = grid
        weights = weights_from_colors(read_colors(obj)).reshape(ny + 1, nx + 1, 4)
        inv = np.array(obj.matrix_world.inverted())
        lx = inv[0, 0] * gx + inv[0, 1] * gy + inv[0, 3]
        ly = inv[1, 0] * gx + inv[1, 1] * gy + inv[1, 3]
        fx = (lx + sx / 2.0) / sx * nx
        fy = (ly + sy / 2.0) / sy * ny
        inside = (fx >= -1e-6) & (fx <= nx + 1e-6) & (fy >= -1e-6) & (fy <= ny + 1e-6)
        if not inside.any():
            continue
        fx, fy = np.clip(fx[inside], 0, nx), np.clip(fy[inside], 0, ny)
        i0, j0 = np.minimum(fx.astype(int), nx - 1), np.minimum(fy.astype(int), ny - 1)
        tx, ty = (fx - i0)[:, None], (fy - j0)[:, None]
        val = (weights[j0, i0] * (1 - tx) * (1 - ty) + weights[j0, i0 + 1] * tx * (1 - ty)
               + weights[j0 + 1, i0] * (1 - tx) * ty + weights[j0 + 1, i0 + 1] * tx * ty)
        out[inside] = val
    return out.reshape(-1, 4), (res, res), skipped


def bake(bsp, path):
    pixels, size, _skipped = bake_pixels(bsp)
    if pixels is None:
        return None
    name = "%s_blend_map" % bsp.name
    img = bpy.data.images.get(name)
    if img is not None and tuple(img.size) != size:
        bpy.data.images.remove(img)
        img = None
    if img is None:
        img = bpy.data.images.new(name, size[0], size[1], alpha=True)
    img.alpha_mode = 'STRAIGHT'
    img.colorspace_settings.name = 'Non-Color'
    img.pixels.foreach_set(pixels.ravel())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.filepath_raw = path
    img.file_format = 'TIFF'
    img.save()
    return path


def blend_path(context, bsp):
    from .export import bsp_file_name, level_dir
    base = level_dir(context)
    if not base:
        return None
    return os.path.join(base, "bitmaps", bsp_file_name(bsp) + "_blend.tif")


# ------------------------------------------------------------------ operators

def _active_terrain(context):
    bsp = context.scene.banana.active_bsp
    if bsp is None:
        return None, None, "Pick a BSP"
    objs = terrain_objects(bsp)
    if not objs:
        return bsp, None, "No terrain in %s uses its terrain material '%s'" % (bsp.name, bsp.banana.terrain_material)
    obj = context.active_object if context.active_object in objs else objs[0]
    return bsp, obj, None


def _set_vertex_tool(context, tool):
    try:
        bpy.ops.wm.tool_set_by_id(name="builtin_brush.%s" % tool, space_type='VIEW_3D')
        return True
    except Exception:
        return False


def _set_paint_color(context, color):
    ups = context.tool_settings.unified_paint_settings
    brush = context.tool_settings.vertex_paint.brush if context.tool_settings.vertex_paint else None
    for holder in (ups, brush):
        if holder is None:
            continue
        try:
            holder.color = color
        except Exception:
            pass


class BANANA_OT_blend_setup(bpy.types.Operator):
    """Set up blend painting on the active BSP's terrain (UVs, paint colors, preview)"""
    bl_idname = "banana.blend_setup"
    bl_label = "Set Up Blend Map"
    bl_options = {'REGISTER', 'UNDO'}

    refit: bpy.props.BoolProperty(name="Refit Area", default=False,
                                  description="Refit the blend area to the terrain")

    def execute(self, context):
        bsp = context.scene.banana.active_bsp
        if bsp is None:
            self.report({'ERROR'}, "Pick a BSP")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if self.refit:
            bsp.banana.blend_set = False
        objs, warnings = setup(bsp)
        for w in warnings:
            self.report({'WARNING'}, w)
        if not objs:
            return {'CANCELLED'}
        self.report({'INFO'}, "Blend painting ready on %s" % ", ".join(o.name for o in objs))
        return {'FINISHED'}


class BANANA_OT_paint_blend(bpy.types.Operator):
    """Paint this layer in Vertex Paint mode (strength and falloff are Blender's own brush settings)"""
    bl_idname = "banana.paint_blend"
    bl_label = "Paint Layer"
    bl_options = {'REGISTER', 'UNDO'}

    layer: bpy.props.IntProperty(min=0, max=4, default=1, description="1-4 = paint that layer, 0 = blur")

    def execute(self, context):
        bsp, obj, err = _active_terrain(context)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        if obj.mode != 'VERTEX_PAINT':
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            setup(bsp)
            for o in context.selected_objects:
                o.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
            ensure_colors(obj)
            bpy.ops.object.mode_set(mode='VERTEX_PAINT')
            space = context.space_data
            if space is not None and space.type == 'VIEW_3D' and context.scene.banana.preview_while_painting:
                space.shading.type = 'MATERIAL'
        if self.layer == 0:
            if not _set_vertex_tool(context, "Blur"):
                self.report({'WARNING'}, "Pick the Blur brush from the toolbar")
            return {'FINISHED'}
        _set_vertex_tool(context, "Draw")
        _set_paint_color(context, LAYER_COLORS[self.layer])
        context.scene.banana.paint_layer = str(self.layer)
        return {'FINISHED'}


class BANANA_OT_fill_layer(bpy.types.Operator):
    """Fill the whole terrain with this layer"""
    bl_idname = "banana.fill_layer"
    bl_label = "Fill Layer"
    bl_options = {'REGISTER', 'UNDO'}

    layer: bpy.props.IntProperty(min=1, max=4, default=1)

    def execute(self, context):
        bsp, obj, err = _active_terrain(context)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        mode = obj.mode
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for o in terrain_objects(bsp):
            attr = ensure_colors(o)
            fill = np.tile(np.array((*LAYER_COLORS[self.layer], 1.0), np.float32), len(o.data.vertices))
            attr.data.foreach_set("color", fill)
            o.data.update()
        if mode == 'VERTEX_PAINT':
            bpy.ops.object.mode_set(mode='VERTEX_PAINT')
        return {'FINISHED'}


class BANANA_OT_done_painting(bpy.types.Operator):
    """Back to Object Mode"""
    bl_idname = "banana.done_painting"
    bl_label = "Done Painting"

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}


class BANANA_OT_unique_terrain_material(bpy.types.Operator):
    """Give this BSP's terrain its own terrain material (each BSP needs its own shader_terrain)"""
    bl_idname = "banana.unique_terrain_material"
    bl_label = "Make Unique"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bsp = context.scene.banana.active_bsp
        if bsp is None:
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        old_name = bsp.banana.terrain_material
        objs = terrain_objects(bsp)
        new_name = default_material_name(bsp)
        if old_name == new_name and objs:
            self.report({'INFO'}, "%s already has its own material" % bsp.name)
            return {'FINISHED'}
        old = bpy.data.materials.get(old_name)
        others = [o for o in bsp_mod.find_bsps(context.scene) if o is not bsp]
        existing = bpy.data.materials.get(new_name)
        in_use = existing is not None and any(o.banana.terrain_material == new_name for o in others)
        if existing is not None and not in_use:
            new = existing  # reuse a free material that already has this BSP's name
        else:
            new = old.copy() if old is not None else bpy.data.materials.new(new_name)
            new.name = new_name
        for obj in objs:
            for slot in obj.material_slots:
                if slot.material and naming.strip_suffix(slot.material.name) == old_name:
                    slot.material = new
        bsp.banana.terrain_material = new.name
        if bsp.banana.blend_set:
            build_preview(bsp)
        self.report({'INFO'}, "%s now uses %s" % (bsp.name, new.name))
        return {'FINISHED'}


class BANANA_OT_save_blend_map(bpy.types.Operator):
    """Turn the painted vertex colors into the RGBA blend map TIFF in your level's bitmaps folder"""
    bl_idname = "banana.save_blend_map"
    bl_label = "Save Blend Map"

    def execute(self, context):
        bsp = context.scene.banana.active_bsp
        if bsp is None:
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        path = blend_path(context, bsp)
        if path is None:
            self.report({'ERROR'}, "Set your H3EK folder or an export folder first")
            return {'CANCELLED'}
        if bake(bsp, path) is None:
            self.report({'ERROR'}, "Set up the blend map first")
            return {'CANCELLED'}
        self.report({'INFO'}, "Saved %s" % path)
        return {'FINISHED'}


class BANANA_PT_blend(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Banana"
    bl_label = "Blend Map"
    bl_parent_id = "BANANA_PT_terrain"

    def draw(self, context):
        s = context.scene.banana
        bsp = s.active_bsp
        layout = self.layout
        if bsp is None:
            layout.label(text="Pick a BSP")
            return
        b = bsp.banana
        row = layout.row(align=True)
        row.prop(b, "terrain_material", text="Shader")
        row.operator("banana.unique_terrain_material", text="", icon='DUPLICATE')
        shared = [o.name for o in bsp_mod.find_bsps(context.scene)
                  if o is not bsp and o.banana.terrain_material == b.terrain_material and terrain_objects(o)]
        if shared:
            layout.label(text="Shared with %s: press Make Unique" % ", ".join(shared[:2]), icon='ERROR')
        row = layout.row(align=True)
        row.prop(b, "blend_resolution")
        row.operator("banana.blend_setup", text="", icon='UV').refit = False

        painting = context.mode == 'PAINT_VERTEX'
        for n, label in ((1, "1 Red (R)"), (2, "2 Green (G)"), (3, "3 Blue (B)"), (4, "4 Black (A)")):
            box = layout.box()
            row = box.row(align=True)
            op = row.operator("banana.paint_blend", text="Paint %s" % label, icon='BRUSH_DATA',
                              depress=painting and s.paint_layer == str(n))
            op.layer = n
            row.prop(b, "layer%d_color" % n, text="")
            row.operator("banana.fill_layer", text="", icon='SNAP_FACE').layer = n
            row = box.row(align=True)
            row.template_ID(b, "layer%d_image" % n, open="image.open")
            if getattr(b, "layer%d_image" % n) is not None:
                box.prop(b, "layer%d_tile" % n)
        row = layout.row(align=True)
        row.operator("banana.paint_blend", text="Blur", icon='MOD_SMOOTH').layer = 0
        if painting:
            row.operator("banana.done_painting", icon='CHECKMARK')
        layout.prop(s, "preview_while_painting")
        layout.label(text="Radius/strength: Blender's brush settings (F / Shift+F)", icon='INFO')
        layout.operator("banana.save_blend_map", icon='IMAGE_DATA')


CLASSES = (BANANA_OT_blend_setup, BANANA_OT_paint_blend, BANANA_OT_fill_layer, BANANA_OT_done_painting,
           BANANA_OT_unique_terrain_material, BANANA_OT_save_blend_map, BANANA_PT_blend)


def register():
    pass


def unregister():
    pass
