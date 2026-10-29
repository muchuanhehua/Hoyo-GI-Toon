"""22–34: native reference fixtures, cross-format close-ups and source protection."""
import argparse
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Vector
from verification_runtime import copy_better,load_mmd,load_addon,install_candidate,unload_addon,file_hash
from verification_data import source_snapshot,mmd_snapshot,mesh_data
from verification_materials import fixtures,pixels,compare

parser=argparse.ArgumentParser()
for key in ('fbx-index','pmx-index','better-fbx','mmd-tools','reference-shader','output-dir'):
    parser.add_argument('--'+key,type=Path,required=True)
for key in ('candidate','baseline-fbx','baseline-pmx'):parser.add_argument('--'+key,type=Path)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
for key,value in vars(args).items():
    if isinstance(value,Path):setattr(args,key,value.resolve())
project=Path(__file__).resolve().parents[1];out=args.output_dir
assert out.is_relative_to(project/'.verification');out.mkdir(parents=True,exist_ok=True)
better,_=copy_better(args.better_fbx,out/'_runtime');mmd=load_mmd(args.mmd_tools,out/'_runtime')
addon=install_candidate(args.candidate,out) if args.candidate else load_addon(project)
payload=Path(addon.__file__).resolve().parent
code={p.name:file_hash(p) for p in payload.glob('*.py')}
resources={p.relative_to(payload).as_posix():file_hash(p) for p in (payload/'assets').iterdir() if p.is_file()}
report={'scope':'22–34','package_sha256':file_hash(args.candidate) if args.candidate else None,
        'source_sha256':code,'resource_sha256':resources,'models':[],'checks':{},
        'native_reference_sha256':file_hash(args.reference_shader),'visual_acceptance':'pending_user_review'}
fbx=json.loads(args.fbx_index.read_text(encoding='utf-8'))['models']
pmx=json.loads(args.pmx_index.read_text(encoding='utf-8'))['models']
references={m['name']:m.get('references',[]) for m in fbx}


