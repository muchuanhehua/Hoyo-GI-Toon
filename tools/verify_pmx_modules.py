"""Verify separate PMX actions, material response and MMD data protection."""
import argparse,json,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Vector,Quaternion
from unittest.mock import patch
from verification_runtime import load_mmd,load_addon,install_candidate,unload_addon,file_hash
from verification_data import source_snapshot,mmd_snapshot,mesh_data

parser=argparse.ArgumentParser()
for name in ('assets-index','mmd-tools','output-dir'):parser.add_argument('--'+name,type=Path,required=True)
parser.add_argument('--candidate',type=Path)
parser.add_argument('--model-index',type=int,action='append')
parser.add_argument('--diagnose',action='store_true')
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
project=Path(__file__).resolve().parents[1];out=args.output_dir.resolve()
assert out.is_relative_to(project/'.verification');out.mkdir(parents=True,exist_ok=True)
mmd=load_mmd(args.mmd_tools,out/'_runtime')
addon=install_candidate(args.candidate,out) if args.candidate else load_addon(project)
payload=Path(addon.__file__).resolve().parent
hashes={p.name:file_hash(p) for p in payload.glob('*.py')}
report={'scope':'PMX-M01-M08','package_sha256':file_hash(args.candidate) if args.candidate else None,
        'source_sha256':hashes,'models':[],'checks':{}}
