"""Import, frame and render; detailed controls stay folded."""
import traceback
from pathlib import Path
import bpy
from bpy.props import CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Menu, Operator, Panel, UIList
from bpy_extras.io_utils import ImportHelper
from . import rendering, workflow, subjects, framing, presentation, expressions, project_io
from .properties import HGTPartEdit, PART_ROLES


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
        except rendering.RenderCancelled:
            self.report({'INFO'}, '渲染已取消')
            return {'CANCELLED'}
        except (ValueError, RuntimeError, OSError) as exc:
            return report_error(self, exc)
        self.report({"INFO"}, "已保存：" + path)
        return {"FINISHED"}


class HGT_OT_view_render(Operator):
    bl_idname = 'hgt.view_render'
    bl_label = '查看渲染'
    bl_description = '打开已保存的 PNG'

    @classmethod
    def poll(cls, context):
        path = context.scene.hgt_output.last_render
        return bool(path and Path(path).is_file() and not context.scene.hgt_output.rendering)

    def execute(self, context):
        try:
            result = bpy.ops.wm.path_open(filepath=context.scene.hgt_output.last_render)
            if result != {'FINISHED'}:
                raise RuntimeError('无法打开图片，请从输出位置查看 PNG')
        except (ValueError, RuntimeError, OSError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}


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
        if not target(context):
            return
        self.layout.operator("hgt.material_info", icon="MATERIAL")
        self.layout.operator('hgt.relink_resources', icon='FILE_REFRESH')
        if target(context).hgt_character.parts_version:
            self.layout.operator('hgt.manage_parts', icon='OUTLINER_COLLECTION')
        self.layout.operator("hgt.restore_materials", icon="LOOP_BACK")


class HGT_OT_set_shot(Operator):
    bl_idname = 'hgt.set_shot'
    bl_label = '调整构图'
    bl_options = {'REGISTER', 'UNDO'}
    shot: EnumProperty(items=[('FULL', '全身', ''), ('HALF', '半身', ''), ('HEAD', '头像', '')])

    @classmethod
    def poll(cls, context):
        return bool(target(context) and not context.scene.hgt_output.rendering)

    def execute(self, context):
        try:
            root = target(context)
            context.scene.hgt_output.camera = root.hgt_character.camera
            root.hgt_character.shot = self.shot
            rendering.frame_camera(context.scene, root)
            rendering.preview(context, root)
        except (ValueError, RuntimeError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}


class HGT_OT_view_angle(Operator):
    bl_idname = 'hgt.view_angle'
    bl_label = '选择视角'
    bl_options = {'REGISTER', 'UNDO'}
    angle: EnumProperty(items=[('FRONT', '正面', ''), ('TURN', '斜侧', ''), ('SIDE', '侧面', ''), ('BACK', '背面', '')])

    @classmethod
    def poll(cls, context):
        return HGT_OT_set_shot.poll(context)

    def execute(self, context):
        root = target(context)
        context.scene.hgt_output.camera = root.hgt_character.camera
        root.hgt_character.view_azimuth = {'FRONT': 0, 'TURN': .6, 'SIDE': 1.570796, 'BACK': 3.14159}[self.angle]
        rendering.frame_camera(context.scene, root)
        return {'FINISHED'}


class HGT_OT_light_preset(Operator):
    bl_idname = 'hgt.light_preset'
    bl_label = '选择光照'
    bl_options = {'REGISTER', 'UNDO'}
    preset: EnumProperty(items=[(key, value[0], '') for key, value in presentation.LIGHTS.items()])

    @classmethod
    def poll(cls, context):
        return HGT_OT_set_shot.poll(context)

    def execute(self, context):
        settings = target(context).hgt_character
        _, settings.light_azimuth, settings.light_elevation = presentation.LIGHTS[self.preset]
        return {'FINISHED'}


