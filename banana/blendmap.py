"""Terrain blend-map painting.

Halo 3 terrain shaders blend up to four materials using a blend map whose
R/G/B/A channels are layers 1/2/3/4, read through the terrain's UVs.

In Blender each BSP gets:
- a top-down `blend_uv` UV map over a fixed blend area (set once, so painting
  never shifts when you add tiles later),
- three grayscale weight images for layers 2-4 (layer 1 is the base: whatever the
  others don't cover). Upper layers sit over lower ones, and the viewport preview
  shows exactly what the bake will produce. Painting is done with the Banana
  terrain brush (brush.py),
- a preview node setup inside the terrain material, showing each layer's flat
  color or optional preview texture (the material keeps its name, which is the
  shader name Tool looks up; previews never reach the export).

Save Blend Map (and every export) bakes them into one RGBA TIFF:
  A = w4, B = w3 (1 - w4), G = w2 (1 - w3)(1 - w4), R = (1 - w2)(1 - w3)(1 - w4)
"""

import os

import bpy
import numpy as np
from bpy.app.handlers import persistent

from . import bsp as bsp_mod, naming

UV_NAME = "blend_uv"
LAYER_KEY = "banana_blend_layer"
NODE_PREFIX = "BANANA_"


def layer_image_name(bsp, n):
    return "%s_layer%d" % (bsp.name, n)


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
        n = len(mesh.loops)
        loop_vert = np.empty(n, np.int32)
        mesh.loops.foreach_get("vertex_index", loop_vert)
        co = np.empty(len(mesh.vertices) * 3, np.float32)
        mesh.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3).astype(np.float64)
        m = np.array(obj.matrix_world)
        world = co @ m[:3, :3].T + m[:3, 3]
        uv = np.empty((n, 2), np.float32)
        uv[:, 0] = (world[loop_vert, 0] - x0) / sx
        uv[:, 1] = (world[loop_vert, 1] - y0) / sy
        layer.data.foreach_set("uv", uv.ravel())
        mesh.update()
    return not_first


def ensure_layers(bsp):
    res = bsp.banana.blend_resolution
    images = []
    for n in (2, 3, 4):
        name = layer_image_name(bsp, n)
        img = bpy.data.images.get(name)
        if img is None:
            img = bpy.data.images.new(name, res, res, alpha=False)
            img.generated_color = (0.0, 0.0, 0.0, 1.0)
            img[LAYER_KEY] = n
            img.pack()
        images.append(img)
    return images


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


def build_preview(bsp, images):
    """Adds/rebuilds the BANANA_ preview nodes inside the terrain material.
    Preview only: the material's name (the shader name) is all the export uses."""
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

    uv = _node(nodes, "ShaderNodeUVMap", "uv", (-1500, 0))
    uv.uv_map = UV_NAME
    current = _layer_source(nodes, links, uv, b, 1, (-700, 400))
    for i, img in enumerate(images):
        n = i + 2
        weight = _node(nodes, "ShaderNodeTexImage", "layer%d" % n, (-1100, -300 * i))
        weight.image = img
        weight.extension = 'EXTEND'
        links.new(uv.outputs[0], weight.inputs[0])
        color = _layer_source(nodes, links, uv, b, n, (-700, -300 * i + 120))
        mix = _node(nodes, "ShaderNodeMix", "mix%d" % n, (-400, -300 * i))
        mix.data_type = 'RGBA'
        links.new(weight.outputs["Color"], mix.inputs[0])          # factor = painted weight
        links.new(current, mix.inputs[6])                            # A
        links.new(color, mix.inputs[7])                              # B
        current = mix.outputs[2]
    links.new(current, bsdf.inputs["Base Color"])
    return mat


def setup(bsp):
    """UVs + layer images + preview. Returns (objects, warnings)."""
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
    images = ensure_layers(bsp)
    build_preview(bsp, images)
    return objs, warnings


