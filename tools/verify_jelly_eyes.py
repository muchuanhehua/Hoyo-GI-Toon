"""Private Blender checks for bounded, additive jelly eyes on real MMD fixtures."""
import argparse
import json
from pathlib import Path
import sys
import time
import traceback
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verification_runtime import load_addon, load_mmd, install_candidate, file_hash
from verification_data import mesh_data, digest


def coordinates(obj):
    bpy.context.view_layer.update()
    data = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    values = np.empty(len(data.vertices) * 3, dtype=np.float32)
    data.vertices.foreach_get('co', values)
    return values.reshape((-1, 3)).copy()


def protected(root):
    meshes = addon.scene_models.meshes(root)
    rig = addon.scene_models.armature(root)
    actions = {}
    for action in bpy.data.actions:
        actions[action.name] = [(f.data_path, f.array_index,
                                [(list(k.co), k.interpolation, list(k.handle_left), list(k.handle_right)) for k in f.keyframe_points])
                               for layer in action.layers for strip in layer.strips for bag in strip.channelbags for f in bag.fcurves]
    return digest(dict(meshes={o.name: mesh_data(o.data) for o in meshes},
                       weights={o.name: [[(g.group, g.weight) for g in v.groups] for v in o.data.vertices] for o in meshes},
                       parents={o.name: (o.parent.name if o.parent else '', o.parent_type, o.parent_bone) for o in meshes},
                       slots={o.name: [(s.link, s.material.name if s.material else '') for s in o.material_slots] for o in meshes},
                       bones=[(b.name, b.parent.name if b.parent else '', list(b.head_local), list(b.tail_local)) for b in rig.data.bones],
                       constraints={b.name: [(c.name, c.type, c.mute, c.influence) for c in b.constraints] for b in rig.pose.bones},
                       actions=actions))


def counts():
    return {name: len(getattr(bpy.data, name)) for name in ('objects', 'collections', 'meshes', 'node_groups', 'actions', 'shape_keys')}


def motion(root):
    rig = addon.scene_models.armature(root)
    tracked = addon.scene_models.tracked(root, bpy.context.scene)
    if tracked and tracked.hgt_character.look_camera:
        addon.gaze.clear_gaze(tracked)
    bones = addon.jelly_eye.eye_bones(rig)
    head = addon.gaze.head_bone(root)
    control = next((b for b in rig.pose.bones if b.name == '両目'), None)
    values = [head, *(rig.pose.bones[b.name] for b in bones.values())]
    if control:
        values.append(control)
    for frame, value in ((1, 0), (7, 1), (13, -.8), (19, .5), (25, 0)):
        for bone in values:
            bone.rotation_mode = 'XYZ'
            bone.rotation_euler = ((.08 * value, -.12 * value, .15 * value) if bone == head else
                                   (.10 * value, -.12 * value, .18 * value))
            bone.keyframe_insert('rotation_euler', frame=frame, group=bone.name)
    blinks = []
    for obj in addon.scene_models.meshes(root):
        keys = obj.data.shape_keys
        if not keys:
            continue
        blink = next((k for k in keys.key_blocks if k.name.casefold() in {'まばたき', 'blink', '眨眼'}), None)
        blinks = [blink] if blink else [keys.key_blocks[n] for n in ('ウィンク', 'ウィンク右') if n in keys.key_blocks]
        if blinks:
            for blink in blinks:
                for frame, value in ((1, 0), (7, .75), (13, 1), (19, .3), (25, 0)):
                    blink.value = value
                    blink.keyframe_insert('value', frame=frame)
            break
    assert len(blinks) in {1, 2}, ('Fixture must contain an actual blink/wink morph',
                              [(o.name, [k.name for k in o.data.shape_keys.key_blocks] if o.data.shape_keys else [])
                               for o in addon.scene_models.meshes(root)])
    bpy.context.scene.frame_set(1)
    return [b.name for b in blinks]


