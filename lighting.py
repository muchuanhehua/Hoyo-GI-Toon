"""Per-import light vectors and head references, without editing the rig."""
import math
import json
import bpy
from mathutils import Vector
from . import shaders, scene_models

UNIFORM_VERSION = 1


def light_direction(settings, depsgraph=None):
    source = settings.light_source or settings.light
    if source is None:
        raise ValueError('请先选择灯光')
    depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
    matrix = source.evaluated_get(depsgraph).matrix_world
    if source.data.type == 'SUN':
        return matrix.to_quaternion() @ Vector((0, 0, -1))
    head = settings.head.evaluated_get(depsgraph).matrix_world.translation
    ray = head - matrix.translation
    if ray.length < 1e-6:
        raise ValueError('灯光与头部参考重合，无法确定材质光向')
    return ray.normalized()


def build(root, collection, imported, library):
    settings = root.hgt_character
    from .head_binding import select
    armature, bone, evidence = select(settings)
    settings.source_armature = armature
    if settings.source_root is None:
        original_root = armature
        while original_root.parent in imported:
            original_root = original_root.parent
        settings.source_root = original_root
    controls = library.controls(collection)
    head = controls["Head Origin"]
    head['hgt_head_binding'] = json.dumps(evidence, ensure_ascii=False)
    constraint = head.constraints.get("Child Of")
    if constraint is None:
        raise ValueError("头部参照缺少 Child Of 约束")
    constraint.target, constraint.subtarget = armature, bone.name
    bpy.context.view_layer.update()
    with bpy.context.temp_override(object=head, active_object=head):
        result = bpy.ops.constraint.childof_set_inverse(constraint=constraint.name, owner="OBJECT")
    if result != {"FINISHED"}:
        raise RuntimeError("无法设置头部参照的初始变换")
    settings = root.hgt_character
    settings.light, settings.head = controls["Light Direction"], head
    settings.lighting_version = UNIFORM_VERSION
    bpy.context.view_layer.update()
    return controls


def attach(mesh, root, controls):
    graph = root.hgt_character.light_vectors
    existing = next((m for m in mesh.modifiers if m.type == "NODES" and m.node_group == graph), None)
    modifier = existing or mesh.modifiers.new("HGT • Light Vectors", "NODES")
    modifier.node_group = graph
    # The source node still supplies constant colour/rim attributes. Light
    # rotation is a shader uniform, so it cannot invalidate outline geometry.
    for name in ("Head Origin", "Head Forward", "Head Up"):
        shaders.set_input(modifier, name, controls[name])
    shaders.set_input(modifier, 'Light Direction', None)
    for name, key in (("Ambient", "Ambient"), ("Lit", "Lit"), ("Shadow", "Shadow"),
                      ("Rim Lit", "RimLit"), ("Fresnel", "Fresnel"), ("Soft Lit", "SoftLit"),
                      ("Soft Shadow", "SoftShadow"), ("Rim Shadow", "RimShadow")):
        shaders.set_input(modifier, name + " Color Wheel", controls["ColorWheel-" + key])
        shaders.set_input(modifier, name + " Color Picker", controls["ColorPicker-" + key])
    for axis in ("X", "Y"):
        shaders.set_input(modifier, f"Rim {axis} Size Origin", controls[f"Origin-Rim{axis}"])
        shaders.set_input(modifier, f"Rim {axis} Size Slider", controls[f"Slider-Rim{axis}"])
    for socket in graph.interface.items_tree:
        if socket.item_type == "SOCKET" and socket.in_out == "OUTPUT" and socket.name != "Geometry":
            getattr(modifier.properties.outputs, socket.identifier).attribute_name = socket.default_attribute_name
    return modifier


def shader_vectors(root, depsgraph=None):
    """Match the original Object Info rotation and head-position differences."""
    settings = root.hgt_character
    if not settings.head or not settings.light:
        return {}
    depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
    if settings.light_source:
        source = settings.light_source
        if source.type != 'LIGHT' or source.data.type not in {'SUN', 'AREA', 'POINT', 'SPOT'}:
            raise ValueError('请选择太阳光、面光、点光或聚光')
        if source.data.type == 'SUN':
            rotation = source.evaluated_get(depsgraph).matrix_world.to_quaternion().to_euler()
        else:
            rotation = light_direction(settings, depsgraph).to_track_quat('-Z', 'Y').to_euler()
        # Object Info reads a matrix decomposed back to Euler, rather than
        # the uncanonicalized RNA Euler values previously assigned to a helper.
        rotation = rotation.to_matrix().to_euler()
    else:
        from .animation_uniforms import previous_rotation
        key = f'hgt_{settings.uid}_hgt_light_rotation'
        previous = previous_rotation(root, depsgraph)
        if previous is None:
            previous = next((scene[key] for scene in bpy.data.scenes if key in scene), None)
        # Clearing a light freezes the last direction, as the old helper did.
        rotation = previous[:3] if previous is not None else settings.light.evaluated_get(depsgraph).matrix_world.to_euler()
    controls = {entry.key: entry.object for entry in settings.controls if entry.object}
    if not all(controls.get(key) for key in ('Head Forward', 'Head Up')):
        raise ValueError('角色缺少头部光向参照，请恢复原材质后重新应用')
    origin = settings.head.evaluated_get(depsgraph).matrix_world.translation
    vectors = {'hgt_light_rotation': tuple(rotation)}
    for name, key in (('Head Forward', 'hgt_head_forward'), ('Head Up', 'hgt_head_up')):
        vectors[key] = tuple(controls[name].evaluated_get(depsgraph).matrix_world.translation - origin)
    return vectors


