"""Build and update a scoped character, preserving the imported source data."""
import math
from pathlib import Path
import uuid
import bpy
from bpy.app.handlers import persistent
from mathutils import Vector
from .asset_resolver import AssetCatalog
from . import importers, outlines, shaders

_REFRESHING = False


def bounds(objects):
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:
        raise ValueError("角色没有可用的包围盒")
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    return low, high


def light_direction(settings):
    a, e = settings.light_azimuth, settings.light_elevation
    return Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))


def _make_rig(root, collection, imported):
    settings = root.hgt_character
    sun_data = bpy.data.lights.new(f"HGT • {root.name} • 主光", "SUN")
    sun = bpy.data.objects.new(sun_data.name, sun_data)
    collection.objects.link(sun)
    sun["hgt_owner"] = settings.uid
    settings.light = sun
    armatures = [obj for obj in imported if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        raise ValueError("角色需要唯一骨架；请单独导出角色后导入")
    armature = armatures[0]
    heads = [b for b in armature.pose.bones if b.name.lower().split()[-1] == "head"]
    if len(heads) != 1:
        raise ValueError("无法确定唯一头骨，请保留原神角色的 Head 骨骼名称")
    head = bpy.data.objects.new(f"HGT • {root.name} • 头部", None)
    collection.objects.link(head)
    head["hgt_owner"] = settings.uid
    head.empty_display_size = settings.height * 0.03
    head.parent = armature
    head.parent_type = "BONE"
    head.parent_bone = heads[0].name
    bpy.context.view_layer.update()
    head.matrix_world = armature.matrix_world @ heads[0].matrix
    settings.head = head
    rotation = head.matrix_world.to_quaternion().inverted()
    settings.head_forward = rotation @ Vector((0, -1, 0))
    settings.head_right = rotation @ Vector((1, 0, 0))


def ensure_camera(root, collection, scene):
    if scene.camera:
        return
    meshes = [entry.object for entry in root.hgt_character.meshes if entry.object and not entry.object.hide_render]
    low, high = bounds(meshes)
    center = (low + high) * 0.5
    height = high.z - low.z
    data = bpy.data.cameras.new("HGT 相机")
    data.type = "ORTHO"
    data.ortho_scale = max(height, (high.x - low.x) / (scene.render.resolution_x / scene.render.resolution_y)) * 1.15
    camera = bpy.data.objects.new(data.name, data)
    collection.objects.link(camera)
    camera["hgt_owner"] = root.hgt_character.uid
    camera.location = center + Vector((0, -height * 3, height * 0.02))
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera


def build(filepath, context):
    catalog = AssetCatalog(filepath)
    if context.object and context.object.mode != "OBJECT":
        raise ValueError("请先退出编辑或姿态模式，再导入角色")
    # Import into an owned collection so any failed transaction can be removed
    # without touching objects or material slots that were already in the scene.
    previous_objects = {obj.as_pointer() for obj in bpy.data.objects}
    previous_materials = {mat.as_pointer() for mat in bpy.data.materials}
    kinds = ("node_groups", "meshes", "armatures", "lights", "cameras", "images", "actions")
    previous_data = {kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in kinds}
    selected = tuple(context.selected_objects)
    active = context.view_layer.objects.active
    scene = context.scene
    previous_scene = (scene.render.engine, scene.view_settings.view_transform, scene.render.film_transparent,
                      scene.render.image_settings.file_format, scene.render.image_settings.color_mode,
                      scene.camera, scene.hgt_target)
    collection = bpy.data.collections.new(Path(filepath).stem)
    context.scene.collection.children.link(collection)
    try:
        imported = importers.import_character(filepath)
        root = bpy.data.objects.new(Path(filepath).stem, None)
        collection.objects.link(root)
        settings = root.hgt_character
        settings.building = True
        settings.managed = True
        settings.uid = uuid.uuid4().hex
        settings.source_file = str(Path(filepath).resolve())
        collection["hgt_owner"] = settings.uid
        for obj in imported:
            for old in tuple(obj.users_collection):
                old.objects.unlink(obj)
            collection.objects.link(obj)
            if obj.parent is None:
                matrix = obj.matrix_world.copy()
                obj.parent = root
                obj.matrix_world = matrix
            obj["hgt_owner"] = settings.uid
            if obj.type == "MESH":
                entry = settings.meshes.add()
                entry.object = obj
                entry.original_hidden = obj.hide_render
                entry.original_view_hidden = obj.hide_get()
                # Spawn/skill meshes are retained, but excluded from a still
                # character preview until their effect timeline is supported.
                if "effectmesh" in obj.name.casefold() or obj.name.casefold().startswith("eff_") or obj.name.casefold().startswith("eyestar"):
                    obj.hide_render = True
                    obj.hide_set(True)
        visible = [e.object for e in settings.meshes if not e.object.hide_render]
        low, high = bounds(visible)
        settings.height = max(0.01, high.z - low.z)
        _make_rig(root, collection, imported)
        built = {}
        for entry in settings.meshes:
            mesh = entry.object
            if mesh.hide_render:
                continue
            for index, slot in enumerate(mesh.material_slots):
                original = slot.material
                if original is None:
                    raise ValueError(f"{mesh.name} 的材质槽为空")
                key = original.as_pointer()
                if key not in built:
                    assets = catalog.resolve(original.name)
                    generated = bpy.data.materials.new(f"HGT • {root.name} • {assets.source.rsplit('_Mat_', 1)[-1]}")
                    shaders.build_material(generated, assets, root)
                    built[key] = generated
                    binding = settings.bindings.add()
                    binding.source, binding.generated = original, generated
                    binding.source_name, binding.role = assets.source, assets.role
                snap = settings.slots.add()
                snap.mesh, snap.index, snap.original, snap.generated = mesh, index, original, built[key]
                slot.material = built[key]
            outlines.build(mesh, root)
        settings.building = False
        context.scene.render.engine = "BLENDER_EEVEE"
        context.scene.view_settings.view_transform = "Standard"
        context.scene.render.film_transparent = True
        context.scene.render.image_settings.file_format = "PNG"
        context.scene.render.image_settings.color_mode = "RGBA"
        context.scene.hgt_target = root
        ensure_camera(root, collection, context.scene)
        refresh_character(root)
        for selected in context.selected_objects:
            selected.select_set(False)
        root.select_set(True)
        context.view_layer.objects.active = root
        return root
    except Exception:
        for obj in list(bpy.data.objects):
            if obj.as_pointer() not in previous_objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        for mat in list(bpy.data.materials):
            if mat.as_pointer() not in previous_materials:
                bpy.data.materials.remove(mat)
        for kind in kinds:
            items = getattr(bpy.data, kind)
            for item in list(items):
                if item.as_pointer() not in previous_data[kind] and item.users == 0:
                    items.remove(item)
        bpy.data.collections.remove(collection)
        (scene.render.engine, scene.view_settings.view_transform, scene.render.film_transparent,
         scene.render.image_settings.file_format, scene.render.image_settings.color_mode,
         scene.camera, scene.hgt_target) = previous_scene
        for obj in selected:
            obj.select_set(True)
        context.view_layer.objects.active = active
        raise


def refresh_character(root, depsgraph=None):
    global _REFRESHING
    if _REFRESHING or root is None:
        return
    settings = root.hgt_character
    if not settings.managed or settings.building:
        return
    _REFRESHING = True
    try:
        direction = light_direction(settings)
        if settings.light:
            rotation = direction.to_track_quat("Z", "Y").to_euler()
            if any(abs(settings.light.rotation_euler[i] - rotation[i]) > 1e-6 for i in range(3)):
                settings.light.rotation_euler = rotation
            if abs(settings.light.data.energy - settings.light_energy) > 1e-6:
                settings.light.data.energy = settings.light_energy
        forward, side = 1.0, 1.0
        if settings.head:
            head = settings.head.evaluated_get(depsgraph) if depsgraph else settings.head
            rotation = head.matrix_world.to_quaternion()
            horizontal = Vector((direction.x, direction.y, 0)).normalized()
            forward = (rotation @ Vector(settings.head_forward)).dot(horizontal)
            side = (rotation @ Vector(settings.head_right)).dot(horizontal)
        values = {"threshold": settings.threshold, "softness": settings.softness, "rim": settings.rim,
                  "shadow_color": settings.shadow_color, "light_vector": direction,
                  "face_forward": forward, "face_side": side, "light_gain": settings.light_energy * 0.5}
        for binding in settings.bindings:
            shaders.set_controls(binding.generated, values)
        for entry in settings.meshes:
            if entry.object:
                outlines.update(entry.object, root)
    finally:
        _REFRESHING = False


def restore(root):
    settings = root.hgt_character
    if not settings.managed:
        raise ValueError("请选择 Hoyo-GI-Toon 角色")
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
        for modifier in list(mesh.modifiers):
            if modifier.type == "NODES" and modifier.node_group and modifier.node_group.get("hgt_owner") == settings.uid:
                tree = modifier.node_group
                mesh.modifiers.remove(modifier)
                if tree and tree.users == 0:
                    bpy.data.node_groups.remove(tree)
    settings.managed = False


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
