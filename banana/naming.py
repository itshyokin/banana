"""Name helpers shared across the add-on."""

import re

_BLENDER_SUFFIX = re.compile(r"\.(\d{3,})$")
SPECIAL_PREFIX = "+"
MAX_MATERIAL_NAME = 32


def strip_suffix(name):
    """'metal.001' -> 'metal'."""
    return _BLENDER_SUFFIX.sub("", name)


def has_blender_suffix(name):
    return bool(_BLENDER_SUFFIX.search(name))


def instance_name(name):
    """Make a Blender object name safe for an ASS instance.

    Instances must start with '%'. Blender's '.001' duplicate suffix becomes
    '_001' so each placement keeps a unique, Tool-friendly name.
    """
    match = _BLENDER_SUFFIX.search(name)
    if match:
        name = name[:match.start()] + "_" + match.group(1)
    if not name.startswith("%"):
        name = "%" + name
    return name


def is_special_material(name):
    return name.startswith(SPECIAL_PREFIX)


def sky_material(name, sky_index):
    """Plain '+sky' takes the BSP's sky index; explicit '+skyN' is left alone."""
    if name == "+sky":
        return "+sky%d" % sky_index
    return name


def structure_name(name, used):
    """Unique, Tool-friendly name for a baked (non-instance) object:
    'Cube_A.001' -> 'Cube_A_001'; leading '%' removed; repeats get a counter."""
    match = _BLENDER_SUFFIX.search(name)
    if match:
        name = name[:match.start()] + "_" + match.group(1)
    name = name.lstrip("%").replace(".", "_") or "object"
    base, n = name, 1
    while name in used:
        n += 1
        name = "%s_%d" % (base, n)
    used.add(name)
    return name