def save():
    assert code=={p.name:file_hash(p) for p in payload.glob('*.py')},'Runtime changed during verification'
    assert resources=={p.relative_to(payload).as_posix():file_hash(p) for p in (payload/'assets').iterdir() if p.is_file()}
    (out/'materials.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def files(folder):
    return {p.relative_to(folder).as_posix():file_hash(p) for p in folder.rglob('*') if p.is_file()}


def camera(scene,root,view):
    settings=scene.hgt_output
    settings.width,settings.height=640,960
    if view=='front':
        settings.camera=root.hgt_character.camera
        return
    positions=[]
    face_mats={b.generated for b in root.hgt_character.bindings if b.role in {'face','eye','brow'}}
    for entry in root.hgt_character.meshes:
        if not entry.render_data or entry.object.hide_render:continue
        obj=entry.object;indices={i for i,s in enumerate(obj.material_slots) if s.material in face_mats}
        vertices={v for p in obj.data.polygons if p.material_index in indices for v in p.vertices}
        positions.extend(obj.matrix_world@obj.data.vertices[v].co for v in vertices)
    assert positions,'No face surfaces for common close-up'
    low=Vector(tuple(min(p[i] for p in positions) for i in range(3)))
    high=Vector(tuple(max(p[i] for p in positions) for i in range(3)))
    center=(low+high)*.5;size=max(high.x-low.x,high.z-low.z)*1.45
    angle=math.radians(18) if view=='head-turn' else 0
    if view=='torso':
        bottom,top=addon.rendering.character_bounds(root)
        center=(bottom+top)*.5;center.z=bottom.z+(top.z-bottom.z)*.67;size=(top.z-bottom.z)*.55
    review=next((o for o in scene.objects if o.get('hgt_material_review') and o.get('hgt_owner')==root.hgt_character.uid),None)
    if review is None:
        review=root.hgt_character.camera.copy();review.data=review.data.copy()
        review['hgt_material_review']=True;scene.collection.objects.link(review)
    review.data.ortho_scale=size
    review.location=center+Vector((math.sin(angle),-math.cos(angle),0))
    review.rotation_euler=(center-review.location).to_track_quat('-Z','Y').to_euler()
    settings.camera=review;settings.width=settings.height=768


def render(scene,root,path,view='front'):
    camera(scene,root,view)
    scene.hgt_output.filepath=str(path);scene.hgt_output.transparent=True
    scene.hgt_output.post_processing=False
    before=addon.workflow.asset_tracking.data_pointers()
    original=addon.workflow.asset_tracking.scene_state(bpy.context)
    addon.rendering.start(scene,root)
    after=addon.workflow.asset_tracking.data_pointers()
    after['images']-={i.as_pointer() for i in bpy.data.images if i.type=='RENDER_RESULT' and i.as_pointer() not in before['images']}
    assert before==after,'Render leaked data IDs'
    assert all(getattr(owner,key)==value for owner,key,value in original),'Source scene changed'
    values=pixels(path)
    assert values[:,:3].std()>.02 and (values[:,3]>.5).mean()>.04,'Blank output'
    assert ((values[:,0]>.9)&(values[:,1]<.1)&(values[:,2]>.9)).mean()<.002,'Missing texture'
    assert scene.hgt_output.last_render==str(path)
    return values


report['fixtures']=fixtures(addon,args.reference_shader,out/'fixtures')
save()
for format,models,baseline_dir in (('fbx',fbx,args.baseline_fbx),('pmx',pmx,args.baseline_pmx)):
    for model in models:
        print('HGT_MATERIAL_START',format,model['name'],flush=True)
        folder=out/format/model['name'];folder.mkdir(parents=True,exist_ok=True)
        before_images={}
        old=baseline_dir/model['name']/'render.blend' if baseline_dir else None
        if old and old.is_file():
            bpy.ops.wm.open_mainfile(filepath=str(old))
            root=bpy.context.scene.hgt_target
            for view in ('front','head','head-turn','torso'):
                before_images[view]=render(bpy.context.scene,root,folder/('baseline-'+view+'.png'),view)
        bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
        path=Path(model['path']);source_files=files(path.parent)
        refs={r['path']:file_hash(r['path']) for r in references.get(model['name'],[])}
        batch=addon.workflow.importers.import_character(str(path));bpy.context.view_layer.update()
        baseline=source_snapshot(batch);metadata=mmd_snapshot(batch) if format=='pmx' else None
        root=addon.workflow.assemble(batch,bpy.context);scene=bpy.context.scene
        bpy.context.view_layer.update();assert source_snapshot(batch)==baseline
        mats=[]
        for binding in root.hgt_character.bindings:
            mat=binding.generated;features=json.loads(mat['hgt_features'])
            overlay=mat.get('hgt_eye_overlay')
            if features['layered_eye']:
                assert overlay and overlay.surface_render_method=='BLENDED'
                assert mat.surface_render_method=='DITHERED'
                assert any(mod.type=='NODES' and mod.node_group.get('hgt_eye_surfaces')
                           for e in root.hgt_character.meshes if mat in e.object.data.materials[:] for mod in e.object.modifiers)
            for item in (mat,overlay):
                if item is None:continue
                assert item.get('hgt_owner')==root.hgt_character.uid
                for tree in addon.workflow.shaders.walk(item.node_tree):
                    assert not any(n.bl_idname=='NodeUndefined' for n in tree.nodes)
            mats.append({'source':binding.source_name,'role':binding.role,'features':features,
                         'textures':json.loads(mat['hgt_texture_matches']),'independent_highlight':bool(overlay)})
        for entry in root.hgt_character.meshes:
            if not entry.original_data:continue
            original=baseline['meshes'][str(entry.original_data.as_pointer())]
            assert mesh_data(entry.render_data,set(original['uv']),set(original['colors']))==original
            marker=entry.render_data.attributes.get(addon.workflow.surface_layers.EXPRESSION_MASK)
            if marker and any(item.value>.5 for item in marker.data):
                assert any(mod.type=='NODES' and mod.node_group.get('hgt_expression_surfaces') for mod in entry.object.modifiers)
                evaluated=entry.object.evaluated_get(bpy.context.evaluated_depsgraph_get())
                evaluated_mesh=evaluated.to_mesh()
                try:
                    active=evaluated_mesh.attributes.get(marker.name)
                    assert active is None or not any(item.value>.5 for item in active.data),'Inactive expressions entered depth'
                    assert len(evaluated_mesh.polygons)>0
                finally:evaluated.to_mesh_clear()
        responses={};differences={};images={}
        for view in ('front','head','head-turn','torso'):
            images[view]=render(scene,root,folder/(view+'.png'),view)
            if view in before_images:differences[view]=compare(before_images[view],images[view])
        root.hgt_character.light_azimuth=-1
        side=render(scene,root,folder/'side-light.png')
        assert np.abs(side-images['front']).max()>.01
        root.hgt_character.light_azimuth=.35
        for feature in ('stockings','silk','shining','reflection','height_normal'):
            controls=[]
            for binding in root.hgt_character.bindings:
                for node in binding.generated.node_tree.nodes:
                    if node.get('hgt_material_module')==feature:controls.append(node.inputs[0])
                    elif feature=='reflection' and binding.generated.get('hgt_reflection_mask') and node.get('hgt_feature_switch'):
                        controls.append(node.inputs[0])
                    elif feature=='height_normal' and node.name=='HGT • Packed Height Normal':controls.append(node.inputs['Strength'])
            if not controls:continue
            values=[s.default_value for s in controls]
            for s in controls:s.default_value=0
            variant=render(scene,root,folder/(feature+'-off.png'))
            for s,v in zip(controls,values):s.default_value=v
            responses[feature]=compare(images['front'],variant)
            assert responses[feature]['maximum']>.002,(model['name'],feature,'No visible feature response')
        for entry in root.hgt_character.meshes:
            if not entry.original_data:continue
            target=next((Path(i.filepath) for i in bpy.data.images if i.source=='FILE' and i.filepath
                         and Path(i.filepath).suffix.lower()=='.png' and Path(i.filepath).is_file()),None)
            if target is None:target=path.parent/'hgt-protected-output.png'
            if target:
                scene.hgt_output.filepath=str(target);ids=addon.workflow.asset_tracking.data_pointers()
                try:addon.rendering.start(scene,root)
                except ValueError as exc:assert '资产目录' in str(exc) or '已有贴图' in str(exc)
                else:raise AssertionError('Source image accepted as render output')
                assert ids==addon.workflow.asset_tracking.data_pointers()
                break
        camera(scene,root,'front');scene.hgt_output.filepath=str(folder/'front.png')
        bpy.ops.wm.save_as_mainfile(filepath=str(folder/'render.blend'),relative_remap=False)
        addon.workflow.restore(root);bpy.context.view_layer.update()
        assert source_snapshot(batch)==baseline
        if metadata is not None:assert mmd_snapshot(batch)==metadata
        assert files(path.parent)==source_files and refs=={p:file_hash(p) for p in refs}
        report['models'].append({'name':model['name'],'format':format,'era':model.get('era',''),
            'source_files_unchanged':len(source_files),'source_data_unchanged':True,'derived_geometry_unchanged':True,
            'restore_verified':True,'mmd_metadata_preserved':True,'source_output_protected':True,
            'expression_depth_filtered':True,
            'render_resources_clean':True,'game_references_unchanged':True,'references':refs,'materials':mats,
            'baseline_difference':differences,'feature_response':responses,'views':list(images)+['side-light']})
        save();print('HGT_MATERIAL_PASSED',format,model['name'],flush=True)
unload_addon(addon);mmd.unregister();better.unregister()
report['checks']={'native_reference_fixtures':True,'cross_format_matrix':True,'source_protection':True,
                  'register_unregister':True,'png_matches_recorded_conditions':True}
save();print('HGT_MATERIAL_PIPELINE_COMPLETE',flush=True)