def frame_check(root, plans, frame, amount):
    root.hgt_jelly.amount = amount
    scene = bpy.context.scene
    scene.frame_set(frame)
    before, after, errors = {}, {}, []
    for item in plans:
        obj = item['obj']
        entry = next(e for e in root.hgt_jelly.entries if e.object == obj)
        modifier = obj.modifiers.get(entry.modifier)
        modifier.show_viewport = False
        before[obj.name] = original = coordinates(obj)
        modifier.show_viewport = True
        after[obj.name] = changed = coordinates(obj)
        assert len(changed) == len(original) == len(obj.data.vertices)
        untouched = np.array(item['region']) == 0
        assert np.array_equal(original[untouched], changed[untouched]), 'Sclera, lids or body moved'
        if amount == 0:
            assert np.array_equal(original, changed), ('Zero must be exactly original', frame, float(np.abs(original-changed).max()),
                    [(s.name, getattr(modifier.properties.inputs, s.identifier).value) for s in modifier.node_group.interface.items_tree
                     if s.item_type=='SOCKET' and s.in_out=='INPUT' and s.name!='Geometry'], root.hgt_jelly.amount)
        region, core = np.array(item['region']), np.array(item['core'])
        for side, anchors in item['eyes'].items():
            polygons = [list(p.vertices) for p in obj.data.polygons
                        if all(region[i] == side and core[i] for i in p.vertices)]
            surface = BVHTree.FromPolygons([Vector(c) for c in original], polygons, all_triangles=False)
            selected = np.where((region == side) & (core > 0))[0]
            center = original[selected].mean(axis=0)
            a, b, c = original[list(anchors)]
            x = b - a
            x /= np.linalg.norm(x)
            n = np.cross(x, c - a)
            n /= max(np.linalg.norm(n), 1e-20)
            # Every iris vertex stays on the current (already animated) iris;
            # no eye-bone or center translation can be introduced by the effect.
            distances = [surface.find_nearest(Vector(changed[i]))[3] for i in selected]
            error = float(max(distances))
            assert error < 3e-6, (obj.name, frame, side, error)
            d = changed[selected] - original[selected]
            normal_shift = float(np.max(np.abs(d @ n)))
            center_drift = float(np.linalg.norm(changed[selected].mean(axis=0) - center))
            errors.append(dict(side=side, surface_error=error, normal_shift=normal_shift,
                               center=list(map(float, center)), center_drift=center_drift,
                               max_deformation=float(np.max(np.linalg.norm(d, axis=1)))))
        assert not list(modifier.node_warnings), [(w.message) for w in modifier.node_warnings]
    response = max(float(np.abs(after[n] - before[n]).max()) for n in before)
    if amount > 0 and frame in {1, 4, 25}:
        assert response > 1e-5, (frame, response)
    return dict(frame=frame, amount=amount, response=response, eyes=errors), after


def render(path):
    scene = bpy.context.scene
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(str(path), check_existing=False)
    pixels = np.array(image.pixels[:], dtype=np.float32)
    bpy.data.images.remove(image)
    return pixels


def closeup(plans):
    scene = bpy.context.scene
    points = [item['obj'].matrix_world @ item['obj'].data.vertices[i].co
              for item in plans for i, value in enumerate(item['core']) if value]
    center = sum(points, Vector()) / len(points)
    camera = bpy.data.objects.new('Jelly Review Camera', bpy.data.cameras.new('Jelly Review Camera'))
    scene.collection.objects.link(camera)
    camera.location = center + Vector((0, -.5, .008))
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.type, camera.data.ortho_scale = 'ORTHO', .20
    scene.camera = camera
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 720, 400, 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.film_transparent = True


