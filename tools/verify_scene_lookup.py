"""Scene membership boundaries, uniform animation and protected render comparison."""
import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verification_runtime import install_candidate, load_mmd, file_hash
from outline_verification import protected
from scene_lookup_verification import LookupRoutes

parser = argparse.ArgumentParser()
for name in ('output-dir', 'candidate', 'fixture', 'mmd-tools'):
    parser.add_argument('--' + name, type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
OUT = args.output_dir.resolve()
OUT.mkdir(parents=True, exist_ok=True)
load_mmd(args.mmd_tools, OUT / '_runtime')
addon = install_candidate(args.candidate, OUT)
bpy.ops.wm.open_mainfile(filepath=str(args.fixture), load_ui=False)
scene, root = bpy.context.scene, bpy.context.scene.hgt_target
before = protected(root)
objects = [(o.as_pointer(), bool(o.rigid_body), bool(o.rigid_body_constraint)) for o in scene.objects]
report = {'scope': 'SCENE-LOOKUP-COMPATIBILITY', 'complete': False, 'checks': {}, 'renders': [],
          'package_sha256': file_hash(args.candidate),
          'source_sha256': {p.name: file_hash(p) for p in Path(addon.__file__).parent.glob('*.py')}}


def check(name, result):
    assert result, name
    report['checks'][name] = True


def matches(obj, target):
    expected = obj in set(target.objects) if obj else False
    return addon.scene_models.in_scene(obj, target) == expected


def render(name):
    bpy.ops.render.render()
    path = OUT / (name + '.png')
    bpy.data.images['Render Result'].save_render(str(path))
    image = bpy.data.images.load(str(path), check_existing=False)
    pixels = np.array(image.pixels[:], dtype=np.float32)
    bpy.data.images.remove(image)
    return pixels


check('existing_root_and_light_membership', all(matches(o, scene) for o in (root, scene.hgt_light, None)))
other = bpy.data.scenes.new('Private lookup scene')
parent = bpy.data.collections.new('Private lookup parent')
child = bpy.data.collections.new('Private lookup child')
parent.children.link(child)
scene.collection.children.link(parent)
obj = bpy.data.objects.new('Private lookup object', None)
child.objects.link(obj)
check('nested_collection_and_warm_cache', matches(obj, scene) and matches(obj, scene))
check('other_scene_absent', matches(obj, other) and not addon.scene_models.in_scene(obj, other))
other.collection.children.link(parent)
check('shared_nested_collection', matches(obj, scene) and matches(obj, other))
scene.collection.children.unlink(parent)
check('unlink_ancestor_invalidates_positive', matches(obj, scene) and not addon.scene_models.in_scene(obj, scene))
scene.collection.children.link(parent)
check('relink_after_negative', matches(obj, scene) and addon.scene_models.in_scene(obj, scene))
obj.name = 'Private renamed lookup object'
child.name = 'Private renamed lookup collection'
check('object_and_collection_rename', matches(obj, scene))
child.objects.unlink(obj)
check('unlink_object_invalidates_positive', matches(obj, scene) and not addon.scene_models.in_scene(obj, scene))
scene.collection.objects.link(obj)
check('master_collection_link', matches(obj, scene) and addon.scene_models.in_scene(obj, scene))
child.objects.link(obj)
scene.collection.objects.unlink(obj)
addon.scene_models.in_scene(obj, scene)
bpy.data.collections.remove(child)
check('deleted_cached_owner', matches(obj, scene) and not addon.scene_models.in_scene(obj, scene))
scene.collection.objects.link(obj)
check('new_owner_after_deletion', matches(obj, scene) and addon.scene_models.in_scene(obj, scene))
name = obj.name
bpy.data.objects.remove(obj, do_unlink=True)
obj = bpy.data.objects.new(name, None)
other.collection.objects.link(obj)
check('same_name_replacement_other_scene', matches(obj, scene) and matches(obj, other))
bpy.data.objects.remove(obj, do_unlink=True)
bpy.data.collections.remove(parent)
bpy.data.scenes.remove(other)

settings = root.hgt_character
routes = LookupRoutes(addon)
scene.render.resolution_x, scene.render.resolution_y = 320, 480
scene.render.resolution_percentage = 100
scene.eevee.taa_render_samples = 32
for frame in (186, 201, 228):
    routes.select('baseline')
    scene.frame_set(frame)
    reference = render(f'{frame}-baseline')
    routes.select('candidate')
    scene.frame_set(frame)
    graph = bpy.context.evaluated_depsgraph_get()
    graph.update()
    vectors = addon.lighting.shader_vectors(root, graph)
    error = max(abs(a-b) for key, value in vectors.items()
                for a, b in zip(graph.scene_eval[f'hgt_{settings.uid}_{key}'][:3], value))
    check(f'animated_uniforms_{frame}', error < 2e-6)
    actual = render(f'{frame}-candidate')
    difference = np.abs(actual - reference)
    report['renders'].append({'frame': frame, 'max_error': float(difference.max()),
                              'mean_error': float(difference.mean())})
    check(f'pixels_match_2111_{frame}', np.array_equal(reference, actual))

light = settings.light_source
owner = light.users_collection[0]
addon.scene_models.in_scene(light, scene)
owner.objects.unlink(light)
try:
    addon.lighting.update(root, scene=scene)
except ValueError as error:
    check('unlinked_light_still_reports_error', '不在当前场景' in str(error))
else:
    raise AssertionError('Removed light incorrectly accepted')
owner.objects.link(light)
addon.lighting.update(root, scene=scene)
check('relinked_light_recovers', addon.scene_models.in_scene(light, scene))
check('source_mesh_actions_weights_unchanged', protected(root) == before)
check('scene_objects_and_physics_unchanged', sorted(objects) == sorted(
    (o.as_pointer(), bool(o.rigid_body), bool(o.rigid_body_constraint)) for o in scene.objects))
routes.select('candidate')
scene.frame_set(186)
reference = render('before-save')
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'verified.blend'), relative_remap=False)
bpy.ops.wm.open_mainfile(filepath=str(OUT / 'verified.blend'), load_ui=False)
scene, root = bpy.context.scene, bpy.context.scene.hgt_target
check('save_reopen_membership', matches(root, scene) and matches(scene.hgt_light, scene))
check('save_reopen_pixels', np.array_equal(reference, render('after-reopen')))
check('save_reopen_protected_sources', protected(root) == before)
for handlers, callback in ((bpy.app.handlers.frame_change_post, addon.workflow.update_frame),
                           (bpy.app.handlers.depsgraph_update_post, addon.workflow.update_scene)):
    check(callback.__name__ + '_unique', handlers.count(callback) == 1)
report['complete'] = True
(OUT / 'compatibility.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
print('SCENE_LOOKUP_COMPATIBILITY', len(report['checks']), flush=True)
