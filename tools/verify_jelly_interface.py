"""Hidden-window checks for live jelly controls, undo and character glow."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import traceback
import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verification_runtime import load_mmd, load_addon, install_candidate, file_hash

parser = argparse.ArgumentParser()
parser.add_argument('--output-dir', type=Path, required=True)
parser.add_argument('--fixture', type=Path, required=True)
parser.add_argument('--mmd-tools', type=Path, required=True)
parser.add_argument('--candidate', type=Path)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
OUT = args.output_dir.resolve()
assert OUT.is_relative_to(ROOT / '.verification')
OUT.mkdir(parents=True, exist_ok=True)
callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
@callback
def hide(hwnd, _):
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid():
        ctypes.windll.user32.ShowWindow(hwnd, 0)
    return True
ctypes.windll.user32.EnumWindows(hide, 0)
load_mmd(args.mmd_tools, OUT / '_runtime')
addon = install_candidate(args.candidate, OUT) if args.candidate else load_addon(ROOT)
payload = Path(addon.__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(args.fixture), load_ui=False)
bpy.context.preferences.edit.use_global_undo = True
window = bpy.context.window_manager.windows[0]
area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
space = area.spaces.active
phase = -2
baseline = None
images = {}
report = dict(scope='GI-TOON-JELLY-UI', complete=False, checks={},
              source_sha256={p.name: file_hash(p) for p in payload.glob('*.py')},
              package_sha256=file_hash(args.candidate) if args.candidate else None)


def counts():
    return {k: len(getattr(bpy.data, k)) for k in ('objects', 'collections', 'meshes', 'node_groups', 'actions')}


def root():
    return next(o for o in bpy.context.scene.objects if addon.scene_models.model_root(o))


def capture(name):
    path = OUT / (name + '.png')
    bpy.ops.screen.screenshot(filepath=str(path))
    image = bpy.data.images.load(str(path), check_existing=False)
    w, h = image.size
    data = np.array(image.pixels[:], dtype=np.float32).reshape((h, w, 4))
    bpy.data.images.remove(image)
    ui = next(r for r in area.regions if r.type == 'UI')
    return data[area.y + 50:area.y + area.height - 50, area.x + 40:ui.x - 5].copy()


def finish(error=None):
    if error:
        report['error'] = error
    if report['source_sha256'] != {p.name: file_hash(p) for p in payload.glob('*.py')}:
        report['complete'] = False
        report['error'] = (report.get('error', '') + '\nRuntime source changed during verification').strip()
    (OUT / 'ui.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print('HGT_JELLY_UI', report, flush=True)
    bpy.ops.wm.quit_blender()


def step():
    global phase, baseline
    try:
        scene = bpy.context.scene
        with bpy.context.temp_override(window=window, area=area):
            if phase == -2:
                space.show_region_ui = True
                space.shading.type = 'MATERIAL'
                space.shading.use_scene_world = space.shading.use_scene_lights = True
                space.region_3d.view_perspective = 'CAMERA'
            elif phase == -1:
                next(r for r in area.regions if r.type == 'UI').active_panel_category = 'GI-Toon'
            elif phase == 0:
                if addon.jelly_eye.is_active(root()):
                    assert bpy.ops.hgt.toggle_jelly_eye() == {'FINISHED'}
                scene.frame_set(1)
                baseline = counts()
                bpy.ops.ed.undo_push(message='Before jelly')
                assert bpy.ops.hgt.toggle_jelly_eye() == {'FINISHED'}
                bpy.ops.ed.undo_push(message='Jelly enabled')
                assert addon.jelly_eye.is_active(root())
                report['checks']['panel_and_operator'] = True
            elif phase == 1:
                assert bpy.ops.ed.undo() == {'FINISHED'}
                assert not addon.jelly_eye.is_active(root()) and counts() == baseline
            elif phase == 2:
                assert bpy.ops.ed.redo() == {'FINISHED'}
                assert addon.jelly_eye.is_active(root()) and not addon.jelly_eye.error(root())
                report['checks']['enable_undo_redo'] = True
                root().hgt_jelly.amount = 0
                bpy.ops.ed.undo_push(message='Jelly zero')
            elif phase == 3:
                images['zero'] = capture('zero')
                root().hgt_jelly.amount = 1
                bpy.ops.ed.undo_push(message='Jelly full')
            elif phase == 4:
                images['on'] = capture('on')
                response = float(np.abs(images['on'] - images['zero']).max())
                assert response > .02, response
                report['viewport_response'] = response
                report['checks']['live_slider_in_material_view'] = True
                assert bpy.ops.ed.undo() == {'FINISHED'}
                assert root().hgt_jelly.amount == 0
            elif phase == 5:
                assert bpy.ops.ed.redo() == {'FINISHED'}
                assert root().hgt_jelly.amount == 1
                report['checks']['parameter_undo_redo'] = True
                bpy.context.scene.frame_set(1)
                bpy.ops.screen.animation_play()
            elif phase == 6:
                assert scene.frame_current != 1
                bpy.ops.screen.animation_cancel(restore_frame=False)
                scene.frame_set(1)
                report['checks']['native_playback'] = True
                assert bpy.ops.hgt.toggle_glow() == {'FINISHED'}
                scene.hgt_glow.threshold = .2
            elif phase == 7:
                assert not scene.hgt_glow.error
                record = addon.glow_preview._records.get(scene.as_pointer(), {})
                assert record.get('draws', 0) > 0, record
                report['glow_initial_draws'] = record['draws']
                root().hgt_jelly.amount = 0
            elif phase == 8:
                record = addon.glow_preview._records[scene.as_pointer()]
                assert record['draws'] > report['glow_initial_draws'], (record, report)
                capture('with-glow')
                report['checks']['glow_refreshes_when_jelly_changes'] = True
                assert bpy.ops.hgt.toggle_jelly_eye() == {'FINISHED'}
            elif phase == 9:
                assert not addon.jelly_eye.is_active(root())
                assert not any(o.get(addon.jelly_eye.OWNER) for o in bpy.data.objects)
                assert not any(t.get(addon.jelly_eye.OWNER) for t in bpy.data.node_groups)
                report['checks']['disable_jelly_with_glow_active_cleans_resources'] = True
                assert bpy.ops.hgt.toggle_jelly_eye() == {'FINISHED'}
                root().hgt_jelly.amount = 1
            elif phase == 10:
                assert not addon.jelly_eye.error(root()) and not scene.hgt_glow.error
                assert bpy.ops.hgt.toggle_glow() == {'FINISHED'}
            elif phase == 11:
                assert bpy.ops.hgt.toggle_jelly_eye() == {'FINISHED'}
                assert counts() == baseline, (counts(), baseline)
                report['checks']['both_enable_orders_restore_resources'] = True
                report['complete'] = True
                finish()
                return None
        phase += 1
        return 8 if phase in {-1, 7, 8, 9, 10} else 1.2
    except Exception:
        finish(traceback.format_exc())
        return None


# Wait until the window is initialized before changing sidebar regions.
bpy.app.timers.register(step, first_interval=2)
