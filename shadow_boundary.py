"""Soften owned shadow masks while retaining the original zero-value path."""
import math

import bpy

VERSION = 1
HARD_RANGE = .001
BODY_WIDTH = .18
FACE_RADIUS = .07
SAMPLES = 32


def zero_face_range(settings):
    """Match the old slider minimum, including its advanced compensation."""
    return min(.2, max(HARD_RANGE, HARD_RANGE * (.02 / .035) * settings.face_softness_adjust))


def _node(tree, kind, name):
    node = tree.nodes.new(kind)
    node.name = 'HGT • ' + name
    return node


def _link(tree, value, socket):
    if isinstance(value, bpy.types.NodeSocket):
        tree.links.new(value, socket)
    else:
        socket.default_value = value


def _source(socket):
    """Preserve the consumer's fallback when a reroute chain is unconnected."""
    if not socket.is_linked:
        return socket.default_value
    source = socket.links[0].from_socket
    while source.node.bl_idname == 'NodeReroute':
        incoming = source.node.inputs[0]
        if not incoming.is_linked:
            return socket.default_value
        source = incoming.links[0].from_socket
    return source


def _math(tree, operation, a, b):
    node = _node(tree, 'ShaderNodeMath', operation)
    node.operation = operation
    _link(tree, a, node.inputs[0])
    _link(tree, b, node.inputs[1])
    return node.outputs[0]


def _mix(tree, factor, a, b, color=False):
    node = _node(tree, 'ShaderNodeMix', 'Boundary Mix')
    node.data_type = 'RGBA' if color else 'FLOAT'
    indices = (6, 7) if color else (2, 3)
    _link(tree, factor, node.inputs[0])
    _link(tree, a, node.inputs[indices[0]])
    _link(tree, b, node.inputs[indices[1]])
    return node.outputs[2 if color else 0]


def _uniform(tree, uid, key):
    node = _node(tree, 'ShaderNodeAttribute', key)
    node.attribute_type = 'VIEW_LAYER'
    node.attribute_name = f'hgt_{uid}_{key}'
    return node.outputs['Fac']


def _replace(tree, new, targets):
    for socket in targets:
        tree.links.new(new, socket)


def _vector(tree, vector):
    node = _node(tree, 'ShaderNodeCombineXYZ', 'Toon Coordinate')
    for value, socket in zip(vector, node.inputs):
        _link(tree, value, socket)
    return node.outputs[0]


def _smooth(tree, value, threshold, width):
    node = _node(tree, 'ShaderNodeMapRange', 'Boundary Smoothstep')
    node.interpolation_type = 'SMOOTHSTEP'
    # The zero branch remains native. Keep this unused branch finite as well.
    width = _math(tree, 'MAXIMUM', width, 1e-7)
    _link(tree, value, node.inputs['Value'])
    _link(tree, _math(tree, 'SUBTRACT', threshold, width), node.inputs['From Min'])
    _link(tree, _math(tree, 'ADD', threshold, width), node.inputs['From Max'])
    return node.outputs[0]


def _sampler(tree, original, vector, name):
    node = _node(tree, 'ShaderNodeTexImage', name)
    node.image = original.image
    node.interpolation = original.interpolation
    node.extension = original.extension
    node.projection = original.projection
    # Image textures use implicit UVs when Vector is unlinked, even if its
    # default value is set. All constant and offset samples need actual links.
    tree.links.new(vector, node.inputs['Vector'])
    return node


