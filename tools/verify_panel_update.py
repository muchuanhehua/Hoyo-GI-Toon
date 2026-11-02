"""Exercise bundled SDF switching, wider outlines and protected character data."""
import argparse
import importlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

import bpy
import numpy as np

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verification_runtime import load_addon, load_mmd, install_candidate, file_hash
from verification_data import source_snapshot, mmd_snapshot, array_hash

parser = argparse.ArgumentParser()
for name in ('output-dir', 'assets-index', 'mmd-tools'):
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
faces = importlib.import_module(addon.__name__ + '.face_catalog')
resources = importlib.import_module(addon.__name__ + '.face_assets')
report = {'scope': 'GI-TOON-PANELS-SDF', 'complete': False,
          'source_sha256': {p.name: file_hash(p) for p in payload.glob('*.py')},
          'asset_sha256': {str(p.relative_to(payload)).replace('\\', '/'): file_hash(p)
                           for p in (payload / 'assets/faces').glob('*.png')},
          'catalog_sha256': file_hash(payload / 'assets/faces.json'),
          'package_sha256': file_hash(args.candidate) if args.candidate else None,
          'models': [], 'checks': {}}


def save():
    assert report['source_sha256'] == {p.name: file_hash(p) for p in payload.glob('*.py')}
    (out / 'panel-update.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')


def render(name):
    bpy.context.view_layer.update()
    bpy.ops.render.render(write_still=False)
    path = out / (name + '.png')
    bpy.data.images['Render Result'].save_render(str(path))
    image = bpy.data.images.load(str(path), check_existing=False)
    pixels = np.array(image.pixels[:], dtype=np.float32).reshape((-1, 4))
    bpy.data.images.remove(image)
    assert np.isfinite(pixels).all()
    return pixels


def controls(settings):
    return {'global': [getattr(settings, key) for key in ('shadow_position', 'shadow_transition', 'face_softness', 'outline', 'outline_lower')],
            'local': [{key: list(getattr(binding, key)) if key in {'tint', 'shadow_color', 'outline_color'}
                       else getattr(binding, key) for key in ('tint', 'shadow_color', 'outline_color', 'brightness', 'saturation', 'opacity', 'defaults')}
                      for binding in settings.bindings]}


def profiles(settings):
    return [(array_hash(entry.render_data.attributes['hgt_outline_height'].data, 'value', 1),
             array_hash(entry.render_data.attributes['hgt_outline_surface'].data, 'value', 1, np.bool_))
            for entry in settings.meshes if entry.render_data and entry.render_data.attributes.get('hgt_outline_height')]


def counts():
    return [len(getattr(bpy.data, kind)) for kind in ('objects', 'meshes', 'materials', 'node_groups', 'images')]


assert len(faces.PRESETS) == 11 and len(report['asset_sha256']) == 13
for key in faces.PRESETS:
    faces.resolve(key)
