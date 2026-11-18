bl_info = {
    "name": "Banana",
    "author": "itshyokin",
    "version": (0, 9, 0),
    "blender": (4, 1, 0),
    "location": "View3D > Sidebar > Banana",
    "description": "Halo 3 map building toolkit (BSPs, validation, .ASS export) and Rig Convert",
    "category": "Import-Export",
}

import importlib
import sys

import bpy

# Installing a new zip over a running Blender keeps old submodules in memory;
# reload them so the new version is used everywhere without a restart.
_SUBMODULES = ("naming", "ass_writer", "props", "bsp", "export", "sky", "validate", "limits", "terrain", "blendmap", "brush", "proplib", "rig", "ui")
for _name in _SUBMODULES:
    _full = "%s.%s" % (__name__, _name)
    if _full in sys.modules:
        importlib.reload(sys.modules[_full])

from . import props, bsp, export, validate, ui, rig, sky, limits, terrain, blendmap, brush, proplib  # noqa: E402

_MODULES_WITH_CLASSES = (bsp, export, validate, ui, terrain, blendmap, brush, proplib, rig, sky, limits)


def register():
    props.register()
    for module in _MODULES_WITH_CLASSES:
        for cls in module.CLASSES:
            bpy.utils.register_class(cls)
    rig.register()
    limits.register()
    blendmap.register()
    proplib.register()
    ui.register()


def unregister():
    ui.unregister()
    proplib.unregister()
    blendmap.unregister()
    limits.unregister()
    rig.unregister()
    for module in reversed(_MODULES_WITH_CLASSES):
        for cls in reversed(module.CLASSES):
            bpy.utils.unregister_class(cls)
    props.unregister()
