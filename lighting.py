"""Per-import light vectors and head references, without editing the rig."""
import math
import json
import bpy
from mathutils import Vector
from . import shaders


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
    bpy.context.view_layer.update()
    return controls


def attach(mesh, root, controls):
    graph = root.hgt_character.light_vectors
    existing = next((m for m in mesh.modifiers if m.type == "NODES" and m.node_group == graph), None)
    modifier = existing or mesh.modifiers.new("HGT • Light Vectors", "NODES")
    modifier.node_group = graph
    for name in ("Light Direction", "Head Origin", "Head Forward", "Head Up"):
        shaders.set_input(modifier, name, controls[name])
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


def update(root, depsgraph=None, scene=None):
    settings = root.hgt_character
    if settings.light and settings.light_source:
        source = settings.light_source
        if source.type != 'LIGHT' or source.data.type not in {'SUN', 'AREA', 'POINT', 'SPOT'}:
            raise ValueError('请选择太阳光、面光、点光或聚光')
        if scene and source.name not in scene.objects:
            raise ValueError('材质灯光不在当前场景中')
        depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
        if source.data.type == 'SUN':
            rotation = source.evaluated_get(depsgraph).matrix_world.to_quaternion().to_euler()
        else:
            rotation = light_direction(settings, depsgraph).to_track_quat('-Z', 'Y').to_euler()
        if any(abs(settings.light.rotation_euler[i] - rotation[i]) > 1e-6 for i in range(3)):
            settings.light.rotation_euler = rotation
    shaders.set_controls(root)


def default_light(scene):
    from .scene_presets import restore_default_light
    restore_default_light(scene)
    light = next((obj for obj in scene.objects if obj.get('hgt_scene_light') and obj.type == 'LIGHT'), None)
    if light is None:
        data = bpy.data.lights.new('HGT • 默认光', 'SUN')
        light = bpy.data.objects.new(data.name, data)
        light['hgt_scene_light'] = True
        scene.collection.objects.link(light)
    light.data.energy = 2
    direction = Vector((math.sin(.35)*math.cos(.35), -math.cos(.35)*math.cos(.35), math.sin(.35)))
    light.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.hgt_light = light
    bpy.context.view_layer.update()
    return light
