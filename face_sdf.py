"""Owned sampling around native Face Factor; source meshes stay unchanged."""
import json
from .sampling import configure as configure_mapping
from .shaders import load_image


def shader_node(material):
    key = 'Face Shader' if material.get('hgt_template') == 'Face' else 'Body Shader'
    node = material.node_tree.nodes.get(key)
    if node is None:
        raise ValueError('生成材质缺少 ' + key)
    return node


def _mask_node(tree, node, image, settings):
    node.image = image
    node['hgt_texture_role'] = 'face_mask'
    uv = tree.nodes.new('ShaderNodeUVMap')
    uv.uv_map = 'UV0'
    tree.links.new(uv.outputs['UV'], node.inputs['Vector'])
    configure_mapping(node, settings)


def configure(library, assets, graph):
    shader = graph.shader
    tree = shader.node_tree
    factor = tree.nodes['Face Factor'].node_tree
    info = assets.features['face_sdf']
    legacy = info['encoding'] == 'genshin_face_lightmap_alpha'
    # R/A store two ranges of the new main-shadow field. G/B and the
    # original game's complete parameter mapping remain outside this adapter.
    channel = 'A' if legacy else 'RA'
    material = graph.material
    material['hgt_sdf_channel'] = channel
    material['hgt_sdf_encoding'] = info['encoding']
    material['hgt_sdf_verified_encoding'] = legacy
    material['hgt_sdf_parameters'] = json.dumps(info['source_parameters'], sort_keys=True)
    material['hgt_sdf_status'] = 'legacy-alpha' if legacy else 'new-format-ra-main-shadow'
    sdf = load_image(assets.textures['face_sdf'], True, library.uid)
    mask = load_image(assets.textures['face_mask'], True, library.uid)
    # Each native body-type branch uses the resolved character resource.
    for node in tuple(factor.nodes):
        if node.type == 'UVMAP':
            node.uv_map = 'UV0'
        if node.type != 'TEX_IMAGE':
            continue
        if node.name.startswith('Face_Lightmap'):
            # Native -U needs wrapping; EXTEND clamps it to the first column.
            node.image = sdf
            node['hgt_texture_role'] = 'face_sdf'
            node.extension = 'REPEAT'
            configure_mapping(node, assets.texture_settings['face_sdf'])
            targets = [link.to_socket for link in node.outputs['Color'].links]
            value = node.outputs['Alpha']
            if not legacy:
                split = factor.nodes.new('ShaderNodeSeparateColor')
                split.name = 'HGT • SDF Channels'
                factor.links.new(node.outputs['Color'], split.inputs[0])
                combined = factor.nodes.new('ShaderNodeMath')
                combined.name = 'HGT • SDF R+A'
                combined.operation = 'ADD'
                factor.links.new(split.outputs['Red'], combined.inputs[0])
                factor.links.new(node.outputs['Alpha'], combined.inputs[1])
                half = factor.nodes.new('ShaderNodeMath')
                half.name = 'HGT • SDF Half'
                half.operation = 'MULTIPLY'
                half.inputs[1].default_value = 0.5
                factor.links.new(combined.outputs[0], half.inputs[0])
                value = half.outputs[0]
            for socket in targets:
                factor.links.new(value, socket)
        elif node.name == 'Face_Shadow':
            _mask_node(factor, node, mask, assets.texture_settings['face_mask'])
    for node in tuple(tree.nodes):
        if node.type == 'TEX_IMAGE' and node.name == 'Face_Shadow':
            _mask_node(tree, node, mask, assets.texture_settings['face_mask'])
    if not legacy:
        # This old green eye mask is not valid for the new atlas.
        for link in tuple(factor.nodes['Separate RGB'].outputs['Green'].links):
            socket = link.to_socket
            factor.links.remove(link)
            socket.default_value = 1
    material['hgt_sdf_legacy_eye_mask'] = legacy
    alpha = shader.inputs['Diffuse Alpha']
    for link in tuple(alpha.links):
        graph.tree.links.remove(link)
    alpha.default_value = 1  # The common PMX surface applies coverage once.
    shader.inputs['Face Shadow Softness'].default_value = library.root.hgt_character.face_softness
