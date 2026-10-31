"""Freeze and promote the exact PMX candidate after matching verification."""
import argparse,ast,hashlib,json,subprocess,tomllib,zipfile,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PAYLOAD={"__init__.py","asset_tracking.py","importers.py","mmd_importer.py","material_assets.py",
         "material_controls.py","pmx_materials.py","node_graph.py","sampling.py","shaders.py","lighting.py",
         "face_assets.py","face_sdf.py","head_binding.py","scene_presets.py",
         "outlines.py","gaze.py","workflow.py","properties.py","panels.py","rendering.py","scene_models.py","project_io.py",
         "assets/original_shader.blend","assets/original_controls.blend","assets/upstream.json",
         "assets/scenes.json","assets/scene_city_terrace.blend","assets/scene_stage.blend",
         "blender_manifest.toml","README.md","CHANGELOG.md","LICENSE","NOTICE",
         "docs/upstream-baseline.md","docs/basic-rendering.md","docs/pmx-rendering.md","docs/workflow.md","docs/scene-presets.md"}

def sha(data):return hashlib.sha256(data).hexdigest()
def runtime_hashes():return {name:sha((ROOT/name).read_bytes()) for name in PAYLOAD if name.endswith('.py')}
def validate_evidence(evidence,interface,integration=False):
    hashes=runtime_hashes()
    assert evidence['scope']=='PMX-M09-M12' and interface['scope']=='PMX-M09-M12-UI'
    assert evidence['source_sha256']==interface['source_sha256']==hashes,'Runtime changed after verification'
    expected_background=('native_render_without_model','light_without_model','plugin_import_independent',
                         'legacy_200_project','register_unregister','all_models','packed_scene')
    assert len(evidence['models'])>=3 and all(evidence['checks'].get(key) is True for key in expected_background)
    required=('source_data_unchanged','mmd_metadata_preserved','existing_model_without_reimport','no_bone_repair',
              'manual_camera_light_preserved','native_render_scene_unchanged','whole_scene_render',
              'gaze_live','reset_and_restore','save_reload_exact','resource_counts_stable',
              'bone_and_vertex_morph_animation','material_failure_rollback')
    for model in evidence['models']:
        assert all(model.get(key) is True for key in required)
        assert model['material_tint_response']>.05 and model['shadow_response']>.03
        assert model['shadow_position_response']>.02 and model['light_response']>.05
        if model['source_edges_enabled']:
            assert model['outline_response']>.01 and model['outline_color_response']>.01
    expected=('empty_scene_controls','no_output_panel','light_without_model_undo','camera_without_model_undo',
              'existing_model_apply_undo','material_params_undo','gaze_undo','save_project','native_async_render')
    assert not interface.get('error') and all(interface['checks'].get(key) is True for key in expected)
    if integration:
        assert evidence['package_sha256'] and evidence['package_sha256']==interface['package_sha256']
    return hashes

def validate_archive(path):
    with zipfile.ZipFile(path) as package:
        assert package.testzip() is None and set(package.namelist())==PAYLOAD
        for name in PAYLOAD:assert package.read(name)==(ROOT/name).read_bytes(),name
    return {name:sha((ROOT/name).read_bytes()) for name in sorted(PAYLOAD)}

def validate_sdf_evidence(evidence,hashes,package_sha256=None):
    assert evidence['complete'] and evidence['protected_sources_unchanged']
    runtime={name:value for name,value in evidence['payload_sha256'].items() if name.endswith('.py')}
    assert runtime==hashes,'SDF verification does not match current runtime'
    assert len(evidence['models'])>=3
    kinds={model['candidate_kind'] for model in evidence['models'].values()}
    assert {'alpha','ra_half'}<=kinds
    required=('fresh_assembly_preserves_originals','approved_key_light_material_and_factor_pixels_equal',
              'owned_textures_pack_save_reopen_equal','restore_and_reapply_preserves_data_and_pixels')
    for model in evidence['models'].values():
        assert all(model['checks'].get(key) is True for key in required)
        assert len(model['frames'])>=7
        assert all(check['strict_pixels_equal_approved'] and check['max_image_buffer_error']==0
                   for frame in model['frames'].values() for check in frame.values())
        if model['candidate_kind']=='ra_half':assert model['checks']['ra_softness_response_and_reset_equal']
    if package_sha256 is not None:assert evidence['package_sha256']==package_sha256

