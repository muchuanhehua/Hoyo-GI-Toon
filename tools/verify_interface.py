"""Exercise real UI operators in a separate hidden Blender window."""
import argparse
import ctypes
import json
import os
import struct
from pathlib import Path
import shutil
import sys
import time
import traceback
from types import SimpleNamespace
from unittest.mock import patch

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
from verification_runtime import copy_better,load_mmd,load_addon,install_candidate,file_hash,unload_addon

parser=argparse.ArgumentParser()
parser.add_argument('--assets-index',type=Path,required=True)
parser.add_argument('--better-fbx',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True)
parser.add_argument('--candidate',type=Path)
parser.add_argument('--mmd-tools',type=Path)
parser.add_argument('--tab-click',type=int,nargs=2)
parser.add_argument('--subjects',action='store_true')
parser.add_argument('--workflow',action='store_true')
parser.add_argument('--model-index',type=int)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
project=Path(__file__).resolve().parents[1]
out=args.output_dir.resolve()
assert out.is_relative_to(project/'.verification')
out.mkdir(parents=True,exist_ok=True)
index=json.loads(args.assets_index.read_text(encoding='utf-8'))
report={'package_sha256':file_hash(args.candidate) if args.candidate else None,'integration_checks':{},'screenshots':[]}
report['subject_checks']={}
phase=-1
capture_index=0
panel_captures=[('view-panel.png',318),('display-panel.png',349),
                ('expressions-panel.png',379),('output-panel.png',411)]
started=time.monotonic()


def hide_own_window():
    if sys.platform!='win32': return
    callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
    @callback
    def hide(hwnd,_):
        process=ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(process))
        if process.value==os.getpid(): ctypes.windll.user32.ShowWindow(hwnd,0)
        return True
    ctypes.windll.user32.EnumWindows(hide,0)