def save():
    assert hashes=={p.name:file_hash(p) for p in payload.glob('*.py')}
    (out/'pmx-modules.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def pixels(path):
    image=bpy.data.images.load(str(path),check_existing=False)
    data=np.array(image.pixels[:],dtype=np.float32).reshape((-1,4))
    bpy.data.images.remove(image);return data
def render(root,path):
    bpy.context.scene.hgt_output.filepath=str(path)
    addon.rendering.start(bpy.context.scene,root)
    return pixels(path)
def diff(a,b):return float(np.abs(a-b).max())
models=json.loads(args.assets_index.read_text(encoding='utf-8'))['models']
for index,model in enumerate(models):
    if args.model_index and index not in args.model_index:continue
    folder=out/model['name'];folder.mkdir(exist_ok=True)
    bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
    scene=bpy.context.scene;scene.render.resolution_x,scene.render.resolution_y=384,576
    scene.render.film_transparent=True
    source=Path(model['path']);files={str(p):file_hash(p) for p in source.parent.rglob('*') if p.is_file()}
    before=addon.workflow.asset_tracking.data_pointers();start=time.monotonic()
    root=addon.workflow.build(str(source),bpy.context);settings=root.hgt_character
    imported=time.monotonic();data=addon.workflow.asset_tracking.new_data(before)
    data['objects']=tuple(o for o in data['objects'] if o!=root and not o.get('hgt_helper'))
    slot=next(e.object.material_slots[0] for e in settings.meshes if e.object.material_slots)
    original=slot.material;slot.link='OBJECT';slot.material=original
    # Author ordinary bone and vertex-morph keys before material replacement.
    # This reproduces the data ownership expected when MMD motion is present.
    head=addon.gaze.head_bone(root);head.rotation_mode='QUATERNION'
    head.rotation_quaternion=Quaternion();head.keyframe_insert(data_path='rotation_quaternion',frame=1)
    head.rotation_quaternion=Quaternion((0,0,1),.12);head.keyframe_insert(data_path='rotation_quaternion',frame=5)
    candidates=[]
    for entry in settings.meshes:
        keys=entry.object.data.shape_keys
        if not keys:continue
        driven={curve.data_path for curve in keys.animation_data.drivers} if keys.animation_data else set()
        candidates.extend((entry.object,key) for key in keys.key_blocks if key!=keys.reference_key
                          and not key.name.startswith(('mmd_','_')) and key.path_from_id('value') not in driven)
    assert candidates,'Model has no freely animated vertex morph'
    morph_object,morph_key=next(((obj,key) for obj,key in candidates if key.name in {'笑い','あ'}),candidates[0])
    morph_name=morph_key.name
    morph_key.value=0;morph_key.keyframe_insert(data_path='value',frame=1)
    morph_key.value=.6;morph_key.keyframe_insert(data_path='value',frame=5)
    scene.frame_set(1);bpy.context.view_layer.update()
    data['actions']=tuple(a for a in bpy.data.actions if a.as_pointer() not in before['actions'])
    batch=addon.workflow.asset_tracking.ImportBatch(str(source),data,{},source_format='pmx',model_root=settings.source_root,armature=settings.source_armature)
    baseline=source_snapshot(batch);metadata=mmd_snapshot(batch)
    assert settings.imported and not settings.managed and not settings.bindings
    assert all(e.render_data is None for e in settings.meshes)
    assert not any(o.type=='LIGHT' for o in scene.objects)
    assert tuple(settings.camera.location)==(0,0,0) and tuple(settings.camera.rotation_euler)==(0,0,0)
    assert sum(o.type=='CAMERA' for o in scene.objects)==1
    visibility={e.object:(e.object.hide_render,e.object.hide_get()) for e in settings.meshes}
    camera=settings.camera;matrix=camera.matrix_world.copy()
    ids=addon.workflow.asset_tracking.data_pointers();real_build=addon.shaders.ShaderLibrary.build_material;calls=[0]
    def failed_material(library,assets):
        calls[0]+=1
        if calls[0]==2:raise RuntimeError('injected material failure')
        return real_build(library,assets)
    with patch.object(addon.shaders.ShaderLibrary,'build_material',failed_material):
        try:addon.workflow.apply_materials(root,bpy.context)
        except RuntimeError as exc:assert 'injected material failure' in str(exc)
        else:raise AssertionError('Material failure was accepted')
    assert ids==addon.workflow.asset_tracking.data_pointers()
    assert source_snapshot(batch)==baseline and mmd_snapshot(batch)==metadata
    assert settings.imported and not settings.managed and settings.camera==camera
    assert bpy.ops.hgt.apply_materials()=={'FINISHED'}
    assert settings.managed and settings.bindings and camera.matrix_world==matrix
    assert not any(o.type=='LIGHT' for o in scene.objects)
    assert visibility=={o:(o.hide_render,o.hide_get()) for o in visibility}
    assert source_snapshot(batch)==baseline and mmd_snapshot(batch)==metadata
    ids=addon.workflow.asset_tracking.data_pointers()
    assert bpy.ops.hgt.apply_materials()=={'FINISHED'} and ids==addon.workflow.asset_tracking.data_pointers()
    assert bpy.ops.hgt.default_light()=={'FINISHED'}
    light=settings.light_source
    assert bpy.ops.hgt.default_light()=={'FINISHED'} and settings.light_source==light
    assert sum(o.type=='LIGHT' for o in scene.objects)==1
    bpy.context.view_layer.update()
    pts=[e.object.matrix_world@Vector(c) for e in settings.meshes if not e.object.hide_render for c in e.object.bound_box]
    low=Vector(tuple(min(p[i] for p in pts) for i in range(3)));high=Vector(tuple(max(p[i] for p in pts) for i in range(3)))
    center=(low+high)*.5;size=high.z-low.z
    camera.location=center+Vector((0,-size*3,0));camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.data.type='ORTHO';camera.data.sensor_fit='VERTICAL';camera.data.ortho_scale=max(size,(high.x-low.x)/(.6666667))*1.15
    bpy.context.view_layer.update();manual=camera.matrix_world.copy()
    first=render(root,folder/'base.png');assert (first[:,3]>.5).mean()>.04
    assert camera.matrix_world==manual
    binding=next(b for b in settings.bindings if b.role in {'body','hair'} and b.source.mmd_material.alpha>.5)
    binding.tint=(.4,.7,1);tinted=render(root,folder/'tint.png')
    assert diff(first,tinted)>.05
    assert bpy.ops.hgt.reset_materials()=={'FINISHED'}
    binding.shadow_color=(.2,.3,.45);shadow=render(root,folder/'shadow.png')
    print('HGT_SHADOW_DIAGNOSTIC',binding.source_name,binding.role,settings.shadow_position,diff(first,shadow),flush=True)
    if not args.diagnose:assert diff(first,shadow)>.03
    assert bpy.ops.hgt.reset_materials()=={'FINISHED'}
    settings.shadow_position=.15;threshold=render(root,folder/'threshold.png')
    print('HGT_THRESHOLD_DIAGNOSTIC',diff(first,threshold),flush=True)
    if not args.diagnose:assert diff(first,threshold)>.02
    assert bpy.ops.hgt.reset_materials()=={'FINISHED'}
    settings.outline=.8;outline=render(root,folder/'outline.png')
    edges=any(b.source.mmd_material.enabled_toon_edge and b.source.mmd_material.edge_weight>0 for b in settings.bindings)
    if edges:assert diff(first,outline)>.01
    assert bpy.ops.hgt.reset_materials()=={'FINISHED'}
    edge_binding=next((b for b in settings.bindings if b.source.mmd_material.enabled_toon_edge
        and b.source.mmd_material.edge_weight>0 and b.source.mmd_material.edge_color[3]>0
        and b.source.mmd_material.alpha>0 and b.role in {'body','hair'}),None)
    edge_color_response=0
    if edge_binding:
        edge_binding.outline_color=(1,.05,.05)
        edge_color_response=diff(first,render(root,folder/'edge-color.png'))
        assert edge_color_response>.01
        assert bpy.ops.hgt.reset_materials()=={'FINISHED'}
    rotation=light.rotation_euler.copy();light.rotation_euler.z+=1.1;bpy.context.view_layer.update()
    angled=render(root,folder/'light.png');assert diff(first,angled)>.05
    light.rotation_euler=rotation;bpy.context.view_layer.update()
    constraints={b.name:len(b.constraints) for b in settings.source_armature.pose.bones}
    assert bpy.ops.hgt.look_camera()=={'FINISHED'}
    before_gaze=[tuple(i.helper.rotation_quaternion) for i in settings.gaze_bones]
    camera.location.x+=size*.25;bpy.context.view_layer.update()
    assert before_gaze!=[tuple(i.helper.rotation_quaternion) for i in settings.gaze_bones]
    render(root,folder/'gaze.png')
    camera.matrix_world=manual
    gaze_first=[tuple(i.helper.rotation_quaternion) for i in settings.gaze_bones]
    scene.frame_set(5);bpy.context.view_layer.update()
    assert abs(morph_object.data.shape_keys.key_blocks[morph_name].value-.6)<1e-5
    assert gaze_first!=[tuple(i.helper.rotation_quaternion) for i in settings.gaze_bones]
    animated=render(root,folder/'animated.png');assert diff(first,animated)>.05
    scene.frame_set(1);bpy.context.view_layer.update()
    assert bpy.ops.hgt.look_camera()=={'FINISHED'} and not settings.look_camera
    assert constraints=={b.name:len(b.constraints) for b in settings.source_armature.pose.bones}
    assert source_snapshot(batch)==baseline and mmd_snapshot(batch)==metadata
    counts=addon.workflow.asset_tracking.data_pointers()
    for _ in range(30):addon.workflow.refresh_character(root)
    assert counts==addon.workflow.asset_tracking.data_pointers()
    saved=render(root,folder/'saved.png')
    bpy.ops.wm.save_as_mainfile(filepath=str(folder/'model.blend'),relative_remap=False)
    addon.workflow.restore(root)
    assert not settings.managed and settings.imported and settings.camera==camera and settings.light_source==light
    assert source_snapshot(batch)==baseline and mmd_snapshot(batch)==metadata
    bpy.ops.wm.open_mainfile(filepath=str(folder/'model.blend'))
    scene=bpy.context.scene;root=scene.hgt_target
    reopened=render(root,folder/'reopened.png')
    assert np.array_equal(saved,reopened)
    assert files=={str(p):file_hash(p) for p in source.parent.rglob('*') if p.is_file()}
    report['models'].append({'name':model['name'],'source_files_unchanged':len(files),'source_data_unchanged':True,
        'mmd_metadata_preserved':True,'import_material_light_separate':True,'manual_camera_preserved':True,
        'material_tint_response':diff(first,tinted),'shadow_response':diff(first,shadow),
        'shadow_position_response':diff(first,threshold),'outline_response':diff(first,outline),
        'outline_color_response':edge_color_response,'source_edges_enabled':edges,
        'light_response':diff(first,angled),'gaze_live':True,'reset_and_restore':True,'save_reload_exact':True,
        'bone_and_vertex_morph_animation':True,
        'material_failure_rollback':True,
        'resource_counts_stable':True,'seconds':time.monotonic()-start})
    save();print('HGT_PMX_MODULE_PASSED',model['name'],flush=True)
unload_addon(addon);mmd.unregister()
report['checks']={'register_unregister':True,'all_models':len(report['models'])==len(models),'diagnostic_disabled':not args.diagnose}
save();print('HGT_PMX_MODULES_COMPLETE',flush=True)
