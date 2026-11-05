"""Exercise natural Bloom preview and undo in an isolated real UI window."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import traceback

import bpy
import numpy as np

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--output-dir',type=Path,required=True)
parser.add_argument('--fixture',type=Path,required=True)
parser.add_argument('--candidate',type=Path)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
OUT=args.output_dir.resolve()
assert OUT.is_relative_to(ROOT/'.verification')
OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'tools'))
from verification_runtime import load_addon,install_candidate,file_hash
callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
@callback
def hide(hwnd,_):
    pid=ctypes.c_ulong();ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
    if pid.value==os.getpid():ctypes.windll.user32.ShowWindow(hwnd,0)
    return True
ctypes.windll.user32.EnumWindows(hide,0)
addon=install_candidate(args.candidate,OUT) if args.candidate else load_addon(ROOT)
payload=Path(addon.__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(args.fixture),load_ui=False)
bpy.context.preferences.edit.use_global_undo=True
window=bpy.context.window_manager.windows[0]
area=next(a for a in window.screen.areas if a.type=='VIEW_3D')
space=area.spaces.active
initial=None
phase=-2
images={}
report={'complete':False,'scope':'GI-TOON-GLOW-UI','checks':{},
        'source_sha256':{p.name:file_hash(p) for p in payload.glob('*.py')},
        'package_sha256':file_hash(args.candidate) if args.candidate else None}

def capture(name):
    bpy.ops.screen.screenshot(filepath=str(OUT/(name+'.png')))
    image=bpy.data.images.load(str(OUT/(name+'.png')),check_existing=False)
    width,height=image.size
    data=np.array(image.pixels[:],dtype=np.float32).reshape((height,width,4))
    bpy.data.images.remove(image)
    region=next(r for r in area.regions if r.type=='UI')
    right=region.x if region.x>area.x else area.x+area.width-300
    return data[area.y+50:area.y+area.height-50,area.x+70:right-10].copy()

def finish(error=None):
    if error:report['error']=error
    assert report['source_sha256']=={p.name:file_hash(p) for p in payload.glob('*.py')}
    (OUT/'ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
    print('HGT_GLOW_UI',report,flush=True)
    bpy.ops.wm.quit_blender()

def step():
    global phase,initial
    try:
        if phase==-2:
            with bpy.context.temp_override(window=window,area=area):
                area.spaces.active.show_region_ui=True
                space.shading.type='SOLID'
                space.shading.use_scene_world=True
                space.shading.use_scene_lights=True
                space.region_3d.view_perspective='CAMERA'
            initial=(space.shading.type,space.shading.use_compositor)
        elif phase==-1:
            with bpy.context.temp_override(window=window,area=area):
                next(r for r in area.regions if r.type=='UI').active_panel_category='GI-Toon'
        elif phase==0:
            with bpy.context.temp_override(window=window,area=area):
                bpy.ops.ed.undo_push(message='Before glow')
                assert bpy.ops.hgt.toggle_glow()=={'FINISHED'}
                bpy.ops.ed.undo_push(message='Glow enabled')
            assert (space.shading.type,space.shading.use_compositor)==('MATERIAL','ALWAYS')
            report['checks']['auto_preview']=True
        elif phase==1:
            images['on']=capture('on')
            bpy.context.scene.hgt_glow.strength=0
        elif phase==2:
            zero=capture('zero')
            report['natural_parameter_response']=float(np.abs(zero-images['on']).max())
            assert report['natural_parameter_response']>.01
            report['checks']['natural_compositor_parameter_preview']=True
            with bpy.context.temp_override(window=window,area=area):bpy.ops.ed.undo()
        elif phase==3:
            assert not addon.panels.glow.is_active(bpy.context.scene)
            report['undo_viewport']=[space.shading.type,space.shading.use_compositor]
            assert (space.shading.type,space.shading.use_compositor)==initial
            report['checks']['undo_graph_and_viewport']=True
            with bpy.context.temp_override(window=window,area=area):bpy.ops.ed.redo()
        elif phase==4:
            assert addon.panels.glow.is_active(bpy.context.scene)
            assert (space.shading.type,space.shading.use_compositor)==('MATERIAL','ALWAYS')
            report['checks']['redo_graph_and_viewport']=True
            with bpy.context.temp_override(window=window,area=area):bpy.ops.hgt.toggle_glow()
            assert (space.shading.type,space.shading.use_compositor)==initial
            report['checks']['off_restores_viewport']=True
            report['complete']=True
            finish();return None
        phase+=1
        return 3 if phase==1 else 1
    except Exception:
        finish(traceback.format_exc());return None
bpy.app.timers.register(step,first_interval=1)
