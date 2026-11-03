"""Owned height gradients; source rest-height and mesh data stay unchanged."""
import json
import bpy

NODE = 'HGT • Outline Height Gradient'


def node(settings):
    tree = settings.outline_profile
    if tree is None:
        return None
    result = tree.nodes.get(NODE)
    if tree.get('hgt_owner') != settings.uid or result is None or result.type != 'VALTORGB':
        raise ValueError('描边渐变数据无效，请恢复原材质后重新应用')
    return result


def coefficient(color):
    return (color[0] * .2126 + color[1] * .7152 + color[2] * .0722) * color[3]


def endpoint(settings, top):
    ramp = node(settings)
    if ramp:
        element = ramp.color_ramp.elements[0 if top else -1]
        return coefficient(element.color)
    return settings.get('outline_top' if top else 'outline_lower', 1.0 if top else .35)


def set_endpoint(settings, value, top):
    settings['outline_top' if top else 'outline_lower'] = value
    ramp = node(settings)
    if ramp:
        ramp.color_ramp.elements[0 if top else -1].color = (value, value, value, 1)


def ensure(root):
    settings = root.hgt_character
    if node(settings):
        return settings.outline_profile
    tree = bpy.data.node_groups.new('HGT • ' + root.name + ' • Outline Profile', 'GeometryNodeTree')
    tree['hgt_owner'], tree['hgt_outline_profile'] = settings.uid, True
    tree.interface.new_socket(name='Height', in_out='INPUT', socket_type='NodeSocketFloat')
    tree.interface.new_socket(name='Scale', in_out='OUTPUT', socket_type='NodeSocketFloat')
    source = tree.nodes.new('NodeGroupInput')
    output = tree.nodes.new('NodeGroupOutput')
    reverse = tree.nodes.new('ShaderNodeMath')
    reverse.operation = 'SUBTRACT'
    reverse.inputs[0].default_value = 1
    tree.links.new(source.outputs['Height'], reverse.inputs[1])
    ramp = tree.nodes.new('ShaderNodeValToRGB')
    ramp.name = NODE
    ramp.color_ramp.interpolation = 'EASE'
    top, lower = endpoint(settings, True), endpoint(settings, False)
    ramp.color_ramp.elements[0].color = (top, top, top, 1)
    ramp.color_ramp.elements[-1].color = (lower, lower, lower, 1)
    tree.links.new(reverse.outputs[0], ramp.inputs['Fac'])
    split = tree.nodes.new('FunctionNodeSeparateColor')
    split.mode = 'RGB'
    tree.links.new(ramp.outputs['Color'], split.inputs['Color'])
    gray = None
    for channel, weight in (('Red', .2126), ('Green', .7152), ('Blue', .0722)):
        term = tree.nodes.new('ShaderNodeMath')
        term.operation = 'MULTIPLY_ADD'
        tree.links.new(split.outputs[channel], term.inputs[0])
        term.inputs[1].default_value = weight
        term.inputs[2].default_value = 0
        if gray:
            tree.links.new(gray, term.inputs[2])
        gray = term.outputs[0]
    alpha = tree.nodes.new('ShaderNodeMath')
    alpha.operation = 'MULTIPLY'
    tree.links.new(gray, alpha.inputs[0])
    tree.links.new(ramp.outputs['Alpha'], alpha.inputs[1])
    tree.links.new(alpha.outputs[0], output.inputs['Scale'])
    settings.outline_profile = tree
    if settings.outline_profile_state:
        restore(settings, json.loads(settings.outline_profile_state))
    return tree


def snapshot(settings):
    ramp = node(settings)
    if ramp is None:
        return None
    data = ramp.color_ramp
    return {'interpolation': data.interpolation, 'color_mode': data.color_mode,
            'hue_interpolation': data.hue_interpolation,
            'elements': [{'position': e.position, 'color': list(e.color)} for e in data.elements]}


def restore(settings, state):
    data = node(settings).color_ramp
    while len(data.elements) > 2:
        data.elements.remove(data.elements[1])
    for element, record in zip((data.elements[0], data.elements[-1]), (state['elements'][0], state['elements'][-1])):
        element.position, element.color = record['position'], record['color']
    for record in state['elements'][1:-1]:
        data.elements.new(record['position']).color = record['color']
    for key in ('interpolation', 'color_mode', 'hue_interpolation'):
        setattr(data, key, state[key])


def reset(root):
    settings = root.hgt_character
    ensure(root)
    restore(settings, {'interpolation': 'EASE', 'color_mode': 'RGB', 'hue_interpolation': 'NEAR',
                       'elements': [{'position': 0, 'color': (1, 1, 1, 1)},
                                    {'position': 1, 'color': (.35, .35, .35, 1)}]})
    settings.outline_profile_state = ''
