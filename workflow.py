"""Build and update a scoped character, preserving the imported source data."""
from pathlib import Path
import json
import uuid
import bpy
from bpy.app.handlers import persistent
from mathutils import Vector
from .asset_resolver import AssetCatalog, source_name
from . import asset_tracking, importers, lighting, outlines, rendering, shaders

_REFRESHING = False


def bounds(objects):
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:
        raise ValueError("角色没有可用的包围盒")
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    return low, high


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
    root["hgt_import"] = json.dumps({"operator": batch.operator, "parameters": batch.parameters})
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
                # Named effect overlays are retained with their original data.
                # Their visibility is restored together with the render assembly.
                if source_name(obj.name).casefold() in {"effectmesh", "eyestar"}:
                    obj.hide_render = True
                    obj.hide_set(True)
        visible = [e.object for e in settings.meshes if not e.object.hide_render]
        low, high = bounds(visible)
        settings.height = max(0.01, high.z - low.z)
        library = shaders.ShaderLibrary(root)
        controls = lighting.build(root, collection, batch.objects, library)
        built = {}
        for entry in settings.meshes:
            mesh = entry.object
            if mesh.hide_render:
                continue
            candidates = [(i, s.material) for i, s in enumerate(mesh.material_slots)
                          if s.material and is_character_material(s.material)]
            if not candidates:
                continue
            if any(slot.material is None for slot in mesh.material_slots):
                raise ValueError(f"{mesh.name} 的材质槽为空，请检查 FBX 材质")
            asset_tracking.derive_mesh(entry, settings.uid)
            for index, original in candidates:
                key = original.as_pointer()
                if key not in built:
                    assets = catalog.resolve(original.name, original)
                    generated, outline = library.build_material(assets)
                    built[key] = generated
                    binding = settings.bindings.add()
                    binding.source, binding.generated, binding.outline = original, generated, outline
                    binding.source_name, binding.role = assets.source, assets.role
                snap = settings.slots.add()
                snap.mesh, snap.index, snap.original, snap.generated = mesh, index, original, built[key]
                # An OBJECT-linked source slot also has to be recorded and restored.
                mesh.material_slots[index].material = built[key]
            lighting.attach(mesh, root, controls)
            outlines.build(mesh, root)
        if not built:
            raise ValueError("没有可匹配的原神角色材质，请保留 Avatar_*_Mat_* 材质名称")
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
    for handlers in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.frame_change_post):
        if update_scene in handlers:
            handlers.remove(update_scene)
