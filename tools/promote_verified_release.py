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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--base-version', required=True)
    parser.add_argument('--scope', choices=('jelly',), required=True)
    parser.add_argument('--verification', type=Path, required=True)
    parser.add_argument('--interface-verification', type=Path, required=True)
    parser.add_argument('--interactions-verification', type=Path, required=True)
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    payload = validate_archive(candidate)
    archive_sha = sha(candidate.read_bytes())
    evidence, interface, interactions = [read(p) for p in (
        args.verification, args.interface_verification, args.interactions_verification)]
    validate_jelly_evidence(evidence, interface, interactions, runtime_hashes(), archive_sha)
    base = read(ROOT / 'release' / ('build-v' + args.base_version + '.json'))
    previous = ROOT / 'release' / base['archive']
    assert sha(previous.read_bytes()) == base['sha256'], 'Baseline archive changed'
    with zipfile.ZipFile(previous) as old, zipfile.ZipFile(candidate) as new:
        old_files, new_files = set(old.namelist()), set(new.namelist())
        assert not old_files - new_files, 'Incremental jelly release cannot remove payload files'
        changed = sorted(n for n in new_files if n not in old_files or new.read(n) != old.read(n))
        allowed = {'__init__.py', 'properties.py', 'panels.py', 'jelly_eye.py', 'jelly_geometry.py',
                   'blender_manifest.toml', 'README.md', 'CHANGELOG.md', 'NOTICE',
                   'docs/upstream-baseline.md', 'docs/workflow.md'}
        assert set(changed) <= allowed, ('Change exceeds jelly evidence scope', changed)
        assert new_files - old_files == {'jelly_eye.py', 'jelly_geometry.py'}
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
    summary = {'version': version, 'scope': 'incremental-jelly-release', 'archive_sha256': archive_sha,
               'baseline_version': args.base_version, 'baseline_archive_sha256': base['sha256'],
               'changed_payload': changed, 'unchanged_payload': sorted(new_files - set(changed)),
               'baseline_policy': 'Unchanged files verified byte exact; previous results are not new runs',
               'source_sha256': runtime_hashes(), 'jelly': evidence, 'jelly_interface': interface,
               'jelly_interactions': interactions, 'full_regression_required': False}
    shutil.copy2(candidate, target)
    (release / ('build-v' + version + '.json')).write_text(json.dumps(record, indent=2) + '\n', 'utf-8')
    (release / ('verification-v' + version + '.json')).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    item = {k:v for k,v in manifest.items() if k != 'build'}
    item.update(archive_url=f'https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/v{version}/release/{target.name}',
                archive_size=record['bytes'], archive_hash='sha256:' + archive_sha)
    (release / 'index.json').write_text(json.dumps({'version':'v1', 'blocklist':[], 'data':[item]}, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print('HGT_INCREMENTAL_RELEASE', version, len(changed), 'changed;', len(new_files - set(changed)), 'unchanged;', archive_sha)


if __name__ == '__main__':
    main()
