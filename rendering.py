"""Use Blender's current scene, camera and native render result."""
import bpy


def check_idle():
    if bpy.app.is_job_running('RENDER'):
        raise RuntimeError('请先结束当前渲染')


def prepare(scene):
    if scene.camera:
        return scene.camera
    data = bpy.data.cameras.new('HGT • Camera')
    camera = bpy.data.objects.new(data.name, data)
    scene.collection.objects.link(camera)
    camera['hgt_scene_camera'] = True
    scene.camera = camera
    return camera


def configure_material_render(scene):
    scene.render.engine = 'BLENDER_EEVEE'
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1


def start(scene, invoke=False):
    check_idle()
    if scene.camera is None:
        raise ValueError('请先选择相机，或点击“相机对齐当前视角”创建相机')
    if scene != bpy.context.scene:
        raise ValueError('请切换到要渲染的场景')
    result = bpy.ops.render.render('INVOKE_DEFAULT' if invoke else 'EXEC_DEFAULT', write_still=False)
    if result not in ({'FINISHED'}, {'RUNNING_MODAL'}):
        raise RuntimeError('Blender 渲染未启动')
    return result
