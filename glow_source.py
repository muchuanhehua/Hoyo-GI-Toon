"""Retire owned character-source data from pre-2.10 saved projects."""
import bpy

TAG = 'hgt_glow_source'
OWNER = 'hgt_glow_scene'
MASTER = 'hgt_glow_master'
PREVIEW_TAG = 'hgt_glow_preview'


def base_layer(scene):
    settings = scene.hgt_glow
    layer = scene.view_layers.get(settings.base_layer)
    if layer is None or layer.get(TAG):
        layer = next((v for v in scene.view_layers if not v.get(TAG)), None)
    if layer is None:
        raise ValueError('场景没有可用于人物辉光的原视图层')
    return layer


def clear_preview(scene):
    scope = scene.hgt_glow.scope_id
    if not scope:return
    for image in tuple(bpy.data.images):
        if image.get(PREVIEW_TAG) == scope and image.users == 0:
            bpy.data.images.remove(image)


def preflight_remove(scene):
    settings = scene.hgt_glow
    collection = settings.source_collection
    if collection and collection.get(OWNER) != scene:
        raise ValueError('旧辉光辅助集合归属已改变，请先分离旧辉光设置')
    if collection and any(c.get(TAG) not in {'Character', 'Occluders', 'Support'} or c.children for c in collection.children):
        raise ValueError('辉光辅助集合包含用户新增集合，请先移出')
    if collection and any(len(o.users_collection) == 1 for c in collection.children for o in c.objects):
        raise ValueError('辉光辅助集合包含用户新增物体，请先移出')
    master = settings.master_collection
    if master and master.get(OWNER) != scene:
        raise ValueError('旧辉光根层集合归属已改变，请先分离旧辉光设置')
    if master and master.get(OWNER) == scene and master.children:
        raise ValueError('辉光根层辅助集合包含用户新增集合，请先移出')
    roots = {c for c in (collection, master) if c}
    if any(c.name in other.collection.children for other in bpy.data.scenes if other != scene for c in roots):
        raise ValueError('其他场景正在使用辉光辅助集合，请先取消该集合链接')
    if any(c.name in parent.children for parent in bpy.data.collections for c in roots):
        raise ValueError('其他集合正在使用辉光辅助集合，请先取消该集合链接')


def remove(scene):
    preflight_remove(scene)
    settings = scene.hgt_glow
    collection = settings.source_collection
    had_source = bool(collection or settings.master_collection or settings.scope_id)
    layer = scene.view_layers.get(settings.render_layer)
    if layer and layer.get(TAG) == settings.scope_id:
        base = base_layer(scene)
        for window in bpy.context.window_manager.windows:
            if window.scene == scene and window.view_layer == layer:window.view_layer = base
        # A view-layer driver belongs to the retired layer as well. Leaving it
        # behind makes Blender repeatedly evaluate an invalid RNA target.
        prefix = layer.path_from_id()
        if scene.animation_data:
            for driver in tuple(scene.animation_data.drivers):
                if driver.data_path.startswith((prefix + '.', prefix + '[')):
                    scene.driver_remove(driver.data_path, driver.array_index)
        scene.view_layers.remove(layer)
    if collection:
        children = list(collection.children)
        bpy.data.collections.remove(collection)
        for child in children:
            if child.users == 0:bpy.data.collections.remove(child)
    master = settings.master_collection
    if master and master.get(OWNER) == scene:
        for obj in tuple(master.objects):
            if obj.name not in scene.collection.objects:scene.collection.objects.link(obj)
        bpy.data.collections.remove(master)
    settings.master_collection = None
    if had_source and not scene.render.use_single_layer:
        scene.render.use_single_layer = settings.previous_single_layer
    settings.source_collection = None
    settings.render_layer = ''
    settings.target = None
    settings.scope_id = settings.base_layer = ''
