"""Control existing derived shape keys and reversible eye constraints."""
import math
import re
import bpy
from mathutils import Quaternion

LABELS = {'まばたき': '眨眼', '笑い': '笑眼', 'ウィンク': '左眨眼', 'ウィンク右': '右眨眼',
          'あ': '口型 A', 'い': '口型 I', 'う': '口型 U', 'え': '口型 E', 'お': '口型 O',
          'Eye_WinkA_L': '左眨眼', 'Eye_WinkA_R': '右眨眼', 'Mouth_Smile01': '微笑'}


def initialize(root):
    settings = root.hgt_character
    if settings.expressions_version:
        return
    previous = settings.building;settings.building = True
    try:
        mapping = {}
        for entry in settings.meshes:
            mesh = entry.render_data
            if not mesh or not mesh.shape_keys:
                continue
            keys = mesh.shape_keys
            drivers = keys.animation_data.drivers if keys.animation_data else []
            for key in keys.key_blocks:
                if key == keys.reference_key or key.name.startswith(('mmd_', '_')) or key.name.endswith('_Default'):
                    continue
                if key.name not in mapping:
                    item = settings.expressions.add();item.name = key.name
                    item.label = LABELS.get(key.name, key.name);item.value = key.value
                    mapping[key.name] = item
                target = mapping[key.name].targets.add()
                target.object, target.key, target.original_value = entry.object, key.name, key.value
                curve = next((d for d in drivers if d.data_path == key.path_from_id('value')), None)
                target.driver_muted = curve.mute if curve else False
        settings.expressions_version = 1
    finally:
        settings.building = previous


def set_value(item):
    root = item.id_data
    if root.hgt_character.building:
        return
    item.touched = True
    root.hgt_character.has_expression_edits = True
    apply_values(root)


def apply_values(root):
    if not root.hgt_character.has_expression_edits:
        return
    for item in root.hgt_character.expressions:
        if not item.touched:
            continue
        for target in item.targets:
            keys = target.object.data.shape_keys if target.object else None
            key = keys.key_blocks.get(target.key) if keys else None
            if key is None:
                raise ValueError('表情引用已改变，请恢复后重新导入模型')
            if keys.animation_data:
                for driver in keys.animation_data.drivers:
                    if driver.data_path == key.path_from_id('value') and not driver.mute:
                        driver.mute = True
            value = max(key.slider_min, min(key.slider_max, item.value))
            if abs(key.value - value) > 1e-6:
                key.value = value


def eye_bones(root):
    settings = root.hgt_character;armature = settings.source_armature
    if armature is None:
        return []
    if settings.source_format == 'pmx':
        aliases = {'左目', '右目', '左眼', '右眼', 'eye_l', 'eye_r', 'left eye', 'right eye'}
        values = [bone for bone in armature.pose.bones if not bone.name.startswith('_')
                  and any(name.strip().casefold() in aliases for name in
                          (bone.name, getattr(getattr(bone, 'mmd_bone', None), 'name_j', ''),
                           getattr(getattr(bone, 'mmd_bone', None), 'name_e', '')))]
    else:
        values = [bone for bone in armature.pose.bones if 'eyebone' in bone.name.casefold()
                  or re.sub(r'[^a-z]', '', bone.name.casefold()) in {'eyel', 'eyer', 'lefteye', 'righteye'}]
        values = [bone for bone in values if not any(parent in values for parent in bone.parent_recursive)]
    return values if len(values) == 2 else []


def constraint_name(root):
    return 'HGT Look ' + root.hgt_character.uid


def clear_gaze(root):
    settings = root.hgt_character;armature = settings.source_armature
    for item in settings.gaze_bones:
        bone = armature.pose.bones.get(item.bone) if armature else None
        constraint = bone.constraints.get(constraint_name(root)) if bone else None
        if constraint and constraint.type == 'COPY_ROTATION' and constraint.target == item.helper:
            bone.constraints.remove(constraint)
            bone.constraints.active = bone.constraints.get(item.active_constraint)
        if item.helper and item.helper.users <= 1:
            bpy.data.objects.remove(item.helper, do_unlink=True)
    settings.gaze_bones.clear()
    settings.look_camera = False


def set_gaze(root, scene, enabled):
    if not enabled:
        clear_gaze(root)
        return
    bones = eye_bones(root)
    if not bones:
        raise ValueError('模型没有可识别的一对眼部骨骼')
    settings = root.hgt_character
    if settings.look_camera:
        return
    try:
        for bone in bones:
            helper = bpy.data.objects.new('HGT • Eye Look', None)
            helper['hgt_owner'], helper['hgt_helper'] = settings.uid, True
            helper.hide_render = True;helper.rotation_mode = 'QUATERNION'
            root.users_collection[0].objects.link(helper);helper.hide_set(True)
            item = settings.gaze_bones.add();item.bone, item.helper = bone.name, helper
            item.active_constraint = bone.constraints.active.name if bone.constraints.active else ''
            constraint = bone.constraints.new('COPY_ROTATION')
            constraint.name = constraint_name(root);constraint.target = helper
            constraint.owner_space = constraint.target_space = 'WORLD'
            constraint.mix_mode = 'REPLACE'
        settings.look_camera = True
        update_gaze(root, scene)
    except Exception:
        clear_gaze(root)
        raise


def update_gaze(root, scene):
    settings = root.hgt_character
    if not settings.look_camera:
        return
    camera = scene.hgt_output.camera or settings.camera
    head_constraint = settings.head.constraints.get('Child Of') if settings.head else None
    armature = settings.source_armature
    if camera is None or head_constraint is None or armature is None:
        raise ValueError('视线缺少相机或头部参照')
    head = armature.pose.bones.get(head_constraint.subtarget)
    controls = {item.key: item.object for item in settings.controls}
    forward = (controls['Head Forward'].matrix_world.translation - settings.head.matrix_world.translation).normalized()
    transform = armature.matrix_world @ head.matrix @ head.bone.matrix_local.inverted()
    for item in settings.gaze_bones:
        bone = armature.pose.bones.get(item.bone)
        if bone is None or item.helper is None:
            raise ValueError('视线引用已改变，请关闭视线后重新启用')
        base = transform @ bone.bone.matrix_local
        direction = camera.matrix_world.translation - base.translation
        if direction.length < 1e-6:
            raise ValueError('相机与眼部重合，请调整机位')
        delta = forward.rotation_difference(direction.normalized())
        delta = Quaternion().slerp(delta, min(1, math.radians(30) / max(delta.angle, 1e-6)))
        rotation = delta @ base.to_quaternion()
        if abs(item.helper.rotation_quaternion.dot(rotation)) < 1 - 1e-8:
            item.helper.rotation_quaternion = rotation


def reset(root):
    settings = root.hgt_character;previous = settings.building;settings.building = True
    try:
        clear_gaze(root)
        for item in settings.expressions:
            if item.touched:
                for target in item.targets:
                    keys = target.object.data.shape_keys if target.object else None
                    key = keys.key_blocks.get(target.key) if keys else None
                    if key:
                        key.value = target.original_value
                        if keys.animation_data:
                            for curve in keys.animation_data.drivers:
                                if curve.data_path == key.path_from_id('value'):
                                    curve.mute = target.driver_muted
                item.value = item.targets[0].original_value
                item.touched = False
        settings.has_expression_edits = False
    finally:
        settings.building = previous