def validate_scene_evidence(evidence,interface,hashes,package_sha256=None):
    assert evidence['scope']=='SCENE-PRESETS' and interface['scope']=='SCENE-PRESETS-UI'
    assert evidence['complete'] and interface['complete'] and not interface.get('error')
    assert evidence['source_sha256']==interface['source_sha256']==hashes,'Scene runtime changed after verification'
    assets={name:sha((ROOT/'assets'/name).read_bytes()) for name in ('scenes.json','scene_city_terrace.blend','scene_stage.blend')}
    assert evidence['asset_sha256']==interface['asset_sha256']==assets,'Scene asset changed after verification'
    required=('clean_assets_and_packed_images','empty_scene_both_presets',
              'repeat_load_and_remove_no_resource_growth','output_units_compositor_unchanged',
              'switch_replaces_only_previous_preset','previous_camera_light_world_restored',
              'default_light_still_works','manual_pointer_changes_preserved',
              'two_scenes_isolated_and_shared_light_preserved','manual_collection_deletion_can_restore',
              'invalid_asset_failure_rollback','user_added_and_reused_data_preserved',
              'existing_pmx_source_and_mmd_metadata_unchanged','packed_scene_save_reopen_and_restore',
              'original_files_unchanged','register_unregister')
    assert all(evidence['checks'].get(key) is True for key in required)
    assert set(evidence['presets'])=={'CITY_TERRACE','STAGE'}
    assert all(interface['checks'].get(key) is True for key in
               ('always_visible_without_model','load_undo_redo','switch_undo_redo','remove_undo_redo'))
    if package_sha256 is not None:
        assert evidence['package_sha256']==interface['package_sha256']==package_sha256

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('candidate','release'))
    parser.add_argument('--blender',type=Path,required=True)
    parser.add_argument('--verification',type=Path,required=True)
    parser.add_argument('--interface-verification',type=Path,required=True)
    parser.add_argument('--sdf-verification',type=Path,required=True)
    parser.add_argument('--sdf-interface-verification',type=Path)
    parser.add_argument('--scene-verification',type=Path,required=True)
    parser.add_argument('--scene-interface-verification',type=Path,required=True)
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
    hashes=validate_evidence(evidence,interface,integration=args.action=='release')
    sdf=json.loads(args.sdf_verification.read_text(encoding='utf-8'))
    validate_sdf_evidence(sdf,hashes,evidence.get('package_sha256') if args.action=='release' else None)
    scene=json.loads(args.scene_verification.read_text(encoding='utf-8'))
    scene_ui=json.loads(args.scene_interface_verification.read_text(encoding='utf-8'))
    validate_scene_evidence(scene,scene_ui,hashes,evidence.get('package_sha256') if args.action=='release' else None)
    sdf_ui=None
    if args.action=='release':
        assert args.sdf_interface_verification,'Actual ZIP SDF interface verification is required'
        sdf_ui=json.loads(args.sdf_interface_verification.read_text(encoding='utf-8'))
        assert sdf_ui['scope']=='P04-F06-UI' and not sdf_ui.get('error')
        assert sdf_ui['source_sha256']==hashes and sdf_ui['package_sha256']==evidence['package_sha256']
        assert all(sdf_ui['checks'].get(key) is True for key in ('face_resource_directory_undo_redo','face_softness_undo_redo'))
    directory=ROOT/'.build/candidate';directory.mkdir(parents=True,exist_ok=True)
    name=f"{manifest['id']}-{manifest['version']}.zip";candidate=directory/name
    if args.action=='candidate':
        assert not candidate.exists(),'Preserve frozen candidates; increment version if payload changes'
        source=ROOT/'.build'/('source-v'+manifest['version'])
        assert not source.exists(),'Preserve the source staging directory'
        for path in PAYLOAD:
            target=source/path;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/path,target)
        command=[str(args.blender),'--background','--factory-startup','--command','extension']
        subprocess.run([*command,'build','--source-dir',str(source),'--output-filepath',str(candidate)],check=True)
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
             'render_mode':'native_current_scene','source_sha256':evidence['source_sha256'],
             'sdf_models':{name:{'sampling':model['candidate_kind'],'checks':model['checks'],
                                 'key_light_conditions':len(model['frames'])} for name,model in sdf['models'].items()},
             'sdf_interface_checks':sdf_ui['checks'],
             'scene_presets':scene['presets'],'scene_checks':scene['checks'],'scene_interface_checks':scene_ui['checks'],
             'new_full_game_algorithm_recovered':sdf['full_new_game_shader_recovered']}
    (release/f"verification-v{manifest['version']}.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('HGT_RELEASE',record['version'],record['sha256'])
if __name__=='__main__':main()
