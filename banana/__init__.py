bl_info = {
    "name": "Banana",
    "author": "itshyokin",
    "version": (0, 2, 0),
    "blender": (4, 1, 0),
    "location": "View3D > Sidebar > Banana",
    "description": "Halo 3 map building toolkit (BSPs, validation, .ASS export) and Rig Convert",
    "category": "Import-Export",
}

import bpy

from . import props, bsp, export, validate, ui, rig

_MODULES_WITH_CLASSES = (bsp, export, validate, ui, rig)


def register():
    props.register()
    for module in _MODULES_WITH_CLASSES:
        for cls in module.CLASSES:
            bpy.utils.register_class(cls)
    rig.register()
    ui.register()


def unregister():
    ui.unregister()
    rig.unregister()
    for module in reversed(_MODULES_WITH_CLASSES):
        for cls in reversed(module.CLASSES):
            bpy.utils.unregister_class(cls)
    props.unregister()
