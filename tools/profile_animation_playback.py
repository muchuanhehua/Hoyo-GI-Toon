"""Native rendered playback A/B/A/B, final panorama and undo in a private UI."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import statistics
import sys
import time
import traceback
import zipfile

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verification_runtime import install_candidate, load_mmd, file_hash
parser = argparse.ArgumentParser()
for name in ('output-dir', 'fixture', 'mmd-tools', 'candidate'):
    parser.add_argument('--' + name, type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
OUT = args.output_dir.resolve()
assert OUT.is_relative_to(ROOT / '.verification')
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
payload = Path(addon.__file__).resolve().parent
report = {'scope': 'STAGE-ANIMATION-PLAYBACK', 'complete': False, 'cases': [], 'checks': {},
          'package_sha256': file_hash(args.candidate),
          'source_sha256': {p.name: file_hash(p) for p in payload.glob('*.py')},
          'metric': 'Native animation_play, sync NONE, identical hidden rendered viewport and action; private MMD Tools + GI-Toon process, all CPU threads'}
with zipfile.ZipFile(ROOT / 'release/hoyo_gi_toon-2.10.0.zip') as package:
    old = {'__package__': addon.__name__, '__name__': addon.__name__ + '.baseline_workflow'}
    exec(compile(package.read('workflow.py'), '<2.10.0-workflow>', 'exec'), old)
    old_shader = dict(addon.shaders.__dict__)
    exec(compile(package.read('shaders.py'), '<2.10.0-shaders>', 'exec'), old_shader)
new_controls = addon.shaders.set_controls
jobs = ['baseline_2100', 'candidate_2110', 'baseline_repeat', 'candidate_repeat', 'candidate_panorama']
state = {'phase': 'init', 'case': 0, 'ticks': [], 'pre': 0, 'started': time.perf_counter()}
window = area = space = None


def pre(scene, graph=None):
    if state['phase'] in {'warm', 'measure'}:
        state['pre'] = time.perf_counter()


def post(scene, graph=None):
    if state['phase'] in {'warm', 'measure'}:
        now = time.perf_counter()
        if state['phase'] == 'warm':
            if scene.frame_current >= 192:
                state['ticks'] = []
                state['phase'] = 'measure'
        else:
            state['ticks'].append((now, scene.frame_current, (now - state['pre']) * 1000))


def switch(mode):
    root = scene.hgt_target
    addon.animation_uniforms.freeze(root)
    addon.workflow.reset_runtime_cache()
    legacy = mode.startswith('baseline')
    for handlers, name in ((bpy.app.handlers.frame_change_post, 'update_frame'),
                           (bpy.app.handlers.depsgraph_update_post, 'update_scene'),
                           (bpy.app.handlers.render_pre, 'update_frame')):
        for function in (old[name], getattr(addon.workflow, name)):
            if function in handlers:
                handlers.remove(function)
        handlers.insert(0, old[name] if legacy else getattr(addon.workflow, name))
    addon.shaders.set_controls = old_shader['set_controls'] if legacy else new_controls
    scene.frame_set(186)


def finish(error=None):
    if error:
        report['error'] = error
    for handlers, function in ((bpy.app.handlers.frame_change_pre, pre), (bpy.app.handlers.frame_change_post, post)):
        if function in handlers:
            handlers.remove(function)
    (OUT / 'playback.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print('STAGE_PLAYBACK', report['complete'], report.get('error', ''), flush=True)
    bpy.ops.wm.quit_blender()


def step():
    global scene, window, area, space
    try:
        if time.perf_counter() - state['started'] > 240:
            raise TimeoutError('Playback validation exceeded bounded runtime')
        window = bpy.context.window_manager.windows[0]
        area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
        region = next(r for r in area.regions if r.type == 'WINDOW')
        space = area.spaces.active
        with bpy.context.temp_override(window=window, area=area, region=region):
            scene = bpy.context.scene
            phase = state['phase']
            if phase == 'init':
                space.shading.type = 'RENDERED'
                space.shading.use_compositor = 'ALWAYS'
                space.overlay.show_overlays = False
                space.show_gizmo = False
                space.show_region_ui = False
                space.show_region_toolbar = False
                space.camera = scene.camera
                space.region_3d.view_perspective = 'CAMERA'
                scene.sync_mode = 'NONE'
                scene.frame_start, scene.frame_end = 186, 400
                report['viewport_size'] = [region.width, region.height]
                report['settings'] = {'samples': scene.eevee.taa_samples, 'raytracing': scene.eevee.use_raytracing,
                                      'fps_target': scene.render.fps, 'objects': len(scene.objects)}
                bpy.app.handlers.frame_change_pre.append(pre)
                bpy.app.handlers.frame_change_post.append(post)
                state['phase'] = 'begin'
                return 2
            if phase == 'begin':
                switch(jobs[state['case']])
                state['ticks'] = []
                state['phase'] = 'warm'
                bpy.ops.screen.animation_play()
                return .1
            if phase == 'warm':
                return .1
            if phase == 'measure':
                if len(state['ticks']) < 36:
                    return .1
                bpy.ops.screen.animation_cancel(restore_frame=False)
                ticks = state['ticks'][:36]
                assert len(ticks) >= 6, len(ticks)
                assert [ticks[0][1], ticks[-1][1]] == [193, 228]
                assert all(b[1] == a[1] + 1 for a, b in zip(ticks, ticks[1:])), 'Playback skipped a frame'
                intervals = [(b[0] - a[0]) * 1000 for a, b in zip(ticks, ticks[1:])]
                row = {'mode': jobs[state['case']], 'frames': len(ticks),
                       'fps': (len(ticks) - 1) / (ticks[-1][0] - ticks[0][0]),
                       'interval_median_ms': statistics.median(intervals),
                       'frame_evaluation_median_ms': statistics.median(t[2] for t in ticks),
                       'frame_range': [ticks[0][1], ticks[-1][1]], 'samples_ms': intervals,
                       'objects': len(scene.objects), 'cameras': sum(o.type == 'CAMERA' for o in scene.objects),
                       'stage_layout': scene.hgt_scene.collection.get('hgt_scene_layout', 'legacy')}
                report['cases'].append(row)
                print('NATIVE_PLAYBACK', row['mode'], round(row['fps'], 2), round(row['frame_evaluation_median_ms'], 2), flush=True)
                state['case'] += 1
                if state['case'] == len(jobs):
                    assert row['cameras'] == 1 and row['stage_layout'] == 'panorama-360-v1'
                    report['complete'] = True
                    finish()
                    return None
                state['phase'] = 'undo_start' if state['case'] == 4 else 'begin'
                return .3
            if phase == 'undo_start':
                switch('candidate')
                bpy.context.preferences.edit.use_global_undo = True
                bpy.ops.ed.undo_push(message='Original animated stage')
                scene.hgt_scene_preset = 'STAGE'
                assert bpy.ops.hgt.load_scene() == {'FINISHED'}
                bpy.ops.ed.undo_push(message='Panoramic stage and one camera')
                assert sum(o.type == 'CAMERA' for o in scene.objects) == 1
                bpy.ops.ed.undo()
                state['phase'] = 'undo_check'
                return .3
            if phase == 'undo_check':
                assert sum(o.type == 'CAMERA' for o in scene.objects) == 3
                bpy.ops.ed.redo()
                state['phase'] = 'redo_check'
                return .3
            if phase == 'redo_check':
                assert sum(o.type == 'CAMERA' for o in scene.objects) == 1
                assert scene.camera.parent and scene.camera.animation_data.action
                assert set(addon.workflow.tracked_roots()) == {o for o in bpy.data.objects if addon.workflow.current(o)}
                scene.frame_set(193)
                graph = bpy.context.evaluated_depsgraph_get()
                root = scene.hgt_target
                expected = addon.lighting.shader_vectors(root, graph)
                assert max(abs(a - b) for key, value in expected.items()
                           for a, b in zip(graph.scene_eval[f'hgt_{root.hgt_character.uid}_{key}'][:3], value)) < 2e-6
                report['checks']['legacy_scene_migration_undo_redo'] = True
                report['checks']['undo_redo_rebuilds_character_and_native_driver_caches'] = True
                report['checks']['natural_playback_no_frame_dropping'] = True
                state['phase'] = 'begin'
                return .3
    except Exception:
        finish(traceback.format_exc())
        return None


bpy.app.timers.register(step, first_interval=1)
