"""Verify staged PMX operators, undo and actual PNG in a private UI process."""
import argparse,ctypes,json,os,sys,time,traceback,struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
from mathutils import Vector,Euler
from verification_runtime import load_mmd,load_addon,install_candidate,unload_addon,file_hash
parser=argparse.ArgumentParser()
for name in ('assets-index','mmd-tools','output-dir'):parser.add_argument('--'+name,type=Path,required=True)
parser.add_argument('--candidate',type=Path)
parser.add_argument('--tab-click',type=int,nargs=2)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
project=Path(__file__).resolve().parents[1];out=args.output_dir.resolve()
assert out.is_relative_to(project/'.verification');out.mkdir(parents=True,exist_ok=True)
def hide():
    callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
    @callback
    def each(hwnd,_):
        pid=ctypes.c_ulong();ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value==os.getpid():ctypes.windll.user32.ShowWindow(hwnd,0)
        return True
    ctypes.windll.user32.EnumWindows(each,0)
hide();mmd=load_mmd(args.mmd_tools,out/'_runtime')
addon=install_candidate(args.candidate,out) if args.candidate else load_addon(project)
payload=Path(addon.__file__).resolve().parent
report={'scope':'PMX-M01-M08-UI','package_sha256':file_hash(args.candidate) if args.candidate else None,
        'source_sha256':{p.name:file_hash(p) for p in payload.glob('*.py')},'checks':{},'screenshots':[]}
bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
bpy.context.preferences.edit.use_global_undo=True
bpy.context.preferences.view.show_splash=False
bpy.context.preferences.view.render_display_type='NONE'
window=bpy.context.window_manager.windows[0]
area=next(a for a in window.screen.areas if a.type=='VIEW_3D')
region=next(r for r in area.regions if r.type=='WINDOW')
for cls in (addon.panels.HGT_PT_materials,addon.panels.HGT_PT_light,addon.panels.HGT_PT_camera,addon.panels.HGT_PT_output):
    bpy.utils.unregister_class(cls);cls.bl_options=set();bpy.utils.register_class(cls)