report['checks']['all_bundled_assets_match_hashes'] = True
save()
for index, model in enumerate(json.loads(args.assets_index.read_text('utf-8'))['models']):
    bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = 256, 384
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    batch = addon.importers.import_character(model['path'], bpy.context)
    source, metadata = source_snapshot(batch), mmd_snapshot(batch)
    root = addon.scene_models.ensure(batch.model_root, bpy.context, model['path'])
    addon.rendering.prepare(scene, root)
    addon.lighting.default_light(scene)
    addon.workflow.apply_materials(root, bpy.context)
    settings = root.hgt_character
    skin = next(binding for binding in settings.bindings if resources.skin_material(binding.source))
    resolved = json.loads(skin.generated['hgt_features'])['face_sdf']['preset']
    rest_profile = profiles(settings)
    untouched = {b.source_name: (b.generated, b.outline) for b in settings.bindings if not resources.skin_material(b.source)}
    baseline = render(f'{index}-auto')
    settings.face_sdf_preset = resolved
    manual = render(f'{index}-bundled-match')
    error = float(np.abs(baseline - manual).max())
    assert error <= 1 / 255 + 1e-6, (model['name'], 'matching bundled image differs', error)
    if index == 0:
        before_counts, before_controls = counts(), controls(settings)
        before_materials = [(b.generated, b.outline) for b in settings.bindings]
        settings.building = True
        settings.face_sdf_preset = 'LEGACY_LADY'
        settings.building = False
        with patch.object(faces, 'resolve', side_effect=resources.AssetError('Expected damaged SDF diagnostic')):
            try:
                addon.workflow.change_face_sdf(root, bpy.context)
            except resources.AssetError:
                pass
            else:
                raise AssertionError('Broken SDF did not report an error')
        assert settings.face_sdf_preset == settings.applied_sdf_preset == resolved
        assert settings.preview_error == 'Expected damaged SDF diagnostic'
        assert counts() == before_counts and controls(settings) == before_controls
        assert [(b.generated, b.outline) for b in settings.bindings] == before_materials
        report['checks']['sdf_failure_atomic_and_visible'] = True
        mesh = bpy.data.meshes.new('User-owned diagnostic mesh')
        adopted = bpy.data.objects.new('User-owned face material reuse', mesh)
        scene.collection.objects.link(adopted)
        adopted_material = skin.generated
        mesh.materials.append(adopted_material)
        settings.face_sdf_preset = 'LEGACY_LADY'
        assert mesh.materials[0] == adopted_material and skin.generated != adopted_material
        assert adopted_material.name in bpy.data.materials
        bpy.data.objects.remove(adopted, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        settings.face_sdf_preset = resolved
        report['checks']['user_reused_face_material_preserved'] = True
    settings.shadow_position, settings.outline_lower = .63, .27
    skin.tint, skin.brightness, skin.saturation = (.85, .9, 1), .9, .7
    expected_controls = controls(settings)
    expected_groups = (settings.global_properties, settings.light_vectors, settings.outline_graph)
    rows = []
    with patch.object(addon.workflow, 'apply_materials', side_effect=AssertionError('Manual apply must not be required')):
        with patch.object(resources.FaceResources, '_packages', side_effect=AssertionError('Bundled mode accessed external FBX')):
            for cycle in range(2):
                for key in ('NONE', *faces.PRESETS):
                    settings.face_sdf_preset = key
                    assert settings.applied_sdf_preset == key, settings.preview_error
                    assert not settings.preview_error
                    assert controls(settings) == expected_controls
                    assert profiles(settings) == rest_profile
                    assert (settings.global_properties, settings.light_vectors, settings.outline_graph) == expected_groups
                    assert all((b.generated, b.outline) == untouched[b.source_name] for b in settings.bindings if b.source_name in untouched)
                    for snap in settings.slots:
                        assert snap.mesh.material_slots[snap.index].material == snap.generated
                    if key == 'NONE':
                        assert skin.generated['hgt_template'] == 'Body'
                    else:
                        assert skin.generated['hgt_template'] == 'Face'
                        for tree in addon.shaders.walk(skin.generated.node_tree):
                            for node in tree.nodes:
                                if node.type == 'TEX_IMAGE' and node.get('hgt_texture_role') in {'face_sdf', 'face_mask'}:
                                    assert node.image.packed_file
                                    assert node.image.colorspace_settings.name == 'Non-Color'
                                    assert node.image.alpha_mode == 'CHANNEL_PACKED'
                    if cycle == 0 and index == 0:
                        render(f'{index}-choice-{key}')
                    rows.append({'cycle': cycle, 'preset': key, 'counts': counts()})
            for first, second in zip(rows[:12], rows[12:]):
                assert first['counts'] == second['counts'], (first, second)
            settings.face_sdf_preset = resolved
            settings.outline = 1
            narrow = render(f'{index}-width-1')
            settings.outline = 3.5
            assert abs(settings.outline - 3.5) < 1e-6
            wide = render(f'{index}-width-3_5')
            response = float(np.abs(narrow - wide).max())
            assert response > .02
            settings.outline = .18
            settings.face_sdf_preset = resolved
    assert source_snapshot(batch) == source and mmd_snapshot(batch) == metadata
    before = render(f'{index}-save')
    bpy.ops.wm.save_as_mainfile(filepath=str(out / f'{index}-bundled.blend'), relative_remap=False)
    bpy.ops.wm.open_mainfile(filepath=str(out / f'{index}-bundled.blend'), load_ui=False)
    after = render(f'{index}-reopen')
    assert np.array_equal(before, after), float(np.abs(before - after).max())
    root = bpy.context.scene.hgt_target
    assert root.hgt_character.face_sdf_preset == resolved
    report['models'].append({'name': model['name'], 'matching_preset': resolved,
                             'auto_manual_max_error': error, 'outline_above_one_response': response,
                             'source_and_mmd_preserved': True, 'only_face_rebuilt': True,
                             'controls_and_profiles_preserved': True, 'all_choices_without_external_fbx': True,
                             'repeat_no_resource_growth': True, 'save_reopen_exact': True, 'choices': rows})
    save()
    print('HGT_PANEL_MODEL_PASSED', model['name'], flush=True)
report['complete'] = True
save()
print('HGT_PANEL_UPDATE_PASSED', flush=True)
