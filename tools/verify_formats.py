"""Check both importer routes and mixed-format ownership using an installed ZIP."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from verification_runtime import copy_better,load_mmd,install_candidate,file_hash,unload_addon
from verification_data import source_snapshot,mmd_snapshot

parser=argparse.ArgumentParser()
for name in ('fbx-index','pmx-index','better-fbx','mmd-tools','candidate','output-dir'):
    parser.add_argument('--'+name,type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
project=Path(__file__).resolve().parents[1];out=args.output_dir.resolve()
assert out.is_relative_to(project/'.verification')
out.mkdir(parents=True,exist_ok=True)
better,_=copy_better(args.better_fbx,out/'_runtime')
mmd=load_mmd(args.mmd_tools,out/'_runtime')
addon=install_candidate(args.candidate,out)
fbx=json.loads(args.fbx_index.read_text(encoding='utf-8'))['models'][0]
pmx=json.loads(args.pmx_index.read_text(encoding='utf-8'))['models'][-1]
bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
batch_fbx=addon.workflow.importers.import_character(fbx['path'])
base_fbx=source_snapshot(batch_fbx)
first=addon.workflow.assemble(batch_fbx,bpy.context)
scene=bpy.context.scene

def pixels(path):
    image=bpy.data.images.load(str(path),check_existing=False)
    result=np.array(image.pixels[:],dtype=np.float32)
    bpy.data.images.remove(image)
    return result

scene.hgt_output.width,scene.hgt_output.height=320,480
scene.hgt_output.transparent=True
scene.hgt_output.filepath=str(out/'fbx-before.png')
addon.rendering.start(scene,first,invoke=False)
batch_pmx=addon.workflow.importers.import_character(pmx['path'])
base_pmx,metadata=source_snapshot(batch_pmx),mmd_snapshot(batch_pmx)
second=addon.workflow.assemble(batch_pmx,bpy.context)
assert first.hgt_character.source_format=='fbx' and second.hgt_character.source_format=='pmx'
assert first.hgt_character.uid!=second.hgt_character.uid
assert source_snapshot(batch_fbx)==base_fbx
scene.hgt_target=first
scene.hgt_output.filepath=str(out/'fbx-after.png')
addon.rendering.start(scene,first,invoke=False)
assert np.array_equal(pixels(out/'fbx-before.png'),pixels(out/'fbx-after.png')),'Second import affected FBX output'
scene.hgt_target=second
scene.hgt_output.filepath=str(out/'pmx.png')
addon.rendering.start(scene,second,invoke=False)
assert source_snapshot(batch_pmx)==base_pmx and mmd_snapshot(batch_pmx)==metadata
addon.workflow.restore(first)
assert second.hgt_character.managed
assert source_snapshot(batch_pmx)==base_pmx and mmd_snapshot(batch_pmx)==metadata
scene.hgt_output.filepath=str(out/'pmx-after-restore.png')
addon.rendering.start(scene,second,invoke=False)
assert np.array_equal(pixels(out/'pmx.png'),pixels(out/'pmx-after-restore.png'))
addon.workflow.restore(second)
assert source_snapshot(batch_fbx)==base_fbx and source_snapshot(batch_pmx)==base_pmx
assert mmd_snapshot(batch_pmx)==metadata
report={'package_sha256':file_hash(args.candidate),'checks':{'mixed_formats':True,
    'independent_render':True,'restore_isolated':True,'source_data_preserved':True,'mmd_metadata_preserved':True}}
(out/'formats.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
unload_addon(addon);mmd.unregister();better.unregister()
print('HGT_FORMATS_COMPLETE',flush=True)
