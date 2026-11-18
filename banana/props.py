"""Settings stored on the add-on, the scene, BSP collections and objects."""

import bpy
from bpy.props import (
    BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty,
    IntProperty, PointerProperty, StringProperty,
)

ADDON_ID = __package__

# 1 Halo world unit = 10 ft = 3.048 m, and 1 world unit = 100 ASS/JMS units.
METERS_TO_ASS = 100.0 / 3.048

ROLE_ITEMS = (
    ('NONE', "None", "Not part of a Banana BSP"),
    ('BSP', "BSP", "Top-level BSP collection"),
    ('STRUCTURE', "Structure", "Sealed level geometry"),
    ('INSTANCES', "Instances", "Instance geometry (props); sub-collections included"),
    ('DESIGN', "Design", "Soft ceilings, kill zones, slip surfaces, water physics"),
    ('PORTALS', "Portals", "Portal planes; every face exports as +portal"),
)


class BananaPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    h3ek_path: StringProperty(
        name="H3EK Folder",
        description="Your Halo 3 Editing Kit folder (the one containing tool.exe, data and tags)",
        subtype='DIR_PATH',
    )
    tool_exe: EnumProperty(
        name="Tool",
        items=(('tool.exe', "tool.exe", ""), ('tool_fast.exe', "tool_fast.exe", "")),
        default='tool.exe',
    )

    def draw(self, context):
        self.layout.prop(self, "h3ek_path")
        self.layout.prop(self, "tool_exe")


