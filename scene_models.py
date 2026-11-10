"""Resolve scene MMD models without importing or repairing existing assets."""
import uuid
import bpy

_ACTIVE = {}
_OWNERS = {}


def in_scene(obj, scene):
    """Validate cached owner collections instead of searching every scene object."""
    if obj is None:
        return False
    hierarchy = {scene.collection, *scene.collection.children_recursive}
    key = obj.as_pointer()
    for collection in _OWNERS.get(key, ()):
        try:
            if collection in hierarchy and collection.objects.get(obj.name) == obj:
                return True
        except ReferenceError:
            # Deletion/undo can replace a collection before the cache is reset.
            continue
    # Only positive membership is cached, and it is checked again on every use.
    # New links, other scenes and removed owners need a fresh ownership query.
    owners = obj.users_collection
    _OWNERS[key] = owners
    return any(collection in hierarchy for collection in owners)


def model_root(obj):
    return bool(obj and getattr(obj, 'mmd_type', '') == 'ROOT' and source_root(obj) == obj
                and armature(obj) and meshes(obj))


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


def meshes(source):
    root = source_root(source)
    return [obj for obj in root.children_recursive if obj.type == 'MESH' and source_root(obj) == root
            and getattr(obj, 'mmd_type', '') not in {'RIGID_BODY', 'JOINT'}] if root else []


def visible(source, bones=False):
    values = [armature(source)] if bones else meshes(source)
    return any(obj and not obj.hide_get() for obj in values)


def toggle_visibility(source, bones=False):
    values = [armature(source)] if bones else meshes(source)
    values = [obj for obj in values if obj]
    if not values:
        raise ValueError('当前模型没有可显示的' + ('骨架' if bones else '网格'))
    hide = visible(source, bones)
    snapshots = source_root(source).hgt_character.display_meshes
    if not bones:
        if hide:
            snapshots.clear()
            for obj in values:
                entry = snapshots.add()
                entry.object, entry.hidden = obj, obj.hide_get()
        elif snapshots:
            for entry in snapshots:
                if entry.object and entry.object in values:
                    entry.object.hide_set(entry.hidden)
            snapshots.clear()
            return
    for obj in values:
        obj.hide_set(hide)


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
    settings.face_sdf_preset = model.hgt_character.face_sdf_preset
    root['hgt_owner'] = collection['hgt_owner'] = settings.uid
    root.hide_set(True)
    for mesh in meshes:
        entry = settings.meshes.add()
        entry.object = mesh
        entry.original_hidden, entry.original_view_hidden = mesh.hide_render, mesh.hide_get()
    context.scene.hgt_target = root
    context.scene.hgt_model = model
    from .workflow import reset_runtime_cache
    reset_runtime_cache()
    return root


def reset_selection_cache():
    _ACTIVE.clear()
    _OWNERS.clear()
