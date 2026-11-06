"""Owned character glare, with reversible graph and viewport changes.

Defaults and viewport behaviour follow the author's MAVR glow module.
"""
import json

import bpy
from bpy.app.handlers import persistent

TAG = 'hgt_glow'
HELPER = 'hgt_glow_helper'
CREATED_TREE = 'hgt_glow_created_tree'
INTERFACE = 'hgt_glow_output_socket'
VIEWPORT = 'hgt_glow_viewport'
NAME = 'HGT • Bloom'
KERNEL = 'hgt_glow_kernel'
OWNER = 'hgt_glow_scene'
_VIEW_CACHE = {}


def node(scene):
    tree = scene.compositing_node_group
    return next((n for n in tree.nodes if n.get(TAG)), None) if tree else None


def is_active(scene):
    effect = node(scene)
    return bool(effect and not effect.mute and effect.get(OWNER) == scene and effect.inputs.get('Glow Source'))


def _image_socket(sockets):
    image = sockets.get('Image')
    if image is not None and image.type == 'RGBA':
        return image
    colors = [s for s in sockets if s.type == 'RGBA']
    if len(colors) != 1:
        raise ValueError('合成器图像输出不明确，请连接 Image 输出')
    return colors[0]


def _parameters(effect, settings):
    if effect.bl_idname != 'CompositorNodeGroup' or not effect.node_tree or not effect.node_tree.get(KERNEL):
        raise ValueError('辉光节点类型已改变，请恢复 GI-Toon 辉光组')
    values = {'Threshold': settings.threshold, 'Strength': settings.strength, 'Size': settings.size}
    for name in values:
        if effect.inputs.get(name) is None:
            raise ValueError('当前 Blender 不支持辉光输入：' + name)
        if effect.inputs[name].is_linked:
            raise ValueError('辉光参数已手动连接，请先断开：' + name)
    return values


def _configure(effect, values):
    for name, value in values.items():
        socket = effect.inputs[name]
        if socket.default_value != value:
            socket.default_value = value


def _private_tree(scene):
    tree = scene.compositing_node_group
    if tree and (tree.library or tree.users > 1):
        tree = tree.copy()
        scene.compositing_node_group = tree
    return tree


def update(scene):
    effect = node(scene)
    if effect:
        from . import glow_modes
        values = _parameters(effect, scene.hgt_glow)
        glow_modes.validate(effect, scene.hgt_glow)
        tree = _private_tree(scene)
        effect = next(n for n in tree.nodes if n.get(TAG))
        glow_modes.configure(effect, scene.hgt_glow)
        _configure(effect, values)
    from .rendering import redraw_materials
    redraw_materials(scene)


def _helper(tree, kind):
    result = tree.nodes.new(kind)
    result[HELPER] = True
    return result


def _kernel(tree):
    tree[KERNEL] = True
    for name, kind, direction in (('Image', 'Color', 'INPUT'), ('Glow Source', 'Color', 'INPUT'), ('Threshold', 'Float', 'INPUT'),
                                   ('Strength', 'Float', 'INPUT'), ('Size', 'Float', 'INPUT'),
                                   ('Image', 'Color', 'OUTPUT')):
        tree.interface.new_socket(name=name, in_out=direction, socket_type='NodeSocket' + kind)
    inputs = tree.nodes.new('NodeGroupInput')
    output = tree.nodes.new('NodeGroupOutput')
    bloom = tree.nodes.new('CompositorNodeGlare')
    bloom.name = 'Bloom'
    for name, value in (('Type', 'Bloom'), ('Quality', 'Medium'), ('Smoothness', .1), ('Maximum', 10.0)):
        bloom.inputs[name].default_value = value
    bloom.inputs['Strength'].default_value = 1
    for name in ('Threshold', 'Size'):
        tree.links.new(inputs.outputs[name], bloom.inputs[name])
    tree.links.new(inputs.outputs['Glow Source'], bloom.inputs['Image'])
    add = tree.nodes.new('ShaderNodeMix')
    add.data_type, add.blend_type = 'RGBA', 'ADD'
    add.clamp_factor = False
    tree.links.new(inputs.outputs['Strength'], add.inputs[0])
    tree.links.new(inputs.outputs['Image'], add.inputs[6])
    tree.links.new(bloom.outputs['Glare'], add.inputs[7])
    original = tree.nodes.new('CompositorNodeSeparateColor')
    combined = tree.nodes.new('CompositorNodeSeparateColor')
    tree.links.new(inputs.outputs['Image'], original.inputs[0])
    tree.links.new(add.outputs[2], combined.inputs[0])

    def math(operation, a, b):
        node = tree.nodes.new('ShaderNodeMath')
        node.operation = operation
        for value, socket in zip((a, b), node.inputs):
            tree.links.new(value, socket)
        return node.outputs[0]

    differences = [math('SUBTRACT', a, b) for a, b in zip(combined.outputs[:3], original.outputs[:3])]
    halo = math('MAXIMUM', math('MAXIMUM', differences[0], differences[1]), differences[2])
    alpha = math('MAXIMUM', original.outputs[3], halo)
    alpha.node.use_clamp = True
    replace = tree.nodes.new('CompositorNodeSetAlpha')
    replace.inputs['Type'].default_value = 'Replace Alpha'
    tree.links.new(add.outputs[2], replace.inputs['Image'])
    tree.links.new(alpha, replace.inputs['Alpha'])
    tree.links.new(replace.outputs['Image'], output.inputs['Image'])
    inputs.location, bloom.location = (-650, 150), (-400, 150)
    original.location, combined.location = (-400, -100), (-150, -100)
    replace.location, output.location = (400, 150), (650, 150)


