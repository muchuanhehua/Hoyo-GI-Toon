"""Import, materials and lighting are independent, reversible user actions."""
from pathlib import Path
import uuid
import bpy
from mathutils import Vector
from bpy.app.handlers import persistent
from . import asset_tracking, importers, lighting, outlines, rendering, shaders, project_io, gaze, material_controls
from .pmx_materials import Catalog
_REFRESHING = False

def current(root):
    return bool(root and root.hgt_character.imported and (root.hgt_character.schema_version == 2))

def build(filepath, context):
    transaction = asset_tracking.DataTransaction(context)
    try:
        batch = importers.import_character(filepath, context)
        collection = bpy.data.collections.new(Path(batch.source).stem + ' • HGT')
        context.scene.collection.children.link(collection)
        root = bpy.data.objects.new(Path(batch.source).stem, None)
        collection.objects.link(root)
        settings = root.hgt_character
        settings.uid = uuid.uuid4().hex
        settings.source_file = batch.source
        settings.source_format = 'pmx'
        settings.schema_version = 2
        settings.source_root, settings.source_armature = (batch.model_root, batch.armature)
        root['hgt_owner'] = collection['hgt_owner'] = settings.uid
        for obj in batch.objects:
            obj['hgt_owner'] = settings.uid
            if obj.type == 'MESH' and getattr(obj, 'mmd_type', '') not in {'RIGID_BODY', 'JOINT'}:
                entry = settings.meshes.add()
                entry.object = obj
                entry.original_hidden, entry.original_view_hidden = (obj.hide_render, obj.hide_get())
        settings.imported = True
        rendering.prepare(context.scene, root, collection)
        project_io.stamp(root)
        context.scene.hgt_target = root
        return root
    except Exception:
        transaction.rollback()
        raise

def apply_materials(root, context):
    if not current(root):
        raise ValueError('请先导入 PMX 模型')
    settings = root.hgt_character
    if settings.managed:
        refresh_character(root)
        return root
    transaction = asset_tracking.DataTransaction(context)
    settings.building = True
    try:
        context.view_layer.update()
        points = [entry.object.matrix_world @ Vector(corner) for entry in settings.meshes for corner in entry.object.bound_box]
        settings.height = max((p.z for p in points)) - min((p.z for p in points))
        if settings.height < 1e-05:
            raise ValueError('模型尺寸无效')
        catalog = Catalog(settings.source_file)
        library = shaders.ShaderLibrary(root)
        controls = lighting.build(root, root.users_collection[0], [settings.source_armature], library)
        settings.shadow_position = library.groups['Global Material Properties'].nodes['Global Properties'].inputs['Shadow Position'].default_value
        settings.initial_shadow = settings.shadow_position
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
        settings.managed = True
        settings.building = False
        project_io.stamp(root)
        refresh_character(root)
        return root
    except Exception:
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

def refresh_character(root, depsgraph=None):
    global _REFRESHING
    if _REFRESHING or not current(root) or root.hgt_character.building:
        return
    _REFRESHING = True
    try:
        settings = root.hgt_character
        if settings.look_camera:
            scene = next((s for s in bpy.data.scenes if root.name in s.objects and s.hgt_target == root), bpy.context.scene)
            gaze.update_gaze(root, scene)
        if settings.managed:
            lighting.update(root)
            material_controls.apply(root)
            for entry in settings.meshes:
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

@persistent
def update_scene(scene, depsgraph=None):
    for obj in tuple(scene.objects):
        if current(obj):
            refresh_character(obj, depsgraph)

def register():
    bpy.app.handlers.depsgraph_update_post.append(update_scene)
    bpy.app.handlers.frame_change_post.append(update_scene)

def unregister():
    for handlers in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.frame_change_post):
        if update_scene in handlers:
            handlers.remove(update_scene)
