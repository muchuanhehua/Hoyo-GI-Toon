"""Native rendered playback and image comparison for instance-preserving outlines."""
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
from verification_runtime import install_candidate, load_mmd, file_hash, load_addon
from outline_verification import protected
import numpy as np
from bpy_extras.view3d_utils import location_3d_to_region_2d
parser = argparse.ArgumentParser()
for name in ('output-dir', 'fixture', 'mmd-tools'):
    parser.add_argument('--' + name, type=Path, required=True)
parser.add_argument('--candidate', type=Path)
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
addon = install_candidate(args.candidate, OUT) if args.candidate else load_addon(ROOT)
bpy.ops.wm.open_mainfile(filepath=str(args.fixture), load_ui=False)
scene = bpy.context.scene
payload = Path(addon.__file__).resolve().parent
report = {'scope': 'OUTLINE-PREVIEW-PLAYBACK', 'complete': False, 'cases': [], 'checks': {},
          'package_sha256': file_hash(args.candidate) if args.candidate else None,
          'source_sha256': {p.name: file_hash(p) for p in payload.glob('*.py')},
          'metric': 'Native animation_play, sync NONE, identical hidden rendered viewport and action; private MMD Tools + GI-Toon process, all CPU threads'}
with zipfile.ZipFile(ROOT / 'release/hoyo_gi_toon-2.11.0.zip') as package:
    old = {'__package__': addon.__name__, '__name__': addon.__name__ + '.baseline_workflow'}
    exec(compile(package.read('workflow.py'), '<2.11.0-workflow>', 'exec'), old)
    old_outline = {'__package__': addon.__name__, '__name__': addon.__name__ + '.baseline_outlines'}
    exec(compile(package.read('outlines.py'), '<2.11.0-outlines>', 'exec'), old_outline)
root = scene.hgt_target
graphs = []
for entry in root.hgt_character.meshes:
    mesh = entry.object
    current = next(m for m in mesh.modifiers if m.type == 'NODES' and m.node_group.get('hgt_pmx_outline'))
    new_graph = current.node_group
    baseline_modifier = old_outline['build'](mesh, root)
    old_graph = baseline_modifier.node_group
    mesh.modifiers.remove(baseline_modifier)
    graphs.append((mesh, current.name, old_graph, new_graph))
jobs = ['baseline_2110', 'candidate', 'baseline_repeat', 'candidate_repeat']
state = {'phase': 'init', 'case': 0, 'ticks': [], 'pre': 0, 'started': time.perf_counter(), 'image_case': 0}
window = area = space = region = None
report['viewport_comparisons'] = []


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


def switch(mode, frame=186):
    legacy = mode.startswith('baseline')
    old['reset_runtime_cache']()
    addon.workflow.reset_runtime_cache()
    for handlers, name in ((bpy.app.handlers.frame_change_post, 'update_frame'),
                           (bpy.app.handlers.depsgraph_update_post, 'update_scene'),
                           (bpy.app.handlers.render_pre, 'update_frame')):
        for function in (old[name], getattr(addon.workflow, name)):
            if function in handlers:
                handlers.remove(function)
        handlers.insert(0, old[name] if legacy else getattr(addon.workflow, name))
    for mesh, name, previous, current in graphs:
        mesh.modifiers[name].node_group = previous if legacy else current
    scene.frame_set(frame)
    bpy.context.view_layer.update()


def screenshot(name):
    path = OUT / (name + '.png')
    bpy.ops.screen.screenshot(filepath=str(path))
    image = bpy.data.images.load(str(path), check_existing=False)
    pixels = np.array(image.pixels[:], dtype=np.float32).reshape((image.size[1], image.size[0], 4))
    bpy.data.images.remove(image)
    camera = scene.camera.evaluated_get(bpy.context.evaluated_depsgraph_get())
    corners = [location_3d_to_region_2d(region, space.region_3d, camera.matrix_world @ p)
               for p in camera.data.view_frame(scene=scene)]
    low = [max(8, int(min(p[i] for p in corners)) + 4) for i in range(2)]
    high = [min((region.width, region.height)[i] - 8, int(max(p[i] for p in corners)) - 4) for i in range(2)]
    return pixels[region.y + low[1]:region.y + high[1], region.x + low[0]:region.x + high[0], :3]


