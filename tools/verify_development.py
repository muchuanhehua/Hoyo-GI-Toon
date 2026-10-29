"""Verify development modules 01–05 against private assets, in a factory process."""
import argparse
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch
from types import SimpleNamespace

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Euler
from verification_data import source_snapshot, mesh_data, digest
from verification_fixture import animated_fbx
from verification_assets import check_resolver
from verification_runtime import copy_better, load_addon, install_candidate, unload_addon

parser = argparse.ArgumentParser()
parser.add_argument('--assets-index', type=Path, required=True)
parser.add_argument('--better-fbx', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
parser.add_argument('--model-index', type=int, action='append')
parser.add_argument('--render', action='store_true')
parser.add_argument('--lifecycle', action='store_true')
parser.add_argument('--animation-fixture', action='store_true')
parser.add_argument('--addon-dir', type=Path)
parser.add_argument('--candidate', type=Path)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
project = Path(__file__).resolve().parents[1]
payload = (args.addon_dir or project).resolve()
out = args.output_dir.resolve()
out.mkdir(parents=True, exist_ok=True)
assert out.is_relative_to(project / '.verification')
index = json.loads(args.assets_index.read_text(encoding='utf-8'))
runtime = out / '_runtime'
runtime.mkdir(exist_ok=True)
os.environ['TEMP'] = os.environ['TMP'] = str(runtime)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_hashes(path):
    return {str(p.relative_to(path)):file_hash(p) for p in sorted(path.rglob('*')) if p.is_file()}


better, better_hashes = copy_better(args.better_fbx, runtime)
addon = install_candidate(args.candidate,out) if args.candidate else load_addon(payload)
payload = Path(addon.__file__).resolve().parent
report = {'scope':'01–05', 'blender':bpy.app.version_string,
          'better_fbx_version':list(better.bl_info['version']), 'better_fbx_sha256':better_hashes,
          'models':[], 'lifecycle':None}
report['package_sha256']=file_hash(args.candidate) if args.candidate else None


def write_report():
    report['source_sha256'] = {p.relative_to(payload).as_posix():file_hash(p) for p in sorted(payload.glob('*.py'))}
    report['resource_sha256'] = {p.relative_to(payload).as_posix():file_hash(p) for p in sorted((payload/'assets').iterdir()) if p.is_file()}
    report['verification_sha256']={p.relative_to(project).as_posix():file_hash(p) for p in (Path(__file__),project/'tools/verification_data.py',project/'tools/verification_fixture.py',project/'tools/verification_assets.py',project/'tools/verification_runtime.py')}
    (out / 'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def check_preservation(batch, baseline):
    current = source_snapshot(batch)
    if baseline != current:
        differences = [(category,key) for category, values in baseline.items()
                       for key, value in values.items() if current[category].get(key) != value]
        (out/'preservation-diff.json').write_text(json.dumps({'differences':differences,'baseline':baseline,'current':current},ensure_ascii=False,indent=2),encoding='utf-8')
        raise AssertionError(f'Imported data changed: {differences[:8]}')


def validate_materials(root, package):
    evidence = []
    for binding in root.hgt_character.bindings:
        material = binding.generated
        assert material.node_tree.nodes.get('Material Output').inputs['Surface'].is_linked
        textures = []
        for tree in addon.workflow.shaders.walk(material.node_tree):
            for node in tree.nodes:
                assert node.bl_idname != 'NodeUndefined', (tree.name,node.name)
                if node.type == 'TEX_IMAGE' and node.image:
                    image = node.image
                    path = Path(bpy.path.abspath(image.filepath)).resolve()
                    assert path.is_file() and path.is_relative_to(package)
                    role = node.get('hgt_texture_role')
                    data_roles = {'normal','normal_package','lightmap','face_sdf','specular_ramp',
                                  'eye_normal','eye_matcap','eye_highlight','stocking_detail',
                                  'silk_detail','shining_shape','facet_normal'}
                    expected = 'Non-Color' if role in data_roles else 'sRGB'
                    assert image.colorspace_settings.name == expected, (material.name,role,image.colorspace_settings.name)
                    assert image.alpha_mode == 'CHANNEL_PACKED'
                    textures.append({'role':role,'path':str(path.relative_to(package)),'colorspace':expected})
        assert any(t['role']=='diffuse' for t in textures), material.name
        evidence.append({'source':binding.source_name,'role':binding.role,'template':material['hgt_template'],
                         'textures':textures,'matches':json.loads(material['hgt_texture_matches'])})
    return evidence


def validate_derived(root, baseline):
    for entry in root.hgt_character.meshes:
        if not entry.original_data:
            continue
        before = baseline['meshes'][str(entry.original_data.as_pointer())]
        current = mesh_data(entry.object.data, set(before['uv']),set(before['colors']))
        assert before == current, f'Derived mesh changed geometry or attributes: {entry.object.name}'
        modifiers = [m for m in entry.object.modifiers if m.type=='NODES']
        names = [m.node_group for m in modifiers]
        assert names[-2:] == [root.hgt_character.light_vectors,root.hgt_character.outline_graph] or entry.object.name.split('.')[0] in {'Brow','Pupil','Face_Eye'}


def render(root, destination, azimuth):
    settings, scene = root.hgt_character, bpy.context.scene
    settings.light_azimuth = azimuth
    scene.hgt_output.width,scene.hgt_output.height = 512,768
    scene.hgt_output.filepath = str(destination)
    addon.rendering.start(scene,root)
    assert destination.is_file() and destination.stat().st_size > 1000
    image = bpy.data.images.load(str(destination),check_existing=False)
    pixels = np.asarray(image.pixels[:],dtype=np.float32).reshape((-1,4))
    visible = pixels[:,3] > 0.5
    assert visible.mean()>0.04, 'Blank render'
    assert ((pixels[visible,0]>.9)&(pixels[visible,2]>.9)&(pixels[visible,1]<.1)).mean()<.01, 'Missing-texture magenta'
    assert (np.ptp(pixels[visible,:3],axis=1)>.02).mean()>.05, 'Lost diffuse color'
    data = pixels.copy()
    bpy.data.images.remove(image)
    return data


def check_head(root):
    head = root.hgt_character.head
    constraint = head.constraints['Child Of']
    bone = constraint.target.pose.bones[constraint.subtarget]
    mode, rotation = bone.rotation_mode, bone.rotation_quaternion.copy()
    before = head.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()
    bone.rotation_mode='QUATERNION'
    bone.rotation_quaternion=Euler((.15,.25,.1)).to_quaternion()
    bpy.context.view_layer.update()
    after = head.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()
    assert before != after, 'Head reference did not follow bone'
    bone.rotation_quaternion=rotation
    bone.rotation_mode=mode
    bpy.context.view_layer.update()


for position in args.model_index or range(len(index['models'])):
    model = index['models'][position]
    path = Path(model['path']).resolve()
    print('HGT_START',model['name'],flush=True)
    start=time.monotonic()
    source_files=package_hashes(path.parent)
    bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
    batch = addon.workflow.importers.import_character(str(path))
    bpy.context.view_layer.update()
    baseline = source_snapshot(batch)
    imported_slots={obj:tuple(slot.material for slot in obj.material_slots) for obj in batch.meshes}
    visibility={obj:(obj.hide_render,obj.hide_get()) for obj in batch.meshes}
    model_dir=out / path.stem
    model_dir.mkdir(exist_ok=True)
    (model_dir/'baseline.json').write_text(json.dumps(baseline,ensure_ascii=False,indent=2),encoding='utf-8')
    bpy.ops.wm.save_as_mainfile(filepath=str(model_dir/'import.blend'),relative_remap=False)
    shared = batch.meshes[0].copy()
    shared.name='Verification shared data sentinel'
    bpy.context.scene.collection.objects.link(shared)
    shared.hide_render=True
    shared.hide_set(True)
    shared_data,shared_slots=shared.data,tuple(s.material for s in shared.material_slots)
    root = addon.workflow.assemble(batch,bpy.context)
    bpy.context.view_layer.update()
    check_preservation(batch,baseline)
    assert shared.data==shared_data and tuple(s.material for s in shared.material_slots)==shared_slots
    validate_derived(root,baseline)
    matches=validate_materials(root,path.parent)
    counts=addon.workflow.asset_tracking.data_pointers()
    assert addon.workflow.assemble(batch,bpy.context)==root
    for _ in range(10): addon.workflow.refresh_character(root)
    assert counts==addon.workflow.asset_tracking.data_pointers(), 'Repeated update created IDs'
    check_head(root)
    check_preservation(batch,baseline)
    renders=[]
    appearance={}
    if args.render and position in {0,1}:
        front=render(root,model_dir/'front.png',.65)
        side=render(root,model_dir/'side-light.png',-1.0)
        assert np.abs(front[:,:3]-side[:,:3]).max()>.02, 'Light direction has no render effect'
        renders=['front.png','side-light.png']
        root.hgt_character.light_azimuth=.65
        if position==0:
            body=next(b.generated for b in root.hgt_character.bindings if b.role=='body')
            node=body.node_tree.nodes['Body Shader']
            for key,label in (('Enable Metallics?','metal'),('Specular Multiplier','specular')):
                value=node.inputs[key].default_value
                assert value>0,(key,value)
                node.inputs[key].default_value=0
                variant=render(root,model_dir/(label+'-off.png'),.65)
                node.inputs[key].default_value=value
                delta=float(np.abs(front[:,:3]-variant[:,:3]).max())
                assert delta>.01,(label,'has no visual response',delta)
                appearance[label+'_response_max']=delta
            root.hgt_character.shadow_position=.8
            variant=render(root,model_dir/'shadow-shift.png',.65)
            root.hgt_character.shadow_position=.55
            appearance['shadow_response_max']=float(np.abs(front[:,:3]-variant[:,:3]).max())
            assert appearance['shadow_response_max']>.01
            root.hgt_character.outline=0
            thin=render(root,model_dir/'outline-off.png',.65)
            root.hgt_character.outline=.6
            thick=render(root,model_dir/'outline-wide.png',.65)
            root.hgt_character.outline=.25
            appearance['outline_response_max']=float(np.abs(thin-thick).max())
            assert appearance['outline_response_max']>.01
    bpy.ops.wm.save_as_mainfile(filepath=str(model_dir/'render.blend'),relative_remap=False)
    imported_materials={str(obj.as_pointer()):[s.material for s in obj.material_slots]
                        for obj in batch.meshes if not obj.data.get('hgt_owner')}
    original_mesh_refs={entry.object:entry.original_data for entry in root.hgt_character.meshes if entry.original_data}
    addon.workflow.restore(root)
    bpy.context.view_layer.update()
    check_preservation(batch,baseline)
    assert all(obj.data==original for obj,original in original_mesh_refs.items())
    assert all(tuple(s.material for s in obj.material_slots)==slots for obj,slots in imported_slots.items())
    assert all((obj.hide_render,obj.hide_get())==state for obj,state in visibility.items())
    assert all([s.material for s in obj.material_slots]==imported_materials[str(obj.as_pointer())]
               for obj in batch.meshes if str(obj.as_pointer()) in imported_materials)
    assert package_hashes(path.parent)==source_files, 'Source package changed'
    before_reapply={k:len(v) for k,v in addon.workflow.asset_tracking.data_pointers().items()}
    before_reapply_ids={k:{item.name:item.users for item in getattr(bpy.data,k)} for k in before_reapply}
    rebuilt=addon.workflow.assemble(batch,bpy.context)
    assert rebuilt==root,'Reassembly created a second root'
    addon.workflow.restore(root)
    after_reapply={k:len(v) for k,v in addon.workflow.asset_tracking.data_pointers().items()}
    if before_reapply!=after_reapply:
        (out/'restore-leak.json').write_text(json.dumps({'before':before_reapply_ids,
            'after':{k:{item.name:{'users':item.users,'owner':item.get('hgt_owner')} for item in getattr(bpy.data,k)} for k in before_reapply},
            'users':{item.name:[(type(user).__name__,user.name) for user in users] for item,users in bpy.data.user_map().items() if item.get('hgt_owner')==root.hgt_character.uid}},ensure_ascii=False,indent=2),encoding='utf-8')
        raise AssertionError(f'Restore/reassembly leaked data IDs: {before_reapply} -> {after_reapply}')
    check_preservation(batch,baseline)
    if position==0:
        before_failure=addon.workflow.asset_tracking.data_pointers()
        resolve=addon.workflow.AssetCatalog.resolve
        failures=[0]
        def assembly_fail(catalog,*a,**kw):
            failures[0]+=1
            if failures[0]==2: raise ValueError('Injected standalone assembly failure')
            return resolve(catalog,*a,**kw)
        with patch.object(addon.workflow.AssetCatalog,'resolve',assembly_fail):
            try: addon.workflow.assemble(batch,bpy.context)
            except ValueError as exc: assert str(exc)=='Injected standalone assembly failure'
            else: raise AssertionError('Standalone assembly failure was ignored')
        assert before_failure==addon.workflow.asset_tracking.data_pointers()
        assert all((obj.hide_render,obj.hide_get())==state for obj,state in visibility.items())
        check_preservation(batch,baseline)
    record={'name':model['name'],'objects':len(batch.objects),'meshes':len(batch.meshes),
            'armatures':len(batch.data['armatures']), 'actions':len(batch.data['actions']),
            'materials':len(matches),'parameters':batch.parameters,'matches':matches,
            'source_files_unchanged':len(source_files),'source_data_unchanged':True,
            'derived_geometry_unchanged':True,'original_mesh_refs_restored':True,
            'head_follow':True,'repeat_assembly':True,'restore_reassembly':True,'shared_data_preserved':True,
            'visibility_restored':True,'renders':renders,'seconds':round(time.monotonic()-start,2)}
    record['appearance_checks']=appearance
    if position==0: record['standalone_assembly_failure_restored']=True
    report['models'].append(record)
    write_report()
    print('HGT_MODEL_PASSED',model['name'],flush=True)

if args.lifecycle:
    bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
    first=addon.workflow.build(index['models'][0]['path'],bpy.context)
    first_groups={g for g in bpy.data.node_groups if g.get('hgt_owner')==first.hgt_character.uid}
    second=addon.workflow.build(index['models'][1]['path'],bpy.context)
    assert first_groups.isdisjoint({g for g in bpy.data.node_groups if g.get('hgt_owner')==second.hgt_character.uid})
    value=first.hgt_character.global_properties.nodes['Global Properties'].inputs['Shadow Position'].default_value
    second.hgt_character.shadow_position=.75
    second.hgt_character.outline=.4
    assert first.hgt_character.global_properties.nodes['Global Properties'].inputs['Shadow Position'].default_value==value
    bpy.context.view_layer.update()
    before=addon.workflow.asset_tracking.data_pointers()
    selected,active=tuple(bpy.context.selected_objects),bpy.context.view_layer.objects.active
    original=addon.workflow.AssetCatalog.resolve
    calls=[0]
    def fail(catalog,*a,**kw):
        calls[0]+=1
        if calls[0]==2: raise ValueError('Injected material assembly failure')
        return original(catalog,*a,**kw)
    with patch.object(addon.workflow.AssetCatalog,'resolve',fail):
        try: addon.workflow.build(index['models'][0]['path'],bpy.context)
        except ValueError as exc: assert str(exc)=='Injected material assembly failure'
        else: raise AssertionError('Injected failure was ignored')
    assert before==addon.workflow.asset_tracking.data_pointers(),'Failed build left IDs'
    assert set(selected)==set(bpy.context.selected_objects) and active==bpy.context.view_layer.objects.active
    # Import may return CANCELLED after partially creating data. Simulate both
    # cancellation and a FINISHED result with no mesh using the real RNA schema.
    real_operator=bpy.ops.better_import.fbx
    for status in ({'CANCELLED'},{'FINISHED'}):
        class PartialOperator:
            def get_rna_type(self): return real_operator.get_rna_type()
            def __call__(self,*a,**kw):
                obj=bpy.data.objects.new('Partial import',None)
                bpy.context.scene.collection.objects.link(obj)
                return status
        fake=SimpleNamespace(context=bpy.context,ops=SimpleNamespace(better_import=SimpleNamespace(fbx=PartialOperator())))
        with patch.object(addon.workflow.importers,'bpy',fake):
            try: addon.workflow.importers.import_character(index['models'][0]['path'])
            except (ValueError,RuntimeError): pass
            else: raise AssertionError('Invalid import result was accepted')
        assert before==addon.workflow.asset_tracking.data_pointers(),'Partial import was not rolled back'
    class Unregistered:
        def get_rna_type(self): raise RuntimeError('not registered')
    try: addon.workflow.importers.better_fbx_options(Path(index['models'][0]['path']),Unregistered())
    except RuntimeError as exc: assert 'Better FBX' in str(exc) and '启用' in str(exc)
    else: raise AssertionError('Missing dependency was ignored')
    addon.workflow.restore(second)
    assert all(g.as_pointer() for g in first_groups)
    assert first.hgt_character.managed
    # A render material explicitly used by an outside object must survive restore.
    adopted=first.hgt_character.bindings[0].generated
    mesh=bpy.data.meshes.new('Outside material user')
    mesh.from_pydata([(0,0,0),(1,0,0),(0,1,0)],[],[(0,1,2)])
    outsider=bpy.data.objects.new(mesh.name,mesh)
    bpy.context.scene.collection.objects.link(outsider)
    mesh.materials.append(adopted)
    addon.workflow.restore(first)
    assert outsider.material_slots[0].material==adopted and adopted.node_tree
    report['lifecycle']={'two_imports_isolated':True,'failure_rollback':True,'selection_restored':True,
                         'cancelled_import_rollback':True,'empty_import_rollback':True,'missing_dependency_error':True,
                         'adopted_material_preserved':True,
                         'other_character_survives_restore':True}
    write_report()
if args.animation_fixture:
    batch=animated_fbx(addon,index['models'][0]['path'],out/'animation-fixture')
    baseline=source_snapshot(batch)
    root=addon.workflow.assemble(batch,bpy.context)
    bpy.context.view_layer.update()
    check_preservation(batch,baseline)
    validate_derived(root,baseline)
    addon.workflow.restore(root)
    bpy.context.view_layer.update()
    check_preservation(batch,baseline)
    report['animation_fixture']={'actions':len(batch.data['actions']),'shapes':sum(len(o.data.shape_keys.key_blocks) if o.data.shape_keys else 0 for o in batch.meshes),
                                 'source_actions_preserved':True,'uv_color_normals_preserved':True}
    write_report()
report['resolver_checks']=check_resolver(importlib.import_module(addon.__name__+'.asset_resolver'),out)
write_report()
unload_addon(addon)
better.unregister()
shutil.rmtree(runtime)
print('HGT_01_05_COMPLETE',flush=True)
