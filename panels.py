"""Always-visible material, lighting and camera tools for scene MMD models."""
import json
import traceback
import bpy
from bpy.types import Operator, Panel, UIList, Menu
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper
from . import workflow, rendering, lighting, gaze, material_controls, scene_models, scene_presets


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
    bl_label = '导入 PMX'
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


class HGT_OT_face_resources(Operator):
    bl_idname = 'hgt.face_resources'
    bl_label = '选择脸部资源'
    bl_description = '选择同角色 FBX 资源包或 Textures 目录；更换前先恢复原材质'
    bl_options = {'REGISTER', 'UNDO'}
    directory: StringProperty(name='目录', subtype='DIR_PATH')
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        root = target(context)
        return bool(idle(context) and scene_models.selected(context)
                    and (root is None or not root.hgt_character.managed))

    def invoke(self, context, event):
        root = target(context)
        if root:
            self.directory = root.hgt_character.face_resource_directory
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        transaction = workflow.asset_tracking.DataTransaction(context)
        try:
            from .face_assets import FaceResources
            directory = bpy.path.abspath(self.directory) if self.directory else ''
            if directory:
                FaceResources(directory=directory).resolve()
            root = scene_models.ensure(scene_models.selected(context), context)
            if root.hgt_character.managed:
                raise ValueError('请先恢复原材质，再更换脸部资源')
            root.hgt_character.face_resource_directory = directory
        except (ValueError, RuntimeError, OSError) as exc:
            transaction.rollback()
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


class HGT_MT_tools(Menu):
    bl_idname = 'HGT_MT_tools'
    bl_label = '模型操作'

    def draw(self, context):
        self.layout.operator('hgt.restore_materials', icon='LOOP_BACK')
        self.layout.operator('hgt.face_resources', icon='FILE_FOLDER')
        self.layout.operator('file.find_missing_files', text='查找丢失贴图', icon='FILE_REFRESH')


class HGT_UL_materials(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.source_name, icon='MATERIAL')


def draw_materials(layout, context):
    column = layout.column()
    column.enabled = idle(context)
    column.label(text='材质', icon='MATERIAL')
    column.operator('hgt.apply_materials', icon='MATERIAL')
    root = target(context)
    if not root or not root.hgt_character.managed:
        return
    settings = root.hgt_character
    column.prop(settings, 'shadow_position', slider=True)
    if any(b.generated and b.generated.get('hgt_template') == 'Face' for b in settings.bindings):
        column.prop(settings, 'face_softness', slider=True)
    if settings.has_outline:
        column.prop(settings, 'outline', slider=True)
    column.template_list('HGT_UL_materials', '', settings, 'bindings', settings, 'active_material', rows=3, maxrows=3)
    if settings.bindings:
        item = settings.bindings[min(max(0, settings.active_material), len(settings.bindings) - 1)]
        row = column.row(align=True)
        row.label(text='颜色')
        row.prop(item, 'tint', text='')
        if item.role not in {'eye', 'brow', 'expression'}:
            row = column.row(align=True)
            row.label(text='阴影颜色')
            row.prop(item, 'shadow_color', text='')
        edge = json.loads(item.generated['hgt_pmx'])
        if edge['edge'] and edge['edge_weight'] > 0 and edge['edge_color'][3] > 0 and edge['alpha'] > 0 and not edge['overlay'] and item.role not in {'eye', 'brow', 'expression'}:
            row = column.row(align=True)
            row.label(text='描边颜色')
            row.prop(item, 'outline_color', text='')
    column.operator('hgt.reset_materials', icon='LOOP_BACK')


class HGT_PT_main(Panel):
    bl_label = 'Hoyo-GI-Toon'
    bl_idname = 'HGT_PT_main'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Hoyo-GI-Toon'

    def draw(self, context):
        layout = self.layout
        layout.enabled = idle(context)
        row = layout.row(align=True)
        row.operator('hgt.import_character', icon='IMPORT')
        row.menu('HGT_MT_tools', text='', icon='DOWNARROW_HLT')
        layout.prop(context.scene, 'hgt_model')
        layout.separator()
        draw_materials(layout, context)
        layout.separator()
        layout.label(text='场景预设', icon='SCENE_DATA')
        row = layout.row(align=True)
        row.prop(context.scene, 'hgt_scene_preset', text='')
        row.operator('hgt.load_scene', text='载入', icon='IMPORT')
        row.operator('hgt.remove_scene', text='', icon='X')
        layout.separator()
        layout.label(text='打光', icon='LIGHT_SUN')
        layout.operator('hgt.default_light', icon='LIGHT_SUN')
        layout.prop(context.scene, 'hgt_light')
        layout.separator()
        layout.label(text='相机', icon='CAMERA_DATA')
        layout.prop(context.scene, 'camera', text='相机')
        layout.operator('hgt.align_camera', icon='VIEW_CAMERA')
        root = target(context)
        layout.operator('hgt.look_camera', depress=bool(root and root.hgt_character.look_camera), icon='HIDE_OFF')
        layout.separator()
        layout.operator('hgt.render', icon='RENDER_STILL')


CLASSES = (HGT_OT_import_character, HGT_OT_apply_materials, HGT_OT_face_resources, HGT_OT_restore, HGT_OT_reset_materials,
           HGT_OT_default_light, HGT_OT_load_scene, HGT_OT_remove_scene, HGT_OT_look_camera, HGT_OT_align_camera, HGT_OT_render,
           HGT_MT_tools, HGT_UL_materials, HGT_PT_main)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
