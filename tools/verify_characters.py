"""Render any supplied character list with one candidate and uniform settings."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import traceback

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from verification_runtime import copy_better,install_candidate,unload_addon,file_hash
from verification_data import source_snapshot

parser=argparse.ArgumentParser()
parser.add_argument('--assets-index',type=Path,required=True)
parser.add_argument('--better-fbx',type=Path,required=True)
parser.add_argument('--candidate',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
project=Path(__file__).resolve().parents[1]
out=args.output_dir.resolve()
assert out.is_relative_to(project/'.verification')
out.mkdir(parents=True,exist_ok=True)
better,_=copy_better(args.better_fbx,out/'_runtime')
addon=install_candidate(args.candidate,out)
models=json.loads(args.assets_index.read_text(encoding='utf-8'))['models']
report={'package_sha256':file_hash(args.candidate),'conditions':{'size':[640,960],
        'background':[.06,.06,.06,1],'light_azimuths':[.65,-1.0],
        'shadow_position':.55,'outline':.25,'post_processing':False},'models':[]}


def package_hashes(folder):
    return {str(p.relative_to(folder)):file_hash(p) for p in folder.rglob('*') if p.is_file()}


def save_report():
    (out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


for model in models:
    path=Path(model['path']).resolve()
    record={'name':model['name'],'technical_checks_passed':False}
    report['models'].append(record)
    print('HGT_CHARACTER_START',model['name'],flush=True)
    try:
        files=package_hashes(path.parent)
        bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
        scene=bpy.context.scene
        world=bpy.data.worlds.new('Verification studio')
        world.use_nodes=True
        background=next(n for n in world.node_tree.nodes if n.type=='BACKGROUND')
        background.inputs['Color'].default_value=(.06,.06,.06,1)
        background.inputs['Strength'].default_value=1
        scene.world=world
        batch=addon.workflow.importers.import_character(str(path))
        bpy.context.view_layer.update()
        baseline=source_snapshot(batch)
        root=addon.workflow.assemble(batch,bpy.context)
        bpy.context.view_layer.update()
        assert source_snapshot(batch)==baseline,'Imported data changed during assembly'
        for binding in root.hgt_character.bindings:
            for tree in addon.workflow.shaders.walk(binding.generated.node_tree):
                assert all(node.bl_idname!='NodeUndefined' for node in tree.nodes)
        folder=out/model['name']
        folder.mkdir(exist_ok=True)
        scene.hgt_output.width,scene.hgt_output.height=640,960
        scene.hgt_output.transparent=False
        scene.hgt_output.post_processing=False
        root.hgt_character.shadow_position=.55
        root.hgt_character.outline=.25
        outputs=[]
        for name,azimuth in [('front',.65),('side-light',-1.0)]:
            root.hgt_character.light_azimuth=azimuth
            output=folder/(name+'.png')
            scene.hgt_output.filepath=str(output)
            addon.rendering.start(scene,root)
            image=bpy.data.images.load(str(output),check_existing=False)
            assert tuple(image.size)==(640,960)
            pixels=np.asarray(image.pixels[:],dtype=np.float32).reshape((-1,4)).copy()
            assert np.std(pixels[:,:3])>.03,'Blank render'
            assert ((pixels[:,0]>.9)&(pixels[:,2]>.9)&(pixels[:,1]<.1)).mean()<.01,'Missing-texture magenta'
            bpy.data.images.remove(image)
            outputs.append(pixels)
        assert np.abs(outputs[0][:,:3]-outputs[1][:,:3]).max()>.01,'Light direction has no visual response'
        root.hgt_character.light_azimuth=.65
        scene.hgt_output.filepath=str(folder/'front.png')
        bpy.ops.wm.save_as_mainfile(filepath=str(folder/'render.blend'),relative_remap=False)
        record.update({'objects':len(batch.objects),'meshes':len(batch.meshes),
                       'materials':len(root.hgt_character.bindings),'renders':['front.png','side-light.png']})
        addon.workflow.restore(root)
        bpy.context.view_layer.update()
        assert source_snapshot(batch)==baseline,'Imported data changed after rendering/restoration'
        assert package_hashes(path.parent)==files,'Source package changed'
        record.update({'technical_checks_passed':True,'source_files_unchanged':len(files),'source_data_preserved':True})
        print('HGT_CHARACTER_TECHNICAL_CHECKS_PASSED',model['name'],flush=True)
    except Exception:
        record['error']=traceback.format_exc()
        print(record['error'],flush=True)
    save_report()
unload_addon(addon)
better.unregister()
shutil.rmtree(out/'_runtime')
if not all(model['technical_checks_passed'] for model in report['models']):
    raise RuntimeError('Character verification failed; inspect verification.json')
print('HGT_THREE_CHARACTERS_COMPLETE',flush=True)
