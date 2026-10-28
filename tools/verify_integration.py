"""Verify output isolation and reload using the current source or an installed ZIP."""
import argparse
import importlib
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
from verification_runtime import copy_better,load_addon,install_candidate,file_hash,unload_addon
from verification_data import mesh_data,matrix

parser=argparse.ArgumentParser()
parser.add_argument('--assets-index',type=Path,required=True)
parser.add_argument('--better-fbx',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True)
parser.add_argument('--candidate',type=Path)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
project=Path(__file__).resolve().parents[1]
out=args.output_dir.resolve()
assert out.is_relative_to(project/'.verification')
out.mkdir(parents=True,exist_ok=True)
runtime=out/'_runtime'
better,_=copy_better(args.better_fbx,runtime)
addon=install_candidate(args.candidate,out) if args.candidate else load_addon(project)
payload=Path(addon.__file__).resolve().parent
index=json.loads(args.assets_index.read_text(encoding='utf-8'))
checks={}
report={'scope':'06–08','integration_checks':checks,'package_sha256':file_hash(args.candidate) if args.candidate else None,
        'source_sha256':{p.relative_to(payload).as_posix():file_hash(p) for p in payload.glob('*.py')},
        'resource_sha256':{p.relative_to(payload).as_posix():file_hash(p) for p in (payload/'assets').iterdir() if p.is_file()}}


