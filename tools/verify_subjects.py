"""Verify approved 16–21 with real assets and explicit mixed-surface fixtures."""
import argparse
import importlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from verification_runtime import copy_better,load_mmd,load_addon,install_candidate,file_hash,unload_addon
from verification_data import source_snapshot,mmd_snapshot,mesh_data
from verification_fixture import animated_fbx
from verification_subject_fixture import mixed_pmx

parser=argparse.ArgumentParser()
for name in ('assets-index','pmx-index','better-fbx','mmd-tools','output-dir'):
    parser.add_argument('--'+name,type=Path,required=True)
parser.add_argument('--candidate',type=Path)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
project=Path(__file__).resolve().parents[1];out=args.output_dir.resolve()
assert out.is_relative_to(project/'.verification');out.mkdir(parents=True,exist_ok=True)
better,_=copy_better(args.better_fbx,out/'_runtime')
mmd=load_mmd(args.mmd_tools,out/'_runtime')
addon=install_candidate(args.candidate,out) if args.candidate else load_addon(project)
payload=Path(addon.__file__).resolve().parent
subjects=addon.workflow.subjects
hashes={p.name:file_hash(p) for p in payload.glob('*.py')}
fbx=json.loads(args.assets_index.read_text(encoding='utf-8'))['models']
pmx=json.loads(args.pmx_index.read_text(encoding='utf-8'))['models']
report={'scope':'16–21','package_sha256':file_hash(args.candidate) if args.candidate else None,
        'source_sha256':hashes,'models':[],'checks':{}}