def _body(shader, uid):
    tree = shader.node_tree
    if tree.get('hgt_boundary_version') == VERSION:
        return
    old = tree.nodes['Lit Factor'].outputs[0]
    targets = [link.to_socket for link in old.links]
    compare = tree.nodes['Shadows > -- Position']
    signal = compare.inputs[0].links[0].from_socket
    threshold = compare.inputs[1].links[0].from_socket
    softness = _uniform(tree, uid, 'hgt_shadow_softness')
    positive = _math(tree, 'GREATER_THAN', softness, 0)
    width = _math(tree, 'MULTIPLY', softness, BODY_WIDTH)
    softened = _smooth(tree, signal, threshold, width)
    shadow = tree.nodes['Shadows Mix -- 0'].outputs[0]
    shadow_targets = [link.to_socket for link in shadow.links]
    shadow_value = _mix(tree, positive, shadow, _math(tree, 'SUBTRACT', 1, softened))
    shadow_value.node.name = 'HGT • Body Shadow Boundary'
    _replace(tree, shadow_value, shadow_targets)
    result = _mix(tree, positive, old, softened)
    result.node.name = 'HGT • Body Boundary'
    _replace(tree, result, targets)
    tree['hgt_boundary_version'] = VERSION

    lighting = tree.nodes['Group.002'].node_tree
    if lighting.get('hgt_boundary_version') == VERSION:
        return
    output = next(n for n in lighting.nodes if n.bl_idname == 'NodeGroupOutput' and n.is_active_output)
    original = output.inputs['Color'].links[0].from_socket
    inputs = next(n for n in lighting.nodes if n.bl_idname == 'NodeGroupInput').outputs

    def multiply(a, b):
        node = _node(lighting, 'ShaderNodeMixRGB', 'Lighting Product')
        node.blend_type = 'MULTIPLY'
        node.inputs[0].default_value = 1
        _link(lighting, a, node.inputs[1])
        _link(lighting, b, node.inputs[2])
        return node.outputs[0]

    shadow = multiply(inputs['Sharp Shadow Color'], inputs['Soft Shadow Colour'])
    light = multiply(inputs['Sharp Light Colour'], inputs['Soft Light Colour'])
    illumination = _mix(lighting, inputs['Lit Factor'], shadow, light, color=True)
    color = multiply(multiply(inputs['Color'], illumination), inputs['Ambient Colour'])
    enabled = _math(lighting, 'GREATER_THAN', _uniform(lighting, uid, 'hgt_shadow_softness'), 0)
    interior = _math(lighting, 'MULTIPLY', _math(lighting, 'GREATER_THAN', inputs['Lit Factor'], 0),
                     _math(lighting, 'LESS_THAN', inputs['Lit Factor'], 1))
    enabled = _math(lighting, 'MULTIPLY', enabled, interior)
    lighting.links.new(_mix(lighting, enabled, original, color, color=True), output.inputs['Color'])
    lighting['hgt_boundary_version'] = VERSION


def _body_toon(tree, shader, original, positive):
    targets = [link.to_socket for link in original.outputs['Color'].links]
    shade = _sampler(tree, original, _vector(tree, (.5, 0, 0)), 'Toon Shadow Endpoint')
    light = _sampler(tree, original, _vector(tree, (.5, 1, 0)), 'Toon Light Endpoint')
    color = _mix(tree, shader.outputs['Lit Factor'], shade.outputs['Color'], light.outputs['Color'], color=True)
    selected = _mix(tree, positive, original.outputs['Color'], color, color=True)
    selected.node.name = 'HGT • Toon Boundary'
    _replace(tree, selected, targets)


def _mapped_factor(tree, raw, inputs):
    masked = _math(tree, 'ADD', _math(tree, 'MULTIPLY', raw, inputs['Mask']), inputs['Fill'])
    mapped = _mix(tree, masked, inputs['Shade'], inputs['Lit'])
    return _mix(tree, inputs['Catch'], 0, mapped)


