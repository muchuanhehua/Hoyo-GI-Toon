"""Exercise jelly eyes with native MMD materials, gaze and multiple actors."""
import bpy
import numpy as np
from verification_data import mesh_data
from verify_jelly_eyes import coordinates, frame_check, counts
import verify_jelly_eyes as verification


def verify(addon, fixtures):
    verification.addon = addon
    checks = {}
    bpy.ops.wm.open_mainfile(filepath=str(fixtures / '安柏' / 'verified.blend'), load_ui=False)
    scene = bpy.context.scene
    root = next(o for o in scene.objects if addon.scene_models.model_root(o))
    tracked = addon.scene_models.tracked(root, scene)
    scene.hgt_model = root
    scene.frame_set(4)
    originals = {entry.original_data: mesh_data(entry.original_data) for entry in tracked.hgt_character.meshes if entry.original_data}
    addon.jelly_eye.enable(root, scene)
    graphs = [e.graph for e in root.hgt_jelly.entries]
    addon.workflow.restore(tracked)
    assert addon.jelly_eye.is_active(root) and not addon.jelly_eye.error(root)
    assert [e.graph for e in root.hgt_jelly.entries] == graphs
    plans = addon.jelly_eye.plan(root, scene)
    frame_check(root, plans, 4, .7)
    assert all(mesh_data(mesh) == expected for mesh, expected in originals.items()), {
        mesh.name: [key for key, value in mesh_data(mesh).items() if value != expected[key]] for mesh, expected in originals.items()}
    checks['native_mmd_materials_and_restore_materials_preserve_effect'] = True
    addon.workflow.apply_materials(root, bpy.context)
    assert not addon.jelly_eye.error(root) and [e.graph for e in root.hgt_jelly.entries] == graphs
    checks['apply_materials_keeps_independent_effect'] = True
    # Probe before outlines, using the current original pose as the boundary.
    post = []
    for entry in root.hgt_jelly.entries:
        modifiers = list(entry.object.modifiers)
        i = next(i for i, m in enumerate(modifiers) if m.name == entry.modifier)
        for m in modifiers[i + 1:]:
            post.append((m, m.show_viewport))
            m.show_viewport = False
    addon.gaze.set_gaze(tracked, scene, True)
    for x in (-.4, .3):
        scene.camera.location.x = x
        addon.gaze.update_gaze(tracked, scene)
        frame_check(root, addon.jelly_eye.plan(root, scene), 4, .7)
    addon.gaze.clear_gaze(tracked)
    for modifier, show in post:
        modifier.show_viewport = show
    checks['look_at_camera_remains_bounded'] = True
    addon.jelly_eye.disable(root)
    # An unrelated accessory named Highlight must never be mistaken for an eye.
    material = bpy.data.materials.new('Highlight')
    material.mmd_material.name_j = 'Highlight'
    mesh = bpy.data.meshes.new('Unrelated Highlight')
    mesh.from_pydata([(0, 0, 0), (.01, 0, 0), (0, 0, .01)], [], [(0, 1, 2)])
    mesh.materials.append(material)
    accessory = bpy.data.objects.new('Unrelated Highlight', mesh)
    scene.collection.objects.link(accessory)
    accessory.parent = root
    assert accessory not in [item['obj'] for item in addon.jelly_eye.plan(root, scene)]
    checks['unrelated_highlights_ignored'] = True
    bpy.data.objects.remove(accessory, do_unlink=True)
    bpy.data.meshes.remove(mesh)
    bpy.data.materials.remove(material)
    # Reject ambiguous bone identification before allocating any effect data.
    rig = addon.scene_models.armature(root)
    head = addon.gaze.head_bone(root)
    old = head.mmd_bone.name_e
    head.mmd_bone.name_e = 'Left Eye'
    before = counts()
    try:
        try:
            addon.jelly_eye.enable(root, scene)
            raise AssertionError('Ambiguous eye bone was accepted')
        except ValueError as exc:
            assert '唯一识别' in str(exc)
    finally:
        head.mmd_bone.name_e = old
    assert counts() == before and not addon.jelly_eye.is_active(root)
    checks['ambiguous_eye_rejected_without_writes'] = True
    # Append a second real PMX actor without importing or repairing it again.
    with bpy.data.libraries.load(str(fixtures / '纳西妲' / 'verified.blend'), link=False) as (source, target):
        target.objects = list(source.objects)
    collection = bpy.data.collections.new('Second Actor Test')
    scene.collection.children.link(collection)
    for obj in target.objects:
        if obj:
            collection.objects.link(obj)
    second = next(o for o in target.objects if addon.scene_models.model_root(o))
    addon.jelly_eye.enable(root, scene)
    addon.jelly_eye.enable(second, scene)
    second_before = {e.object: coordinates(e.object) for e in second.hgt_jelly.entries}
    root.hgt_jelly.amount = .1
    for e in root.hgt_jelly.entries:
        coordinates(e.object)
    root.hgt_jelly.amount = .95
    for e in root.hgt_jelly.entries:
        coordinates(e.object)
    assert all(np.array_equal(original, coordinates(obj)) for obj, original in second_before.items())
    addon.jelly_eye.disable(root)
    assert addon.jelly_eye.is_active(second)
    addon.jelly_eye.disable(second)
    checks['two_real_characters_are_independent'] = True
    # Animated parameters are evaluated natively along with Scene Time.
    for frame, amount in ((1, .1), (10, .9)):
        root.hgt_jelly.amount = amount
        root.keyframe_insert(data_path='hgt_jelly.amount', frame=frame)
    addon.jelly_eye.enable(root, scene)
    scene.frame_set(1)
    first = {e.object: coordinates(e.object) for e in root.hgt_jelly.entries}
    assert abs(root.hgt_jelly.amount - .1) < 1e-6
    scene.frame_set(10)
    assert abs(root.hgt_jelly.amount - .9) < 1e-6
    assert any(float(np.abs(first[e.object] - coordinates(e.object)).max()) > 1e-5 for e in root.hgt_jelly.entries)
    addon.jelly_eye.disable(root)
    checks['parameters_can_be_keyframed'] = True
    return checks
