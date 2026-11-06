"""Cache a GPU draw of the character layer; never use the full image as source."""
import time

import bpy
from bpy.app.handlers import persistent

TAG = 'hgt_glow_preview'
_records = {}
_handler = None
_drawing = False
_preparing = False


def _value(nodes, role, value):
    socket = nodes[role].outputs[0]
    if socket.default_value != value:socket.default_value = value


def _object_shading(obj):
    return (tuple(obj.color), obj.pass_index, obj.hide_render, obj.hide_viewport,
            tuple(s.material.as_pointer() if s.material else 0 for s in obj.material_slots))


def _collections(scene):
    from .glow_source import base_layer, TAG as SOURCE_TAG
    layer = base_layer(scene)
    values = []
    def visit(current):
        collection = current.collection
        if collection.get(SOURCE_TAG):return
        values.append((collection.as_pointer(), current.exclude, current.holdout, current.indirect_only,
                       current.hide_viewport, collection.hide_viewport, collection.hide_render,
                       tuple(sorted((o.as_pointer(), o.hide_get(view_layer=layer)) for o in collection.objects))))
        for child in current.children:visit(child)
    visit(layer.layer_collection)
    return tuple(values)


def _nodes(scene):
    tree = scene.compositing_node_group
    return {n.get(TAG): n for n in tree.nodes if n.get(TAG)} if tree else {}


def invalidate(scene):
    record = _records.setdefault(scene.as_pointer(), {})
    record['revision'] = record.get('revision', 0) + 1
    record['dirty'] = True
    nodes = _nodes(scene)
    if 'ready' in nodes:_value(nodes, 'ready', 0)


def _key(scene, area, region, record):
    view = area.spaces.active.region_3d
    shading = area.spaces.active.shading
    uniforms = tuple((k, tuple(v) if hasattr(v, '__len__') and not isinstance(v, str) else v)
                     for k, v in scene.items() if k.startswith('hgt_') and k != 'hgt_glow'
                     and (isinstance(v, (int, float, str, list, tuple)) or hasattr(v, 'to_list')))
    return (area.as_pointer(), region.width, region.height, record.get('revision', 0),
            scene.frame_current, scene.frame_subframe, tuple(x for row in view.view_matrix for x in row),
            tuple(x for row in view.window_matrix for x in row), shading.type,
            shading.use_scene_world, shading.use_scene_lights,
            shading.use_scene_world_render, shading.use_scene_lights_render,
            shading.studio_light, shading.studiolight_rotate_z, shading.studiolight_intensity, uniforms)


def _draw():
    global _drawing
    if _drawing or bpy.app.is_job_running('RENDER'):return
    context = bpy.context
    scene, area, region = context.scene, context.area, context.region
    if not area or area.type != 'VIEW_3D' or not region or region.type != 'WINDOW':return
    from . import glow
    if not glow.is_active(scene) or area.spaces.active.shading.type not in {'MATERIAL', 'RENDERED'}:return
    record = _records.get(scene.as_pointer())
    if not record or not record.get('prepared'):return
    key = _key(scene, area, region, record)
    if record.get('uniforms') != key[-1]:
        record['dirty'], record['prepared'] = True, False
        return
    if record.get('pending') or record.get('key') == key and not record.get('settle'):return
    if record.get('capture_key') != key:
        record['capture_key'], record['passes'] = key, 0
    # Eevee can return the previous shader while compilation is asynchronous.
    # Capture again after it finishes, then stop drawing the unchanged source.
    if record['passes'] and bpy.app.is_job_running('SHADER_COMPILATION'):return
    import gpu
    import numpy as np
    _drawing = True
    space = area.spaces.active
    old = space.shading.use_compositor
    overlays = space.overlay.show_overlays
    try:
        # Disable the compositor only for this isolated draw, preventing recursion.
        space.shading.use_compositor = 'DISABLED'
        space.overlay.show_overlays = False
        buffer = record.get('buffer')
        if buffer is None or record.get('size') != (region.width, region.height):
            if buffer:buffer.free()
            buffer = gpu.types.GPUOffScreen(region.width, region.height, format='RGBA16F')
            record['buffer'], record['size'] = buffer, (region.width, region.height)
        layer = scene.view_layers.get(scene.hgt_glow.render_layer)
        started = time.perf_counter()
        buffer.draw_view3d(scene, layer, space, region, space.region_3d.view_matrix,
                          space.region_3d.window_matrix, do_color_management=False, draw_background=False)
        pixels = np.array(buffer.texture_color.read(), dtype=np.float32).ravel()
        record['pending'] = (key, region.width, region.height, pixels)
        record['draws'] = record.get('draws', 0) + 1
        record['passes'] += 1
        record['milliseconds'] = (time.perf_counter() - started) * 1000
    except (RuntimeError, ValueError, ReferenceError) as exc:
        if isinstance(exc, ReferenceError):
            record.pop('buffer', None)
            record.pop('size', None)
        record['error'] = '人物辉光视口绘制失败：' + str(exc)
        record['prepared'] = False
    finally:
        space.shading.use_compositor = old
        space.overlay.show_overlays = overlays
        _drawing = False


