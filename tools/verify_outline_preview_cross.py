"""Compare both outline paths with 2.11.0 across four views and three widths."""
import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verification_runtime import load_mmd, install_candidate, load_addon, file_hash
from outline_verification import OutlineRoutes, protected
parser = argparse.ArgumentParser()
for name in ('fixture-index', 'output-dir', 'mmd-tools'):
    parser.add_argument('--' + name, type=Path, required=True)
parser.add_argument('--candidate', type=Path)
parser.add_argument('--start-index', type=int, default=0)
parser.add_argument('--limit', type=int)
parser.add_argument('--resume', action='store_true')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
OUT = args.output_dir.resolve()
assert OUT.is_relative_to(ROOT / '.verification')
OUT.mkdir(parents=True, exist_ok=True)
load_mmd(args.mmd_tools, OUT / '_runtime')
addon = install_candidate(args.candidate, OUT) if args.candidate else load_addon(ROOT)
if bpy.app.timers.is_registered(addon.project_io._migrate_open_project):
    bpy.app.timers.unregister(addon.project_io._migrate_open_project)
payload = Path(addon.__file__).resolve().parent
report = {'scope': 'CROSS-CHARACTER-OUTLINE-PREVIEW', 'complete': False, 'models': [],
          'package_sha256': file_hash(args.candidate) if args.candidate else None,
          'source_sha256': {p.name: file_hash(p) for p in payload.glob('*.py')},
          'pixel_metric': 'Worst RGB difference composited over black and white, plus alpha; straight RGB retained separately.',
          'comparison': 'Frozen 2.11.0 outline graph versus the exact native-instance viewport branch, rendered with identical EEVEE settings; final route checked separately.'}
if args.resume:
    previous = json.loads((OUT / 'cross-character.json').read_text('utf-8'))
    assert previous['package_sha256'] == report['package_sha256'] and previous['source_sha256'] == report['source_sha256']
    report['models'] = previous['models']


def preview_matches(row):
    # Coverage and opaque colour stay strict. A few antialiased boundary pixels
    # can shade differently when identical geometry changes draw batching.
    return row['alpha_max_error'] <= 1/255+1e-6 and row['mean_error'] <= 1e-5 and (
        row['max_error'] <= 2/255+1e-6 or (row['opaque_max_error'] <= 2/255+1e-6
        and row['mean_error'] <= 1e-6 and row['pixels_over_one_byte'] <= 32))


def save():
    (OUT / 'cross-character.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')


