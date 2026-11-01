"""Append optional environments without replacing character or output data."""
import json
from pathlib import Path
from uuid import uuid4
import bpy
from mathutils import Matrix, Vector
from . import asset_tracking, rendering

ASSETS = Path(__file__).resolve().parent / 'assets'
PRESETS = {item['id']: item for item in json.loads((ASSETS / 'scenes.json').read_text('utf-8'))['presets']}
PRESET_ITEMS = tuple((key, item['name'], '') for key, item in PRESETS.items())
OWNER = 'hgt_scene_owner'


def _owned(uid):
    return {item for kind in asset_tracking.DATA_KINDS for item in getattr(bpy.data, kind)
            if item.get(OWNER) == uid}


def _release(scene, collection, uid):
    """Unlink this preset; keep anything the user has reused or added."""
    if collection:
        for parent in (scene.collection, *scene.collection.children_recursive):
            if collection.name in parent.children:
                parent.children.unlink(collection)
        if collection.users:
            return
    owned = _owned(uid)
    collections = {item for item in owned if isinstance(item, bpy.types.Collection)}
    for parent in collections:
        for child in parent.children:
            if child not in owned and child.name not in scene.collection.children:
                scene.collection.children.link(child)
        for obj in parent.objects:
            if obj not in owned and obj.name not in scene.collection.objects:
                scene.collection.objects.link(obj)
    users = bpy.data.user_map(subset=owned)
    protected = {item for item in owned if users.get(item, set()) - owned}
    while True:
        dependent = {item for item in owned - protected if users.get(item, set()) & protected}
        if not dependent:
            break
        protected.update(dependent)
    removed = {item for item in owned - protected if isinstance(item, (bpy.types.Object, bpy.types.Collection))}
    for item in protected:
        if isinstance(item, bpy.types.Object) and all(parent in removed for parent in item.users_collection):
            scene.collection.objects.link(item)
    bpy.data.batch_remove(ids=removed)
    # Delete unused dependencies in layers, leaving materials/meshes reused elsewhere.
    while True:
        unused = {item for item in _owned(uid) if item.users == 0}
        if not unused:
            break
        bpy.data.batch_remove(ids=unused)


def restore_default_light(scene, force=False):
    state = scene.hgt_scene
    light = state.muted_light
    if light and (force or scene.hgt_light == light):
        if light.hide_render:
            light.hide_render = state.muted_render
        if light.hide_viewport:
            light.hide_viewport = state.muted_viewport
    state.muted_light = None


def _mute_default_light(scene):
    state, light = scene.hgt_scene, scene.hgt_light
    if (light and light.get('hgt_scene_light') and light != state.muted_light
            and tuple(light.users_scene) == (scene,)):
        state.muted_light = light
        state.muted_render, state.muted_viewport = light.hide_render, light.hide_viewport
        light.hide_render = light.hide_viewport = True


def _fit_model(context, collection):
    from . import scene_models
    source = scene_models.selected(context)
    objects = scene_models.meshes(source)
    if not objects:
        return
    tracked = scene_models.tracked(source, context.scene)
    original = {entry.object: entry.original_data for entry in tracked.hgt_character.meshes
                if entry.object and entry.original_data} if tracked else {}
    # A rendered bound box includes the outline shell; fit to the source body.
    points = [obj.matrix_world @ coordinate for obj in objects
              for coordinate in ([v.co for v in original[obj].vertices] if obj in original
                                 else [Vector(corner) for corner in obj.bound_box])]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    height = high.z - low.z
    if height < 1e-5:
        raise ValueError('模型高度无效，无法匹配城市露台尺寸')
    scale = height / collection['hgt_nominal_height']
    anchor = Vector(((low.x + high.x) * .5, (low.y + high.y) * .5, low.z))
    transform = Matrix.Translation(anchor) @ Matrix.Scale(scale, 4)
    members = set(collection.all_objects)
    for obj in members:
        if obj.parent not in members:
            obj.matrix_world = transform @ obj.matrix_world
        if obj.type == 'CAMERA':
            obj.data.ortho_scale *= scale
        elif obj.type == 'LIGHT' and obj.data.type == 'AREA':
            obj.data.energy *= scale * scale
            obj.data.size *= scale
    collection['hgt_model_scale'] = scale


