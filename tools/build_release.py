"""Build a local review archive or promote a fully verified PMX candidate."""
import argparse,ast,hashlib,json,subprocess,tomllib,zipfile,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PAYLOAD={"__init__.py","asset_tracking.py","importers.py","mmd_importer.py","material_assets.py",
         "material_controls.py","pmx_materials.py","node_graph.py","sampling.py","shaders.py","lighting.py",
         "face_assets.py","face_catalog.py","face_sdf.py","head_binding.py","scene_presets.py",
         "outlines.py","outline_profile.py","shadow_boundary.py","glow.py","glow_source.py","glow_preview.py","glow_modes.py","gaze.py","workflow.py","properties.py","panels.py","rendering.py","scene_models.py","project_io.py",
         "assets/original_shader.blend","assets/original_controls.blend","assets/upstream.json",
         "assets/scenes.json","assets/scene_city_terrace.blend","assets/scene_stage.blend",
         "blender_manifest.toml","README.md","CHANGELOG.md","LICENSE","NOTICE",
         "docs/upstream-baseline.md","docs/basic-rendering.md","docs/pmx-rendering.md","docs/workflow.md","docs/scene-presets.md"}
PAYLOAD.update({'assets/faces.json', 'jelly_eye.py', 'jelly_geometry.py'})
FACE_PRESETS=json.loads((ROOT/'assets/faces.json').read_text('utf-8'))['presets']
for preset in FACE_PRESETS:
    for role,name in preset['textures'].items():
        assert Path(name).parent==Path('faces') and Path(name).suffix=='.png','Invalid face asset path'
        assert hashlib.sha256((ROOT/'assets'/name).read_bytes()).hexdigest()==preset['sha256'][role]
        PAYLOAD.add('assets/'+name)

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
        has_edges=model['toon_edges_enabled'] if 'toon_edges_enabled' in model else model['source_edges_enabled']
        if has_edges:
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
    isolated=evidence.get('scope')=='GI-TOON-2.4-SDF-REGRESSION'
    required=('fresh_assembly_preserves_originals',
              'face_factor_interior_matches_approved' if isolated else 'approved_key_light_material_and_factor_pixels_equal',
              'owned_textures_pack_save_reopen_equal','restore_and_reapply_preserves_data_and_pixels')
    for model in evidence['models'].values():
        assert all(model['checks'].get(key) is True for key in required)
        assert len(model['frames'])>=7
        if isolated:
            # The accepted outline style changed. Compare the SDF field on
            # face interiors with outlines disabled, retaining strict pixels.
            for frame in model['frames'].values():
                factor=frame['factor']
                assert frame['colour']['current_style_rendered']
                assert factor['strict_face_interior_equal_approved'] and factor['max_image_buffer_error']==0
                assert factor['compared_face_pixels']>2000 and factor['border_excluded_pixels']==4
                assert factor['outline_disabled_for_algorithm_comparison'] is True
        else:
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
              'original_files_unchanged','register_unregister','existing_half_ring_replaced_on_explicit_load')
    assert all(evidence['checks'].get(key) is True for key in required)
    assert set(evidence['presets'])=={'CITY_TERRACE','STAGE'}
    assert all(interface['checks'].get(key) is True for key in
               ('always_visible_without_model','load_undo_redo','switch_undo_redo','remove_undo_redo'))
    if package_sha256 is not None:
        assert evidence['package_sha256']==interface['package_sha256']==package_sha256