def write_report():
    (out/'interface.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def find_root():
    return next(obj for obj in bpy.context.scene.objects if obj.hgt_character.managed)


def part_state(root):
    return [(p.key,p.role,p.included,p.locked) for p in root.hgt_character.parts]


def check_display(root):
    # Let the normal depsgraph handler update undo/redo, without forcing masks.
    bpy.context.view_layer.update()
    for entry in root.hgt_character.meshes:
        selected={p.key for p in root.hgt_character.parts if p.object==entry.object and p.included and not p.locked}
        assert entry.object.hide_render==(not bool(selected))
        if entry.render_data:
            ids=entry.render_data.attributes['hgt_part_id'].data
            visible=entry.render_data.attributes['hgt_part_visible'].data
            assert all(v.value==(i.value in selected) for i,v in zip(ids,visible))
            assert 'hgt_part_id' not in entry.original_data.attributes


def check_subject_operators():
    root=find_root()
    original=part_state(root)
    part=next(p for p in root.hgt_character.parts if not p.locked and p.role in {'WEAPON','GLIDER','EFFECT'})
    key=part.key
    scale=root.hgt_character.camera.data.ortho_scale
    assert bpy.ops.ed.undo_push(message='HGT before attachment')=={'FINISHED'}
    assert bpy.ops.hgt.toggle_part(key=key)=={'FINISHED'}
    assert next(p for p in find_root().hgt_character.parts if p.key==key).included
    assert bpy.ops.ed.undo_push(message='HGT attachment shown')=={'FINISHED'}
    assert bpy.ops.ed.undo()=={'FINISHED'}
    root=find_root();check_display(root)
    assert part_state(root)==original
    assert abs(root.hgt_character.camera.data.ortho_scale-scale)<1e-6
    assert bpy.ops.ed.redo()=={'FINISHED'}
    root=find_root();check_display(root)
    assert next(p for p in root.hgt_character.parts if p.key==key).included
    assert bpy.ops.ed.undo()=={'FINISHED'}
    root=find_root();check_display(root)
    assert part_state(root)==original
    report['subject_checks']['toggle_undo_redo']=True
    edits=[{'name':str(p.key),'key':p.key,'label':p.name,'role':'BODY' if p.key==key else p.role,
            'included':True if p.key==key else p.included} for p in root.hgt_character.parts if not p.locked]
    assert bpy.ops.ed.undo_push(message='HGT before grouping')=={'FINISHED'}
    assert bpy.ops.hgt.manage_parts(parts=edits)=={'FINISHED'}
    assert next(p for p in root.hgt_character.parts if p.key==key).role=='BODY'
    assert bpy.ops.ed.undo_push(message='HGT grouped')=={'FINISHED'}
    assert bpy.ops.ed.undo()=={'FINISHED'}
    root=find_root();check_display(root)
    assert part_state(root)==original
    assert bpy.ops.ed.redo()=={'FINISHED'}
    root=find_root();check_display(root)
    assert next(p for p in root.hgt_character.parts if p.key==key).role=='BODY'
    assert bpy.ops.ed.undo()=={'FINISHED'}
    root=find_root();check_display(root)
    assert part_state(root)==original
    report['subject_checks']['group_undo_redo']=True
    edits=[{'name':str(p.key),'key':p.key,'label':p.name,'role':p.role,'included':False}
           for p in root.hgt_character.parts if not p.locked]
    try:bpy.ops.hgt.manage_parts(parts=edits)
    except RuntimeError as exc:assert '至少选择一个' in str(exc)
    else:raise AssertionError('Empty selection was accepted')
    assert part_state(root)==original
    report['subject_checks']['empty_selection_rollback']=True


def finish(error=None):
    if error:
        report['error']=error
    write_report()
    print('HGT_INTERFACE_COMPLETE' if not error else 'HGT_INTERFACE_FAILED',flush=True)
    bpy.ops.wm.quit_blender()


def check_workflow_operators():
    root=find_root();initial=root.hgt_character.shot
    assert bpy.ops.ed.undo_push(message='Before framing')=={'FINISHED'}
    assert bpy.ops.hgt.set_shot(shot='HEAD')=={'FINISHED'}
    assert bpy.ops.ed.undo_push(message='Head framing')=={'FINISHED'}
    assert bpy.ops.ed.undo()=={'FINISHED'}
    assert find_root().hgt_character.shot==initial
    assert bpy.ops.ed.redo()=={'FINISHED'}
    assert find_root().hgt_character.shot=='HEAD'
    assert bpy.ops.ed.undo()=={'FINISHED'}
    root=find_root();settings=root.hgt_character
    values=settings.light_azimuth,settings.light_elevation
    assert bpy.ops.ed.undo_push(message='Before lighting')=={'FINISHED'}
    assert bpy.ops.hgt.light_preset(preset='SIDE')=={'FINISHED'}
    assert bpy.ops.ed.undo_push(message='Side light')=={'FINISHED'}
    assert bpy.ops.ed.undo()=={'FINISHED'}
    settings=find_root().hgt_character
    assert (settings.light_azimuth,settings.light_elevation)==values
    assert bpy.ops.ed.redo()=={'FINISHED'}
    assert abs(find_root().hgt_character.light_azimuth+1)<1e-6
    assert bpy.ops.ed.undo()=={'FINISHED'}
    root=find_root();settings=root.hgt_character
    item=settings.expressions[0];name=item.name;value=item.value
    assert bpy.ops.ed.undo_push(message='Before expression')=={'FINISHED'}
    item.value=.65;bpy.context.view_layer.update()
    assert bpy.ops.ed.undo_push(message='Expression changed')=={'FINISHED'}
    assert bpy.ops.ed.undo()=={'FINISHED'}
    assert find_root().hgt_character.expressions[name].value==value
    assert bpy.ops.ed.redo()=={'FINISHED'}
    assert abs(find_root().hgt_character.expressions[name].value-.65)<1e-5
    assert bpy.ops.ed.undo()=={'FINISHED'}
    root=find_root()
    if addon.panels.HGT_OT_look_camera.poll(bpy.context):
        assert bpy.ops.ed.undo_push(message='Before gaze')=={'FINISHED'}
        assert bpy.ops.hgt.look_camera()=={'FINISHED'}
        assert bpy.ops.ed.undo_push(message='Gaze enabled')=={'FINISHED'}
        assert bpy.ops.ed.undo()=={'FINISHED'}
        assert not find_root().hgt_character.look_camera
        assert bpy.ops.ed.redo()=={'FINISHED'}
        assert find_root().hgt_character.look_camera and len(find_root().hgt_character.gaze_bones)==2
        assert bpy.ops.ed.undo()=={'FINISHED'}
        report['gaze_undo_redo']=True
    report['integration_checks']['workflow_undo_redo']=True
    root=find_root()
    assert bpy.ops.hgt.output_size(preset='SQUARE')=={'FINISHED'}
    assert (bpy.context.scene.hgt_output.width,bpy.context.scene.hgt_output.height)==(1024,1024)
    assert bpy.ops.hgt.view_angle(angle='TURN')=={'FINISHED'}
    assert abs(root.hgt_character.view_azimuth-.6)<1e-5
    assert bpy.ops.hgt.reset_display()=={'FINISHED'}
    report['integration_checks']['ui_workflow_controls']=True


hide_own_window()
runtime=out/'_runtime'
better,_=copy_better(args.better_fbx,runtime)
mmd=load_mmd(args.mmd_tools,runtime) if args.mmd_tools else None
addon=install_candidate(args.candidate,out) if args.candidate else load_addon(project)
bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
bpy.context.preferences.view.show_splash=False
bpy.context.preferences.edit.use_global_undo=True
window=bpy.context.window_manager.windows[0]
area=max((a for a in window.screen.areas if a.type=='VIEW_3D'),key=lambda a:a.width*a.height)
region=next(r for r in area.regions if r.type=='WINDOW')
render_display=bpy.context.preferences.view.bl_rna.properties.get('render_display_type')
if render_display and 'NONE' in render_display.enum_items.keys():
    bpy.context.preferences.view.render_display_type='NONE'


def screenshot(name):
    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP',iterations=2)
    path=out/name
    assert bpy.ops.screen.screenshot(filepath=str(path))=={'FINISHED'}
    assert path.is_file() and path.stat().st_size>5000
    report['screenshots'].append(name)


def click_panel(y):
    x,y=660,window.height-y
    window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=x,y=y)
    window.event_simulate(type='LEFTMOUSE',value='PRESS',x=x,y=y)
    window.event_simulate(type='LEFTMOUSE',value='RELEASE',x=x,y=y)


