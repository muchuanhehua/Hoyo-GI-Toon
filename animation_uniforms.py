"""Evaluate animated shader directions in Blender's existing dependency pass."""
import bpy

_CACHE = {}
VECTOR_NAMES = ('hgt_head_forward', 'hgt_head_up', 'hgt_light_rotation')


def reset():
    _CACHE.clear()


def path(uid, name):
    return f'["hgt_{uid}_{name}"]'


def owned(curve):
    return bool(curve.driver.variables) and all(v.name in {'_hgt_a', '_hgt_b'} for v in curve.driver.variables)


def sync(root, scene, vectors):
    """Use native transforms for head vectors and Sun rotation; other lights keep their solver."""
    settings = root.hgt_character
    controls = {entry.key: entry.object for entry in settings.controls if entry.object}
    targets = {}
    if root.name in scene.objects and settings.head:
        for name, label in (('hgt_head_forward', 'Head Forward'), ('hgt_head_up', 'Head Up')):
            if controls.get(label):
                targets[name] = (controls[label], settings.head)
        light = settings.light_source
        if light and light.type == 'LIGHT' and light.data.type == 'SUN':
            targets['hgt_light_rotation'] = (light,)
    signature = tuple((name, tuple(obj.as_pointer() for obj in objects)) for name, objects in targets.items())
    key = scene.as_pointer(), settings.uid
    curves = scene.animation_data.drivers if scene.animation_data else ()
    if _CACHE.get(key) == (signature, len(curves)):
        return set(targets), False
    changed = False
    for name in VECTOR_NAMES:
        data_path = path(settings.uid, name)
        for axis in range(3):
            curve = curves.find(data_path, index=axis) if curves else None
            if curve and not owned(curve):
                raise ValueError('光向参数存在自定义驱动，请保留或移除该驱动后重新应用材质：' + name)
            if name not in targets:
                if curve:
                    scene.driver_remove(data_path, axis)
                    changed = True
                continue
            property_name = f'hgt_{settings.uid}_{name}'
            if property_name not in scene:
                scene[property_name] = (*vectors[name], 1)
            curve = curve or scene.driver_add(data_path, axis)
            driver = curve.driver
            driver.type = 'SCRIPTED'
            for variable in tuple(driver.variables):
                driver.variables.remove(variable)
            for index, obj in enumerate(targets[name]):
                variable = driver.variables.new()
                variable.name = '_hgt_a' if index == 0 else '_hgt_b'
                variable.type = 'TRANSFORMS'
                target = variable.targets[0]
                target.id = obj
                target.transform_space = 'WORLD_SPACE'
                target.transform_type = ('ROT_' if name == 'hgt_light_rotation' else 'LOC_') + 'XYZ'[axis]
                if name == 'hgt_light_rotation':
                    target.rotation_mode = 'XYZ'
            driver.expression = '_hgt_a - _hgt_b' if len(targets[name]) == 2 else '_hgt_a'
            changed = True
        curves = scene.animation_data.drivers if scene.animation_data else ()
    _CACHE[key] = signature, len(curves)
    return set(targets), changed


def previous_rotation(root, depsgraph):
    """Clearing a Sun freezes its last evaluated direction, not the old undriven value."""
    for scene in bpy.data.scenes:
        curves = scene.animation_data.drivers if scene.animation_data else None
        curve = curves.find(path(root.hgt_character.uid, 'hgt_light_rotation'), index=0) if curves else None
        if curve and owned(curve):
            source = curve.driver.variables[0].targets[0].id
            if source:
                return tuple(source.evaluated_get(depsgraph).matrix_world.to_quaternion().to_euler())
    return None


def freeze(root):
    """Retained materials keep the final uniforms after their render rig is removed."""
    from .lighting import shader_vectors
    vectors = shader_vectors(root)
    for scene in bpy.data.scenes:
        curves = scene.animation_data.drivers if scene.animation_data else ()
        changed = False
        for name, value in vectors.items():
            data_path = path(root.hgt_character.uid, name)
            for axis in range(3):
                curve = curves.find(data_path, index=axis) if curves else None
                if curve and owned(curve):
                    scene.driver_remove(data_path, axis)
                    changed = True
            if changed:
                scene[f'hgt_{root.hgt_character.uid}_{name}'] = (*value, 1)
        if changed:
            scene.update_tag(refresh={'TIME'})
    reset()
