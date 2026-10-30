"""Verify existing scene PMX models, native rendering and source preservation."""
import argparse,json,sys,time
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Vector,Quaternion
from verification_runtime import load_mmd,load_addon,install_candidate,unload_addon,file_hash
from verification_data import source_snapshot,mmd_snapshot

parser=argparse.ArgumentParser()
for name in ('assets-index','mmd-tools','output-dir'):parser.add_argument('--'+name,type=Path,required=True)
parser.add_argument('--candidate',type=Path)
parser.add_argument('--model-index',type=int,action='append')
parser.add_argument('--legacy-project',type=Path)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
project=Path(__file__).resolve().parents[1];out=args.output_dir.resolve()
assert out.is_relative_to(project/'.verification');out.mkdir(parents=True,exist_ok=True)
mmd=load_mmd(args.mmd_tools,out/'_runtime')
addon=install_candidate(args.candidate,out) if args.candidate else load_addon(project)
payload=Path(addon.__file__).resolve().parent
hashes={p.name:file_hash(p) for p in payload.glob('*.py')}
report={'scope':'PMX-M09-M12','package_sha256':file_hash(args.candidate) if args.candidate else None,
        'source_sha256':hashes,'models':[],'checks':{}}

def save():
    assert hashes=={p.name:file_hash(p) for p in payload.glob('*.py')}
    (out/'pmx-modules.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def pixels(path):
    image=bpy.data.images.load(str(path),check_existing=False)
    data=np.array(image.pixels[:],dtype=np.float32).reshape((-1,4))
    bpy.data.images.remove(image);return data

def render(path):
    scene=bpy.context.scene
    settings=(scene.render.filepath,scene.render.resolution_x,scene.render.resolution_y,
              scene.render.resolution_percentage,scene.camera,len(bpy.data.scenes))
    assert bpy.ops.hgt.render()=={'FINISHED'}
    assert settings==(scene.render.filepath,scene.render.resolution_x,scene.render.resolution_y,
                      scene.render.resolution_percentage,scene.camera,len(bpy.data.scenes))
    bpy.data.images['Render Result'].save_render(str(path),scene=scene)
    assert (out/'output-canary.png').read_bytes()==b'preserve native output'
    return pixels(path)

def diff(a,b):return float(np.abs(a-b).max())

def assert_sources(batch,baseline,metadata,label):
    actual={'source':source_snapshot(batch),'mmd':mmd_snapshot(batch)}
    expected={'source':baseline,'mmd':metadata}
    if actual==expected:return
    changes=[]
    def compare(a,b,path=''):
        if a==b:return
        if isinstance(a,dict) and isinstance(b,dict):
            for key in a.keys()|b.keys():compare(a.get(key),b.get(key),path+'/'+str(key))
        elif isinstance(a,list) and isinstance(b,list) and len(a)==len(b):
            for i,(x,y) in enumerate(zip(a,b)):compare(x,y,path+'/'+str(i))
        else:changes.append({'path':path,'before':a,'after':b})
    compare(expected,actual)
    (out/(label+'-source-diff.json')).write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding='utf-8')
    raise AssertionError(str(changes[:8]))

def empty():
    bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
    scene=bpy.context.scene
    scene.render.resolution_x,scene.render.resolution_y=384,576
    scene.render.film_transparent=True
    scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA'
    scene.render.filepath=str(out/'output-canary.png')
    (out/'output-canary.png').write_bytes(b'preserve native output')
    return scene

def frame(camera,objects):
    points=[obj.matrix_world@Vector(c) for obj in objects for c in obj.bound_box]
    low=Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high=Vector(tuple(max(p[i] for p in points) for i in range(3)))
    size=high.z-low.z;center=(high+low)*.5
    camera.data.type='ORTHO';camera.data.ortho_scale=size*1.2
    camera.location=center+Vector((0,-size*3,0))
    camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
    bpy.context.view_layer.update()
    return size,center

