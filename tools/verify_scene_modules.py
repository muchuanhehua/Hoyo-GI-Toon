"""Exercise real environment assets, preservation, cleanup and saved projects."""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch
import bpy
import numpy as np

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verification_runtime import load_addon, load_mmd, install_candidate, unload_addon, file_hash
from verification_data import source_snapshot, mmd_snapshot

parser = argparse.ArgumentParser()
for name in ('output-dir', 'mmd-tools', 'assets-index'):
    parser.add_argument('--' + name, type=Path, required=True)
parser.add_argument('--candidate', type=Path)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
project = Path(__file__).resolve().parents[1]
out = args.output_dir.resolve()
assert out.is_relative_to(project / '.verification')
out.mkdir(parents=True, exist_ok=True)
mmd = load_mmd(args.mmd_tools, out / '_runtime')
addon = install_candidate(args.candidate, out) if args.candidate else load_addon(project)
module = addon.panels.scene_presets
payload = Path(addon.__file__).resolve().parent
hashes = {p.name: file_hash(p) for p in payload.glob('*.py')}
assets = {name: file_hash(payload / 'assets' / name) for name in
          ('scenes.json', 'scene_city_terrace.blend', 'scene_stage.blend')}
checks = {}
report = {'scope': 'SCENE-PRESETS', 'source_sha256': hashes, 'asset_sha256': assets,
          'package_sha256': file_hash(args.candidate) if args.candidate else None, 'checks': checks, 'presets': {}}


def ids():
    return {kind: {x.as_pointer() for x in getattr(bpy.data, kind)
                   if not (kind == 'images' and x.source == 'VIEWER')}
            for kind in addon.asset_tracking.DATA_KINDS}


def empty():
    bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.render.resolution_x, scene.render.resolution_y = 270, 480
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = '//keep-my-output/'
    scene.frame_start, scene.frame_end = 13, 47
    scene.render.fps = 30
    scene.frame_set(16)
    return scene


def settings(scene):
    return {'render': [scene.render.engine, scene.render.resolution_x, scene.render.resolution_y,
                       scene.render.resolution_percentage, scene.render.filepath, scene.render.fps],
            'view': [scene.view_settings.view_transform, scene.view_settings.look,
                     scene.view_settings.exposure, scene.view_settings.gamma],
            'frame': [scene.frame_start, scene.frame_end, scene.frame_current],
            'compositor': scene.compositing_node_group.as_pointer() if scene.compositing_node_group else None,
            'units': [scene.unit_settings.system, scene.unit_settings.scale_length]}


def load(key):
    bpy.context.scene.hgt_scene_preset = key
    assert bpy.ops.hgt.load_scene() == {'FINISHED'}
    bpy.context.view_layer.update()
    return bpy.context.scene.hgt_scene.collection


def remove():
    assert bpy.ops.hgt.remove_scene() == {'FINISHED'}
    bpy.context.view_layer.update()


def render(name):
    assert bpy.ops.hgt.render() == {'FINISHED'}
    path = out / (name + '.png')
    bpy.data.images['Render Result'].save_render(str(path), scene=bpy.context.scene)
    image = bpy.data.images.load(str(path), check_existing=False)
    pixels = np.array(image.pixels[:], dtype=np.float32)
    bpy.data.images.remove(image)
    assert np.isfinite(pixels).all() and float(np.std(pixels.reshape(-1, 4)[:, :3])) > .015
    return pixels


scene = empty()
original = scene.world, scene.camera, scene.hgt_light
baseline = ids()
configuration = settings(scene)
for key, preset in module.PRESETS.items():
    with bpy.data.libraries.load(str(module.ASSETS / preset['file'])) as (source, target):
        assert not source.scenes and not source.armatures and not source.texts
        assert source.collections and preset['collection'] in source.collections
    collection = load(key)
    assert scene.camera in collection.all_objects.values() and scene.hgt_light in collection.all_objects.values()
    assert scene.world == collection['hgt_scene_world']
    assert not any(o.type == 'ARMATURE' for o in collection.all_objects)
    assert all(not item.library for kind in addon.asset_tracking.DATA_KINDS
               for item in getattr(bpy.data, kind) if item.get(module.OWNER) == scene.hgt_scene.uid)
    images = [image for image in bpy.data.images if image.get(module.OWNER) == scene.hgt_scene.uid]
    assert all(image.packed_file and len(image.packed_file.data) > 0 and min(image.size) > 0 for image in images)
    stable = ids()
    assert load(key) == collection and ids() == stable
    render(key.lower() + '-empty')
    report['presets'][key] = {'objects': len(collection.all_objects), 'packed_images': len(images), 'rendered': True}
    assert settings(scene) == configuration
    remove()
    assert (scene.world, scene.camera, scene.hgt_light) == original
    assert ids() == baseline, {kind: len(ids()[kind]) - len(baseline[kind]) for kind in baseline}
