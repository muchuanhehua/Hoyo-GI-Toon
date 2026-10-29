"""PMX import-to-PNG, MMD metadata and reversible-data verification."""
import argparse
import importlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Euler
from mathutils import Vector
from verification_runtime import load_mmd, load_addon, install_candidate, unload_addon, file_hash
from verification_data import source_snapshot, mmd_snapshot, mesh_data

parser = argparse.ArgumentParser()
parser.add_argument('--assets-index', type=Path, required=True)
parser.add_argument('--mmd-tools', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
parser.add_argument('--candidate', type=Path)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
project = Path(__file__).resolve().parents[1]
out = args.output_dir.resolve()
assert out.is_relative_to(project/'.verification')
out.mkdir(parents=True, exist_ok=True)
mmd = load_mmd(args.mmd_tools, out/'_runtime')
addon = install_candidate(args.candidate, out) if args.candidate else load_addon(project)
payload = Path(addon.__file__).resolve().parent
importer = importlib.import_module(addon.__name__+'.mmd_importer')
materials = importlib.import_module(addon.__name__+'.pmx_materials')
models = json.loads(args.assets_index.read_text(encoding='utf-8'))['models']
hashes = {p.name: file_hash(p) for p in payload.glob('*.py')}
report = {'scope':'09–15', 'blender':bpy.app.version_string, 'mmd_tools':mmd.MMD_TOOLS_VERSION,
          'package_sha256':file_hash(args.candidate) if args.candidate else None,
          'source_sha256':hashes, 'models':[], 'checks':{}}


def save():
    assert hashes == {p.name:file_hash(p) for p in payload.glob('*.py')}, 'Runtime changed during verification'
    (out/'pmx-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def files(folder):
    return {p.relative_to(folder).as_posix():file_hash(p) for p in folder.rglob('*') if p.is_file()}


def preserved(batch, baseline, metadata):
    current, mmd_current = source_snapshot(batch), mmd_snapshot(batch)
    if current != baseline or mmd_current != metadata:
        (out/'preservation-diff.json').write_text(json.dumps({'baseline':baseline,'current':current,
            'mmd_baseline':metadata,'mmd_current':mmd_current},ensure_ascii=False,indent=2),encoding='utf-8')
        raise AssertionError('Imported source or MMD data changed')


def render(root, path, transparent=False, post=False):
    scene=bpy.context.scene
    scene.hgt_output.width,scene.hgt_output.height=640,960
    scene.hgt_output.transparent,scene.hgt_output.post_processing=transparent,post
    scene.hgt_output.filepath=str(path)
    state=addon.workflow.asset_tracking.scene_state(bpy.context)
    ids=addon.workflow.asset_tracking.data_pointers()
    addon.rendering.start(scene,root,invoke=False)
    after_ids=addon.workflow.asset_tracking.data_pointers()
    after_ids['images'] -= {i.as_pointer() for i in bpy.data.images
                           if i.type=='RENDER_RESULT' and i.as_pointer() not in ids['images']}
    if ids != after_ids:
        difference={kind:[item.name for item in getattr(bpy.data,kind) if item.as_pointer() in (after_ids[kind]-ids[kind])]
                    for kind in ids if ids[kind]!=after_ids[kind]}
        raise AssertionError(f'Render changed IDs: {difference}')
    assert all(getattr(owner,key)==value for owner,key,value in state), 'Render changed original scene'
    image=bpy.data.images.load(str(path),check_existing=False)
    assert tuple(image.size)==(640,960)
    pixels=np.array(image.pixels[:],dtype=np.float32).reshape((-1,4))
    bpy.data.images.remove(image)
    assert pixels[:,:3].std()>.04, 'Blank render'
    assert ((pixels[:,0]>.9)&(pixels[:,2]>.9)&(pixels[:,1]<.1)).mean()<.002, 'Missing-texture magenta'
    if transparent:
        assert (pixels[:,3]<.01).mean()>.2 and (pixels[:,3]>.95).mean()>.08, 'Invalid alpha'
    return pixels


for model in models:
    print('HGT_PMX_START',model['name'],flush=True)
    path=Path(model['path']).resolve()
    source_files=files(path.parent)
    bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
    scene=bpy.context.scene
    scene.render.engine='CYCLES';scene.render.fps=30
    scene.render.resolution_x,scene.render.resolution_y=333,222
    scene.view_settings.exposure=.125
    scene.mmd_validation_results='Existing validation'
    old_state=addon.workflow.asset_tracking.scene_state(bpy.context)
    raw=[]
    actual_state=importer._state
    def capture(root,armature):
        bpy.context.view_layer.update()
        data={'objects':tuple(root.children_recursive)+(root,), 'meshes':tuple(o.data for o in root.children_recursive if o.type=='MESH'),
              'armatures':(armature.data,)}
        batch=addon.workflow.asset_tracking.ImportBatch(str(path),data,{})
        raw.append(source_snapshot(batch))
        return actual_state(root,armature)
    with patch.object(importer,'_state',capture):
        batch=addon.workflow.importers.import_character(str(path))
    assert batch.source_format=='pmx' and batch.operator=='mmd_tools.import_model'
    assert len(raw)==2
    assert raw[0]['meshes']==raw[1]['meshes'], 'Bone repair changed mesh geometry'
    before_bones=batch.repair['before']['bones'];after_bones=batch.repair['after']['bones']
    for name,bone in before_bones.items():
        assert name in after_bones and bone['rest']==after_bones[name]['rest'] and bone['parent']==after_bones[name]['parent'], name
    assert all(getattr(owner,key)==value for owner,key,value in old_state), 'Import changed original scene settings'
    baseline,metadata=source_snapshot(batch),mmd_snapshot(batch)
    slots={o:tuple(s.material for s in o.material_slots) for o in batch.meshes}
    visibility={o:(o.hide_render,o.hide_get()) for o in batch.meshes}
    folder=out/model['name'];folder.mkdir(exist_ok=True)
    (folder/'repair.json').write_text(json.dumps(batch.repair,ensure_ascii=False,indent=2),encoding='utf-8')
    root=addon.workflow.assemble(batch,bpy.context)
    bpy.context.view_layer.update()
    preserved(batch,baseline,metadata)
    for entry in root.hgt_character.meshes:
        if entry.render_data:
            original=baseline['meshes'][str(entry.original_data.as_pointer())]
            assert mesh_data(entry.render_data,set(original['uv']),set(original['colors']))==original
            assert entry.render_data.uv_layers.get('UV0')
        if getattr(entry.object,'mmd_type','') in {'RIGID_BODY','JOINT'}:
            assert entry.original_data is None and entry.object.hide_render
    for binding in root.hgt_character.bindings:
        generated=binding.generated
        assert generated['hgt_format']=='pmx'
        assert generated!=binding.source and binding.source in batch.data['materials']
        for tree in addon.workflow.shaders.walk(generated.node_tree):
            assert all(n.bl_idname!='NodeUndefined' for n in tree.nodes)
        pmx=json.loads(generated['hgt_pmx'])
        assert pmx['alpha']==binding.source.mmd_material.alpha
        assert generated.use_backface_culling == (not binding.source.mmd_material.is_double_sided)
    ids=addon.workflow.asset_tracking.data_pointers()
    assert addon.workflow.assemble(batch,bpy.context)==root
    for _ in range(5):addon.workflow.refresh_character(root)
    assert ids==addon.workflow.asset_tracking.data_pointers()
    head=root.hgt_character.head
    constraint=head.constraints['Child Of'];bone=constraint.target.pose.bones[constraint.subtarget]
    initial=head.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()
    mode,quaternion=bone.rotation_mode,bone.rotation_quaternion.copy()
    bone.rotation_mode='QUATERNION';bone.rotation_quaternion=Euler((.1,.2,.1)).to_quaternion()
    bpy.context.view_layer.update()
    assert head.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world!=initial
    bone.rotation_quaternion=quaternion;bone.rotation_mode=mode;bpy.context.view_layer.update()
    preserved(batch,baseline,metadata)
    scene.hgt_output.width,scene.hgt_output.height=640,960
    addon.rendering.frame_camera(scene,root)
    front=render(root,folder/'front.png')
    root.hgt_character.light_azimuth=-1.0
    side=render(root,folder/'side-light.png')
    light_delta=float(np.abs(front[:,:3]-side[:,:3]).max())
    assert light_delta>.01,'No light response'
    root.hgt_character.light_azimuth=.35
    if model != models[0]:
        for semantic in ('toon','sphere'):
            switches=[n for b in root.hgt_character.bindings for n in b.generated.node_tree.nodes
                      if n.get('hgt_pmx_semantic')==semantic]
            assert switches
            for node in switches:node.inputs[0].default_value=0
            variant=render(root,folder/(semantic+'-off.png'))
            for node in switches:node.inputs[0].default_value=1
            delta=float(np.abs(front[:,:3]-variant[:,:3]).max())
            assert delta>.005,(semantic,'No visible response',delta)
    root.hgt_character.outline=0
    thin=render(root,folder/'outline-off.png')
    root.hgt_character.outline=.6
    thick=render(root,folder/'outline-wide.png')
    outline_delta=float(np.abs(thin-thick).max())
    has_outline=any(m.type=='NODES' and m.node_group and m.node_group.get('hgt_pmx_outline')
                    for e in root.hgt_character.meshes for m in e.object.modifiers)
    assert outline_delta>.01 if has_outline else outline_delta==0, 'Outline does not respect PMX edge flags'
    root.hgt_character.outline=.25
    alpha=render(root,folder/'transparent.png',True)
    post_alpha=render(root,folder/'post.png',True,True)
    assert np.abs(alpha[:,3]-post_alpha[:,3]).max()<.005
    scene.hgt_output.transparent=False;scene.hgt_output.post_processing=False
    scene.hgt_output.filepath=str(folder/'front.png')
    bpy.ops.wm.save_as_mainfile(filepath=str(folder/'render.blend'),relative_remap=False)
    original_camera=root.hgt_character.camera
    camera=original_camera.copy();camera.data=original_camera.data.copy()
    scene.collection.objects.link(camera)
    scene.hgt_output.camera=camera
    head_position=(constraint.target.matrix_world @ constraint.target.pose.bones[constraint.subtarget].matrix).translation
    focus=head_position+Vector((0,0,root.hgt_character.height*.035))
    camera.data.ortho_scale=root.hgt_character.height*.26
    for view,direction in [('head',Vector((0,-1,0))),('head-turn',Vector((.42,-1,0)))]:
        camera.location=focus+direction.normalized()*root.hgt_character.height*3
        camera.rotation_euler=(focus-camera.location).to_track_quat('-Z','Y').to_euler()
        bpy.context.view_layer.update()
        closeup=render(root,folder/(view+'.png')).reshape((960,640,4))
        assert closeup[456:504,296:344,:3].mean()>.04,'Black coverage around head reference'
    scene.hgt_output.camera=original_camera
    camera_data=camera.data
    bpy.data.objects.remove(camera,do_unlink=True);bpy.data.cameras.remove(camera_data)
    bpy.context.view_layer.update()
    preserved(batch,baseline,metadata)
    refs={e.object:e.original_data for e in root.hgt_character.meshes if e.original_data}
    addon.workflow.restore(root);bpy.context.view_layer.update()
    preserved(batch,baseline,metadata)
    assert all(o.data==mesh for o,mesh in refs.items())
    assert all(tuple(s.material for s in o.material_slots)==mats for o,mats in slots.items())
    assert all((o.hide_render,o.hide_get())==v for o,v in visibility.items())
    counts=addon.workflow.asset_tracking.data_pointers()
    rebuilt=addon.workflow.assemble(batch,bpy.context)
    assert rebuilt==root
    addon.workflow.restore(rebuilt);bpy.context.view_layer.update()
    assert counts==addon.workflow.asset_tracking.data_pointers(),'Restore/reassembly leaked IDs'
    preserved(batch,baseline,metadata)
    assert files(path.parent)==source_files
    record={'name':model['name'],'source_files_unchanged':len(source_files),'source_data_unchanged':True,
        'mmd_metadata_unchanged':True,'repair_rest_geometry_unchanged':True,'derived_geometry_unchanged':True,
        'original_mesh_refs_restored':True,'head_follow':True,'repeat_assembly':True,'restore_reassembly':True,
        'materials':len(slots[next(o for o in slots if o.mmd_type not in {'RIGID_BODY','JOINT'})]),
        'repair_bones_before':len(before_bones),'repair_bones_after':len(after_bones),
        'changed_bone_records':sum(before_bones.get(k)!=v for k,v in after_bones.items()),
        'light_response_max':light_delta,'outline_response_max':outline_delta,'source_edges_enabled':has_outline,
        'transparent_alpha':True,'post_alpha':True,
        'renders':['front.png','side-light.png','transparent.png','post.png','head.png','head-turn.png']}
    report['models'].append(record);save()
    print('HGT_PMX_PASSED',model['name'],flush=True)

# Reload actual saved source IDs and their MMD metadata in the same private process.
bpy.ops.wm.open_mainfile(filepath=str(out/models[-1]['name']/'render.blend'))
root=bpy.context.scene.hgt_target
assert root.hgt_character.managed and root.hgt_character.source_root.mmd_type=='ROOT'
assert root.hgt_character.source_armature.type=='ARMATURE'
assert json.loads(root.hgt_character.source_root['hgt_mmd_repair'])['after']['bones']
render(root,out/'reload.png')
addon.workflow.restore(root)
report['checks']['save_reload']=True

# Material failure must restore existing imported MMD IDs as well as clean generated IDs.
bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
assert bpy.context.scene.rigidbody_world is None
empty_ids=addon.workflow.asset_tracking.data_pointers()
with patch.object(importer,'_state',side_effect=RuntimeError('Injected first-import failure')):
    try:addon.workflow.build(models[0]['path'],bpy.context)
    except RuntimeError as exc:assert str(exc)=='Injected first-import failure'
    else:raise AssertionError('First import failure ignored')
assert empty_ids==addon.workflow.asset_tracking.data_pointers()
assert bpy.context.scene.rigidbody_world is None,'Failed import left an embedded physics world'
report['checks']['empty_scene_failure_rollback']=True
batch=addon.workflow.importers.import_character(models[0]['path'])
baseline,metadata=source_snapshot(batch),mmd_snapshot(batch)
ids=addon.workflow.asset_tracking.data_pointers()
original=materials.Catalog.resolve;calls=[0]
def fail(catalog,*a,**kw):
    calls[0]+=1
    if calls[0]==2:raise ValueError('Injected PMX material failure')
    return original(catalog,*a,**kw)
with patch.object(materials.Catalog,'resolve',fail):
    try:addon.workflow.assemble(batch,bpy.context)
    except ValueError as exc:assert str(exc)=='Injected PMX material failure'
    else:raise AssertionError('Assembly failure ignored')
assert ids==addon.workflow.asset_tracking.data_pointers()
preserved(batch,baseline,metadata)
report['checks']['assembly_failure_rollback']=True
first=addon.workflow.assemble(batch,bpy.context)
first_state=mmd_snapshot(batch)
second=addon.workflow.build(models[1]['path'],bpy.context)
first_shadow=first.hgt_character.shadow_position
first_groups={g for g in bpy.data.node_groups if g.get('hgt_owner')==first.hgt_character.uid}
assert first_groups.isdisjoint({g for g in bpy.data.node_groups if g.get('hgt_owner')==second.hgt_character.uid})
second.hgt_character.shadow_position=.75
assert first.hgt_character.shadow_position==first_shadow
addon.workflow.restore(second)
assert first.hgt_character.managed and mmd_snapshot(batch)==first_state
report['checks']['two_imports_isolated']=True
addon.workflow.restore(first)
ids=addon.workflow.asset_tracking.data_pointers()
with patch.object(importer,'_state',side_effect=RuntimeError('Injected repair failure')):
    try:addon.workflow.build(models[0]['path'],bpy.context)
    except RuntimeError as exc:assert str(exc)=='Injected repair failure'
    else:raise AssertionError('Repair failure ignored')
assert ids==addon.workflow.asset_tracking.data_pointers()
report['checks']['import_repair_failure_rollback']=True
mmd.unregister()
try:addon.workflow.build(models[0]['path'],bpy.context)
except RuntimeError as exc:assert 'MMD Tools' in str(exc)
else:raise AssertionError('Missing MMD dependency ignored')
assert ids==addon.workflow.asset_tracking.data_pointers()
mmd.register()
report['checks']['missing_mmd_dependency']=True
unload_addon(addon)
assert not hasattr(bpy.types.Object,'hgt_character')
addon.register();assert hasattr(bpy.types.Object,'hgt_character')
unload_addon(addon);mmd.unregister()
report['checks']['register_unregister']=True
save()
print('HGT_PMX_COMPLETE',flush=True)
