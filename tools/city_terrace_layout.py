"""Bend the exported terrace into a compact half ring; retain its materials."""
import math
import bmesh
import bpy
from mathutils import Matrix, Vector

PROJECTION = 'hgt_city_projection'


def _world_mesh(obj):
    obj.data = obj.data.copy()
    obj.data.transform(obj.matrix_world)
    obj.matrix_world = Matrix.Identity(4)
    return obj.data


def _subdivide(mesh, vertical=False):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    # Long horizontal edges need samples to describe a curve, including rails.
    edges = [e for e in bm.edges if abs(e.verts[1].co.x - e.verts[0].co.x) > 1
             or (vertical and abs(e.verts[1].co.z - e.verts[0].co.z) > 1)]
    if edges:
        bmesh.ops.subdivide_edges(bm, edges=edges, cuts=40, use_grid_fill=True)
    bm.to_mesh(mesh)
    bm.free()


def _projection(mesh, projector):
    values = [component for vertex in mesh.vertices for component in projector.matrix_world.inverted() @ vertex.co]
    attr = mesh.attributes.new(PROJECTION, 'FLOAT_VECTOR', 'POINT')
    attr.data.foreach_set('vector', values)
    for material in mesh.materials:
        if material is None or not material.use_nodes:
            continue
        tree = material.node_tree
        coordinate = next((n for n in tree.nodes if n.type == 'TEX_COORD' and n.object == projector), None)
        if coordinate is None:
            continue
        attribute = tree.nodes.get('HGT • Original Projection')
        if attribute is None:
            attribute = tree.nodes.new('ShaderNodeAttribute')
            attribute.name, attribute.attribute_name = 'HGT • Original Projection', PROJECTION
        for link in tuple(coordinate.outputs['Object'].links):
            tree.links.new(attribute.outputs['Vector'], link.to_socket)


def reshape(collection):
    if collection.get('hgt_city_layout'):
        raise ValueError('City terrace has already been reshaped')
    objects = list(collection.all_objects)
    projector = next(o for o in objects if o.name.startswith('REFERENCE_PROJECTOR'))
    for obj in objects:
        if obj.type != 'MESH':
            continue
        mesh = _world_mesh(obj)
        if obj.name.startswith('Canal /'):
            material = mesh.materials[0]
            # Replace the 120 x 148 m plane with water between rail and skyline.
            vertices, faces, original = [], [], []
            for row in range(9):
                radius = 2.16 + row / 8 * 1.2
                for col in range(97):
                    theta = (col / 96 - .5) * math.pi
                    vertices.append((radius * math.sin(theta), radius * math.cos(theta) - 1, -.174))
                    original.append(Vector(((col / 96 - .5) * 8.995674, 2.36 + row / 8 * 7.35, -.174)))
            for row in range(8):
                for col in range(96):
                    i = row * 97 + col
                    faces.append((i, i + 1, i + 98, i + 97))
            mesh.clear_geometry()
            mesh.from_pydata(vertices, [], faces)
            mesh.materials.clear()
            mesh.materials.append(material)
            attr = mesh.attributes.new(PROJECTION, 'FLOAT_VECTOR', 'POINT')
            inverse = projector.matrix_world.inverted()
            attr.data.foreach_set('vector', [v for point in original for v in inverse @ point])
            # Material remapping is shared with the skyline below.
            for mat in mesh.materials:
                tree = mat.node_tree
                coordinate = next(n for n in tree.nodes if n.type == 'TEX_COORD' and n.object == projector)
                attribute = tree.nodes.new('ShaderNodeAttribute')
                attribute.name, attribute.attribute_name = 'HGT • Original Projection', PROJECTION
                for link in tuple(coordinate.outputs['Object'].links):
                    tree.links.new(attribute.outputs['Vector'], link.to_socket)
        elif obj.name.startswith('Far only /'):
            _subdivide(mesh, vertical=True)
            _projection(mesh, projector)
            for vertex in mesh.vertices:
                x, y, z = vertex.co
                theta = x / 4.497837 * math.pi / 2
                radius = 3.36 + (y - 9.7) * .1
                # Keep the skyline at railing height while reducing the sky
                # overhead. Extend the lower image to meet the small water ring.
                height = (1.15 + (z - 1.15) * .35 if z >= 1.15
                          else -.2 + (z - .344877) / (1.15 - .344877) * 1.35)
                vertex.co = (radius * math.sin(theta), radius * math.cos(theta) - 1, height)
        else:
            _subdivide(mesh)
            for vertex in mesh.vertices:
                x, y, z = vertex.co
                theta = x / 3.125 * math.pi / 2
                radius = (y + 3.65) * (2 / 5.7)
                vertex.co = (radius * math.sin(theta), radius * math.cos(theta) - 1, z)
        mesh.update()
    camera = collection['hgt_scene_camera']
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = 2.35
    camera.location = (0, -4.4, 1.05)
    camera.rotation_euler = (Vector((0, 0, .85)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
    collection['hgt_city_layout'] = 'compact-half-ring-v1'
    collection['hgt_nominal_height'] = 1.7