def save_report():
    (out/'integration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def scene_snapshot(scene):
    return {'camera':scene.camera.name if scene.camera else None,
            'camera_data':{'matrix':matrix(scene.camera.matrix_world),'lens':scene.camera.data.lens} if scene.camera else None,
            'engine':scene.render.engine,'size':(scene.render.resolution_x,scene.render.resolution_y,scene.render.resolution_percentage),
            'transparent':scene.render.film_transparent,'path':scene.render.filepath,
            'format':scene.render.image_settings.file_format,'world':scene.world.name if scene.world else None,
            'compositor':scene.compositing_node_group.name if scene.compositing_node_group else None,
            'links':[(l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier)
                     for l in scene.compositing_node_group.links] if scene.compositing_node_group else [],
            'lamp':[(o.name,matrix(o.matrix_world),o.data.energy) for o in scene.objects if o.type=='LIGHT']}


def semantic_snapshot(root):
    return {'uid':root.hgt_character.uid,
            'meshes':{entry.object.name:{'original':entry.original_data.name,'data':mesh_data(entry.original_data)}
                      for entry in root.hgt_character.meshes if entry.original_data},
            'materials':[(b.source.name,b.generated.name,b.outline.name) for b in root.hgt_character.bindings],
            'camera':root.hgt_character.camera.name}


def pixels(path):
    image=bpy.data.images.load(str(path),check_existing=False)
    data=np.asarray(image.pixels[:],dtype=np.float32).reshape((-1,4)).copy()
    size=tuple(image.size)
    bpy.data.images.remove(image)
    assert size==(448,672),size
    assert ((data[:,0]>.9)&(data[:,2]>.9)&(data[:,1]<.1)&(data[:,3]>.5)).mean()<.01
    return data


bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
scene=bpy.context.scene
camera=bpy.data.objects.new('Existing camera',bpy.data.cameras.new('Existing camera'))
scene.collection.objects.link(camera)
camera.location=(3,4,5)
camera.data.lens=71
scene.camera=camera
lamp=bpy.data.objects.new('Existing lamp',bpy.data.lights.new('Existing lamp','SUN'))
lamp.data.energy=.37
scene.collection.objects.link(lamp)
scene.render.engine='CYCLES'
scene.render.resolution_x,scene.render.resolution_y,scene.render.resolution_percentage=321,456,77
scene.render.filepath='//unchanged-output'
scene.render.image_settings.file_format='JPEG'
scene.render.film_transparent=False
tree=bpy.data.node_groups.new('Existing compositor','CompositorNodeTree')
tree.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
layers=tree.nodes.new('CompositorNodeRLayers')
layers.scene=scene
gamma=tree.nodes.new('CompositorNodeBrightContrast')
output=tree.nodes.new('NodeGroupOutput')
tree.links.new(layers.outputs['Image'],gamma.inputs['Image'])
tree.links.new(gamma.outputs['Image'],output.inputs['Image'])
scene.compositing_node_group=tree
bpy.context.view_layer.update()
original_scene=scene_snapshot(scene)
assert bpy.ops.hgt.import_character(filepath=index['models'][0]['path'])=={'FINISHED'}
root=scene.hgt_target
uid=root.hgt_character.uid
assert scene_snapshot(scene)==original_scene,'Import changed user scene settings'
settings=scene.hgt_output
framing=[]
for width,height in ((448,672),(672,448)):
    settings.width,settings.height=width,height
    assert bpy.ops.hgt.frame_camera()=={'FINISHED'}
    job=addon.rendering._proxy(scene,root,out/'framing.png')
    low,high=addon.rendering.character_bounds(root)
    projected=[world_to_camera_view(job.proxy,settings.camera,Vector((x,y,z)))
               for x in (low.x,high.x) for y in (low.y,high.y) for z in (low.z,high.z)]
    assert all(.02<p.x<.98 and .02<p.y<.98 and p.z>0 for p in projected),[(list(p)) for p in projected]
    framing.append({'size':[width,height],'x':[min(p.x for p in projected),max(p.x for p in projected)],
                    'y':[min(p.y for p in projected),max(p.y for p in projected)]})
    bpy.data.batch_remove(ids=job.resources)
checks['camera_framing']=True
report['framing']=framing
settings.width,settings.height=448,672
renders={}
for name,transparent,post in (('transparent',True,False),('opaque',False,False),('post',True,True)):
    settings.transparent,settings.post_processing=transparent,post
    path=out/(name+'.png')
    settings.filepath=str(path)
    before_scenes=set(bpy.data.scenes)
    before_groups=set(bpy.data.node_groups)
    assert bpy.ops.hgt.render()=={'FINISHED'}
    data=pixels(path)
    assert set(bpy.data.scenes)==before_scenes and set(bpy.data.node_groups)==before_groups,'Temporary render data leaked'
    assert scene_snapshot(scene)==original_scene,'Render changed the source scene'
    assert not addon.rendering._JOBS and not settings.rendering
    if transparent:
        assert (data[:,3]<.01).mean()>.05 and (data[:,3]>.5).mean()>.05
    else:
        assert data[:,3].min()>.999,'Opaque output has transparent pixels'
    renders[name]=data
assert np.abs(renders['transparent'][:,3]-renders['post'][:,3]).max()<1e-5,'Post-processing changed Alpha'
checks.update({'scene_preserved':True,'transparent_alpha':True,'post_alpha':True,'render_save':True})
report['post_rgb_response_max']=float(np.abs(renders['transparent'][:,:3]-renders['post'][:,:3]).max())

# Resource errors must clean up a scene copy created before the failure.
before=addon.asset_tracking.data_pointers() if hasattr(addon,'asset_tracking') else addon.workflow.asset_tracking.data_pointers()
settings.post_processing=True
with patch.object(addon.rendering.post_processing,'configure',side_effect=ValueError('Injected compositor failure')):
    try: addon.rendering.start(scene,root)
    except ValueError as exc: assert str(exc)=='Injected compositor failure'
    else: raise AssertionError('Compositor failure was ignored')
assert before==addon.workflow.asset_tracking.data_pointers()
assert not settings.rendering and not addon.rendering._JOBS
bad=out/'directory.png'
bad.mkdir(exist_ok=True)
settings.filepath=str(bad)
try: addon.rendering.start(scene,root)
except ValueError: pass
else: raise AssertionError('Directory accepted as output file')
checks['errors_and_cleanup']=True

settings.filepath=str(out/'after-reload.png')
settings.post_processing=False
expected=semantic_snapshot(root)
expected_settings=(settings.width,settings.height,settings.filepath,settings.transparent,settings.camera.name)
for _ in range(2):
    addon.unregister()
    addon.register()
assert len([h for h in bpy.app.handlers.render_complete if h==addon.rendering.render_complete])==1
assert len([h for h in bpy.app.handlers.depsgraph_update_post if h==addon.workflow.update_scene])==1
checks['register_unregister']=True
bpy.ops.wm.save_as_mainfile(filepath=str(out/'integration.blend'),relative_remap=False)
bpy.ops.wm.open_mainfile(filepath=str(out/'integration.blend'))
scene=bpy.context.scene
root=next(obj for obj in scene.objects if obj.hgt_character.uid==uid)
assert expected==semantic_snapshot(root),'Saved original data references changed'
settings=scene.hgt_output
assert expected_settings==(settings.width,settings.height,settings.filepath,settings.transparent,settings.camera.name)
assert scene_snapshot(scene)==original_scene
assert bpy.ops.hgt.render()=={'FINISHED'}
pixels(out/'after-reload.png')
assert scene_snapshot(scene)==original_scene
checks['save_reload']=True
checks['fresh_package_process']=bool(args.candidate)
save_report()
unload_addon(addon)
better.unregister()
shutil.rmtree(runtime)
print('HGT_INTEGRATION_COMPLETE',flush=True)