def load(context, preset_id):
    rendering.check_idle()
    if context.mode != 'OBJECT':
        raise ValueError('请切换到对象模式后载入场景')
    preset = PRESETS.get(preset_id)
    if preset is None:
        raise ValueError('场景预设不存在')
    path = ASSETS / preset['file']
    if not path.is_file():
        raise ValueError('缺少场景资产：' + preset['name'])
    scene, state = context.scene, context.scene.hgt_scene
    if state.collection and state.preset == preset_id and state.collection in scene.collection.children_recursive:
        return state.collection
    before = asset_tracking.data_pointers()
    previous = {name: getattr(state, name) for name in state.bl_rna.properties.keys() if name != 'rna_type'}
    pointers = scene.world, scene.camera, scene.hgt_light
    visibility = {light: (light.hide_render, light.hide_viewport)
                  for light in (state.muted_light, scene.hgt_light) if light}
    old_collection, old_uid = state.collection, state.uid
    try:
        with bpy.data.libraries.load(str(path), link=False) as (source, target):
            if preset['collection'] not in source.collections:
                raise ValueError('场景资产缺少预设集合：' + preset['name'])
            target.collections = [preset['collection']]
        collection = target.collections[0]
        camera, light, world = (collection.get('hgt_scene_' + key) for key in ('camera', 'light', 'world'))
        if (collection.get('hgt_scene_asset') != preset_id or not isinstance(camera, bpy.types.Object)
                or camera.type != 'CAMERA' or camera.name not in collection.all_objects
                or not isinstance(light, bpy.types.Object) or light.type != 'LIGHT'
                or light.data.type not in {'SUN', 'AREA', 'POINT', 'SPOT'} or light.name not in collection.all_objects
                or not isinstance(world, bpy.types.World)):
            raise ValueError('场景资产的相机、主光或世界引用无效：' + preset['name'])
        uid = uuid4().hex
        for values in asset_tracking.new_data(before).values():
            for item in values:
                item[OWNER] = uid
        if not old_uid:
            state.previous_world, state.previous_camera, state.previous_light = pointers
        _mute_default_light(scene)
        scene.collection.children.link(collection)
        if preset.get('fit_model'):
            context.view_layer.update()
            _fit_model(context, collection)
        scene.world, scene.camera, scene.hgt_light = world, camera, light
        state.collection, state.uid, state.preset = collection, uid, preset_id
        state.world, state.camera, state.light = world, camera, light
    except Exception:
        for name, value in previous.items():
            setattr(state, name, value)
        scene.world, scene.camera, scene.hgt_light = pointers
        for light, flags in visibility.items():
            light.hide_render, light.hide_viewport = flags
        bpy.data.batch_remove(ids={item for values in asset_tracking.new_data(before).values() for item in values})
        raise
    if old_uid:
        _release(scene, old_collection, old_uid)
    return collection


def remove(context):
    rendering.check_idle()
    if context.mode != 'OBJECT':
        raise ValueError('请切换到对象模式后移除场景')
    scene, state = context.scene, context.scene.hgt_scene
    collection, uid = state.collection, state.uid
    if not uid:
        raise ValueError('当前没有载入的场景预设')
    for name in ('world', 'camera'):
        if getattr(scene, name) == getattr(state, name):
            setattr(scene, name, getattr(state, 'previous_' + name))
    if scene.hgt_light == state.light:
        scene.hgt_light = state.previous_light
    restore_default_light(scene)
    for name in state.bl_rna.properties.keys():
        if name != 'rna_type':
            state.property_unset(name)
    _release(scene, collection, uid)
