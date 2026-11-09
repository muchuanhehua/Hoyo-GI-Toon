"""Incremental camera, panoramic-stage and animated-uniform compatibility checks."""
import argparse
import json
from pathlib import Path
import sys
import zipfile

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verification_runtime import load_addon, load_mmd, install_candidate, file_hash

parser = argparse.ArgumentParser()
for name in ('output-dir', 'fixture', 'mmd-tools'):
    parser.add_argument('--' + name, type=Path, required=True)
parser.add_argument('--candidate', type=Path)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
OUT = args.output_dir.resolve()
assert OUT.is_relative_to(ROOT / '.verification')
OUT.mkdir(parents=True, exist_ok=True)
load_mmd(args.mmd_tools, OUT / '_runtime')
addon = install_candidate(args.candidate, OUT) if args.candidate else load_addon(ROOT)
bpy.ops.wm.open_mainfile(filepath=str(args.fixture), load_ui=False)
s = bpy.context.scene
root = s.hgt_target
settings = root.hgt_character
payload = Path(addon.__file__).resolve().parent
report = {'scope': 'STAGE-ANIMATION-COMPATIBILITY', 'complete': False, 'checks': {}, 'renders': [],
          'source_sha256': {p.name: file_hash(p) for p in payload.glob('*.py')},
          'package_sha256': file_hash(args.candidate) if args.candidate else None}


def check(name, value):
    assert value, name
    report['checks'][name] = True


def uniforms():
    graph = bpy.context.evaluated_depsgraph_get()
    graph.update()
    expected = addon.lighting.shader_vectors(root, graph)
    error = max(abs(a - b) for key, value in expected.items()
                for a, b in zip(graph.scene_eval[f'hgt_{settings.uid}_{key}'][:3], value))
    assert error < 2e-6, error


def render(name):
    s.render.resolution_x, s.render.resolution_y = 256, 384
    s.render.resolution_percentage = 100
    s.eevee.taa_render_samples = 16
    bpy.ops.render.render()
    path = OUT / (name + '.png')
    bpy.data.images['Render Result'].save_render(str(path))
    image = bpy.data.images.load(str(path), check_existing=False)
    values = np.array(image.pixels[:], dtype=np.float32)
    bpy.data.images.remove(image)
    return values


current = addon.shaders.set_controls
with zipfile.ZipFile(ROOT / 'release/hoyo_gi_toon-2.10.0.zip') as archive:
    namespace = dict(addon.shaders.__dict__)
    exec(compile(archive.read('shaders.py'), '<2.10.0-shaders>', 'exec'), namespace)
    baseline = namespace['set_controls']

binding = next(b for b in settings.bindings if b.role == 'body')
for frame, color, opacity, outline in ((186, (1, 1, 1), 1, .18), (201, (.6, .8, 1), .7, .32)):
    binding.tint, binding.opacity, settings.outline = color, opacity, outline
    binding.keyframe_insert(data_path='tint', frame=frame)
    binding.keyframe_insert(data_path='opacity', frame=frame)
    settings.keyframe_insert(data_path='outline', frame=frame)
for frame in (186, 193, 201):
    addon.shaders.set_controls = current
    addon.animation_uniforms.reset()
    s.frame_set(frame)
    uniforms()
    check(f'frame_{frame}_native_vectors', True)
    tint = binding.generated.node_tree.nodes['HGT • Material Tint'].inputs[2].default_value
    check(f'frame_{frame}_animated_material', np.allclose(tint, (*binding.tint, 1), atol=1e-6))
    actual = render(f'frame-{frame}-native')
    addon.animation_uniforms.freeze(root)
    addon.shaders.set_controls = baseline
    addon.workflow.refresh_character(root, scene=s)
    reference = render(f'frame-{frame}-baseline')
    maximum = float(np.max(np.abs(actual - reference)))
    check(f'frame_{frame}_pixels_match_2100', maximum <= 1 / 255 + 1e-6)
    report['renders'].append({'frame': frame, 'max_error': maximum,
                              'mean_error': float(np.mean(np.abs(actual - reference)))})
