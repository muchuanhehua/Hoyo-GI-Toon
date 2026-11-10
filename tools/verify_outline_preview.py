"""Source protection, output and modifier-stack compatibility for fast outlines."""
import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verification_runtime import install_candidate, load_addon, load_mmd, file_hash
from outline_verification import OutlineRoutes, protected
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
bpy.app.handlers.load_post.remove(addon.project_io.on_load)
bpy.ops.wm.open_mainfile(filepath=str(args.fixture), load_ui=False)
bpy.app.handlers.load_post.append(addon.project_io.on_load)
scene = bpy.context.scene
root = scene.hgt_target
before = protected(root)
physics = [(o.as_pointer(), bool(o.rigid_body), bool(o.rigid_body_constraint)) for o in scene.objects]
addon.project_io.on_load(None)
payload = Path(addon.__file__).resolve().parent
report = {'scope': 'OUTLINE-PREVIEW-COMPATIBILITY', 'complete': False, 'checks': {}, 'renders': [],
          'source_sha256': {p.name: file_hash(p) for p in payload.glob('*.py')},
          'package_sha256': file_hash(args.candidate) if args.candidate else None}


def check(name, value):
    report['checks'][name] = bool(value)
    (OUT / 'compatibility.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    assert value, name


def flush():
    bpy.context.view_layer.update()
    bpy.context.view_layer.update()


def render(name):
    bpy.ops.render.render()
    path = OUT / (name + '.png')
    bpy.data.images['Render Result'].save_render(str(path))
    image = bpy.data.images.load(str(path), check_existing=False)
    values = np.array(image.pixels[:], dtype=np.float32)
    bpy.data.images.remove(image)
    return values


check('migration_preserves_sources_actions_weights', protected(root) == before)
check('migration_preserves_scene_objects_and_physics', physics == [(o.as_pointer(), bool(o.rigid_body), bool(o.rigid_body_constraint)) for o in scene.objects])
mesh = root.hgt_character.meshes[0].object
modifier = next(m for m in mesh.modifiers if m.type == 'NODES' and m.node_group.get('hgt_pmx_outline'))
check('legacy_graph_migrated_to_version_6', modifier.node_group['hgt_outline_version'] == 6)
routes = OutlineRoutes(addon, root)
routes.select('final')
flush()
check('last_modifier_uses_native_preview', not addon.shaders.input_value(modifier, 'Realize Geometry').value)
check('viewport_keeps_original_base_mesh', len(mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices) == len(mesh.data.vertices))
scene.render.resolution_x, scene.render.resolution_y = 320, 480
scene.render.resolution_percentage = 100
scene.eevee.taa_render_samples = 16
for frame, width in ((186, 0), (193, .18), (201, .6642105579376221)):
    scene.frame_set(frame)
    root.hgt_character.outline = width
    routes.select('baseline')
    expected = render(f'{frame}-baseline')
    routes.select('final')
    actual = render(f'{frame}-final')
    maximum = float(np.max(np.abs(actual - expected)))
    check(f'frame_{frame}_final_matches_2110', maximum <= 1 / 255 + 1e-6)
    routes.select('preview')
    preview = render(f'{frame}-preview-geometry')
    difference = np.abs(preview - expected)
    row = {'frame': frame, 'width': width, 'final_max_error': maximum,
           'preview_max_error': float(difference.max()), 'preview_mean_error': float(difference.mean())}
    report['renders'].append(row)
    check(f'frame_{frame}_preview_geometry_matches', row['preview_mean_error'] <= 1e-5 and row['preview_max_error'] <= 2 / 255 + 1e-6)
routes.select('final')
downstream = mesh.modifiers.new('Verification downstream', 'SOLIDIFY')
downstream.thickness = .001
flush()
check('adding_downstream_modifier_enables_complete_mesh', addon.shaders.input_value(modifier, 'Realize Geometry').value)
count = len(mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices)
routes.select('baseline')
expected_count = len(mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices)
check('downstream_result_keeps_complete_outline_geometry', count == expected_count and count > len(mesh.data.vertices) * 2)
routes.select('final')
downstream.show_viewport = False
flush()
check('disabling_downstream_restores_fast_preview', not addon.shaders.input_value(modifier, 'Realize Geometry').value)
downstream.show_viewport = True
mesh.modifiers.move(len(mesh.modifiers) - 1, 0)
flush()
check('reordering_modifier_before_outline_restores_fast_preview', not addon.shaders.input_value(modifier, 'Realize Geometry').value)
mesh.modifiers.remove(downstream)
for obj in bpy.context.selected_objects:
    obj.select_set(False)
mesh.select_set(True)
bpy.context.view_layer.objects.active = mesh
bpy.ops.object.mode_set(mode='EDIT')
flush()
check('edit_mode_uses_complete_geometry', addon.shaders.input_value(modifier, 'Realize Geometry').value)
bpy.ops.object.mode_set(mode='OBJECT')
flush()
check('object_mode_restores_fast_preview', not addon.shaders.input_value(modifier, 'Realize Geometry').value)
scene.frame_set(186)
check('all_checks_preserve_original_data_and_actions', protected(root) == before)
native = render('before-save')
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'verified.blend'), relative_remap=False)
bpy.ops.wm.open_mainfile(filepath=str(OUT / 'verified.blend'), load_ui=False)
scene, root = bpy.context.scene, bpy.context.scene.hgt_target
mesh = root.hgt_character.meshes[0].object
modifier = next(m for m in mesh.modifiers if m.type == 'NODES' and m.node_group.get('hgt_pmx_outline'))
check('save_reopen_preserves_final_pixels', np.array_equal(native, render('after-reopen')))
check('save_reopen_preserves_fast_preview', not addon.shaders.input_value(modifier, 'Realize Geometry').value)
originals = {e.object.name: e.original_data.name for e in root.hgt_character.meshes}
addon.workflow.restore(root)
check('restore_preserves_original_meshes', all(bpy.data.objects[name].data.name == data for name, data in originals.items()))
check('restore_removes_own_outline_modifiers', not any(m.type == 'NODES' and m.node_group and m.node_group.get('hgt_pmx_outline') for m in mesh.modifiers))
report['complete'] = True
(OUT / 'compatibility.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
print('OUTLINE_PREVIEW_COMPATIBILITY', len(report['checks']))
