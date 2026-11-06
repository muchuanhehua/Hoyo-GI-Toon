"""Native glare modes and an owned, optional convolution image."""
from math import exp

import bpy

IMAGE_TAG = 'hgt_glow_default_kernel'
NODE_TAG = 'hgt_glow_kernel_image'
MODE_ITEMS = (
    ('Bloom', '辉光', '高亮周围的柔和辉光'),
    ('Ghosts', '鬼影', '高亮产生的镜头鬼影'),
    ('Streaks', '光条', '高亮向外延伸的放射光条'),
    ('Fog Glow', '雾辉光', '更柔和的雾状扩散'),
    ('Simple Star', '简单星芒', '十字或对角星芒'),
    ('Sun Beams', '阳光束', '从指定画面位置向外延伸的光束'),
    ('Kernel', '卷积核', '使用默认柔光核或自选图像扩散高亮'),
)
SIZE_MODES = {'Bloom', 'Fog Glow', 'Sun Beams'}
CONTROLS = {
    'Ghosts': (('Iterations', 'iterations'), ('Color Modulation', 'color_modulation')),
    'Streaks': (('Streaks', 'streaks'), ('Streaks Angle', 'angle'), ('Iterations', 'iterations'),
                ('Fade', 'fade'), ('Color Modulation', 'color_modulation')),
    'Simple Star': (('Iterations', 'iterations'), ('Fade', 'fade'), ('Diagonal', 'diagonal')),
    'Sun Beams': (('Sun Position', 'sun_position'),),
}


def glare(effect):
    tree = effect.node_tree
    native = tree.nodes.get('Bloom') if tree else None
    if not native or native.bl_idname != 'CompositorNodeGlare':
        raise ValueError('辉光原生节点已改变，请恢复 GI-Toon 辉光组')
    return native


def _values(settings):
    return {'Type': settings.mode,
            **{name: getattr(settings, field) for name, field in CONTROLS.get(settings.mode, ())},
            **({'Kernel Data Type': 'Color'} if settings.mode == 'Kernel' else {})}


def validate(effect, settings):
    native = glare(effect)
    image_node = next((n for n in effect.node_tree.nodes if n.get(NODE_TAG)), None)
    if image_node and image_node.bl_idname != 'CompositorNodeImage':
        raise ValueError('辉光卷积图像节点已改变，请恢复原图像节点')
    for name in _values(settings):
        socket = native.inputs.get(name)
        if socket is None:
            raise ValueError('当前 Blender 缺少辉光模式输入：' + name)
        if socket.is_linked:
            raise ValueError('辉光模式参数已手动连接，请先断开：' + name)
    if settings.mode != 'Kernel':return
    socket = next((s for s in native.inputs if s.name == 'Kernel' and s.type == 'RGBA'), None)
    if not socket:
        raise ValueError('当前 Blender 不支持图像卷积核')
    if socket.is_linked and not socket.links[0].from_node.get(NODE_TAG):
        raise ValueError('卷积核已手动连接，请先断开该连接')
    image = settings.kernel_image
    if image and (image.size[0] == 0 or image.size[1] == 0):
        raise ValueError('卷积图像无法读取，请重新选择或关联图像')


def _default_image():
    image = next((i for i in bpy.data.images if i.get(IMAGE_TAG) == 1), None)
    if image:return image
    image = bpy.data.images.new('GI-Toon • 默认柔光核', width=65, height=65, alpha=True, float_buffer=True)
    image[IMAGE_TAG] = 1
    pixels = []
    for y in range(-32, 33):
        for x in range(-32, 33):
            value = exp(-8 * (x * x + y * y) / (32 * 32))
            pixels.extend((value, value, value, 1))
    image.pixels.foreach_set(pixels)
    image.update()
    # Keep float kernel values in the blend; no external file is required.
    image.file_format = 'OPEN_EXR'
    image.pack()
    return image


def _same(socket, value):
    current = socket.default_value
    if isinstance(value, (int, float)):
        return abs(current - value) < 1e-6
    if isinstance(value, str):return current == value
    return tuple(current) == tuple(value)


def configure(effect, settings):
    validate(effect, settings)
    native = glare(effect)
    values = _values(settings)
    image_node = next((n for n in effect.node_tree.nodes if n.get(NODE_TAG)), None)
    image = (settings.kernel_image or _default_image()) if settings.mode == 'Kernel' else None
    changed = any(not _same(native.inputs[name], value) for name, value in values.items())
    changed |= image is not None and (not image_node or image_node.image != image)
    if not changed:return
    # Copying a shared parent compositor does not copy its nested kernel.
    if effect.node_tree.library or effect.node_tree.users > 1:
        effect.node_tree = effect.node_tree.copy()
        native = glare(effect)
        image_node = next((n for n in effect.node_tree.nodes if n.get(NODE_TAG)), None)
    for name, value in values.items():
        if not _same(native.inputs[name], value):native.inputs[name].default_value = value
    if image is None:return
    if not image_node:
        image_node = effect.node_tree.nodes.new('CompositorNodeImage')
        image_node[NODE_TAG] = True
        image_node.label = '卷积图像'
        image_node.location = (-650, -350)
    if image_node.image != image:image_node.image = image
    socket = next(s for s in native.inputs if s.name == 'Kernel' and s.type == 'RGBA')
    if not socket.is_linked:effect.node_tree.links.new(image_node.outputs['Image'], socket)


def clear_unused():
    for image in tuple(bpy.data.images):
        if image.get(IMAGE_TAG) and image.users == 0:bpy.data.images.remove(image)