def _output(tree):
    outputs = [n for n in tree.nodes if n.bl_idname == 'NodeGroupOutput' and n.is_active_output]
    if len(outputs) != 1:
        raise ValueError('请先为原合成器设置一个有效的图像输出')
    target = _image_socket(outputs[0].inputs)
    if not target.is_linked:
        raise ValueError('原合成器输出未连接图像，请先连接或移除空合成器')
    return target


def enable(scene):
    if not scene.is_editable:
        raise ValueError('当前场景不可编辑，请先建立本地场景')
    if is_active(scene):
        return
    from . import glow_source
    root = glow_source.target(scene)
    glow_source.preflight(scene, root)
    if node(scene):
        disable(scene)
    original = scene.compositing_node_group
    if original:
        if original.nodes.get(NAME):
            raise ValueError('合成器已有同名节点，请先重命名：' + NAME)
        if original.nodes:
            _output(original)
        elif any(item.item_type == 'SOCKET' for item in original.interface.items_tree):
            raise ValueError('原合成器尚未完成连接，请先连接图像输出')
    shared = original and (original.library or original.users > 1)
    tree = original.copy() if shared else original
    created = tree is None
    if created:
        tree = bpy.data.node_groups.new('HGT • Compositor', 'CompositorNodeTree')
        tree[CREATED_TREE] = True
    previous_nodes = set(tree.nodes)
    interface = None
    kernel = None
    previous_compositing = scene.render.use_compositing
    source_created = False
    try:
        if not tree.nodes:
            interface = tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
            source = _helper(tree, 'CompositorNodeRLayers')
            source.location = (-400, 0)
            output = _helper(tree, 'NodeGroupOutput')
            output.location = (220, 0)
            target = output.inputs['Image']
            incoming = source.outputs['Image']
        else:
            target = _output(tree)
            incoming = target.links[0].from_socket
        effect = tree.nodes.new('CompositorNodeGroup')
        kernel = bpy.data.node_groups.new('HGT • Bloom', 'CompositorNodeTree')
        effect.node_tree = kernel
        _kernel(kernel)
        effect.name, effect.label = NAME, 'GI-Toon 辉光'
        effect[TAG] = True
        effect[OWNER] = scene
        effect['hgt_previous_compositing'] = previous_compositing
        effect.location = (target.node.location.x - 220, target.node.location.y)
        if interface:
            effect[INTERFACE] = interface.identifier
        _configure(effect, _parameters(effect, scene.hgt_glow))
        from . import glow_modes
        glow_modes.configure(effect, scene.hgt_glow)
        source_created = True
        layer = glow_source.create(scene, root)
        render = _helper(tree, 'CompositorNodeRLayers')
        render.scene, render.layer = scene, layer.name
        render['hgt_glow_preview'] = 'source'
        image = _helper(tree, 'CompositorNodeImage')
        image['hgt_glow_preview'] = 'image'
        ready = _helper(tree, 'ShaderNodeValue')
        ready['hgt_glow_preview'] = 'ready'
        ready.outputs[0].default_value = 0
        mode = _helper(tree, 'ShaderNodeValue')
        mode['hgt_glow_preview'] = 'render'
        mode.outputs[0].default_value = 1 if bpy.app.background else 0
        preview = _helper(tree, 'ShaderNodeMix')
        preview.data_type = 'RGBA'
        preview.inputs[6].default_value = (0, 0, 0, 0)
        tree.links.new(ready.outputs[0], preview.inputs[0])
        tree.links.new(image.outputs['Image'], preview.inputs[7])
        switch = _helper(tree, 'ShaderNodeMix')
        switch.data_type = 'RGBA'
        tree.links.new(mode.outputs[0], switch.inputs[0])
        tree.links.new(preview.outputs[2], switch.inputs[6])
        tree.links.new(render.outputs['Image'], switch.inputs[7])
        tree.links.new(switch.outputs[2], effect.inputs['Glow Source'])
        tree.links.new(incoming, effect.inputs['Image'])
        tree.links.new(effect.outputs['Image'], target)
        scene.compositing_node_group = tree
        scene.render.use_compositing = True
    except Exception:
        # Keep the scene and existing links untouched if construction fails.
        if 'target' in locals() and target.node in previous_nodes and 'incoming' in locals():
            tree.links.new(incoming, target)
        for added in set(tree.nodes) - previous_nodes:
            tree.nodes.remove(added)
        if kernel and kernel.users == 0:
            bpy.data.node_groups.remove(kernel)
        from . import glow_modes
        glow_modes.clear_unused()
        if interface:
            tree.interface.remove(interface)
        if created or shared:
            bpy.data.node_groups.remove(tree)
        scene.compositing_node_group = original
        scene.render.use_compositing = previous_compositing
        if source_created:
            glow_source.remove(scene)
        raise


