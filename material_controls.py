"""Adjust only owned shader inputs; MMD source materials remain untouched."""
import json

def initialize(binding):
    material = binding.generated
    tree = material.node_tree
    surface = tree.nodes['HGT • Surface Color']
    color = surface.inputs['Color'].links[0].from_socket
    tint = tree.nodes.new('ShaderNodeMixRGB')
    tint.name = 'HGT • Material Tint'
    tint.blend_type = 'MULTIPLY'
    tint.inputs[0].default_value = 1
    tint.inputs[2].default_value = (1, 1, 1, 1)
    tree.links.new(color, tint.inputs[1])
    tree.links.new(tint.outputs[0], surface.inputs['Color'])
    binding.tint = (1, 1, 1)
    binding.shadow_color = tree.nodes['Body Shader'].inputs['Daytime Shadow Color'].default_value[:3]
    binding.outline_color = binding.outline.node_tree.nodes['Outlines'].inputs['Outline Color 1'].default_value[:3]
    binding.defaults = json.dumps({'tint': list(binding.tint), 'shadow_color': list(binding.shadow_color), 'outline_color': list(binding.outline_color)})

def apply(root):
    for binding in root.hgt_character.bindings:
        if not binding.generated or not binding.outline:
            raise ValueError('材质引用已改变，请恢复后重新应用材质')
        tree = binding.generated.node_tree
        socket = tree.nodes['HGT • Material Tint'].inputs[2]
        if tuple(socket.default_value) != (*binding.tint, 1):
            socket.default_value = (*binding.tint, 1)
        for socket in tree.nodes['Body Shader'].inputs:
            if socket.name.startswith(('Daytime Shadow Color', 'Nighttime Shadow Color')):
                if tuple(socket.default_value) != (*binding.shadow_color, 1):
                    socket.default_value = (*binding.shadow_color, 1)
        alpha = json.loads(binding.generated['hgt_pmx'])['edge_color'][3]
        for socket in binding.outline.node_tree.nodes['Outlines'].inputs:
            if socket.name.startswith('Outline Color '):
                if tuple(socket.default_value) != (*binding.outline_color, alpha):
                    socket.default_value = (*binding.outline_color, alpha)

def reset(root):
    settings = root.hgt_character
    settings.building = True
    try:
        for binding in settings.bindings:
            for key, value in json.loads(binding.defaults).items():
                setattr(binding, key, value)
        settings.shadow_position = settings.initial_shadow
        settings.outline = settings.initial_outline
    finally:
        settings.building = False