class HGT_OT_output_size(Operator):
    bl_idname = 'hgt.output_size'
    bl_label = '选择图片尺寸'
    bl_options = {'REGISTER', 'UNDO'}
    preset: EnumProperty(items=[(key, value[0], '') for key, value in presentation.SIZES.items()])

    @classmethod
    def poll(cls, context):
        return HGT_OT_set_shot.poll(context)

    def execute(self, context):
        settings = context.scene.hgt_output
        _, settings.width, settings.height = presentation.SIZES[self.preset]
        root = target(context)
        if settings.camera == root.hgt_character.camera and framing.is_auto(root):
            rendering.frame_camera(context.scene, root)
        return {'FINISHED'}


class HGT_OT_reset_display(Operator):
    bl_idname = 'hgt.reset_display'
    bl_label = '恢复初始展示'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return HGT_OT_set_shot.poll(context)

    def execute(self, context):
        root = target(context);settings = root.hgt_character
        settings.building = True
        try:
            settings.light_azimuth = settings.light_elevation = .35
            settings.show_floor = False;settings.view_azimuth = settings.view_elevation = 0
            settings.frame_margin = .15;settings.shot = 'FULL'
            context.scene.hgt_output.transparent = True
            context.scene.hgt_output.background_color = (.04, .055, .08)
        finally:
            settings.building = False
        context.scene.hgt_output.camera = settings.camera
        workflow.refresh_character(root);rendering.frame_camera(context.scene, root)
        return {'FINISHED'}


class HGT_OT_look_camera(Operator):
    bl_idname = 'hgt.look_camera'
    bl_label = '看向相机'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(HGT_OT_set_shot.poll(context) and expressions.eye_bones(target(context)))

    def execute(self, context):
        try:
            root = target(context)
            expressions.set_gaze(root, context.scene, not root.hgt_character.look_camera)
            context.view_layer.update()
        except (ValueError, RuntimeError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}


class HGT_OT_reset_expressions(Operator):
    bl_idname = 'hgt.reset_expressions'
    bl_label = '重置表情'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return HGT_OT_set_shot.poll(context)

    def execute(self, context):
        expressions.reset(target(context))
        return {'FINISHED'}


class HGT_OT_relink(Operator, ImportHelper):
    bl_idname = 'hgt.relink_resources'
    bl_label = '重新定位资源'
    bl_description = '选择移动后的原模型，校验并更新资源路径'
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = '.fbx'
    filter_glob: StringProperty(default='*.fbx;*.pmx', options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return HGT_OT_set_shot.poll(context)

    def execute(self, context):
        try:
            project_io.relink(target(context), self.filepath)
        except (ValueError, RuntimeError, OSError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}


class HGT_OT_extensions(Operator):
    bl_idname = 'hgt.open_extensions'
    bl_label = '管理扩展'

    def execute(self, context):
        bpy.ops.screen.userpref_show()
        context.preferences.active_section = 'EXTENSIONS'
        return {'FINISHED'}


class HGT_OT_help(Operator):
    bl_idname = 'hgt.help'
    bl_label = '使用说明'

    def execute(self, context):
        bpy.ops.wm.url_open(url='https://github.com/muchuanhehua/Hoyo-GI-Toon#使用流程')
        return {'FINISHED'}


class HGT_UL_expressions(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.label)
        row.prop(item, 'value', text='', slider=True)

    def filter_items(self, context, data, propname):
        text = self.filter_name.casefold()
        return [self.bitflag_filter_item if not text or text in item.label.casefold() or text in item.name.casefold()
                else 0 for item in getattr(data, propname)], []


class HGT_OT_toggle_part(Operator):
    bl_idname='hgt.toggle_part'
    bl_label='切换部件显示'
    bl_description='切换这个部件的预览与渲染'
    bl_options={'REGISTER','UNDO'}
    key: IntProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls,context):
        return bool(target(context) and not context.scene.hgt_output.rendering)

    def execute(self,context):
        previous=None
        try:
            root=target(context)
            part=next((p for p in root.hgt_character.parts if p.key==self.key),None)
            if part is None:raise ValueError('部件不存在，请重新选择角色')
            previous=part.included
            subjects.set_part(root,self.key,not part.included)
            if context.scene.hgt_output.camera==root.hgt_character.camera and framing.is_auto(root):
                rendering.frame_camera(context.scene,root)
        except (ValueError,RuntimeError) as exc:
            if previous is not None and part.included!=previous:
                subjects.set_part(root,self.key,previous)
            return report_error(self,exc)
        return {'FINISHED'}


