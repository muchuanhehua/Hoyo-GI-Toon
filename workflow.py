"""Import, materials and lighting are independent, reversible user actions."""
import bpy
from types import SimpleNamespace
from mathutils import Vector
from bpy.app.handlers import persistent
from . import asset_tracking, importers, lighting, outlines, rendering, shaders, project_io, gaze, material_controls, scene_models
from .pmx_materials import Catalog, DEFAULT_SHADOW_POSITION, DEFAULT_OUTLINE
_REFRESHING = False

def current(root):
    return bool(root and root.hgt_character.uid and root.hgt_character.source_root and root.hgt_character.schema_version == 2)

def build(filepath, context):
    transaction = asset_tracking.DataTransaction(context)
    try:
        batch = importers.import_character(filepath, context)
        root = scene_models.ensure(batch.model_root, context, batch.source)
        settings = root.hgt_character
        settings.imported = True
        context.view_layer.update()
        settings.camera = rendering.prepare(context.scene, root)
        project_io.stamp(root)
        context.scene.hgt_target = root
        return root
    except Exception:
        transaction.rollback()
        raise

def apply_materials(root, context):
    rendering.check_idle()
    if context.mode != 'OBJECT':
        raise ValueError('请切换到对象模式后应用材质')
    transaction = asset_tracking.DataTransaction(context)
    settings = None
    try:
        root = scene_models.ensure(root, context)
        settings = root.hgt_character
        if settings.managed:
            material_controls.upgrade(root)
            outlines.upgrade(root)
            rendering.configure_material_render(context.scene)
            refresh_character(root, scene=context.scene)
            rendering.preview_materials(context)
            return root
        settings.building = True
        context.view_layer.update()
        points = [entry.object.matrix_world @ Vector(corner) for entry in settings.meshes for corner in entry.object.bound_box]
        settings.height = max((p.z for p in points)) - min((p.z for p in points))
        if settings.height < 1e-05:
            raise ValueError('模型尺寸无效')
        catalog = Catalog(settings.source_file, settings.face_resource_directory, settings.face_sdf_preset)
        library = shaders.ShaderLibrary(root)
        controls = lighting.build(root, root.users_collection[0], [settings.source_armature], library)
        # Set new assembly defaults here; RNA fallbacks stay stable for saved scenes.
        settings.shadow_position = DEFAULT_SHADOW_POSITION
        if not settings.is_property_set('outline'):
            settings.outline = DEFAULT_OUTLINE
        settings.initial_shadow = settings.shadow_position
        settings.initial_face_softness = settings.face_softness
        settings.initial_outline = settings.outline
        built = {}
        for entry in settings.meshes:
            mesh = entry.object
            if not mesh.material_slots:
                continue
            if any((slot.material is None for slot in mesh.material_slots)):
                raise ValueError(mesh.name + ' 存在空材质槽')
            asset_tracking.derive_mesh(entry, settings.uid)
            for index, slot in enumerate(mesh.material_slots):
                original = slot.material
                if original not in built:
                    assets = catalog.resolve(original.name, original)
                    if assets.pmx['sphere_mode'] == '3' and entry.original_data.uv_layers.get('UV1') is None:
                        raise ValueError(original.name + ' 的 Sphere 需要附加 UV1')
                    generated, outline = library.build_material(assets)
                    binding = settings.bindings.add()
                    binding.source, binding.generated, binding.outline = (original, generated, outline)
                    binding.source_name, binding.role = (original.name, assets.role)
                    material_controls.initialize(binding)
                    built[original] = generated
                snap = settings.slots.add()
                snap.mesh, snap.index = (mesh, index)
                snap.original, snap.generated = (original, built[original])
                slot.material = built[original]
                entry.render_data.materials[index] = built[original]
            lighting.attach(mesh, root, controls)
            outlines.build(mesh, root)
        if not built:
            raise ValueError('模型没有可应用的材质')
        settings.has_outline = any((modifier.type == 'NODES' and modifier.node_group and modifier.node_group.get('hgt_pmx_outline') for entry in settings.meshes for modifier in entry.object.modifiers))
        library.finish()
        rendering.configure_material_render(context.scene)
        settings.managed = True
        settings.applied_sdf_preset = settings.face_sdf_preset
        settings.building = False
        project_io.stamp(root)
        refresh_character(root, scene=context.scene)
        rendering.preview_materials(context)
        return root
    except Exception:
        if settings:
            for entry in settings.meshes:
                asset_tracking.restore_mesh(entry)
            for snap in settings.slots:
                if snap.mesh and snap.index < len(snap.mesh.material_slots):
                    snap.mesh.material_slots[snap.index].material = snap.original
            settings.bindings.clear()
            settings.slots.clear()
            settings.controls.clear()
            settings.global_properties = settings.light_vectors = settings.outline_graph = None
            settings.light = settings.head = None
            settings.managed = settings.building = False
        transaction.rollback()
        raise