def validate_usability_evidence(evidence,interface,hashes):
    assert evidence['scope']=='GI-TOON-USABILITY' and evidence['complete']
    assert evidence['source_sha256']==hashes,'Usability verification does not match current runtime'
    assert len(evidence['models'])>=3
    for model in evidence['models']:
        assert all(model.get(key) is True for key in ('source_and_mmd_unchanged','front_camera','visibility','light_presets_persist'))
        assert all(model['responses'][key]>.001 for key in
                   ('brightness','saturation','opacity','shadow_transition','outline_taper','outline','outline_color',
                    'light_energy','light_color'))
    assert all(evidence['checks'].get(key) is True for key in
               ('parameters_save_reopen_exact','city_terrace_v230_restored','original_scene_files_unchanged',
                'sidebar_and_display_controls','multi_character_uniform_isolation','reused_material_survives_restore'))
    assert all(interface['checks'].get(key) is True for key in
               ('display_controls_undo','light_presets_undo','realtime_viewport_shadow_response'))

def validate_outline_evidence(evidence,hashes,package_sha256=None):
    assert evidence['scope']=='GI-TOON-OUTLINE-SURFACES' and evidence['complete']
    assert evidence['source_sha256']==hashes,'Outline verification does not match current runtime'
    assert len(evidence['models'])>=3
    required=('material_colors_restored','outer_contours_preserved','legacy_upgrade_preserves_parameters_and_source',
              'source_disabled_outer_edges_preserved','no_resource_growth','save_reopen_exact','restore_reapply_exact')
    for model in evidence['models']:
        assert all(model['checks'].get(key) is True for key in required)
        assert model['silhouette_pixels_with_outline']>5 and model['silhouette_pixels_with_wide_outline']>20
        assert model['source_disabled_outer_surfaces']
        assert set(model['widths'])=={'default','wide'}
        assert all(row['reference_max_error']<=1/255+1e-6 for row in model['widths'].values())
    assert any(model.get('restored_color_pixels',0)>500 and model['excluded_inner_surfaces']
               for model in evidence['models']),'Missing actual inner-shell colour regression'
    if package_sha256 is not None:assert evidence['package_sha256']==package_sha256


def validate_cross_character_evidence(evidence,hashes,package_sha256=None):
    if evidence['scope']=='CROSS-CHARACTER-OUTLINE-PACKAGE':
        # Light/gradient controls preserve the generic inner-surface and
        # rest-height algorithms. Recheck all 13 regression/control fixtures;
        # do not relabel 2.4.2's 204-file/87-model audit as a new execution.
        assert evidence['complete'] and evidence['source_sha256']==hashes
        with zipfile.ZipFile(ROOT/'release/hoyo_gi_toon-2.4.2.zip') as baseline:
            old_outline=ast.parse(baseline.read('outlines.py'))
            new_outline=ast.parse((ROOT/'outlines.py').read_text('utf-8'))
            for name in ('eligible','surface_mask','record_surface_mask','profile'):
                select=lambda tree:ast.dump(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name))
                assert select(old_outline)==select(new_outline),'Generic inner protection or rest height changed: '+name
            old=ast.parse(baseline.read('pmx_materials.py'))
            new=ast.parse((ROOT/'pmx_materials.py').read_text('utf-8'))
            for name in ('is_inner_surface','visible_source_edge'):
                select=lambda tree:ast.dump(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name))
                assert select(old)==select(new)
        assert len(evidence['models'])>=13
        for model in evidence['models']:
            assert model['source_data_preserved'] and model['migration_parameters_and_profile_preserved'] and model['save_reopen_exact']
            assert model['source_image_max_error']<=1/255+1e-6
            assert set(model['views'])=={'front','back','left','right'}
            for view in model['views'].values():
                assert set(view)=={'default','wide'}
                assert all(row['largest_core_region']<20 and row['core_fraction']<.002 for row in view.values())
        if package_sha256 is not None:assert evidence['package_sha256']==package_sha256
        return
    assert evidence['scope']=='CROSS-CHARACTER-OUTLINE-COMPARISON' and evidence['complete']
    assert evidence['source_sha256']==hashes,'Cross-character evidence does not match runtime'
    assert evidence['inventory_pmx_files']>=204 and evidence['available_characters']>=81
    assert evidence['native_material_cases']>=78 and evidence['extra_variants']>=6
    assert evidence['canonical_native_cases']+evidence['geometry_only_cases']==evidence['available_characters']
    assert len(evidence['native_resource_failures'])==evidence['geometry_only_cases']
    assert len(evidence['regression_cases'])>=11 and len(evidence['intentional_source_edges'])>=2
    assert len(evidence['source_migration_cases'])>=13
    required=('source_migration_and_profile_preserved','visual_reviewed_all_cases','all_local_pmx_scanned_readonly','four_views_and_both_widths','all_81_characters_geometry_covered',
              'native_resource_errors_kept_explicit','source_files_and_verified_data_preserved',
              'native_regressions_removed','normal_exterior_silhouettes_preserved','source_enabled_edges_preserved')
    assert all(evidence['checks'].get(key) is True for key in required)
    if package_sha256 is not None:
        assert evidence['package_sha256']==package_sha256
        assert evidence['checks']['actual_zip_migration_and_views'] and len(evidence['actual_package_cases'])>=13
        for model in evidence['actual_package_cases']:
            assert model['source_data_preserved'] and model['migration_parameters_and_profile_preserved'] and model['save_reopen_exact']
            assert model['source_image_max_error']<=1/255+1e-6
            assert set(model['views'])=={'front','back','left','right'}
            assert all(set(view)=={'default','wide'} for view in model['views'].values())


