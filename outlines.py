"""Material-aware PMX outlines on derived geometry."""

import json
import bpy
from mathutils import Vector

from .shaders import input_value
from .pmx_materials import is_inner_surface, visible_source_edge
from . import outline_profile

PAIRS = ("Hair", "Body", "Face", "Dress", "Dress 2", "Other")
GRAPH_VERSION = 5


def eligible(binding):
    if not binding.generated:
        return False
    pmx = json.loads(binding.generated['hgt_pmx'])
    if binding.role in {'eye', 'brow', 'expression'} or pmx['alpha'] <= 0 or pmx['overlay']:
        return False
    # An exposed undershirt can have intentional source edges. Only the new
    # fallback shell is suppressed by the lining semantics.
    return not (binding.source and not visible_source_edge(pmx) and is_inner_surface(binding.source))


def surface_mask(mesh, bindings):
    """Reject coincident reversed sheets, independently of material names."""
    data = mesh.data
    info = {b.generated: json.loads(b.generated['hgt_pmx']) for b in bindings if b.generated}
    materials = [info.get(material) for material in data.materials]
    valid = {i for i, pmx in enumerate(materials) if pmx and pmx['alpha'] > 0 and not pmx['overlay']}
    fallback = {i for i in valid if not materials[i]['double_sided'] and not visible_source_edge(materials[i])}
    allowed = [True] * len(data.polygons)
    if not fallback or not data.polygons:
        return allowed
    low = [min(v.co[i] for v in data.vertices) for i in range(3)]
    high = [max(v.co[i] for v in data.vertices) for i in range(3)]
    tolerance = max(max(b - a for a, b in zip(low, high)) * 1e-6, 1e-8)
    positions = [tuple(round(c / tolerance) for c in v.co) for v in data.vertices]
    data.calc_loop_triangles()
    coincident = {}
    for triangle in data.loop_triangles:
        index = triangle.material_index
        if index not in valid:
            continue
        key = tuple(sorted(positions[i] for i in triangle.vertices))
        previous = coincident.setdefault(key, [])
        normal = triangle.normal.copy()
        for other_face, other_index, other_normal in previous:
            if normal.dot(other_normal) > -.999:
                continue
            if index in fallback:
                allowed[triangle.polygon_index] = False
            if other_index in fallback:
                allowed[other_face] = False
        previous.append((triangle.polygon_index, index, normal))
    return allowed


def record_surface_mask(mesh, root):
    # Face membership survives skinning and vertex Morphs. Keep the mask on
    # the owned derived mesh, preserving the imported geometry and normals.
    attribute = mesh.data.attributes.get('hgt_outline_surface')
    if attribute is None:
        attribute = mesh.data.attributes.new('hgt_outline_surface', 'BOOLEAN', 'FACE')
    if attribute.data_type != 'BOOLEAN' or attribute.domain != 'FACE':
        raise ValueError('派生网格的描边面属性类型不正确，请恢复后重新应用材质')
    attribute.data.foreach_set('value', surface_mask(mesh, root.hgt_character.bindings))


def profile(mesh, root):
    """Keep rest-height on the derived mesh, so the taper follows skinning."""
    attribute = mesh.data.attributes.get('hgt_outline_height')
    if attribute is not None:
        if attribute.data_type != 'FLOAT' or attribute.domain != 'POINT':
            raise ValueError('派生网格的描边高度属性类型不正确，请恢复后重新应用材质')
        return
    settings = root.hgt_character
    inverse = settings.source_root.matrix_world.inverted_safe()
    points = [inverse @ entry.object.matrix_world @ Vector(corner)
              for entry in settings.meshes if entry.object for corner in entry.object.bound_box]
    low, high = min(p.z for p in points), max(p.z for p in points)
    transform = inverse @ mesh.matrix_world
    attribute = mesh.data.attributes.new('hgt_outline_height', 'FLOAT', 'POINT')
    attribute.data.foreach_set('value', [min(1, max(0, ((transform @ v.co).z - low) / max(high - low, 1e-6)))
                                        for v in mesh.data.vertices])