def disable(scene):
    effect = node(scene)
    if effect is None:
        return
    if effect.bl_idname != 'CompositorNodeGroup' or len(effect.inputs['Image'].links) != 1:
        raise ValueError('辉光输入已改变，请先恢复原图像连接')
    if any(s.is_linked for s in effect.outputs if s.name != 'Image'):
        raise ValueError('其他节点正在使用辉光通道，请先断开该连接')
    from . import glow_preview, glow_source
    glow_source.preflight_remove(scene)
    helpers = {n for n in scene.compositing_node_group.nodes if n.get(HELPER)}
    source_nodes = {n for n in helpers if n.get(glow_preview.TAG) == 'source'}
    pending, connected = list(source_nodes), set(source_nodes)
    while pending:
        current = pending.pop()
        neighbours = {l.from_node for s in current.inputs for l in s.links}
        neighbours |= {l.to_node for s in current.outputs for l in s.links}
        if neighbours - helpers - {effect}:
            raise ValueError('其他节点正在使用人物辉光辅助通道，请先断开该连接')
        for other in (neighbours & helpers) - connected:
            connected.add(other)
            pending.append(other)
    tree = _private_tree(scene)
    effect = next(n for n in tree.nodes if n.get(TAG))
    previous = bool(effect['hgt_previous_compositing'])
    identifier = effect.get(INTERFACE)
    source = effect.inputs['Image'].links[0].from_socket
    kernel = effect.node_tree
    for destination in [link.to_socket for link in effect.outputs['Image'].links]:
        tree.links.new(source, destination)
    tree.nodes.remove(effect)
    if kernel and kernel.get(KERNEL) and kernel.users == 0:
        bpy.data.node_groups.remove(kernel)
    from . import glow_modes
    glow_modes.clear_unused()
    helpers = {n for n in tree.nodes if n.get(HELPER)}
    # A user may have attached nodes to a generated source. Keep its dependency
    # chain, and outputs they subsequently connected to their own nodes.
    keep = {n for n in helpers if any(link.to_node not in helpers for s in n.outputs for link in s.links)
            or any(link.from_node not in helpers for s in n.inputs for link in s.links)}
    pending = list(keep)
    while pending:
        current = pending.pop()
        adjacent = {link.from_node for s in current.inputs for link in s.links}
        adjacent |= {link.to_node for s in current.outputs for link in s.links}
        for other in (adjacent & helpers) - keep:
            keep.add(other)
            pending.append(other)
    for helper in helpers - keep:
        tree.nodes.remove(helper)
    for helper in keep:
        del helper[HELPER]
        if helper.get(glow_preview.TAG):del helper[glow_preview.TAG]
    if identifier and not keep:
        socket = next((s for s in tree.interface.items_tree if s.item_type == 'SOCKET' and s.identifier == identifier), None)
        if socket:
            tree.interface.remove(socket)
    if tree.get(CREATED_TREE) and not tree.nodes:
        scene.compositing_node_group = None
        bpy.data.node_groups.remove(tree)
    if scene.render.use_compositing:
        scene.render.use_compositing = previous
    glow_preview.clear(scene)
    glow_source.remove(scene)


def update_target(scene):
    from . import glow_source, glow_preview
    try:
        glow_source.sync(scene)
        scene.hgt_glow.error = '' if scene.hgt_glow.target else '请在角色管理中选定人物'
    except (ValueError, RuntimeError) as exc:
        scene.hgt_glow.error = str(exc)
    glow_preview.invalidate(scene)