def _timer():
    global _preparing
    if _drawing or bpy.app.is_job_running('RENDER'):return .1
    from . import glow, glow_source
    for scene in bpy.data.scenes:
        effect = glow.node(scene)
        if effect and effect.get(glow.OWNER) != scene and not effect.mute:
            next(n for n in glow._private_tree(scene).nodes if n.get(glow.TAG)).mute = True
        if not glow.is_active(scene):continue
        nodes = _nodes(scene)
        if not {'image', 'ready', 'render'} <= set(nodes):continue
        record = _records.setdefault(scene.as_pointer(), {})
        views = [(w, a, next((r for r in a.regions if r.type == 'WINDOW'), None))
                 for w in bpy.context.window_manager.windows if w.scene == scene
                 for a in w.screen.areas if a.type == 'VIEW_3D'
                 and a.spaces.active.shading.type in {'MATERIAL', 'RENDERED'}]
        if len(views) != 1:
            _value(nodes, 'ready', 0)
            record['prepared'] = False
            record.pop('key', None)
            if len(views) > 1:scene.hgt_glow.error = '人物辉光实时预览请使用单个 3D 视图'
            continue
        window, area, region = views[0]
        if not region:continue
        try:
            if record.get('error'):raise RuntimeError(record.pop('error'))
            if record.pop('dirty', False) or not record.get('prepared'):
                _preparing = True
                try:
                    with bpy.context.temp_override(window=window, area=area):
                        layer = glow_source.sync(scene)
                        with bpy.context.temp_override(view_layer=layer):bpy.context.evaluated_depsgraph_get().update()
                finally:_preparing = False
                record['object_shading'] = {o.as_pointer(): _object_shading(o) for o in scene.objects}
                record['collections'] = _collections(scene)
                record['uniforms'] = _key(scene, area, region, record)[-1]
                record['prepared'] = True
            key = _key(scene, area, region, record)
            pending = record.pop('pending', None)
            if pending and pending[0] == key:
                _, width, height, pixels = pending
                image = bpy.data.images.get(record.get('image', ''))
                saved = nodes['image'].image
                if image is None and saved and saved.get(TAG) == scene.hgt_glow.scope_id:image = saved
                if image is None or tuple(image.size) != (width, height):
                    if image and nodes['image'].image == image:nodes['image'].image = None
                    if image and image.users == 0:bpy.data.images.remove(image)
                    image = bpy.data.images.new('HGT • Character Glow Preview', width=width, height=height,
                                                alpha=True, float_buffer=True)
                    image[TAG] = scene.hgt_glow.scope_id
                    image.alpha_mode = 'PREMUL'
                record['image'] = image.name
                image.pixels.foreach_set(pixels)
                image.update()
                image.update_tag()
                nodes['image'].image = None
                nodes['image'].image = image
                scene.compositing_node_group.update_tag()
                record['key'] = key
                record['settle'] = record['passes'] < 2 or bpy.app.is_job_running('SHADER_COMPILATION')
                _value(nodes, 'ready', 1)
                if scene.hgt_glow.error.startswith('人物辉光'):
                    scene.hgt_glow.error = ''
                area.tag_redraw()
            elif record.get('key') != key:
                _value(nodes, 'ready', 0)
                area.tag_redraw()
            elif record.get('settle'):
                area.tag_redraw()
        except (ValueError, RuntimeError, ReferenceError) as exc:
            scene.hgt_glow.error = '人物辉光预览未就绪：' + str(exc)
            _value(nodes, 'ready', 0)
            record['prepared'] = False
    return .05


@persistent
def changed(scene, depsgraph):
    if _drawing or _preparing:return
    from .glow_source import TAG as SOURCE_TAG
    if depsgraph.view_layer.get(SOURCE_TAG):return
    from . import glow
    if not glow.is_active(scene):return
    record = _records.setdefault(scene.as_pointer(), {})
    shades = record.setdefault('object_shading', {})
    dirty = False
    types = (bpy.types.Mesh, bpy.types.Armature, bpy.types.Material, bpy.types.Light, bpy.types.World)
    collections_changed = False
    for update in depsgraph.updates:
        data = update.id.original
        if isinstance(data, bpy.types.Object):
            # Compositor edits mark every object's shading dirty. They do not
            # change our source image; only real object changes invalidate it.
            signature = _object_shading(data)
            pointer = data.as_pointer()
            dirty |= update.is_updated_transform or update.is_updated_geometry or shades.get(pointer) != signature
            shades[pointer] = signature
        else:
            collections_changed |= isinstance(data, bpy.types.Collection) and not data.get(SOURCE_TAG)
            dirty |= isinstance(data, types) or isinstance(data, bpy.types.NodeTree) and data.type == 'SHADER'
    if collections_changed:
        signature = _collections(scene)
        dirty |= signature != record.get('collections')
        record['collections'] = signature
    if dirty:invalidate(scene)


def clear(scene=None):
    keys = [scene.as_pointer()] if scene else list(_records)
    for key in keys:
        record = _records.pop(key, {})
        if record.get('buffer'):
            try:record['buffer'].free()
            except ReferenceError:
                # Closing its window already frees the OpenGL context/buffer.
                pass
        image = bpy.data.images.get(record.get('image', ''))
        if image:
            for tree in bpy.data.node_groups:
                for n in tree.nodes:
                    if n.get(TAG) == 'image' and n.image == image:n.image = None
            if image.users == 0:bpy.data.images.remove(image)


@persistent
def reset(_):
    clear()


def register():
    global _handler
    if changed not in bpy.app.handlers.depsgraph_update_post:bpy.app.handlers.depsgraph_update_post.append(changed)
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre, bpy.app.handlers.exit_pre):
        if reset not in handlers:handlers.append(reset)
    if not bpy.app.background:
        _handler = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL')
        bpy.app.timers.register(_timer, first_interval=.1, persistent=True)


def unregister():
    global _handler
    if changed in bpy.app.handlers.depsgraph_update_post:bpy.app.handlers.depsgraph_update_post.remove(changed)
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre, bpy.app.handlers.exit_pre):
        if reset in handlers:handlers.remove(reset)
    if bpy.app.timers.is_registered(_timer):bpy.app.timers.unregister(_timer)
    if _handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handler, 'WINDOW')
        _handler = None
    clear()