def change_face_sdf(root, context):
    """Rebuild only face surfaces; keep bindings, controls and source IDs intact."""
    from .face_assets import skin_material
    settings = root.hgt_character
    previous = settings.applied_sdf_preset
    originals = [(binding, binding.generated) for binding in settings.bindings
                 if binding.source and skin_material(binding.source)]
    changed, sockets, mesh_slots = [], [], []
    before = asset_tracking.data_pointers()
    settings.building = True
    try:
        rendering.check_idle()
        if not originals:
            raise ValueError('当前模型没有可绑定 SDF 的脸部皮肤材质')
        catalog = Catalog(settings.source_file, settings.face_resource_directory, settings.face_sdf_preset)
        library = shaders.ShaderLibrary(root, reuse_controls=True)
        replacements = {}
        for binding, original in originals:
            assets = catalog.resolve(binding.source_name, binding.source)
            generated, outline = library.build_material(assets)
            draft = SimpleNamespace(id_data=root, generated=generated, outline=outline, role=binding.role)
            material_controls.initialize(draft)
            for name in ('tint', 'brightness', 'saturation', 'opacity', 'shadow_color', 'outline_color'):
                value = getattr(binding, name)
                setattr(draft, name, tuple(value) if name.endswith('color') or name == 'tint' else value)
            material_controls.apply_binding(draft)
            replacements[original] = generated
        # Stage all replacements first, so a bad resource cannot partly change a character.
        for snap in settings.slots:
            if snap.generated in replacements:
                changed.append((snap, snap.generated))
                if snap.mesh and snap.index < len(snap.mesh.material_slots):
                    slot = snap.mesh.material_slots[snap.index]
                    if slot.material == snap.generated:
                        slot.material = replacements[snap.generated]
                snap.generated = replacements[snap.generated]
        for entry in settings.meshes:
            if not entry.object:
                continue
            if entry.render_data:
                for index, material in enumerate(entry.render_data.materials):
                    if material in replacements:
                        mesh_slots.append((entry.render_data, index, material))
                        entry.render_data.materials[index] = replacements[material]
            for modifier in entry.object.modifiers:
                tree = modifier.node_group if modifier.type == 'NODES' else None
                if not tree or tree.get('hgt_owner') != settings.uid:
                    continue
                for node in tree.nodes:
                    for socket in node.inputs:
                        if socket.type == 'MATERIAL' and socket.default_value in replacements:
                            sockets.append((socket, socket.default_value))
                            socket.default_value = replacements[socket.default_value]
        for binding, original in originals:
            binding.generated = replacements[original]
        settings.applied_sdf_preset = settings.face_sdf_preset
        settings.preview_error = ''
        library.finish()
    except Exception as error:
        for binding, original in originals:
            binding.generated = original
        for socket, original in sockets:
            socket.default_value = original
        for mesh, index, original in mesh_slots:
            mesh.materials[index] = original
        for snap, original in changed:
            if snap.mesh and snap.index < len(snap.mesh.material_slots):
                slot = snap.mesh.material_slots[snap.index]
                if slot.material == snap.generated:
                    slot.material = original
            snap.generated = original
        settings.face_sdf_preset = previous
        settings.applied_sdf_preset = previous
        settings.preview_error = str(error)
        bpy.data.batch_remove(ids={item for values in asset_tracking.new_data(before).values() for item in values})
        raise
    finally:
        settings.building = False
    asset_tracking.remove_render_data(settings.uid)
    shaders.set_controls(root)
    rendering.preview_materials(context)


def refresh_character(root, depsgraph=None, scene=None, appearance=True):
    global _REFRESHING
    if _REFRESHING or not current(root) or root.hgt_character.building:
        return
    _REFRESHING = True
    try:
        settings = root.hgt_character
        scene = scene or next((s for s in bpy.data.scenes if root.name in s.objects), bpy.context.scene)
        if scene.hgt_light and settings.light_source != scene.hgt_light:
            settings.light_source = scene.hgt_light
        if settings.look_camera:
            gaze.update_gaze(root, scene)
        if settings.managed:
            lighting.update(root, depsgraph=depsgraph, scene=scene)
            if appearance:
                material_controls.apply(root)
                for entry in settings.meshes:
                    if entry.object:
                        outlines.update(entry.object, root)
    finally:
        _REFRESHING = False

def restore(root):
    if not current(root) or not root.hgt_character.managed:
        raise ValueError('请先应用材质')
    settings = root.hgt_character
    settings.building = True
    for snap in settings.slots:
        if snap.mesh and snap.index < len(snap.mesh.material_slots):
            slot = snap.mesh.material_slots[snap.index]
            if slot.material == snap.generated:
                slot.material = snap.original
    for entry in settings.meshes:
        for modifier in tuple(entry.object.modifiers):
            if modifier.type == 'NODES' and modifier.node_group and (modifier.node_group.get('hgt_owner') == settings.uid):
                entry.object.modifiers.remove(modifier)
        asset_tracking.restore_mesh(entry)
    settings.slots.clear()
    settings.bindings.clear()
    settings.controls.clear()
    settings.global_properties = settings.light_vectors = settings.outline_graph = None
    settings.light = settings.head = None
    settings.managed = False
    settings.building = False
    asset_tracking.remove_render_data(settings.uid)
    shaders.remove_controls(root)

@persistent
def update_scene(scene, depsgraph=None):
    scene_models.sync_active(scene)
    for obj in tuple(scene.objects):
        if current(obj):
            refresh_character(obj, depsgraph, scene, appearance=False)


@persistent
def update_frame(scene, depsgraph=None):
    # A material can be reused in a scene that does not contain its source rig.
    for obj in bpy.data.objects:
        if current(obj) and obj.hgt_character.managed:
            shaders.set_controls(obj)
    for obj in tuple(scene.objects):
        if current(obj):
            refresh_character(obj, depsgraph, scene)

def register():
    bpy.app.handlers.depsgraph_update_post.append(update_scene)
    bpy.app.handlers.frame_change_post.append(update_frame)
    bpy.app.handlers.render_pre.append(update_frame)

def unregister():
    scene_models.reset_selection_cache()
    for handlers, callback in ((bpy.app.handlers.depsgraph_update_post, update_scene),
                               (bpy.app.handlers.frame_change_post, update_frame),
                               (bpy.app.handlers.render_pre, update_frame)):
        if callback in handlers:
            handlers.remove(callback)