class HGT_OT_manage_parts(Operator):
    bl_idname='hgt.manage_parts'
    bl_label='调整部件分组'
    bl_description='调整出图分组和显示，保留现有材质'
    bl_options={'REGISTER','UNDO'}
    parts: CollectionProperty(type=HGTPartEdit)

    @classmethod
    def poll(cls,context):
        return bool(target(context) and target(context).hgt_character.parts_version
                    and not context.scene.hgt_output.rendering)

    def invoke(self,context,event):
        self.parts.clear()
        for part in target(context).hgt_character.parts:
            if part.locked:continue
            edit=self.parts.add();edit.key=part.key;edit.label=part.name
            edit.role,edit.included=part.role,part.included
        return context.window_manager.invoke_props_dialog(self,width=550)

    def draw(self,context):
        for part in self.parts:
            row=self.layout.row(align=True)
            row.label(text=part.label)
            row.prop(part,'role',text='')
            row.prop(part,'included',text='')

    def execute(self,context):
        root=target(context);settings=root.hgt_character
        before={p.key:(p.role,p.included) for p in settings.parts}
        applied=False
        try:
            subjects.validate(root)
            mapping={p.key:p for p in settings.parts if not p.locked}
            if set(mapping)!={p.key for p in self.parts}:
                raise ValueError('部件列表已改变，请重新打开分组窗口')
            for edit in self.parts:
                part=mapping[edit.key];part.role,part.included=edit.role,edit.included
            if not any(p.included and not p.locked and p.face_count for p in settings.parts):
                raise ValueError('请至少选择一个可出图的部件')
            applied=True
            subjects.apply(root,force=True)
            if context.scene.hgt_output.camera==settings.camera and framing.is_auto(root):
                rendering.frame_camera(context.scene,root)
        except (ValueError,RuntimeError) as exc:
            for part in settings.parts:
                if part.key in before:part.role,part.included=before[part.key]
            if applied:subjects.apply(root,force=True)
            return report_error(self,exc)
        return {'FINISHED'}