def prefs(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon else None


class BananaProblem(bpy.types.PropertyGroup):
    severity: EnumProperty(items=(('ERROR', "Error", ""), ('WARNING', "Warning", ""), ('INFO', "Info", "")))
    message: StringProperty()
    object_name: StringProperty()
    bsp_name: StringProperty()
    count: IntProperty(default=1)


class BananaScene(bpy.types.PropertyGroup):
    level_name: StringProperty(name="Level Name", default="my_level")
    level_type: EnumProperty(
        name="Type",
        items=(('multi', "Multiplayer", "data\\levels\\multi"), ('solo', "Campaign", "data\\levels\\solo")),
        default='solo',
    )
    scale_mode: EnumProperty(
        name="Scale",
        items=(
            ('METERS', "Real Meters", "Model in meters (matches GLB props); 1 m = 32.81 ASS units"),
            ('JMS', "JMS Units", "1 Blender unit = 1 ASS unit (100 per world unit)"),
            ('CUSTOM', "Custom", "Your own multiplier"),
        ),
        default='METERS',
    )
    custom_scale: FloatProperty(name="Multiplier", default=1.0, min=0.0001)
    export_root: StringProperty(
        name="Export Folder Override",
        description="Leave empty to export to <H3EK>\\data\\levels\\<type>\\<level>",
        subtype='DIR_PATH',
    )
    design_mode: EnumProperty(
        name="Design Export",
        items=(
            ('SEPARATE', "Separate File", "Design pieces go to structure_design\\<bsp>.ass"),
            ('COMBINED', "Same File", "Design pieces go into the BSP's structure .ass"),
        ),
        default='SEPARATE',
    )
    run_tool_after_export: BoolProperty(name="Run Tool After Export", default=False)
    sky_height_auto: BoolProperty(
        name="Auto Sky Height", default=True,
        description="Put the sky shell top 30 m above the highest terrain in any BSP",
    )
    sky_height: FloatProperty(
        name="Sky Height", default=100.0, subtype='DISTANCE',
        description="World height of every sky shell's top (shared so seams between BSPs match)",
    )
    seam_top_material: StringProperty(
        name="Seam Top", default="+seamsealer",
        description="Material for the sky-cap strip along the top of each seam, so the seam ends on real "
                    "geometry instead of +sky. Empty = plain +sky")
    prop_folder: StringProperty(name="Prop Folder", subtype='DIR_PATH',
                                description="Folder of .glb/.gltf models to use as props")
    prop_radius: FloatProperty(name="Radius", default=8.0, min=0.1, subtype='DISTANCE')
    prop_density: IntProperty(name="Per Dab", default=3, min=1, max=50,
                              description="How many props each dab tries to place")
    prop_spacing: FloatProperty(name="Min Spacing", default=3.0, min=0.0, subtype='DISTANCE',
                                description="No two copies of a prop closer than this")
    prop_scale_min: FloatProperty(name="Scale Min", default=0.9, min=0.01)
    prop_scale_max: FloatProperty(name="Scale Max", default=1.1, min=0.01)
    prop_random_yaw: BoolProperty(name="Random Rotation", default=True)
    prop_align: BoolProperty(name="Align to Surface", default=False,
                             description="Tilt props to the ground's slope (off: always upright, like trees)")
    prop_sink: FloatProperty(name="Sink", default=0.0, subtype='DISTANCE',
                             description="Push props this far into the ground")
    live_meters: BoolProperty(name="Live Meters", default=True,
                              description="Recount the limit meters shortly after you stop editing")
    lock_borders: BoolProperty(name="Lock Borders", default=True,
                               description="Mask terrain borders while sculpting so seams and the sky shell stay sealed")
    border_rings: IntProperty(name="Border Falloff", default=2, min=0, max=10,
                              description="Rings of vertices next to the border that are partly locked, for a soft edge")
    brush_height: FloatProperty(name="Height", default=0.0, subtype='DISTANCE',
                                description="Target height the Set Height brush paints toward (world Z)")
    brush_radius: FloatProperty(name="Radius", default=5.0, min=0.1, subtype='DISTANCE')
    brush_strength: FloatProperty(name="Strength", default=0.5, min=0.01, max=1.0,
                                  description="How far toward the target height each dab moves the terrain")
    paint_layer: StringProperty(default="1")
    preview_while_painting: BoolProperty(
        name="Show Textures While Painting", default=True,
        description="Switch the 3D view to Material Preview when painting, so the layer textures show")
    meter_overlay: BoolProperty(name="Viewport Overlay", default=False,
                                description="Show the active BSP's meters in the corner of the 3D view")
    active_bsp: PointerProperty(
        name="BSP", type=bpy.types.Collection,
        poll=lambda self, coll: coll.banana.role == 'BSP',
    )
    problems: CollectionProperty(type=BananaProblem)
    problems_index: IntProperty()

    def scale(self):
        if self.scale_mode == 'METERS':
            return METERS_TO_ASS
        if self.scale_mode == 'JMS':
            return 1.0
        return self.custom_scale


def _refresh_preview(self, context):
    coll = self.id_data
    if isinstance(coll, bpy.types.Collection) and self.blend_set:
        from . import blendmap
        blendmap.build_preview(coll)


class BananaCollection(bpy.types.PropertyGroup):
    role: EnumProperty(name="Role", items=ROLE_ITEMS, default='NONE')
    export_enabled: BoolProperty(name="Export", default=True)
    sky_index: IntProperty(
        name="Sky Index", default=0, min=0, max=31,
        description="Faces using the plain '+sky' material export as +sky<index>",
    )
    terrain_material: StringProperty(
        name="Terrain Shader", default="terrain",
        description="Name of this BSP's shader_terrain tag; new tiles and the blend-map preview use it")
    blend_resolution: IntProperty(name="Blend Map Size", default=1024, min=64, max=8192)
    seam_material: PointerProperty(
        name="Seam Material", type=bpy.types.Material,
        description="This BSP's seam material (created by Generate Seam as '+seam'; rename it as you like)")
    blend_set: BoolProperty(default=False)
    blend_min: FloatVectorProperty(size=2)
    blend_max: FloatVectorProperty(size=2)
    layer1_color: FloatVectorProperty(name="Layer 1 (R)", subtype='COLOR', size=3, min=0, max=1, default=(1.0, 0.0, 0.0), update=_refresh_preview)
    layer2_color: FloatVectorProperty(name="Layer 2 (G)", subtype='COLOR', size=3, min=0, max=1, default=(0.0, 1.0, 0.0), update=_refresh_preview)
    layer3_color: FloatVectorProperty(name="Layer 3 (B)", subtype='COLOR', size=3, min=0, max=1, default=(0.0, 0.0, 1.0), update=_refresh_preview)
    layer4_color: FloatVectorProperty(name="Layer 4 (A)", subtype='COLOR', size=3, min=0, max=1, default=(0.0, 0.0, 0.0), update=_refresh_preview)
    layer1_image: PointerProperty(name="Preview Texture", type=bpy.types.Image, update=_refresh_preview,
                                  description="Optional texture shown in the viewport for this layer (export is unaffected)")
    layer2_image: PointerProperty(name="Preview Texture", type=bpy.types.Image, update=_refresh_preview)
    layer3_image: PointerProperty(name="Preview Texture", type=bpy.types.Image, update=_refresh_preview)
    layer4_image: PointerProperty(name="Preview Texture", type=bpy.types.Image, update=_refresh_preview)
    layer1_tile: FloatProperty(name="Tile Size", default=4.0, min=0.01, subtype='DISTANCE', update=_refresh_preview,
                               description="How many meters one repeat of the preview texture covers")
    layer2_tile: FloatProperty(name="Tile Size", default=4.0, min=0.01, subtype='DISTANCE', update=_refresh_preview)
    layer3_tile: FloatProperty(name="Tile Size", default=4.0, min=0.01, subtype='DISTANCE', update=_refresh_preview)
    layer4_tile: FloatProperty(name="Tile Size", default=4.0, min=0.01, subtype='DISTANCE', update=_refresh_preview)
    stat_tris: IntProperty()
    stat_verts: IntProperty()
    stat_instances: IntProperty()
    stat_instance_defs: IntProperty()
    stat_materials: IntProperty()
    stat_portals: IntProperty()


CLASSES = (BananaPreferences, BananaProblem, BananaScene, BananaCollection)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.banana = PointerProperty(type=BananaScene)
    bpy.types.Collection.banana = PointerProperty(type=BananaCollection)


def unregister():
    del bpy.types.Collection.banana
    del bpy.types.Scene.banana
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
