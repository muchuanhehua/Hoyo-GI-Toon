"""Apply explicit source texture transforms to owned shader image nodes."""
import math


def components(value, defaults):
    if not isinstance(value, dict):
        raise ValueError('贴图缩放与偏移必须为数字向量')
    try:
        result = tuple(float(value.get(key, default)) for key, default in zip(('X', 'Y'), defaults))
    except (TypeError, ValueError) as exc:
        raise ValueError('贴图缩放与偏移包含无效数值') from exc
    if not all(math.isfinite(v) for v in result):
        raise ValueError('贴图缩放与偏移包含非有限数值')
    return result


def configure(texture, settings):
    scale = components(settings.get('m_Scale', {}), (1, 1))
    offset = components(settings.get('m_Offset', {}), (0, 0))
    if scale == (1, 1) and offset == (0, 0):
        return
    tree = texture.id_data
    socket = texture.inputs['Vector']
    if socket.is_linked:
        vector = socket.links[0].from_socket
    else:
        uv = tree.nodes.new('ShaderNodeUVMap')
        uv.uv_map = 'UV1' if texture.name.endswith('_UV1') else 'UV0'
        vector = uv.outputs['UV']
    for operation, values in (('MULTIPLY', (*scale, 1)), ('ADD', (*offset, 0))):
        if (operation == 'MULTIPLY' and scale == (1, 1)) or (operation == 'ADD' and offset == (0, 0)):
            continue
        node = tree.nodes.new('ShaderNodeVectorMath')
        node.name = 'HGT • Source Texture ' + operation
        node.operation = operation
        tree.links.new(vector, node.inputs[0])
        node.inputs[1].default_value = values
        vector = node.outputs['Vector']
    tree.links.new(vector, socket)