def validate_panel_update(evidence,interface,hashes,package_sha256=None):
    assert evidence['scope']=='GI-TOON-PANELS-SDF' and evidence['complete']
    assert evidence['source_sha256']==hashes
    assets={str(p.relative_to(ROOT)).replace('\\','/'):sha(p.read_bytes()) for p in (ROOT/'assets/faces').glob('*.png')}
    assert evidence['asset_sha256']==assets and evidence['catalog_sha256']==sha((ROOT/'assets/faces.json').read_bytes())
    assert len(evidence['models'])>=3
    for model in evidence['models']:
        assert model['auto_manual_max_error']<=1/255+1e-6 and model['outline_above_one_response']>.02
        assert all(model[key] is True for key in ('source_and_mmd_preserved','only_face_rebuilt','controls_and_profiles_preserved',
                                                'all_choices_without_external_fbx','repeat_no_resource_growth','save_reopen_exact'))
        assert len(model['choices'])==2*(len(FACE_PRESETS)+1)
    assert evidence['checks']['sdf_failure_atomic_and_visible'] and evidence['checks']['user_reused_face_material_preserved']
    assert all(interface['checks'].get(key) is True for key in ('seven_independent_panels','scene_light_default_closed',
        'complete_models_only','automatic_material_preview','bundled_sdf_undo_redo','face_softness_undo_redo',
        'realtime_viewport_shadow_response','realtime_viewport_local_response'))
    if package_sha256 is not None:assert evidence['package_sha256']==package_sha256


def validate_lighting_controls(evidence,interface,hashes,package_sha256=None):
    assert evidence['scope']=='GI-TOON-LIGHTING-CONTROLS' and evidence['complete']
    assert evidence['source_sha256']==hashes and evidence['cpu_only']
    previous=json.loads((ROOT/'release/build-v2.5.0.json').read_text('utf-8'))
    assert evidence['baseline_archive_sha256']==previous['sha256']
    assert len(evidence['models'])>=3
    for model in evidence['models']:
        assert all(model['checks'].get(key) is True for key in (
            'legacy_parameters_and_source_preserved','rest_height_and_inner_mask_preserved',
            'geometry_light_reference_detached','sun_point_area_head_and_root_match_261_zero',
            'clearing_light_freezes_last_direction',
            'full_outline_light_update_faster_and_helper_static','editable_gradient_both_ends_and_middle',
            'zero_gradient_preserves_surface',
            'single_difference_changes_both_ends',
            'overall_softness_and_face_compensation','advanced_bias_controls_existing_threshold',
            'save_reopen_exact_and_restore_reapply_preserves_profile'))
        assert set(model['frames'])=={'front','left','right','back_l','back_r','up','down',
                                    'head_turn','model_turn','sun_roll','point','area'}
        assert all(frame['max_error']<=1/255+1e-6 and frame['mean_error']<1e-5 for frame in model['frames'].values())
        assert model['performance']['speedup']>2
        assert set(model['gradient_responses'])=={'top','bottom','middle'}
        assert all(value>.01 for value in model['gradient_responses'].values())
        assert all(value>.01 for value in model['single_difference_responses'].values())
    assert all(interface['checks'].get(key) is True for key in (
        'height_gradient_undo_redo','overall_softness_undo_redo','realtime_viewport_gradient_response',
        'single_outline_difference_control',
        'realtime_viewport_overall_softness_response','realtime_viewport_light_rotation_response'))
    if package_sha256 is not None:assert evidence['package_sha256']==package_sha256


