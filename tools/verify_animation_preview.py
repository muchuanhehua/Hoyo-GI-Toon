"""Bounded animation/uniform regression for the Eevee preview performance fix."""
import argparse
import ast
import json
import math
from pathlib import Path
import sys
import zipfile

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verification_runtime import file_hash, install_candidate, load_mmd

parser = argparse.ArgumentParser()
for key in ('output-dir', 'candidate', 'fixture', 'mmd-tools'):
    parser.add_argument('--' + key, type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
OUT = args.output_dir.resolve()
assert OUT.is_relative_to(ROOT / '.verification')
OUT.mkdir(parents=True, exist_ok=True)
load_mmd(args.mmd_tools, OUT / '_runtime')
addon = install_candidate(args.candidate, OUT)
payload = Path(addon.__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(args.fixture), load_ui=False)
scene = bpy.context.scene
root = scene.hgt_target
assert root and addon.workflow.current(root), ('Missing tracked root', root.name if root else None)
settings = root.hgt_character
if addon.glow.is_active(scene):
    addon.glow.disable(scene)
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x, scene.render.resolution_y = 256, 384
scene.render.resolution_percentage = 100
scene.eevee.taa_render_samples = 16
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
report = {'scope': 'ANIMATION-PREVIEW-COMPATIBILITY', 'complete': False,
          'package_sha256': file_hash(args.candidate),
          'source_sha256': {p.name: file_hash(p) for p in payload.glob('*.py')},
          'checks': {}, 'renders': []}


def check(name, condition):
    assert condition, name
    report['checks'][name] = True


def fresh_uniforms():
    graph = bpy.context.evaluated_depsgraph_get()
    graph.update()
    evaluated = graph.scene_eval
    expected = addon.lighting.shader_vectors(root, graph)
    for name, vector in expected.items():
        value = evaluated[f'hgt_{settings.uid}_{name}']
        assert np.allclose(value[:3], vector, atol=1e-6), (name, list(value), vector)
    for name, value in (('hgt_shadow_position', settings.shadow_position),
                        ('hgt_shadow_softness', settings.shadow_softness)):
        assert abs(evaluated[f'hgt_{settings.uid}_{name}'] - value) < 1e-6
    return graph


def render(label):
    bpy.ops.render.render(write_still=False)
    path = OUT / (label + '.png')
    bpy.data.images['Render Result'].save_render(str(path))
    image = bpy.data.images.load(str(path), check_existing=False)
    pixels = np.array(image.pixels[:], dtype=np.float32)
    bpy.data.images.remove(image)
    return pixels


new_controls = addon.shaders.set_controls
with zipfile.ZipFile(ROOT / 'release/hoyo_gi_toon-2.9.2.zip') as package:
    old_namespace = dict(addon.shaders.__dict__)
    exec(compile(package.read('shaders.py'), 'release-2.9.2/shaders.py', 'exec'), old_namespace)
    old_controls = old_namespace['set_controls']
    old_tree = ast.parse(package.read('workflow.py').decode('utf-8'))
    old_current = next(n for n in old_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'current')
    namespace = {}
    exec(compile(ast.Module(body=[old_current], type_ignores=[]), '<old-current>', 'exec'), namespace)
    check('tracked_roots_match_previous_version',
          {o.as_pointer() for o in bpy.data.objects if addon.workflow.current(o)} ==
          {o.as_pointer() for o in bpy.data.objects if namespace['current'](o)})

head_constraint = next(c for c in settings.head.constraints if c.type == 'CHILD_OF')
bone = settings.source_armature.pose.bones[head_constraint.subtarget]
bone.rotation_mode = 'XYZ'
bone.rotation_euler = (0, 0, 0)
bone.keyframe_insert(data_path='rotation_euler', frame=1)
bone.rotation_euler.z = .45
bone.keyframe_insert(data_path='rotation_euler', frame=8)
binding = next(b for b in settings.bindings if b.role == 'body')
binding.tint = (1, 1, 1)
binding.opacity = 1
binding.keyframe_insert(data_path='tint', frame=1)
binding.keyframe_insert(data_path='opacity', frame=1)
binding.tint = (.6, .8, 1)
binding.opacity = .65
binding.keyframe_insert(data_path='tint', frame=8)
binding.keyframe_insert(data_path='opacity', frame=8)
settings.outline = .25
settings.keyframe_insert(data_path='outline', frame=1)
settings.outline = .55
settings.keyframe_insert(data_path='outline', frame=8)

for frame, position, glow in ((1, .3, False), (8, .7, False), (8, .7, True)):
    label = f'frame-{frame}-glow-{int(glow)}'
    if glow:
        addon.glow.enable(scene)
    addon.shaders.set_controls = new_controls
    scene.frame_set(frame)
    settings.shadow_position = position
    graph = fresh_uniforms()
    expected_tint = (*binding.tint, 1)
    tint = binding.generated.node_tree.nodes['HGT • Material Tint'].inputs[2].default_value
    opacity = binding.generated.node_tree.nodes['HGT • Opacity'].inputs[1].default_value
    check(label + '-animated-local-controls', np.allclose(tint, expected_tint) and abs(opacity - binding.opacity) < 1e-6)
    for entry in settings.meshes:
        if entry.object:
            modifier = next(m for m in entry.object.modifiers if m.type == 'NODES'
                            and m.node_group and m.node_group.get('hgt_pmx_outline'))
            width = addon.shaders.input_value(modifier, 'Outline Thickness').value
            scale = max(sum(entry.object.matrix_world.to_scale()) / 3, 1e-6)
            check(label + '-animated-outline-' + entry.object.name,
                  abs(width - settings.outline * settings.height / (1.7 * scale)) < 1e-6)
    check(label + '-evaluated-uniforms-current', True)
    actual = render(label + '-candidate')
    addon.shaders.set_controls = old_controls
    addon.workflow.refresh_character(root, scene=scene)
    reference = render(label + '-reference')
    difference = np.abs(actual - reference)
    check(label + '-render-matches-2.9.2', float(difference.max()) < 1e-6)
    report['renders'].append({'case': label, 'max_abs_error': float(difference.max()),
                              'mean_abs_error': float(difference.mean())})

addon.shaders.set_controls = new_controls
layer = scene.view_layers[scene.hgt_glow.render_layer]
with bpy.context.temp_override(view_layer=layer):
    graph = bpy.context.evaluated_depsgraph_get()
    graph.update()
    prefix = f'hgt_{settings.uid}_'
    before = {k: list(v) if hasattr(v, '__len__') and not isinstance(v, str) else v
              for k, v in scene.items() if k.startswith(prefix)}
    addon.workflow.update_frame(scene, graph)
    addon.workflow.update_scene(scene, graph)
    after = {k: list(v) if hasattr(v, '__len__') and not isinstance(v, str) else v
             for k, v in scene.items() if k.startswith(prefix)}
    check('auxiliary_callbacks_preserve_main_uniforms', before == after)
addon.glow.disable(scene)
check('glow_disable_removes_owned_layer', not scene.hgt_glow.render_layer)
for handlers, callback in ((bpy.app.handlers.frame_change_post, addon.workflow.update_frame),
                           (bpy.app.handlers.depsgraph_update_post, addon.workflow.update_scene)):
    check(callback.__name__ + '-registered-once', handlers.count(callback) == 1)
report['complete'] = True
(OUT / 'compatibility.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
print('ANIMATION_PREVIEW_COMPATIBILITY', len(report['checks']), len(report['renders']), flush=True)
