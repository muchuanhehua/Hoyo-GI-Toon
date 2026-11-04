"""Verify unchanged body end colors and face colors at a zero blur radius."""
import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verification_runtime import load_addon, install_candidate, load_mmd, file_hash
from verify_lighting_controls import render, source_state


def debug(settings, category, mode):
    plans = []
    for binding in settings.bindings:
        material = binding.generated
        tree = material.node_tree
        socket = tree.nodes['HGT • Surface Color'].inputs['Color']
        plans.append((tree, socket, socket.links[0].from_socket))
        selected = binding.role not in {'eye', 'brow', 'expression'} and ((material.get('hgt_template') == 'Face') == (category == 'face'))
        for link in tuple(socket.links):tree.links.remove(link)
        if not selected:
            socket.default_value = (0, 0, 0, 1)
        elif mode == 'coverage':
            socket.default_value = (1, 1, 1, 1)
        else:
            shader = tree.nodes['Body Shader']
            factor = shader.outputs['Lit Factor']
            if mode == 'transition':
                values = []
                for operation, threshold in (('GREATER_THAN', 0), ('LESS_THAN', 1)):
                    node = tree.nodes.new('ShaderNodeMath')
                    node.operation = operation
                    tree.links.new(factor, node.inputs[0])
                    node.inputs[1].default_value = threshold
                    values.append(node.outputs[0])
                node = tree.nodes.new('ShaderNodeMath')
                node.operation = 'MULTIPLY'
                for source, target in zip(values, node.inputs):tree.links.new(source, target)
                factor = node.outputs[0]
            tree.links.new(factor, socket)
    return plans


def restore(plans):
    for tree, socket, source in plans:tree.links.new(source, socket)


def floating(path):
    scene = bpy.context.scene
    options = scene.render.image_settings
    before = options.file_format, options.color_depth, options.color_mode
    try:
        options.file_format, options.color_depth, options.color_mode = 'OPEN_EXR', '32', 'RGBA'
        bpy.context.view_layer.update()
        bpy.ops.render.render()
        bpy.data.images['Render Result'].save_render(str(path))
        image = bpy.data.images.load(str(path), check_existing=False)
        result = np.array(image.pixels[:], dtype=np.float32).reshape((512, 512, 4))
        bpy.data.images.remove(image)
        return result
    finally:
        options.file_format, options.color_depth, options.color_mode = before