def verify_fixture(name, fixture):
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(fixture), load_ui=False)
    scene = bpy.context.scene
    root = next(o for o in scene.objects if addon.scene_models.model_root(o))
    scene.hgt_model = root
    blink = motion(root)
    plans = addon.jelly_eye.plan(root, scene)
    baseline = protected(root)
    original_counts = counts()
    animation_empty = {o.name: o.animation_data is None for o in addon.scene_models.meshes(root)}
    addon.jelly_eye.enable(root, scene)
    assert not addon.jelly_eye.error(root)
    assert protected(root) == baseline
    # Isolate the modifier's output, before later outlines or user topology.
    later = []
    for entry in root.hgt_jelly.entries:
        modifiers = list(entry.object.modifiers)
        i = next(i for i, m in enumerate(modifiers) if m.name == entry.modifier)
        for modifier in modifiers[i + 1:]:
            later.append((modifier, modifier.show_viewport))
            modifier.show_viewport = False
    frames = []
    reference = {}
    relative_eye_rotations = []
    for frame in (1, 4, 7, 13, 19, 25):
        record, data = frame_check(root, plans, frame, 1)
        bone = addon.scene_models.armature(root).pose.bones[addon.jelly_eye.eye_bones(addon.scene_models.armature(root))[1].name]
        relative_eye_rotations.append((bone.parent.matrix.inverted() @ bone.matrix).to_quaternion())
        reference[frame] = data
        frames.append(record)
    assert max(relative_eye_rotations[0].rotation_difference(q).angle for q in relative_eye_rotations[1:]) > .01, 'Original eye action did not actually move the eye'
    for frame in (1, 7, 13):
        record, _ = frame_check(root, plans, frame, 0)
        frames.append(record)
    # Out-of-order evaluation must have no hidden spring simulation state.
    for frame in (25, 7, 19, 1, 13, 4):
        _, actual = frame_check(root, plans, frame, 1)
        assert all(np.array_equal(actual[n], reference[frame][n]) for n in actual)
    scene.frame_set(1)
    root.hgt_jelly.amount = .1
    low = {item['obj'].name: coordinates(item['obj']) for item in plans}
    root.hgt_jelly.amount = .9
    high = {item['obj'].name: coordinates(item['obj']) for item in plans}
    assert max(float(np.abs(low[n] - high[n]).max()) for n in low) > 1e-5, 'Live slider did not invalidate drivers'
    root.hgt_jelly.amount = 1
    timings = {}
    for enabled in (False, True):
        for entry in root.hgt_jelly.entries:
            entry.object.modifiers[entry.modifier].show_viewport = enabled
        samples = []
        for frame in (1, 4, 7, 13, 19, 25) * 4:
            start = time.perf_counter()
            scene.frame_set(frame)
            for item in plans:
                coordinates(item['obj'])
            samples.append((time.perf_counter() - start) * 1000)
        timings['on_ms' if enabled else 'off_ms'] = float(np.median(samples[6:]))
    for modifier, show in later:
        modifier.show_viewport = show
    scene.frame_set(1)
    assert protected(root) == baseline
    closeup(plans)
    root.hgt_jelly.amount = 0
    off = render(out / 'off.png')
    root.hgt_jelly.amount = 1
    on = render(out / 'on.png')
    assert float(np.abs(off - on).max()) > .02, 'Visible jelly effect absent'
    for frame in (4, 7, 13, 19):
        scene.frame_set(frame)
        render(out / ('on-%02d.png' % frame))
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / 'jelly.blend'))
    root_name = root.name
    before_save = protected(root)
    bpy.ops.wm.open_mainfile(filepath=str(out / 'jelly.blend'), load_ui=False)
    root = bpy.data.objects[root_name]
    assert not addon.jelly_eye.error(root)
    assert protected(root) == before_save
    assert np.array_equal(on, render(out / 'reopened.png')), 'Saved evaluation changed'
    addon.jelly_eye.disable(root)
    assert not addon.jelly_eye.is_active(root)
    assert np.array_equal(off, render(out / 'disabled.png')), 'Disable changed original render'
    assert protected(root) == baseline
    assert all((o.animation_data is None) == animation_empty[o.name] for o in addon.scene_models.meshes(root))
    assert not any(o.get(addon.jelly_eye.OWNER) for o in bpy.data.objects)
    assert not any(t.get(addon.jelly_eye.OWNER) for t in bpy.data.node_groups)
    # The review camera is the sole intentional extra object/data after cleanup.
    assert counts() == {k: v + (1 if k == 'objects' else 0) for k, v in original_counts.items()}, (counts(), original_counts)
    for _ in range(3):
        addon.jelly_eye.enable(root, bpy.context.scene)
        addon.jelly_eye.disable(root)
    after_cycles = counts()
    build = addon.jelly_eye.jelly_geometry.build
    def fail(*args):
        build(*args)
        raise RuntimeError('Injected failure after native node construction')
    addon.jelly_eye.jelly_geometry.build = fail
    try:
        try:
            addon.jelly_eye.enable(root, bpy.context.scene)
            raise AssertionError('Failure injection did not fail')
        except RuntimeError as exc:
            assert 'Injected failure' in str(exc)
    finally:
        addon.jelly_eye.jelly_geometry.build = build
    assert counts() == after_cycles and protected(root) == baseline
    assert not root.hgt_jelly.entries
    return dict(name=name, blink=blink, frames=frames, cpu_pose_and_modifier_median=timings, checks={
        'original_actions_meshes_weights_keys_and_materials_preserved': True,
        'original_eye_action_actually_moves_eye': True,
        'iris_on_current_original_surface': True, 'sclera_lids_body_exact': True,
        'zero_exact': True, 'live_parameter_without_frame_change': True,
        'scrubbing_deterministic': True, 'render_responds': True,
        'save_reopen_exact': True, 'disable_restores_exact': True,
        'cycles_release_resources': True, 'failure_atomic': True})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--mmd-tools', type=Path, required=True)
    parser.add_argument('--candidate', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    OUT = args.output_dir.resolve()
    assert OUT.is_relative_to(ROOT / '.verification')
    OUT.mkdir(parents=True, exist_ok=True)
    report = dict(scope='GI-TOON-JELLY-EYES', complete=False, models=[])
    try:
        load_mmd(args.mmd_tools, OUT / '_runtime')
        addon = install_candidate(args.candidate, OUT) if args.candidate else load_addon(ROOT)
        payload = Path(addon.__file__).resolve().parent
        report['source_sha256'] = {p.name: file_hash(p) for p in payload.glob('*.py')}
        report['package_sha256'] = file_hash(args.candidate) if args.candidate else None
        for name in ('安柏', '纳西妲', '奥黛塔'):
            report['models'].append(verify_fixture(name, args.fixtures / name / 'verified.blend'))
        report['complete'] = True
    except Exception:
        report['error'] = traceback.format_exc()
        raise
    finally:
        (OUT / 'jelly.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        print('HGT_JELLY_EYES', report.get('complete'), flush=True)