def upgrade(root):
    settings = root.hgt_character
    if settings.lighting_version == UNIFORM_VERSION:
        return
    trees = [tree for tree in bpy.data.node_groups if tree.get('hgt_owner') == settings.uid]
    trees.extend(m.node_tree for m in bpy.data.materials if m.get('hgt_owner') == settings.uid and m.node_tree)
    shaders.bind_light_uniforms(trees, settings.uid)
    for entry in settings.meshes:
        if not entry.object:
            continue
        for modifier in entry.object.modifiers:
            if modifier.type == 'NODES' and modifier.node_group == settings.light_vectors:
                shaders.set_input(modifier, 'Light Direction', None)
    settings.lighting_version = UNIFORM_VERSION


def update(root, depsgraph=None, scene=None):
    source = root.hgt_character.light_source
    if source and scene and not scene_models.in_scene(source, scene):
        raise ValueError('材质灯光不在当前场景中')
    shaders.set_controls(root, shader_vectors(root, depsgraph))


PRESETS = {
    'DEFAULT': ('默认光', 2.0, (1, 1, 1), .35, .35, .1),
    'SOFT': ('柔和正面', 1.5, (1, .96, .92), .05, .25, .45),
    'SIDE': ('侧面塑形', 2.5, (1, .91, .8), 1.15, .5, .12),
    'BACK': ('背光轮廓', 2.8, (.82, .9, 1), 2.75, .4, .18),
}


def active_parameters(scene):
    state = scene.hgt_lighting
    return next((item for item in state.presets if item.key == state.active), None)


def select_light(scene):
    for light in scene.objects:
        if (light.get('hgt_scene_light') and light.type == 'LIGHT' and light != scene.hgt_light
                and tuple(light.users_scene) == (scene,)):
            light.hide_render = light.hide_viewport = True


def update_parameters(scene, parameters):
    light = scene.hgt_light
    if (scene.hgt_lighting.active != parameters.key or light is None
            or not light.get('hgt_scene_light') or light.type != 'LIGHT'
            or tuple(light.users_scene) != (scene,)):
        return
    if abs(light.data.energy - parameters.energy) > 1e-6:
        light.data.energy = parameters.energy
    if any(abs(a - b) > 1e-6 for a, b in zip(light.data.color, parameters.color)):
        light.data.color = parameters.color
    if abs(light.data.angle - parameters.angle) > 1e-6:
        light.data.angle = parameters.angle
    azimuth, elevation = parameters.azimuth, parameters.elevation
    direction = Vector((math.sin(azimuth) * math.cos(elevation),
                        -math.cos(azimuth) * math.cos(elevation), math.sin(elevation)))
    rotation = direction.to_track_quat('-Z', 'Y').to_euler()
    if any(abs(a - b) > 1e-6 for a, b in zip(light.rotation_euler, rotation)):
        light.rotation_euler = rotation


def apply_preset(scene, key):
    if key not in PRESETS:
        raise ValueError('打光预设不存在')
    from .scene_presets import restore_default_light
    restore_default_light(scene, force=True)
    state = scene.hgt_lighting
    parameters = next((item for item in state.presets if item.key == key), None)
    if parameters is None:
        parameters = state.presets.add()
        parameters.key = key
        name, parameters.energy, parameters.color, parameters.azimuth, parameters.elevation, parameters.angle = PRESETS[key]
    light = next((obj for obj in scene.objects if obj.get('hgt_scene_light') and obj.type == 'LIGHT'
                  and tuple(obj.users_scene) == (scene,) and obj.data.users == 1), None)
    if light is None:
        data = bpy.data.lights.new('HGT • 默认光', 'SUN')
        light = bpy.data.objects.new(data.name, data)
        light['hgt_scene_light'] = True
        scene.collection.objects.link(light)
    state.active = key
    state.selected = key
    light.name = 'HGT • ' + PRESETS[key][0]
    light.hide_render = light.hide_viewport = False
    scene.hgt_light = light
    update_parameters(scene, parameters)
    bpy.context.view_layer.update()
    return light


def default_light(scene):
    return apply_preset(scene, 'DEFAULT')
