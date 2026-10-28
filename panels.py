"""A compact sidebar: one import entry and the controls used while rendering."""
import traceback
import bpy
from bpy.props import StringProperty
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ImportHelper
from . import workflow


class HGT_OT_import_character(Operator, ImportHelper):
    bl_idname = "hgt.import_character"
    bl_label = "导入角色"
    bl_description = "选择角色模型并配置配套贴图与材质"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".fbx"
    filter_glob: StringProperty(default="*.fbx", options={"HIDDEN"})

    def execute(self, context):
        try:
            workflow.build(self.filepath, context)
        except (ValueError, RuntimeError, OSError) as exc:
            traceback.print_exc()
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class HGT_OT_restore(Operator):
    bl_idname = "hgt.restore_materials"
    bl_label = "恢复原材质"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.hgt_target and context.scene.hgt_target.hgt_character.managed)

    def execute(self, context):
        workflow.restore(context.scene.hgt_target)
        return {"FINISHED"}


class HGT_OT_render(Operator):
    bl_idname = "hgt.render"
    bl_label = "渲染当前帧"

    @classmethod
    def poll(cls, context):
        return bool(context.scene.camera and context.scene.hgt_target)

    def execute(self, context):
        return bpy.ops.render.render("INVOKE_DEFAULT")


class HGT_PT_main(Panel):
    bl_label = "Hoyo-GI-Toon"
    bl_idname = "HGT_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Hoyo-GI-Toon"

    def draw(self, context):
        layout = self.layout
        layout.operator("hgt.import_character", icon="IMPORT")
        roots = [o for o in context.scene.objects if o.hgt_character.managed]
        if not roots:
            return
        if len(roots) > 1:
            layout.prop(context.scene, "hgt_target", text="角色")
        root = context.scene.hgt_target
        if not root or not root.hgt_character.managed:
            return
        settings = root.hgt_character
        column = layout.column(align=True)
        for name in ("threshold", "softness", "rim", "outline"):
            column.prop(settings, name, slider=True)
        layout.separator(factor=0.5)
        layout.operator("hgt.render", icon="RENDER_STILL")


class HGT_PT_lighting(Panel):
    bl_label = "灯光"
    bl_idname = "HGT_PT_lighting"
    bl_parent_id = "HGT_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.hgt_target and context.scene.hgt_target.hgt_character.managed)

    def draw(self, context):
        column = self.layout.column(align=True)
        settings = context.scene.hgt_target.hgt_character
        for name in ("light_azimuth", "light_elevation", "light_energy", "shadow_color"):
            column.prop(settings, name)


class HGT_PT_materials(HGT_PT_lighting):
    bl_label = "材质"
    bl_idname = "HGT_PT_materials"

    def draw(self, context):
        layout = self.layout
        for binding in context.scene.hgt_target.hgt_character.bindings:
            row = layout.row(align=True)
            row.label(text=binding.source_name.rsplit("_Mat_", 1)[-1])
            value = row.row()
            value.enabled = False
            value.prop(binding, "generated", text="")
        layout.operator("hgt.restore_materials", icon="LOOP_BACK")


class HGT_PT_output(HGT_PT_lighting):
    bl_label = "输出"
    bl_idname = "HGT_PT_output"

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "camera", text="相机")
        column = layout.column(align=True)
        column.prop(context.scene.render, "resolution_x", text="宽")
        column.prop(context.scene.render, "resolution_y", text="高")
        column.prop(context.scene.render, "film_transparent", text="透明背景")
        column.prop(context.scene.render, "filepath", text="路径")


CLASSES = (HGT_OT_import_character, HGT_OT_restore, HGT_OT_render, HGT_PT_main,
           HGT_PT_lighting, HGT_PT_materials, HGT_PT_output)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