def pixels(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    values = np.array(image.pixels[:], dtype=np.float32)
    bpy.data.images.remove(image)
    return values


def render(path):
    bpy.context.view_layer.update()
    bpy.ops.render.render()
    bpy.data.images['Render Result'].save_render(str(path))
    return pixels(path)


def comparison(baseline, preview):
    a, b = baseline.reshape((-1, 4)), preview.reshape((-1, 4))
    # Straight RGB at alpha 1/255 can amplify an imperceptible rounding error.
    # Test appearance on both background extremes, including alpha changes.
    black_a, black_b = a[:, :3] * a[:, 3:], b[:, :3] * b[:, 3:]
    white_a, white_b = black_a + 1-a[:, 3:], black_b + 1-b[:, 3:]
    difference = np.concatenate((np.maximum(np.abs(black_a-black_b), np.abs(white_a-white_b)),
                                 np.abs(a[:, 3:]-b[:, 3:])), axis=1)
    raw = np.abs(a-b)
    opaque = np.minimum(a[:, 3], b[:, 3]) >= .99
    return {'max_error': float(difference.max()), 'mean_error': float(difference.mean()),
            'channels_over_one_byte': int(np.count_nonzero(difference > 1/255+1e-6)),
            'pixels_over_one_byte': int(np.count_nonzero(difference.max(axis=1) > 1/255+1e-6)),
            'opaque_max_error': float(difference[opaque].max()) if opaque.any() else 0.0,
            'straight_rgb_max_error': float(raw[:, :3].max()), 'straight_rgb_mean_error': float(raw[:, :3].mean()),
            'alpha_max_error': float(raw[:, 3].max())}


if args.resume:
    # Reuse exact saved pairs; changing the alpha-aware analysis needs no rerenders.
    for row in report['models']:
        folder = OUT / row['case_key']
        for view in row['views']:
            for width in ('off', 'default', 'wide'):
                baseline = folder / f'{view}-{width}-baseline.png'
                preview = folder / f'{view}-{width}-preview.png'
                if baseline.exists() and preview.exists():
                    row['views'][view][width] = comparison(pixels(baseline), pixels(preview))
                    assert preview_matches(row['views'][view][width]), (row['name'], view, width, row['views'][view][width])
    save()


fixtures = json.loads(args.fixture_index.read_text('utf-8'))['fixtures']
fixtures = fixtures[args.start_index:][:args.limit]
for fixture in fixtures:
    if any(row['case_key'] == fixture['case_key'] and row.get('save_reopen_exact') for row in report['models']):
        continue
    folder = OUT / fixture['case_key']
    folder.mkdir(exist_ok=True)
    bpy.app.handlers.load_post.remove(addon.project_io.on_load)
    bpy.ops.wm.open_mainfile(filepath=fixture['source_project'], load_ui=False)
    bpy.app.handlers.load_post.append(addon.project_io.on_load)
    scene = bpy.context.scene
    root = scene.hgt_target
    before = protected(root)
    parameters = (root.hgt_character.outline, root.hgt_character.outline_lower)
    addon.project_io.on_load(None)
    assert before == protected(root), (fixture['name'], 'Source data changed during migration')
    assert parameters == (root.hgt_character.outline, root.hgt_character.outline_lower)
    scene.render.resolution_x, scene.render.resolution_y = 384, 576
    scene.render.resolution_percentage = 100
    scene.eevee.taa_render_samples = 16
    routes = OutlineRoutes(addon, root)
    row = next((r for r in report['models'] if r['case_key'] == fixture['case_key']), None)
    if row is None:
        row = {'case_key': fixture['case_key'], 'name': fixture['name'], 'views': {},
               'source_data_preserved': True, 'migration_parameters_preserved': True}
        report['models'].append(row)
    points = [e.object.matrix_world @ v.co for e in root.hgt_character.meshes for v in e.original_data.vertices]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center, height = (low + high) / 2, high.z - low.z
    for view, direction in (('front', (0, -1, 0)), ('back', (0, 1, 0)), ('left', (-1, 0, 0)), ('right', (1, 0, 0))):
        scene.camera.location = center + Vector(direction) * height * 3
        scene.camera.rotation_euler = (center - scene.camera.location).to_track_quat('-Z', 'Y').to_euler()
        horizontal = high.x - low.x if view in {'front', 'back'} else high.y - low.y
        scene.camera.data.ortho_scale = max(height * 1.08, horizontal * 1.08 / (2 / 3))
        row['views'].setdefault(view, {})
        for label, width in (('off', 0), ('default', .18), ('wide', .6642105579376221)):
            root.hgt_character.outline = width
            if label in row['views'][view] and preview_matches(row['views'][view][label]):
                if view != 'front' or label != 'wide' or 'final_max_error' in row:
                    continue
            routes.select('baseline')
            baseline = render(folder / f'{view}-{label}-baseline.png')
            routes.select('preview')
            preview = render(folder / f'{view}-{label}-preview.png')
            result = comparison(baseline, preview)
            row['views'][view][label] = result
            save()
            assert preview_matches(result), (fixture['name'], view, label, result)
            if view == 'front' and label == 'wide':
                routes.select('final')
                final = render(folder / 'front-wide-final.png')
                row['final_max_error'] = float(np.abs(final - baseline).max())
                assert row['final_max_error'] <= 1 / 255 + 1e-6, (fixture['name'], 'Final output changed')
        print('OUTLINE_CROSS_VIEW', fixture['case_key'], view, flush=True)
    routes.select('final')
    assert protected(root) == before, (fixture['name'], 'Original data changed')
    saved = render(folder / 'before-save.png')
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'verified.blend'), relative_remap=False)
    bpy.ops.wm.open_mainfile(filepath=str(folder / 'verified.blend'), load_ui=False)
    reopened = render(folder / 'after-reopen.png')
    assert np.array_equal(saved, reopened), (fixture['name'], 'Save/reopen output changed')
    row['save_reopen_exact'] = True
    save()
    print('OUTLINE_CROSS_CHARACTER', fixture['case_key'], flush=True)
report['complete'] = True
save()
print('OUTLINE_CROSS_COMPLETE', len(report['models']))
