"""Detach legacy preset cameras without discarding MMD camera animation."""
import bpy

OWNER = 'hgt_scene_owner'


def animated(obj):
    for item in (obj, obj.data):
        data = item.animation_data
        if data and (data.action or data.nla_tracks or data.drivers):
            return True
    return bool(obj.constraints or (obj.parent and obj.parent.animation_data))


def detach(scene, camera, uid):
    if camera.name not in scene.collection.objects:
        scene.collection.objects.link(camera)
    shared = {collection for other in camera.users_scene if other != scene
              for collection in other.collection.children_recursive}
    for collection in tuple(camera.users_collection):
        if collection.get(OWNER) == uid and collection not in shared:
            collection.objects.unlink(camera)
    for item in (camera, camera.data):
        if item.get(OWNER) == uid:
            del item[OWNER]


def migrate(scene):
    """Promote the animated legacy camera; its data, NLA and drivers stay intact."""
    state = scene.hgt_scene
    uid = state.uid
    if not uid:
        return
    cameras = [obj for obj in scene.objects if obj.type == 'CAMERA' and obj.get(OWNER) == uid]
    if not cameras:
        return
    default = state.previous_camera
    if not (default and default.type == 'CAMERA' and default.name in scene.objects):
        default = None
    active = state.camera if state.camera in cameras else None
    moving = [obj for obj in cameras if animated(obj)]
    if len(moving) > 1:
        raise ValueError('旧场景有多台带动画的预设相机，请先明确保留的镜头')
    chosen = moving[0] if moving else default or active or cameras[0]
    replacing = chosen in cameras and default and default != chosen and default.get('hgt_scene_camera')
    if replacing and (animated(default) or tuple(default.users_scene) != (scene,)):
        raise ValueError('默认相机也有动画或被其他场景复用，请先明确保留的镜头')
    # A manual camera choice belongs to the user, even while a preset is active.
    selected = scene.camera
    follow_chosen = selected in cameras or selected == default or selected is None
    name = default.name if replacing else None
    if chosen in cameras:
        detach(scene, chosen, uid)
        chosen['hgt_scene_camera'] = True
        if replacing:
            data = default.data
            default.user_remap(chosen)
            bpy.data.objects.remove(default, do_unlink=True)
            if data.users == 0:
                bpy.data.cameras.remove(data)
            chosen.name = name
        elif not default:
            chosen.name = 'HGT • Camera'
    if follow_chosen:
        scene.camera = chosen
    state.camera = state.previous_camera = None
    # Keep other reused preset cameras; ordinary unused reference cameras can go.
    users = bpy.data.user_map(subset=set(cameras))
    for camera in cameras:
        if camera == chosen:
            continue
        external = [item for item in users.get(camera, ())
                    if item not in {scene, state.collection} and item.get(OWNER) != uid]
        camera_cut = any(marker.camera == camera for other in bpy.data.scenes for marker in other.timeline_markers)
        if external or camera_cut or len(camera.users_scene) > 1 or animated(camera) or camera.children:
            detach(scene, camera, uid)
            continue
        data = camera.data
        bpy.data.objects.remove(camera, do_unlink=True)
        if data.users == 0:
            bpy.data.cameras.remove(data)
