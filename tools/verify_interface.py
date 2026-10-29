"""Exercise real UI operators in a separate hidden Blender window."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

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
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
project=Path(__file__).resolve().parents[1]
out=args.output_dir.resolve()
assert out.is_relative_to(project/'.verification')
out.mkdir(parents=True,exist_ok=True)
index=json.loads(args.assets_index.read_text(encoding='utf-8'))
report={'package_sha256':file_hash(args.candidate) if args.candidate else None,'integration_checks':{},'screenshots':[]}
phase=-1
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


def finish(error=None):
    if error:
        report['error']=error
    write_report()
    print('HGT_INTERFACE_COMPLETE' if not error else 'HGT_INTERFACE_FAILED',flush=True)
    bpy.ops.wm.quit_blender()


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


def step():
    global phase,render_start,uid
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
                if mmd: better.unregister()
                assert bpy.ops.hgt.import_character(filepath=index['models'][1]['path'])=={'FINISHED'}
                if mmd: better.register()
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
                dependency=mmd if mmd else better
                dependency.unregister()
                try: bpy.ops.hgt.import_character(filepath=index['models'][0]['path'])
                except RuntimeError as exc: assert ('MMD Tools' if mmd else 'Better FBX') in str(exc)
                else: raise AssertionError('Missing-dependency operator did not report an error')
                dependency.register()
                report['integration_checks']['ui_errors']=True
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
                output_panel=addon.panels.HGT_PT_output
                bpy.utils.unregister_class(output_panel)
                output_panel.bl_options=set()
                bpy.utils.register_class(output_panel)
                phase=2
                return 1.0
            if phase==2:
                screenshot('output-panel.png')
                bpy.ops.wm.save_as_mainfile(filepath=str(out/'ui-preview.blend'),relative_remap=False)
                assert bpy.ops.hgt.render()=={'RUNNING_MODAL'}
                render_start=time.monotonic()
                phase=3
                return .3
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