def validate_shadow_boundaries(evidence, hashes, package_sha256=None):
    assert evidence['scope'] == 'GI-TOON-SHADOW-BOUNDARIES' and evidence['complete']
    assert evidence['source_sha256'] == hashes
    assert evidence['zero_reference'] == 'immutable-release-v2.6.1'
    assert len(evidence['models']) == 3
    required = ('zero_matches_261_all_lights', 'face_spatial_boundary_filter_responds',
                'zero_face_compensation_preserved',
                'zero_radius_filter_preserves_native_face',
                'legacy_face_parameter_at_zero',
                'overall_control_changes_boundary', 'uniform_only_drag_without_geometry_or_graph_rebuild',
                'migration_idempotent', 'save_reopen_exact', 'source_and_fixture_preserved')
    for model in evidence['models']:
        assert all(model['checks'].get(key) is True for key in required)
        assert set(model['zero_lights']) == {'front', 'left', 'right', 'back_l', 'back_r', 'up', 'down'}
        assert all(value == 0 for value in model['zero_lights'].values())
        assert model['zero_compensation_errors'] == {'0': 0, '3': 0}
        assert model['zero_radius_face_max_error'] <= 1 / 255 + 1e-6
        assert model['face_mask_response'] > .02
        assert model['positive_frames']['0.5']['max_response'] > .01
    if package_sha256 is not None:assert evidence['package_sha256'] == package_sha256


