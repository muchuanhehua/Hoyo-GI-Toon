"""MAVR-inspired head confidence checks around the native HGT reference."""
import unicodedata
from mathutils import Vector
from .face_assets import skin_material

HEAD_NAMES = {'head', '頭', '头', 'あたま', 'atama', 'headbone', 'bip01 head',
              'def-head', 'def_head', 'bone_head', 'sk_head', 'hed', 'head_m', 'b_head'}


def _is_head(bone):
    names = (bone.name, bone.mmd_bone.name_j, bone.mmd_bone.name_e)
    return any(unicodedata.normalize('NFKC', name).strip().casefold().rsplit(':', 1)[-1]
               in HEAD_NAMES for name in names if name)


def select(settings):
    armature = settings.source_armature
    if armature is None or abs(armature.matrix_world.determinant()) < 1e-10:
        raise ValueError('角色缺少有效骨架')
    heads = [bone for bone in armature.pose.bones if _is_head(bone)]
    if not heads:
        raise ValueError('无法识别头骨，请检查 Head / 頭 骨骼名称')
    weights, positions = {}, []
    for entry in settings.meshes:
        mesh = entry.object
        slots = {i for i, slot in enumerate(mesh.material_slots)
                 if slot.material and skin_material(slot.material)}
        indices = {i for polygon in mesh.data.polygons if polygon.material_index in slots for i in polygon.vertices}
        transform = armature.matrix_world.inverted() @ mesh.matrix_world
        groups = {group.index: group.name for group in mesh.vertex_groups}
        for index in indices:
            vertex = mesh.data.vertices[index]
            positions.append(transform @ vertex.co)
            for assignment in vertex.groups:
                name = groups.get(assignment.group)
                if name in armature.data.bones and assignment.weight > 1e-6:
                    weights[name] = weights.get(name, 0.0) + assignment.weight
    if not positions:
        if len(heads) != 1:
            raise ValueError('没有主脸数据且头骨不唯一，无法绑定')
        chosen, confidence = heads[0], None
    else:
        total = sum(weights.values())
        ranked = []
        for bone in heads:
            descendants = {bone.name, *(child.name for child in bone.children_recursive)}
            ranked.append((sum(w for name, w in weights.items() if name in descendants), bone))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if total < 1e-6 or ranked[0][0] / total < .8:
            raise ValueError('主脸权重无法明确关联头骨，请检查模型绑定')
        if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < total * .1:
            raise ValueError('存在相近的头骨候选，请检查模型绑定')
        chosen, confidence = ranked[0][1], ranked[0][0] / total
    up = chosen.bone.tail_local - chosen.bone.head_local
    if up.length < 1e-6:
        raise ValueError('头骨长度为零，无法建立方向')
    if positions:
        center = sum(positions, Vector()) / len(positions)
        front = center - chosen.bone.head_local
        front -= up.normalized() * front.dot(up.normalized())
        if front.length < 1e-6:
            raise ValueError('主脸中心与头骨重合，无法确认脸部方向')
    return armature, chosen, {'bone': chosen.name, 'face_weight_confidence': confidence,
                              'face_vertices': len(positions), 'reference': 'native-festivity'}