phase=0;started=time.monotonic()
def root():return bpy.context.scene.hgt_target
def save():
    (out/'interface.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def screenshot(name):
    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP',iterations=2)
    assert bpy.ops.screen.screenshot(filepath=str(out/name))=={'FINISHED'}
    report['screenshots'].append(name)
def finish(error=None):
    if error:report['error']=error
    save();print('HGT_PMX_UI_FAILED' if error else 'HGT_PMX_UI_PASSED',flush=True)
    bpy.ops.wm.quit_blender()
def step():
    global phase
    try:
        hide()
        if time.monotonic()-started>150:raise TimeoutError('Private PMX UI verification timed out')
        with bpy.context.temp_override(window=window,area=area,region=region):
            scene=bpy.context.scene
            if phase==0:
                window.event_simulate(type='ESC',value='PRESS');window.event_simulate(type='ESC',value='RELEASE')
                phase=1;return .5
            if phase==1:
                def view_state():
                    view=area.spaces.active.region_3d
                    return (area.spaces.active.shading.type,view.view_perspective,tuple(view.view_location),
                            tuple(view.view_rotation),view.view_distance)
                before_view=view_state()
                assert bpy.ops.ed.undo_push(message='Empty')=={'FINISHED'}
                model=json.loads(args.assets_index.read_text(encoding='utf-8'))['models'][1]
                assert bpy.ops.hgt.import_character(filepath=model['path'])=={'FINISHED'}
                assert not root().hgt_character.managed and not any(o.type=='LIGHT' for o in scene.objects)
                assert before_view==view_state()
                assert bpy.ops.ed.undo_push(message='Imported')=={'FINISHED'}
                assert bpy.ops.ed.undo()=={'FINISHED'} and not any(o.hgt_character.imported for o in bpy.context.scene.objects)
                assert bpy.ops.ed.redo()=={'FINISHED'} and root().hgt_character.imported
                report['checks']['split_actions']=report['checks']['undo_redo']=True
                assert bpy.ops.hgt.apply_materials()=={'FINISHED'}
                assert bpy.ops.ed.undo_push(message='Materials')=={'FINISHED'}
                assert bpy.ops.ed.undo()=={'FINISHED'} and not root().hgt_character.managed
                assert bpy.ops.ed.redo()=={'FINISHED'} and root().hgt_character.managed
                item=root().hgt_character.bindings[0];color=tuple(item.tint)
                assert bpy.ops.ed.undo_push(message='Before tint')=={'FINISHED'}
                item.tint=(.4,.7,1)
                assert bpy.ops.ed.undo_push(message='Tint')=={'FINISHED'}
                assert bpy.ops.ed.undo()=={'FINISHED'} and tuple(root().hgt_character.bindings[0].tint)==color
                assert bpy.ops.ed.redo()=={'FINISHED'} and abs(root().hgt_character.bindings[0].tint[0]-.4)<1e-5
                assert bpy.ops.ed.undo()=={'FINISHED'}
                report['checks']['material_params_undo']=True
                assert bpy.ops.hgt.default_light()=={'FINISHED'}
                assert bpy.ops.ed.undo_push(message='Light')=={'FINISHED'}
                assert bpy.ops.ed.undo()=={'FINISHED'} and root().hgt_character.light_source is None
                assert bpy.ops.ed.redo()=={'FINISHED'} and root().hgt_character.light_source
                report['checks']['light_undo']=True
                assert bpy.ops.hgt.look_camera()=={'FINISHED'}
                assert bpy.ops.ed.undo_push(message='Gaze')=={'FINISHED'}
                assert bpy.ops.ed.undo()=={'FINISHED'} and not root().hgt_character.look_camera
                assert bpy.ops.ed.redo()=={'FINISHED'} and root().hgt_character.look_camera
                assert bpy.ops.hgt.look_camera()=={'FINISHED'}
                report['checks']['gaze_undo']=True
                scene=bpy.context.scene
                assert bpy.ops.hgt.import_character.get_rna_type().properties['filter_glob'].default=='*.pmx'
                assert not hasattr(addon.panels,'HGT_PT_expressions') and not hasattr(addon.panels,'HGT_PT_parts')
                assert not hasattr(root().hgt_character,'show_floor')
                report['checks']['panel_inventory']=True
                camera=root().hgt_character.camera
                points=[e.object.matrix_world@Vector(c) for e in root().hgt_character.meshes for c in e.object.bound_box]
                low=Vector(tuple(min(p[i] for p in points) for i in range(3)));high=Vector(tuple(max(p[i] for p in points) for i in range(3)))
                view=area.spaces.active.region_3d
                view.view_location=(low+high)*.5;view.view_distance=(high.z-low.z)*3
                view.view_rotation=Euler((1.570796,0,0)).to_quaternion()
                assert bpy.ops.hgt.align_camera()=={'FINISHED'}
                scene.render.resolution_x,scene.render.resolution_y=256,384
                scene.render.film_transparent=True
                scene.hgt_output.filepath=str(out/'ui-render.png')
                area.spaces.active.show_region_ui=True
                phase=2;return 1
            if phase==2:
                if not (out/'initial.png').exists():screenshot('initial.png')
                # The category position is read from the first private screenshot.
                command=out/'tab-click.json'
                if not args.tab_click and not command.exists():return .4
                x,y=args.tab_click or json.loads(command.read_text(encoding='utf-8-sig'))
                window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=x,y=y)
                window.event_simulate(type='LEFTMOUSE',value='PRESS',x=x,y=y)
                window.event_simulate(type='LEFTMOUSE',value='RELEASE',x=x,y=y)
                phase=3;return 1
            if phase==3:
                assert next(r for r in area.regions if r.type=='UI').active_panel_category=='Hoyo-GI-Toon'
                screenshot('panel-full.png')
                for _ in range(5):window.event_simulate(type='WHEELDOWNMOUSE',value='PRESS',x=850,y=400)
                phase=31;return .6
            if phase==31:
                screenshot('panel-output.png')
                scene.hgt_output.filepath=str(out/'cancelled.png')
                (out/'cancelled.png').write_bytes(b'preserve old output')
                previous=scene.hgt_output.last_render;report['previous_last_render']=previous
                def cancelled(*a,**kw):
                    proxy=bpy.data.scenes[kw['scene']]
                    Path(proxy.render.filepath).write_bytes(b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',256,384))
                    addon.rendering.render_cancel(proxy);return {'RUNNING_MODAL'}
                fake=SimpleNamespace(app=bpy.app,context=bpy.context,data=bpy.data,path=bpy.path,
                    ops=SimpleNamespace(render=SimpleNamespace(render=cancelled)))
                with patch.object(addon.rendering,'bpy',fake):assert bpy.ops.hgt.render()=={'RUNNING_MODAL'}
                phase=4;return .4
            if phase==4:
                if scene.hgt_output.rendering:return .2
                assert not addon.rendering._JOBS and not list(out.glob('.hgt-*.png'))
                assert (out/'cancelled.png').read_bytes()==b'preserve old output'
                assert scene.hgt_output.last_render==report['previous_last_render']
                report['checks']['cancel_cleanup']=True
                report['native_cancel_input']='not_verified; callback fault injection only'
                scene.hgt_output.filepath=str(out/'ui-render.png')
                bpy.ops.wm.save_as_mainfile(filepath=str(out/'ui-preview.blend'),relative_remap=False)
                report['checks']['save_project']=True
                assert bpy.ops.hgt.render()=={'RUNNING_MODAL'}
                phase=5;return .3
            if phase==5:
                if scene.hgt_output.rendering or bpy.app.is_job_running('RENDER'):return .3
                assert not addon.rendering._JOBS
                image=bpy.data.images.load(str(out/'ui-render.png'),check_existing=False)
                assert tuple(image.size)==(256,384);bpy.data.images.remove(image)
                report['checks']['async_render']=True
                unload_addon(addon);mmd.unregister();finish();return None
    except Exception:
        finish(traceback.format_exc());return None
    return .3
bpy.app.timers.register(step,first_interval=.5)
