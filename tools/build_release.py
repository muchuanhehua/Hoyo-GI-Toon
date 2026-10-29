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
         "mmd_importer.py","pmx_materials.py",
         "material_protocol.py","node_graph.py","normal_maps.py","eye_surfaces.py","textiles.py","reflections.py",
         "panels.py","post_processing.py","properties.py","rendering.py","shaders.py","subjects.py","surface_layers.py","upstream_mapping.py","workflow.py",
         "assets/original_shader.blend","assets/original_controls.blend","assets/upstream.json",
         "blender_manifest.toml","README.md","CHANGELOG.md","LICENSE","NOTICE","docs/upstream-baseline.md","docs/basic-rendering.md","docs/pmx-rendering.md","docs/subjects.md"}


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
        if evidence.get('scope') not in {'01–08','01–15','01–21'} or not all(evidence.get('integration_checks',{}).get(key) is True for key in required):
            raise ValueError('08 integration evidence is required')
    return hashes


def validate_pmx(evidence, hashes, integration=False):
    expected={name:value for name,value in hashes.items() if name.endswith('.py')}
    if evidence.get('scope')!='09–15' or evidence.get('source_sha256')!=expected:
        raise ValueError('PMX verification does not match the runtime payload')
    flags=('source_data_unchanged','mmd_metadata_unchanged','repair_rest_geometry_unchanged',
           'derived_geometry_unchanged','original_mesh_refs_restored','head_follow','repeat_assembly',
           'restore_reassembly','transparent_alpha','post_alpha')
    if len(evidence.get('models',[]))<3 or not all(all(m.get(k) is True for k in flags) for m in evidence['models']):
        raise ValueError('Three-model PMX verification is incomplete')
    checks=('save_reload','assembly_failure_rollback','two_imports_isolated',
            'import_repair_failure_rollback','empty_scene_failure_rollback','missing_mmd_dependency','register_unregister')
    if not all(evidence.get('checks',{}).get(k) is True for k in checks):
        raise ValueError('PMX lifecycle verification is incomplete')
    if integration and not evidence.get('package_sha256'):
        raise ValueError('Installed PMX package verification is required')


def validate_subjects(evidence,hashes,integration=False):
    expected={name:value for name,value in hashes.items() if name.endswith('.py')}
    if evidence.get('scope')!='16–21' or evidence.get('source_sha256')!=expected:
        raise ValueError('Subject verification does not match the runtime payload')
    models=evidence.get('models',[])
    flags=('source_data_unchanged','mmd_metadata_preserved','derived_geometry_unchanged',
           'references_restored','visibility_restored','save_reload','repeat_no_leak','toggle_pixels_restored')
    if len(models)<5 or not all(all(m.get(k) is True for k in flags) for m in models):
        raise ValueError('Subject data/display verification is incomplete')
    if {m['source_format'] for m in models if m.get('mixed')}!={'fbx','pmx'}:
        raise ValueError('Both mixed-mesh formats must be verified')
    required=('unknown_kept_and_corrected','head_decoration_preserved','assembly_failure_rollback',
              'mixed_imports_isolated','register_unregister')
    if not all(evidence.get('checks',{}).get(k) is True for k in required):
        raise ValueError('Subject lifecycle verification is incomplete')
    if integration and not evidence.get('package_sha256'):
        raise ValueError('Installed subject package verification is required')


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
    parser.add_argument('--pmx-verification',type=Path)
    parser.add_argument('--subjects-verification',type=Path)
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
    if tuple(map(int,manifest['version'].split('.'))) >= (0,5,0):
        if not args.pmx_verification:raise ValueError('PMX verification is required for this version')
        pmx=json.loads(args.pmx_verification.read_text(encoding='utf-8'))
        validate_pmx(pmx,hashes,integration=args.action=='release')
        if args.action=='release' and pmx.get('package_sha256')!=evidence.get('package_sha256'):
            raise ValueError('FBX and PMX verification must use the same candidate')
    if tuple(map(int,manifest['version'].split('.'))) >= (0,6,0):
        if not args.subjects_verification:raise ValueError('Subject verification is required for this version')
        subjects=json.loads(args.subjects_verification.read_text(encoding='utf-8'))
        validate_subjects(subjects,hashes,integration=args.action=='release')
        if args.action=='release' and subjects.get('package_sha256')!=evidence.get('package_sha256'):
            raise ValueError('Subject verification must use the same candidate')
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
    summary={'scope':evidence.get('scope','01–08'),'version':manifest['version'],'archive_sha256':record['sha256'],
             'integration_checks':evidence['integration_checks'],'core_sha256':hashes,
             'models':[{key:model[key] for key in ('name','objects','meshes','materials','source_data_unchanged')}
                       for model in evidence['models']]}
    if args.pmx_verification:
        summary['pmx']={'checks':pmx['checks'],'models':[{key:model[key] for key in
            ('name','materials','source_data_unchanged','mmd_metadata_unchanged','original_mesh_refs_restored')}
            for model in pmx['models']]}
        summary['formats']=evidence.get('formats',{})
    if args.subjects_verification:
        summary['subjects']={'checks':subjects['checks'],'models':subjects['models']}
    (release/f"verification-v{manifest['version']}.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('HGT_RELEASE_RECORD',name,record['sha256'],flush=True)


if __name__=='__main__': main()
