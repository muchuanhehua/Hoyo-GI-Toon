"""Use Blender's current scene, camera and native render result."""
import bpy
from mathutils import Vector


def check_idle():
    if bpy.app.is_job_running('RENDER'):
        raise RuntimeError('请先结束当前渲染')


def prepare(scene, model=None):
    if scene.camera:
        return scene.camera
    data = bpy.data.cameras.new('HGT • Camera')
    camera = bpy.data.objects.new(data.name, data)
    scene.collection.objects.link(camera)
    camera['hgt_scene_camera'] = True
    meshes = [entry.object for entry in model.hgt_character.meshes if entry.object] if model else []
    points = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    if points:
        low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
        high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
        center = (low + high) * .5
        size = max(high.z - low.z, .01)
        aspect = (scene.render.resolution_x * scene.render.pixel_aspect_x
                  / max(1, scene.render.resolution_y * scene.render.pixel_aspect_y))
        data.type = 'ORTHO'
        data.ortho_scale = max(size, (high.x - low.x) / aspect) * 1.15 * max(1, aspect)
        camera.location = center + Vector((0, -max(size * 3, 2), 0))
        data.clip_start, data.clip_end = .01, max(100, size * 10)
    else:
        center = Vector((0, 0, 1))
        camera.location = (0, -5, 1)
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
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
