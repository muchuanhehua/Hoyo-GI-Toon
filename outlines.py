"""Material-aware PMX outlines on derived geometry."""

import json
import bpy
from mathutils import Vector

from .shaders import input_value
from .pmx_materials import is_inner_surface

PAIRS = ("Hair", "Body", "Face", "Dress", "Dress 2", "Other")
GRAPH_VERSION = 3


def eligible(binding):
    if not binding.generated:
        return False
    # Shader roles stay unchanged: inner cloth still uses Body shading.
    if binding.source and is_inner_surface(binding.source):
        return False
    pmx = json.loads(binding.generated['hgt_pmx'])
    return binding.role not in {'eye', 'brow', 'expression'} and pmx['alpha'] > 0 and not pmx['overlay']


def profile(mesh, root):
    """Keep rest-height on the derived mesh, so the taper follows skinning."""
    settings = root.hgt_character
    inverse = settings.source_root.matrix_world.inverted_safe()
    points = [inverse @ entry.object.matrix_world @ Vector(corner)
              for entry in settings.meshes if entry.object for corner in entry.object.bound_box]
    low, high = min(p.z for p in points), max(p.z for p in points)
    transform = inverse @ mesh.matrix_world
    attribute = mesh.data.attributes.get('hgt_outline_height')
    if attribute is None:
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
                                  ('Lower Thickness', 'INPUT', 'NodeSocketFloat'),
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
    height = graph.nodes.new('GeometryNodeInputNamedAttribute')
    height.data_type = 'FLOAT'
    height.inputs['Name'].default_value = 'hgt_outline_height'
    taper = graph.nodes.new('ShaderNodeMapRange')
    taper.interpolation_type = 'SMOOTHSTEP'
    graph.links.new(height.outputs['Attribute'], taper.inputs['Value'])
    graph.links.new(source.outputs['Lower Thickness'], taper.inputs['To Min'])
    taper.inputs['To Max'].default_value = 1
    thickness = graph.nodes.new('ShaderNodeMath')
    thickness.operation = 'MULTIPLY'
    graph.links.new(taper.outputs['Result'], thickness.inputs[0])
    graph.links.new(source.outputs['Outline Thickness'], thickness.inputs[1])
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
            graph.links.new(selection, separate.inputs['Selection'])
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
        if graph.get('hgt_outline_version', 0) >= 2:
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
