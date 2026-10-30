"""Exercise the always-open UI, existing MMD model and native render job."""
import argparse,ctypes,json,os,sys,time,traceback
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
from mathutils import Vector,Euler
from verification_runtime import load_mmd,load_addon,install_candidate,unload_addon,file_hash

parser=argparse.ArgumentParser()
for name in ('assets-index','mmd-tools','output-dir'):parser.add_argument('--'+name,type=Path,required=True)
parser.add_argument('--candidate',type=Path)
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
hashes={p.name:file_hash(p) for p in payload.glob('*.py')}
report={'scope':'PMX-M09-M12-UI','package_sha256':file_hash(args.candidate) if args.candidate else None,
        'source_sha256':hashes,'checks':{},'screenshots':[]}
bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
bpy.context.preferences.edit.use_global_undo=True
bpy.context.preferences.view.show_splash=False
bpy.context.preferences.view.render_display_type='NONE'
window=bpy.context.window_manager.windows[0]
area=next(a for a in window.screen.areas if a.type=='VIEW_3D')
region=next(r for r in area.regions if r.type=='WINDOW')
phase=0;started=time.monotonic()

def root():return addon.panels.target(bpy.context)

def align_camera():
    live_window=bpy.context.window_manager.windows[0]
    live_area=next(a for a in live_window.screen.areas if a.type=='VIEW_3D')
    live_region=next(r for r in live_area.regions if r.type=='WINDOW')
    with bpy.context.temp_override(window=live_window,area=live_area,region=live_region):
        return bpy.ops.hgt.align_camera()

def screenshot(name):
    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP',iterations=2)
    assert bpy.ops.screen.screenshot(filepath=str(out/name))=={'FINISHED'}
    report['screenshots'].append(name)

