"""Exercise natural Bloom preview and undo in an isolated real UI window."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import traceback
import time

import bpy
import numpy as np

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--output-dir',type=Path,required=True)
parser.add_argument('--fixture',type=Path,required=True)
parser.add_argument('--candidate',type=Path)
parser.add_argument('--mmd-tools',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
OUT=args.output_dir.resolve()
assert OUT.is_relative_to(ROOT/'.verification')
OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'tools'))
from verification_runtime import load_addon,install_candidate,file_hash,load_mmd
callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
@callback
def hide(hwnd,_):
    pid=ctypes.c_ulong();ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
    if pid.value==os.getpid():ctypes.windll.user32.ShowWindow(hwnd,0)
    return True
ctypes.windll.user32.EnumWindows(hide,0)
load_mmd(args.mmd_tools,OUT/'_runtime')
addon=install_candidate(args.candidate,OUT) if args.candidate else load_addon(ROOT)
payload=Path(addon.__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(args.fixture),load_ui=False)
bpy.context.preferences.edit.use_global_undo=True
window=bpy.context.window_manager.windows[0]
area=next(a for a in window.screen.areas if a.type=='VIEW_3D')
space=area.spaces.active
initial=None
phase=-2
phase_wait=None
images={}
report={'complete':False,'scope':'GI-TOON-GLOW-UI','character_only':True,'checks':{},
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

def stats():
    record=addon.glow_preview._records.get(bpy.context.scene.as_pointer(),{})
    return {k:record.get(k) for k in ('draws','revision','milliseconds','prepared')}


def raw():
    record=addon.glow_preview._records[bpy.context.scene.as_pointer()]
    image=bpy.data.images[record['image']]
    width,height=image.size
    return np.array(image.pixels[:],dtype=np.float32).reshape((height,width,4))


def step():
    global phase,initial,phase_wait
    try:
        scene=bpy.context.scene
        if phase in {1,4,6,19}:
            if phase_wait is None or phase_wait[0]!=phase:phase_wait=(phase,time.perf_counter())
            record=addon.glow_preview._records.get(scene.as_pointer(),{})
            region=next(r for r in area.regions if r.type=='WINDOW')
            ready=record.get('key')==addon.glow_preview._key(scene,area,region,record)
            ready=ready and record.get('image') and not record.get('settle') and not record.get('dirty')
            if not ready:
                assert time.perf_counter()-phase_wait[1]<30, ('Preview did not settle',phase,scene.hgt_glow.error)
                return .1
        if phase==-2:
            with bpy.context.temp_override(window=window,area=area):
                space.show_region_ui=True
                space.shading.type='SOLID'
                space.shading.use_scene_world=True
                space.shading.use_scene_lights=True
                space.region_3d.view_perspective='CAMERA'
            initial=(space.shading.type,space.shading.use_compositor)
        elif phase==-1:
            with bpy.context.temp_override(window=window,area=area):
                next(r for r in area.regions if r.type=='UI').active_panel_category='GI-Toon'
        elif phase==0:
            scene.hgt_model=scene.objects['Subject A']
            with bpy.context.temp_override(window=window,area=area):
                bpy.ops.ed.undo_push(message='Before glow')
                assert bpy.ops.hgt.toggle_glow()=={'FINISHED'}
                bpy.ops.ed.undo_push(message='Glow enabled')
            assert (space.shading.type,space.shading.use_compositor)==('MATERIAL','ALWAYS')
            report['checks']['auto_preview']=True
        elif phase==1:
            images['on']=capture('on')
            images['raw-a']=raw()
            report['stationary_start']=stats()
        elif phase==2:
            assert stats()['draws']==report['stationary_start']['draws'], (stats(), report['stationary_start'])
            report['checks']['stationary_preview_uses_cache']=True
            scene.hgt_glow.strength=0
        elif phase==3:
            zero=capture('zero')
            report['natural_parameter_response']=float(np.abs(zero-images['on']).max())
            assert report['natural_parameter_response']>.01
            assert stats()['draws']==report['stationary_start']['draws'], (stats(), report['stationary_start'])
            report['checks']['parameters_do_not_redraw_character_source']=True
            report['checks']['natural_compositor_parameter_preview']=True
            scene.hgt_glow.strength=1
            scene.hgt_model=scene.objects['Subject B']
        elif phase==4:
            other=capture('other-character')
            report['natural_selection_response']=float(np.abs(other-images['on']).max())
            assert report['natural_selection_response']>.01
            a,b=images['raw-a'],raw()
            middle=a.shape[1]//2
            assert a[:,:middle,:3].max()>.5 and a[:,middle:,:3].max()==0
            assert b[:,:middle,:3].max()==0 and b[:,middle:,:3].max()>.5
            report['checks']['selected_character_only_and_switching']=True
            report['selection_draws']=stats()
        elif phase==5:
            assert stats()['draws']==report['selection_draws']['draws']
            emission=next(n for n in scene.objects['Dim'].data.materials[0].node_tree.nodes if n.type=='EMISSION')
            images['source-color']=tuple(emission.inputs['Color'].default_value)
            images['raw-b']=raw()
            emission.inputs['Color'].default_value=(.1,.2,.3,1)
        elif phase==6:
            changed=raw()
            assert changed[:,:,:3].max()<.5
            report['material_source_response']=float(np.abs(changed-images['raw-b']).max())
            assert report['material_source_response']>.1
            report['checks']['material_colour_refreshes_source_after_compilation']=True
            emission=next(n for n in scene.objects['Dim'].data.materials[0].node_tree.nodes if n.type=='EMISSION')
            emission.inputs['Color'].default_value=images['source-color']
        elif phase==7:
            with bpy.context.temp_override(window=window,area=area):bpy.ops.ed.undo()
        elif phase==8:
            assert not addon.panels.glow.is_active(scene)
            assert (space.shading.type,space.shading.use_compositor)==initial
            assert not scene.hgt_glow.source_collection and len(scene.view_layers)==1
            report['checks']['undo_graph_source_and_viewport']=True
            with bpy.context.temp_override(window=window,area=area):bpy.ops.ed.redo()
        elif phase==9:
            assert addon.panels.glow.is_active(scene)
            assert (space.shading.type,space.shading.use_compositor)==('MATERIAL','ALWAYS')
            report['checks']['redo_graph_and_viewport']=True
            with bpy.context.temp_override(window=window,area=area):bpy.ops.hgt.toggle_glow()
            assert (space.shading.type,space.shading.use_compositor)==initial
            report['checks']['off_restores_viewport']=True
        elif 10<=phase<18:
            with bpy.context.temp_override(window=window,area=area):
                assert bpy.ops.hgt.toggle_glow()=={'FINISHED'}
            if phase%2:
                assert not addon.glow_preview._records and len(scene.view_layers)==1
                assert not any(im.get(addon.glow_preview.TAG) for im in bpy.data.images)
            else:
                assert addon.panels.glow.is_active(scene)
        elif phase==18:
            report['checks']['four_preview_cycles_release_resources']=True
            if not hasattr(addon, 'glow_modes'):
                report['complete']=True
                finish();return None
            bpy.context.view_layer.objects.active=scene.objects['Bright']
            scene.hgt_model=scene.objects['Subject A']
            with bpy.context.temp_override(window=window,area=area):bpy.ops.hgt.toggle_glow()
            scene.hgt_glow.strength=0
        elif phase==19:
            images['mode-zero']=capture('mode-zero')
            report['mode_source_draws']=stats()['draws']
            scene.hgt_glow.strength=1
        elif 20<=phase<34:
            index=(phase-20)//2
            mode=addon.glow_modes.MODE_ITEMS[index][0]
            if phase%2==0:
                scene.hgt_glow.mode=mode
                assert not scene.hgt_glow.error,scene.hgt_glow.error
            else:
                pixels=capture('mode-'+mode.replace(' ','-'))
                response=float(np.abs(pixels-images['mode-zero']).max())
                assert response>.01,(mode,response)
                assert stats()['draws']==report['mode_source_draws'],(mode,stats())
                report.setdefault('mode_responses',{})[mode]=response
        elif phase==34:
            report['checks']['all_seven_modes_natural_preview']=len(report['mode_responses'])==7
            report['checks']['mode_switching_reuses_character_source']=True
            scene.hgt_glow.mode='Streaks'
            with bpy.context.temp_override(window=window,area=area):bpy.ops.ed.undo_push(message='Streaks mode')
            scene.hgt_glow.mode='Ghosts'
            with bpy.context.temp_override(window=window,area=area):bpy.ops.ed.undo_push(message='Ghosts mode')
            with bpy.context.temp_override(window=window,area=area):bpy.ops.ed.undo()
        elif phase==35:
            assert scene.hgt_glow.mode=='Streaks'
            assert addon.glow_modes.glare(addon.glow.node(scene)).inputs['Type'].default_value=='Streaks'
            with bpy.context.temp_override(window=window,area=area):bpy.ops.ed.redo()
        elif phase==36:
            assert scene.hgt_glow.mode=='Ghosts'
            assert addon.glow_modes.glare(addon.glow.node(scene)).inputs['Type'].default_value=='Ghosts'
            report['checks']['mode_undo_redo_keeps_selection_and_native_type']=True
            for _ in range(3):
                for mode,_,_ in addon.glow_modes.MODE_ITEMS:scene.hgt_glow.mode=mode
            with bpy.context.temp_override(window=window,area=area):bpy.ops.hgt.toggle_glow()
            assert not addon.glow_preview._records and len(scene.view_layers)==1
            assert not any(im.get(addon.glow_modes.IMAGE_TAG) for im in bpy.data.images)
            report['checks']['mode_cycles_release_kernel_and_preview']=True
            report['complete']=True
            finish();return None
        phase+=1
        return 2 if phase in {1,4,6,9,19,35,36} or 21<=phase<=33 and phase%2 else 1
    except Exception:
        finish(traceback.format_exc());return None
bpy.app.timers.register(step,first_interval=1)
