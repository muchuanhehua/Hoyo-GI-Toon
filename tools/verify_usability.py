"""Verify the GI-Toon operation feedback in a disposable Blender process."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch
import bpy
import numpy as np
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verification_runtime import load_addon, load_mmd, install_candidate, file_hash
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
load_mmd(args.mmd_tools, out / '_runtime')
addon = install_candidate(args.candidate, out) if args.candidate else load_addon(project)
payload = Path(addon.__file__).resolve().parent
hashes = {p.name: file_hash(p) for p in payload.glob('*.py')}
report = {'scope': 'GI-TOON-USABILITY', 'source_sha256': hashes, 'models': [], 'checks': {},
          'package_sha256': file_hash(args.candidate) if args.candidate else None}


def save():
    assert hashes == {p.name: file_hash(p) for p in payload.glob('*.py')}
    (out / 'usability.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')


def render(name):
    bpy.ops.render.render()
    destination = out / (name + '.png')
    bpy.data.images['Render Result'].save_render(str(destination))
    image = bpy.data.images.load(str(destination), check_existing=False)
    pixels = np.array(image.pixels[:], dtype=np.float32).reshape((-1, 4))
    bpy.data.images.remove(image)
    return pixels


def difference(a, b):
    return float(np.abs(a - b).max())


models = json.loads(args.assets_index.read_text('utf-8'))['models']
for index, model in enumerate(models):
    bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = 360, 540
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    protected = {str(p): file_hash(p) for p in Path(model['path']).parent.rglob('*') if p.is_file()}
    batch = addon.importers.import_character(model['path'], bpy.context)
    original, metadata = source_snapshot(batch), mmd_snapshot(batch)
    root = addon.scene_models.ensure(batch.model_root, bpy.context, model['path'])
    camera = addon.rendering.prepare(scene, root)
    bpy.context.view_layer.update()
    points = [e.object.matrix_world @ Vector(c) for e in root.hgt_character.meshes for c in e.object.bound_box]
    projected = [world_to_camera_view(scene, camera, point) for point in points]
    assert all(.02 < p.x < .98 and .02 < p.y < .98 and p.z > 0 for p in projected)
    matrix = camera.matrix_world.copy()
    assert addon.rendering.prepare(scene, root) == camera and camera.matrix_world == matrix
    meshes = addon.scene_models.meshes(batch.model_root)
    visibility = {obj: obj.hide_get() for obj in meshes}
    render_visibility = {obj: obj.hide_render for obj in meshes}
    addon.scene_models.toggle_visibility(batch.model_root)
    assert not addon.scene_models.visible(batch.model_root)
    addon.scene_models.toggle_visibility(batch.model_root)
    assert visibility == {obj: obj.hide_get() for obj in meshes}
    assert render_visibility == {obj: obj.hide_render for obj in meshes}
    bones_hidden = batch.armature.hide_get()
    addon.scene_models.toggle_visibility(batch.model_root, bones=True)
    assert batch.armature.hide_get() != bones_hidden
    addon.scene_models.toggle_visibility(batch.model_root, bones=True)
    assert batch.armature.hide_get() == bones_hidden
    addon.workflow.apply_materials(root, bpy.context)
    light = addon.lighting.default_light(scene)
    settings = root.hgt_character
    assert abs(settings.light_reference_energy - 2) < 1e-6
    assert settings.has_outline
    prefix = f'model-{index}'
    baseline = render(prefix + '-default')
    assert np.count_nonzero(baseline[:, 3] > .5) > 1000
    binding = next((b for b in settings.bindings if b.role == 'hair'),
                   next(b for b in settings.bindings if b.role == 'body'))
    responses = {}
    parameters = addon.lighting.active_parameters(scene)
    parameters.energy = .5
    responses['light_energy'] = difference(baseline, render(prefix + '-light-energy'))
    parameters.energy = 2
    parameters.color = (.3, .6, 1)
    responses['light_color'] = difference(baseline, render(prefix + '-light-color'))
    parameters.color = (1, 1, 1)
    assert responses['light_energy'] > .02 and responses['light_color'] > .02
    for key, value in (('brightness', .55), ('saturation', 0), ('opacity', .25)):
        setattr(binding, key, value)
        if key == 'opacity':
            assert abs(binding.outline.node_tree.nodes['HGT • PMX Edge Alpha'].inputs[0].default_value
                       - binding.outline['hgt_edge_coverage'] * value) < 1e-6
        responses[key] = difference(baseline, render(prefix + '-' + key))
        assert responses[key] > .005, (model['name'], key, responses[key])
        bpy.ops.hgt.reset_materials()
    settings.shadow_transition = .3
    responses['shadow_transition'] = difference(baseline, render(prefix + '-transition'))
    assert responses['shadow_transition'] > .001
    bpy.ops.hgt.reset_materials()
    settings.outline_lower = 1
    responses['outline_taper'] = difference(baseline, render(prefix + '-uniform-outline'))
    assert responses['outline_taper'] > .001
    bpy.ops.hgt.reset_materials()
    settings.outline = 0
    responses['outline'] = difference(baseline, render(prefix + '-no-outline'))
    assert responses['outline'] > .005
    bpy.ops.hgt.reset_materials()
    edge = next(b for b in settings.bindings if addon.outlines.eligible(b))
    edge.outline_color = (1, .01, .01)
    responses['outline_color'] = difference(baseline, render(prefix + '-outline-color'))
    assert responses['outline_color'] > .005
    bpy.ops.hgt.reset_materials()
    timings = []
    with patch.object(addon.material_controls, 'apply', side_effect=AssertionError('full material refresh during slider')):
        for step in range(30):
            started = time.perf_counter()
            settings.shadow_position = .3 + step / 100
            bpy.context.view_layer.update()
            timings.append((time.perf_counter() - started) * 1000)
    settings.shadow_position = .52
    assert source_snapshot(batch) == original and mmd_snapshot(batch) == metadata
    addon.lighting.apply_preset(scene, 'SOFT')
    parameters = addon.lighting.active_parameters(scene)
    parameters.energy, parameters.azimuth = 3.1, .9
    count = len(bpy.data.lights)
    addon.lighting.apply_preset(scene, 'SIDE')
    addon.lighting.apply_preset(scene, 'SOFT')
    addon.lighting.apply_preset(scene, 'SOFT')
    assert scene.hgt_light == light and abs(light.data.energy - 3.1) < 1e-5
    assert abs(addon.lighting.active_parameters(scene).azimuth - .9) < 1e-5 and len(bpy.data.lights) == count
    addon.workflow.restore(root)
    assert not settings.managed and scene.hgt_light == light and not light.hide_render
    assert source_snapshot(batch) == original and mmd_snapshot(batch) == metadata
    assert not any(key.startswith(f'hgt_{settings.uid}_hgt_') for key in scene.keys())
    addon.workflow.apply_materials(root, bpy.context)
    assert source_snapshot(batch) == original and mmd_snapshot(batch) == metadata
    assert protected == {str(p): file_hash(p) for p in Path(model['path']).parent.rglob('*') if p.is_file()}
    report['models'].append({'name': model['name'], 'responses': responses, 'source_and_mmd_unchanged': True,
                             'front_camera': True, 'visibility': True, 'light_presets_persist': True,
                             'shadow_update_ms': {'median': statistics.median(timings), 'max': max(timings)}})
    save()
    print('HGT_USABILITY_MODEL', model['name'], responses, flush=True)

# Saved parameters and scene uniforms survive a real reopen.
settings = root.hgt_character
settings.shadow_position, settings.outline_lower = .64, .22
binding = next(b for b in settings.bindings if b.role in {'body', 'hair'})
binding.brightness, binding.saturation, binding.opacity = .8, .75, .9
before = render('saved-parameters')
bpy.ops.wm.save_as_mainfile(filepath=str(out / 'parameters.blend'), relative_remap=False)
bpy.ops.wm.open_mainfile(filepath=str(out / 'parameters.blend'), load_ui=False)
scene, root = bpy.context.scene, bpy.context.scene.hgt_target
after = render('reopened-parameters')
assert np.array_equal(before, after), difference(before, after)
assert abs(root.hgt_character.outline_lower - .22) < 1e-5
assert abs(addon.lighting.active_parameters(scene).energy - 3.1) < 1e-5
report['checks']['parameters_save_reopen_exact'] = True

module = addon.panels.scene_presets
source_hashes = {preset['source']: file_hash(project.parent / preset['source']) for preset in module.PRESETS.values()}
collection = module.load(bpy.context, 'CITY_TERRACE')
assert 'hgt_city_layout' not in collection and 'hgt_model_scale' not in collection
import zipfile, hashlib
with zipfile.ZipFile(project/'release/hoyo_gi_toon-2.3.0.zip') as baseline:
    assert hashlib.sha256(baseline.read('assets/scene_city_terrace.blend')).hexdigest()==file_hash(payload/'assets/scene_city_terrace.blend')
    assert baseline.read('assets/scenes.json')==(payload/'assets/scenes.json').read_bytes()
bpy.context.view_layer.update()
projected = [world_to_camera_view(scene, scene.camera, entry.object.matrix_world @ Vector(corner))
             for entry in root.hgt_character.meshes for corner in entry.object.bound_box]
assert len(collection.all_objects)==321
render('city-terrace-model')
camera = scene.camera
camera.location = (0, -1, 9)
camera.rotation_euler = (Vector((0, -1, 0)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
camera.data.ortho_scale = 8
scene.render.resolution_x = scene.render.resolution_y = 600
render('city-terrace-layout')
assert module.load(bpy.context, 'CITY_TERRACE') == collection
module.remove(bpy.context)
assert all(file_hash(project.parent / path) == digest for path, digest in source_hashes.items())
report['checks']['city_terrace_v230_restored'] = True
report['checks']['original_scene_files_unchanged'] = True
report['checks']['sidebar_and_display_controls'] = addon.panels.HGT_PT_main.bl_category == 'GI-Toon'
previous = root
previous_value = previous.hgt_character.shadow_position
second_batch = addon.importers.import_character(models[0]['path'], bpy.context)
second = addon.workflow.apply_materials(second_batch.model_root, bpy.context)
second.hgt_character.shadow_position = .21
bpy.context.view_layer.update()
for character, value in ((previous, previous_value), (second, .21)):
    node = character.hgt_character.global_properties.nodes['HGT • Shadow Position']
    assert node.attribute_type == 'VIEW_LAYER' and abs(scene[node.attribute_name] - value) < 1e-5
adopted = next(b.generated for b in second.hgt_character.bindings if b.role in {'body', 'hair'})
other_scene = bpy.data.scenes.new('Reused material scene')
reused_mesh = bpy.data.meshes.new('User reused material mesh')
reused_mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 0, 1)], [], [(0, 1, 2)])
reused_mesh.materials.append(adopted)
reused_object = bpy.data.objects.new('User reused material', reused_mesh)
other_scene.collection.objects.link(reused_object)
addon.workflow.update_frame(other_scene)
key = second.hgt_character.global_properties.nodes['HGT • Shadow Position'].attribute_name
assert abs(other_scene[key] - .21) < 1e-5
addon.workflow.restore(second)
assert adopted.name in bpy.data.materials and reused_mesh.materials[0] == adopted
assert abs(other_scene[key] - .21) < 1e-5
report['checks']['reused_material_survives_restore'] = True
node = previous.hgt_character.global_properties.nodes['HGT • Shadow Position']
assert abs(scene[node.attribute_name] - previous_value) < 1e-5
report['checks']['multi_character_uniform_isolation'] = True
report['complete'] = True
save()
print('HGT_USABILITY_PASSED', flush=True)
