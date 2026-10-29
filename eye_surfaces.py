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
    mask = mesh.attributes.new(OUTER_MASK, 'FLOAT', 'FACE')
    for index in outer:
        mask.data[index].value = 1
    mesh['hgt_eye_outer_faces'] = len(outer)
    mesh['hgt_eye_inner_faces'] = len(faces) - len(outer)
    return len(outer)