def finish(error=None):
    if error:
        report['error'] = error
    for handlers, function in ((bpy.app.handlers.frame_change_pre, pre), (bpy.app.handlers.frame_change_post, post)):
        if function in handlers:
            handlers.remove(function)
    (OUT / 'playback.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print('OUTLINE_PLAYBACK', report['complete'], report.get('error', ''), flush=True)
    bpy.ops.wm.quit_blender()


def step():
    global scene, window, area, space, region
    try:
        if time.perf_counter() - state['started'] > 240:
            raise TimeoutError('Outline playback validation exceeded bounded runtime')
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
                assert [ticks[0][1], ticks[-1][1]] == [193, 228]
                assert all(b[1] == a[1] + 1 for a, b in zip(ticks, ticks[1:])), 'Playback skipped a frame'
                intervals = [(b[0] - a[0]) * 1000 for a, b in zip(ticks, ticks[1:])]
                row = {'mode': jobs[state['case']], 'frames': len(ticks),
                       'fps': (len(ticks) - 1) / (ticks[-1][0] - ticks[0][0]),
                       'interval_median_ms': statistics.median(intervals),
                       'frame_evaluation_median_ms': statistics.median(t[2] for t in ticks),
                       'frame_range': [ticks[0][1], ticks[-1][1]], 'samples_ms': intervals,
                       'objects': len(scene.objects), 'evaluated_vertices': len(graphs[0][0].evaluated_get(
                           bpy.context.evaluated_depsgraph_get()).data.vertices)}
                report['cases'].append(row)
                print('NATIVE_OUTLINE_PLAYBACK', row['mode'], round(row['fps'], 2), flush=True)
                state['case'] += 1
                state['phase'] = 'begin' if state['case'] < len(jobs) else 'image_begin'
                return .3
            if phase == 'undo_start':
                switch('candidate')
                bpy.context.preferences.edit.use_global_undo = True
                state['protected'] = protected(scene.hgt_target)
                bpy.ops.ed.undo_push(message='Native outline preview')
                mesh = scene.hgt_target.hgt_character.meshes[0].object
                mesh.modifiers.new('Verification downstream', 'SOLIDIFY')
                bpy.context.view_layer.update()
                bpy.context.view_layer.update()
                modifier = next(m for m in mesh.modifiers if m.type == 'NODES' and m.node_group.get('hgt_pmx_outline'))
                assert addon.shaders.input_value(modifier, 'Realize Geometry').value
                bpy.ops.ed.undo_push(message='Complete outlines before downstream modifier')
                bpy.ops.ed.undo()
                state['phase'] = 'undo_check'
                return .3
            if phase == 'undo_check':
                mesh = scene.hgt_target.hgt_character.meshes[0].object
                modifier = next(m for m in mesh.modifiers if m.type == 'NODES' and m.node_group.get('hgt_pmx_outline'))
                assert 'Verification downstream' not in mesh.modifiers
                assert not addon.shaders.input_value(modifier, 'Realize Geometry').value
                assert len(mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices) == len(mesh.data.vertices)
                report['checks']['undo_restores_native_preview'] = True
                bpy.ops.ed.redo()
                state['phase'] = 'undo_redo_check'
                return .3
            if phase == 'undo_redo_check':
                mesh = scene.hgt_target.hgt_character.meshes[0].object
                modifier = next(m for m in mesh.modifiers if m.type == 'NODES' and m.node_group.get('hgt_pmx_outline'))
                assert 'Verification downstream' in mesh.modifiers
                assert addon.shaders.input_value(modifier, 'Realize Geometry').value
                assert len(mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices) > len(mesh.data.vertices) * 2
                assert protected(scene.hgt_target) == state['protected']
                report['checks']['redo_restores_complete_geometry'] = True
                report['checks']['undo_redo_preserves_source_actions_and_weights'] = True
                report['complete'] = True
                finish()
                return None
            frame = (186, 201, 228)[state['image_case']]
            if phase == 'image_begin':
                switch('baseline', frame)
                state['phase'] = 'image_baseline'
                return 2
            if phase == 'image_baseline':
                state['baseline_image'] = screenshot(f'{frame}-baseline')
                switch('candidate', frame)
                state['phase'] = 'image_candidate'
                return 2
            if phase == 'image_candidate':
                state['candidate_image'] = screenshot(f'{frame}-candidate')
                switch('baseline', frame)
                state['phase'] = 'image_repeat'
                return 2
            if phase == 'image_repeat':
                repeated = screenshot(f'{frame}-baseline-repeat')
                baseline, candidate = state.pop('baseline_image'), state.pop('candidate_image')
                difference = np.abs(candidate - baseline)
                noise = float(np.abs(repeated - baseline).mean())
                mean = float(difference.mean())
                report['viewport_comparisons'].append({'frame': frame, 'mean_error': mean,
                    'max_error': float(difference.max()), 'baseline_repeat_mean_error': noise})
                assert mean <= max(.001, noise * 2), (frame, mean, noise)
                state['image_case'] += 1
                if state['image_case'] < 3:
                    state['phase'] = 'image_begin'
                    return .2
                report['checks']['natural_playback_no_frame_dropping'] = True
                report['checks']['viewport_geometry_matches_baseline'] = True
                report['checks']['same_objects_and_samples'] = len({r['objects'] for r in report['cases']}) == 1
                state['phase'] = 'undo_start'
                return .2
    except Exception:
        finish(traceback.format_exc())
        return None


bpy.app.timers.register(step, first_interval=1)
