"""Independent, collapsible character, material and scene panels."""
import traceback
import bpy
from bpy.types import Operator, Panel, UIList
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper
from . import workflow, rendering, lighting, gaze, material_controls, scene_models, scene_presets, outlines, glow


def target(context):
    source = scene_models.selected(context)
    return scene_models.tracked(source, context.scene) if source else None


def idle(context):
    return not bpy.app.is_job_running('RENDER')


def report_error(operator, error):
    traceback.print_exc()
    operator.report({'ERROR'}, str(error))
    return {'CANCELLED'}


class HGT_OT_import_character(Operator, ImportHelper):
    bl_idname = 'hgt.import_character'
    bl_label = '导入模型'
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = '.pmx'
    filter_glob: StringProperty(default='*.pmx', options={'HIDDEN'})

    def execute(self, context):
        try:
            rendering.check_idle()
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
        return idle(context) and scene_models.selected(context) is not None

    def execute(self, context):
        try:
            workflow.apply_materials(scene_models.selected(context), context)
        except (ValueError, RuntimeError, OSError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}


class HGT_OT_toggle_display(Operator):
    bl_idname = 'hgt.toggle_display'
    bl_label = '骨骼显示'
    bl_description = '显示或隐藏所选角色的骨架（仅视口）'
    bl_options = {'REGISTER', 'UNDO'}
    bones: bpy.props.BoolProperty(default=True, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return idle(context) and scene_models.selected(context) is not None

    def execute(self, context):
        try:
            scene_models.toggle_visibility(scene_models.selected(context), self.bones)
        except (ValueError, RuntimeError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}


class HGT_OT_restore(Operator):
    bl_idname = 'hgt.restore_materials'
    bl_label = '恢复原材质'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        root = target(context)
        return bool(idle(context) and root and root.hgt_character.managed)

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
        workflow.refresh_character(target(context), scene=context.scene)
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
            lighting.default_light(context.scene)
        except (ValueError, RuntimeError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}


class HGT_OT_toggle_glow(Operator):
    bl_idname = 'hgt.toggle_glow'
    bl_label = '辉光'
    bl_description = '仅让角色管理中选定的人物产生辉光，保留背景和其他角色'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return idle(context)

    def execute(self, context):
        try:
            enabled = not glow.is_active(context.scene)
            (glow.enable if enabled else glow.disable)(context.scene)
            glow.viewport(context, enabled)
            context.scene.hgt_glow.error = ''
        except (ValueError, RuntimeError) as exc:
            context.scene.hgt_glow.error = str(exc)
            return report_error(self, exc)
        return {'FINISHED'}


class HGT_OT_apply_light_preset(Operator):
    bl_idname = 'hgt.apply_light_preset'
    bl_label = '启用打光'
    bl_description = '启用所选预设并保留在场景中；重复启用保留已调参数'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return idle(context)

    def execute(self, context):
        try:
            lighting.apply_preset(context.scene, context.scene.hgt_lighting.selected)
        except (ValueError, RuntimeError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}


class HGT_OT_load_scene(Operator):
    bl_idname = 'hgt.load_scene'
    bl_label = '载入场景'
    bl_description = '载入预设布景、相机、灯光和世界；不移动角色'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return idle(context) and context.mode == 'OBJECT'

    def execute(self, context):
        try:
            scene_presets.load(context, context.scene.hgt_scene_preset)
        except (ValueError, RuntimeError, OSError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}


class HGT_OT_remove_scene(Operator):
    bl_idname = 'hgt.remove_scene'
    bl_label = '移除场景'
    bl_description = '移除预设布景，恢复原相机、主光和世界；保留手动改选及复用的资产'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(idle(context) and context.mode == 'OBJECT' and context.scene.hgt_scene.uid)

    def execute(self, context):
        try:
            scene_presets.remove(context)
        except (ValueError, RuntimeError, OSError) as exc:
            return report_error(self, exc)
        return {'FINISHED'}


class HGT_OT_look_camera(Operator):
    bl_idname = 'hgt.look_camera'
    bl_label = '看向相机'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        source = scene_models.selected(context)
        return bool(idle(context) and source and context.scene.camera and gaze.eye_bones(source))

    def execute(self, context):
        transaction = workflow.asset_tracking.DataTransaction(context)
        try:
            root = scene_models.ensure(scene_models.selected(context), context)
            gaze.set_gaze(root, context.scene, not root.hgt_character.look_camera)
        except (ValueError, RuntimeError) as exc:
            transaction.rollback()
            return report_error(self, exc)
        return {'FINISHED'}


class HGT_OT_align_camera(Operator):
    bl_idname = 'hgt.align_camera'
    bl_label = '相机对齐当前视角'
    bl_description = '使用当前场景相机对齐视角；场景没有相机时创建一个'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(idle(context) and context.area and context.area.type == 'VIEW_3D'
                    and context.space_data.region_3d.view_perspective != 'CAMERA')

    def execute(self, context):
        rendering.prepare(context.scene)
        region = next(r for r in context.area.regions if r.type == 'WINDOW')
        with context.temp_override(region=region):
            return bpy.ops.view3d.camera_to_view()


class HGT_OT_render(Operator):
    bl_idname = 'hgt.render'
    bl_label = '渲染'
    bl_description = '使用 Blender 当前场景、相机与原生渲染结果'

    @classmethod
    def poll(cls, context):
        return bool(idle(context) and context.scene.camera)

    def execute(self, context):
        try:
            return rendering.start(context.scene, invoke=not bpy.app.background)
        except (ValueError, RuntimeError) as exc:
            return report_error(self, exc)


class HGT_UL_materials(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.source_name, icon='MATERIAL')


def draw_materials(layout, context):
    column = layout.column()
    column.enabled = idle(context)
    root = target(context)
    source = scene_models.selected(context)
    if source:
        column.prop((root or source).hgt_character, 'face_sdf_preset')
    if not root or not root.hgt_character.managed:
        column.operator('hgt.apply_materials', icon='MATERIAL')
        return
    settings = root.hgt_character
    column.prop(settings, 'shadow_softness', slider=True)
    if settings.has_outline:
        column.prop(settings, 'outline', slider=True)
        column.prop(settings, 'outline_difference', slider=True)
    column.prop(settings, 'show_material_advanced', icon='TRIA_DOWN' if settings.show_material_advanced else 'TRIA_RIGHT', emboss=False)
    if settings.show_material_advanced:
        advanced = column.column()
        advanced.prop(settings, 'shadow_bias', slider=True)
        if any(b.generated and b.generated.get('hgt_template') == 'Face' for b in settings.bindings):
            advanced.prop(settings, 'face_softness_adjust', slider=True)
    row = column.row(align=True)
    row.operator('hgt.reset_materials', text='重置参数', icon='LOOP_BACK')
    row.operator('hgt.restore_materials', text='恢复原材质')
    if settings.preview_error:
        error = column.column()
        error.alert = True
        error.label(text=settings.preview_error, icon='ERROR')


def draw_local_colors(column, context):
    root = target(context)
    if not root or not root.hgt_character.managed:
        column.label(text='应用材质后调整局部颜色', icon='MATERIAL')
        return
    settings = root.hgt_character
    column.template_list('HGT_UL_materials', '', settings, 'bindings', settings, 'active_material', rows=3, maxrows=3)
    if settings.bindings:
        item = settings.bindings[min(max(0, settings.active_material), len(settings.bindings) - 1)]
        row = column.row(align=True)
        row.label(text='颜色')
        row.prop(item, 'tint', text='')
        column.prop(item, 'brightness', slider=True)
        column.prop(item, 'saturation', slider=True)
        column.prop(item, 'opacity', slider=True)
        if item.role not in {'eye', 'brow', 'expression'}:
            row = column.row(align=True)
            row.label(text='阴影颜色')
            row.prop(item, 'shadow_color', text='')
        if outlines.eligible(item):
            row = column.row(align=True)
            row.label(text='描边颜色')
            row.prop(item, 'outline_color', text='')


class HGTPanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'GI-Toon'


class HGT_PT_main(HGTPanel, Panel):
    bl_label = '角色管理'
    bl_idname = 'HGT_PT_main'
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        layout.enabled = idle(context)
        source = scene_models.selected(context)
        row = layout.row(align=True)
        row.operator('hgt.import_character', icon='IMPORT')
        row.prop(context.scene, 'hgt_model', text='')
        visible = scene_models.visible(source, bones=True)
        row.operator('hgt.toggle_display', text='', icon='HIDE_OFF' if visible else 'HIDE_ON',
                     depress=visible).bones = True


class HGT_PT_materials(HGTPanel, Panel):
    bl_label = '材质'
    bl_idname = 'HGT_PT_materials'
    bl_order = 1

    def draw(self, context):
        draw_materials(self.layout, context)


class HGT_PT_local_colors(HGTPanel, Panel):
    bl_label = '局部调色'
    bl_idname = 'HGT_PT_local_colors'
    bl_order = 2

    def draw(self, context):
        self.layout.enabled = idle(context)
        draw_local_colors(self.layout, context)


class HGT_PT_effects(HGTPanel, Panel):
    bl_label = '附加效果'
    bl_idname = 'HGT_PT_effects'
    bl_order = 3

    def draw(self, context):
        layout = self.layout
        layout.enabled = idle(context)
        active = glow.is_active(context.scene)
        settings = context.scene.hgt_glow
        layout.operator('hgt.toggle_glow', text='辉光', icon='LIGHT_SUN', depress=active)
        if active:
            layout.label(text='人物：' + settings.target.name if settings.target else '未选定人物', icon='OUTLINER_OB_ARMATURE')
            layout.prop(settings, 'threshold', slider=True)
            layout.prop(settings, 'strength', slider=True)
            layout.prop(settings, 'size', slider=True)
        if settings.error:
            column = layout.column()
            column.alert = True
            column.label(text=settings.error, icon='ERROR')


class HGT_PT_scene(HGTPanel, Panel):
    bl_label = '场景'
    bl_idname = 'HGT_PT_scene'
    bl_order = 4
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.enabled = idle(context)
        row = layout.row(align=True)
        row.prop(context.scene, 'hgt_scene_preset', text='')
        row.operator('hgt.load_scene', text='载入', icon='IMPORT')
        row.operator('hgt.remove_scene', text='', icon='X')


class HGT_PT_lighting(HGTPanel, Panel):
    bl_label = '打光'
    bl_idname = 'HGT_PT_lighting'
    bl_order = 5
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.enabled = idle(context)
        row = layout.row(align=True)
        row.prop(context.scene.hgt_lighting, 'selected', text='')
        row.operator('hgt.apply_light_preset', text='启用', icon='LIGHT_SUN')
        layout.prop(context.scene, 'hgt_light')
        light = context.scene.hgt_light
        if light:
            parameters = lighting.active_parameters(context.scene) if light.get('hgt_scene_light') else None
            if parameters:
                for name in ('energy', 'color', 'azimuth', 'elevation', 'angle'):
                    layout.prop(parameters, name)
            else:
                layout.prop(light.data, 'energy', text='强度')
                layout.prop(light.data, 'color', text='颜色')
                layout.prop(light, 'rotation_euler', text='旋转')


class HGT_PT_camera(HGTPanel, Panel):
    bl_label = '相机'
    bl_idname = 'HGT_PT_camera'
    bl_order = 6

    def draw(self, context):
        layout = self.layout
        layout.enabled = idle(context)
        layout.prop(context.scene, 'camera', text='相机')
        layout.operator('hgt.align_camera', icon='VIEW_CAMERA')
        root = target(context)
        layout.operator('hgt.look_camera', depress=bool(root and root.hgt_character.look_camera), icon='HIDE_OFF')
        layout.separator()
        layout.operator('hgt.render', icon='RENDER_STILL')


CLASSES = (HGT_OT_import_character, HGT_OT_apply_materials, HGT_OT_toggle_display, HGT_OT_restore, HGT_OT_reset_materials,
           HGT_OT_default_light, HGT_OT_toggle_glow, HGT_OT_apply_light_preset, HGT_OT_load_scene, HGT_OT_remove_scene, HGT_OT_look_camera, HGT_OT_align_camera, HGT_OT_render,
           HGT_UL_materials, HGT_PT_main, HGT_PT_materials, HGT_PT_local_colors, HGT_PT_effects, HGT_PT_scene, HGT_PT_lighting, HGT_PT_camera)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
