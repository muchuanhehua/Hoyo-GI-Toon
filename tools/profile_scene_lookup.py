"""Actual-package native playback and undo/redo for scene membership queries."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import statistics
import sys
import time
import traceback

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verification_runtime import install_candidate, load_mmd, file_hash
from outline_verification import protected
from scene_lookup_verification import LookupRoutes

parser = argparse.ArgumentParser()
for name in ('output-dir', 'candidate', 'fixture', 'mmd-tools'):
    parser.add_argument('--' + name, type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
OUT = args.output_dir.resolve()
OUT.mkdir(parents=True, exist_ok=True)
callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
@callback
def hide(hwnd, unused):
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid():
        ctypes.windll.user32.ShowWindow(hwnd, 0)
    return True
ctypes.windll.user32.EnumWindows(hide, 0)
load_mmd(args.mmd_tools, OUT / '_runtime')
addon = install_candidate(args.candidate, OUT)
bpy.ops.wm.open_mainfile(filepath=str(args.fixture), load_ui=False)
scene = bpy.context.scene
routes = LookupRoutes(addon)
jobs = ['baseline_priming', 'baseline', 'candidate', 'baseline_repeat', 'candidate_repeat']
state = {'phase': 'init', 'case': 0, 'ticks': [], 'pre': 0, 'started': time.perf_counter()}
report = {'scope': 'SCENE-LOOKUP-PLAYBACK', 'complete': False, 'cases': [], 'checks': {},
          'package_sha256': file_hash(args.candidate),
          'source_sha256': {p.name: file_hash(p) for p in Path(addon.__file__).parent.glob('*.py')},
          'metric': 'Native animation_play, sync NONE, all CPU threads, 128 samples and original raytracing/compositor; one full priming pass retained separately'}


def pre(scene, graph=None):
    if state['phase'] in {'warm', 'measure'}:
        state['pre'] = time.perf_counter()


def post(scene, graph=None):
    if state['phase'] == 'warm' and scene.frame_current >= 192:
        state['ticks'] = []
        state['phase'] = 'measure'
    elif state['phase'] == 'measure':
        now = time.perf_counter()
        state['ticks'].append((now, scene.frame_current, (now - state['pre']) * 1000))


def save():
    (OUT / 'playback.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), 'utf-8')


def finish(error=None):
    if error:
        report['error'] = error
    save()
    bpy.ops.wm.quit_blender()


def step():
    global scene
    try:
        assert time.perf_counter() - state['started'] < 240, 'Playback verification timeout'
        window = bpy.context.window_manager.windows[0]
        area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
        region = next(r for r in area.regions if r.type == 'WINDOW')
        space = area.spaces.active
        with bpy.context.temp_override(window=window, area=area, region=region):
            scene = bpy.context.scene
            phase = state['phase']
            if phase == 'init':
                space.overlay.show_overlays = False
                space.show_gizmo = False
                space.show_region_ui = False
                space.show_region_toolbar = False
                space.camera = scene.camera
                space.region_3d.view_perspective = 'CAMERA'
                space.shading.type = 'RENDERED'
                space.shading.use_compositor = 'ALWAYS'
                scene.sync_mode = 'NONE'
                scene.frame_start, scene.frame_end = 186, 400
                report['viewport'] = [region.width, region.height]
                report['settings'] = {'samples': scene.eevee.taa_samples, 'raytracing': scene.eevee.use_raytracing,
                                      'objects': len(scene.objects), 'glow': addon.glow.is_active(scene),
                                      'compositor': space.shading.use_compositor}
                bpy.app.handlers.frame_change_pre.append(pre)
                bpy.app.handlers.frame_change_post.append(post)
                state['phase'] = 'begin'
                return 2
            if phase == 'begin':
                routes.select(jobs[state['case']])
                scene.frame_set(186)
                bpy.context.view_layer.update()
                state['phase'] = 'start'
                return 1
            if phase == 'start':
                state['ticks'] = []
                state['phase'] = 'warm'
                bpy.ops.screen.animation_play()
                return .1
            if phase == 'warm':
                return .1
            if phase == 'measure':
                if len(state['ticks']) < 96:
                    return .1
                bpy.ops.screen.animation_cancel(restore_frame=False)
                ticks = state['ticks'][:96]
                assert [t[1] for t in ticks] == list(range(193, 289)), 'Frame dropping'
                intervals = [(b[0] - a[0]) * 1000 for a, b in zip(ticks, ticks[1:])]
                row = {'case': jobs[state['case']], 'fps': 95 / (ticks[-1][0] - ticks[0][0]),
                       'interval_ms': statistics.median(intervals), 'evaluation_ms': statistics.median(t[2] for t in ticks),
                       'frame_range': [193, 288], 'frames': 96, 'samples_ms': intervals,
                       'evaluation_samples_ms': [t[2] for t in ticks]}
                if state['case'] == 0:
                    report['priming'] = row
                else:
                    report['cases'].append(row)
                save()
                print('LOOKUP_PLAYBACK', row['case'], row['fps'], row['evaluation_ms'], flush=True)
                state['case'] += 1
                state['phase'] = 'begin' if state['case'] < len(jobs) else 'undo_start'
                return .3
            if phase == 'undo_start':
                routes.select('candidate')
                bpy.context.preferences.edit.use_global_undo = True
                state['protected'] = protected(scene.hgt_target)
                collection = bpy.data.collections.new('Private lookup undo collection')
                scene.collection.children.link(collection)
                obj = bpy.data.objects.new('Private lookup undo object', None)
                collection.objects.link(obj)
                bpy.context.view_layer.update()
                assert addon.scene_models.in_scene(obj, scene)
                bpy.ops.ed.undo_push(message='Linked object membership')
                collection.objects.unlink(obj)
                assert not addon.scene_models.in_scene(obj, scene)
                bpy.ops.ed.undo_push(message='Unlinked object membership')
                bpy.ops.ed.undo()
                state['phase'] = 'undo_check'
                return .3
            if phase == 'undo_check':
                obj = bpy.data.objects['Private lookup undo object']
                assert addon.scene_models.in_scene(obj, scene)
                report['checks']['undo_restores_membership'] = True
                bpy.ops.ed.redo()
                state['phase'] = 'redo_check'
                return .3
            if phase == 'redo_check':
                obj = bpy.data.objects['Private lookup undo object']
                assert not addon.scene_models.in_scene(obj, scene)
                report['checks']['redo_removes_membership'] = True
                bpy.data.objects.remove(obj, do_unlink=True)
                bpy.data.collections.remove(bpy.data.collections['Private lookup undo collection'])
                assert protected(scene.hgt_target) == state['protected']
                report['checks']['undo_redo_preserves_sources_and_actions'] = True
                report['checks']['native_playback_no_frame_dropping'] = True
                report['checks']['same_quality_and_scene'] = (
                    scene.eevee.taa_samples == report['settings']['samples']
                    and scene.eevee.use_raytracing == report['settings']['raytracing']
                    and len(scene.objects) == report['settings']['objects']
                    and addon.glow.is_active(scene) == report['settings']['glow'])
                assert report['checks']['same_quality_and_scene']
                scene.frame_set(186)
                state['phase'] = 'capture'
                return 2
            if phase == 'capture':
                bpy.ops.screen.screenshot(filepath=str(OUT / 'native-preview.png'))
                report['complete'] = True
                finish()
                return None
    except Exception:
        finish(traceback.format_exc())
        return None

bpy.app.timers.register(step, first_interval=1)
