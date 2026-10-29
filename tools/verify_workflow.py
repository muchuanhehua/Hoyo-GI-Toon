"""39–49: real framing, display, expressions, relocation and resource lifetimes."""
import argparse
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Quaternion
from verification_runtime import copy_better, load_mmd, load_addon, install_candidate, unload_addon, file_hash
from verification_data import source_snapshot, mmd_snapshot, mesh_data
from verification_materials import pixels, compare
from verification_subject_fixture import mixed_pmx

parser = argparse.ArgumentParser()
for key in ('fbx-index', 'pmx-index', 'better-fbx', 'mmd-tools', 'output-dir'):
    parser.add_argument('--' + key, type=Path, required=True)
parser.add_argument('--candidate', type=Path)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
project = Path(__file__).resolve().parents[1];out = args.output_dir.resolve()
assert out.is_relative_to(project / '.verification');out.mkdir(parents=True, exist_ok=True)
better, _ = copy_better(args.better_fbx, out / '_runtime')
mmd = load_mmd(args.mmd_tools, out / '_runtime')
addon = install_candidate(args.candidate, out) if args.candidate else load_addon(project)
payload = Path(addon.__file__).resolve().parent
report = {'scope': '39–49', 'package_sha256': file_hash(args.candidate) if args.candidate else None,
    'source_sha256': {p.name: file_hash(p) for p in payload.glob('*.py')}, 'models': [], 'checks': {}}
fbx = json.loads(args.fbx_index.read_text(encoding='utf-8'))['models']
pmx = json.loads(args.pmx_index.read_text(encoding='utf-8'))['models']


