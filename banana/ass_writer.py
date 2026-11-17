"""Plain-Python model and writer for Halo 3 .ASS files (version 7).

Nothing in here touches bpy, so it can be unit tested on its own.
The layout mirrors what Tool accepts from known-working exporters:
  HEADER -> MATERIALS -> OBJECTS -> INSTANCES
Instance 0 is always the "Scene Root"; every other instance parents to it.
"""

from dataclasses import dataclass, field

ASS_VERSION = 7


@dataclass
class Vertex:
    position: tuple   # (x, y, z) in ASS units, object space
    normal: tuple     # (x, y, z) unit vector, object space
    color: tuple = (0.0, 0.0, 0.0)
    uvs: tuple = ()   # ((u, v), ...) one entry per UV layer


@dataclass
class MeshObject:
    vertices: list = field(default_factory=list)
    triangles: list = field(default_factory=list)  # (material_index, a, b, c)


@dataclass
class Instance:
    name: str
    object_index: int
    unique_id: int
    rotation: tuple = (0.0, 0.0, 0.0, 1.0)   # quaternion x, y, z, w
    translation: tuple = (0.0, 0.0, 0.0)
    scale: float = 1.0
    parent_id: int = 0                         # index into instances; 0 = Scene Root


@dataclass
class AssScene:
    materials: list = field(default_factory=list)   # material name strings
    objects: list = field(default_factory=list)     # MeshObject
    instances: list = field(default_factory=list)   # Instance (Scene Root added on write)

    def material_index(self, name):
        try:
            return self.materials.index(name)
        except ValueError:
            self.materials.append(name)
            return len(self.materials) - 1


def _f(value):
    value = float(value)
    if value == 0.0:
        value = 0.0  # avoid writing "-0.0000000000"
    return "%0.10f" % value


def _vec(values):
    return "\t".join(_f(v) for v in values)


def _quote(text):
    return '"%s"' % str(text).replace('"', "'")


def build_text(scene, app_version="4.1", user="banana", device="BANANA"):
    out = []
    w = out.append

    w(";### HEADER ###\n%d\n\"BLENDER\"\n%s\n%s\n%s\n" % (
        ASS_VERSION, _quote(app_version), _quote(user), _quote(device)))

    w("\n;### MATERIALS ###\n%d\n" % len(scene.materials))
    for idx, name in enumerate(scene.materials):
        w("\n;MATERIAL %d\n%s\n\"\"\n0\n" % (idx, _quote(name)))

    w("\n;### OBJECTS ###\n%d\n" % len(scene.objects))
    for idx, obj in enumerate(scene.objects):
        w("\n;OBJECT %d\n\"MESH\"\n\"\"\n\"\"\n%d" % (idx, len(obj.vertices)))
        for v in obj.vertices:
            w("\n%s\n%s\n%s\n0\n%d" % (_vec(v.position), _vec(v.normal), _vec(v.color[:3]), len(v.uvs)))
            for u, vv in v.uvs:
                w("\n%s\n" % _vec((u, vv, 0.0)))
        w("\n%d" % len(obj.triangles))
        for mat, a, b, c in obj.triangles:
            w("\n%d\t\t%d\t%d\t%d" % (mat, a, b, c))
        w("\n")

    instances = [Instance("Scene Root", -1, -1, parent_id=-1)] + list(scene.instances)
    w("\n;### INSTANCES ###\n%d\n" % len(instances))
    for idx, inst in enumerate(instances):
        w("\n;INSTANCE %d\n%d\n%s\n%d\n%d\n0\n%s\n%s\n%s\n%s\n%s\n%s\n" % (
            idx, inst.object_index, _quote(inst.name), inst.unique_id, inst.parent_id,
            _vec(inst.rotation), _vec(inst.translation), _f(inst.scale),
            _vec((0.0, 0.0, 0.0, 1.0)), _vec((0.0, 0.0, 0.0)), _f(1.0)))

    return "".join(out)


def write_file(scene, filepath, **header):
    text = build_text(scene, **header)
    with open(filepath, "w", encoding="utf-8", newline="\r\n") as handle:
        handle.write(text)
    return len(text)
