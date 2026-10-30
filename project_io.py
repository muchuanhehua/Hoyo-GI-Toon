"""Record source resources and reconnect saved scene selection without reimport."""
import hashlib
import json
from pathlib import Path
import bpy
from bpy.app.handlers import persistent

SCHEMA = 2


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def images(root, source=False):
    from .shaders import walk
    materials = {slot.material for entry in root.hgt_character.meshes if entry.object
                 and (source or not entry.object.hide_render) for slot in entry.object.material_slots if slot.material}
    if source:
        materials.update(m for binding in root.hgt_character.bindings
                         for m in (binding.source, binding.generated, binding.outline) if m)
    return {node.image for material in materials if material.use_nodes
            for tree in walk(material.node_tree) for node in tree.nodes if node.type == 'TEX_IMAGE'
            and node.image and node.image.source == 'FILE' and node.image.filepath}


def image_path(image):
    return Path(bpy.path.abspath(image.filepath, library=image.library)).resolve()


def stamp(root):
    settings = root.hgt_character
    source = Path(settings.source_file) if settings.source_file else None
    if source and source.is_file() and not settings.source_digest:
        settings.source_digest = digest(source)
    records = json.loads(settings.resource_digests or '{}')
    for image in images(root, source=True):
        path = image_path(image)
        if str(path).casefold() not in records and path.is_file():
            records[str(path).casefold()] = digest(path)
    settings.resource_digests = json.dumps(records)
    settings.schema_version = SCHEMA


def validate(root):
    for image in images(root):
        if not image.packed_file and not image_path(image).is_file():
            raise ValueError('贴图丢失，请用“查找丢失贴图”重新关联：' + Path(image.filepath).name)


@persistent
def on_load(_):
    from . import scene_models
    scene_models.reset_selection_cache()
    for scene in bpy.data.scenes:
        root = scene.hgt_target
        if root and root.hgt_character.schema_version == SCHEMA and root.hgt_character.source_root:
            scene.hgt_model = root.hgt_character.source_root
            light = root.hgt_character.light_source
            if scene.hgt_light is None and light and light.name in scene.objects:
                scene.hgt_light = light
        scene_models.sync_active(scene)


def register():
    bpy.app.handlers.load_post.append(on_load)
    bpy.app.timers.register(_migrate_open_project, first_interval=0.0)


def _migrate_open_project():
    on_load(None)


def unregister():
    if bpy.app.timers.is_registered(_migrate_open_project):
        bpy.app.timers.unregister(_migrate_open_project)
    if on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load)