def build(mesh, root):
    """Repeat the upstream six-material outline branch, joining the base once."""
    settings = root.hgt_character
    by_weight = {}
    for binding in settings.bindings:
        material = binding.generated
        if material not in mesh.data.materials[:]:
            continue
        pmx = json.loads(material['hgt_pmx'])
        if not eligible(binding):
            continue
        weight = pmx['edge_weight'] if pmx['edge'] and pmx['edge_weight'] > 0 else 1.0
        by_weight.setdefault(weight, []).append((material, binding.outline))
    if not by_weight:
        return None
    graph = bpy.data.node_groups.new(f'HGT • {mesh.name} • PMX Outlines', 'GeometryNodeTree')
    graph['hgt_owner'], graph['hgt_pmx_outline'] = settings.uid, True
    graph['hgt_outline_version'] = GRAPH_VERSION
    for name, direction, kind in [('Geometry', 'INPUT', 'NodeSocketGeometry'),
                                  ('Outline Thickness', 'INPUT', 'NodeSocketFloat'),
                                  ('Geometry', 'OUTPUT', 'NodeSocketGeometry')]:
        graph.interface.new_socket(name=name, in_out=direction, socket_type=kind)
    source = graph.nodes.new('NodeGroupInput')
    output = graph.nodes.new('NodeGroupOutput')
    join = graph.nodes.new('GeometryNodeJoinGeometry')
    realize = graph.nodes.new('GeometryNodeRealizeInstances')
    graph.links.new(source.outputs['Geometry'], join.inputs['Geometry'])
    graph.links.new(join.outputs['Geometry'], realize.inputs['Geometry'])
    graph.links.new(realize.outputs['Geometry'], output.inputs['Geometry'])
    profile(mesh, root)
    record_surface_mask(mesh, root)
    surface = graph.nodes.new('GeometryNodeInputNamedAttribute')
    surface.data_type = 'BOOLEAN'
    surface.inputs['Name'].default_value = 'hgt_outline_surface'
    height = graph.nodes.new('GeometryNodeInputNamedAttribute')
    height.data_type = 'FLOAT'
    height.inputs['Name'].default_value = 'hgt_outline_height'
    taper = graph.nodes.new('GeometryNodeGroup')
    taper.node_tree = outline_profile.ensure(root)
    graph.links.new(height.outputs['Attribute'], taper.inputs['Height'])
    thickness = graph.nodes.new('ShaderNodeMath')
    thickness.operation = 'MULTIPLY'
    graph.links.new(taper.outputs['Scale'], thickness.inputs[0])
    graph.links.new(source.outputs['Outline Thickness'], thickness.inputs[1])
    visible = graph.nodes.new('ShaderNodeMath')
    visible.operation = 'GREATER_THAN'
    visible.inputs[1].default_value = 0
    graph.links.new(taper.outputs['Scale'], visible.inputs[0])
    for weight, pairs in by_weight.items():
        width = graph.nodes.new('ShaderNodeMath')
        width.operation = 'MULTIPLY'
        width.inputs[1].default_value = weight
        graph.links.new(thickness.outputs[0], width.inputs[0])
        for offset in range(0, len(pairs), len(PAIRS)):
            chunk = pairs[offset:offset+len(PAIRS)]
            selection = None
            for material, _outline in chunk:
                test = graph.nodes.new('GeometryNodeMaterialSelection')
                test.inputs['Material'].default_value = material
                selected = test.outputs['Selection']
                if selection is not None:
                    combine = graph.nodes.new('FunctionNodeBooleanMath')
                    combine.operation = 'OR'
                    graph.links.new(selection, combine.inputs[0])
                    graph.links.new(selected, combine.inputs[1])
                    selected = combine.outputs[0]
                selection = selected
            separate = graph.nodes.new('GeometryNodeSeparateGeometry')
            separate.domain = 'FACE'
            graph.links.new(source.outputs['Geometry'], separate.inputs['Geometry'])
            safe = graph.nodes.new('FunctionNodeBooleanMath')
            safe.operation = 'AND'
            graph.links.new(selection, safe.inputs[0])
            graph.links.new(surface.outputs['Attribute'], safe.inputs[1])
            # A zero-width reversed shell can still cover transparent source
            # faces. Black regions of the gradient must emit no shell.
            enabled = graph.nodes.new('FunctionNodeBooleanMath')
            enabled.operation = 'AND'
            graph.links.new(safe.outputs[0], enabled.inputs[0])
            graph.links.new(visible.outputs[0], enabled.inputs[1])
            graph.links.new(enabled.outputs[0], separate.inputs['Selection'])
            node = graph.nodes.new('GeometryNodeGroup')
            node.node_tree = settings.outline_graph
            graph.links.new(separate.outputs['Selection'], node.inputs['Geometry'])
            graph.links.new(width.outputs[0], node.inputs['Outline Thickness'])
            node.inputs['Base Geometry'].default_value = False
            node.inputs['Use Vertex Colors?'].default_value = False
            for name, (material, outline) in zip(PAIRS, chunk):
                node.inputs[name].default_value = material
                node.inputs[name + ' Outline'].default_value = outline
            graph.links.new(node.outputs['Geometry'], join.inputs['Geometry'])
    modifier = mesh.modifiers.new('HGT • Outlines', 'NODES')
    modifier.node_group = graph
    update(mesh, root)
    return modifier

def update(mesh, root):
    settings = root.hgt_character
    for modifier in mesh.modifiers:
        if modifier.type != "NODES" or not modifier.node_group:
            continue
        graph = modifier.node_group
        if graph != settings.outline_graph and not (graph.get('hgt_pmx_outline') and graph.get('hgt_owner') == settings.uid):
            continue
        scale = max(sum(mesh.matrix_world.to_scale()) / 3, 1e-6)
        value = settings.outline * settings.height / (1.7 * scale)
        field = input_value(modifier, "Outline Thickness")
        if abs(field.value - value) > 1e-7:
            field.value = value
            mesh.update_tag(refresh={'OBJECT'})
        if 2 <= graph.get('hgt_outline_version', 0) < 5:
            lower = input_value(modifier, 'Lower Thickness')
            if abs(lower.value - settings.outline_lower) > 1e-7:
                lower.value = settings.outline_lower
                mesh.update_tag(refresh={'OBJECT'})
        enabled = value > 0
        if modifier.show_viewport != enabled:
            modifier.show_viewport = enabled
        if modifier.show_render != enabled:
            modifier.show_render = enabled


def upgrade(root):
    settings = root.hgt_character
    for entry in settings.meshes:
        mesh = entry.object
        if not mesh or not entry.render_data or mesh.data != entry.render_data:
            continue
        owned = [m for m in mesh.modifiers if m.type == 'NODES' and m.node_group
                 and m.node_group.get('hgt_owner') == settings.uid and m.node_group.get('hgt_pmx_outline')]
        if owned and all(m.node_group.get('hgt_outline_version') == GRAPH_VERSION for m in owned):
            continue
        for modifier in owned:
            graph = modifier.node_group
            mesh.modifiers.remove(modifier)
            if graph.users == 0:
                bpy.data.node_groups.remove(graph)
        build(mesh, root)
    settings.has_outline = any(m.type == 'NODES' and m.node_group and m.node_group.get('hgt_pmx_outline')
                               for entry in settings.meshes if entry.object for m in entry.object.modifiers)
