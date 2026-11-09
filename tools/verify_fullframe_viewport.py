"""Real viewport camera alignment, native preview and undo/multiple views."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time
import traceback

import bpy
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from verification_runtime import file_hash,install_candidate,load_mmd
parser=argparse.ArgumentParser()
for name in ('output-dir','candidate','fixture','mmd-tools'):parser.add_argument('--'+name,type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
OUT=args.output_dir.resolve();assert OUT.is_relative_to(ROOT/'.verification')
OUT.mkdir(parents=True,exist_ok=True)
callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
@callback
def hide(hwnd,_):
    pid=ctypes.c_ulong();ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
    if pid.value==os.getpid():ctypes.windll.user32.ShowWindow(hwnd,0)
    return True
ctypes.windll.user32.EnumWindows(hide,0)
load_mmd(args.mmd_tools,OUT/'_runtime')
addon=install_candidate(args.candidate,OUT)
bpy.ops.wm.open_mainfile(filepath=str(args.fixture),load_ui=False)
payload=Path(addon.__file__).resolve().parent
report={'scope':'FULLFRAME-GLOW-VIEWPORT','complete':False,'checks':{},'camera_cases':[],
        'package_sha256':file_hash(args.candidate),'source_sha256':{p.name:file_hash(p) for p in payload.glob('*.py')}}
state={'phase':'start','case':0}
cases=[('center',0,(0,0)),('pan',0,(.12,-.08)),('zoom',25,(.12,-.08))]
window=area=space=reference=target=actual=None


def check(name,value):
    assert value,name
    report['checks'][name]=True


def route(socket):
    tree=bpy.context.scene.compositing_node_group
    tree.links.new(socket,target)
    for node in tree.nodes:
        if node.bl_idname=='CompositorNodeViewer' and node.get(addon.glow.VIEWER_TOKEN):
            tree.links.new(socket,node.inputs['Image'])


def capture(name,areas):
    path=OUT/(name+'.png')
    bpy.ops.screen.screenshot(filepath=str(path))
    image=bpy.data.images.load(str(path),check_existing=False)
    pixels=np.array(image.pixels[:],dtype=np.float32).reshape((image.size[1],image.size[0],4))
    bpy.data.images.remove(image)
    results=[]
    for current in areas:
        region=next(r for r in current.regions if r.type=='WINDOW')
        crop=pixels[region.y+8:region.y+region.height-8,region.x+8:region.x+region.width-8]
        mask=(crop[:,:,0]>.8)&(crop[:,:,1]>.15)&(crop[:,:,1]<.85)&(crop[:,:,2]<.5)
        y,x=np.nonzero(mask)
        assert len(x)>500,(name,len(x))
        results.append({'center':[float(x.mean()),float(y.mean())],'pixels':len(x)})
    return results


def finish(error=None):
    if error:report['error']=error
    (OUT/'viewport.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
    print('FULLFRAME_GLOW_VIEWPORT',report['complete'],len(report['checks']),report.get('error',''),flush=True)
    bpy.ops.wm.quit_blender()


def frame_pixels(name):
    path=OUT/(name+'.png');bpy.ops.screen.screenshot(filepath=str(path))
    image=bpy.data.images.load(str(path),check_existing=False)
    pixels=np.array(image.pixels[:],dtype=np.float32).reshape((image.size[1],image.size[0],4))
    bpy.data.images.remove(image)
    region=next(r for r in area.regions if r.type=='WINDOW')
    return pixels[region.y+8:region.y+region.height-8,region.x+8:region.x+region.width-8,:3]


def step():
    global window,area,space,reference,target,actual
    try:
        scene=bpy.context.scene
        phase=state['phase']
        if phase=='start':
            window=bpy.context.window_manager.windows[0]
            area=next(a for a in window.screen.areas if a.type=='VIEW_3D');space=area.spaces.active
            with bpy.context.temp_override(window=window,area=area):
                space.show_region_ui=False;space.show_region_toolbar=False
                space.overlay.show_overlays=False;space.show_gizmo=False
                space.shading.type='RENDERED';space.shading.use_compositor='ALWAYS'
                space.camera=scene.camera;space.region_3d.view_perspective='CAMERA'
            scene.render.film_transparent=False
            scene.objects['Dim'].hide_viewport=True
            emission=next(n for n in scene.objects['Bright'].active_material.node_tree.nodes if n.type=='EMISSION')
            emission.inputs['Color'].default_value=(3,.4,.05,1)
            scene.hgt_glow.mode='Bloom';scene.hgt_glow.strength=1;scene.hgt_glow.threshold=.85
            tree=scene.compositing_node_group;effect=addon.glow.node(scene)
            target=next(n for n in tree.nodes if n.type=='GROUP_OUTPUT' and n.is_active_output).inputs['Image']
            actual=effect.outputs['Image']
            reference=tree.nodes.new('CompositorNodeGlare')
            for name,value in {'Type':'Bloom','Quality':'Medium','Threshold':.85,'Smoothness':.1,
                               'Maximum':10.,'Strength':1.,'Size':scene.hgt_glow.size}.items():reference.inputs[name].default_value=value
            tree.links.new(effect.inputs['Image'].links[0].from_socket,reference.inputs['Image'])
            state['phase']='camera_setup';return 2
        if phase=='camera_setup':
            name,zoom,pan=cases[state['case']]
            space.region_3d.view_camera_zoom=zoom;space.region_3d.view_camera_offset=pan
            route(actual)
            area.tag_redraw();state['phase']='camera_actual';return 2
        if phase=='camera_actual':
            name=cases[state['case']][0]
            state['actual']=capture(name+'-actual',[area])[0]
            route(reference.outputs['Image'])
            area.tag_redraw();state['phase']='camera_reference';return 2
        if phase=='camera_reference':
            name=cases[state['case']][0]
            expected=capture(name+'-native',[area])[0]
            offset=[a-b for a,b in zip(state['actual']['center'],expected['center'])]
            check('camera-'+name,max(map(abs,offset))<3)
            report['camera_cases'].append({'case':name,'offset_px':offset})
            state['case']+=1
            if state['case']<len(cases):state['phase']='camera_setup';return .1
            route(actual)
            scene.compositing_node_group.nodes.remove(reference)
            space.region_3d.view_camera_zoom=0;space.region_3d.view_camera_offset=(0,0)
            scene.hgt_glow.threshold=0;scene.hgt_glow.strength=2
            area.tag_redraw();state['phase']='response_on';return 2
        if phase=='response_on':
            state['response_on']=frame_pixels('response-on')
            scene.hgt_glow.strength=0
            area.tag_redraw();state['phase']='response_off';return 2
        if phase=='response_off':
            difference=float(np.abs(state.pop('response_on')-frame_pixels('response-off')).mean())
            check('natural_viewport_parameter_response',difference>.002)
            report['viewport_parameter_response']=difference
            scene.hgt_glow.threshold=.85;scene.hgt_glow.strength=1
            addon.glow.disable(scene)
            with bpy.context.temp_override(window=window,area=area):
                addon.glow.viewport(bpy.context,False)
                space.shading.type='SOLID';space.shading.use_compositor='DISABLED'
                scene.hgt_model=None
                bpy.ops.ed.undo_push(message='Before native glow')
                assert bpy.ops.hgt.toggle_glow()=={'FINISHED'}
                bpy.ops.ed.undo_push(message='Native glow enabled')
            state['phase']='undo';return 1
        if phase=='undo':
            check('auto_preview_without_character',addon.glow.is_active(scene)
                  and (space.shading.type,space.shading.use_compositor)==('MATERIAL','ALWAYS'))
            with bpy.context.temp_override(window=window,area=area):bpy.ops.ed.undo()
            state['phase']='redo';return 1
        if phase=='redo':
            check('undo_restores_graph_and_viewport',not addon.glow.is_active(scene)
                  and (space.shading.type,space.shading.use_compositor)==('SOLID','DISABLED') and len(scene.view_layers)==1)
            with bpy.context.temp_override(window=window,area=area):bpy.ops.ed.redo()
            state['phase']='mode_undo';return 1
        if phase=='mode_undo':
            check('redo_restores_native_preview',addon.glow.is_active(scene)
                  and (space.shading.type,space.shading.use_compositor)==('MATERIAL','ALWAYS') and len(scene.view_layers)==1)
            with bpy.context.temp_override(window=window,area=area):
                scene.hgt_glow.mode='Streaks';bpy.ops.ed.undo_push(message='Native Streaks')
                scene.hgt_glow.mode='Ghosts';bpy.ops.ed.undo_push(message='Native Ghosts')
                bpy.ops.ed.undo()
            state['phase']='mode_redo';return 1
        if phase=='mode_redo':
            check('mode_undo',scene.hgt_glow.mode=='Streaks'
                  and addon.glow_modes.glare(addon.glow.node(scene)).inputs['Type'].default_value=='Streaks')
            with bpy.context.temp_override(window=window,area=area):bpy.ops.ed.redo()
            state['phase']='split';return 1
        if phase=='split':
            check('mode_redo',scene.hgt_glow.mode=='Ghosts'
                  and addon.glow_modes.glare(addon.glow.node(scene)).inputs['Type'].default_value=='Ghosts')
            with bpy.context.temp_override(window=window,area=area):bpy.ops.screen.area_split(direction='VERTICAL',factor=.5)
            for current in window.screen.areas:
                if current.type!='VIEW_3D':continue
                current.spaces.active.shading.type='RENDERED'
                current.spaces.active.shading.use_compositor='ALWAYS'
                current.spaces.active.overlay.show_overlays=False
                current.spaces.active.show_gizmo=False
                current.spaces.active.camera=scene.camera
                current.spaces.active.region_3d.view_perspective='CAMERA'
            state['phase']='finish';return 2
        views=[a for a in window.screen.areas if a.type=='VIEW_3D']
        images=capture('multiple-views',views)
        check('multiple_native_viewports',len(images)==2 and not scene.hgt_glow.error and len(scene.view_layers)==1)
        report['complete']=True;finish();return None
    except Exception:finish(traceback.format_exc());return None


bpy.app.timers.register(step,first_interval=2)
