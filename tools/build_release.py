"""Build an immutable candidate, then promote its verified bytes after acceptance."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tomllib
import zipfile

ROOT=Path(__file__).resolve().parents[1]
PAYLOAD={"__init__.py","asset_resolver.py","asset_tracking.py","eye_layers.py","importers.py","lighting.py","outlines.py",
         "panels.py","post_processing.py","properties.py","rendering.py","shaders.py","surface_layers.py","upstream_mapping.py","workflow.py",
         "assets/original_shader.blend","assets/original_controls.blend","assets/upstream.json",
         "blender_manifest.toml","README.md","CHANGELOG.md","LICENSE","NOTICE","docs/upstream-baseline.md","docs/basic-rendering.md"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def validate_evidence(evidence,integration=False):
    hashes={**evidence['source_sha256'],**evidence['resource_sha256']}
    expected={name for name in PAYLOAD if name.endswith('.py') or name.startswith('assets/')}
    if set(hashes)!=expected: raise ValueError('Verification does not cover the exact runtime payload')
    for name,value in hashes.items():
        if sha((ROOT/name).read_bytes())!=value: raise ValueError('Source changed after verification: '+name)
    flags=('source_data_unchanged','derived_geometry_unchanged','original_mesh_refs_restored',
           'head_follow','repeat_assembly','restore_reassembly','shared_data_preserved')
    if len(evidence['models'])<4 or not all(all(model.get(key) is True for key in flags) for model in evidence['models']):
        raise ValueError('Four-model data protection verification is incomplete')
    if sum(len(model.get('renders',[])) for model in evidence['models'])<4 or not all(evidence['lifecycle'].values()):
        raise ValueError('Render and lifecycle verification is incomplete')
    if integration:
        required={'fresh_package_process','register_unregister','save_reload','undo_redo','ui_render_save',
                  'camera_framing','scene_preserved','transparent_alpha','post_alpha','errors_and_cleanup','ui_errors'}
        if evidence.get('scope')!='01–08' or not all(evidence.get('integration_checks',{}).get(key) is True for key in required):
            raise ValueError('08 integration evidence is required')
    return hashes


def validate_archive(path):
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None or set(archive.namelist())!=PAYLOAD:
            raise ValueError('Unexpected archive payload or failed CRC')
        for name in PAYLOAD:
            if archive.read(name)!=(ROOT/name).read_bytes(): raise ValueError('Packaged bytes differ: '+name)
    return {name:sha((ROOT/name).read_bytes()) for name in sorted(PAYLOAD)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('candidate','release'))
    parser.add_argument('--blender',type=Path,required=True)
    parser.add_argument('--verification',type=Path,required=True)
    args=parser.parse_args()
    manifest=tomllib.loads((ROOT/'blender_manifest.toml').read_text(encoding='utf-8'))
    for name in PAYLOAD:
        if name.endswith('.py'): ast.parse((ROOT/name).read_text(encoding='utf-8'),name)
    tree=ast.parse((ROOT/'__init__.py').read_text(encoding='utf-8'))
    info=ast.literal_eval(next(node.value for node in tree.body if isinstance(node,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='bl_info' for t in node.targets)))
    if '.'.join(map(str,info['version']))!=manifest['version']: raise ValueError('Version metadata mismatch')
    evidence=json.loads(args.verification.read_text(encoding='utf-8'))
    hashes=validate_evidence(evidence,integration=args.action=='release')
    candidate_dir=ROOT/'.build/candidate'
    candidate_dir.mkdir(parents=True,exist_ok=True)
    name=f"{manifest['id']}-{manifest['version']}.zip"
    candidate=candidate_dir/name
    command=[str(args.blender),'--background','--factory-startup','--command','extension']
    if args.action=='candidate':
        if candidate.exists(): raise ValueError('Candidate already exists; preserve or remove it before rebuilding')
        subprocess.run([*command,'build','--source-dir',str(ROOT),'--output-filepath',str(candidate)],check=True)
        subprocess.run([*command,'validate',str(candidate)],check=True)
        payload=validate_archive(candidate)
        record={'version':manifest['version'],'archive':name,'bytes':candidate.stat().st_size,
                'sha256':sha(candidate.read_bytes()),'payload':payload,'core_sha256':hashes}
        (candidate_dir/'candidate.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
        print('HGT_CANDIDATE',name,record['sha256'],len(payload),flush=True)
        return
    record=json.loads((candidate_dir/'candidate.json').read_text(encoding='utf-8'))
    if sha(candidate.read_bytes())!=record['sha256'] or evidence.get('package_sha256')!=record['sha256']:
        raise ValueError('Installed-package verification does not match this candidate')
    validate_archive(candidate)
    release=ROOT/'release'
    target=release/name
    if target.exists(): raise ValueError('Do not overwrite an existing release archive: '+name)
    shutil.copy2(candidate,target)
    (release/f"build-v{manifest['version']}.json").write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    item={key:value for key,value in manifest.items() if key!='build'}
    item.update(archive_url=f"https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/v{manifest['version']}/release/{name}",
                archive_size=record['bytes'],archive_hash='sha256:'+record['sha256'])
    (release/'index.json').write_text(json.dumps({'version':'v1','blocklist':[],'data':[item]},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary={'scope':'01–08','version':manifest['version'],'archive_sha256':record['sha256'],
             'integration_checks':evidence['integration_checks'],'core_sha256':hashes,
             'models':[{key:model[key] for key in ('name','objects','meshes','materials','source_data_unchanged')}
                       for model in evidence['models']]}
    (release/f"verification-v{manifest['version']}.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('HGT_RELEASE_RECORD',name,record['sha256'],flush=True)


if __name__=='__main__': main()
