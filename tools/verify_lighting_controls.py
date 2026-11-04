"""Verify light/shader isolation, height gradients and shared shadow softness."""
import argparse
import json
import math
from pathlib import Path
import statistics
import sys
import time

import bpy
import numpy as np
from mathutils import Matrix

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verification_runtime import load_addon, load_mmd, install_candidate, file_hash, load_reference
from verification_data import array_hash, mesh_data, properties, digest

LIGHT_CASES = (('front', 0, .25), ('left', .8, .25), ('right', -.8, .25),
               ('back_l', math.pi - .02, .25), ('back_r', -math.pi + .02, .25),
               ('up', .8, .9), ('down', .8, -.7))


def pixels(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    data = np.array(image.pixels[:], dtype=np.float32)
    bpy.data.images.remove(image)
    return data


def render(path):
    bpy.context.view_layer.update()
    bpy.ops.render.render(write_still=False)
    bpy.data.images['Render Result'].save_render(str(path))
    return pixels(path)


def light_cases(addon, root, capture):
    scene = bpy.context.scene
    addon.lighting.apply_preset(scene, 'DEFAULT')
    parameters = addon.lighting.active_parameters(scene)
    for label, azimuth, elevation in LIGHT_CASES:
        parameters.azimuth, parameters.elevation = azimuth, elevation
        capture(label)
    parameters.azimuth, parameters.elevation = .8, .25
    settings = root.hgt_character
    head = next(c for c in settings.head.constraints if c.type == 'CHILD_OF')
    bone = settings.source_armature.pose.bones[head.subtarget]
    before = bone.matrix_basis.copy()
    bone.matrix_basis = Matrix.Rotation(.35, 4, 'Z') @ before
    capture('head_turn')
    bone.matrix_basis = before
    source = settings.source_root
    before = source.matrix_world.copy()
    source.matrix_world = Matrix.Rotation(.35, 4, 'Z') @ before
    capture('model_turn')
    source.matrix_world = before
    sun = scene.hgt_light
    before = sun.rotation_euler.copy()
    sun.rotation_euler.x += .37
    capture('sun_roll')
    sun.rotation_euler = before
    for kind, location, energy in (('POINT', (-1, 1.5, 1.8), 30), ('AREA', (.3, -2.5, 2.3), 50)):
        data = bpy.data.lights.new('Verification ' + kind, kind)
        light = bpy.data.objects.new(data.name, data)
        scene.collection.objects.link(light)
        light.location, data.energy = location, energy
        scene.hgt_light = light
        capture(kind.lower())
        addon.lighting.apply_preset(scene, 'DEFAULT')
        bpy.data.objects.remove(light, do_unlink=True)
        bpy.data.lights.remove(data)


def source_state(root):
    s = root.hgt_character
    return digest({'mesh': {e.object.name: mesh_data(e.original_data) for e in s.meshes},
                   'material': {b.source_name: properties(b.source.mmd_material) for b in s.bindings},
                   'bones': [(b.name, [list(row) for row in b.matrix_local]) for b in s.source_armature.data.bones]})


def profile_attributes(root):
    result = {}
    for entry in root.hgt_character.meshes:
        for name, dtype in (('hgt_outline_height', np.float32), ('hgt_outline_surface', np.bool_)):
            attribute = entry.object.data.attributes.get(name)
            if attribute:
                result[(entry.object.name, name)] = array_hash(attribute.data, 'value', 1, dtype)
    return result


def legacy_parameters(root):
    s = root.hgt_character
    return digest({'global': {key: getattr(s, key) for key in ('outline', 'outline_lower', 'shadow_position', 'shadow_transition', 'face_softness')},
                   'local': {b.source_name: [list(b.tint), list(b.shadow_color), list(b.outline_color), b.brightness, b.saturation, b.opacity]
                             for b in s.bindings}})


def main():
    parser = argparse.ArgumentParser()
    for key in ('output-dir', 'mmd-tools', 'fixture-directory', 'baseline-directory'):
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
    payload = Path(addon.__file__).resolve().parent
    legacy = load_reference(project / 'release/hoyo_gi_toon-2.6.1.zip', out / '_reference')
    reference = json.loads((args.baseline_directory / 'report.json').read_text('utf-8'))
    assert reference['complete'] and reference['version'] == '2.5.0'
    report = {'scope': 'GI-TOON-LIGHTING-CONTROLS', 'complete': False, 'models': [],
              'source_sha256': {p.name: file_hash(p) for p in payload.glob('*.py')},
              'package_sha256': file_hash(args.candidate) if args.candidate else None,
              'baseline_archive_sha256': reference['archive_sha256'], 'cpu_only': True}

    def save():
        assert report['source_sha256'] == {p.name: file_hash(p) for p in payload.glob('*.py')}
        (out / 'lighting-controls.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')

    for index, baseline in enumerate(reference['models']):
        fixture = args.fixture_directory / baseline['name'] / 'model.blend'
        assert file_hash(fixture) == baseline['fixture_sha256']
        bpy.app.handlers.load_post.remove(addon.project_io.on_load)
        try:
            bpy.ops.wm.open_mainfile(filepath=str(fixture), load_ui=False)
        finally:
            bpy.app.handlers.load_post.append(addon.project_io.on_load)
        scene, root = bpy.context.scene, bpy.context.scene.hgt_target
        legacy.project_io.on_load(None)
        root.hgt_character.shadow_softness = .001
        root.hgt_character.outline = 0
        scene.render.resolution_x, scene.render.resolution_y = 384, 576
        scene.render.resolution_percentage = 100
        zero_reference = {}

        def capture_zero(label):
            legacy.workflow.refresh_character(root, scene=scene)
            zero_reference[label] = render(out / f'{index}-legacy-zero-{label}.png')
        light_cases(legacy, root, capture_zero)
        before_source, before_parameters = source_state(root), legacy_parameters(root)
        attributes = profile_attributes(root)
        addon.project_io.on_load(None)
        s = root.hgt_character
        assert source_state(root) == before_source and legacy_parameters(root) == before_parameters
        assert profile_attributes(root) == attributes
        assert s.lighting_version == addon.lighting.UNIFORM_VERSION
        assert s.outline_profile and s.outline_top == 1
        assert abs(max(.001, s.shadow_softness) - s.shadow_transition) < 1e-7
        assert all(addon.shaders.input_value(m, 'Light Direction').value is None for e in s.meshes for m in e.object.modifiers
                   if m.type == 'NODES' and m.node_group == s.light_vectors)
        row = {'name': baseline['name'], 'frames': {}, 'checks': {'legacy_parameters_and_source_preserved': True,
               'rest_height_and_inner_mask_preserved': True, 'geometry_light_reference_detached': True}}
        report['models'].append(row)
        scene.render.resolution_x, scene.render.resolution_y = 384, 576
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = 'PNG'
        s.outline = 0

        def capture(label):
            path = out / f'{index}-{label}.png'
            image = render(path)
            expected = zero_reference[label]
            error = np.abs(image - expected)
            assert float(error.max()) <= 1 / 255 + 1e-6, (baseline['name'], label, float(error.max()))
            assert float(error.mean()) < 1e-5
            row['frames'][label] = {'max_error': float(error.max()), 'mean_error': float(error.mean())}
        light_cases(addon, root, capture)
        row['colour_reference'] = 'immutable-2.6.1-zero-shadow-softness'
        row['checks']['sun_point_area_head_and_root_match_261_zero'] = True
        selected = scene.hgt_light
        before_clear = render(out / f'{index}-before-clear.png')
        scene.hgt_light = None
        # Keep physical scene illumination fixed while checking Toon fallback.
        selected.hide_render = selected.hide_viewport = False
        assert np.array_equal(before_clear, render(out / f'{index}-cleared-light.png'))
        scene.hgt_light = selected
        row['checks']['clearing_light_freezes_last_direction'] = True
        s.outline = .18
        parameters = addon.lighting.active_parameters(scene)
        helper_rotation = tuple(s.light.rotation_euler)
        timings = []
        for step in range(24):
            start = time.perf_counter()
            parameters.azimuth = .15 + step * .021
            bpy.context.view_layer.update()
            if step >= 4:
                timings.append((time.perf_counter() - start) * 1000)
        assert tuple(s.light.rotation_euler) == helper_rotation
        median = statistics.median(timings)
        assert median < baseline['light_rotation_median_ms'] * .5, (baseline['name'], median)
        row['performance'] = {'median_ms': median, 'max_ms': max(timings),
                              'baseline_median_ms': baseline['light_rotation_median_ms'],
                              'speedup': baseline['light_rotation_median_ms'] / median}
        row['checks']['full_outline_light_update_faster_and_helper_static'] = True
        s.outline = .8
        default = render(out / f'{index}-profile-default.png')
        profile = addon.outline_profile.snapshot(s)
        responses = {}
        for label, key, value in (('top', 'outline_top', .15), ('bottom', 'outline_lower', .95)):
            setattr(s, key, value)
            edited = render(out / f'{index}-profile-{label}.png')
            responses[label] = float(np.abs(default - edited).max())
            assert responses[label] > .01, (baseline['name'], label, responses[label])
            addon.outline_profile.restore(s, profile)
        addon.outline_profile.node(s).color_ramp.elements.new(.48).color = (0, 0, 0, 1)
        edited = render(out / f'{index}-profile-middle.png')
        responses['middle'] = float(np.abs(default - edited).max())
        assert responses['middle'] > .01
        addon.outline_profile.restore(s, profile)
        row['gradient_responses'] = responses
        s.outline_top = s.outline_lower = 0
        zero_profile = render(out / f'{index}-profile-zero.png')
        s.outline = 0
        no_outline = render(out / f'{index}-outline-off.png')
        assert float(np.abs(zero_profile - no_outline).max()) <= 1 / 255 + 1e-6
        addon.outline_profile.restore(s, profile)
        s.outline = .8
        row['checks']['zero_gradient_preserves_surface'] = True
        total_width=s.outline
        mean=(s.outline_top+s.outline_lower)*.5
        s.outline_difference=0
        assert abs(s.outline_top-s.outline_lower)<1e-6
        uniform=render(out / f'{index}-difference-zero.png')
        single_responses={}
        for value in (.8,-.8):
            s.outline_difference=value
            assert abs(s.outline_difference-value)<1e-6
            assert abs((s.outline_top+s.outline_lower)*.5-mean)<1e-6
            assert (s.outline_top>mean>s.outline_lower) if value>0 else (s.outline_top<mean<s.outline_lower)
            assert s.outline==total_width
            image=render(out / f'{index}-difference-{value}.png')
            single_responses[str(value)]=float(np.abs(image-uniform).max())
            assert single_responses[str(value)]>.01
        s.outline_difference=.65
        row['single_difference_responses']=single_responses
        row['checks']['single_difference_changes_both_ends']=True
        custom = render(out / f'{index}-profile-custom.png')
        assert float(np.abs(default - custom).max()) > .02
        assert profile_attributes(root) == attributes
        saved_profile = addon.outline_profile.snapshot(s)
        old_global = (s.shadow_softness, s.face_softness_adjust, s.shadow_bias)
        s.shadow_softness = .14
        assert abs(s.shadow_transition - .14) < 1e-6
        assert abs(s.face_softness - .08 * s.face_softness_adjust) < 1e-6
        soft = render(out / f'{index}-global-soft.png')
        assert float(np.abs(soft - custom).max()) > .005
        body_softness = s.shadow_transition
        s.face_softness_adjust = .5
        assert s.shadow_transition == body_softness and abs(s.face_softness - .04) < 1e-6
        s.shadow_bias = .1
        assert abs(s.shadow_position - .62) < 1e-6
        s.shadow_softness, s.face_softness_adjust, s.shadow_bias = old_global
        row['checks']['editable_gradient_both_ends_and_middle'] = True
        row['checks']['overall_softness_and_face_compensation'] = True
        row['checks']['advanced_bias_controls_existing_threshold'] = True
        before_save = render(out / f'{index}-save.png')
        bpy.ops.wm.save_as_mainfile(filepath=str(out / f'{index}-controls.blend'), relative_remap=False)
        bpy.ops.wm.open_mainfile(filepath=str(out / f'{index}-controls.blend'), load_ui=False)
        root, s = bpy.context.scene.hgt_target, bpy.context.scene.hgt_target.hgt_character
        assert addon.outline_profile.snapshot(s) == saved_profile
        assert np.array_equal(before_save, render(out / f'{index}-reopen.png'))
        assert source_state(root) == before_source and profile_attributes(root) == attributes
        addon.workflow.restore(root)
        addon.workflow.apply_materials(root, bpy.context)
        assert addon.outline_profile.snapshot(root.hgt_character) == saved_profile
        assert source_state(root) == before_source
        addon.outline_profile.restore(root.hgt_character, profile)
        addon.material_controls.reset(root)
        assert abs(root.hgt_character.outline_top - 1) < 1e-6
        assert abs(root.hgt_character.outline_lower - .35) < 1e-6
        row['checks']['save_reopen_exact_and_restore_reapply_preserves_profile'] = True
        assert file_hash(fixture) == baseline['fixture_sha256']
        save()
        print('HGT_LIGHTING_CONTROLS', row['name'], row['performance'], flush=True)
    report['complete'] = True
    save()
    print('HGT_LIGHTING_CONTROLS_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
