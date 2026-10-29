"""Stepwise PMX materials for an MMD workflow."""
from pathlib import Path
import json
import traceback
import bpy
from bpy.types import Operator, Panel, UIList, Menu
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper
from . import workflow, rendering, lighting, gaze, material_controls, project_io

def target(context):
    root = context.scene.hgt_target
    return root if workflow.current(root) else None

def report_error(operator, error):
    traceback.print_exc()
    operator.report({'ERROR'}, str(error))
    return {'CANCELLED'}

def idle(context):
    return bool(target(context) and (not context.scene.hgt_output.rendering))

class HGT_OT_import_character(Operator, ImportHelper):
    bl_idname = 'hgt.import_character'
    bl_label = '导入 PMX'
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = '.pmx'
    filter_glob: StringProperty(default='*.pmx', options={'HIDDEN'})

    def execute(self, context):
        try:
            if context.scene.hgt_output.rendering:
                raise ValueError('请等待渲染结束')
            workflow.build(self.filepath, context)
        except (ValueError, RuntimeError, OSError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}

class HGT_OT_apply_materials(Operator):
    bl_idname = 'hgt.apply_materials'
    bl_label = '应用材质'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return idle(context)

    def execute(self, context):
        try:
            workflow.apply_materials(target(context), context)
        except (ValueError, RuntimeError, OSError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}

class HGT_OT_restore(Operator):
    bl_idname = 'hgt.restore_materials'
    bl_label = '恢复原材质'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(idle(context) and target(context).hgt_character.managed)

    def execute(self, context):
        try:
            workflow.restore(target(context))
        except (ValueError, RuntimeError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}

class HGT_OT_reset_materials(Operator):
    bl_idname = 'hgt.reset_materials'
    bl_label = '重置材质参数'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return HGT_OT_restore.poll(context)

    def execute(self, context):
        material_controls.reset(target(context))
        workflow.refresh_character(target(context))
        return {'FINISHED'}

class HGT_OT_default_light(Operator):
    bl_idname = 'hgt.default_light'
    bl_label = '默认光'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return idle(context)

    def execute(self, context):
        try:
            lighting.default_light(target(context), context.scene)
        except (ValueError, RuntimeError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}

class HGT_OT_look_camera(Operator):
    bl_idname = 'hgt.look_camera'
    bl_label = '看向相机'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(idle(context) and gaze.eye_bones(target(context)))

    def execute(self, context):
        try:
            gaze.set_gaze(target(context), context.scene, not target(context).hgt_character.look_camera)
        except (ValueError, RuntimeError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}

class HGT_OT_align_camera(Operator):
    bl_idname = 'hgt.align_camera'
    bl_label = '相机对齐当前视角'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(idle(context) and context.area and (context.area.type == 'VIEW_3D'))

    def execute(self, context):
        camera = context.scene.hgt_output.camera
        if camera is None:
            return report_error(self, ValueError('请先选择相机'))
        context.scene.camera = camera
        region = next((r for r in context.area.regions if r.type == 'WINDOW'))
        with context.temp_override(region=region):
            return bpy.ops.view3d.camera_to_view()

class HGT_OT_render(Operator):
    bl_idname = 'hgt.render'
    bl_label = '渲染'

    @classmethod
    def poll(cls, context):
        return HGT_OT_restore.poll(context)

    def execute(self, context):
        try:
            result = rendering.start(context.scene, target(context), invoke=not bpy.app.background)
            if bpy.app.background:
                return {'FINISHED'}
            self._job = result
            self._timer = context.window_manager.event_timer_add(0.2, window=context.window)
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        except (ValueError, RuntimeError, OSError) as exc:
            return report_error(self, exc)

    def modal(self, context, event):
        if event.type != 'TIMER' or bpy.app.is_job_running('RENDER'):
            return {'PASS_THROUGH'}
        if rendering.job_state(self._job) == 'running':
            return {'PASS_THROUGH'}
        context.window_manager.event_timer_remove(self._timer)
        try:
            path = rendering.finish(self._job)
        except rendering.RenderCancelled:
            self.report({'INFO'}, '渲染已取消')
            return {'CANCELLED'}
        except (ValueError, RuntimeError, OSError) as exc:
            return report_error(self, exc)
        self.report({'INFO'}, '已保存：' + path)
        return {'FINISHED'}

class HGT_OT_view_render(Operator):
    bl_idname = 'hgt.view_render'
    bl_label = '查看图片'

    @classmethod
    def poll(cls, context):
        return bool(context.scene.hgt_output.last_render and Path(context.scene.hgt_output.last_render).is_file() and (not context.scene.hgt_output.rendering))

    def execute(self, context):
        return bpy.ops.wm.path_open(filepath=context.scene.hgt_output.last_render)

