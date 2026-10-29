"""Material-aware PMX outlines on derived geometry."""

import json
import bpy

from .shaders import input_value, set_input

PAIRS = ("Hair", "Body", "Face", "Dress", "Dress 2", "Other")

def build(mesh, root):
    """Repeat the upstream six-material outline branch, joining the base once."""
    settings = root.hgt_character
    by_weight = {}
    for binding in settings.bindings:
        material = binding.generated
        if material not in mesh.data.materials[:]:
            continue
        pmx = json.loads(material['hgt_pmx'])
        if (binding.role in {'eye', 'brow', 'expression'} or not pmx['edge']
                   or pmx['alpha'] <= 0 or pmx['overlay'] or pmx['edge_weight'] <= 0 or pmx['edge_color'][3] <= 0):
            continue
        by_weight.setdefault(pmx['edge_weight'], []).append((material, binding.outline))
    if not by_weight:
        return None
    graph = bpy.data.node_groups.new(f'HGT • {mesh.name} • PMX Outlines', 'GeometryNodeTree')
    graph['hgt_owner'], graph['hgt_pmx_outline'] = settings.uid, True
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
    for weight, pairs in by_weight.items():
        width = graph.nodes.new('ShaderNodeMath')
        width.operation = 'MULTIPLY'
        width.inputs[1].default_value = weight
        graph.links.new(source.outputs['Outline Thickness'], width.inputs[0])
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
        value = settings.outline
        field = input_value(modifier, "Outline Thickness")
        if abs(field.value - value) > 1e-7:
            field.value = value
        enabled = value > 0
        if modifier.show_viewport != enabled:
            modifier.show_viewport = enabled
        if modifier.show_render != enabled:
            modifier.show_render = enabled
