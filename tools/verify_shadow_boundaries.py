"""Compare native zero shadows and boundary-only changes in actual runtimes."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

import bpy
import numpy as np
from mathutils import Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verification_runtime import load_mmd, load_addon, install_candidate, load_reference, file_hash
from verify_lighting_controls import render, source_state, LIGHT_CASES


def diagnostic(addon, settings, mode):
    plans = []
    for binding in settings.bindings:
        tree = binding.generated.node_tree
        target = tree.nodes['HGT • Surface Color'].inputs['Color']
        plans.append((tree, target, target.links[0].from_socket))
        shader = addon.face_sdf.shader_node(binding.generated)
        if mode == 'face' and binding.generated.get('hgt_template') != 'Face':
            for old in tuple(target.links):tree.links.remove(old)
            target.default_value = (0, 0, 0, 1)
            continue
        if binding.role in {'eye', 'brow', 'expression'}:
            for old in tuple(target.links):tree.links.remove(old)
            target.default_value = (0, 0, 0, 1)
            continue
        tree.links.new(shader.outputs['Lit Factor'], target)
        if mode == 'face':
            inner = shader.node_tree
            if not any(s.name == 'HGT Verification Primary' and s.in_out == 'OUTPUT' for s in inner.interface.items_tree if s.item_type == 'SOCKET'):
                inner.interface.new_socket(name='HGT Verification Primary', in_out='OUTPUT', socket_type='NodeSocketFloat')
            output = next(n for n in inner.nodes if n.bl_idname == 'NodeGroupOutput' and n.is_active_output)
            inner.links.new(inner.nodes['Face Factor'].outputs['Factor'], output.inputs['HGT Verification Primary'])
            tree.links.new(shader.outputs['HGT Verification Primary'], target)
    return plans


def restore(plans):
    for tree, target, source in plans:tree.links.new(source, target)


def main():
    parser = argparse.ArgumentParser()
    for key in ('output-dir', 'fixture-directory', 'mmd-tools'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--candidate', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    project = Path(__file__).resolve().parents[1]
    out = args.output_dir.resolve()
    assert out.is_relative_to(project / '.verification')
    out.mkdir(parents=True, exist_ok=True)
    load_mmd(args.mmd_tools, out / '_runtime')
    addon = install_candidate(args.candidate, out) if args.candidate else load_addon(project)
    if bpy.app.timers.is_registered(addon.project_io._migrate_open_project):
        bpy.app.timers.unregister(addon.project_io._migrate_open_project)
    legacy = load_reference(project / 'release/hoyo_gi_toon-2.6.1.zip', out / '_reference')
    payload = Path(addon.__file__).resolve().parent
    hashes = {p.name: file_hash(p) for p in payload.glob('*.py')}
    report = {'scope': 'GI-TOON-SHADOW-BOUNDARIES', 'complete': False, 'version': '2.6.2',
              'package_sha256': file_hash(args.candidate) if args.candidate else None,
              'source_sha256': hashes, 'zero_reference': 'immutable-release-v2.6.1', 'models': []}

    def save():
        assert hashes == {p.name: file_hash(p) for p in payload.glob('*.py')}
        (out / 'shadow-boundaries.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')

    for name in ('安柏', '纳西妲', '奥黛塔'):
        folder = out / name
        folder.mkdir(exist_ok=True)
        fixture = args.fixture_directory / name / 'model.blend'
        fixture_hash = file_hash(fixture)
        bpy.app.handlers.load_post.remove(addon.project_io.on_load)
        try:bpy.ops.wm.open_mainfile(filepath=str(fixture), load_ui=False)
        finally:bpy.app.handlers.load_post.append(addon.project_io.on_load)
        scene, root = bpy.context.scene, bpy.context.scene.hgt_target
        legacy.project_io.on_load(None)
        s = root.hgt_character
        protected = source_state(root)
        s.outline = 0
        s.shadow_softness = .001
        owned = {e.object for e in s.meshes}
        for obj in scene.objects:
            if obj.type == 'MESH' and obj not in owned:obj.hide_render = True
        points = [obj.matrix_world @ Vector(c) for obj in owned for c in obj.bound_box]
        low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
        high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
        height = high.z - low.z
        center = Vector(((low.x + high.x) * .5, 0, low.z + height * .82))
        scene.camera.location = center + Vector((0, -height * 3, 0))
        scene.camera.rotation_euler = (center - scene.camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.camera.data.ortho_scale = height * .34
        scene.render.resolution_x = scene.render.resolution_y = 512
        scene.render.resolution_percentage = 100
        addon.lighting.apply_preset(scene, 'DEFAULT')
        parameters = addon.lighting.active_parameters(scene)
        expected = {}
        for label, azimuth, elevation in LIGHT_CASES:
            parameters.azimuth, parameters.elevation = azimuth, elevation
            expected[label] = render(folder / f'legacy-zero-{label}.png')
        parameters.azimuth, parameters.elevation = 1.25, .25
        expected_compensation = {}
        for value in (0, 3):
            s.face_softness_adjust = value
            expected_compensation[value] = render(folder / f'legacy-compensation-{value}.png')
        s.face_softness_adjust = 1
        addon.project_io.on_load(None)
        assert s.shadow_softness == 0
        row = {'name': name, 'zero_lights': {}, 'positive_frames': {}, 'checks': {}}
        report['models'].append(row)
        for label, azimuth, elevation in LIGHT_CASES:
            parameters.azimuth, parameters.elevation = azimuth, elevation
            actual = render(folder / f'zero-{label}.png')
            error = float(np.abs(actual - expected[label]).max())
            assert error == 0, (name, label, error)
            row['zero_lights'][label] = error
        row['checks']['zero_matches_261_all_lights'] = True
        parameters.azimuth, parameters.elevation = 1.25, .25
        row['zero_compensation_errors'] = {}
        for value in (0, 3):
            s.face_softness_adjust = value
            actual = render(folder / f'zero-compensation-{value}.png')
            error = float(np.abs(actual - expected_compensation[value]).max())
            assert error == 0, (name, value, error)
            row['zero_compensation_errors'][str(value)] = error
        s.face_softness_adjust = 1
        row['checks']['zero_face_compensation_preserved'] = True
        s.face_softness = .15
        assert s.shadow_softness == 0 and abs(s.face_softness - .15) < 1e-6
        assert abs(s.face_softness_adjust - 262.5) < .001
        s.face_softness_adjust = 1
        row['checks']['legacy_face_parameter_at_zero'] = True
        s.face_softness_adjust = 0
        s.shadow_softness = 0
        plans = diagnostic(addon, s, 'face')
        hard_face = render(folder / 'face-zero-radius-reference.png')
        s.shadow_softness = .5
        filtered_face = render(folder / 'face-zero-radius-filter.png')
        restore(plans)
        error = float(np.abs(hard_face - filtered_face).max())
        assert error <= 1 / 255 + 1e-6, (name, 'Zero-radius filter changes the original face', error)
        row['zero_radius_face_max_error'] = error
        row['checks']['zero_radius_filter_preserves_native_face'] = True
        s.face_softness_adjust = 1
        parameters.azimuth, parameters.elevation = 1.8, .25
        row['boundary_probe_azimuth'] = 1.8
        s.shadow_softness = 0
        zero = render(folder / 'zero.png')
        masks = {}
        for softness in (0, .035, .15, .3, .5):
            s.shadow_softness = softness
            image = render(folder / f'softness-{softness}.png')
            row['positive_frames'][str(softness)] = {'sha256': file_hash(folder / f'softness-{softness}.png'),
                                                   'max_response': float(np.abs(image - zero).max())}
            plans = diagnostic(addon, s, 'face')
            masks[softness] = render(folder / f'face-mask-{softness}.png')
            restore(plans)
        face_response = float(np.abs(masks[.5] - masks[0]).max())
        assert face_response > .02, (name, face_response)
        assert row['positive_frames']['0.5']['max_response'] > .01
        row['face_mask_response'] = face_response
        row['checks']['face_spatial_boundary_filter_responds'] = True
        row['checks']['overall_control_changes_boundary'] = True
        # Source data and graph topology must remain stable while dragging.
        topology = {t.as_pointer(): len(t.nodes) for b in s.bindings for t in addon.shaders.walk(b.generated.node_tree)}
        helper = tuple(tuple(row) for row in s.light.matrix_world)
        timings = []
        for step in range(24):
            start = time.perf_counter()
            parameters.azimuth = .4 + step * .02
            s.shadow_softness = step / 46
            bpy.context.view_layer.update()
            if step > 3:timings.append((time.perf_counter() - start) * 1000)
        assert helper == tuple(tuple(row) for row in s.light.matrix_world)
        assert topology == {t.as_pointer(): len(t.nodes) for b in s.bindings for t in addon.shaders.walk(b.generated.node_tree)}
        row['cpu_light_and_softness_median_ms'] = statistics.median(timings)
        row['checks']['uniform_only_drag_without_geometry_or_graph_rebuild'] = True
        counts = [(b.generated.as_pointer(), b.generated.get('hgt_boundary_version')) for b in s.bindings]
        addon.material_controls.upgrade(root)
        assert counts == [(b.generated.as_pointer(), b.generated.get('hgt_boundary_version')) for b in s.bindings]
        assert topology == {t.as_pointer(): len(t.nodes) for b in s.bindings for t in addon.shaders.walk(b.generated.node_tree)}
        row['checks']['migration_idempotent'] = True
        parameters.azimuth, parameters.elevation = 1.8, .25
        s.shadow_softness = .3
        before_save = render(folder / 'before-save.png')
        bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'verified.blend'), relative_remap=False)
        bpy.ops.wm.open_mainfile(filepath=str(folder / 'verified.blend'), load_ui=False)
        root, s = bpy.context.scene.hgt_target, bpy.context.scene.hgt_target.hgt_character
        assert np.array_equal(before_save, render(folder / 'reopened.png'))
        row['checks']['save_reopen_exact'] = True
        assert source_state(root) == protected and file_hash(fixture) == fixture_hash
        row['checks']['source_and_fixture_preserved'] = True
        save()
        print('HGT_SHADOW_BOUNDARIES_MODEL', name, face_response, row['cpu_light_and_softness_median_ms'], flush=True)
    report['complete'] = True
    save()
    print('HGT_SHADOW_BOUNDARIES_COMPLETE', flush=True)


if __name__ == '__main__':main()
