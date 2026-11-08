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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--base-version', required=True)
    parser.add_argument('--scope', choices=('jelly', 'glow', 'glow-camera'), required=True)
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
    else:
        validate_camera_evidence(evidence, interface, interactions, runtime_hashes(), archive_sha)
    base = read(ROOT / 'release' / ('build-v' + args.base_version + '.json'))
    previous = ROOT / 'release' / base['archive']
    assert sha(previous.read_bytes()) == base['sha256'], 'Baseline archive changed'
    with zipfile.ZipFile(previous) as old, zipfile.ZipFile(candidate) as new:
        old_files, new_files = set(old.namelist()), set(new.namelist())
        assert not old_files - new_files, 'Incremental release cannot remove payload files'
        changed = sorted(n for n in new_files if n not in old_files or new.read(n) != old.read(n))
        if args.scope == 'jelly':
            allowed = {'__init__.py', 'properties.py', 'panels.py', 'jelly_eye.py', 'jelly_geometry.py',
                       'blender_manifest.toml', 'README.md', 'CHANGELOG.md', 'NOTICE',
                       'docs/upstream-baseline.md', 'docs/workflow.md'}
            assert new_files - old_files == {'jelly_eye.py', 'jelly_geometry.py'}
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
               'baseline_policy': 'Unchanged files verified byte exact; previous results are not new runs',
               'source_sha256': runtime_hashes(), 'full_regression_required': False}
    if args.scope == 'jelly':
        summary.update(jelly=evidence, jelly_interface=interface, jelly_interactions=interactions)
    elif args.scope == 'glow':
        summary.update(glow_functional={k:evidence[k] for k in (
            'functional_complete', 'performance_verified', 'native_checks', 'native_mode_checks',
            'viewport_checks', 'moving_timeline_uploads', 'native_render_core_ast_unchanged')},
            glow_interface=interface, glow_incremental_audit=interactions)
    else:
        summary.update(camera_source_checks={'camera_cases':len(evidence['camera_cases']),
            'ordinary_view_cases':len(evidence['ordinary_view_cases']), 'viewport_checks':evidence['viewport_checks'],
            'moving_timeline_uploads':evidence['moving_timeline_uploads'],
            'final_render_core_ast_unchanged':evidence['final_render_core_ast_unchanged']},
            camera_package=interface, camera_incremental_audit=interactions)
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
