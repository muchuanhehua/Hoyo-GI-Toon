"""Per-import light vectors and head references, without editing the rig."""
import math
import bpy
from mathutils import Vector
from . import shaders


def light_direction(settings):
    a, e = settings.light_azimuth, settings.light_elevation
    return Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))


def build(root, collection, imported, library):
    heads = [(obj, bone) for obj in imported if obj.type == "ARMATURE"
             for bone in obj.pose.bones if bone.name.casefold().split()[-1] == "head"]
    if len(heads) != 1:
        raise ValueError("无法确定角色头骨，请保留唯一的 Head 骨骼名称")
    armature, bone = heads[0]
    controls = library.controls(collection)
    head = controls["Head Origin"]
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


def update(root):
    settings = root.hgt_character
    if settings.light:
        rotation = light_direction(settings).to_track_quat("-Z", "Y").to_euler()
        if any(abs(settings.light.rotation_euler[i] - rotation[i]) > 1e-6 for i in range(3)):
            settings.light.rotation_euler = rotation
    shaders.set_controls(root)
