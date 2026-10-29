"""Classify layered eye surfaces from connected geometry, never character IDs."""
from collections import defaultdict
from mathutils import Vector

OUTER_MASK = 'hgt_eye_outer'


def mark(entry, slot_index):
    mesh = entry.render_data
    faces = [p for p in mesh.polygons if p.material_index == slot_index]
    by_vertex = defaultdict(list)
    for face in faces:
        for vertex in face.vertices:
            by_vertex[vertex].append(face.index)
    remaining = {face.index for face in faces}
    islands = []
    while remaining:
        todo = [remaining.pop()]
        indices = []
        while todo:
            index = todo.pop()
            indices.append(index)
            for vertex in mesh.polygons[index].vertices:
                for neighbor in by_vertex[vertex]:
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        todo.append(neighbor)
        vertices = {v for index in indices for v in mesh.polygons[index].vertices}
        center = sum((mesh.vertices[v].co for v in vertices), Vector()) / len(vertices)
        islands.append((indices, center))
    if len(islands) < 4:
        raise ValueError(f'{entry.object.name} 的分层眼部缺少可区分的内外表面')
    normal = sum((face.normal * face.area for face in faces), Vector())
    if normal.length < 1e-8:
        raise ValueError(f'{entry.object.name} 的眼部朝向无法确定')
    normal.normalize()
    spans = [max(c[axis] for _, c in islands) - min(c[axis] for _, c in islands) for axis in range(3)]
    lateral = max(range(3), key=lambda axis: spans[axis])
    split = (max(c[lateral] for _, c in islands) + min(c[lateral] for _, c in islands)) * .5
    outer = set()
    for side in (False, True):
        parts = [part for part in islands if (part[1][lateral] >= split) == side]
        if len(parts) < 2:
            raise ValueError(f'{entry.object.name} 的单眼内外表面不足')
        ranked = sorted(parts, key=lambda part: part[1].dot(normal), reverse=True)
        if ranked[0][1].dot(normal) - ranked[1][1].dot(normal) < max(spans) * 1e-5:
            raise ValueError(f'{entry.object.name} 的眼部表面深度存在歧义')
        outer.update(ranked[0][0])
    mask = mesh.attributes.get(OUTER_MASK)
    if mask is None:
        mask = mesh.attributes.new(OUTER_MASK, 'FLOAT', 'FACE')
    elif mask.data_type != 'FLOAT' or mask.domain != 'FACE':
        raise ValueError(f'{entry.object.name} 的眼部分层属性类型不正确')
    for index in outer:
        mask.data[index].value = 1
    mesh['hgt_eye_outer_faces'] = len(outer)
    mesh['hgt_eye_inner_faces'] = len(faces) - len(outer)
    return len(outer)


def attach(entry, material):
    """Route clear highlights in evaluated geometry, preserving source slots."""
    import bpy
    overlay = material.get('hgt_eye_overlay')
    if overlay is None:
        raise ValueError('分层眼材质缺少独立高光分支')
    owner = material['hgt_owner']
    graph = next((m.node_group for m in entry.object.modifiers if m.type == 'NODES'
                  and m.node_group and m.node_group.get('hgt_eye_surfaces')), None)
    if graph is None:
        graph = bpy.data.node_groups.new('HGT • Eye Surfaces', 'GeometryNodeTree')
        graph['hgt_owner'], graph['hgt_eye_surfaces'] = owner, True
        graph.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
        graph.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
        start = graph.nodes.new('NodeGroupInput')
        end = graph.nodes.new('NodeGroupOutput')
        graph.links.new(start.outputs['Geometry'], end.inputs['Geometry'])
        modifier = entry.object.modifiers.new('HGT • Eye Surfaces', 'NODES')
        modifier.node_group = graph
    end = next(n for n in graph.nodes if n.type == 'GROUP_OUTPUT')
    source = end.inputs['Geometry'].links[0].from_socket
    marker = graph.nodes.new('GeometryNodeInputNamedAttribute');marker.data_type = 'FLOAT'
    marker.inputs['Name'].default_value = OUTER_MASK
    selection = graph.nodes.new('GeometryNodeMaterialSelection')
    selection.inputs['Material'].default_value = material
    both = graph.nodes.new('FunctionNodeBooleanMath');both.operation = 'AND'
    graph.links.new(marker.outputs['Attribute'], both.inputs[0])
    graph.links.new(selection.outputs['Selection'], both.inputs[1])
    assign = graph.nodes.new('GeometryNodeSetMaterial')
    assign.inputs['Material'].default_value = overlay
    graph.links.new(source, assign.inputs['Geometry'])
    graph.links.new(both.outputs[0], assign.inputs['Selection'])
    graph.links.new(assign.outputs['Geometry'], end.inputs['Geometry'])
