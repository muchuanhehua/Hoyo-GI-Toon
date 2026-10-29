"""Compare the unchanged 0.5.3 shading and load its existing projects."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from verification_runtime import copy_better,load_mmd,load_addon,install_candidate,file_hash,unload_addon
from verification_data import mesh_data

parser=argparse.ArgumentParser()
for name in ('fbx-index','pmx-index','better-fbx','mmd-tools','output-dir','legacy-evidence'):
    parser.add_argument('--'+name,type=Path,required=True)
parser.add_argument('--addon-dir',type=Path)
parser.add_argument('--reference',type=Path)
parser.add_argument('--candidate',type=Path)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
args.legacy_evidence=args.legacy_evidence.resolve()
if args.reference:args.reference=args.reference.resolve()
project=Path(__file__).resolve().parents[1];out=args.output_dir.resolve()
assert out.is_relative_to(project/'.verification');out.mkdir(parents=True,exist_ok=True)
better,_=copy_better(args.better_fbx,out/'_runtime');mmd=load_mmd(args.mmd_tools,out/'_runtime')
addon=install_candidate(args.candidate,out) if args.candidate else load_addon(args.addon_dir or project)
payload=Path(addon.__file__).resolve().parent
report={'package_sha256':file_hash(args.candidate) if args.candidate else None,
        'source_sha256':{p.name:file_hash(p) for p in payload.glob('*.py')},'comparisons':[],'checks':{}}
fbx=json.loads(args.fbx_index.read_text(encoding='utf-8'))['models'][3]
pmx=json.loads(args.pmx_index.read_text(encoding='utf-8'))['models'][2]


def pixels(path):
    image=bpy.data.images.load(str(path),check_existing=False)
    result=np.array(image.pixels[:],dtype=np.float32).reshape((-1,4));bpy.data.images.remove(image)
    return result


def render(root,path):
    scene=bpy.context.scene
    scene.hgt_target=root;scene.hgt_output.camera=root.hgt_character.camera
    scene.hgt_output.width,scene.hgt_output.height=480,720
    scene.hgt_output.transparent=True;scene.hgt_output.post_processing=False
    scene.hgt_output.filepath=str(path);addon.rendering.start(scene,root)
    return pixels(path)


def compare(before,after):
    delta=np.abs(before-after)
    metrics={'changed_fraction':float(np.any(delta>0,axis=1).mean()),
             'mean_error':float(delta.mean()),'maximum_error':float(delta.max())}
    assert metrics['changed_fraction']<.001 and metrics['mean_error']<.00001,metrics
    assert np.array_equal(before[:,3],after[:,3]),'Baseline silhouette changed'
    return metrics


for format,model in [('fbx',fbx),('pmx',pmx)]:
    bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
    root=addon.workflow.build(model['path'],bpy.context)
    path=out/(format+'-fresh.png');current=render(root,path)
    if args.reference:
        metrics=compare(pixels(args.reference/(format+'-fresh.png')),current)
        report['comparisons'].append({'source_format':format,'unchanged_shading':True,'pixels':metrics})
    addon.workflow.restore(root)
    if not args.reference:continue
    bpy.ops.wm.open_mainfile(filepath=str(args.legacy_evidence/f'candidate-053-{format}'/model['name']/'render.blend'))
    root=bpy.context.scene.hgt_target;settings=root.hgt_character
    assert settings.parts_version==0 and not len(settings.parts)
    assert not addon.panels.HGT_PT_parts.poll(bpy.context)
    originals={e.object:e.original_data for e in settings.meshes if e.original_data}
    source={o:mesh_data(data) for o,data in originals.items()}
    visibility={e.object:(e.object.hide_render,e.object.hide_get()) for e in settings.meshes}
    first=render(root,out/(format+'-legacy.png'))
    assert visibility=={o:(o.hide_render,o.hide_get()) for o in visibility}
    second=render(root,out/(format+'-legacy-repeat.png'))
    assert np.array_equal(first,second)
    addon.workflow.restore(root)
    assert all(o.data==data and mesh_data(data)==source[o] for o,data in originals.items())
    report['checks'][format+'_legacy_load_render_restore']=True

unload_addon(addon);mmd.unregister();better.unregister()
report['checks']['register_unregister']=True
(out/'baseline.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('HGT_SUBJECT_BASELINE_COMPLETE',flush=True)
