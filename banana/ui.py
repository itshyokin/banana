"""Sidebar panels: View3D > N panel > Banana."""

import bpy

from . import bsp as bsp_mod
from .export import level_dir
from .props import prefs

ICONS = {'ERROR': 'ERROR', 'WARNING': 'INFO', 'INFO': 'CHECKMARK'}


class BananaPanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Banana"


class BANANA_PT_project(BananaPanel, bpy.types.Panel):
    bl_label = "Project"

    def draw(self, context):
        s = context.scene.banana
        layout = self.layout
        p = prefs(context)
        if p is not None and not p.h3ek_path:
            box = layout.box()
            box.label(text="Set your H3EK folder:", icon='ERROR')
            box.prop(p, "h3ek_path", text="")
        layout.prop(s, "level_name")
        layout.prop(s, "level_type")
        row = layout.row()
        row.prop(s, "scale_mode", expand=True)
        if s.scale_mode == 'CUSTOM':
            layout.prop(s, "custom_scale")
        layout.prop(s, "design_mode")
        layout.prop(s, "export_root")
        target = level_dir(context)
        if target:
            layout.label(text=target, icon='FILE_FOLDER')


class BANANA_PT_bsps(BananaPanel, bpy.types.Panel):
    bl_label = "BSPs"

    def draw(self, context):
        s = context.scene.banana
        layout = self.layout
        row = layout.row(align=True)
        row.prop(s, "active_bsp", text="")
        row.operator("banana.create_bsp", text="", icon='ADD')

        bsp = s.active_bsp
        if bsp is None:
            layout.label(text="Create a BSP or pick one above")
            return
        b = bsp.banana
        col = layout.column(align=True)
        col.prop(b, "export_enabled")
        col.prop(b, "sky_index")

        box = layout.box()
        row = box.row()
        row.label(text="Stats", icon='INFO')
        row.operator("banana.refresh_stats", text="", icon='FILE_REFRESH')
        grid = box.grid_flow(columns=2, even_columns=True)
        grid.label(text="Triangles: %d" % b.stat_tris)
        grid.label(text="Vertices: %d" % b.stat_verts)
        grid.label(text="Instances: %d" % b.stat_instances)
        grid.label(text="Instance defs: %d" % b.stat_instance_defs)
        grid.label(text="Materials: %d" % b.stat_materials)
        grid.label(text="Portals: %d" % b.stat_portals)

        box = layout.box()
        box.label(text="Sky & Seams", icon='WORLD')
        row = box.row(align=True)
        row.prop(s, "sky_height_auto", text="Auto Height")
        sub = row.row(align=True)
        sub.enabled = not s.sky_height_auto
        sub.prop(s, "sky_height", text="")
        row = box.row(align=True)
        row.operator("banana.build_sky_shell", text="Build Sky Shells", icon='MESH_CUBE').all_bsps = True
        row.operator("banana.build_sky_shell", text="This BSP").all_bsps = False
        box.operator("banana.mirror_seam", icon='MOD_MIRROR')

        col = layout.column(align=True)
        col.label(text="Collections in this BSP:")
        for sub in bsp_mod.all_collections(bsp):
            if sub is not bsp and sub.banana.role != 'NONE':
                col.label(text="%s  (%s)" % (sub.name, sub.banana.role.title()), icon='OUTLINER_COLLECTION')


class BANANA_PT_export(BananaPanel, bpy.types.Panel):
    bl_label = "Validate & Export"

    def draw(self, context):
        s = context.scene.banana
        layout = self.layout
        row = layout.row(align=True)
        row.operator("banana.validate", text="Validate BSP", icon='CHECKMARK').all_bsps = False
        row.operator("banana.validate", text="All", icon='CHECKMARK').all_bsps = True
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("banana.export", text="Export BSP", icon='EXPORT').all_bsps = False
        row.operator("banana.export", text="Export All", icon='EXPORT').all_bsps = True
        layout.prop(s, "run_tool_after_export")

        if s.problems:
            box = layout.box()
            row = box.row()
            row.label(text="Problems")
            row.operator("banana.clear_problems", text="", icon='X')
            for item in s.problems[:40]:
                row = box.row(align=True)
                row.label(text=item.message, icon=ICONS.get(item.severity, 'DOT'))
                if item.object_name:
                    op = row.operator("banana.select_problem_object", text=item.object_name, icon='RESTRICT_SELECT_OFF')
                    op.object_name = item.object_name
            if len(s.problems) > 40:
                box.label(text="... and %d more" % (len(s.problems) - 40))


class BANANA_MT_collection_role(bpy.types.Menu):
    bl_label = "Banana Role"
    bl_idname = "BANANA_MT_collection_role"

    def draw(self, context):
        for role in ('BSP', 'STRUCTURE', 'INSTANCES', 'DESIGN', 'PORTALS', 'NONE'):
            self.layout.operator("banana.set_role", text=role.title()).role = role


def outliner_menu(self, context):
    self.layout.separator()
    self.layout.menu(BANANA_MT_collection_role.bl_idname)


CLASSES = (BANANA_PT_project, BANANA_PT_bsps, BANANA_PT_export, BANANA_MT_collection_role)


def register():
    bpy.types.OUTLINER_MT_collection.append(outliner_menu)


def unregister():
    bpy.types.OUTLINER_MT_collection.remove(outliner_menu)
