"""Promote an unchanged verified ZIP using explicit, bounded change evidence."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import tomllib
import zipfile
from build_release import ROOT, runtime_hashes, validate_archive, validate_jelly_evidence


def read(path):
    return json.loads(Path(path).read_text('utf-8'))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def validate_glow_evidence(evidence, interface, audit, hashes, archive_sha):
    assert evidence['functional_complete'] and not evidence['performance_verified']
    assert evidence['native_checks'] == 22 and evidence['native_mode_checks'] == 6
    assert evidence['viewport_checks'] == 20 and evidence['moving_timeline_uploads'] >= 2
    for name, expected in evidence['current_source_sha256'].items():
        if name != '__init__.py':assert hashes[name] == expected, name
    assert interface['scope'] == 'GI-TOON-GLOW-UI' and interface['complete'] and not interface.get('error')
    assert interface['source_sha256'] == hashes and interface['package_sha256'] == archive_sha
    assert len(interface['checks']) == 20 and all(interface['checks'].values())
    assert interface['timeline_uploads'] >= 2
    assert audit['scope'] == 'INCREMENTAL-GLOW-RELEASE' and audit['complete']
    assert audit['source_sha256'] == hashes and audit['archive_sha256'] == archive_sha
    assert audit['native_render_core_ast_unchanged'] and audit['baseline_handlers_ast_unchanged']
    assert audit['published_on_user_request_without_idle_gpu_benchmark']


def validate_camera_evidence(evidence, camera, audit, hashes, archive_sha):
    assert evidence['scope'] == 'GLOW-CAMERA-FRAME-FIX' and evidence['complete']
    for name, expected in evidence['source_sha256'].items():
        if name != '__init__.py':assert hashes[name] == expected, name
    assert len(evidence['camera_cases']) == 9 and len(evidence['ordinary_view_cases']) == 2
    assert len(evidence['viewport_checks']) == 20 and all(evidence['viewport_checks'].values())
    assert evidence['moving_timeline_uploads'] >= 2 and evidence['final_render_core_ast_unchanged']
    assert camera['scope'] == 'GLOW-CAMERA-ALIGNMENT' and camera['complete'] and not camera.get('error')
    assert camera['source_sha256'] == hashes and camera['package_sha256'] == archive_sha
    assert len(camera['cases']) == 11 and all(max(map(abs, case['offset_px'])) < 3 for case in camera['cases'])
    assert audit['scope'] == 'INCREMENTAL-GLOW-CAMERA-RELEASE' and audit['complete']
    assert audit['source_sha256'] == hashes and audit['archive_sha256'] == archive_sha
    assert audit['native_render_core_ast_unchanged'] and audit['version_metadata_only']
    assert audit['legacy_scale_upgrade_and_shared_compositor_verified']


def validate_animation_evidence(evidence, compatibility, audit, hashes, archive_sha):
    assert evidence['scope'] == 'ANIMATION-PREVIEW-PERFORMANCE' and evidence['complete']
    assert evidence['source_sha256'] == hashes and evidence['package_sha256'] == archive_sha
    samples = evidence['paired_measurements']
    assert [row['mode'] for row in samples] == ['baseline_on', 'fixed_on', 'baseline_repeat']
    assert all(row['draws'] > 0 and row['uploads'] > 0 and not row['error'] for row in samples)
    assert samples[1]['interval_median_ms'] < min(samples[0]['interval_median_ms'], samples[2]['interval_median_ms'])
    assert len({tuple(sorted(row['resources'].items())) for row in samples}) == 1
    assert compatibility['scope'] == 'ANIMATION-PREVIEW-COMPATIBILITY' and compatibility['complete']
    assert compatibility['source_sha256'] == hashes and compatibility['package_sha256'] == archive_sha
    assert len(compatibility['checks']) == 17 and all(compatibility['checks'].values())
    assert len(compatibility['renders']) == 3 and all(row['max_abs_error'] == 0 for row in compatibility['renders'])
    assert audit['scope'] == 'INCREMENTAL-ANIMATION-PREVIEW-RELEASE' and audit['complete']
    assert audit['source_sha256'] == hashes and audit['archive_sha256'] == archive_sha
    assert audit['glow_render_and_capture_byte_exact'] and audit['shader_and_animation_compatibility_verified']


def validate_fullframe_evidence(evidence, interface, audit, hashes, archive_sha):
    assert evidence['scope'] == 'FULLFRAME-GLOW-COMPATIBILITY' and evidence['complete']
    assert evidence['source_sha256'] == hashes and evidence['package_sha256'] == archive_sha
    assert len(evidence['checks']) == 40 and all(evidence['checks'].values())
    assert all(evidence['checks'].get(k) is True for k in (
        'viewer_preview_and_restore_record','user_file_output_still_executes',
        'manual_viewer_rewire_preserved','legacy_user_dependencies_protected',
        'no_glow_depsgraph_or_frame_handlers'))
    assert len(evidence['modes']) == 7 and all(m['zero_exact'] and m['native_rgb_max_error'] <= 1/255+1e-6 for m in evidence['modes'])
    assert evidence['transparent_halo_pixels'] > 20
    assert interface['scope'] == 'FULLFRAME-GLOW-VIEWPORT' and interface['complete'] and not interface.get('error')
    assert interface['source_sha256'] == hashes and interface['package_sha256'] == archive_sha
    assert all(interface['checks'].values()) and len(interface['camera_cases']) == 3
    assert interface['checks'].get('natural_viewport_parameter_response') is True and interface['viewport_parameter_response'] > .002
    assert audit['scope'] == 'INCREMENTAL-FULLFRAME-GLOW-RELEASE' and audit['complete']
    assert audit['source_sha256'] == hashes and audit['archive_sha256'] == archive_sha
    assert audit['material_animation_and_assets_byte_exact'] and audit['capture_module_removed']
    rows = audit['performance']
    assert [r['mode'] for r in rows] == ['legacy_2.9.3', 'fullframe', 'off', 'fullframe_repeat']
    assert all(not r['error'] for r in rows)
    assert rows[0]['resources']['layers'] == 2 and rows[0]['draws'] > 0
    assert all(r['resources']['layers'] == 1 and r['draws'] == r['uploads'] == 0 for r in rows[1:])
    assert all(r['resources']['objects'] == rows[0]['resources']['objects'] for r in rows)
    assert max(rows[1]['interval_median_ms'], rows[3]['interval_median_ms']) < rows[0]['interval_median_ms']*.75
    assert max(rows[1]['interval_median_ms'], rows[3]['interval_median_ms']) <= rows[2]['interval_p95_ms']+20


def validate_stage_animation_evidence(evidence, playback, audit, hashes, archive_sha):
    assert evidence['scope'] == 'STAGE-ANIMATION-COMPATIBILITY' and evidence['complete']
    assert evidence['source_sha256'] == hashes and evidence['package_sha256'] == archive_sha
    assert len(evidence['checks']) == 29 and all(evidence['checks'].values())
    assert len(evidence['renders']) == 3 and all(row['max_error'] == 0 for row in evidence['renders'])
    assert playback['scope'] == 'STAGE-ANIMATION-PLAYBACK' and playback['complete'] and not playback.get('error')
    assert playback['source_sha256'] == hashes and playback['package_sha256'] == archive_sha
    assert len(playback['checks']) == 3 and all(playback['checks'].values())
    rows = playback['cases']
    assert [r['mode'] for r in rows] == ['baseline_2100', 'candidate_2110', 'baseline_repeat', 'candidate_repeat', 'candidate_panorama']
    assert all(r['frames'] == 36 and r['frame_range'] == [193, 228] for r in rows)
    assert min(rows[i]['fps'] for i in (1, 3)) > max(rows[i]['fps'] for i in (0, 2))
    assert rows[4]['cameras'] == 1 and rows[4]['stage_layout'] == 'panorama-360-v1'
    assert audit['scope'] == 'INCREMENTAL-STAGE-ANIMATION-RELEASE' and audit['complete']
    assert audit['source_sha256'] == hashes and audit['archive_sha256'] == archive_sha
    assert audit['outline_shader_assets_and_physics_byte_exact']
    assert audit['six_stage_views_reviewed'] and audit['camera_trajectory']['camera_max_error'] == 0
    assert audit['camera_trajectory']['checks']['all_1053_camera_frames_identical']
    assert all(audit['camera_trajectory']['checks'].values())
    ownership = audit['camera_ownership']
    assert ownership['complete'] and ownership['package_sha256'] == archive_sha
    assert len(ownership['checks']) == 7 and all(ownership['checks'].values())


def validate_outline_preview_evidence(evidence, playback, audit, hashes, archive_sha):
    assert evidence['scope'] == 'OUTLINE-PREVIEW-COMPATIBILITY' and evidence['complete']
    assert evidence['source_sha256'] == hashes and evidence['package_sha256'] == archive_sha
    assert len(evidence['checks']) == 22 and all(evidence['checks'].values())
    assert len(evidence['renders']) == 3 and all(row['final_max_error'] == 0 for row in evidence['renders'])
    assert all(row['preview_max_error'] <= 2/255+1e-6 and row['preview_mean_error'] <= 1e-5 for row in evidence['renders'])
    assert playback['scope'] == 'OUTLINE-PREVIEW-PLAYBACK' and playback['complete'] and not playback.get('error')
    assert playback['source_sha256'] == hashes and playback['package_sha256'] == archive_sha
    assert len(playback['checks']) == 6 and all(playback['checks'].values())
    rows = playback['cases']
    assert [r['mode'] for r in rows] == ['baseline_2110', 'candidate', 'baseline_repeat', 'candidate_repeat']
    assert all(r['frames'] == 36 and r['frame_range'] == [193, 228] for r in rows)
    assert min(rows[i]['fps'] for i in (1, 3)) > max(rows[i]['fps'] for i in (0, 2))
    assert len(playback['viewport_comparisons']) == 3
    assert all(r['mean_error'] <= max(.001, r['baseline_repeat_mean_error']*2) for r in playback['viewport_comparisons'])
    assert audit['scope'] == 'INCREMENTAL-OUTLINE-PREVIEW-RELEASE' and audit['complete']
    assert audit['source_sha256'] == hashes and audit['archive_sha256'] == archive_sha
    assert audit['source_outline_algorithms_ast_unchanged'] and audit['shader_assets_animation_and_physics_byte_exact']
    assert audit['cross_character_images_reviewed'] and audit['native_playback_images_reviewed']
    cross = audit['cross_character']
    assert cross['scope'] == 'CROSS-CHARACTER-OUTLINE-PREVIEW' and cross['complete']
    assert cross['source_sha256'] == hashes and cross['package_sha256'] == archive_sha
    assert len(cross['models']) == 13
    for model in cross['models']:
        assert model['source_data_preserved'] and model['migration_parameters_preserved'] and model['save_reopen_exact']
        assert model['final_max_error'] <= 1/255+1e-6
        assert set(model['views']) == {'front', 'back', 'left', 'right'}
        for view in model['views'].values():
            assert set(view) == {'off', 'default', 'wide'}
            for row in view.values():
                assert row['mean_error'] <= 1e-5 and row['alpha_max_error'] <= 1/255+1e-6
                if row['max_error'] > 2/255+1e-6:
                    assert row['opaque_max_error'] <= 2/255+1e-6 and row['mean_error'] <= 1e-6
                    assert row['pixels_over_one_byte'] <= 32


def validate_scene_lookup_evidence(evidence, playback, audit, hashes, archive_sha):
    assert evidence['scope'] == 'SCENE-LOOKUP-COMPATIBILITY' and evidence['complete']
    assert evidence['source_sha256'] == hashes and evidence['package_sha256'] == archive_sha
    assert len(evidence['checks']) == 27 and all(evidence['checks'].values())
    assert len(evidence['renders']) == 3 and all(r['max_error'] == 0 for r in evidence['renders'])
    assert playback['scope'] == 'SCENE-LOOKUP-PLAYBACK' and playback['complete'] and not playback.get('error')
    assert playback['source_sha256'] == hashes and playback['package_sha256'] == archive_sha
    assert len(playback['checks']) == 5 and all(playback['checks'].values())
    rows = playback['cases']
    assert [r['case'] for r in rows] == ['baseline', 'candidate', 'baseline_repeat', 'candidate_repeat']
    assert all(r['frames'] == 96 and r['frame_range'] == [193, 288] for r in rows)
    assert sum(rows[i]['evaluation_ms'] for i in (1, 3)) < sum(rows[i]['evaluation_ms'] for i in (0, 2))
    assert audit['scope'] == 'INCREMENTAL-SCENE-LOOKUP-RELEASE' and audit['complete']
    assert audit['source_sha256'] == hashes and audit['archive_sha256'] == archive_sha
    assert audit['only_membership_queries_changed'] and audit['shader_outline_assets_byte_exact']
    assert audit['visual_review_complete']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--base-version', required=True)
    parser.add_argument('--scope', choices=('jelly', 'glow', 'glow-camera', 'animation-preview', 'fullframe-glow', 'stage-animation', 'outline-preview', 'scene-lookup'), required=True)
    parser.add_argument('--verification', type=Path, required=True)
    parser.add_argument('--interface-verification', type=Path, required=True)
    parser.add_argument('--interactions-verification', type=Path, required=True)
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    payload = validate_archive(candidate)
    archive_sha = sha(candidate.read_bytes())
    evidence, interface, interactions = [read(p) for p in (
        args.verification, args.interface_verification, args.interactions_verification)]
    if args.scope == 'jelly':
        validate_jelly_evidence(evidence, interface, interactions, runtime_hashes(), archive_sha)
    elif args.scope == 'glow':
        validate_glow_evidence(evidence, interface, interactions, runtime_hashes(), archive_sha)
    elif args.scope == 'glow-camera':
        validate_camera_evidence(evidence, interface, interactions, runtime_hashes(), archive_sha)
    elif args.scope == 'animation-preview':
        validate_animation_evidence(evidence, interface, interactions, runtime_hashes(), archive_sha)
    elif args.scope == 'stage-animation':
        validate_stage_animation_evidence(evidence, interface, interactions, runtime_hashes(), archive_sha)
    elif args.scope == 'outline-preview':
        validate_outline_preview_evidence(evidence, interface, interactions, runtime_hashes(), archive_sha)
    elif args.scope == 'scene-lookup':
        validate_scene_lookup_evidence(evidence, interface, interactions, runtime_hashes(), archive_sha)
    else:
        validate_fullframe_evidence(evidence, interface, interactions, runtime_hashes(), archive_sha)
    base = read(ROOT / 'release' / ('build-v' + args.base_version + '.json'))
    previous = ROOT / 'release' / base['archive']
    assert sha(previous.read_bytes()) == base['sha256'], 'Baseline archive changed'
    with zipfile.ZipFile(previous) as old, zipfile.ZipFile(candidate) as new:
        old_files, new_files = set(old.namelist()), set(new.namelist())
        removed = sorted(old_files - new_files)
        assert set(removed) == ({'glow_preview.py'} if args.scope == 'fullframe-glow' else set()), 'Unexpected payload removal'
        changed = sorted(n for n in new_files if n not in old_files or new.read(n) != old.read(n))
        if args.scope == 'jelly':
            allowed = {'__init__.py', 'properties.py', 'panels.py', 'jelly_eye.py', 'jelly_geometry.py',
                       'blender_manifest.toml', 'README.md', 'CHANGELOG.md', 'NOTICE',
                       'docs/upstream-baseline.md', 'docs/workflow.md'}
            assert new_files - old_files == {'jelly_eye.py', 'jelly_geometry.py'}
        elif args.scope == 'animation-preview':
            allowed = {'__init__.py', 'blender_manifest.toml', 'CHANGELOG.md', 'workflow.py', 'shaders.py'}
            assert new_files == old_files
        elif args.scope == 'fullframe-glow':
            allowed = {'__init__.py','blender_manifest.toml','CHANGELOG.md','README.md','docs/workflow.md',
                       'glow.py','glow_source.py','properties.py','panels.py'}
            assert not new_files - old_files
        elif args.scope == 'outline-preview':
            allowed = {'__init__.py', 'blender_manifest.toml', 'CHANGELOG.md', 'README.md', 'outlines.py', 'workflow.py'}
            assert new_files == old_files
        elif args.scope == 'scene-lookup':
            allowed = {'__init__.py', 'blender_manifest.toml', 'CHANGELOG.md', 'README.md',
                       'workflow.py', 'lighting.py', 'animation_uniforms.py', 'scene_models.py'}
            assert new_files == old_files
        elif args.scope == 'stage-animation':
            allowed = {'__init__.py', 'blender_manifest.toml', 'CHANGELOG.md', 'README.md', 'docs/scene-presets.md',
                       'assets/scene_city_terrace.blend', 'assets/scene_stage.blend', 'assets/scenes.json',
                       'animation_uniforms.py', 'scene_camera.py', 'lighting.py', 'project_io.py', 'properties.py',
                       'rendering.py', 'scene_models.py', 'scene_presets.py', 'shaders.py', 'workflow.py'}
            assert new_files - old_files == {'animation_uniforms.py', 'scene_camera.py'}
        else:
            allowed = {'__init__.py', 'blender_manifest.toml', 'CHANGELOG.md', 'glow.py', 'glow_preview.py'}
            assert new_files == old_files
        assert set(changed) <= allowed, ('Change exceeds evidence scope', changed)
        manifest = tomllib.loads(new.read('blender_manifest.toml').decode('utf-8'))
        old_manifest = tomllib.loads(old.read('blender_manifest.toml').decode('utf-8'))
        assert {k:v for k,v in manifest.items() if k != 'version'} == {k:v for k,v in old_manifest.items() if k != 'version'}
        # Version metadata may change; registration and existing lifecycle stay identical.
        trees = [ast.parse(z.read('__init__.py').decode('utf-8')) for z in (old, new)]
        infos = []
        for tree in trees:
            info = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'bl_info' for t in n.targets))
            infos.append(ast.literal_eval(info.value))
            tree.body.remove(info)
        assert ast.dump(trees[0]) == ast.dump(trees[1])
        assert {k:v for k,v in infos[0].items() if k != 'version'} == {k:v for k,v in infos[1].items() if k != 'version'}
        assert '.'.join(map(str, infos[1]['version'])) == manifest['version']
    version = manifest['version']
    assert version != args.base_version
    release = ROOT / 'release'
    target = release / candidate.name
    assert not target.exists(), 'Never replace an existing release archive'
    record = {'version': version, 'kind': 'incremental', 'scope': args.scope, 'archive': candidate.name,
              'bytes': candidate.stat().st_size, 'sha256': archive_sha, 'payload': payload}
    summary = {'version': version, 'scope': 'incremental-' + args.scope + '-release', 'archive_sha256': archive_sha,
               'baseline_version': args.base_version, 'baseline_archive_sha256': base['sha256'],
               'changed_payload': changed, 'unchanged_payload': sorted(new_files - set(changed)),
               'removed_payload': removed,
               'baseline_policy': 'Unchanged files verified byte exact; previous results are not new runs',
               'source_sha256': runtime_hashes(), 'full_regression_required': False}
    if args.scope == 'jelly':
        summary.update(jelly=evidence, jelly_interface=interface, jelly_interactions=interactions)
    elif args.scope == 'glow':
        summary.update(glow_functional={k:evidence[k] for k in (
            'functional_complete', 'performance_verified', 'native_checks', 'native_mode_checks',
            'viewport_checks', 'moving_timeline_uploads', 'native_render_core_ast_unchanged')},
            glow_interface=interface, glow_incremental_audit=interactions)
    elif args.scope == 'glow-camera':
        summary.update(camera_source_checks={'camera_cases':len(evidence['camera_cases']),
            'ordinary_view_cases':len(evidence['ordinary_view_cases']), 'viewport_checks':evidence['viewport_checks'],
            'moving_timeline_uploads':evidence['moving_timeline_uploads'],
            'final_render_core_ast_unchanged':evidence['final_render_core_ast_unchanged']},
            camera_package=interface, camera_incremental_audit=interactions)
    elif args.scope == 'animation-preview':
        summary.update(animation_performance=evidence,
                       animation_package_checks={'count':len(interface['checks']), 'all_passed':True,
                           'renders':interface['renders'], 'package_sha256':interface['package_sha256']},
                       animation_incremental_audit=interactions)
    elif args.scope == 'stage-animation':
        summary.update(stage_animation=evidence, native_playback=interface, stage_animation_audit=interactions)
    elif args.scope == 'outline-preview':
        summary.update(outline_preview=evidence, native_playback=interface, outline_preview_audit=interactions)
    elif args.scope == 'scene-lookup':
        summary.update(scene_lookup=evidence, native_playback=interface, scene_lookup_audit=interactions)
    else:
        summary.update(fullframe_glow={'checks':evidence['checks'],'modes':evidence['modes'],
                           'transparent_halo_pixels':evidence['transparent_halo_pixels']},
                       viewport=interface,fullframe_incremental_audit=interactions)
    shutil.copy2(candidate, target)
    (release / ('build-v' + version + '.json')).write_text(json.dumps(record, indent=2) + '\n', 'utf-8', newline='\n')
    (release / ('verification-v' + version + '.json')).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', 'utf-8', newline='\n')
    item = {k:v for k,v in manifest.items() if k != 'build'}
    item.update(archive_url=f'https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/v{version}/release/{target.name}',
                archive_size=record['bytes'], archive_hash='sha256:' + archive_sha)
    (release / 'index.json').write_text(json.dumps({'version':'v1', 'blocklist':[], 'data':[item]}, ensure_ascii=False, indent=2) + '\n', 'utf-8', newline='\n')
    print('HGT_INCREMENTAL_RELEASE', version, len(changed), 'changed;', len(new_files - set(changed)), 'unchanged;', archive_sha)


if __name__ == '__main__':
    main()