def _face_filter(material, sampler, toon, uid):
    tree = bpy.data.node_groups.new('HGT • Face Boundary Filter', 'ShaderNodeTree')
    tree['hgt_owner'] = uid
    tree['hgt_boundary_filter'] = VERSION
    for name, kind in (('Vector', 'Vector'), ('Threshold', 'Float'), ('Mask', 'Float'),
                       ('Fill', 'Float'), ('Lit', 'Float'), ('Shade', 'Float'), ('Catch', 'Float'),
                       ('Radius', 'Float'), ('Hard Range', 'Float')):
        tree.interface.new_socket(name=name, in_out='INPUT', socket_type='NodeSocket' + kind)
    for name, kind in (('Factor', 'Float'), ('Soft Factor', 'Float'), ('Toon', 'Color')):
        tree.interface.new_socket(name=name, in_out='OUTPUT', socket_type='NodeSocket' + kind)
    inputs = _node(tree, 'NodeGroupInput', 'Filter Inputs').outputs
    output = _node(tree, 'NodeGroupOutput', 'Filter Outputs')
    primary, secondary, colors = [], [], []
    weights = [math.exp(-2 * (i + .5) / (SAMPLES // 2)) for i in range(SAMPLES // 2)]
    total = 2 * sum(weights)
    for index, weight in enumerate(weights):
        radius = math.sqrt((index + .5) / (SAMPLES // 2))
        angle = index * math.pi * (3 - math.sqrt(5))
        for sign in (1, -1):
            offset = (sign * radius * math.cos(angle), sign * radius * math.sin(angle), 0)
            scale = _node(tree, 'ShaderNodeVectorMath', 'Filter Offset')
            scale.operation = 'SCALE'
            scale.inputs[0].default_value = offset
            tree.links.new(inputs['Radius'], scale.inputs['Scale'])
            add = _node(tree, 'ShaderNodeVectorMath', 'Filter Coordinate')
            add.operation = 'ADD'
            tree.links.new(inputs['Vector'], add.inputs[0])
            tree.links.new(scale.outputs[0], add.inputs[1])
            sample = _sampler(tree, sampler, add.outputs[0], 'Boundary SDF Sample')
            field = sample.outputs['Alpha']
            if material['hgt_sdf_channel'] == 'RA':
                split = _node(tree, 'ShaderNodeSeparateColor', 'Boundary SDF Red')
                tree.links.new(sample.outputs['Color'], split.inputs[0])
                field = _math(tree, 'MULTIPLY', _math(tree, 'ADD', split.outputs['Red'], field), .5)
            hard = _smooth(tree, field, inputs['Threshold'], inputs['Hard Range'])
            soft_width = _math(tree, 'ADD', inputs['Hard Range'], .05)
            soft = _smooth(tree, _math(tree, 'ADD', field, .05), inputs['Threshold'], soft_width)
            hard = _mapped_factor(tree, hard, inputs)
            soft = _mapped_factor(tree, soft, inputs)
            primary.append(_math(tree, 'MULTIPLY', hard, weight / total))
            secondary.append(_math(tree, 'MULTIPLY', soft, weight / total))
            if toon:
                color = _sampler(tree, toon, _vector(tree, (.5, soft, 0)), 'Boundary Toon Sample').outputs['Color']
                scale = _node(tree, 'ShaderNodeVectorMath', 'Toon Sample Weight')
                scale.operation = 'SCALE'
                tree.links.new(color, scale.inputs[0])
                scale.inputs['Scale'].default_value = weight / total
                colors.append(scale.outputs[0])
    for name, values in (('Factor', primary), ('Soft Factor', secondary)):
        while len(values) > 1:
            values = [_math(tree, 'ADD', values[i], values[i + 1]) for i in range(0, len(values), 2)]
        tree.links.new(values[0], output.inputs[name])
    if colors:
        while len(colors) > 1:
            sums = []
            for i in range(0, len(colors), 2):
                node = _node(tree, 'ShaderNodeVectorMath', 'Toon Sample Sum')
                node.operation = 'ADD'
                tree.links.new(colors[i], node.inputs[0])
                tree.links.new(colors[i + 1], node.inputs[1])
                sums.append(node.outputs[0])
            colors = sums
        tree.links.new(colors[0], output.inputs['Toon'])
    return tree


def _face(material, shader, toon, uid):
    native = shader.node_tree.nodes['Face Factor'].node_tree
    if native.get('hgt_boundary_version') == VERSION:
        return
    samplers = [n for n in native.nodes if n.type == 'TEX_IMAGE' and n.get('hgt_texture_role') == 'face_sdf']
    if len(samplers) != 5 or any(n.image != samplers[0].image for n in samplers):
        raise ValueError('脸部 SDF 采样已改变，请恢复原材质后重新应用')
    sampler = samplers[0]
    filter_tree = _face_filter(material, sampler, toon, uid)
    filtered = _node(native, 'ShaderNodeGroup', 'Face Boundary Samples')
    filtered.node_tree = filter_tree
    gi = next(n for n in native.nodes if n.bl_idname == 'NodeGroupInput').outputs
    sources = {'Vector': sampler.inputs['Vector'].links[0].from_socket,
               'Threshold': native.nodes['Reroute.037'].outputs[0],
               'Mask': _source(native.nodes['Math.015'].inputs[1]),
               'Fill': _source(native.nodes['Math.014'].inputs[1]),
               'Lit': gi['Lit Fac'], 'Shade': gi['Shaded Fac'],
               'Catch': native.nodes['Invert Color'].outputs['Color']}
    for name, source in sources.items():
        _link(native, source, filtered.inputs[name])
    radius = _uniform(native, uid, 'hgt_face_boundary_radius')
    native.links.new(radius, filtered.inputs['Radius'])
    native.links.new(_uniform(native, uid, 'hgt_face_hard_range'), filtered.inputs['Hard Range'])
    positive = _math(native, 'GREATER_THAN', radius, 0)
    output = next(n for n in native.nodes if n.bl_idname == 'NodeGroupOutput' and n.is_active_output)
    for name in ('Factor', 'Soft Factor'):
        old = output.inputs[name].links[0].from_socket
        value = _mix(native, positive, old, filtered.outputs[name])
        value.node.name = 'HGT • Face Boundary ' + name
        native.links.new(value, output.inputs[name])
    if toon:
        for tree, name in ((native, 'Boundary Toon'), (shader.node_tree, 'Boundary Toon')):
            tree.interface.new_socket(name=name, in_out='OUTPUT', socket_type='NodeSocketColor')
        native.links.new(filtered.outputs['Toon'], output.inputs['Boundary Toon'])
        top = shader.node_tree
        top_output = next(n for n in top.nodes if n.bl_idname == 'NodeGroupOutput' and n.is_active_output)
        top.links.new(top.nodes['Face Factor'].outputs['Boundary Toon'], top_output.inputs['Boundary Toon'])
        tree = material.node_tree
        targets = [link.to_socket for link in toon.outputs['Color'].links]
        enabled = _math(tree, 'GREATER_THAN', _uniform(tree, uid, 'hgt_face_boundary_radius'), 0)
        color = _mix(tree, enabled, toon.outputs['Color'], shader.outputs['Boundary Toon'], color=True)
        color.node.name = 'HGT • Toon Boundary'
        _replace(tree, color, targets)
    native['hgt_boundary_version'] = VERSION


def ensure(binding):
    material = binding.generated
    if material.get('hgt_boundary_version') == VERSION:
        return
    if binding.role not in {'eye', 'brow', 'expression'}:
        from .face_sdf import shader_node
        shader = shader_node(material)
        tree = material.node_tree
        toon = next((n for n in tree.nodes if n.type == 'TEX_IMAGE' and n.get('hgt_texture_role') == 'toon'), None)
        uid = binding.id_data.hgt_character.uid
        if material.get('hgt_template') == 'Face':
            _face(material, shader, toon, uid)
        else:
            _body(shader, uid)
            if toon:
                positive = _math(tree, 'GREATER_THAN', _uniform(tree, uid, 'hgt_shadow_softness'), 0)
                _body_toon(tree, shader, toon, positive)
    material['hgt_boundary_version'] = VERSION