def save():
    assert report['source_sha256'] == {p.name: file_hash(p) for p in payload.glob('*.py')}
    (out / 'workflow.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def ids():
    return addon.workflow.asset_tracking.data_pointers()


def render(root, path):
    scene = bpy.context.scene
    scene.hgt_output.filepath = str(path)
    before = ids()
    original = addon.workflow.asset_tracking.scene_state(bpy.context)
    result = addon.rendering.start(scene, root)
    assert result == str(path) and scene.hgt_output.last_render == str(path)
    after = ids()
    after['images'] -= {i.as_pointer() for i in bpy.data.images if i.type == 'RENDER_RESULT' and i.as_pointer() not in before['images']}
    assert before == after, 'Temporary output IDs leaked'
    assert all(getattr(owner, key) == value for owner, key, value in original), 'Original scene changed'
    return pixels(path)


def source_files(path):
    return {str(p.relative_to(path)): file_hash(p) for p in path.rglob('*') if p.is_file()}


for format, model in [('fbx', fbx[2]), ('pmx', pmx[1])]:
    bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
    folder = out / format;folder.mkdir(exist_ok=True)
    source = Path(model['path']);files = source_files(source.parent)
    started = time.perf_counter()
    batch = addon.workflow.importers.import_character(str(source))
    imported = time.perf_counter()
    baseline = source_snapshot(batch);metadata = mmd_snapshot(batch) if format == 'pmx' else None
    root = addon.workflow.assemble(batch, bpy.context);scene = bpy.context.scene;settings = root.hgt_character
    assembled = time.perf_counter()
    assert settings.schema_version == 1 and settings.source_digest == file_hash(source)
    assert source_snapshot(batch) == baseline
    image=next(i for i in addon.rendering.project_io.images(root) if i.get('hgt_owner')==settings.uid and not i.packed_file)
    image_path=image.filepath
    visibility={entry.object:entry.object.hide_render for entry in settings.meshes}
    image.filepath=str(out/'intentionally-missing.png')
    for obj in visibility:obj.hide_render=True
    addon.rendering.project_io.validate(root)
    for obj,value in visibility.items():obj.hide_render=value
    try:addon.rendering.project_io.validate(root)
    except ValueError as exc:assert '贴图丢失' in str(exc)
    else:raise AssertionError('Visible missing image was ignored')
    image.filepath=image_path
    scene.hgt_output.width, scene.hgt_output.height = 480, 640
    images = {};scales = {}
    for shot in ('FULL', 'HALF', 'HEAD'):
        assert bpy.ops.hgt.set_shot(shot=shot) == {'FINISHED'}
        scales[shot] = settings.camera.data.ortho_scale
        images[shot] = render(root, folder / (shot.lower() + '.png'))
        assert (images[shot][:, 3] > .5).mean() > .04
    assert scales['FULL'] > scales['HALF'] > scales['HEAD'], scales
    assert bpy.ops.hgt.view_angle(angle='TURN') == {'FINISHED'}
    images['turn'] = render(root, folder / 'turn.png')
    assert compare(images['HEAD'], images['turn'])['maximum'] > .1
    for angle in ('SIDE', 'BACK', 'FRONT'):
        assert bpy.ops.hgt.view_angle(angle=angle) == {'FINISHED'}
        images[angle] = render(root, folder / (angle.lower() + '.png'))
    camera = settings.camera
    camera.location.x += .06;camera.data.shift_x = .03;bpy.context.view_layer.update()
    manual = addon.rendering.framing.signature(camera)
    render(root, folder / 'manual.png')
    assert addon.rendering.framing.signature(camera) == manual, 'Manual camera overwritten'
    camera.data.shift_x = 0
    assert bpy.ops.hgt.set_shot(shot='HEAD') == {'FINISHED'}
    for preset in ('SIDE', 'RIM', 'SOFT'):
        assert bpy.ops.hgt.light_preset(preset=preset) == {'FINISHED'}
        images[preset] = render(root, folder / ('light-' + preset.lower() + '.png'))
    assert compare(images['SIDE'], images['SOFT'])['maximum'] > .05
    assert settings.expressions
    key = next((item for item in settings.expressions if item.name in ('Mouth_Smile01', '笑い')), settings.expressions[0])
    key.value = .7;bpy.context.view_layer.update()
    assert all(abs(target.object.data.shape_keys.key_blocks[target.key].value - .7) < 1e-5 for target in key.targets)
    images['expression'] = render(root, folder / 'expression.png')
    assert compare(images['expression'], images['SOFT'])['maximum'] > .02
    constraints = {bone.name: len(bone.constraints) for bone in settings.source_armature.pose.bones}
    assert len(addon.workflow.expressions.eye_bones(root)) == 2
    assert bpy.ops.hgt.look_camera() == {'FINISHED'} and settings.look_camera
    assert len(settings.gaze_bones) == 2
    gaze_ids = ids()
    started_refresh = time.perf_counter()
    for _ in range(50):
        addon.workflow.refresh_character(root)
    refresh_seconds = time.perf_counter() - started_refresh
    assert ids() == gaze_ids
    assert bpy.ops.hgt.view_angle(angle='TURN') == {'FINISHED'}
    images['look'] = render(root, folder / 'look.png')
    head = settings.source_armature.pose.bones[settings.head.constraints['Child Of'].subtarget]
    original_pose = head.rotation_mode, tuple(head.rotation_quaternion), tuple(head.rotation_euler), tuple(head.rotation_axis_angle)
    head.rotation_mode = 'QUATERNION'
    head.rotation_quaternion = Quaternion((0, 0, 1), .15) @ head.rotation_quaternion
    bpy.context.view_layer.update()
    images['pose'] = render(root, folder / 'pose.png')
    assert compare(images['pose'], images['look'])['maximum'] > .05
    head.rotation_quaternion, head.rotation_euler, head.rotation_axis_angle = original_pose[1:]
    head.rotation_mode = original_pose[0];bpy.context.view_layer.update()
    assert bpy.ops.hgt.look_camera() == {'FINISHED'} and not settings.look_camera
    assert constraints == {bone.name: len(bone.constraints) for bone in settings.source_armature.pose.bones}
    assert bpy.ops.hgt.reset_expressions() == {'FINISHED'}
    assert not settings.has_expression_edits
    assert source_snapshot(batch) == baseline
    assert bpy.ops.hgt.set_shot(shot='FULL') == {'FINISHED'}
    settings.show_floor = True
    assert settings.view_elevation >= .119
    scene.hgt_output.transparent = False;scene.hgt_output.background_color = (.1, .16, .25)
    displayed = render(root, folder / 'display.png')
    assert displayed[:, 3].min() == 1, 'Solid output contains transparent pixels'
    assert abs(displayed[-1, 2] - displayed[-1, 0]) > .05
    key.value = .4
    assert bpy.ops.hgt.look_camera() == {'FINISHED'}
    camera_state = addon.rendering.framing.signature(settings.camera)
    first = render(root, folder / 'saved-before.png')
    snapshots = {entry.object.name: mesh_data(entry.original_data) for entry in settings.meshes if entry.original_data}
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'workflow.blend'), relative_remap=False)
    addon.workflow.restore(root);bpy.context.view_layer.update()
    assert source_snapshot(batch) == baseline
    if metadata is not None:
        assert mmd_snapshot(batch) == metadata
    bpy.ops.wm.open_mainfile(filepath=str(folder / 'workflow.blend'))
    scene = bpy.context.scene;root = scene.hgt_target;settings = root.hgt_character
    assert settings.look_camera and settings.show_floor and settings.shot == 'FULL'
    assert addon.rendering.framing.signature(settings.camera) == camera_state
    reopened = render(root, folder / 'saved-reopened.png')
    difference = compare(first, reopened)
    assert difference['mean'] < .00001 and difference['changed_fraction'] < .001, difference
    assert all(mesh_data(entry.original_data) == snapshots[entry.object.name] for entry in settings.meshes if entry.original_data)
    counts = ids();started_bounds = time.perf_counter()
    for _ in range(8):
        addon.rendering.character_bounds(root)
    bounds_seconds = time.perf_counter() - started_bounds
    assert counts == ids()
    addon.workflow.restore(root)
    assert files == source_files(source.parent)
    report['models'].append({'name': model['name'], 'format': format, 'source_data_unchanged': True,
        'source_files_unchanged': len(files), 'mmd_metadata_preserved': True, 'shots': scales,
        'manual_camera_preserved': True, 'preset_response': True, 'expressions': True, 'gaze': True,
        'pose_follow': True, 'reset_restored': True, 'background_floor': True, 'save_reload': difference,
        'temporary_resources_clean': True, 'seconds': {'import': imported - started, 'assemble': assembled - imported,
            'refresh_50': refresh_seconds, 'bounds_8': bounds_seconds}})
    save();print('HGT_WORKFLOW_MODEL_PASSED', format, model['name'], flush=True)

