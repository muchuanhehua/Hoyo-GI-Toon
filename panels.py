"""One import, two appearance sliders, folded lighting/output and one render."""
import traceback
import bpy
from bpy.props import StringProperty
from bpy.types import Menu, Operator, Panel
from bpy_extras.io_utils import ImportHelper
from . import rendering, workflow


def target(context):
    root = context.scene.hgt_target
    return root if root and root.hgt_character.managed else None


def report_error(operator, error):
    traceback.print_exc()
    operator.report({"ERROR"}, str(error))
    return {"CANCELLED"}


class HGT_OT_import_character(Operator, ImportHelper):
    bl_idname = "hgt.import_character"
    bl_label = "导入模型"
    bl_description = "选择 FBX 或 PMX，并读取配套材质和贴图"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".fbx"
    filter_glob: StringProperty(default="*.fbx;*.pmx", options={"HIDDEN"})

    def execute(self, context):
        try:
            if context.scene.hgt_output.rendering:
                raise ValueError("请等待渲染结束后再导入模型")
            root = workflow.build(self.filepath, context)
            rendering.preview(context, root)
        except (ValueError, RuntimeError, OSError) as exc:
            return report_error(self, exc)
        return {"FINISHED"}


class HGT_OT_restore(Operator):
    bl_idname = "hgt.restore_materials"
    bl_label = "恢复导入状态"
    bl_description = "恢复导入时的网格、材质和显示状态"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(target(context) and not context.scene.hgt_output.rendering)

    def execute(self, context):
        try:
            workflow.restore(target(context))
        except (ValueError, RuntimeError, OSError) as exc:
            return report_error(self, exc)
        return {"FINISHED"}


class HGT_OT_frame(Operator):
    bl_idname = "hgt.frame_camera"
    bl_label = "重新构图"
    bl_description = "按当前尺寸调整角色相机，保留模型变换"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(target(context) and not context.scene.hgt_output.rendering)

    def execute(self, context):
        try:
            rendering.frame_camera(context.scene, target(context))
        except (ValueError, RuntimeError) as exc:
            return report_error(self, exc)
        return {"FINISHED"}


class HGT_OT_render(Operator):
    bl_idname = "hgt.render"
    bl_label = "渲染"
    bl_description = "渲染当前帧并保存 PNG"

    @classmethod
    def poll(cls, context):
        return bool(target(context) and not context.scene.hgt_output.rendering)

    def execute(self, context):
        try:
            result = rendering.start(context.scene, target(context), invoke=not bpy.app.background)
            if bpy.app.background:
                return {"FINISHED"}
            self._job = result
            self._timer = context.window_manager.event_timer_add(.2, window=context.window)
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}
        except (ValueError, RuntimeError, OSError) as exc:
            return report_error(self, exc)

    def modal(self, context, event):
        if event.type != "TIMER" or bpy.app.is_job_running("RENDER"):
            return {"PASS_THROUGH"}
        if rendering.job_state(self._job) == "running":
            return {"PASS_THROUGH"}
        context.window_manager.event_timer_remove(self._timer)
        try:
            path = rendering.finish(self._job)
        except (ValueError, RuntimeError, OSError) as exc:
            return report_error(self, exc)
        self.report({"INFO"}, "已保存：" + path)
        return {"FINISHED"}


class HGT_OT_material_info(Operator):
    bl_idname = "hgt.material_info"
    bl_label = "查看材质"
    bl_description = "查看原材质与渲染材质的对应关系"

    @classmethod
    def poll(cls, context):
        return bool(target(context))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        for binding in target(context).hgt_character.bindings:
            row = self.layout.row()
            row.label(text=binding.source_name.rsplit("_Mat_", 1)[-1])
            row.label(text=binding.generated.name if binding.generated else "材质引用缺失")

    def execute(self, context):
        return {"FINISHED"}


class HGT_MT_tools(Menu):
    bl_idname = "HGT_MT_tools"
    bl_label = "角色操作"

    def draw(self, context):
        self.layout.operator("hgt.material_info", icon="MATERIAL")
        self.layout.operator("hgt.restore_materials", icon="LOOP_BACK")


class HGT_PT_main(Panel):
    bl_label = "Hoyo-GI-Toon"
    bl_idname = "HGT_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Hoyo-GI-Toon"

    def draw(self, context):
        layout = self.layout
        layout.enabled = not context.scene.hgt_output.rendering
        row = layout.row(align=True)
        row.operator("hgt.import_character", icon="IMPORT")
        root = target(context)
        if root:
            row.menu("HGT_MT_tools", text="", icon="DOWNARROW_HLT")
        if not root:
            return
        roots = [o for o in context.scene.objects if o.hgt_character.managed]
        if len(roots) > 1:
            layout.prop(context.scene, "hgt_target", text="角色")
        column = layout.column(align=True)
        for name in ("shadow_position", "outline"):
            column.prop(root.hgt_character, name, slider=True)
        layout.separator(factor=.5)
        layout.operator("hgt.render", icon="RENDER_STILL")


class HGT_PT_lighting(Panel):
    bl_label = "光照"
    bl_idname = "HGT_PT_lighting"
    bl_parent_id = "HGT_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return bool(target(context))

    def draw(self, context):
        column = self.layout.column(align=True)
        column.enabled = not context.scene.hgt_output.rendering
        for name in ("light_azimuth", "light_elevation"):
            column.prop(target(context).hgt_character, name)


class HGT_PT_output(Panel):
    bl_label = "输出"
    bl_idname = "HGT_PT_output"
    bl_parent_id = "HGT_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return bool(target(context))

    def draw(self, context):
        layout = self.layout
        layout.enabled = not context.scene.hgt_output.rendering
        settings = context.scene.hgt_output
        layout.prop(settings, "camera")
        if settings.camera == target(context).hgt_character.camera:
            layout.operator("hgt.frame_camera", icon="VIEW_CAMERA")
        row = layout.row(align=True)
        row.prop(settings, "width")
        row.prop(settings, "height")
        layout.prop(settings, "filepath")
        layout.prop(settings, "transparent")
        layout.prop(settings, "post_processing")


CLASSES = (HGT_OT_import_character, HGT_OT_restore, HGT_OT_frame, HGT_OT_render, HGT_OT_material_info,
           HGT_MT_tools, HGT_PT_main, HGT_PT_lighting, HGT_PT_output)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
