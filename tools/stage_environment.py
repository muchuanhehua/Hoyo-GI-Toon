"""Build the camera-free, inward-facing panoramic stage asset."""
import math
import random
import bpy
from mathutils import Vector

RADIUS = 10.0
WALL_TOP = 6.8
SEGMENTS = 256


def replace_mesh(obj, vertices, faces, uv=None):
    previous = obj.data
    mesh = bpy.data.meshes.new(previous.name + ' 360')
    mesh.from_pydata(vertices, [], faces)
    for material in previous.materials:
        mesh.materials.append(material)
    if uv:
        layer = mesh.uv_layers.new(name='UVMap')
        for polygon, values in zip(mesh.polygons, uv):
            for index, value in zip(polygon.loop_indices, values):
                layer.data[index].uv = value
    obj.data = mesh
    if previous.users == 0:
        bpy.data.meshes.remove(previous)
    return mesh


def panorama(scene):
    sky = scene.objects['STAGE__curved_sky_backdrop']
    rings = [(RADIUS, -.12), (RADIUS, WALL_TOP)]
    for step in range(1, 16):
        angle = step / 16 * math.pi / 2
        rings.append((RADIUS * math.cos(angle), WALL_TOP + RADIUS * math.sin(angle)))
    vertices = [(radius * math.cos(i * math.tau / SEGMENTS),
                 radius * math.sin(i * math.tau / SEGMENTS), z)
                for radius, z in rings for i in range(SEGMENTS)]
    vertices.append((0, 0, WALL_TOP + RADIUS))
    faces, uv = [], []
    for ring in range(len(rings) - 1):
        lower, upper = ring * SEGMENTS, (ring + 1) * SEGMENTS
        for i in range(SEGMENTS):
            j = (i + 1) % SEGMENTS
            faces.append((lower + i, upper + i, upper + j, lower + j))
            bottom, top = (min(1, max(0, rings[k][1] / WALL_TOP)) for k in (ring, ring + 1))
            uv.append(((i / SEGMENTS, bottom), (i / SEGMENTS, top),
                       ((i + 1) / SEGMENTS, top), ((i + 1) / SEGMENTS, bottom)))
    last = (len(rings) - 1) * SEGMENTS
    for i in range(SEGMENTS):
        faces.append((last + i, len(vertices) - 1, last + (i + 1) % SEGMENTS))
        uv.append(((i / SEGMENTS, 1), (.5, 1), ((i + 1) / SEGMENTS, 1)))
    replace_mesh(sky, vertices, faces, uv)
    sky.name = 'STAGE__panoramic_sky_360'
    material = sky.data.materials[0]
    material.use_backface_culling = True
    material.use_backface_culling_shadow = True
    # Circular colour variation uses Cartesian position, so the UV seam is invisible.
    tree = material.node_tree
    coordinates = next(n for n in tree.nodes if n.type == 'TEX_COORD')
    side = tree.nodes.new('ShaderNodeSeparateXYZ')
    tree.links.new(coordinates.outputs['Generated'], side.inputs['Vector'])
    blend_range = next(n for n in tree.nodes if n.type == 'MAP_RANGE')
    tree.links.new(side.outputs['X'], blend_range.inputs['Value'])
    return sky


def stars(scene):
    obj = scene.objects['STAGE__editable_star_quads']
    previous = obj.data
    rng = random.Random(360110)
    vertices, faces, uv, materials = [], [], [], []
    for polygon in previous.polygons:
        points = [previous.vertices[index].co.copy() for index in polygon.vertices]
        center = sum(points, Vector()) / len(points)
        old_tangent = Vector((-center.y, center.x, 0)).normalized()
        azimuth = rng.uniform(-math.pi, math.pi)
        if rng.random() < .18:
            elevation = rng.uniform(.08, math.pi / 2 - .03)
            radius = (RADIUS - .015) * math.cos(elevation)
            z = WALL_TOP + (RADIUS - .015) * math.sin(elevation)
            vertical = Vector((-math.sin(elevation) * math.cos(azimuth),
                               -math.sin(elevation) * math.sin(azimuth), math.cos(elevation)))
        else:
            radius, z = RADIUS - .015, rng.uniform(.025, WALL_TOP)
            vertical = Vector((0, 0, 1))
        tangent = Vector((-math.sin(azimuth), math.cos(azimuth), 0))
        target = Vector((radius * math.cos(azimuth), radius * math.sin(azimuth), z))
        scale = RADIUS / 3.7
        positions = [target + tangent * ((p - center).dot(old_tangent) * scale)
                     + vertical * ((p.z - center.z) * scale) for p in points]
        indices = list(range(len(vertices), len(vertices) + len(points)))
        coords = [tuple(previous.uv_layers.active.data[i].uv) for i in polygon.loop_indices]
        normal = (positions[1] - positions[0]).cross(positions[2] - positions[0])
        inward = Vector((-target.x, -target.y, -(target.z - WALL_TOP) if target.z > WALL_TOP else 0))
        if normal.dot(inward) < 0:
            indices.reverse(); coords.reverse()
        vertices.extend(positions); faces.append(indices); uv.append(coords); materials.append(polygon.material_index)
    mesh = replace_mesh(obj, vertices, faces, uv)
    for polygon, material in zip(mesh.polygons, materials):
        polygon.material_index = material
    for material in mesh.materials:
        material.use_backface_culling = True
    obj.name = 'STAGE__panoramic_stars'


def surround_floor(scene, collection):
    floor = scene.objects['STAGE__circular_platform']
    vertices = [(radius * math.cos(i * math.tau / SEGMENTS),
                 radius * math.sin(i * math.tau / SEGMENTS), -.081)
                for radius in (3.39, RADIUS) for i in range(SEGMENTS)]
    faces = [(i, SEGMENTS + i, SEGMENTS + (i + 1) % SEGMENTS, (i + 1) % SEGMENTS)
             for i in range(SEGMENTS)]
    mesh = bpy.data.meshes.new('STAGE__surround_floor')
    mesh.from_pydata(vertices, [], faces)
    for material in floor.data.materials:
        mesh.materials.append(material)
    obj = bpy.data.objects.new('STAGE__surround_floor', mesh)
    collection.objects.link(obj)


def build(scene, collection):
    panorama(scene)
    stars(scene)
    surround_floor(scene, collection)
    glints = scene.objects['STAGE__four_point_star_glints']
    # Keep the authored glints as a feature on the distant wall, away from the camera path.
    for vertex in glints.data.vertices:
        vertex.co.x *= RADIUS / 3.7
        vertex.co.y *= RADIUS / 3.7
        vertex.co.z *= WALL_TOP / 4.2
    for material in glints.data.materials:
        material.use_backface_culling = True
    collection['hgt_stage_radius'] = RADIUS
    collection['hgt_stage_coverage_degrees'] = 360
