"""Build and update a scoped character, preserving the imported source data."""
from pathlib import Path
import json
import uuid
import bpy
from bpy.app.handlers import persistent
from .asset_resolver import AssetCatalog, source_name
from . import asset_tracking, importers, lighting, outlines, rendering, shaders, surface_layers, eye_surfaces, subjects

_REFRESHING = False


def build(filepath, context):
    transaction = asset_tracking.DataTransaction(context)
    try:
        batch = importers.import_character(filepath, context)
        return assemble(batch, context)
    except Exception:
        transaction.rollback()
        raise


def assemble(batch, context):
    # Repeating assembly for the same batch updates its controls, not its data IDs.
    owners = {obj.get("hgt_owner") for obj in batch.objects if obj.get("hgt_owner")}
    if len(owners) == 1:
        root = next((obj for obj in context.scene.objects
                     if obj.hgt_character.uid in owners), None)
        if root and root.hgt_character.managed:
            refresh_character(root)
            return root
    else:
        root = None
    if batch.source_format == 'pmx':
        from .pmx_materials import Catalog
        catalog = Catalog(batch.source)
    else:
        catalog = AssetCatalog(batch.source)
    transaction = asset_tracking.DataTransaction(context)
    if root:
        collection = next(c for c in root.users_collection if c.get("hgt_owner") == root.hgt_character.uid)
        root.hgt_character.meshes.clear()
    else:
        collection = bpy.data.collections.new(Path(batch.source).stem)
        context.scene.collection.children.link(collection)
        root = bpy.data.objects.new(Path(batch.source).stem, None)
        collection.objects.link(root)
    original_collections = {obj: tuple(obj.users_collection) for obj in batch.objects}
    original_tags = {obj: obj.get("hgt_owner") for obj in batch.objects}
    settings = root.hgt_character
    settings.building = True
    settings.uid = settings.uid or uuid.uuid4().hex
    settings.source_file = batch.source
    settings.source_format = batch.source_format
    settings.source_root, settings.source_armature = batch.model_root, batch.armature
    root["hgt_import"] = json.dumps({"operator": batch.operator, "parameters": batch.parameters,
                                    "format": batch.source_format})
    collection["hgt_owner"] = settings.uid
    try:
        for obj in batch.objects:
            for old in tuple(obj.users_collection):
                old.objects.unlink(obj)
            collection.objects.link(obj)
            obj["hgt_owner"] = settings.uid
            if obj.type == "MESH":
                entry = settings.meshes.add()
                entry.object = obj
                entry.original_hidden = obj.hide_render
                entry.original_view_hidden = obj.hide_get()
                if batch.source_format == 'pmx':
                    helper = getattr(obj, 'mmd_type', '') in {'RIGID_BODY', 'JOINT'}
                    entry.participation = 'helper' if helper else 'surface'
                    entry.participation_basis = 'MMD object type'
                else:
                    entry.participation, entry.participation_basis = surface_layers.participation(obj)
                # Preview participation never deletes geometry or changes its rig.
                # Permanent Avatar surfaces keep rendering even if named EffectMesh.
                if entry.participation != 'surface':
                    obj.hide_render = True
                    obj.hide_set(True)
        subjects.initialize(root)
        low, high = rendering.character_bounds(root)
        settings.height = max(0.01, high.z - low.z)
        library = shaders.ShaderLibrary(root)
        controls = lighting.build(root, collection, batch.objects, library)
        built = {}
        for entry in settings.meshes:
            mesh = entry.object
            if not entry.render_data:
                continue
            candidates = [(i, s.material) for i, s in enumerate(mesh.material_slots)
                          if s.material and (batch.source_format == 'pmx' or is_character_material(s.material)
                                             or source_name(s.material.name).casefold() in catalog.materials)
                          and any(p.object==mesh and p.role in {'BODY','WEAPON','GLIDER'} and not p.locked
                                  and i in json.loads(p.source_slots) for p in settings.parts)]
            if not candidates:
                continue
            if any(slot.material is None for slot in mesh.material_slots):
                raise ValueError(f"{mesh.name} 的材质槽为空，请检查模型材质")
            asset_tracking.derive_mesh(entry, settings.uid)
            for index, original in candidates:
                assets = catalog.resolve(original.name, original)
                if (assets.source_format == 'pmx' and assets.pmx['sphere_mode'] == '3'
                        and entry.original_data.uv_layers.get('UV1') is None):
                    raise ValueError(f'{original.name} 的 Sphere 子贴图需要原模型的附加 UV1')
                key = original.as_pointer()
                if key not in built:
                    generated, outline = library.build_material(assets)
                    built[key] = generated
                    binding = settings.bindings.add()
                    binding.source, binding.generated, binding.outline = original, generated, outline
                    binding.source_name, binding.role = assets.source, assets.role
                snap = settings.slots.add()
                snap.mesh, snap.index, snap.original, snap.generated = mesh, index, original, built[key]
                # An OBJECT-linked source slot also has to be recorded and restored.
                mesh.material_slots[index].material = built[key]
                if built[key].get("hgt_expression_mask"):
                    surface_layers.mark_expression_faces(entry, index, assets)
                if built[key].get('hgt_eye_surface_mask'):
                    eye_surfaces.mark(entry, index)
                    eye_surfaces.attach(entry, built[key])
            surface_layers.attach_expression(entry, settings.uid)
            lighting.attach(mesh, root, controls)
            outlines.build(mesh, root)
        if not built:
            raise ValueError("没有可匹配的角色材质，请检查所选模型的原材质")
        library.finish()
        settings.managed = True
        settings.building = False
        rendering.prepare(context.scene, root, collection)
        context.scene.hgt_target = root
        refresh_character(root)
        for selected in context.selected_objects:
            selected.select_set(False)
        root.select_set(True)
        context.view_layer.objects.active = root
        return root
    except Exception:
        # Reattach imported IDs before removing the render transaction's collection.
        for entry in settings.meshes:
            asset_tracking.restore_mesh(entry)
            if entry.object:
                entry.object.hide_render = entry.original_hidden
                entry.object.hide_set(entry.original_view_hidden)
        for snap in settings.slots:
            if snap.mesh and snap.index < len(snap.mesh.material_slots):
                snap.mesh.material_slots[snap.index].material = snap.original
        for obj, collections in original_collections.items():
            for old in tuple(obj.users_collection):
                old.objects.unlink(obj)
            for old in collections:
                old.objects.link(obj)
            if original_tags[obj] is None:
                del obj["hgt_owner"]
            else:
                obj["hgt_owner"] = original_tags[obj]
        settings.slots.clear()
        settings.bindings.clear()
        settings.controls.clear()
        subjects.clear(root)
        settings.global_properties = settings.light_vectors = settings.outline_graph = None
        settings.light = settings.head = None
        settings.managed = settings.building = False
        transaction.rollback()
        raise


