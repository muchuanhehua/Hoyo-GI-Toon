"""Exercise the always-open UI, existing MMD model and native render job."""
import argparse,ctypes,json,os,sys,time,traceback
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
import numpy as np
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
viewport_before=None

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


def viewport_pixels(name):
    # Read the last naturally drawn frame: forcing DRAW_WIN_SWAP hid stale
    # uniforms even when ordinary slider drags did not refresh the viewport.
    assert bpy.ops.screen.screenshot(filepath=str(out/name))=={'FINISHED'}
    report['screenshots'].append(name)
    image=bpy.data.images.load(str(out/name),check_existing=False)
    width,height=image.size
    pixels=np.array(image.pixels[:],dtype=np.float32).reshape((height,width,4))
    ui=next(r for r in area.regions if r.type=='UI')
    right=ui.x if ui.x>area.x else area.x+area.width-300
    crop=pixels[area.y+50:area.y+area.height-50,area.x+80:right-10].copy()
    bpy.data.images.remove(image)
    return crop

def finish(error=None):
    if error:report['error']=error
    assert hashes=={p.name:file_hash(p) for p in payload.glob('*.py')}
    (out/'interface.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('HGT_SCENE_UI_FAILED' if error else 'HGT_SCENE_UI_PASSED',flush=True)
    bpy.ops.wm.quit_blender()

def step():
    global phase,viewport_before,window,area,region
    try:
        hide()
        window=bpy.context.window_manager.windows[0]
        area=next(a for a in window.screen.areas if a.type=='VIEW_3D')
        region=next(r for r in area.regions if r.type=='WINDOW')
        if time.monotonic()-started>240:raise TimeoutError('Private UI verification timed out')
        with bpy.context.temp_override(window=window,area=area,region=region):
            scene=bpy.context.scene
            if phase==0:
                window.event_simulate(type='ESC',value='PRESS');window.event_simulate(type='ESC',value='RELEASE')
                area.spaces.active.show_region_ui=True
                phase=1;return .7
            if phase==1:
                next(r for r in area.regions if r.type=='UI').active_panel_category='GI-Toon'
                phase=2;return .7
            if phase==2:
                assert not hasattr(bpy.types.Scene,'hgt_output')
                panels=[c for c in addon.panels.CLASSES if issubclass(c,bpy.types.Panel)]
                assert [p.bl_label for p in panels]==['角色管理','材质','局部调色','场景','打光','相机']
                assert [p.bl_label for p in panels if 'DEFAULT_CLOSED' in getattr(p,'bl_options',set())]==['场景','打光']
                assert addon.panels.HGT_OT_import_character.bl_label=='导入模型'
                assert not hasattr(addon.panels,'HGT_MT_tools') and not hasattr(addon.panels,'HGT_OT_face_resources')
                report['checks']['six_independent_panels']=report['checks']['scene_light_default_closed']=True
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
                assert addon.properties.model_poll(bpy.context.scene,model_root)
                assert not addon.properties.model_poll(bpy.context.scene,mesh)
                assert not addon.properties.model_poll(bpy.context.scene,addon.scene_models.armature(model_root))
                bpy.context.scene.hgt_model=addon.scene_models.armature(model_root)
                assert bpy.context.scene.hgt_model==model_root
                report['checks']['complete_models_only']=True
                assert addon.panels.HGT_OT_apply_materials.poll(bpy.context)
                phase=3;return .7
            if phase==3:
                screenshot('panel-existing.png')
                bpy.ops.ed.undo_push(message='Existing MMD')
                assert bpy.ops.hgt.apply_materials()=={'FINISHED'}
                assert next(a for a in window.screen.areas if a.type=='VIEW_3D').spaces.active.shading.type=='MATERIAL'
                report['checks']['automatic_material_preview']=True
                bpy.ops.ed.undo_push(message='Applied')
                assert bpy.ops.ed.undo()=={'FINISHED'} and (root() is None or not root().hgt_character.managed)
                assert bpy.ops.ed.redo()=={'FINISHED'} and root().hgt_character.managed
                assert not root().hgt_character.imported
                report['checks']['existing_model_apply_undo']=True
                class ControlAudit:
                    def __init__(self):self.props=[]
                    def column(self):return self
                    def row(self,**kwargs):return self
                    def prop(self,data,key,**kwargs):self.props.append(key)
                    def operator(self,*args,**kwargs):return None
                    def label(self,**kwargs):return None
                audit=ControlAudit()
                addon.panels.draw_materials(audit,bpy.context)
                assert [key for key in audit.props if key.startswith('outline')]==['outline','outline_difference']
                report['checks']['single_outline_difference_control']=True
                bpy.ops.ed.undo_push(message='Before SDF choice')
                root().hgt_character.face_sdf_preset='LEGACY_GIRL01'
                assert root().hgt_character.applied_sdf_preset=='LEGACY_GIRL01'
                bpy.ops.ed.undo_push(message='SDF choice')
                assert bpy.ops.ed.undo()=={'FINISHED'} and root().hgt_character.face_sdf_preset=='AUTO'
                assert bpy.ops.ed.redo()=={'FINISHED'} and root().hgt_character.applied_sdf_preset=='LEGACY_GIRL01'
                bpy.ops.ed.undo()
                report['checks']['bundled_sdf_undo_redo']=True
                bpy.ops.ed.undo_push(message='Before face softness')
                initial=root().hgt_character.face_softness
                root().hgt_character.face_softness=.11
                bpy.ops.ed.undo_push(message='Face softness')
                assert bpy.ops.ed.undo()=={'FINISHED'} and abs(root().hgt_character.face_softness-initial)<1e-6
                assert bpy.ops.ed.redo()=={'FINISHED'} and abs(root().hgt_character.face_softness-.11)<1e-6
                bpy.ops.ed.undo()
                report['checks']['face_softness_undo_redo']=True
                initial=addon.outline_profile.snapshot(root().hgt_character)
                bpy.ops.ed.undo_push(message='Before outline gradient')
                root().hgt_character.outline_difference=.8
                edited=addon.outline_profile.snapshot(root().hgt_character)
                bpy.ops.ed.undo_push(message='Outline gradient')
                assert bpy.ops.ed.undo()=={'FINISHED'} and addon.outline_profile.snapshot(root().hgt_character)==initial
                assert bpy.ops.ed.redo()=={'FINISHED'} and addon.outline_profile.snapshot(root().hgt_character)==edited
                bpy.ops.ed.undo()
                report['checks']['height_gradient_undo_redo']=True
                initial=root().hgt_character.shadow_softness
                bpy.ops.ed.undo_push(message='Before overall softness')
                root().hgt_character.shadow_softness=.14
                bpy.ops.ed.undo_push(message='Overall softness')
                assert bpy.ops.ed.undo()=={'FINISHED'} and abs(root().hgt_character.shadow_softness-initial)<1e-6
                assert bpy.ops.ed.redo()=={'FINISHED'} and abs(root().hgt_character.shadow_transition-.14)<1e-6
                assert abs(root().hgt_character.face_softness-.08)<1e-6
                bpy.ops.ed.undo()
                report['checks']['overall_softness_undo_redo']=True
                color=tuple(root().hgt_character.bindings[0].tint)
                bpy.ops.ed.undo_push(message='Before tint')
                root().hgt_character.bindings[0].tint=(.4,.7,1)
                bpy.ops.ed.undo_push(message='Tint')
                assert bpy.ops.ed.undo()=={'FINISHED'} and tuple(root().hgt_character.bindings[0].tint)==color
                assert bpy.ops.ed.redo()=={'FINISHED'} and abs(root().hgt_character.bindings[0].tint[0]-.4)<1e-5
                bpy.ops.ed.undo()
                report['checks']['material_params_undo']=True
                source=addon.scene_models.selected(bpy.context)
                visible=addon.scene_models.visible(source)
                bpy.ops.ed.undo_push(message='Before display')
                assert bpy.ops.hgt.toggle_display(bones=False)=={'FINISHED'}
                bpy.ops.ed.undo_push(message='Display')
                assert bpy.ops.ed.undo()=={'FINISHED'}
                assert addon.scene_models.visible(addon.scene_models.selected(bpy.context))==visible
                assert bpy.ops.ed.redo()=={'FINISHED'}
                assert addon.scene_models.visible(addon.scene_models.selected(bpy.context))!=visible
                bpy.ops.ed.undo()
                hidden=addon.scene_models.armature(addon.scene_models.selected(bpy.context)).hide_get()
                assert bpy.ops.hgt.toggle_display(bones=True)=={'FINISHED'}
                bpy.ops.ed.undo_push(message='Bones')
                assert bpy.ops.ed.undo()=={'FINISHED'}
                assert addon.scene_models.armature(addon.scene_models.selected(bpy.context)).hide_get()==hidden
                assert bpy.ops.ed.redo()=={'FINISHED'}
                bpy.ops.ed.undo()
                report['checks']['display_controls_undo']=True
                bpy.ops.ed.undo_push(message='Before preset')
                bpy.context.scene.hgt_lighting.selected='SOFT'
                assert bpy.ops.hgt.apply_light_preset()=={'FINISHED'}
                bpy.ops.ed.undo_push(message='Preset')
                assert bpy.ops.ed.undo()=={'FINISHED'} and bpy.context.scene.hgt_lighting.active=='DEFAULT'
                assert bpy.ops.ed.redo()=={'FINISHED'} and bpy.context.scene.hgt_lighting.active=='SOFT'
                parameters=addon.lighting.active_parameters(bpy.context.scene)
                energy=parameters.energy
                parameters.energy=3.7
                bpy.ops.ed.undo_push(message='Preset parameter')
                assert bpy.ops.ed.undo()=={'FINISHED'}
                assert abs(addon.lighting.active_parameters(bpy.context.scene).energy-energy)<1e-5
                assert bpy.ops.ed.redo()=={'FINISHED'}
                assert abs(bpy.context.scene.hgt_light.data.energy-3.7)<1e-5
                report['checks']['light_presets_undo']=True
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
                root().hgt_character.shadow_position=.15
                phase=6;return 8
            if phase==6:
                assert bpy.context.space_data.shading.type=='MATERIAL'
                assert bpy.context.space_data.shading.use_scene_lights and bpy.context.space_data.shading.use_scene_world
                viewport_before=viewport_pixels('viewport-shadow-15.png')
                screenshot('panel-full.png')
                root().hgt_character.shadow_position=.85
                phase=7;return 2
            if phase==7:
                after=viewport_pixels('viewport-shadow-85.png')
                response=float(np.abs(after-viewport_before).max())
                assert response>.02,response
                report['viewport_shadow_response']=response
                report['checks']['realtime_viewport_shadow_response']=True
                viewport_before=after
                body=next(b for b in root().hgt_character.bindings if b.role=='body')
                body.tint=(.3,.7,1)
                phase=8;return 3
            if phase==8:
                after=viewport_pixels('viewport-local-tint.png')
                response=float(np.abs(after-viewport_before).max())
                assert response>.02,response
                report['viewport_local_response']=response
                report['checks']['realtime_viewport_local_response']=True
                body=next(b for b in root().hgt_character.bindings if b.role=='body')
                body.tint=(1,1,1)
                root().hgt_character.shadow_position=.52
                root().hgt_character.outline=.8
                root().hgt_character.show_material_advanced=True
                phase=9;return 3
            if phase==9:
                viewport_before=viewport_pixels('viewport-gradient-default.png')
                screenshot('panel-advanced.png')
                root().hgt_character.outline_difference=-.8
                phase=10;return 3
            if phase==10:
                after=viewport_pixels('viewport-gradient-custom.png')
                response=float(np.abs(after-viewport_before).max())
                assert response>.02,response
                report['viewport_gradient_response']=response
                report['checks']['realtime_viewport_gradient_response']=True
                viewport_before=after
                root().hgt_character.shadow_softness=.2
                phase=11;return 3
            if phase==11:
                after=viewport_pixels('viewport-overall-soft.png')
                response=float(np.abs(after-viewport_before).max())
                assert response>.01,response
                report['viewport_softness_response']=response
                report['checks']['realtime_viewport_overall_softness_response']=True
                viewport_before=after
                addon.lighting.active_parameters(bpy.context.scene).azimuth+=1.2
                phase=12;return 3
            if phase==12:
                after=viewport_pixels('viewport-light-rotate.png')
                response=float(np.abs(after-viewport_before).max())
                assert response>.02,response
                report['viewport_light_response']=response
                report['checks']['realtime_viewport_light_rotation_response']=True
                area.spaces.active.shading.type='SOLID'
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