checks['clean_assets_and_packed_images'] = checks['empty_scene_both_presets'] = True
checks['repeat_load_and_remove_no_resource_growth'] = checks['output_units_compositor_unchanged'] = True

camera = addon.rendering.prepare(scene)
camera.location = (5, -7, 3)
light = addon.lighting.default_light(scene)
world = scene.world
original = world, camera, light
baseline = ids()
for key in ('CITY_TERRACE', 'STAGE', 'CITY_TERRACE', 'STAGE'):
    load(key)
    assert light.hide_render and light.hide_viewport
    assert len([c for c in scene.collection.children if c.get('hgt_scene_asset')]) == 1
remove()
assert (scene.world, scene.camera, scene.hgt_light) == original
assert not light.hide_render and not light.hide_viewport
assert tuple(camera.location) == (5, -7, 3) and ids() == baseline
checks['switch_replaces_only_previous_preset'] = checks['previous_camera_light_world_restored'] = True

load('CITY_TERRACE')
addon.lighting.default_light(scene)
assert scene.hgt_light == light and not light.hide_render and not light.hide_viewport
remove()
assert scene.hgt_light == light
checks['default_light_still_works'] = True

load('CITY_TERRACE')
manual_world = bpy.data.worlds.new('User manual world')
manual_camera = bpy.data.objects.new('User manual camera', bpy.data.cameras.new('User manual camera'))
manual_light = bpy.data.objects.new('User manual light', bpy.data.lights.new('User manual light', 'AREA'))
scene.collection.objects.link(manual_camera)
scene.collection.objects.link(manual_light)
scene.world, scene.camera, scene.hgt_light = manual_world, manual_camera, manual_light
remove()
assert (scene.world, scene.camera, scene.hgt_light) == (manual_world, manual_camera, manual_light)
checks['manual_pointer_changes_preserved'] = True

light = addon.lighting.default_light(scene)
other_scene = bpy.data.scenes.new('User other scene')
other_scene.collection.objects.link(light)
other_scene.hgt_light = light
baseline = ids()
load('CITY_TERRACE')
assert not light.hide_render and not light.hide_viewport
with bpy.context.temp_override(scene=other_scene, view_layer=other_scene.view_layers[0]):
    other_collection = load('STAGE')
    other_uid = other_scene.hgt_scene.uid
remove()
assert other_scene.hgt_scene.collection == other_collection
assert all(obj.name in bpy.data.objects for obj in other_collection.all_objects)
assert other_scene.hgt_scene.uid == other_uid
with bpy.context.temp_override(scene=other_scene, view_layer=other_scene.view_layers[0]):
    remove()
assert ids() == baseline and not light.hide_render and not light.hide_viewport
bpy.data.scenes.remove(other_scene)
checks['two_scenes_isolated_and_shared_light_preserved'] = True

baseline = ids()
collection = load('CITY_TERRACE')
bpy.data.collections.remove(collection, do_unlink=True)
assert scene.hgt_scene.collection is None and scene.hgt_scene.uid
assert addon.panels.HGT_OT_remove_scene.poll(bpy.context)
remove()
assert ids() == baseline
checks['manual_collection_deletion_can_restore'] = True

load('STAGE')
muted = scene.hgt_scene.muted_light
assert muted
muted.hide_render = muted.hide_viewport = False
stable = ids()
pointers = scene.world, scene.camera, scene.hgt_light, scene.hgt_scene.collection
fixture = out / 'invalid-assets'
fixture.mkdir(exist_ok=True)
broken = bpy.data.collections.new(module.PRESETS['CITY_TERRACE']['collection'])
broken['hgt_scene_asset'] = 'CITY_TERRACE'
bpy.data.libraries.write(str(fixture / module.PRESETS['CITY_TERRACE']['file']), {broken})
bpy.data.collections.remove(broken)
assert ids() == stable
with patch.object(module, 'ASSETS', fixture):
    try:
        module.load(bpy.context, 'CITY_TERRACE')
    except ValueError as exc:
        assert '引用无效' in str(exc)
    else:
        raise AssertionError('Invalid asset should fail')
assert ids() == stable and (scene.world, scene.camera, scene.hgt_light, scene.hgt_scene.collection) == pointers
assert not muted.hide_render and not muted.hide_viewport
checks['invalid_asset_failure_rollback'] = True
remove()