@persistent
def render_prepare(scene, *_):
    effect = node(scene)
    if effect and effect.get(OWNER) != scene:
        next(n for n in _private_tree(scene).nodes if n.get(TAG)).mute = True
        return
    if not is_active(scene):return
    from . import glow_source, glow_preview
    glow_source.sync(scene, render=True)
    for n in scene.compositing_node_group.nodes:
        if n.get(glow_preview.TAG) == 'render':n.outputs[0].default_value = 1


@persistent
def render_finished(scene, *_):
    if not is_active(scene):return
    from . import glow_preview
    for n in scene.compositing_node_group.nodes:
        if n.get(glow_preview.TAG) == 'render':n.outputs[0].default_value = 0
    glow_preview.invalidate(scene)


def viewport(context, enabled):
    scene = context.scene
    if enabled:
        states = json.loads(scene.get(VIEWPORT, '[]'))
        for window in context.window_manager.windows:
            if window.scene != scene:
                continue
            screen = window.screen
            for area_index, area in enumerate(screen.areas):
                for space_index, space in enumerate(area.spaces):
                    if space.type != 'VIEW_3D':
                        continue
                    key = [screen.name, area_index, space_index]
                    if not any(row[:3] == key for row in states):
                        states.append([*key, space.shading.use_compositor, space.shading.type])
                    space.shading.use_compositor = 'ALWAYS'
                    if space.shading.type in {'SOLID', 'WIREFRAME'}:
                        space.shading.type = 'MATERIAL'
        scene[VIEWPORT] = json.dumps(states)
        _VIEW_CACHE[scene.name] = states
    else:
        states = json.loads(scene[VIEWPORT]) if VIEWPORT in scene else _VIEW_CACHE.get(scene.name, [])
        for screen_name, area_index, space_index, compositor, shading in states:
            screen = bpy.data.screens.get(screen_name)
            if not screen or area_index >= len(screen.areas):
                continue
            spaces = screen.areas[area_index].spaces
            if space_index >= len(spaces) or spaces[space_index].type != 'VIEW_3D':
                continue
            space = spaces[space_index]
            if space.shading.use_compositor == 'ALWAYS':
                space.shading.use_compositor = compositor
            if space.shading.type == 'MATERIAL' and shading in {'SOLID', 'WIREFRAME'}:
                space.shading.type = shading
        if VIEWPORT in scene:
            del scene[VIEWPORT]
        _VIEW_CACHE.pop(scene.name, None)
    from .rendering import redraw_materials
    redraw_materials(scene)


@persistent
def sync_undo(_):
    # Scene/node undo does not undo SpaceView3D shading. Retain its original
    # state outside the undo stack, then reconcile only effect transitions.
    for scene in bpy.data.scenes:
        active = is_active(scene)
        if active != (scene.name in _VIEW_CACHE):
            with bpy.context.temp_override(scene=scene):
                viewport(bpy.context, active)


@persistent
def on_load(_):
    _VIEW_CACHE.clear()
    for scene in bpy.data.scenes:
        effect = node(scene)
        if effect and (effect.get(OWNER) != scene or not effect.inputs.get('Glow Source')):
            next(n for n in _private_tree(scene).nodes if n.get(TAG)).mute = True
            scene.hgt_glow.error = '旧辉光已暂停，请选定人物后重新开启'
        if is_active(scene) and VIEWPORT in scene:
            _VIEW_CACHE[scene.name] = json.loads(scene[VIEWPORT])


def register():
    for handlers, function in ((bpy.app.handlers.undo_post, sync_undo),
                               (bpy.app.handlers.redo_post, sync_undo),
                               (bpy.app.handlers.render_init, render_prepare),
                               (bpy.app.handlers.render_pre, render_prepare),
                               (bpy.app.handlers.render_complete, render_finished),
                               (bpy.app.handlers.render_cancel, render_finished),
                               (bpy.app.handlers.load_post, on_load)):
        if function not in handlers:
            handlers.append(function)
    bpy.app.timers.register(_initialise, first_interval=0.0, persistent=True)


def _initialise():
    on_load(None)
    from . import glow_preview
    glow_preview.register()


def unregister():
    from . import glow_preview
    glow_preview.unregister()
    if bpy.app.timers.is_registered(_initialise):
        bpy.app.timers.unregister(_initialise)
    for handlers, function in ((bpy.app.handlers.undo_post, sync_undo),
                               (bpy.app.handlers.redo_post, sync_undo),
                               (bpy.app.handlers.render_init, render_prepare),
                               (bpy.app.handlers.render_pre, render_prepare),
                               (bpy.app.handlers.render_complete, render_finished),
                               (bpy.app.handlers.render_cancel, render_finished),
                               (bpy.app.handlers.load_post, on_load)):
        if function in handlers:
            handlers.remove(function)
    _VIEW_CACHE.clear()
