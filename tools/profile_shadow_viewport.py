"""Compare warm 512 px Eevee viewport draws with the immutable 2.6.1 path."""
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
import gpu
import numpy as np
from mathutils import Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verification_runtime import load_addon, install_candidate, load_mmd, load_reference, file_hash


def hide():
    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    @callback
    def each(hwnd, _):
        process = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
        if process.value == os.getpid():ctypes.windll.user32.ShowWindow(hwnd, 0)
        return True
    ctypes.windll.user32.EnumWindows(each, 0)


def main():
    parser = argparse.ArgumentParser()
    for key in ('output-dir', 'fixture-directory', 'mmd-tools'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--candidate', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    project = Path(__file__).resolve().parents[1]
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hide()
    load_mmd(args.mmd_tools, out / '_runtime')
    addon = install_candidate(args.candidate, out) if args.candidate else load_addon(project)
    if bpy.app.timers.is_registered(addon.project_io._migrate_open_project):
        bpy.app.timers.unregister(addon.project_io._migrate_open_project)
    legacy = load_reference(project / 'release/hoyo_gi_toon-2.6.1.zip', out / '_reference')
    payload = Path(addon.__file__).resolve().parent
    report = {'scope': 'GI-TOON-SHADOW-VIEWPORT', 'complete': False, 'models': [],
              'source_sha256': {p.name: file_hash(p) for p in payload.glob('*.py')},
              'package_sha256': file_hash(args.candidate) if args.candidate else None,
              'measurement': '512x512 Eevee material preview plus GPU readback; warm shaders; CPU and GPU combined'}
    try:
        for name in ('安柏', '纳西妲', '奥黛塔'):
            bpy.app.handlers.load_post.remove(addon.project_io.on_load)
            try:bpy.ops.wm.open_mainfile(filepath=str(args.fixture_directory / name / 'model.blend'), load_ui=False)
            finally:bpy.app.handlers.load_post.append(addon.project_io.on_load)
            hide()
            scene, root = bpy.context.scene, bpy.context.scene.hgt_target
            legacy.project_io.on_load(None)
            s = root.hgt_character
            s.outline = .18
            s.shadow_softness = .001
            owned = {entry.object for entry in s.meshes}
            for obj in scene.objects:
                if obj.type == 'MESH' and obj not in owned:obj.hide_render = obj.hide_viewport = True
            points = [obj.matrix_world @ Vector(c) for obj in owned for c in obj.bound_box]
            low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
            high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
            height = high.z - low.z
            center = Vector(((low.x + high.x) * .5, 0, low.z + height * .82))
            scene.camera.location = center + Vector((0, -height * 3, 0))
            scene.camera.rotation_euler = (center - scene.camera.location).to_track_quat('-Z', 'Y').to_euler()
            scene.camera.data.ortho_scale = height * .34
            addon.lighting.apply_preset(scene, 'DEFAULT')
            parameters = addon.lighting.active_parameters(scene)
            parameters.azimuth, parameters.elevation = 1.8, .25
            window = bpy.context.window_manager.windows[0]
            area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
            region = next(r for r in area.regions if r.type == 'WINDOW')
            space = area.spaces.active
            space.shading.type = 'MATERIAL'
            space.shading.use_scene_lights = True
            space.shading.use_scene_world = True
            space.overlay.show_overlays = False
            row = {'name': name}
            with bpy.context.temp_override(window=window, area=area, region=region):
                offscreen = gpu.types.GPUOffScreen(512, 512, format='RGBA16F')
                try:
                    for label in ('legacy', 'current'):
                        if label == 'current':
                            addon.project_io.on_load(None)
                            s.shadow_softness = .3
                        durations = []
                        frames = []
                        for index in range(15):
                            start = time.perf_counter()
                            parameters.azimuth = 1.65 + index * .012
                            bpy.context.view_layer.update()
                            depsgraph = bpy.context.evaluated_depsgraph_get()
                            projection = scene.camera.calc_matrix_camera(depsgraph, x=512, y=512)
                            offscreen.draw_view3d(scene, bpy.context.view_layer, space, region,
                                                 scene.camera.matrix_world.inverted(), projection,
                                                 do_color_management=False, draw_background=False)
                            pixels = np.array(offscreen.texture_color.read(), dtype=np.float32)
                            if index > 3:
                                durations.append((time.perf_counter() - start) * 1000)
                                frames.append(pixels)
                        assert float(np.abs(frames[-1]).max()) > .1
                        response = float(np.abs(frames[-1] - frames[0]).max())
                        assert response > .001, (name, label, 'Viewport did not update')
                        row[label] = {'median_ms': statistics.median(durations), 'max_ms': max(durations), 'light_response': response}
                finally:offscreen.free()
            row['ratio'] = row['current']['median_ms'] / row['legacy']['median_ms']
            assert row['current']['median_ms'] <= row['legacy']['median_ms'] * 1.6 + 8, row
            report['models'].append(row)
            print('HGT_SHADOW_VIEWPORT_MODEL', name, row, flush=True)
        report['complete'] = True
    except Exception:
        report['error'] = traceback.format_exc()
        print(report['error'], flush=True)
    assert report['source_sha256'] == {p.name: file_hash(p) for p in payload.glob('*.py')}
    (out / 'shadow-viewport.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    bpy.ops.wm.quit_blender()


if __name__ == '__main__':main()