def step():
    global phase,render_start,uid,dialog_state,capture_index
    try:
        hide_own_window()
        if time.monotonic()-started>180: raise TimeoutError('Hidden interface verification timed out')
        with bpy.context.temp_override(window=window,area=area,region=region):
            if phase==-1:
                window.event_simulate(type='ESC',value='PRESS')
                window.event_simulate(type='ESC',value='RELEASE')
                phase=0
                return .5
            if phase==0:
                assert bpy.ops.ed.undo_push(message='HGT empty scene')=={'FINISHED'}
                model=index['models'][args.model_index if args.model_index is not None else (0 if args.subjects else 1)]
                is_pmx=Path(model['path']).suffix.lower()=='.pmx'
                if is_pmx: better.unregister()
                assert bpy.ops.hgt.import_character(filepath=model['path'])=={'FINISHED'}
                if is_pmx: better.register()
                uid=find_root().hgt_character.uid
                assert bpy.ops.ed.undo_push(message='HGT imported')=={'FINISHED'}
                assert bpy.ops.ed.undo()=={'FINISHED'}
                assert not any(o.hgt_character.managed for o in bpy.context.scene.objects)
                assert bpy.ops.ed.redo()=={'FINISHED'}
                root=find_root()
                assert root.hgt_character.uid==uid and root.hgt_character.bindings
                assert bpy.ops.hgt.restore_materials()=={'FINISHED'}
                assert not root.hgt_character.managed
                assert bpy.ops.ed.undo_push(message='HGT restored')=={'FINISHED'}
                assert bpy.ops.ed.undo()=={'FINISHED'}
                root=find_root()
                assert root.hgt_character.uid==uid and root.hgt_character.camera
                assert bpy.ops.ed.redo()=={'FINISHED'}
                assert not any(o.hgt_character.managed for o in bpy.context.scene.objects)
                assert bpy.ops.ed.undo()=={'FINISHED'}
                root=find_root()
                report['integration_checks']['undo_redo']=True
                scene=bpy.context.scene
                before=addon.workflow.asset_tracking.data_pointers()
                try: bpy.ops.hgt.import_character(filepath=str(out/'missing.fbx'))
                except RuntimeError as exc: assert '模型文件不存在' in str(exc)
                else: raise AssertionError('Missing-file operator did not report an error')
                assert before==addon.workflow.asset_tracking.data_pointers()
                dependency=mmd if is_pmx else better
                dependency.unregister()
                try: bpy.ops.hgt.import_character(filepath=index['models'][0]['path'])
                except RuntimeError as exc: assert ('MMD Tools' if is_pmx else 'Better FBX') in str(exc)
                else: raise AssertionError('Missing-dependency operator did not report an error')
                dependency.register()
                report['integration_checks']['ui_errors']=True
                if args.subjects:
                    check_subject_operators()
                    root=find_root()
                    scene=bpy.context.scene
                    part_panel=addon.panels.HGT_PT_parts
                    bpy.utils.unregister_class(part_panel)
                    part_panel.bl_options=set()
                    bpy.utils.register_class(part_panel)
                if args.workflow:
                    check_workflow_operators()
                    root=find_root();scene=bpy.context.scene
                scene.hgt_output.width,scene.hgt_output.height=384,576
                scene.hgt_output.filepath=str(out/'ui-render.png')
                scene.hgt_target=root
                assert bpy.ops.hgt.frame_camera()=={'FINISHED'}
                space=area.spaces.active
                space.show_region_ui=True
                space.show_region_toolbar=False
                space.use_local_camera=True
                space.camera=scene.hgt_output.camera
                space.region_3d.view_perspective='CAMERA'
                space.shading.type='MATERIAL'
                phase=10
                return 1.0
            if phase==10:
                if not (out/'initial.png').exists(): screenshot('initial.png')
                command=out/'tab-click.json'
                if not args.tab_click and not command.exists(): return .3
                x,y=args.tab_click or json.loads(command.read_text(encoding='utf-8-sig'))
                assert 0<=x<window.width and 0<=y<window.height
                window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=x,y=y)
                window.event_simulate(type='LEFTMOUSE',value='PRESS',x=x,y=y)
                window.event_simulate(type='LEFTMOUSE',value='RELEASE',x=x,y=y)
                phase=11
                return 1.0
            if phase==11:
                sidebar=next(r for r in area.regions if r.type=='UI')
                assert sidebar.active_panel_category=='Hoyo-GI-Toon',sidebar.active_panel_category
                phase=1
                return 2.0
            if phase==1:
                screenshot('panel.png')
                if args.workflow:
                    click_panel(panel_captures[0][1]);phase=14
                else:
                    click_panel(411);phase=17
                return .5
            if phase==14:
                label,y=panel_captures[capture_index]
                screenshot(label);click_panel(y);phase=15
                return .5
            if phase==15:
                capture_index+=1
                if capture_index<len(panel_captures):
                    click_panel(panel_captures[capture_index][1]);phase=14
                else:
                    report['integration_checks']['ui_workflow_panels_opened']=True
                    click_panel(411);phase=17
                return .5
            if phase==17:
                if args.subjects:
                    dialog_state=part_state(find_root())
                    assert bpy.ops.hgt.manage_parts('INVOKE_DEFAULT')=={'RUNNING_MODAL'}
                    phase=12
                else:phase=2
                return 1.0
            if phase==12:
                screenshot('group-dialog.png')
                window.event_simulate(type='ESC',value='PRESS')
                window.event_simulate(type='ESC',value='RELEASE')
                phase=13
                return .5
            if phase==13:
                assert part_state(find_root())==dialog_state
                report['subject_checks']['dialog_cancel']=True
                phase=2
                return .5
            if phase==2:
                if args.workflow and not report['integration_checks'].get('ui_cancel_signal_cleanup'):
                    scene=bpy.context.scene
                    scene.hgt_output.filepath=str(out/'cancelled.png')
                    (out/'cancelled.png').write_bytes(b'previous output must survive')
                    report['before_cancel_last_render']=scene.hgt_output.last_render
                    def cancelled(*a,**kw):
                        proxy=bpy.data.scenes[kw['scene']]
                        path=Path(proxy.render.filepath)
                        # A partial writer result must never reach the final path.
                        path.write_bytes(b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',
                            scene.hgt_output.width,scene.hgt_output.height))
                        addon.rendering.render_cancel(proxy)
                        return {'RUNNING_MODAL'}
                    fake=SimpleNamespace(app=bpy.app,context=bpy.context,data=bpy.data,path=bpy.path,
                        ops=SimpleNamespace(render=SimpleNamespace(render=cancelled)))
                    with patch.object(addon.rendering,'bpy',fake):
                        assert bpy.ops.hgt.render()=={'RUNNING_MODAL'}
                    phase=21
                    return .1
                bpy.context.scene.hgt_output.width,bpy.context.scene.hgt_output.height=384,576
                bpy.context.scene.hgt_output.filepath=str(out/'ui-render.png')
                screenshot('output-panel.png')
                bpy.ops.wm.save_as_mainfile(filepath=str(out/'ui-preview.blend'),relative_remap=False)
                assert bpy.ops.hgt.render()=={'RUNNING_MODAL'}
                render_start=time.monotonic()
                phase=3
                return .3
            if phase==21:
                if bpy.context.scene.hgt_output.rendering or bpy.app.is_job_running('RENDER'):
                    return .2
                assert not addon.rendering._JOBS
                assert (out/'cancelled.png').read_bytes()==b'previous output must survive'
                assert bpy.context.scene.hgt_output.last_render==report['before_cancel_last_render']
                assert not list(out.glob('.hgt-*.png'))
                report['cancel_method']='injected_render_cancel_callback_with_partial_file'
                report['native_cancel_input']='pending_user_operation_acceptance'
                report['integration_checks']['ui_cancel_signal_cleanup']=True
                phase=2
                return .2
            if phase==3:
                if bpy.context.scene.hgt_output.rendering or bpy.app.is_job_running('RENDER'):
                    return .3
                assert not addon.rendering._JOBS
                path=out/'ui-render.png'
                assert path.is_file() and path.stat().st_size>1000
                image=bpy.data.images.load(str(path),check_existing=False)
                assert tuple(image.size)==(384,576)
                bpy.data.images.remove(image)
                report['integration_checks']['ui_render_save']=True
                assert bpy.context.scene.hgt_output.last_render==str(path)
                assert addon.panels.HGT_OT_view_render.poll(bpy.context)
                opened=[]
                fake=SimpleNamespace(ops=SimpleNamespace(wm=SimpleNamespace(
                    path_open=lambda **kw:opened.append(kw['filepath']) or {'FINISHED'})))
                with patch.object(addon.panels,'bpy',fake):
                    assert bpy.ops.hgt.view_render()=={'FINISHED'}
                assert opened==[str(path)]
                report['integration_checks']['png_preview']=True
                screenshot('render-complete.png')
                report['render_seconds']=round(time.monotonic()-render_start,2)
                write_report()
                unload_addon(addon)
                better.unregister()
                if mmd:mmd.unregister()
                finish()
                return None
    except Exception:
        error=traceback.format_exc()
        print(error,flush=True)
        finish(error)
        return None
    return .2


bpy.app.timers.register(step,first_interval=.5)