collection = load('CITY_TERRACE')
foreign = bpy.data.objects.new('User-added object', bpy.data.meshes.new('User-added mesh'))
collection.objects.link(foreign)
foreign_child = bpy.data.collections.new('User-added collection')
collection.children.link(foreign_child)
mesh_obj = next(obj for obj in collection.all_objects if obj.type == 'MESH' and obj.data.materials)
reuse = bpy.data.objects.new('User reused mesh', mesh_obj.data)
scene.collection.objects.link(reuse)
reuse_mesh = reuse.data
material = mesh_obj.data.materials[0]
foreign.data.materials.append(material)
remove()
assert foreign.name in scene.objects and foreign.data.materials[0] == material
assert foreign_child.name in scene.collection.children and reuse.data == reuse_mesh and material.name in bpy.data.materials
checks['user_added_and_reused_data_preserved'] = True

scene = empty()
asset_index = json.loads(args.assets_index.read_text('utf-8'))
model = asset_index['models'][0]
pmx_digest = file_hash(model['path'])
batch = addon.importers.import_character(model['path'], bpy.context)
root = addon.workflow.apply_materials(batch.model_root, bpy.context)
scene.hgt_model = root.hgt_character.source_root
addon.lighting.default_light(scene)
baseline_source = source_snapshot(batch)
baseline_mmd = mmd_snapshot(batch)
baseline = ids()
configuration = settings(scene)
protected = {Path(model['path']): pmx_digest}
for preset in module.PRESETS.values():
    original_path = project.parent / preset['source']
    if original_path.is_file():
        assert file_hash(original_path) == preset['source_sha256']
        protected[original_path] = file_hash(original_path)
for image in batch.data.get('images', ()):
    path = Path(bpy.path.abspath(image.filepath))
    if path.is_file():
        protected[path] = file_hash(path)
for key in module.PRESETS:
    load(key)
    assert source_snapshot(batch) == baseline_source and mmd_snapshot(batch) == baseline_mmd
    render(key.lower() + '-amber')
    assert settings(scene) == configuration
    remove()
    assert ids() == baseline, {kind: len(ids()[kind]) - len(baseline[kind]) for kind in baseline}
    assert source_snapshot(batch) == baseline_source and mmd_snapshot(batch) == baseline_mmd
checks['existing_pmx_source_and_mmd_metadata_unchanged'] = True

load('CITY_TERRACE')
before_pixels = render('packed-before')
backup_names = [scene.hgt_scene.previous_world.name if scene.hgt_scene.previous_world else None,
                scene.hgt_scene.previous_camera.name if scene.hgt_scene.previous_camera else None,
                scene.hgt_scene.previous_light.name if scene.hgt_scene.previous_light else None]
assert bpy.ops.wm.save_as_mainfile(filepath=str(out / 'packed-scene.blend'), check_existing=False) == {'FINISHED'}
assert bpy.ops.wm.open_mainfile(filepath=str(out / 'packed-scene.blend'), load_ui=False, use_scripts=False) == {'FINISHED'}
scene = bpy.context.scene
assert scene.hgt_scene.preset == 'CITY_TERRACE'
reopened_pixels = render('packed-reopened')
error = np.abs(before_pixels - reopened_pixels)
report['save_reopen_pixels'] = {'strict_equal': bool(np.array_equal(before_pixels, reopened_pixels)),
                              'max_channel_error': float(error.max()), 'mean_channel_error': float(error.mean()),
                              'changed_pixel_fraction': float(np.any(error.reshape(-1, 4) > 0, axis=1).mean())}
# Full environment renders may move a few 8-bit values at GPU rounding boundaries.
assert float(error.max()) <= 1 / 255 + 1e-6 and float(error.mean()) < 1e-5
assert report['save_reopen_pixels']['changed_pixel_fraction'] < .001
remove()
assert [scene.world.name if scene.world else None, scene.camera.name if scene.camera else None,
        scene.hgt_light.name if scene.hgt_light else None] == backup_names
checks['packed_scene_save_reopen_and_restore'] = True
assert all(file_hash(path) == value for path, value in protected.items())
assert hashes == {p.name: file_hash(p) for p in payload.glob('*.py')}
assert assets == {name: file_hash(payload / 'assets' / name) for name in assets}
checks['original_files_unchanged'] = True
addon.unregister()
assert not hasattr(bpy.types.Scene, 'hgt_scene')
addon.register()
assert hasattr(bpy.types.Scene, 'hgt_scene')
unload_addon(addon)
checks['register_unregister'] = True
report['complete'] = True
(out / 'scene-modules.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
print('HGT_SCENE_MODULES_PASSED', json.dumps(checks, ensure_ascii=False))
