"""Direct tangent maps and source-selected height maps for native toon paths."""
import bpy

WORLD_NORMAL = 'HGT Height Normal'


def _world_input(tree):
    socket = tree.interface.new_socket(name=WORLD_NORMAL, in_out='INPUT', socket_type='NodeSocketVector')
    socket.default_value = (0, 0, 1)
    node = tree.nodes.new('NodeGroupInput')
    node.name = 'HGT Height Normal Input'
    return node.outputs[WORLD_NORMAL]


def _has_normal(tree):
    return tree.get('hgt_upstream') == 'Optimized Normal Map' or any(
        n.type == 'GROUP' and n.node_tree and _has_normal(n.node_tree) for n in tree.nodes)


def _replace(tree, source, owner):
    for node in tree.nodes:
        if node.type != 'GROUP' or not node.node_tree or not _has_normal(node.node_tree):
            continue
        if node.node_tree.get('hgt_upstream') == 'Optimized Normal Map':
            for output in node.outputs:
                for link in tuple(output.links):
                    tree.links.new(source, link.to_socket)
            continue
        copied = node.node_tree.copy()
        copied.use_fake_user = False
        copied['hgt_owner'] = owner
        node.node_tree = copied
        child_input = _world_input(copied)
        _replace(copied, child_input, owner)
        tree.links.new(source, node.inputs[WORLD_NORMAL])


def apply(graph):
    mode = graph.assets.features['normal']
    if graph.body is None:
        return
    strength = graph.assets.features['normal_strength']
    graph.body.inputs['Use Normal Map'].default_value = (min(abs(strength), 1) if mode == 'tangent'
                                                        else int(mode == 'height'))
    if mode != 'height':
        return
    uv = graph.uv(graph.assets.features['normal_uv'])
    texture = graph.texture('normal_package', vector=uv)
    height = graph.channels(texture)[graph.assets.features['normal_channel']]
    node = graph.node('ShaderNodeBump', 'Packed Height Normal')
    graph.link(height, node.inputs['Height'])
    node.inputs['Strength'].default_value = 1
    offset = abs(graph.assets.floats.get('_NormalMapOffset', 0))
    if offset == 0:
        # The derivative spacing is one source texel when no explicit spacing
        # was exported, not a character-dependent world-space displacement.
        offset = 1 / max(1, max(texture.image.size))
    node.inputs['Distance'].default_value = abs(strength) * offset
    node.invert = strength < 0
    graph.normal_override = node.outputs['Normal']
    tree = graph.body.node_tree
    source = _world_input(tree)
    if not _has_normal(tree):
        raise ValueError('原生着色资源缺少着色法线接口')
    _replace(tree, source, graph.owner)
    graph.link(node.outputs['Normal'], graph.body.inputs[WORLD_NORMAL])
    graph.material['hgt_normal_encoding'] = 'source height; no geometry displacement'
