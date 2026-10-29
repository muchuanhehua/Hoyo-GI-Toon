"""Render participation of effect objects and source-marked facial layers."""
from .asset_resolver import source_name

EXPRESSION_MASK = "hgt_facial_expression"
UV_EPSILON = 1e-5


def configure_culling(material, mode):
    if mode not in {0, 1, 2}:
        raise ValueError(f'材质剔除模式无效：{mode}')
    material.use_backface_culling = mode == 2
    if mode != 1:
        return
    tree = material.node_tree
    output = next(n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output)
    source = output.inputs['Surface'].links[0].from_socket
    geometry = tree.nodes.new('ShaderNodeNewGeometry')
    transparent = tree.nodes.new('ShaderNodeBsdfTransparent')
    mix = tree.nodes.new('ShaderNodeMixShader');mix.name = 'HGT Source Front Culling'
    tree.links.new(geometry.outputs['Backfacing'], mix.inputs[0])
    tree.links.new(transparent.outputs[0], mix.inputs[1])
    tree.links.new(source, mix.inputs[2])
    tree.links.new(mix.outputs[0], output.inputs['Surface'])


def participation(obj):
    """Use referenced material namespaces, rather than an object's loose name."""
    materials = [source_name(s.material.name) for s in obj.material_slots if s.material]
    if (source_name(obj.name).casefold() == 'eyestar' and materials
            and all(name.startswith('Avatar_') and name.endswith('_Mat_Face') for name in materials)):
        return 'inactive_expression', 'EyeStar expression geometry using the Face atlas'
    if materials and all(name == 'Avatar_Default_Mat' for name in materials):
        return 'placeholder', 'source default material'
    if materials and all(name.startswith('SkillObj_') for name in materials):
        return 'gameplay_attachment', 'source SkillObj material namespace'
    if materials and all(name.startswith('Eff_') for name in materials):
        return 'gameplay_effect', 'source Eff material namespace'
    return 'surface', 'source character or retained material'


def uses_default_expression(assets):
    return (assets.floats.get("_FacialUVExpressionEnable", 0) != 0
            and assets.floats.get("_FacialExpEnable", 0) == 0
            and assets.floats.get("_FacialExpAdditionEnable", 0) == 0)


def mark_expression_faces(entry, slot_index, assets):
    """Read the third source UV channel; write only a derived render attribute."""
    if not uses_default_expression(assets):
        return 0
    mesh = entry.render_data
    uv = entry.original_data.uv_layers.get("UV2")
    if uv is None:
        raise ValueError(f"{assets.source} 启用了表情 UV，但原网格缺少 UV2")
    faces = [p for p in mesh.polygons if p.material_index == slot_index]
    marked = [p.index for p in faces if any(abs(v) > UV_EPSILON
              for loop in p.loop_indices for v in uv.data[loop].uv)]
    if not marked:
        return 0
    # A zero/nonzero partition identifies this source layout. An unrelated
    # populated UV set must never turn a whole facial material invisible.
    if len(marked) == len(faces):
        raise ValueError(f"{assets.source} 的 UV2 未区分基础面与表情层，请核对源网格的 UV 通道")
    mask = mesh.attributes.get(EXPRESSION_MASK)
    if mask is None:
        mask = mesh.attributes.new(EXPRESSION_MASK, "FLOAT", "FACE")
    elif mask.data_type != "FLOAT" or mask.domain != "FACE":
        raise ValueError(f"{entry.object.name} 的 {EXPRESSION_MASK} 属性类型不正确")
    for index in marked:
        mask.data[index].value = 1.0
    mesh["hgt_expression_source_uv"] = uv.name
    mesh["hgt_expression_faces"] = sum(item.value > .5 for item in mask.data)
    return len(marked)


def attach_expression(entry, owner):
    """Exclude inactive surfaces from evaluated depth, retaining source geometry."""
    mask = entry.render_data.attributes.get(EXPRESSION_MASK)
    if mask is None or not any(item.value > .5 for item in mask.data):
        return None
    for modifier in entry.object.modifiers:
        if (modifier.type == 'NODES' and modifier.node_group
                and modifier.node_group.get('hgt_expression_surfaces')):
            return modifier
    import bpy
    graph = bpy.data.node_groups.new('HGT • Facial Surfaces', 'GeometryNodeTree')
    graph['hgt_owner'], graph['hgt_expression_surfaces'] = owner, True
    graph.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    graph.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    source = graph.nodes.new('NodeGroupInput')
    output = graph.nodes.new('NodeGroupOutput')
    marker = graph.nodes.new('GeometryNodeInputNamedAttribute');marker.data_type = 'FLOAT'
    marker.inputs['Name'].default_value = EXPRESSION_MASK
    active = graph.nodes.new('GeometryNodeDeleteGeometry');active.domain = 'FACE'
    graph.links.new(source.outputs['Geometry'], active.inputs['Geometry'])
    graph.links.new(marker.outputs['Attribute'], active.inputs['Selection'])
    graph.links.new(active.outputs['Geometry'], output.inputs['Geometry'])
    modifier = entry.object.modifiers.new('HGT • Facial Surfaces', 'NODES')
    modifier.node_group = graph
    return modifier
