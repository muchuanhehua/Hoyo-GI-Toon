"""Version owned project records and explicitly reconnect moved asset packages."""
import hashlib
import json
from pathlib import Path
import bpy
from bpy.app.handlers import persistent

SCHEMA = 1


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def images(root, source=False):
    from .shaders import walk
    materials = set()
    for entry in root.hgt_character.meshes:
        obj = entry.object
        if obj is None or (not source and obj.hide_render):
            continue
        visible = obj.data.attributes.get('hgt_part_visible') if not source else None
        expression = obj.data.attributes.get('hgt_facial_expression') if not source else None
        indices = {p.material_index for p in obj.data.polygons
                   if (visible is None or visible.data[p.index].value)
                   and (expression is None or expression.data[p.index].value < .5)}
        materials.update(slot.material for i, slot in enumerate(obj.material_slots)
                         if slot.material and (source or i in indices))
    for binding in root.hgt_character.bindings:
        if source:
            materials.update((binding.source, binding.generated, binding.outline))
        if binding.generated and (source or binding.generated in materials):
            materials.add(binding.generated.get('hgt_eye_overlay'))
    return {node.image for material in materials if material and material.use_nodes
            for tree in walk(material.node_tree) for node in tree.nodes if node.type == 'TEX_IMAGE'
            and node.image and node.image.source == 'FILE' and node.image.filepath}


def image_path(image):
    return Path(bpy.path.abspath(image.filepath, library=image.library)).resolve()


def stamp(root):
    settings = root.hgt_character
    source = Path(settings.source_file)
    if source.is_file() and not settings.source_digest:
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
            raise ValueError('贴图丢失，请用“重新定位资源”选择原模型：' + Path(image.filepath).name)


def _remap(value, before, after):
    if isinstance(value, dict):
        return {key: _remap(item, before, after) for key, item in value.items()}
    if isinstance(value, list):
        return [_remap(item, before, after) for item in value]
    if isinstance(value, str):
        path = Path(value)
        if path.is_absolute() and path.is_relative_to(before):
            return str(after / path.relative_to(before))
    return value


def relink(root, source):
    settings = root.hgt_character;source = Path(source).resolve()
    previous = Path(settings.source_file).resolve()
    if not source.is_file() or source.suffix.casefold() != previous.suffix.casefold() or source.name.casefold() != previous.name.casefold():
        raise ValueError('请选择移动后的同一个 FBX 或 PMX 文件')
    model_digest = digest(source)
    if settings.source_digest and model_digest != settings.source_digest:
        raise ValueError('所选模型与工程中的原文件不同')
    records = json.loads(settings.resource_digests or '{}')
    changes = []
    for image in images(root, source=True):
        path = image_path(image)
        if not path.is_relative_to(previous.parent):
            continue
        target = source.parent / path.relative_to(previous.parent)
        if not target.is_file():
            raise ValueError('新目录缺少贴图：' + target.name)
        expected = records.get(str(path).casefold())
        if expected and digest(target) != expected:
            raise ValueError('新目录中的贴图与原文件不同：' + target.name)
        probe = bpy.data.images.load(str(target), check_existing=False)
        try:
            if image.has_data and tuple(probe.size) != tuple(image.size):
                raise ValueError('新目录中的贴图尺寸不同：' + target.name)
        finally:
            bpy.data.images.remove(probe)
        changes.append((image, image.filepath, image.get('hgt_file'), str(target)))
    metadata = []
    for material in bpy.data.materials:
        if material.get('hgt_owner') != settings.uid:
            continue
        for key in ('hgt_json', 'hgt_texture_matches'):
            if key in material:
                value = material[key]
                changed = (json.dumps(_remap(json.loads(value), previous.parent, source.parent), ensure_ascii=False)
                           if key == 'hgt_texture_matches' else _remap(value, previous.parent, source.parent))
                metadata.append((material, key, value, changed))
    old_fields = settings.source_file, settings.source_digest, settings.resource_digests
    try:
        for image, _, key, target in changes:
            image.filepath = target;image.reload()
            if key is not None:
                image['hgt_file'] = str(Path(target)).casefold()
        for material, key, _, changed in metadata:
            material[key] = changed
        settings.source_file, settings.source_digest = str(source), model_digest
        # Dictionary keys are paths too, unlike texture metadata's field names.
        settings.resource_digests = json.dumps({str(source.parent / Path(key).relative_to(previous.parent)).casefold()
            if Path(key).is_relative_to(previous.parent) else key: value for key, value in records.items()})
        stamp(root)
    except Exception:
        for image, path, key, _ in changes:
            image.filepath = path
            if key is not None:
                image['hgt_file'] = key
            if image_path(image).is_file():
                image.reload()
        for material, key, value, _ in metadata:
            material[key] = value
        settings.source_file, settings.source_digest, settings.resource_digests = old_fields
        raise


@persistent
def on_load(_):
    from . import expressions
    for scene in bpy.data.scenes:
        scene.hgt_output.rendering = False
        for root in scene.objects:
            settings = root.hgt_character
            if settings.managed and settings.schema_version < SCHEMA:
                # Old projects keep their saved camera and existing shader graphs.
                settings.auto_frame = False
                expressions.initialize(root)
                stamp(root)


def register():
    bpy.app.handlers.load_post.append(on_load)
    # Extension registration runs with restricted scene access. Migrate an
    # already open project only after Blender has completed addon activation.
    bpy.app.timers.register(_migrate_open_project, first_interval=0.0)


def _migrate_open_project():
    on_load(None)


def unregister():
    if bpy.app.timers.is_registered(_migrate_open_project):
        bpy.app.timers.unregister(_migrate_open_project)
    if on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load)
