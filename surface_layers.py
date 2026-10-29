"""Render participation of effect objects and source-marked facial layers."""
from .asset_resolver import source_name

EXPRESSION_MASK = "hgt_facial_expression"
UV_EPSILON = 1e-5


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


def mask_material(material):
    """Retain all faces and shade inactive expression surfaces transparently."""
    tree = material.node_tree
    output = next(n for n in tree.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output)
    surface = output.inputs["Surface"]
    source = surface.links[0].from_socket
    marker = tree.nodes.new("ShaderNodeAttribute")
    marker.name = "HGT Expression Mask"
    marker.attribute_name = EXPRESSION_MASK
    marker.location = (output.location.x - 440, output.location.y - 240)
    transparent = tree.nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (output.location.x - 440, output.location.y - 100)
    mix = tree.nodes.new("ShaderNodeMixShader")
    mix.name = "HGT Facial Layers"
    mix.location = (output.location.x - 200, output.location.y)
    tree.links.new(marker.outputs["Fac"], mix.inputs[0])
    tree.links.new(source, mix.inputs[1])
    tree.links.new(transparent.outputs[0], mix.inputs[2])
    tree.links.new(mix.outputs[0], surface)
    material.surface_render_method = "DITHERED"
    material["hgt_expression_mask"] = EXPRESSION_MASK


def filter_outline_surfaces(graph):
    """Filter the evaluated outline branch; retain the entire base geometry."""
    geometry = graph.nodes['Merge by Distance'].inputs['Geometry']
    source = geometry.links[0].from_socket
    marker = graph.nodes.new('GeometryNodeInputNamedAttribute')
    marker.data_type = 'FLOAT'
    marker.inputs['Name'].default_value = EXPRESSION_MASK
    marker.name = 'HGT Expression Outline Mask'
    filtered = graph.nodes.new('GeometryNodeDeleteGeometry')
    filtered.domain = 'FACE'
    filtered.name = 'HGT Active Outline Surfaces'
    filtered.label = 'Active outline surfaces'
    graph.links.new(source, filtered.inputs['Geometry'])
    graph.links.new(marker.outputs['Attribute'], filtered.inputs['Selection'])
    graph.links.new(filtered.outputs['Geometry'], geometry)
    graph['hgt_expression_mask'] = EXPRESSION_MASK
