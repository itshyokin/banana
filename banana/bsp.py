"""BSP collections: creating the template and finding what belongs to each role."""

import bpy

SUB_ROLES = (
    ('STRUCTURE', "structure"),
    ('INSTANCES', "instances"),
    ('DESIGN', "design"),
    ('PORTALS', "portals"),
)


def all_collections(root):
    yield root
    for child in root.children:
        yield from all_collections(child)


def find_bsps(scene):
    return [c for c in all_collections(scene.collection) if c.banana.role == 'BSP']


def sub_collections(bsp, role):
    return [c for c in all_collections(bsp) if c is not bsp and c.banana.role == role]


def objects_for_role(bsp, role):
    """Objects in every collection of this role, including nested sub-collections
    (painted props live in sub-collections under their master's collection).
    Objects sitting directly in the BSP collection count as structure."""
    def walk(coll):
        yield coll
        for child in coll.children:
            # nested collections with no role inherit; a different role is skipped
            if child.banana.role == 'NONE':
                yield from walk(child)

    seen = set()
    result = []
    colls = []
    for root in sub_collections(bsp, role):
        colls.extend(walk(root))
    if role == 'STRUCTURE':
        colls.insert(0, bsp)  # loose objects in the BSP itself
    for coll in colls:
        for obj in coll.objects:
            if obj.name not in seen and obj.type == 'MESH':
                seen.add(obj.name)
                result.append(obj)
    return result


def bsp_of(obj, scene):
    for bsp in find_bsps(scene):
        for coll in all_collections(bsp):
            if obj.name in coll.objects:
                return bsp
    return None


def create_bsp(scene, name, parent=None):
    parent = parent or scene.collection
    bsp = bpy.data.collections.new(name)
    bsp.banana.role = 'BSP'
    parent.children.link(bsp)
    for role, suffix in SUB_ROLES:
        sub = bpy.data.collections.new("%s_%s" % (bsp.name, suffix))
        sub.banana.role = role
        bsp.children.link(sub)
    return bsp


class BANANA_OT_create_bsp(bpy.types.Operator):
    """Create a new BSP collection with Structure, Instances, Design and Portals inside"""
    bl_idname = "banana.create_bsp"
    bl_label = "New BSP"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty(name="BSP Name", default="bsp_a")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        bsp = create_bsp(context.scene, self.name.strip() or "bsp")
        context.scene.banana.active_bsp = bsp
        self.report({'INFO'}, "Created BSP '%s'" % bsp.name)
        return {'FINISHED'}


class BANANA_OT_set_role(bpy.types.Operator):
    """Mark the active collection with a Banana role"""
    bl_idname = "banana.set_role"
    bl_label = "Set Collection Role"
    bl_options = {'REGISTER', 'UNDO'}

    role: bpy.props.EnumProperty(items=[
        ('BSP', "BSP", ""), ('STRUCTURE', "Structure", ""), ('INSTANCES', "Instances", ""),
        ('DESIGN', "Design", ""), ('PORTALS', "Portals", ""), ('NONE', "None", ""),
    ])

    def execute(self, context):
        coll = context.view_layer.active_layer_collection.collection
        if coll is context.scene.collection:
            self.report({'ERROR'}, "Pick a collection in the Outliner first")
            return {'CANCELLED'}
        coll.banana.role = self.role
        return {'FINISHED'}


CLASSES = (BANANA_OT_create_bsp, BANANA_OT_set_role)
