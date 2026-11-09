"""Historical 2.9 character-cache alignment; current checks use verify_fullframe_viewport.py."""
import argparse,ctypes,json,os,sys,time,traceback
from pathlib import Path
import bpy
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--output-dir',type=Path,required=True)
parser.add_argument('--fixture',type=Path,required=True)
parser.add_argument('--mmd-tools',type=Path,required=True)
parser.add_argument('--candidate',type=Path)
parser.add_argument('--case',action='append')
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
OUT=args.output_dir.resolve();assert OUT.is_relative_to(ROOT/'.verification')
OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'tools'))
from verification_runtime import load_addon,load_mmd,file_hash,install_candidate
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
scene=bpy.context.scene;scene.hgt_model=scene.objects['Subject A']
scene.objects['Dim'].hide_viewport=True
emission=next(n for n in scene.objects['Bright'].active_material.node_tree.nodes if n.type=='EMISSION')
emission.inputs['Color'].default_value=(3,.4,.05,1)
window=bpy.context.window_manager.windows[0];area=next(a for a in window.screen.areas if a.type=='VIEW_3D')
space=area.spaces.active;region=next(r for r in area.regions if r.type=='WINDOW')
report={'scope':'GLOW-CAMERA-ALIGNMENT','complete':False,'source_sha256':{p.name:file_hash(p) for p in payload.glob('*.py')},'package_sha256':file_hash(args.candidate) if args.candidate else None,'cases':[]}
cases=[('center',0,(0,0),(512,512),0),('camera_frame_pan',0,(.12,-.08),(512,512),0),
       ('camera_frame_zoom',25,(.12,-.08),(512,512),0),('wide_camera',0,(0,0),(800,450),0),
       ('wide_camera_pan',0,(.12,-.08),(800,450),0),('camera_transform',0,(0,0),(800,450),.25),('perspective',0,(0,0),(800,450),0),('perspective_lens',0,(.08,-.04),(800,450),0),('pixel_aspect',0,(.08,-.04),(512,512),0),
       ('free_view',0,(0,0),(512,512),0),('free_view_pan',0,(0,0),(512,512),0)]
if args.case:cases=[case for case in cases if case[0] in args.case]
assert cases
state={'case':-1,'phase':'start','since':time.perf_counter()}
def output(socket):
    tree=scene.compositing_node_group;dest=next(n for n in tree.nodes if n.type=='GROUP_OUTPUT' and n.is_active_output)
    tree.links.new(socket,dest.inputs['Image']);area.tag_redraw();state['since']=time.perf_counter()
def capture(name):
    path=OUT/(name+'.png');bpy.ops.screen.screenshot(filepath=str(path))
    image=bpy.data.images.load(str(path),check_existing=False)
    pixels=np.array(image.pixels[:],dtype=np.float32).reshape((image.size[1],image.size[0],4));bpy.data.images.remove(image)
    crop=pixels[region.y+8:region.y+region.height-8,region.x+8:region.x+region.width-8]
    mask=(crop[:,:,0]>.8)&(crop[:,:,1]>.15)&(crop[:,:,1]<.85)&(crop[:,:,2]<.5)
    columns=np.flatnonzero(mask.sum(axis=0)>30);rows=np.flatnonzero(mask.sum(axis=1)>30)
    assert len(columns)>20 and len(rows)>20,(name,'No orange subject',len(columns),len(rows))
    mask[:,:columns.min()]=False;mask[:,columns.max()+1:]=False
    mask[:rows.min()]=False;mask[rows.max()+1:]=False
    y,x=np.nonzero(mask);assert len(x)>1000,(name,len(x))
    return {'center':[float(x.mean()),float(y.mean())],'bounds':[int(x.min()),int(y.min()),int(x.max()),int(y.max())],'pixels':len(x)}
def finish(error=None):
    if error:report['error']=error
    report['runtime_unchanged']=report['source_sha256']=={p.name:file_hash(p) for p in payload.glob('*.py')}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
    print('CAMERA_ALIGNMENT',report['complete'],report.get('error',''),flush=True)
    bpy.ops.wm.quit_blender()
def step():
    try:
        phase=state['phase'];now=time.perf_counter()
        if phase=='start':
            with bpy.context.temp_override(window=window,area=area):
                space.show_region_ui=False;space.show_region_toolbar=False;space.overlay.show_overlays=False
                space.shading.type='MATERIAL';space.shading.use_scene_world=space.shading.use_scene_lights=True
                space.camera=scene.camera;space.region_3d.view_perspective='CAMERA';scene.camera.data.show_passepartout=False
                bpy.context.view_layer.objects.active=scene.objects['Bright']
                scene.hgt_model=scene.objects['Subject A']
                addon.glow.enable(scene);addon.glow.viewport(bpy.context,True)
            state['phase']='next';return .1
        if phase=='next':
            state['case']+=1
            if state['case']==len(cases):report['complete']=True;finish();return None
            name,zoom,offset,size,x=cases[state['case']]
            space.region_3d.view_perspective='PERSP' if name.startswith('free_view') else 'CAMERA'
            if name.startswith('free_view'):
                space.region_3d.view_rotation=scene.camera.matrix_world.to_quaternion()
                space.region_3d.view_distance=4
                space.region_3d.view_location=(.3,.12,0) if name=='free_view_pan' else (0,0,0)
            scene.camera.data.type='PERSP' if name.startswith('perspective') else 'ORTHO'
            scene.camera.data.lens=35 if name=='perspective_lens' else 50
            scene.render.pixel_aspect_x=2 if name=='pixel_aspect' else 1
            scene.render.pixel_aspect_y=1
            space.region_3d.view_camera_zoom=zoom;space.region_3d.view_camera_offset=offset
            scene.render.resolution_x,scene.render.resolution_y=size;scene.camera.location.x=x
            state['phase']='wait';state['since']=now;area.tag_redraw();return .1
        if phase=='wait':
            record=addon.glow_preview._records.get(scene.as_pointer(),{})
            ready=record.get('key')==addon.glow_preview._key(scene,area,region,record)
            if not ready or record.get('settle') or record.get('dirty') or now-state['since']<1:
                assert now-state['since']<45,('Cache did not settle',scene.hgt_glow.error)
                return .1
            effect=addon.glow.node(scene);output(effect.inputs['Image'].links[0].from_socket)
            state['phase']='native';return .3
        name=cases[state['case']][0]
        if now-state['since']<.3:return .1
        if phase=='native':
            state['native']=capture(name+'-native')
            output(addon.glow_preview._nodes(scene)['scale'].outputs['Image'])
            state['phase']='cached';return .3
        if phase=='cached':
            cached=capture(name+'-cached');native=state['native']
            assert scene.hgt_glow.target==scene.objects['Subject A'],scene.hgt_glow.target
            delta=np.array(cached['center'])-native['center']
            report['cases'].append({'name':name,'native':native,'cached':cached,'offset_px':delta.tolist(),
                                    'view_camera_zoom':space.region_3d.view_camera_zoom,'view_camera_offset':list(space.region_3d.view_camera_offset)})
            print('CAMERA_CASE',name,'offset_px',delta.tolist(),flush=True)
            assert np.max(np.abs(delta))<3,(name,delta.tolist())
            output(addon.glow.node(scene).outputs['Image']);state['phase']='next';return .1
    except Exception:finish(traceback.format_exc());return None
bpy.app.timers.register(step,first_interval=2)