scene=empty()
light=addon.lighting.default_light(scene)
assert addon.lighting.default_light(scene)==light and len(bpy.data.lights)==1
assert not any(addon.workflow.current(o) for o in scene.objects)
bpy.ops.mesh.primitive_cube_add()
cube=bpy.context.object
camera=addon.rendering.prepare(scene)
frame(camera,[cube])
generic=render(out/'native-without-model.png')
assert np.count_nonzero(generic[:,3]>.5)>100
report['checks']['native_render_without_model']=True
report['checks']['light_without_model']=True

models=json.loads(args.assets_index.read_text(encoding='utf-8'))['models']
scene=empty()
root=addon.workflow.build(models[0]['path'],bpy.context)
assert root.hgt_character.imported and not root.hgt_character.managed
assert scene.camera and tuple(scene.camera.location)==(0,0,0)
assert not any(o.type=='LIGHT' for o in scene.objects)
camera=scene.camera
assert addon.rendering.prepare(scene)==camera and len(bpy.data.cameras)==1
report['checks']['plugin_import_independent']=True

for index,model in enumerate(models):
    if args.model_index and index not in args.model_index:continue
    scene=empty();started=time.monotonic()
    folder=out/model['name'];folder.mkdir(exist_ok=True)
    source=Path(model['path']);files={str(p):file_hash(p) for p in source.parent.rglob('*') if p.is_file()}
    before=addon.workflow.asset_tracking.data_pointers()
    assert bpy.ops.mmd_tools.import_model('EXEC_DEFAULT',filepath=str(source),scale=.08,
        clean_model=False,remove_doubles=False,rename_bones=False,fix_bone_order=False,
        fix_ik_links=False,apply_bone_fixed_axis=False)=={'FINISHED'}
    imported=addon.workflow.asset_tracking.new_data(before)
    source_root=next(o for o in imported['objects'] if getattr(o,'mmd_type','')=='ROOT')
    rig=next(o for o in imported['objects'] if o.type=='ARMATURE')
    assert 'hgt_mmd_repair' not in source_root
    meshes=[o for o in imported['objects'] if o.type=='MESH' and getattr(o,'mmd_type','') not in {'RIGID_BODY','JOINT'}]
    for obj in bpy.context.selected_objects:obj.select_set(False)
    meshes[0].select_set(True);bpy.context.view_layer.objects.active=meshes[0]
    addon.scene_models.sync_active(scene)
    assert scene.hgt_model==source_root and addon.scene_models.selected(bpy.context)==source_root
    camera=addon.rendering.prepare(scene);size,center=frame(camera,meshes)
    light=addon.lighting.default_light(scene)
    camera_matrix=camera.matrix_world.copy();light_rotation=tuple(light.rotation_euler)
    slot=next(o.material_slots[0] for o in meshes if o.material_slots)
    material=slot.material;slot.link='OBJECT';slot.material=material
    packed=0
    if index==2:
        for image in imported['images']:
            if image.has_data and len(image.pixels):
                image.pack();image.filepath='//packed-only/'+image.name
                packed+=1
        assert packed>0
    head=addon.gaze.head_bone(source_root);head.rotation_mode='QUATERNION'
    head.rotation_quaternion=Quaternion();head.keyframe_insert(data_path='rotation_quaternion',frame=1)
    head.rotation_quaternion=Quaternion((0,0,1),.12);head.keyframe_insert(data_path='rotation_quaternion',frame=5)
    morphs=[]
    for obj in meshes:
        keys=obj.data.shape_keys
        if not keys:continue
        driven={curve.data_path for curve in keys.animation_data.drivers} if keys.animation_data else set()
        morphs.extend((obj,key) for key in keys.key_blocks if key!=keys.reference_key
                      and not key.name.startswith(('mmd_','_')) and key.path_from_id('value') not in driven)
    obj,key=next(((o,k) for o,k in morphs if k.name in {'笑い','あ'}),morphs[0]);morph_name=key.name
    key.value=0;key.keyframe_insert(data_path='value',frame=1)
    key.value=.6;key.keyframe_insert(data_path='value',frame=5)
    scene.frame_set(1);bpy.context.view_layer.update()
    imported['actions']=tuple(a for a in bpy.data.actions if a.as_pointer() not in before['actions'])
    batch=addon.workflow.asset_tracking.ImportBatch(str(source),imported,{},model_root=source_root,armature=rig)
    baseline=source_snapshot(batch);metadata=mmd_snapshot(batch)
    counts=addon.workflow.asset_tracking.data_pointers();calls=[0]
    original=addon.shaders.ShaderLibrary.build_material
    def fail(library,assets):
        calls[0]+=1
        if calls[0]==2:raise RuntimeError('injected material failure')
        return original(library,assets)
    with patch.object(addon.shaders.ShaderLibrary,'build_material',fail):
        try:addon.workflow.apply_materials(source_root,bpy.context)
        except RuntimeError as exc:assert 'injected material failure' in str(exc)
        else:raise AssertionError('Partial material failure accepted')
    assert counts==addon.workflow.asset_tracking.data_pointers()
    assert source_snapshot(batch)==baseline and mmd_snapshot(batch)==metadata
    assert bpy.ops.hgt.look_camera()=={'FINISHED'}
    root=scene.hgt_target
    assert not root.hgt_character.managed and not root.hgt_character.imported
    assert bpy.ops.hgt.look_camera()=={'FINISHED'}
    assert source_snapshot(batch)==baseline and mmd_snapshot(batch)==metadata
    assert bpy.ops.hgt.apply_materials()=={'FINISHED'}
    root=scene.hgt_target;settings=root.hgt_character
    assert settings.managed and not settings.imported and not settings.source_file
    assert 'hgt_mmd_repair' not in source_root
    assert camera.matrix_world==camera_matrix and tuple(light.rotation_euler)==light_rotation
    assert len(bpy.data.cameras)==1 and len(bpy.data.lights)==1
    assert source_snapshot(batch)==baseline and mmd_snapshot(batch)==metadata
    counts=addon.workflow.asset_tracking.data_pointers()
    assert addon.workflow.apply_materials(source_root,bpy.context)==root
    assert counts==addon.workflow.asset_tracking.data_pointers()
    first=render(folder/'base.png')
    binding=next(b for b in settings.bindings if b.role in {'body','hair'})
    binding.tint=(.4,.7,1);tinted=render(folder/'tint.png');assert diff(first,tinted)>.05
    bpy.ops.hgt.reset_materials()
    binding.shadow_color=(.2,.3,.45);shadow=render(folder/'shadow.png');assert diff(first,shadow)>.03
    bpy.ops.hgt.reset_materials()
    settings.shadow_position=.15;threshold=render(folder/'threshold.png');assert diff(first,threshold)>.02
    bpy.ops.hgt.reset_materials()
    settings.outline=.8;outline=render(folder/'outline.png')
    edges=settings.has_outline
    if edges:assert diff(first,outline)>.01
    bpy.ops.hgt.reset_materials()
    edge=next((b for b in settings.bindings if b.source.mmd_material.enabled_toon_edge
               and b.source.mmd_material.edge_weight>0 and b.source.mmd_material.edge_color[3]>0
               and b.source.mmd_material.alpha>0 and b.role in {'body','hair'}),None)
    edge_response=0
    if edge:
        edge.outline_color=(1,.05,.05);edge_response=diff(first,render(folder/'edge-color.png'))
        assert edge_response>.01
        bpy.ops.hgt.reset_materials()
    rotation=light.rotation_euler.copy();light.rotation_euler.z+=1.1;bpy.context.view_layer.update()
    angled=render(folder/'light.png');assert diff(first,angled)>.05
    light.rotation_euler=rotation;bpy.context.view_layer.update()
    assert bpy.ops.hgt.look_camera()=={'FINISHED'}
    gaze_before=[tuple(item.helper.rotation_quaternion) for item in settings.gaze_bones]
    camera.location.x+=size*.25;bpy.context.view_layer.update()
    assert gaze_before!=[tuple(item.helper.rotation_quaternion) for item in settings.gaze_bones]
    camera.matrix_world=camera_matrix
    gaze_before=[tuple(item.helper.rotation_quaternion) for item in settings.gaze_bones]
    scene.frame_set(5);bpy.context.view_layer.update()
    assert abs(obj.data.shape_keys.key_blocks[morph_name].value-.6)<1e-5
    assert gaze_before!=[tuple(item.helper.rotation_quaternion) for item in settings.gaze_bones]
    animated=render(folder/'animated.png');assert diff(first,animated)>.05
    scene.frame_set(1);bpy.context.view_layer.update();bpy.ops.hgt.look_camera()
    assert source_snapshot(batch)==baseline and mmd_snapshot(batch)==metadata
    # Add a scene prop without changing the active mesh used by MMD's UI getters.
    geometry=bpy.data.meshes.new('Verification scene prop')
    geometry.from_pydata([(x,y,z) for x in (-.5,.5) for y in (-.5,.5) for z in (-.5,.5)],[],
                         [(0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3)])
    prop=bpy.data.objects.new(geometry.name,geometry);scene.collection.objects.link(prop)
    prop.location=(center.x+size*.34,center.y-size*.25,center.z);prop.scale=(size*.1,)*3
    prop_material=bpy.data.materials.new('Verification magenta');prop_material.use_nodes=True
    prop_material.node_tree.nodes.clear()
    emission=prop_material.node_tree.nodes.new('ShaderNodeEmission')
    emission.inputs['Color'].default_value=(1,0,1,1)
    output=prop_material.node_tree.nodes.new('ShaderNodeOutputMaterial')
    prop_material.node_tree.links.new(emission.outputs[0],output.inputs['Surface'])
    prop.data.materials.append(prop_material)
    saved=render(folder/'saved.png')
    assert np.count_nonzero((saved[:,0]>.95)&(saved[:,1]<.03)&(saved[:,2]>.95))>8
    assert_sources(batch,baseline,metadata,'whole-scene')
    bpy.ops.wm.save_as_mainfile(filepath=str(folder/'model.blend'),relative_remap=False)
    addon.workflow.restore(root)
    assert not settings.managed and scene.camera==camera and scene.hgt_light==light
    assert source_snapshot(batch)==baseline and mmd_snapshot(batch)==metadata
    bpy.ops.wm.open_mainfile(filepath=str(folder/'model.blend'))
    reopened=render(folder/'reopened.png');assert np.array_equal(saved,reopened)
    assert files=={str(p):file_hash(p) for p in source.parent.rglob('*') if p.is_file()}
    report['models'].append({'name':model['name'],'source_files_unchanged':len(files),'source_data_unchanged':True,
        'mmd_metadata_preserved':True,'existing_model_without_reimport':True,'no_bone_repair':True,
        'manual_camera_light_preserved':True,'native_render_scene_unchanged':True,'whole_scene_render':True,'packed_images':packed,
        'material_tint_response':diff(first,tinted),'shadow_response':diff(first,shadow),
        'shadow_position_response':diff(first,threshold),'outline_response':diff(first,outline),
        'outline_color_response':edge_response,'source_edges_enabled':bool(edges),'light_response':diff(first,angled),
        'gaze_live':True,'reset_and_restore':True,'save_reload_exact':True,'bone_and_vertex_morph_animation':True,
        'material_failure_rollback':True,'resource_counts_stable':True,'seconds':time.monotonic()-started})
    save();print('HGT_SCENE_PMX_PASSED',model['name'],flush=True)

if args.legacy_project:
    bpy.ops.wm.open_mainfile(filepath=str(args.legacy_project.resolve()))
    scene=bpy.context.scene;root=scene.hgt_target
    assert root and root.hgt_character.managed and scene.hgt_model==root.hgt_character.source_root
    amount=sum(addon.workflow.current(o) for o in scene.objects)
    addon.workflow.apply_materials(root,bpy.context)
    assert amount==sum(addon.workflow.current(o) for o in scene.objects)
    scene.render.filepath=str(out/'output-canary.png')
    assert np.count_nonzero(render(out/'legacy-200.png')[:,3]>.5)>100
    report['checks']['legacy_200_project']=True
unload_addon(addon);mmd.unregister()
report['checks'].update(register_unregister=True,all_models=len(report['models'])==len(models),
                        packed_scene=any(m['packed_images']>0 for m in report['models']))
save();print('HGT_SCENE_PMX_COMPLETE',flush=True)