class HGT_OT_relink(Operator, ImportHelper):
    bl_idname = 'hgt.relink_resources'
    bl_label = '重新定位资源'
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = '.pmx'
    filter_glob: StringProperty(default='*.pmx', options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return idle(context)

    def execute(self, context):
        try:
            project_io.relink(target(context), self.filepath)
        except (ValueError, RuntimeError, OSError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}

class HGT_MT_tools(Menu):
    bl_idname = 'HGT_MT_tools'
    bl_label = '模型操作'

    def draw(self, context):
        self.layout.operator('hgt.relink_resources', icon='FILE_REFRESH')
        self.layout.operator('hgt.restore_materials', icon='LOOP_BACK')

class HGT_UL_materials(UIList):

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.source_name, icon='MATERIAL')

class HGT_PT_main(Panel):
    bl_label = 'Hoyo-GI-Toon'
    bl_idname = 'HGT_PT_main'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Hoyo-GI-Toon'

    def draw(self, context):
        layout = self.layout
        if context.scene.hgt_output.rendering:
            layout.template_running_jobs()
            return
        row = layout.row(align=True)
        row.operator('hgt.import_character', icon='IMPORT')
        root = target(context)
        if not root:
            if any((o.hgt_character.managed and o.hgt_character.schema_version < 2 for o in context.scene.objects)):
                layout.label(text='旧流程工程请使用 1.0.1', icon='INFO')
            return
        row.menu('HGT_MT_tools', text='', icon='DOWNARROW_HLT')
        if sum((workflow.current(o) for o in context.scene.objects)) > 1:
            layout.prop(context.scene, 'hgt_target', text='模型')
        layout.operator('hgt.apply_materials', icon='MATERIAL')
        row = layout.row(align=True)
        row.operator('hgt.render', icon='RENDER_STILL')
        if HGT_OT_view_render.poll(context):
            row.operator('hgt.view_render', text='', icon='IMAGE_DATA')

class HGT_PT_materials(Panel):
    bl_label = '材质参数'
    bl_idname = 'HGT_PT_materials'
    bl_parent_id = 'HGT_PT_main'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return bool(target(context) and target(context).hgt_character.managed)

    def draw(self, context):
        layout = self.layout
        layout.enabled = not context.scene.hgt_output.rendering
        settings = target(context).hgt_character
        layout.prop(settings, 'shadow_position', slider=True)
        if settings.has_outline:
            layout.prop(settings, 'outline', slider=True)
        layout.template_list('HGT_UL_materials', '', settings, 'bindings', settings, 'active_material', rows=3)
        if settings.bindings:
            item = settings.bindings[min(settings.active_material, len(settings.bindings) - 1)]
            layout.prop(item, 'tint')
            if item.role not in {'eye', 'brow', 'expression'}:
                layout.prop(item, 'shadow_color')
            edge = json.loads(item.generated['hgt_pmx'])
            if edge['edge'] and edge['edge_weight'] > 0 and edge['edge_color'][3] > 0 and edge['alpha'] > 0 and not edge['overlay'] and (item.role not in {'eye', 'brow', 'expression'}):
                layout.prop(item, 'outline_color')
        layout.operator('hgt.reset_materials', icon='LOOP_BACK')

class HGT_PT_light(Panel):
    bl_label = '打光'
    bl_idname = 'HGT_PT_light'
    bl_parent_id = 'HGT_PT_main'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return bool(target(context))

    def draw(self, context):
        self.layout.enabled = not context.scene.hgt_output.rendering
        self.layout.operator('hgt.default_light', icon='LIGHT_SUN')
        self.layout.prop(target(context).hgt_character, 'light_source')

class HGT_PT_camera(Panel):
    bl_label = '相机'
    bl_idname = 'HGT_PT_camera'
    bl_parent_id = 'HGT_PT_main'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return bool(target(context))

    def draw(self, context):
        layout = self.layout
        layout.enabled = not context.scene.hgt_output.rendering
        layout.prop(context.scene.hgt_output, 'camera')
        layout.operator('hgt.align_camera', icon='VIEW_CAMERA')
        if gaze.eye_bones(target(context)):
            layout.operator('hgt.look_camera', depress=target(context).hgt_character.look_camera, icon='HIDE_OFF')

class HGT_PT_output(Panel):
    bl_label = '输出'
    bl_idname = 'HGT_PT_output'
    bl_parent_id = 'HGT_PT_main'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return bool(target(context))

    def draw(self, context):
        layout = self.layout
        layout.enabled = not context.scene.hgt_output.rendering
        row = layout.row(align=True)
        row.prop(context.scene.render, 'resolution_x', text='宽')
        row.prop(context.scene.render, 'resolution_y', text='高')
        layout.prop(context.scene.hgt_output, 'filepath')
        layout.prop(context.scene.hgt_output, 'post_processing')
CLASSES = (HGT_OT_import_character, HGT_OT_apply_materials, HGT_OT_restore, HGT_OT_reset_materials, HGT_OT_default_light, HGT_OT_look_camera, HGT_OT_align_camera, HGT_OT_render, HGT_OT_view_render, HGT_OT_relink, HGT_MT_tools, HGT_UL_materials, HGT_PT_main, HGT_PT_materials, HGT_PT_light, HGT_PT_camera, HGT_PT_output)

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