def is_character_material(material):
    name = source_name(material.name)
    return name.startswith("Avatar_") and "_Mat_" in name


def refresh_character(root, depsgraph=None):
    global _REFRESHING
    if _REFRESHING or root is None:
        return
    settings = root.hgt_character
    if not settings.managed or settings.building or settings.global_properties is None:
        return
    _REFRESHING = True
    try:
        subjects.apply(root)
        lighting.update(root)
        for entry in settings.meshes:
            if entry.object:
                outlines.update(entry.object, root)
    finally:
        _REFRESHING = False


def restore(root):
    settings = root.hgt_character
    if not settings.managed:
        raise ValueError("请选择 Hoyo-GI-Toon 角色")
    settings.building = True
    for snap in settings.slots:
        if snap.mesh and snap.index < len(snap.mesh.material_slots):
            slot = snap.mesh.material_slots[snap.index]
            if slot.material == snap.generated:
                slot.material = snap.original
    for entry in settings.meshes:
        mesh = entry.object
        if not mesh:
            continue
        mesh.hide_render = entry.original_hidden
        mesh.hide_set(entry.original_view_hidden)
        for modifier in tuple(mesh.modifiers):
            if modifier.type == "NODES" and modifier.node_group and modifier.node_group.get("hgt_owner") == settings.uid:
                mesh.modifiers.remove(modifier)
        asset_tracking.restore_mesh(entry)
    settings.slots.clear()
    settings.bindings.clear()
    settings.controls.clear()
    subjects.clear(root)
    settings.global_properties = settings.light_vectors = settings.outline_graph = None
    settings.light = settings.head = None
    for scene in bpy.data.scenes:
        if scene.hgt_output.camera == settings.camera:
            scene.hgt_output.camera = None
    settings.camera = None
    settings.managed = False
    settings.building = False
    asset_tracking.remove_render_data(settings.uid)


@persistent
def update_scene(scene, depsgraph=None):
    for obj in tuple(scene.objects):
        if obj.hgt_character.managed:
            refresh_character(obj, depsgraph)


def register():
    bpy.app.handlers.depsgraph_update_post.append(update_scene)
    bpy.app.handlers.frame_change_post.append(update_scene)


def unregister():
    subjects._STATES.clear()
    for handlers in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.frame_change_post):
        if update_scene in handlers:
            handlers.remove(update_scene)
