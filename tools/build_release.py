"""Freeze and promote the exact PMX candidate after matching verification."""
import argparse,ast,hashlib,json,subprocess,tomllib,zipfile,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PAYLOAD={"__init__.py","asset_tracking.py","importers.py","mmd_importer.py","material_assets.py",
         "material_controls.py","pmx_materials.py","node_graph.py","sampling.py","shaders.py","lighting.py",
         "outlines.py","gaze.py","workflow.py","properties.py","panels.py","rendering.py","post_processing.py","project_io.py",
         "assets/original_shader.blend","assets/original_controls.blend","assets/upstream.json",
         "blender_manifest.toml","README.md","CHANGELOG.md","LICENSE","NOTICE",
         "docs/upstream-baseline.md","docs/basic-rendering.md","docs/pmx-rendering.md","docs/workflow.md"}

def sha(data):return hashlib.sha256(data).hexdigest()
def runtime_hashes():return {name:sha((ROOT/name).read_bytes()) for name in PAYLOAD if name.endswith('.py')}
def validate_evidence(evidence,interface,integration=False):
    hashes=runtime_hashes()
    assert evidence['scope']=='PMX-M01-M08' and interface['scope']=='PMX-M01-M08-UI'
    assert evidence['source_sha256']==interface['source_sha256']==hashes,'Runtime changed after verification'
    assert len(evidence['models'])>=3 and all(evidence['checks'].values())
    required=('source_data_unchanged','mmd_metadata_preserved','import_material_light_separate','manual_camera_preserved',
              'gaze_live','reset_and_restore','save_reload_exact','resource_counts_stable',
              'bone_and_vertex_morph_animation','material_failure_rollback')
    for model in evidence['models']:
        assert all(model.get(key) is True for key in required)
        assert model['material_tint_response']>.05 and model['shadow_response']>.03
        assert model['shadow_position_response']>.02 and model['light_response']>.05
        if model['source_edges_enabled']:
            assert model['outline_response']>.01 and model['outline_color_response']>.01
    expected=('split_actions','undo_redo','material_params_undo','light_undo','gaze_undo','panel_inventory',
              'cancel_cleanup','save_project','async_render')
    assert not interface.get('error') and all(interface['checks'].get(key) is True for key in expected)
    if integration:
        assert evidence['package_sha256'] and evidence['package_sha256']==interface['package_sha256']
    return hashes

def validate_archive(path):
    with zipfile.ZipFile(path) as package:
        assert package.testzip() is None and set(package.namelist())==PAYLOAD
        for name in PAYLOAD:assert package.read(name)==(ROOT/name).read_bytes(),name
    return {name:sha((ROOT/name).read_bytes()) for name in sorted(PAYLOAD)}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('candidate','release'))
    parser.add_argument('--blender',type=Path,required=True)
    parser.add_argument('--verification',type=Path,required=True)
    parser.add_argument('--interface-verification',type=Path,required=True)
    args=parser.parse_args()
    manifest=tomllib.loads((ROOT/'blender_manifest.toml').read_text(encoding='utf-8'))
    init=ast.parse((ROOT/'__init__.py').read_text(encoding='utf-8'))
    info=ast.literal_eval(next(n.value for n in init.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='bl_info' for t in n.targets)))
    assert '.'.join(map(str,info['version']))==manifest['version']
    for name in PAYLOAD:
        if name.endswith('.py'):ast.parse((ROOT/name).read_text(encoding='utf-8'),filename=name)
    evidence=json.loads(args.verification.read_text(encoding='utf-8'))
    interface=json.loads(args.interface_verification.read_text(encoding='utf-8'))
    validate_evidence(evidence,interface,integration=args.action=='release')
    directory=ROOT/'.build/candidate';directory.mkdir(parents=True,exist_ok=True)
    name=f"{manifest['id']}-{manifest['version']}.zip";candidate=directory/name
    if args.action=='candidate':
        assert not candidate.exists(),'Preserve frozen candidates; increment version if payload changes'
        command=[str(args.blender),'--background','--factory-startup','--command','extension']
        subprocess.run([*command,'build','--source-dir',str(ROOT),'--output-filepath',str(candidate)],check=True)
        subprocess.run([*command,'validate',str(candidate)],check=True)
        record={'version':manifest['version'],'archive':name,'bytes':candidate.stat().st_size,
                'sha256':sha(candidate.read_bytes()),'payload':validate_archive(candidate)}
        (directory/'candidate.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8',newline='\n')
        print('HGT_CANDIDATE',record['version'],record['sha256'],len(record['payload']));return
    record=json.loads((directory/'candidate.json').read_text(encoding='utf-8'))
    assert record['sha256']==evidence['package_sha256']==sha(candidate.read_bytes())
    validate_archive(candidate)
    release=ROOT/'release';target=release/name;assert not target.exists()
    shutil.copy2(candidate,target)
    (release/f"build-v{manifest['version']}.json").write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8',newline='\n')
    item={k:v for k,v in manifest.items() if k!='build'}
    item.update(archive_url=f"https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/v{manifest['version']}/release/{name}",
                archive_size=record['bytes'],archive_hash='sha256:'+record['sha256'])
    (release/'index.json').write_text(json.dumps({'version':'v1','blocklist':[],'data':[item]},ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    summary={'scope':evidence['scope'],'version':record['version'],'archive_sha256':record['sha256'],
             'models':evidence['models'],'checks':evidence['checks'],'interface_checks':interface['checks'],
             'native_cancel_input':interface['native_cancel_input'],'source_sha256':evidence['source_sha256']}
    (release/f"verification-v{manifest['version']}.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('HGT_RELEASE',record['version'],record['sha256'])
if __name__=='__main__':main()
