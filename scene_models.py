"""Resolve scene MMD models without importing or repairing existing assets."""
import uuid
import bpy

_ACTIVE = {}


def source_root(obj):
    if obj is None:
        return None
    settings = getattr(obj, 'hgt_character', None)
    if settings and settings.source_root:
        return settings.source_root
    current = obj
    while current:
        if getattr(current, 'mmd_type', '') == 'ROOT':
            return current
        current = current.parent
    if obj.type == 'MESH':
        armature = obj.find_armature()
        if armature:
            return source_root(armature)
    return None


def armature(obj):
    settings = getattr(obj, 'hgt_character', None)
    if settings and settings.source_armature:
        return settings.source_armature
    root = source_root(obj)
    values = [o for o in root.children_recursive if o.type == 'ARMATURE' and source_root(o) == root] if root else []
    return values[0] if len(values) == 1 else None


def selected(context):
    obj = context.scene.hgt_model
    root = source_root(obj) or source_root(context.object)
    return root if root and root.name in context.scene.objects else None


def tracked(source, scene):
    root = source_root(source)
    if root is None:
        return None
    matches = [o for o in scene.objects if o.hgt_character.uid and o.hgt_character.source_root == root]
    if len(matches) > 1:
        raise ValueError('同一 MMD 模型存在多份材质记录，请保留一份')
    return matches[0] if matches else None


def remember_active(context):
    active = context.view_layer.objects.active
    _ACTIVE[context.scene.as_pointer()] = active.as_pointer() if active else 0


def sync_active(scene):
    if bpy.context.scene != scene:
        return
    active = bpy.context.view_layer.objects.active
    key = active.as_pointer() if active else 0
    if _ACTIVE.get(scene.as_pointer()) == key:
        return
    _ACTIVE[scene.as_pointer()] = key
    root = source_root(active)
    if root and root.name in scene.objects and scene.hgt_model != root:
        scene.hgt_model = root


def ensure(source, context, filepath=''):
    model = source_root(source)
    if model is None or model.name not in context.scene.objects:
        raise ValueError('请选择场景中的 MMD 模型、骨架或角色网格')
    existing = tracked(model, context.scene)
    if existing:
        if existing.hgt_character.schema_version != 2:
            raise ValueError('请先在原版本恢复该模型的材质，再使用当前版本')
        context.scene.hgt_target = existing
        return existing
    rig = armature(model)
    if rig is None:
        raise ValueError('MMD 模型需要唯一骨架')
    meshes = [o for o in model.children_recursive if o.type == 'MESH' and source_root(o) == model
              and getattr(o, 'mmd_type', '') not in {'RIGID_BODY', 'JOINT'}]
    if not meshes:
        raise ValueError('MMD 模型没有可渲染网格')
    if model.library or rig.library or rig.data.library or any(o.library or o.data.library for o in meshes):
        raise ValueError('请先将链接的角色模型设为本地或创建库覆写')
    collection = bpy.data.collections.new(model.name + ' • HGT')
    context.scene.collection.children.link(collection)
    root = bpy.data.objects.new(model.name + ' • HGT', None)
    collection.objects.link(root)
    settings = root.hgt_character
    settings.uid = uuid.uuid4().hex
    settings.schema_version = 2
    settings.source_format = 'pmx'
    settings.source_file = filepath
    settings.source_root, settings.source_armature = model, rig
    root['hgt_owner'] = collection['hgt_owner'] = settings.uid
    root.hide_set(True)
    for mesh in meshes:
        entry = settings.meshes.add()
        entry.object = mesh
        entry.original_hidden, entry.original_view_hidden = mesh.hide_render, mesh.hide_get()
    context.scene.hgt_target = root
    context.scene.hgt_model = model
    return root


def reset_selection_cache():
    _ACTIVE.clear()