addon.shaders.set_controls = current
addon.animation_uniforms.reset()
s.frame_set(186)
uniforms()
light = settings.light_source
rotation = light.rotation_euler.copy()
light.rotation_euler.z += .31
bpy.context.view_layer.update()
uniforms()
check('sun_rotation_updates_in_same_evaluation', True)
expected = tuple(addon.lighting.shader_vectors(root)['hgt_light_rotation'])
settings.light_source = None
bpy.context.view_layer.update()
check('clearing_light_preserves_direction', np.allclose(addon.lighting.shader_vectors(root)['hgt_light_rotation'], expected, atol=2e-6))
settings.light_source = light
light.data.type = 'POINT'
light.location = (2, -3, 4)
bpy.context.view_layer.update()
addon.workflow.refresh_character(root, scene=s)
uniforms()
check('point_light_fallback_keeps_vectors_current', True)
light.data.type = 'SUN'
light.rotation_euler = rotation
addon.workflow.refresh_character(root, scene=s)
uniforms()
check('sun_point_sun_switch_rebuilds_native_targets', True)

camera, camera_data, camera_parent = s.camera, s.camera.data, s.camera.parent
action = camera.animation_data.action
actor = [(entry.object, entry.object.data, entry.original_data) for entry in settings.meshes]
physics = [(obj, obj.rigid_body, obj.rigid_body_constraint) for obj in s.objects if obj.rigid_body or obj.rigid_body_constraint]
collection = addon.scene_presets.load(bpy.context, 'STAGE')
check('one_default_camera_after_legacy_migration', len([o for o in s.objects if o.type == 'CAMERA']) == 1 and s.camera.name == 'HGT • Camera')
check('camera_animation_data_parent_and_drivers_preserved', s.camera == camera and camera.data == camera_data
      and camera.parent == camera_parent and camera.animation_data.action == action and len(camera.data.animation_data.drivers) == 3)
check('camera_removed_from_preset_ownership', not camera.get(addon.scene_presets.OWNER) and camera.name not in collection.all_objects)
check('actor_meshes_and_physics_preserved', actor == [(e.object, e.object.data, e.original_data) for e in settings.meshes]
      and physics == [(o, o.rigid_body, o.rigid_body_constraint) for o in s.objects if o.rigid_body or o.rigid_body_constraint])
check('panorama_and_camera_free_asset', collection['hgt_stage_coverage_degrees'] == 360
      and collection['hgt_stage_radius'] == 10 and not any(o.type == 'CAMERA' for o in collection.all_objects))
sky = next(o for o in collection.all_objects if o.name.startswith('STAGE__panoramic_sky'))
check('inward_sky_and_camera_backface_culling', sky.data.materials[0].use_backface_culling
      and all(p.normal.dot(p.center) < 0 for p in sky.data.polygons if p.center.z < 6))
stable = len(bpy.data.objects)
check('repeat_load_is_idempotent', addon.scene_presets.load(bpy.context, 'STAGE') == collection and len(bpy.data.objects) == stable)
user = bpy.data.objects.new('User object in preset', None)
collection.objects.link(user)
for preset in ('CITY_TERRACE', 'STAGE'):
    addon.scene_presets.load(bpy.context, preset)
    check(preset + '_keeps_single_camera', s.camera == camera and sum(o.type == 'CAMERA' for o in s.objects) == 1)
check('user_added_object_survives_switch', user.name in s.objects)
addon.scene_presets.remove(bpy.context)
check('remove_keeps_animated_camera', s.camera == camera and camera.animation_data.action == action)
s.camera = None
check('prepare_reuses_existing_camera', addon.rendering.prepare(s) == camera and sum(o.type == 'CAMERA' for o in s.objects) == 1)
addon.scene_presets.load(bpy.context, 'STAGE')
path = OUT / 'saved.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False, compress=True)
bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
s = bpy.context.scene; root = s.hgt_target; settings = root.hgt_character
s.frame_set(193); uniforms()
check('save_reopen_native_drivers_and_single_camera', sum(o.type == 'CAMERA' for o in s.objects) == 1 and s.camera.parent is not None)
check('cached_roots_match_scene_data', set(addon.workflow.tracked_roots()) == {o for o in bpy.data.objects if addon.workflow.current(o)})
original_meshes = {e.object.name: e.original_data.name for e in settings.meshes}
addon.workflow.restore(root)
prefix = f'["hgt_{settings.uid}_'
check('restore_removes_owned_vector_drivers', not any(fc.data_path.startswith(prefix) for fc in s.animation_data.drivers))
check('restore_keeps_original_meshes', all(e.object.data == bpy.data.meshes[original_meshes[e.object.name]] for e in settings.meshes))
report['complete'] = True
(OUT / 'compatibility.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
print('STAGE_ANIMATION_COMPATIBILITY', len(report['checks']), flush=True)