class HGT_PT_parts(Panel):
    bl_label='附件'
    bl_idname='HGT_PT_parts'
    bl_parent_id='HGT_PT_main'
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_options={'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls,context):
        root=target(context)
        return bool(root and any(not p.locked and p.role!='BODY' for p in root.hgt_character.parts))

    def draw(self,context):
        layout=self.layout;layout.enabled=not context.scene.hgt_output.rendering
        parts=[p for p in target(context).hgt_character.parts if not p.locked and p.role!='BODY']
        labels={role:label for role,label,_ in PART_ROLES}
        for part in parts:
            if part.object is None:
                row=layout.row();row.alert=True;row.label(text=part.name+'：对象已移除')
                continue
            label=part.name if part.role=='OTHER' else labels[part.role]
            if sum(p.role==part.role for p in parts)>1:label+=' · '+part.object.name
            op=layout.operator('hgt.toggle_part',text=label,icon='CHECKBOX_HLT' if part.included else 'CHECKBOX_DEHLT')
            op.key=part.key
        layout.operator('hgt.manage_parts',text='调整分组',icon='OUTLINER_COLLECTION')


class HGT_PT_main(Panel):
    bl_label = "Hoyo-GI-Toon"
    bl_idname = "HGT_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Hoyo-GI-Toon"

    def draw(self, context):
        layout = self.layout
        if context.scene.hgt_output.rendering:
            layout.template_running_jobs()
            return
        row = layout.row(align=True)
        row.operator("hgt.import_character", icon="IMPORT")
        root = target(context)
        if root:
            row.menu("HGT_MT_tools", text="", icon="DOWNARROW_HLT")
        if not root:
            row = layout.row(align=True)
            row.operator('hgt.open_extensions', icon='PREFERENCES')
            row.operator('hgt.help', icon='HELP')
            return
        roots = [o for o in context.scene.objects if o.hgt_character.managed]
        if len(roots) > 1:
            layout.prop(context.scene, "hgt_target", text="角色")
        column = layout.column(align=True)
        for name in ("shadow_position", "outline"):
            column.prop(root.hgt_character, name, slider=True)
        row = layout.row(align=True)
        for value, label in (('FULL', '全身'), ('HALF', '半身'), ('HEAD', '头像')):
            row.operator('hgt.set_shot', text=label, depress=root.hgt_character.shot == value).shot = value
        layout.separator(factor=.5)
        row = layout.row(align=True)
        row.operator("hgt.render", icon="RENDER_STILL")
        if HGT_OT_view_render.poll(context):
            row.operator('hgt.view_render', text='', icon='IMAGE_DATA')


class HGT_PT_lighting(Panel):
    bl_label = "展示"
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
        row = column.row(align=True)
        for key, value in presentation.LIGHTS.items():
            row.operator('hgt.light_preset', text=value[0]).preset = key
        for name in ("light_azimuth", "light_elevation"):
            column.prop(target(context).hgt_character, name)
        column.prop(context.scene.hgt_output, 'transparent')
        if not context.scene.hgt_output.transparent:
            column.prop(context.scene.hgt_output, 'background_color')
        column.prop(target(context).hgt_character, 'show_floor')
        column.operator('hgt.reset_display', icon='LOOP_BACK')


class HGT_PT_view(Panel):
    bl_label = '构图'
    bl_idname = 'HGT_PT_view'
    bl_parent_id = 'HGT_PT_main'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return bool(target(context))

    def draw(self, context):
        layout = self.layout;layout.enabled = not context.scene.hgt_output.rendering
        settings = target(context).hgt_character
        row = layout.row(align=True)
        for key, label in (('FRONT', '正面'), ('TURN', '斜侧'), ('SIDE', '侧面'), ('BACK', '背面')):
            row.operator('hgt.view_angle', text=label).angle = key
        for name in ('view_azimuth', 'view_elevation', 'frame_margin'):
            layout.prop(settings, name)
        layout.prop(context.scene.hgt_output, 'camera')
        if context.scene.hgt_output.camera == settings.camera:
            layout.operator('hgt.frame_camera', icon='VIEW_CAMERA')


class HGT_PT_expressions(Panel):
    bl_label = '表情'
    bl_idname = 'HGT_PT_expressions'
    bl_parent_id = 'HGT_PT_main'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        root = target(context)
        return bool(root and (root.hgt_character.expressions or expressions.eye_bones(root)))

    def draw(self, context):
        layout = self.layout;layout.enabled = not context.scene.hgt_output.rendering
        settings = target(context).hgt_character
        if settings.expressions:
            layout.template_list('HGT_UL_expressions', '', settings, 'expressions', settings, 'active_expression', rows=3)
        row = layout.row(align=True)
        if expressions.eye_bones(target(context)):
            row.operator('hgt.look_camera', depress=settings.look_camera, icon='HIDE_OFF')
        row.operator('hgt.reset_expressions', icon='LOOP_BACK')


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
        row = layout.row(align=True)
        for key, value in presentation.SIZES.items():
            row.operator('hgt.output_size', text=value[0]).preset = key
        row = layout.row(align=True)
        row.prop(settings, "width")
        row.prop(settings, "height")
        layout.prop(settings, "filepath")
        layout.prop(settings, "post_processing")


CLASSES = (HGT_UL_expressions, HGT_OT_set_shot, HGT_OT_view_angle, HGT_OT_light_preset, HGT_OT_output_size,
           HGT_OT_reset_display, HGT_OT_look_camera, HGT_OT_reset_expressions, HGT_OT_relink, HGT_OT_extensions, HGT_OT_help,
           HGT_OT_import_character, HGT_OT_restore, HGT_OT_frame, HGT_OT_render, HGT_OT_view_render, HGT_OT_material_info,
           HGT_OT_toggle_part, HGT_OT_manage_parts,
           HGT_MT_tools, HGT_PT_main, HGT_PT_view, HGT_PT_lighting, HGT_PT_expressions, HGT_PT_parts, HGT_PT_output)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