def main():
    parser = argparse.ArgumentParser()
    for key in ('output-dir', 'boundary-verification', 'mmd-tools'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--candidate', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    project = Path(__file__).resolve().parents[1]
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    load_mmd(args.mmd_tools, out / '_runtime')
    addon = install_candidate(args.candidate, out) if args.candidate else load_addon(project)
    if bpy.app.timers.is_registered(addon.project_io._migrate_open_project):
        bpy.app.timers.unregister(addon.project_io._migrate_open_project)
    payload = Path(addon.__file__).resolve().parent
    hashes = {p.name: file_hash(p) for p in payload.glob('*.py')}
    reference = json.loads(args.boundary_verification.read_text('utf-8'))
    assert reference['complete'] and reference['source_sha256'] == hashes
    package_hash = file_hash(args.candidate) if args.candidate else None
    assert reference['package_sha256'] == package_hash
    report = {'scope': 'GI-TOON-SHADOW-COLOURS', 'complete': False, 'models': [],
              'source_sha256': hashes, 'package_sha256': package_hash}
    for name in ('安柏', '纳西妲', '奥黛塔'):
        folder = out / name
        folder.mkdir(exist_ok=True)
        bpy.ops.wm.open_mainfile(filepath=str(args.boundary_verification.parent / name / 'verified.blend'), load_ui=False)
        scene, root = bpy.context.scene, bpy.context.scene.hgt_target
        settings = root.hgt_character
        protected = source_state(root)
        settings.shadow_softness = 0
        hard = render(folder / 'hard.png').reshape((512, 512, 4))
        plans = debug(settings, 'body', 'coverage')
        coverage = floating(folder / 'body-coverage.exr')
        restore(plans)
        plans = debug(settings, 'body', 'factor')
        a = render(folder / 'body-hard-mask.png').reshape((512, 512, 4))
        restore(plans)
        plans = debug(settings, 'body', 'transition')
        transition_hard = floating(folder / 'body-hard-transition.exr')
        settings.shadow_softness = .5
        transition_soft = floating(folder / 'body-soft-transition.exr')
        restore(plans)
        plans = debug(settings, 'body', 'factor')
        b = render(folder / 'body-soft-mask.png').reshape((512, 512, 4))
        restore(plans)
        soft = render(folder / 'soft.png').reshape((512, 512, 4))
        same_shadow = np.all(a[:, :, :3] < 1e-6, axis=2) & np.all(b[:, :, :3] < 1e-6, axis=2)
        same_light = np.all(a[:, :, :3] > 1 - 1e-6, axis=2) & np.all(b[:, :, :3] > 1 - 1e-6, axis=2)
        no_transition = np.all(transition_hard[:, :, :3] < 1e-7, axis=2) & np.all(transition_soft[:, :, :3] < 1e-7, axis=2)
        core = (same_shadow | same_light) & no_transition & np.all(coverage[:, :, :3] > 1 - 1e-6, axis=2) & (coverage[:, :, 3] > 1 - 1e-6)
        # An 8-bit mask rounds values near 1 to white. Exclude the transition's
        # antialiased border so this checks the actual constant-color regions.
        safe = core.copy()
        for y in range(-2, 3):
            for x in range(-2, 3):safe &= np.roll(core, (y, x), axis=(0, 1))
        core = safe
        assert int(core.sum()) > 1000, (name, int(core.sum()))
        body_core_count = int(core.sum())
        body_delta = np.abs(hard[core, :3] - soft[core, :3])
        body_error = float(body_delta.max())
        body_mean = float(body_delta.mean())
        body_outliers = float(np.mean(body_delta.max(axis=1) > 1 / 255 + 1e-6))
        print('HGT_BODY_CORE', name, body_core_count, body_error, flush=True)
        # The zero reference itself remains bit exact. Positive-style draws
        # can differ by two 8-bit steps at an isolated texture sample; require
        # the region mean and outlier fraction to rule out any overall tint.
        assert body_error <= 2 / 255 + 1e-6 and body_mean < 1e-4 and body_outliers < .002, (name, body_error, body_mean, body_outliers)
        settings.face_softness_adjust = 0
        settings.shadow_softness = 0
        face_hard = render(folder / 'face-zero-radius-hard.png').reshape((512, 512, 4))
        settings.shadow_softness = .5
        face_soft = render(folder / 'face-zero-radius-positive.png').reshape((512, 512, 4))
        plans = debug(settings, 'face', 'coverage')
        face_coverage = floating(folder / 'face-coverage.exr')
        restore(plans)
        core = np.all(face_coverage[:, :, :3] > 1 - 1e-6, axis=2) & (face_coverage[:, :, 3] > 1 - 1e-6)
        safe = core.copy()
        for y in range(-2, 3):
            for x in range(-2, 3):safe &= np.roll(core, (y, x), axis=(0, 1))
        core = safe
        assert int(core.sum()) > 20, (name, 'No opaque face pixels', int(core.sum()))
        face_error = float(np.abs(face_hard[core, :3] - face_soft[core, :3]).max())
        assert face_error <= 1 / 255 + 1e-6, (name, 'Face zero-radius colors changed', face_error)
        assert source_state(root) == protected
        row = {'name': name, 'body_core_pixels': body_core_count,
               'body_color_max_error': body_error, 'face_pixels': int(core.sum()), 'face_color_max_error': face_error,
               'body_color_mean_error': body_mean, 'body_color_outlier_fraction': body_outliers,
               'body_endcolors_preserved': True, 'face_zero_radius_colors_preserved': True, 'source_preserved': True}
        report['models'].append(row)
        print('HGT_SHADOW_COLOURS_MODEL', name, body_error, face_error, flush=True)
    assert hashes == {p.name: file_hash(p) for p in payload.glob('*.py')}
    report['complete'] = True
    (out / 'shadow-colors.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')


if __name__ == '__main__':main()
