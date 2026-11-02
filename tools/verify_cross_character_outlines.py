"""Verify a real ZIP against independently rendered cross-character fixtures."""
import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verification_runtime import load_mmd, install_candidate, file_hash, load_addon
from verification_data import mesh_data, properties, digest, array_hash

parser = argparse.ArgumentParser()
for key in ('fixture-index', 'output-dir', 'mmd-tools'):
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
report = {'scope': 'CROSS-CHARACTER-OUTLINE-PACKAGE', 'complete': False, 'models': [],
          'package_sha256': file_hash(args.candidate) if args.candidate else None,
          'source_sha256': {p.name: file_hash(p) for p in payload.glob('*.py')}}


def save():
    (out / 'cross-character-package.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')


def pixels(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    values = np.array(image.pixels[:], dtype=np.float32).reshape((576, 384, 4))
    bpy.data.images.remove(image)
    return values


def render(path, root):
    addon.workflow.refresh_character(root, scene=bpy.context.scene)
    bpy.context.view_layer.update()
    bpy.ops.render.render()
    bpy.data.images['Render Result'].save_render(str(path))
    return pixels(path)


def core(off, on):
    safe = off[:, :, 3] > .98
    for y in range(-3, 4):
        for x in range(-3, 4):
            safe &= np.roll(off[:, :, 3] > .98, (y, x), axis=(0, 1))
    a, b = off[:, :, :3].max(axis=2), on[:, :, :3].max(axis=2)
    mask = safe & (a > .28) & (b < .20) & (a - b > .15)
    result = mask.copy()
    for y in (-1, 0, 1):
        for x in (-1, 0, 1):
            result &= np.roll(mask, (y, x), axis=(0, 1))
    result[:4, :] = result[-4:, :] = False
    result[:, :4] = result[:, -4:] = False
    return result


def parameters(root):
    s = root.hgt_character
    return digest({'global': {k: getattr(s, k) for k in ('outline', 'outline_lower', 'shadow_position', 'shadow_transition', 'face_softness')},
                   'materials': {b.source_name: [list(b.tint), list(b.shadow_color), list(b.outline_color),
                                               b.brightness, b.saturation, b.opacity] for b in s.bindings}})


def largest_region(mask):
    remaining = set(map(tuple, np.argwhere(mask)))
    maximum = 0
    while remaining:
        queue, count = [remaining.pop()], 0
        while queue:
            y, x = queue.pop()
            count += 1
            for point in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if point in remaining:
                    remaining.remove(point)
                    queue.append(point)
        maximum = max(maximum, count)
    return maximum


def source(root):
    s = root.hgt_character
    return digest({'meshes': {e.object.name: mesh_data(e.original_data) for e in s.meshes},
                   'materials': {b.source_name: properties(b.source.mmd_material) for b in s.bindings},
                   'bones': [(b.name, b.parent.name if b.parent else None, [list(r) for r in b.matrix_local]) for b in s.source_armature.data.bones]})


fixtures = json.loads(args.fixture_index.read_text('utf-8'))['fixtures']
for fixture in fixtures:
    folder = out / fixture['case_key']
    folder.mkdir(exist_ok=True)
    # Use the camera saved by the independently verified source run.
    bpy.ops.wm.open_mainfile(filepath=fixture['source_project'], load_ui=False)
    camera_matrix = bpy.context.scene.camera.matrix_world.copy()
    camera_scale = bpy.context.scene.camera.data.ortho_scale
    if addon.project_io.on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(addon.project_io.on_load)
    try:
        bpy.ops.wm.open_mainfile(filepath=fixture['legacy_project'], load_ui=False)
    finally:
        bpy.app.handlers.load_post.append(addon.project_io.on_load)
    scene = bpy.context.scene
    root = scene.hgt_target
    settings = root.hgt_character
    before_source, before_parameters = source(root), parameters(root)
    before_profile = {e.object.name: array_hash(e.object.data.attributes['hgt_outline_height'].data, 'value') for e in settings.meshes}
    addon.project_io.on_load(None)
    assert source(root) == before_source and parameters(root) == before_parameters
    assert before_profile == {e.object.name: array_hash(e.object.data.attributes['hgt_outline_height'].data, 'value') for e in settings.meshes}
    assert all(m.node_group.get('hgt_outline_version') == 4 for e in settings.meshes for m in e.object.modifiers
               if m.type == 'NODES' and m.node_group and m.node_group.get('hgt_pmx_outline'))
    scene.camera.matrix_world = camera_matrix
    scene.camera.data.ortho_scale = camera_scale
    settings.outline = .6642105579376221
    right = render(folder / 'source-comparison.png', root)
    expected = pixels(Path(fixture['source_right_wide']))
    error = float(np.abs(right - expected).max())
    assert error <= 1 / 255 + 1e-6, (fixture['name'], 'Fresh source versus migrated ZIP', error)
    selected = {n.inputs['Material'].default_value for e in settings.meshes for m in e.object.modifiers
                if m.type == 'NODES' and m.node_group and m.node_group.get('hgt_pmx_outline')
                for n in m.node_group.nodes if n.bl_idname == 'GeometryNodeMaterialSelection'}
    intended = [b for b in settings.bindings if addon.pmx_materials.is_inner_surface(b.source)
                and addon.pmx_materials.visible_source_edge(json.loads(b.generated['hgt_pmx']))
                and b.role not in {'eye', 'brow', 'expression'}]
    assert all(b.generated in selected for b in intended)
    row = {'case_key': fixture['case_key'], 'name': fixture['name'], 'views': {},
           'source_image_max_error': error, 'migration_parameters_and_profile_preserved': True,
           'source_data_preserved': True, 'intentional_source_edges_preserved': [b.source_name for b in intended]}
    report['models'].append(row)
    positions = [e.object.matrix_world @ v.co for e in settings.meshes for v in e.original_data.vertices]
    low = Vector(tuple(min(p[i] for p in positions) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in positions) for i in range(3)))
    center, height = (low + high) / 2, high.z - low.z
    for view, direction in (('front', (0, -1, 0)), ('back', (0, 1, 0)), ('left', (-1, 0, 0)), ('right', (1, 0, 0))):
        scene.camera.location = center + Vector(direction) * height * 3
        scene.camera.rotation_euler = (center - scene.camera.location).to_track_quat('-Z', 'Y').to_euler()
        horizontal = high.x - low.x if view in {'front', 'back'} else high.y - low.y
        scene.camera.data.ortho_scale = max(height * 1.08, horizontal * 1.08 / (2 / 3))
        settings.outline = 0
        off = render(folder / (view + '-off.png'), root)
        row['views'][view] = {}
        for label, width in (('default', .18), ('wide', .6642105579376221)):
            settings.outline = width
            on = render(folder / (view + '-' + label + '.png'), root)
            mask = core(off, on)
            count = int(mask.sum())
            largest = largest_region(mask)
            fraction = count / max(1, int(np.count_nonzero(off[:, :, 3] > .98)))
            assert largest < 20 and fraction < .002, (fixture['name'], view, label, largest, fraction)
            row['views'][view][label] = {'core_pixels': count, 'core_fraction': fraction,
                                         'largest_core_region': largest,
                                         'outer_silhouette_pixels': int(np.count_nonzero(on[:, :, 3] > off[:, :, 3] + .05))}
        save()
    assert sum(v['wide']['outer_silhouette_pixels'] for v in row['views'].values()) > 0
    before = render(folder / 'before-save.png', root)
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'verified.blend'), relative_remap=False)
    bpy.ops.wm.open_mainfile(filepath=str(folder / 'verified.blend'), load_ui=False)
    after = render(folder / 'reopened.png', bpy.context.scene.hgt_target)
    assert np.array_equal(before, after), fixture['name']
    row['save_reopen_exact'] = True
    save()
    print('HGT_CROSS_PACKAGE', row['name'], error, flush=True)
report['complete'] = True
save()
print('HGT_CROSS_PACKAGE_COMPLETE', len(report['models']), flush=True)