def finish(error=None):
    if error:report['error']=error
    assert hashes=={p.name:file_hash(p) for p in payload.glob('*.py')}
    (out/'interface.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('HGT_SCENE_UI_FAILED' if error else 'HGT_SCENE_UI_PASSED',flush=True)
    bpy.ops.wm.quit_blender()

def step():
    global phase
    try:
        hide()
        if time.monotonic()-started>150:raise TimeoutError('Private UI verification timed out')
        with bpy.context.temp_override(window=window,area=area,region=region):
            scene=bpy.context.scene
            if phase==0:
                window.event_simulate(type='ESC',value='PRESS');window.event_simulate(type='ESC',value='RELEASE')
                area.spaces.active.show_region_ui=True
                phase=1;return .7
            if phase==1:
                next(r for r in area.regions if r.type=='UI').active_panel_category='Hoyo-GI-Toon'
                phase=2;return .7
            if phase==2:
                assert not hasattr(bpy.types.Scene,'hgt_output')
                panels=[c for c in addon.panels.CLASSES if issubclass(c,bpy.types.Panel)]
                assert panels==[addon.panels.HGT_PT_main] and 'DEFAULT_CLOSED' not in getattr(panels[0],'bl_options',set())
                assert not addon.panels.HGT_OT_apply_materials.poll(bpy.context)
                assert addon.panels.HGT_OT_default_light.poll(bpy.context)
                assert addon.panels.HGT_OT_align_camera.poll(bpy.context)
                screenshot('panel-empty.png')
                report['checks']['empty_scene_controls']=report['checks']['no_output_panel']=True
                assert bpy.ops.ed.undo_push(message='Empty')=={'FINISHED'}
                assert bpy.ops.hgt.default_light()=={'FINISHED'}
                bpy.ops.ed.undo_push(message='Light')
                assert bpy.ops.ed.undo()=={'FINISHED'} and bpy.context.scene.hgt_light is None
                assert bpy.ops.ed.redo()=={'FINISHED'} and bpy.context.scene.hgt_light
                report['checks']['light_without_model_undo']=True
                assert align_camera()=={'FINISHED'}
                bpy.ops.ed.undo_push(message='Camera')
                assert bpy.ops.ed.undo()=={'FINISHED'} and bpy.context.scene.camera is None
                assert bpy.ops.ed.redo()=={'FINISHED'} and bpy.context.scene.camera
                report['checks']['camera_without_model_undo']=True
                model=json.loads(args.assets_index.read_text(encoding='utf-8'))['models'][1]
                assert bpy.ops.mmd_tools.import_model('EXEC_DEFAULT',filepath=model['path'],scale=.08,
                    clean_model=False,remove_doubles=False,rename_bones=False,fix_bone_order=False,
                    fix_ik_links=False,apply_bone_fixed_axis=False)=={'FINISHED'}
                model_root=next(o for o in bpy.context.scene.objects if getattr(o,'mmd_type','')=='ROOT')
                mesh=next(o for o in model_root.children_recursive if o.type=='MESH'
                          and getattr(o,'mmd_type','') not in {'RIGID_BODY','JOINT'})
                bpy.context.view_layer.objects.active=mesh
                addon.scene_models.sync_active(bpy.context.scene)
                assert bpy.context.scene.hgt_model==model_root and root() is None
                assert addon.panels.HGT_OT_apply_materials.poll(bpy.context)
                phase=3;return .7
            if phase==3:
                screenshot('panel-existing.png')
                bpy.ops.ed.undo_push(message='Existing MMD')
                assert bpy.ops.hgt.apply_materials()=={'FINISHED'}
                bpy.ops.ed.undo_push(message='Applied')
                assert bpy.ops.ed.undo()=={'FINISHED'} and (root() is None or not root().hgt_character.managed)
                assert bpy.ops.ed.redo()=={'FINISHED'} and root().hgt_character.managed
                assert not root().hgt_character.imported
                report['checks']['existing_model_apply_undo']=True
                color=tuple(root().hgt_character.bindings[0].tint)
                bpy.ops.ed.undo_push(message='Before tint')
                root().hgt_character.bindings[0].tint=(.4,.7,1)
                bpy.ops.ed.undo_push(message='Tint')
                assert bpy.ops.ed.undo()=={'FINISHED'} and tuple(root().hgt_character.bindings[0].tint)==color
                assert bpy.ops.ed.redo()=={'FINISHED'} and abs(root().hgt_character.bindings[0].tint[0]-.4)<1e-5
                bpy.ops.ed.undo()
                report['checks']['material_params_undo']=True
                assert bpy.ops.hgt.look_camera()=={'FINISHED'}
                bpy.ops.ed.undo_push(message='Gaze')
                assert bpy.ops.ed.undo()=={'FINISHED'} and not root().hgt_character.look_camera
                assert bpy.ops.ed.redo()=={'FINISHED'} and root().hgt_character.look_camera
                bpy.ops.hgt.look_camera()
                report['checks']['gaze_undo']=True
                scene=bpy.context.scene
                points=[e.object.matrix_world@Vector(c) for e in root().hgt_character.meshes for c in e.object.bound_box]
                low=Vector(tuple(min(p[i] for p in points) for i in range(3)))
                high=Vector(tuple(max(p[i] for p in points) for i in range(3)))
                view=area.spaces.active.region_3d
                view.view_perspective='PERSP'
                view.view_location=(low+high)*.5;view.view_distance=(high.z-low.z)*3
                view.view_rotation=Euler((1.570796,0,0)).to_quaternion()
                assert align_camera()=={'FINISHED'}
                scene.render.resolution_x,scene.render.resolution_y=256,384
                scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA'
                scene.render.film_transparent=True
                scene.render.filepath=str(out/'output-canary.png')
                (out/'output-canary.png').write_bytes(b'preserve native output')
                phase=4;return .7
            if phase==4:
                screenshot('panel-full.png')
                bpy.ops.wm.save_as_mainfile(filepath=str(out/'ui-preview.blend'),relative_remap=False)
                report['checks']['save_project']=True
                report['scene_count']=len(bpy.data.scenes)
                assert bpy.ops.hgt.render()=={'RUNNING_MODAL'}
                phase=5;return .3
            if phase==5:
                if bpy.app.is_job_running('RENDER'):return .3
                assert len(bpy.data.scenes)==report['scene_count']
                assert (out/'output-canary.png').read_bytes()==b'preserve native output'
                bpy.data.images['Render Result'].save_render(str(out/'ui-render.png'),scene=bpy.context.scene)
                image=bpy.data.images.load(str(out/'ui-render.png'),check_existing=False)
                assert tuple(image.size)==(256,384);bpy.data.images.remove(image)
                report['checks']['native_async_render']=True
                unload_addon(addon);mmd.unregister();finish();return None
    except Exception:
        finish(traceback.format_exc());return None
    return .3

bpy.app.timers.register(step,first_interval=.5)
