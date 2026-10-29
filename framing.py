"""Frame evaluated visible surfaces without altering or duplicating source IDs."""
import json
import math
import bpy
from mathutils import Vector
from . import subjects


def points(root, face_only=False, body_only=False):
    subjects.apply(root)
    settings = root.hgt_character
    outlines = {binding.outline for binding in settings.bindings}
    faces = {binding.generated for binding in settings.bindings if binding.role in {'face', 'eye', 'brow'}}
    faces.update(material.get('hgt_eye_overlay') for material in tuple(faces) if material)
    probes = []
    result = []
    try:
        for entry in settings.meshes:
            obj = entry.object
            if not obj or not entry.render_data or obj.hide_render:
                continue
            body = {p.key for p in settings.parts if p.object == obj and p.role == 'BODY' and p.included}
            if body_only and settings.parts_version and not body:
                continue
            # Native lighting/outline graphs can return unrealized instances.
            # Query only posed base surfaces on a temporary object, retaining
            # visibility filters and every original deformation modifier.
            probe = obj.copy();probe.name = 'HGT Framing'
            for modifier in tuple(probe.modifiers):
                if modifier.type == 'NODES' and modifier.node_group and (
                        modifier.node_group in {settings.light_vectors, settings.outline_graph}
                        or modifier.node_group.get('hgt_pmx_outline')):
                    probe.modifiers.remove(modifier)
            bpy.context.scene.collection.objects.link(probe)
            probes.append((probe, body))
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        for obj, body in probes:
            evaluated = obj.evaluated_get(graph);mesh = evaluated.to_mesh()
            try:
                selected = {i for i, material in enumerate(mesh.materials)
                            if material not in outlines and (not face_only or material in faces)}
                part_ids = mesh.attributes.get(subjects.PART_ID)
                indices = {v for polygon in mesh.polygons if polygon.material_index in selected
                           and (not body_only or part_ids is None or part_ids.data[polygon.index].value in body)
                           for v in polygon.vertices}
                result.extend(obj.matrix_world @ mesh.vertices[i].co for i in indices)
            finally:
                evaluated.to_mesh_clear()
    finally:
        if probes:
            bpy.data.batch_remove(ids={obj for obj, _ in probes})
    return result


def bounds_of(values):
    if not values:
        raise ValueError('角色没有可用于构图的表面')
    low = Vector(tuple(min(p[i] for p in values) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in values) for i in range(3)))
    if high.z - low.z < 1e-5:
        raise ValueError('角色尺寸无效，请检查导入模型')
    return low, high


def bounds(root):
    return bounds_of(points(root))


def signature(camera):
    data = camera.data
    return [v for row in camera.matrix_world for v in row] + [data.ortho_scale, data.lens, data.shift_x, data.shift_y,
        ('PERSP', 'ORTHO', 'PANO', 'CUSTOM').index(data.type), data.sensor_width, data.sensor_height,
        ('AUTO', 'HORIZONTAL', 'VERTICAL').index(data.sensor_fit), data.clip_start, data.clip_end]


def is_auto(root):
    settings = root.hgt_character
    if not settings.auto_frame:
        return False
    if not settings.camera_signature:
        return True
    expected = json.loads(settings.camera_signature)
    current = signature(settings.camera)
    return len(expected) == len(current) and all(abs(a - b) < 1e-5 for a, b in zip(current, expected))


def frame(scene, root):
    camera = scene.hgt_output.camera
    settings = root.hgt_character
    if camera is None or camera != settings.camera:
        raise ValueError('请选择角色相机后重新构图；其他相机可直接渲染')
    bpy.context.view_layer.update()
    cloud = points(root, body_only=settings.shot == 'HEAD')
    low, high = bounds_of(cloud)
    full_height = high.z - low.z
    if settings.shot == 'HALF':
        cloud = [p for p in cloud if p.z >= low.z + full_height * .43]
    elif settings.shot == 'HEAD':
        face = points(root, face_only=True, body_only=True)
        bottom = bounds_of(face)[0].z if face else high.z - full_height * .24
        cloud = [p for p in cloud if p.z >= bottom - full_height * .015]
    low, high = bounds_of(cloud)
    center = (low + high) * .5
    a, e = settings.view_azimuth, settings.view_elevation
    direction = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
    rotation = (-direction).to_track_quat('-Z', 'Y')
    right, up = rotation @ Vector((1, 0, 0)), rotation @ Vector((0, 1, 0))
    xs, ys = [(p - center).dot(right) for p in cloud], [(p - center).dot(up) for p in cloud]
    center += right * ((min(xs) + max(xs)) * .5) + up * ((min(ys) + max(ys)) * .5)
    aspect = scene.hgt_output.width / scene.hgt_output.height
    camera.data.type = 'ORTHO'
    camera.data.sensor_fit = 'VERTICAL'
    camera.data.ortho_scale = max(max(ys) - min(ys), (max(xs) - min(xs)) / aspect) * (1 + settings.frame_margin)
    camera.data.clip_start = max(.001, full_height * .001)
    camera.data.clip_end = max(100, full_height * 10)
    camera.location = center + direction * full_height * 3
    camera.rotation_euler = rotation.to_euler()
    bpy.context.view_layer.update()
    settings.camera_signature = json.dumps(signature(camera))
    settings.auto_frame = True