def bake_pixels(bsp):
    imgs = [bpy.data.images.get(layer_image_name(bsp, n)) for n in (2, 3, 4)]
    if any(i is None for i in imgs):
        return None, None
    size = tuple(imgs[0].size)
    if any(tuple(i.size) != size for i in imgs):
        raise RuntimeError("The three blend layers of %s have different sizes" % bsp.name)
    w = []
    for img in imgs:
        px = np.empty(size[0] * size[1] * 4, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(-1, 4)
        w.append(np.clip(px[:, :3].mean(axis=1), 0.0, 1.0))
    w2, w3, w4 = w
    out = np.empty((size[0] * size[1], 4), np.float32)
    out[:, 3] = w4
    out[:, 2] = w3 * (1 - w4)
    out[:, 1] = w2 * (1 - w3) * (1 - w4)
    out[:, 0] = (1 - w2) * (1 - w3) * (1 - w4)
    return out, size


def bake(bsp, path):
    pixels, size = bake_pixels(bsp)
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


@persistent
def _pack_on_save(_dummy):
    """Painted layers live only in memory; pack them into the .blend when saving."""
    for img in bpy.data.images:
        if img.get(LAYER_KEY) is not None and img.is_dirty:
            img.pack()


# ------------------------------------------------------------------ operators

class BANANA_OT_blend_setup(bpy.types.Operator):
    """Create the blend UVs, paint layers and preview for the active BSP's terrain"""
    bl_idname = "banana.blend_setup"
    bl_label = "Set Up Blend Map"
    bl_options = {'REGISTER', 'UNDO'}

    refit: bpy.props.BoolProperty(name="Refit Area", default=False,
                                  description="Refit the blend area to the terrain (moves anything already painted)")

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
        self.report({'INFO'}, "Blend map ready on %d terrain object(s)" % len(objs))
        return {'FINISHED'}


class BANANA_OT_clear_layer(bpy.types.Operator):
    """Erase a terrain layer everywhere"""
    bl_idname = "banana.clear_layer"
    bl_label = "Clear Layer"
    bl_options = {'REGISTER', 'UNDO'}

    layer: bpy.props.IntProperty(min=2, max=4, default=2)

    def execute(self, context):
        bsp = context.scene.banana.active_bsp
        img = bpy.data.images.get(layer_image_name(bsp, self.layer)) if bsp else None
        if img is None:
            return {'CANCELLED'}
        px = np.zeros(img.size[0] * img.size[1] * 4, np.float32)
        px[3::4] = 1.0
        img.pixels.foreach_set(px)
        img.update()
        return {'FINISHED'}


class BANANA_OT_save_blend_map(bpy.types.Operator):
    """Bake the layers into the RGBA blend map TIFF in your level's bitmaps folder"""
    bl_idname = "banana.save_blend_map"
    bl_label = "Save Blend Map"

    def execute(self, context):
        bsp = context.scene.banana.active_bsp
        if bsp is None:
            return {'CANCELLED'}
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
        layout.prop(b, "terrain_material")
        row = layout.row(align=True)
        row.prop(b, "blend_resolution")
        row.operator("banana.blend_setup", text="", icon='UV').refit = False
        row.operator("banana.blend_setup", text="", icon='FULLSCREEN_ENTER').refit = True

        for n, label in ((1, "1 Base (R)"), (2, "2 (G)"), (3, "3 (B)"), (4, "4 (A)")):
            box = layout.box()
            row = box.row(align=True)
            row.label(text=label)
            row.prop(b, "layer%d_color" % n, text="")
            if n > 1:
                row.operator("banana.clear_layer", text="", icon='X').layer = n
            row = box.row(align=True)
            row.template_ID(b, "layer%d_image" % n, open="image.open")
            if getattr(b, "layer%d_image" % n) is not None:
                box.prop(b, "layer%d_tile" % n)

        box = layout.box()
        box.label(text="Blend Brush", icon='BRUSH_DATA')
        box.row(align=True).prop(s, "blend_mode", expand=True)
        row = box.row(align=True)
        row.enabled = s.blend_mode == 'PAINT'
        row.prop(s, "blend_layer", expand=True)
        row = box.row(align=True)
        row.prop(s, "brush_radius")
        row.prop(s, "blend_opacity", slider=True)
        box.operator("banana.terrain_brush", text="Paint Blend", icon='TPAINT_HLT').mode = 'BLEND'
        layout.operator("banana.save_blend_map", icon='IMAGE_DATA')


CLASSES = (BANANA_OT_blend_setup, BANANA_OT_clear_layer,
           BANANA_OT_save_blend_map, BANANA_PT_blend)


def register():
    bpy.app.handlers.save_pre.append(_pack_on_save)


def unregister():
    if _pack_on_save in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_pack_on_save)
