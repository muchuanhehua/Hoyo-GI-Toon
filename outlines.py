"""Material-aware native outline modifiers; the imported mesh remains intact."""
import json
import bpy
from .shaders import input_value, set_input

PAIRS = ("Hair", "Body", "Face", "Dress", "Dress 2", "Other")
# Fixed V3_GenshinImpactGeometryNodesSetup mask routing, in upstream order.
PART_PAIRS = {"Hair":"Hair", "Body":"Body", "Face":"Face", "Dress":"Dress", "Dress1":"Dress",
              "Helmet":"Dress", "Dress2":"Dress 2", "Arm":"Other", "Effect":"Other",
              "EffectHair":"Other", "Gauntlet":"Other", "HelmetEmo":"Other"}


def build(mesh, root):
    if root.hgt_character.source_format == 'pmx':
        return build_pmx(mesh, root)
    # Eye/eyelid surfaces already carry their painted contour. An inverted
    # hull around these overlapping layers draws spurious lines on the cheeks.
    if mesh.name.split('.')[0] in {"Brow", "Pupil", "Face_Eye"}:
        return None
    bindings = {b.generated:b.outline for b in root.hgt_character.bindings}
    materials = list(dict.fromkeys(s.material for s in mesh.material_slots if s.material in bindings))
    if len(materials) > len(PAIRS):
        raise ValueError(f"{mesh.name} 超出原版描边的六个材质分区")
    graph = root.hgt_character.outline_graph
    modifier = next((m for m in mesh.modifiers if m.type == "NODES" and m.node_group == graph), None)
    modifier = modifier or mesh.modifiers.new("HGT • Outlines", "NODES")
    modifier.node_group = graph
    set_input(modifier, "Base Geometry", True)
    set_input(modifier, "Use Vertex Colors?", bool(mesh.data.color_attributes.get("Col")))
    color = input_value(modifier, "Vertex Colors")
    color.type = "ATTRIBUTE"
    color.attribute_name = "Col"
    by_part = {b.source_name.rsplit("_Mat_",1)[-1]:b.generated for b in root.hgt_character.bindings}
    routed = {pair:by_part[part] for part,pair in PART_PAIRS.items() if part in by_part}
    # Newer exports can have additional Body01/Body02 parts. Reuse unused
    # original slots on this mesh without reordering the standard V3 masks.
    for material in materials:
        if material in routed.values():
            continue
        available = [pair for pair in PAIRS if routed.get(pair) not in materials]
        preferred = material["hgt_template"]
        pair = preferred if preferred in available else available[0]
        routed[pair] = material
    for part, material in routed.items():
        set_input(modifier, part, material)
        set_input(modifier, part + " Outline", bindings[material])
    update(mesh, root)
    return modifier


def build_pmx(mesh, root):
    """Repeat the upstream six-material outline branch, joining the base once."""
    settings = root.hgt_character
    by_weight = {}
    for binding in settings.bindings:
        material = binding.generated
        if material not in mesh.data.materials[:]:
            continue
        pmx = json.loads(material['hgt_pmx'])
        if (binding.role in {'eye', 'brow', 'expression'} or not pmx['edge']
                or pmx['alpha'] <= 0 or pmx['overlay'] or pmx['edge_weight'] <= 0):
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