# The move is restricted to a generated fixture inside this verification directory.
bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)
before_folder, after_folder = out / 'move-before', out / 'move-after'
assert before_folder.resolve().is_relative_to(out) and after_folder.resolve().is_relative_to(out)
fixture = mixed_pmx(before_folder)
root = addon.workflow.build(str(fixture), bpy.context);scene = bpy.context.scene
scene.hgt_output.width, scene.hgt_output.height = 240, 320
before = render(root, out / 'relink-before.png')
assert bpy.ops.wm.save_as_mainfile(filepath=str(out / 'relink.blend'), relative_remap=False) == {'FINISHED'}
before_folder.rename(after_folder)
bpy.ops.wm.open_mainfile(filepath=str(out / 'relink.blend'))
root = bpy.context.scene.hgt_target;fixture = after_folder / fixture.name
try:
    addon.rendering.start(bpy.context.scene, root)
except ValueError as exc:
    assert '贴图丢失' in str(exc)
else:
    raise AssertionError('Missing images were accepted')
original_ids = ids();paths = {image: image.filepath for image in addon.rendering.project_io.images(root, source=True)}
texture = after_folder / 'color.png';data = texture.read_bytes()
texture.write_bytes(data + b'changed')
try:
    addon.rendering.project_io.relink(root, fixture)
except ValueError as exc:
    assert '原文件不同' in str(exc)
else:
    raise AssertionError('Different source texture was accepted')
assert ids() == original_ids and all(image.filepath == path for image, path in paths.items())
texture.write_bytes(data)
assert bpy.ops.hgt.relink_resources(filepath=str(fixture)) == {'FINISHED'}
after = render(root, out / 'relink-after.png')
assert np.array_equal(before, after)
assert all(Path(image.filepath).is_file() for image in addon.rendering.project_io.images(root, source=True))
scene = bpy.context.scene
automatic = out / 'automatic.png';automatic.write_bytes(b'preserve previous file')
scene.hgt_output.filepath = scene.hgt_output.last_auto_path = str(automatic)
assert addon.rendering.output_path(scene) == out / 'automatic_001.png'
result = addon.rendering.start(scene, root)
assert result == str(out / 'automatic_001.png') and automatic.read_bytes() == b'preserve previous file'
addon.workflow.restore(root)
report['checks'] = {'framing_angles': True, 'manual_camera': True, 'display_isolated': True, 'existing_expressions': True,
    'gaze_restored': True, 'pose_material_follow': True, 'save_reload': True, 'relocation_identical_pixels': True,
    'missing_resource_error': True, 'wrong_resource_rollback': True, 'automatic_unique_name': True,
    'hidden_resources_not_required': True,
    'resource_counts_stable': True, 'source_protection': True, 'register_unregister': True}
unload_addon(addon);mmd.unregister();better.unregister()
save();print('HGT_WORKFLOW_COMPLETE', flush=True)
