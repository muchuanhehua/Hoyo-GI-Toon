"""Adjust only owned shader inputs; MMD source materials remain untouched."""
import json
from .pmx_materials import configure_transparency
from .face_sdf import shader_node
from .shaders import uniform

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
    extend(binding)
    binding.tint = (1, 1, 1)
    binding.shadow_color = shader_node(material).inputs['Daytime Shadow Color'].default_value[:3]
    binding.outline_color = binding.outline.node_tree.nodes['Outlines'].inputs['Outline Color 1'].default_value[:3]
    binding.defaults = json.dumps({'tint': list(binding.tint), 'shadow_color': list(binding.shadow_color),
                                   'outline_color': list(binding.outline_color),
                                   'brightness': 1, 'saturation': 1, 'opacity': 1})


def extend(binding):
    material = binding.generated
    tree = material.node_tree
    surface = tree.nodes['HGT • Surface Color']
    if tree.nodes.get('HGT • Saturation and Brightness') is None:
        color = surface.inputs['Color'].links[0].from_socket
        hsv = tree.nodes.new('ShaderNodeHueSaturation')
        hsv.name = 'HGT • Saturation and Brightness'
        tree.links.new(color, hsv.inputs['Color'])
        tree.links.new(hsv.outputs['Color'], surface.inputs['Color'])
    if tree.nodes.get('HGT • Key Light Color') is None:
        color = surface.inputs['Color'].links[0].from_socket
        tint = tree.nodes.new('ShaderNodeMixRGB')
        tint.name, tint.blend_type = 'HGT • Key Light Color', 'MULTIPLY'
        tint.inputs[0].default_value = 1
        tree.links.new(color, tint.inputs[1])
        uniform(tree, 'HGT • Key Light Uniform', 'hgt_light_color', tint.inputs[2],
                binding.id_data.hgt_character.uid, output='Color')
        tree.links.new(tint.outputs[0], surface.inputs['Color'])
    if tree.nodes.get('HGT • Opacity') is None:
        coverage = tree.nodes['HGT • Surface Opacity'].inputs[0]
        opacity = tree.nodes.new('ShaderNodeMath')
        opacity.name, opacity.operation = 'HGT • Opacity', 'MULTIPLY'
        opacity.inputs[1].default_value = 1
        if coverage.is_linked:
            tree.links.new(coverage.links[0].from_socket, opacity.inputs[0])
        else:
            opacity.inputs[0].default_value = coverage.default_value
        tree.links.new(opacity.outputs[0], coverage)
        material['hgt_surface_method'] = material.surface_render_method
    shader = shader_node(material)
    for name, key in (('Shadow Transition Range', 'hgt_shadow_transition'), ('Face Shadow Softness', 'hgt_face_softness')):
        socket = shader.inputs.get(name)
        if socket is not None:
            uniform(tree, 'HGT • ' + name, key, socket, binding.id_data.hgt_character.uid)


def apply_binding(binding):
    if not binding.generated or not binding.outline:
        raise ValueError('材质引用已改变，请恢复后重新应用材质')
    material = binding.generated
    tree = material.node_tree
    socket = tree.nodes['HGT • Material Tint'].inputs[2]
    if tuple(socket.default_value) != (*binding.tint, 1):
        socket.default_value = (*binding.tint, 1)
    hsv = tree.nodes.get('HGT • Saturation and Brightness')
    if hsv:
        for key, value in (('Saturation', binding.saturation), ('Value', binding.brightness)):
            if abs(hsv.inputs[key].default_value - value) > 1e-6:
                hsv.inputs[key].default_value = value
        opacity = tree.nodes['HGT • Opacity'].inputs[1]
        if abs(opacity.default_value - binding.opacity) > 1e-6:
            opacity.default_value = binding.opacity
        method = 'BLENDED' if binding.opacity < 1 else material['hgt_surface_method']
        if material.surface_render_method != method:
            material.surface_render_method = method
        outline = binding.outline
        coverage = outline.node_tree.nodes['HGT • PMX Edge Alpha'].inputs[0]
        value = outline['hgt_edge_coverage'] * binding.opacity
        if abs(coverage.default_value - value) > 1e-6:
            coverage.default_value = value
        method = 'BLENDED' if binding.opacity < 1 else outline['hgt_surface_method']
        if outline.surface_render_method != method:
            outline.surface_render_method = method
    for socket in shader_node(material).inputs:
        if socket.name.startswith(('Daytime Shadow Color', 'Nighttime Shadow Color')):
            if tuple(socket.default_value) != (*binding.shadow_color, 1):
                socket.default_value = (*binding.shadow_color, 1)
    alpha = binding.outline.get('hgt_edge_alpha', 1.0)
    for socket in binding.outline.node_tree.nodes['Outlines'].inputs:
        if socket.name.startswith('Outline Color '):
            if tuple(socket.default_value) != (*binding.outline_color, alpha):
                socket.default_value = (*binding.outline_color, alpha)

def apply(root):
    for binding in root.hgt_character.bindings:
        if not binding.generated or not binding.outline:
            raise ValueError('材质引用已改变，请恢复后重新应用材质')
        pmx = json.loads(binding.generated['hgt_pmx'])
        configure_transparency(binding.generated, binding.role, pmx['overlay'])
        apply_binding(binding)


def upgrade(root):
    settings = root.hgt_character
    settings.building = True
    try:
        from . import shaders, pmx_materials
        if settings.light_source and not settings.is_property_set('light_reference_energy'):
            settings.light_reference_energy = (2 if settings.light_source.get('hgt_scene_light')
                                               else max(settings.light_source.data.energy, 1))
        shaders.configure_controls(root)
        from . import lighting
        lighting.upgrade(root)
        if not settings.is_property_set('shadow_softness'):
            settings.shadow_softness = settings.shadow_transition
            settings.face_softness_adjust = settings.face_softness / max(1e-12, settings.shadow_softness * (.02 / .035))
        for binding in settings.bindings:
            extend(binding)
            if 'hgt_edge_coverage' not in binding.outline:
                pmx = json.loads(binding.generated['hgt_pmx'])
                pmx_materials.configure_outline(binding.outline, pmx)
                if not pmx['edge'] or pmx['edge_color'][3] <= 0:
                    binding.outline_color = binding.outline.node_tree.nodes['Outlines'].inputs['Outline Color 1'].default_value[:3]
    finally:
        settings.building = False

def reset(root):
    settings = root.hgt_character
    settings.building = True
    try:
        for binding in settings.bindings:
            for key, value in json.loads(binding.defaults).items():
                setattr(binding, key, value)
        settings.shadow_position = settings.initial_shadow
        settings.face_softness = settings.initial_face_softness
        settings.outline = settings.initial_outline
        settings.shadow_transition = 0.035
        settings.shadow_softness = .035
        settings.face_softness_adjust = settings.initial_face_softness / .02
        from . import outline_profile
        outline_profile.reset(root)
        for binding in settings.bindings:
            binding.brightness = binding.saturation = binding.opacity = 1
    finally:
        settings.building = False