def save():
    assert hashes=={p.name:file_hash(p) for p in payload.glob('*.py')},'Runtime changed during verification'
    (out/'subjects.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def files(path):
    return {p.relative_to(path).as_posix():file_hash(p) for p in path.rglob('*') if p.is_file()}


def snapshot(batch):
    return source_snapshot(batch),mmd_snapshot(batch) if batch.source_format=='pmx' else None


def unchanged(batch,baseline):
    current=snapshot(batch)
    if current!=baseline:
        (out/'difference.json').write_text(json.dumps({'before':baseline,'after':current},ensure_ascii=False,indent=2),encoding='utf-8')
        raise AssertionError('Source data changed')


def state(root):
    return [(p.key,p.role,p.included,p.locked) for p in root.hgt_character.parts]


def render(root,path,transparent=False):
    scene=bpy.context.scene;scene.hgt_output.filepath=str(path);scene.hgt_output.transparent=transparent
    original=addon.workflow.asset_tracking.scene_state(bpy.context)
    before=addon.workflow.asset_tracking.data_pointers()
    addon.rendering.start(scene,root,invoke=False)
    after=addon.workflow.asset_tracking.data_pointers()
    after['images']-={i.as_pointer() for i in bpy.data.images if i.type=='RENDER_RESULT' and i.as_pointer() not in before['images']}
    assert before==after,'Temporary render resources leaked'
    assert all(getattr(owner,key)==value for owner,key,value in original),'Original scene changed'
    image=bpy.data.images.load(str(path),check_existing=False)
    result=np.array(image.pixels[:],dtype=np.float32).reshape((-1,4));bpy.data.images.remove(image)
    assert result[:,:3].std()>.02,'Blank render'
    assert ((result[:,0]>.9)&(result[:,2]>.9)&(result[:,1]<.1)).mean()<.002,'Missing texture'
    return result


def reload_pixels(before,after):
    # Native Eevee serialization also changes a few specular/edge pixels in
    # 0.5.3. Keep alpha exact and bound both affected area and total RGB error.
    delta=np.abs(before-after)
    metrics={'changed_fraction':float(np.any(delta>0,axis=1).mean()),
             'mean_error':float(delta.mean()),'maximum_error':float(delta.max())}
    assert np.array_equal(before[:,3],after[:,3]),'Save/reload changed silhouette'
    assert metrics['changed_fraction']<.0002 and metrics['mean_error']<.00001 and metrics['maximum_error']<.08,metrics
    return metrics


cases=[('FBX 风之翼',fbx[0]),('FBX 技能附件',fbx[3]),('PMX 主体',pmx[2]),
       ('FBX 混合网格',None),('PMX 混合网格',None)]
for label,model in cases:
    print('HGT_SUBJECT_START',label,flush=True)
    bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
    folder=out/label;folder.mkdir(exist_ok=True)
    if label=='FBX 混合网格':
        batch=animated_fbx(addon,fbx[0]['path'],folder/'fixture',accessories=True)
        path=Path(batch.source)
    else:
        path=mixed_pmx(folder/'fixture') if label=='PMX 混合网格' else Path(model['path'])
        batch=addon.workflow.importers.import_character(str(path))
    bpy.context.view_layer.update()
    original_files=files(path.parent);baseline=snapshot(batch)
    visibility={o:(o.hide_render,o.hide_get()) for o in batch.meshes}
    slots={o:tuple(s.material for s in o.material_slots) for o in batch.meshes}
    root=addon.workflow.assemble(batch,bpy.context);settings=root.hgt_character
    bpy.context.view_layer.update();unchanged(batch,baseline)
    assert settings.parts_version==1 and settings.source_armature and settings.source_root
    assert all(p.object in batch.objects for p in settings.parts)
    assert all(p.included for p in settings.parts if p.role=='BODY' and not p.locked)
    assert all(not p.included for p in settings.parts if p.role in {'WEAPON','GLIDER','EFFECT'})
    for entry in settings.meshes:
        if not entry.original_data:continue
        source=baseline[0]['meshes'][str(entry.original_data.as_pointer())]
        assert mesh_data(entry.render_data,set(source['uv']),set(source['colors']))==source
        assert subjects.PART_ID not in entry.original_data.attributes
    if label=='FBX 风之翼':assert any(p.role=='GLIDER' for p in settings.parts)
    if label=='FBX 技能附件':
        assert any(p.role=='EFFECT' for p in settings.parts)
        assert all(p.role=='BODY' and p.included for p in settings.parts if p.object.name in {'Accessory','Hat','Ring'})
    if label=='PMX 主体':
        assert not addon.panels.HGT_PT_parts.poll(bpy.context)
    if label=='FBX 混合网格':
        unknown=[p for p in settings.parts if p.role=='OTHER' and not p.locked]
        assert unknown and all(p.included for p in unknown),'Ambiguity did not retain visibility'
        assert all(p.role=='BODY' for p in settings.parts if p.object.name=='Bow')
        for part in unknown:
            subjects.set_part(root,part.key,role='WEAPON')
            assert not part.included
        report['checks']['unknown_kept_and_corrected']=True
        report['checks']['head_decoration_preserved']=True
    accessories=[p for p in settings.parts if not p.locked and p.role not in {'BODY','OTHER'}]
    scene=bpy.context.scene;scene.hgt_output.width,scene.hgt_output.height=640,960
    low_before,high_before=addon.rendering.character_bounds(root)
    subject=render(root,folder/'subject.png',True)
    for part in accessories:subjects.set_part(root,part.key,True)
    low_after,high_after=addon.rendering.character_bounds(root)
    with_parts=render(root,folder/'accessories.png',True)
    for part in accessories:
        subjects.set_part(root,part.key,False)
    returned=render(root,folder/'returned.png',True)
    assert np.array_equal(subject,returned),'Display toggle did not return identical pixels'
    if accessories:
        assert np.abs(subject-with_parts).max()>.01,'No accessory render response'
    mixed='混合网格' in label
    if mixed:
        assert any(p.role=='WEAPON' for p in settings.parts)
        assert high_after.x-high_before.x>1,'Hidden weapon still affects framing'
        mixed_entry=next(e for e in settings.meshes if e.original_data and
                         len({p.role for p in settings.parts if p.object==e.object})>1)
        assert len(mixed_entry.original_data.polygons)==len(mixed_entry.render_data.polygons)
        assert any(m.type=='NODES' and m.node_group.get('hgt_subject_filter') for m in mixed_entry.object.modifiers if m.type=='NODES')
        weapon=next(p for p in settings.parts if p.role=='WEAPON' and p.object==mixed_entry.object)
        subjects.set_part(root,weapon.key,role='BODY');assert weapon.included
        subjects.set_part(root,weapon.key,role='WEAPON');assert not weapon.included
        assert len(mixed_entry.render_data.shape_keys.key_blocks)>1
    before_ids=addon.workflow.asset_tracking.data_pointers()
    for _ in range(8):addon.workflow.refresh_character(root)
    assert before_ids==addon.workflow.asset_tracking.data_pointers()
    unchanged(batch,baseline)
    expected=state(root)
    bpy.ops.wm.save_as_mainfile(filepath=str(folder/'subject.blend'),relative_remap=False)
    # Restore is checked before reopening: in-memory source IDs stay comparable.
    original_refs={e.object:e.original_data for e in settings.meshes if e.original_data}
    addon.workflow.restore(root);bpy.context.view_layer.update();unchanged(batch,baseline)
    assert all(o.data==data for o,data in original_refs.items())
    assert all(tuple(s.material for s in o.material_slots)==mats for o,mats in slots.items())
    assert all((o.hide_render,o.hide_get())==v for o,v in visibility.items())
    counts=addon.workflow.asset_tracking.data_pointers()
    assert addon.workflow.assemble(batch,bpy.context)==root
    addon.workflow.restore(root)
    assert counts==addon.workflow.asset_tracking.data_pointers(),'Reassembly leaked IDs'
    assert files(path.parent)==original_files
    bpy.ops.wm.open_mainfile(filepath=str(folder/'subject.blend'))
    root=bpy.context.scene.hgt_target
    assert state(root)==expected
    reopened=render(root,folder/'reopened.png',True)
    reload_difference=reload_pixels(subject,reopened)
    report['models'].append({'name':label,'source_format':batch.source_format,'mixed':mixed,
        'source_files_unchanged':len(original_files),'source_data_unchanged':True,
        'mmd_metadata_preserved':True,'derived_geometry_unchanged':True,'references_restored':True,
        'visibility_restored':True,'save_reload':True,'repeat_no_leak':True,'toggle_pixels_restored':True,
        'reload_pixel_difference':reload_difference,
        'bounds_without':[list(low_before),list(high_before)],'bounds_with':[list(low_after),list(high_after)],
        'parts':[{'key':p.key,'name':p.name,'role':p.role,'included':p.included,'locked':p.locked,
                  'faces':p.face_count,'basis':p.basis} for p in root.hgt_character.parts]})
    save();print('HGT_SUBJECT_PASSED',label,flush=True)

# First assembly failure after masks are written must restore source state.
bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
batch=addon.workflow.importers.import_character(fbx[0]['path'])
baseline=snapshot(batch);before=addon.workflow.asset_tracking.data_pointers()
with patch.object(addon.workflow.shaders.ShaderLibrary,'build_material',side_effect=ValueError('Injected subject assembly failure')):
    try:addon.workflow.assemble(batch,bpy.context)
    except ValueError as exc:assert str(exc)=='Injected subject assembly failure'
    else:raise AssertionError('Assembly failure ignored')
assert before==addon.workflow.asset_tracking.data_pointers();unchanged(batch,baseline)
report['checks']['assembly_failure_rollback']=True
first=addon.workflow.assemble(batch,bpy.context)
first_parts=state(first)
second=addon.workflow.build(pmx[2]['path'],bpy.context)
addon.workflow.restore(second)
assert state(first)==first_parts and first.hgt_character.managed
unchanged(batch,baseline)
report['checks']['mixed_imports_isolated']=True
addon.workflow.restore(first)
unload_addon(addon);mmd.unregister();better.unregister()
report['checks']['register_unregister']=True
save();print('HGT_SUBJECTS_COMPLETE',flush=True)