def validate_jelly_evidence(evidence, interface, interactions, hashes, package_sha256=None):
    for report, scope in ((evidence, 'GI-TOON-JELLY-EYES'), (interface, 'GI-TOON-JELLY-UI'),
                          (interactions, 'GI-TOON-JELLY-INTERACTIONS')):
        assert report['scope'] == scope and report['complete'] and not report.get('error')
        assert report['source_sha256'] == hashes, 'Jelly-eye evidence does not match runtime'
        if package_sha256 is not None:
            assert report.get('package_sha256') == package_sha256, 'Jelly-eye evidence must use the actual ZIP'
    assert len(evidence['models']) >= 3
    required = ('original_actions_meshes_weights_keys_and_materials_preserved', 'original_eye_action_actually_moves_eye',
                'iris_on_current_original_surface', 'sclera_lids_body_exact', 'zero_exact',
                'live_parameter_without_frame_change', 'scrubbing_deterministic', 'render_responds',
                'save_reopen_exact', 'disable_restores_exact', 'cycles_release_resources', 'failure_atomic')
    assert all(all(model['checks'].get(key) is True for key in required) for model in evidence['models'])
    assert all(interface['checks'].get(key) is True for key in (
        'panel_and_operator', 'enable_undo_redo', 'live_slider_in_material_view', 'parameter_undo_redo',
        'native_playback', 'glow_refreshes_when_jelly_changes',
        'disable_jelly_with_glow_active_cleans_resources', 'both_enable_orders_restore_resources'))
    assert all(interactions['checks'].get(key) is True for key in (
        'native_mmd_materials_and_restore_materials_preserve_effect', 'apply_materials_keeps_independent_effect',
        'look_at_camera_remains_bounded', 'unrelated_highlights_ignored', 'ambiguous_eye_rejected_without_writes',
        'two_real_characters_are_independent', 'parameters_can_be_keyframed'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('review','candidate','release'))
    parser.add_argument('--blender',type=Path,required=True)
    parser.add_argument('--verification',type=Path,required=True)
    parser.add_argument('--interface-verification',type=Path,required=True)
    parser.add_argument('--sdf-verification',type=Path)
    parser.add_argument('--usability-verification',type=Path)
    parser.add_argument('--outline-verification',type=Path)
    parser.add_argument('--cross-character-verification',type=Path)
    parser.add_argument('--sdf-interface-verification',type=Path)
    parser.add_argument('--panel-verification',type=Path)
    parser.add_argument('--lighting-controls-verification',type=Path,required=True)
    parser.add_argument('--shadow-boundary-verification',type=Path,required=True)
    parser.add_argument('--shadow-color-verification',type=Path,required=True)
    parser.add_argument('--shadow-viewport-verification',type=Path,required=True)
    parser.add_argument('--glow-verification',type=Path)
    parser.add_argument('--glow-interface-verification',type=Path)
    parser.add_argument('--jelly-verification',type=Path)
    parser.add_argument('--jelly-interface-verification',type=Path)
    parser.add_argument('--jelly-interactions-verification',type=Path)
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
    assert args.panel_verification,'Current panel and bundled-SDF verification is required'
    panel_update=json.loads(args.panel_verification.read_text('utf-8'))
    validate_panel_update(panel_update,interface,hashes,evidence.get('package_sha256') if args.action=='release' else None)
    lighting_controls=json.loads(args.lighting_controls_verification.read_text('utf-8'))
    validate_lighting_controls(lighting_controls,interface,hashes,evidence.get('package_sha256') if args.action=='release' else None)
    shadow_boundaries=json.loads(args.shadow_boundary_verification.read_text('utf-8'))
    validate_shadow_boundaries(shadow_boundaries,hashes,evidence.get('package_sha256') if args.action=='release' else None)
    shadow_colors=json.loads(args.shadow_color_verification.read_text('utf-8'))
    assert shadow_colors['scope']=='GI-TOON-SHADOW-COLOURS' and shadow_colors['complete']
    assert shadow_colors['source_sha256']==hashes and len(shadow_colors['models'])==3
    for model in shadow_colors['models']:
        assert model['body_endcolors_preserved'] and model['face_zero_radius_colors_preserved'] and model['source_preserved']
        assert model['body_core_pixels']>1000 and model['face_pixels']>20
        assert model['body_color_max_error']<=2/255+1e-6 and model['body_color_mean_error']<1e-4
        assert model['body_color_outlier_fraction']<.002 and model['face_color_max_error']<=1/255+1e-6
    if args.action=='release':assert shadow_colors['package_sha256']==evidence['package_sha256']
    shadow_viewport=json.loads(args.shadow_viewport_verification.read_text('utf-8'))
    assert shadow_viewport['scope']=='GI-TOON-SHADOW-VIEWPORT' and shadow_viewport['complete'] and not shadow_viewport.get('error')
    assert shadow_viewport['source_sha256']==hashes and len(shadow_viewport['models'])==3
    for model in shadow_viewport['models']:
        assert model['current']['median_ms']<=model['legacy']['median_ms']*1.6+8
        assert min(model['current']['light_response'],model['legacy']['light_response'])>.001
    if args.action=='release':assert shadow_viewport['package_sha256']==evidence['package_sha256']
    glow=None
    glow_ui=None
    if tuple(info['version'])>=(2,7,0):
        assert args.glow_verification and args.glow_interface_verification,'Bloom render and real viewport evidence is required'
        glow=json.loads(args.glow_verification.read_text('utf-8'))
        glow_ui=json.loads(args.glow_interface_verification.read_text('utf-8'))
        assert glow['scope']=='GI-TOON-GLOW' and glow['complete'] and not glow.get('error')
        assert glow_ui['scope']=='GI-TOON-GLOW-UI' and glow_ui['complete'] and not glow_ui.get('error')
        assert glow.get('character_only') is True and glow_ui.get('character_only') is True
        assert glow['source_sha256']==glow_ui['source_sha256']==hashes
        assert len(glow['models'])==3 and all(m['off_matches_262_exact'] and m['disable_exact']
            and m['shader_topology_unchanged'] and m['parameters_and_source_preserved'] for m in glow['models'])
        assert all(glow['checks'].values()) and glow['transparent_halo_pixels']>50 and glow['transparent_halo_alpha_max']>.01
        assert all(glow_ui['checks'].get(key) is True for key in ('auto_preview',
            'natural_compositor_parameter_preview','undo_graph_source_and_viewport','redo_graph_and_viewport','off_restores_viewport',
            'selected_character_only_and_switching','stationary_preview_uses_cache',
            'parameters_do_not_redraw_character_source','four_preview_cycles_release_resources',
            'material_colour_refreshes_source_after_compilation'))
        assert all(glow['checks'].get(key) is True for key in ('selected_character_only_and_switching',
            'bright_background_does_not_emit_glow','shared_materials_stay_isolated','blended_character_transparency',
            'foreground_occlusion','transparent_foreground_occlusion','original_collections_and_layers_restored'))
        assert glow_ui['natural_parameter_response']>.01
        if tuple(info['version'])>=(2,8,0):
            assert len(glow.get('modes',[]))==7 and all(m['zero_exact'] and m['saved_project_exact'] for m in glow['modes'])
            assert all(glow.get('mode_checks',{}).get(key) is True for key in (
                'seven_modes_render_and_zero_and_save_reopen','all_modes_ignore_unselected_actor_and_bright_world',
                'mode_specific_controls_respond','custom_kernel_responds_and_user_image_unchanged',
                'nested_kernel_copy_preserves_other_users','switching_cycles_restore_data_and_release_default_kernel'))
            assert glow.get('legacy_272_active_glow_exact') is True
            assert all(m.get('default_bloom_272_exact') is True for m in glow['models'])
            assert all(glow_ui['checks'].get(key) is True for key in (
                'all_seven_modes_natural_preview','mode_switching_reuses_character_source',
                'mode_undo_redo_keeps_selection_and_native_type','mode_cycles_release_kernel_and_preview'))
        if args.action=='release':assert glow['package_sha256']==glow_ui['package_sha256']==evidence['package_sha256']
    jelly=jelly_ui=jelly_interactions=None
    if tuple(info['version']) >= (2,9,0):
        assert args.jelly_verification and args.jelly_interface_verification and args.jelly_interactions_verification, 'Bounded jelly-eye animation, viewport and integration evidence is required'
        jelly=json.loads(args.jelly_verification.read_text('utf-8'))
        jelly_ui=json.loads(args.jelly_interface_verification.read_text('utf-8'))
        jelly_interactions=json.loads(args.jelly_interactions_verification.read_text('utf-8'))
        validate_jelly_evidence(jelly,jelly_ui,jelly_interactions,hashes,evidence.get('package_sha256') if args.action=='release' else None)
    outline=None
    if tuple(info['version'])>=(2,4,1):
        assert args.outline_verification,'Inner-shell colour and exterior silhouette evidence is required'
        outline=json.loads(args.outline_verification.read_text('utf-8'))
        validate_outline_evidence(outline,hashes,evidence.get('package_sha256') if args.action=='release' else None)
    cross=None
    if tuple(info['version'])>=(2,4,2):
        assert args.cross_character_verification,'Four-view cross-character outline evidence is required'
        cross=json.loads(args.cross_character_verification.read_text('utf-8'))
        validate_cross_character_evidence(cross,hashes,evidence.get('package_sha256') if args.action=='release' else None)
    usability=None
    if args.usability_verification:
        usability=json.loads(args.usability_verification.read_text('utf-8'))
        validate_usability_evidence(usability,interface,hashes)
        if args.action=='release':assert usability['package_sha256']==evidence['package_sha256']
    if args.action=='review':
        assert args.usability_verification,'Local review builds require the current usability checks'
    else:
        assert args.sdf_verification,'Full candidate/release builds require matching SDF evidence'
        sdf=json.loads(args.sdf_verification.read_text(encoding='utf-8'))
        validate_sdf_evidence(sdf,hashes,evidence.get('package_sha256') if args.action=='release' else None)
    scene=json.loads(args.scene_verification.read_text(encoding='utf-8'))
    scene_ui=json.loads(args.scene_interface_verification.read_text(encoding='utf-8'))
    validate_scene_evidence(scene,scene_ui,hashes,evidence.get('package_sha256') if args.action=='release' else None)
    sdf_ui=None
    if args.action=='release':
        assert args.sdf_interface_verification,'Actual ZIP SDF interface verification is required'
        sdf_ui=json.loads(args.sdf_interface_verification.read_text(encoding='utf-8'))
        assert sdf_ui['scope']=='PMX-M09-M12-UI' and not sdf_ui.get('error')
        assert sdf_ui['source_sha256']==hashes and sdf_ui['package_sha256']==evidence['package_sha256']
        assert all(sdf_ui['checks'].get(key) is True for key in ('bundled_sdf_undo_redo','face_softness_undo_redo'))
    directory=ROOT/'.build/candidate';directory.mkdir(parents=True,exist_ok=True)
    name=f"{manifest['id']}-{manifest['version']}.zip";candidate=directory/name
    if args.action in {'review','candidate'}:
        assert not candidate.exists(),'Preserve frozen candidates; increment version if payload changes'
        source=ROOT/'.build'/('source-v'+manifest['version'])
        assert not source.exists(),'Preserve the source staging directory'
        for path in PAYLOAD:
            target=source/path;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/path,target)
        command=[str(args.blender),'--background','--factory-startup','--command','extension']
        subprocess.run([*command,'build','--source-dir',str(source),'--output-filepath',str(candidate)],check=True)
        subprocess.run([*command,'validate',str(candidate)],check=True)
        record={'version':manifest['version'],'kind':args.action,'archive':name,'bytes':candidate.stat().st_size,
                'sha256':sha(candidate.read_bytes()),'payload':validate_archive(candidate)}
        (directory/'candidate.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8',newline='\n')
        print('HGT_REVIEW' if args.action=='review' else 'HGT_CANDIDATE',record['version'],record['sha256'],len(record['payload']));return
    record=json.loads((directory/'candidate.json').read_text(encoding='utf-8'))
    if record.get('kind')=='review':assert usability,'Promoting a review archive requires its actual-package usability evidence'
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
             'sdf_comparison_scope':sdf.get('scope'),
             'usability_models':usability['models'] if usability else [],
             'usability_checks':usability['checks'] if usability else {},
             'outline_surface_models':outline['models'] if outline else [],
             'cross_character_outlines':cross,
             'panel_and_bundled_sdf':panel_update,
             'lighting_controls':lighting_controls,
             'shadow_boundaries':shadow_boundaries,
             'shadow_colours':shadow_colors,
             'shadow_viewport':shadow_viewport,
             'glow':glow,'glow_interface':glow_ui,
             'jelly':jelly,'jelly_interface':jelly_ui,'jelly_interactions':jelly_interactions,
             'new_full_game_algorithm_recovered':sdf['full_new_game_shader_recovered']}
    (release/f"verification-v{manifest['version']}.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('HGT_RELEASE',record['version'],record['sha256'])
if __name__=='__main__':main()
