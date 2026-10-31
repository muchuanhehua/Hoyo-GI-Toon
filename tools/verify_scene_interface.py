"""Verify the scene controls and actual undo/redo in an isolated UI process."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time
import traceback
import bpy

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verification_runtime import load_addon, install_candidate, file_hash

parser = argparse.ArgumentParser()
for name in ('output-dir', 'mmd-tools', 'assets-index'):
    parser.add_argument('--' + name, type=Path, required=True)
parser.add_argument('--candidate', type=Path)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
project = Path(__file__).resolve().parents[1]
out = args.output_dir.resolve()
assert out.is_relative_to(project / '.verification')
out.mkdir(parents=True, exist_ok=True)


def hide():
    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    @callback
    def each(hwnd, unused):
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            ctypes.windll.user32.ShowWindow(hwnd, 0)
        return True
    ctypes.windll.user32.EnumWindows(each, 0)


hide()
addon = install_candidate(args.candidate, out) if args.candidate else load_addon(project)
payload = Path(addon.__file__).resolve().parent
hashes = {p.name: file_hash(p) for p in payload.glob('*.py')}
assets = {name: file_hash(payload / 'assets' / name) for name in
          ('scenes.json', 'scene_city_terrace.blend', 'scene_stage.blend')}
report = {'scope': 'SCENE-PRESETS-UI', 'source_sha256': hashes, 'asset_sha256': assets,
          'package_sha256': file_hash(args.candidate) if args.candidate else None, 'checks': {}, 'screenshots': []}
bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
bpy.context.preferences.edit.use_global_undo = True
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.view.render_display_type = 'NONE'
scene = bpy.context.scene
camera = addon.rendering.prepare(scene)
camera.location = (4, -5, 3)
light = addon.lighting.default_light(scene)
original = (scene.world.name if scene.world else None, camera.name, light.name)
phase = 0
started = time.monotonic()


def assert_original(scene):
    assert scene.hgt_scene.collection is None
    assert (scene.world.name if scene.world else None, scene.camera.name, scene.hgt_light.name) == original
    assert tuple(scene.camera.location) == (4, -5, 3)
    assert not scene.hgt_light.hide_render and not scene.hgt_light.hide_viewport


def assert_loaded(scene, key):
    state = scene.hgt_scene
    assert state.preset == key and state.collection in scene.collection.children_recursive
    assert scene.camera == state.camera and scene.hgt_light == state.light and scene.world == state.world
    assert state.muted_light and state.muted_light.hide_render and state.muted_light.hide_viewport
    assert len([c for c in scene.collection.children if c.get('hgt_scene_asset')]) == 1
    assert all(image.packed_file for image in bpy.data.images if image.get(addon.panels.scene_presets.OWNER) == state.uid)


def screenshot(name):
    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)
    assert bpy.ops.screen.screenshot(filepath=str(out / name)) == {'FINISHED'}
    report['screenshots'].append(name)


def finish(error=None):
    if error:
        report['error'] = error
    else:
        assert hashes == {p.name: file_hash(p) for p in payload.glob('*.py')}
        assert assets == {name: file_hash(payload / 'assets' / name) for name in assets}
        report['complete'] = True
    (out / 'scene-interface.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print('HGT_SCENE_UI_FAILED' if error else 'HGT_SCENE_UI_PASSED', flush=True)
    bpy.ops.wm.quit_blender()


def step():
    global phase
    try:
        hide()
        if time.monotonic() - started > 90:
            raise TimeoutError('Scene preset UI verification timed out')
        window = bpy.context.window_manager.windows[0]
        area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
        region = next(r for r in area.regions if r.type == 'WINDOW')
        with bpy.context.temp_override(window=window, area=area, region=region):
            scene = bpy.context.scene
            if phase == 0:
                area.spaces.active.show_region_ui = True
                phase = 1
                return .5
            if phase == 1:
                next(r for r in area.regions if r.type == 'UI').active_panel_category = 'Hoyo-GI-Toon'
                phase = 2
                return .5
            if phase == 2:
                assert addon.panels.HGT_OT_load_scene.poll(bpy.context)
                assert not addon.panels.HGT_OT_remove_scene.poll(bpy.context)
                assert addon.panels.target(bpy.context) is None
                screenshot('panel-empty.png')
                report['checks']['always_visible_without_model'] = True
                bpy.ops.ed.undo_push(message='Original scene')
                scene.hgt_scene_preset = 'CITY_TERRACE'
                assert bpy.ops.hgt.load_scene() == {'FINISHED'}
                bpy.ops.ed.undo_push(message='City terrace')
            elif phase == 3:
                assert_loaded(scene, 'CITY_TERRACE')
                screenshot('panel-city.png')
                assert bpy.ops.ed.undo() == {'FINISHED'}
            elif phase == 4:
                assert_original(scene)
                assert bpy.ops.ed.redo() == {'FINISHED'}
            elif phase == 5:
                assert_loaded(scene, 'CITY_TERRACE')
                report['checks']['load_undo_redo'] = True
                scene.hgt_scene_preset = 'STAGE'
                assert bpy.ops.hgt.load_scene() == {'FINISHED'}
                bpy.ops.ed.undo_push(message='Stage')
            elif phase == 6:
                assert_loaded(scene, 'STAGE')
                screenshot('panel-stage.png')
                assert bpy.ops.ed.undo() == {'FINISHED'}
            elif phase == 7:
                assert_loaded(scene, 'CITY_TERRACE')
                assert bpy.ops.ed.redo() == {'FINISHED'}
            elif phase == 8:
                assert_loaded(scene, 'STAGE')
                report['checks']['switch_undo_redo'] = True
                assert bpy.ops.hgt.remove_scene() == {'FINISHED'}
                bpy.ops.ed.undo_push(message='Removed preset')
            elif phase == 9:
                assert_original(scene)
                assert bpy.ops.ed.undo() == {'FINISHED'}
            elif phase == 10:
                assert_loaded(scene, 'STAGE')
                assert bpy.ops.ed.redo() == {'FINISHED'}
            elif phase == 11:
                assert_original(scene)
                report['checks']['remove_undo_redo'] = True
                finish()
                return None
            phase += 1
            return .35
    except Exception:
        error = traceback.format_exc()
        print(error, flush=True)
        finish(error)
        return None


bpy.app.timers.register(step, first_interval=.5)
