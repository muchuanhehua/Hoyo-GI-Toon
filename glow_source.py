"""A character-only view layer using the original objects and transparency."""
import uuid

import bpy

TAG = 'hgt_glow_source'
OWNER = 'hgt_glow_scene'
MASTER = 'hgt_glow_master'
RENDERABLE = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'VOLUME', 'GREASEPENCIL'}


def target(scene):
    from .scene_models import source_root
    source = source_root(scene.hgt_model)
    if source is None and scene.hgt_target:
        source = scene.hgt_target.hgt_character.source_root
    return source if source and source.name in scene.objects else None


def members(root):
    from .scene_models import source_root
    return {o for o in root.children_recursive if source_root(o) == root
            and (o.type in RENDERABLE or o.instance_type == 'COLLECTION')
            and getattr(o, 'mmd_type', '') not in {'RIGID_BODY', 'JOINT'}} if root else set()


def base_layer(scene):
    settings = scene.hgt_glow
    layer = scene.view_layers.get(settings.base_layer)
    if layer is None or layer.get(TAG):
        layer = next((v for v in scene.view_layers if not v.get(TAG)), None)
    if layer is None:
        raise ValueError('场景没有可用于人物辉光的原视图层')
    return layer


def preflight(scene, root):
    if not root or not members(root):
        raise ValueError('请先在角色管理中选定人物')


def _group_direct(scene):
    settings = scene.hgt_glow
    direct = [o for o in scene.collection.objects if o.type in RENDERABLE or o.instance_type == 'COLLECTION']
    if not direct:return
    master = settings.master_collection
    if master and master.get(OWNER) != scene:
        raise ValueError('人物辉光的根层辅助集合归属已改变')
    if not master:
        master = bpy.data.collections.new('HGT • Original Root Objects')
        master[MASTER], master[OWNER] = settings.scope_id, scene
        scene.collection.children.link(master)
        settings.master_collection = master
    for obj in direct:
        if obj.name not in master.objects:master.objects.link(obj)
        scene.collection.objects.unlink(obj)


def create(scene, root):
    preflight(scene, root)
    settings = scene.hgt_glow
    if bpy.context.scene == scene and not bpy.context.view_layer.get(TAG):
        settings.base_layer = bpy.context.view_layer.name
    base = base_layer(scene)
    settings.base_layer = base.name
    settings.scope_id = uuid.uuid4().hex
    collection = bpy.data.collections.new('HGT • Character Glow')
    collection[TAG], collection[OWNER] = settings.scope_id, scene
    scene.collection.children.link(collection)
    settings.source_collection = collection
    # Scene Collection links cannot be excluded per view layer. Group them
    # reversibly, retaining the original objects, data, modifiers and physics.
    _group_direct(scene)
    for name in ('Character', 'Occluders', 'Support'):
        child = bpy.data.collections.new('HGT • Glow ' + name)
        child[TAG] = name
        collection.children.link(child)
    layer = scene.view_layers.new('HGT • Character Glow')
    layer[TAG] = settings.scope_id
    layer.use_sky = False
    layer.use_motion_blur = base.use_motion_blur
    settings.render_layer = layer.name
    settings.previous_single_layer = scene.render.use_single_layer
    scene.render.use_single_layer = False
    sync(scene, root=root)
    return layer


def sync(scene, root=None, render=False):
    settings = scene.hgt_glow
    collection = settings.source_collection
    layer = scene.view_layers.get(settings.render_layer)
    if not collection or collection.get(OWNER) != scene or not layer or layer.get(TAG) != settings.scope_id:
        raise ValueError('人物辉光专用视图层已改变，请关闭后重新开启')
    base = base_layer(scene)
    _group_direct(scene)
    root = target(scene) if root is None else root
    if settings.target != root:settings.target = root
    selected = members(root)
    children = {c.get(TAG): c for c in collection.children}
    if set(children) != {'Character', 'Occluders', 'Support'}:
        raise ValueError('人物辉光辅助集合已改变，请先恢复其子集合')
    for view in scene.view_layers:
        for child in view.layer_collection.children:
            if view == layer:
                excluded = child.collection != collection
                if child.exclude != excluded:child.exclude = excluded
            elif child.collection.get(TAG):
                if not child.exclude:child.exclude = True
    # The original view layer excludes our root, so these are user objects only.
    objects = set(base.objects)
    wanted = {'Character': set(), 'Occluders': set(), 'Support': set()}
    for obj in objects:
        geometry = obj.type in RENDERABLE or obj.instance_type == 'COLLECTION'
        key = ('Character' if obj in selected else 'Occluders') if geometry else 'Support'
        wanted[key].add(obj)
    for name, child in children.items():
        current = set(child.objects)
        for obj in current - wanted[name]:child.objects.unlink(obj)
        for obj in wanted[name] - current:child.objects.link(obj)
    layer.update()
    root_layer = layer.layer_collection.children[collection.name]
    occluders = root_layer.children[children['Occluders'].name]
    if not occluders.holdout:occluders.holdout = True
    for obj in objects:
        hidden = False if render else obj.hide_get(view_layer=base)
        if obj.hide_get(view_layer=layer) != hidden:
            obj.hide_set(hidden, view_layer=layer)
    for key, value in base.items():
        if key == TAG:continue
        value = value.to_list() if hasattr(value, 'to_list') else value
        if layer.get(key) != value:layer[key] = value
    layer.update()
    return layer


def preflight_remove(scene):
    settings = scene.hgt_glow
    collection = settings.source_collection
    if not collection or collection.get(OWNER) != scene:
        return
    if any(c.get(TAG) not in {'Character', 'Occluders', 'Support'} or c.children for c in collection.children):
        raise ValueError('辉光辅助集合包含用户新增集合，请先移出')
    if any(len(o.users_collection) == 1 for c in collection.children for o in c.objects):
        raise ValueError('辉光辅助集合包含用户新增物体，请先移出')
    master = settings.master_collection
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
    if not collection or collection.get(OWNER) != scene:
        settings.source_collection = None
        settings.render_layer = ''
        settings.target = None
        return
    layer = scene.view_layers.get(settings.render_layer)
    if layer and layer.get(TAG) == settings.scope_id:
        base = base_layer(scene)
        for window in bpy.context.window_manager.windows:
            if window.scene == scene and window.view_layer == layer:window.view_layer = base
        scene.view_layers.remove(layer)
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
    if not scene.render.use_single_layer:
        scene.render.use_single_layer = settings.previous_single_layer
    settings.source_collection = None
    settings.render_layer = ''
    settings.target = None
