"""Settings stored on the add-on, the scene, BSP collections and objects."""

import bpy
from bpy.props import (
    BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
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
            ('SEPARATE', "Separate File", "Design pieces go to structure-design\\<bsp>.ass"),
            ('COMBINED', "Same File", "Design pieces go into the BSP's structure .ass"),
        ),
        default='SEPARATE',
    )
    run_tool_after_export: BoolProperty(name="Run Tool After Export", default=False)
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


class BananaCollection(bpy.types.PropertyGroup):
    role: EnumProperty(name="Role", items=ROLE_ITEMS, default='NONE')
    export_enabled: BoolProperty(name="Export", default=True)
    sky_index: IntProperty(
        name="Sky Index", default=0, min=0, max=31,
        description="Faces using the plain '+sky' material export as +sky<index>",
    )
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
