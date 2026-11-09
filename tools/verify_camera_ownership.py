"""Bounded legacy-camera ownership checks against an installed candidate."""
import argparse
import json
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verification_runtime import install_candidate, file_hash

parser = argparse.ArgumentParser()
parser.add_argument('--candidate', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
OUT = args.output_dir.resolve()
addon = install_candidate(args.candidate, OUT)
report = {'scope': 'CAMERA-OWNERSHIP', 'complete': False, 'checks': {},
          'package_sha256': file_hash(args.candidate)}


def fixture(name):
    scene = bpy.data.scenes.new(name)
    bpy.context.window.scene = scene
    collection = bpy.data.collections.new(name + ' preset')
    scene.collection.children.link(collection)
    collection['hgt_scene_owner'] = name
    cameras = []
    for label in ('default', 'active', 'overview'):
        camera = bpy.data.objects.new(name + label, bpy.data.cameras.new(name + label))
        if label == 'default':
            scene.collection.objects.link(camera)
            camera['hgt_scene_camera'] = True
        else:
            collection.objects.link(camera)
            camera['hgt_scene_owner'] = camera.data['hgt_scene_owner'] = name
        cameras.append(camera)
    scene.camera = cameras[1]
    state = scene.hgt_scene
    state.uid, state.collection = name, collection
    state.previous_camera, state.camera = cameras[:2]
    return scene, collection, cameras


def check(name, value):
    report['checks'][name] = bool(value)
    (OUT / 'ownership.json').write_text(json.dumps(report, indent=2) + '\n', 'utf-8')
    assert value, name


def blocked(scene):
    pointers = tuple(o.as_pointer() for o in scene.objects)
    original = scene.camera
    try:
        addon.scene_camera.migrate(scene)
    except ValueError:
        return pointers == tuple(o.as_pointer() for o in scene.objects) and scene.camera == original
    return False


scene, collection, cameras = fixture('unanimated')
default = cameras[0]
addon.scene_camera.migrate(scene)
check('unanimated_presets_keep_default_only', scene.camera == default and len(scene.objects) == 1)

scene, collection, cameras = fixture('multiple-motion')
for camera in cameras[1:]:
    camera.keyframe_insert('location', frame=1)
check('multiple_animated_cameras_fail_before_mutation', blocked(scene))

scene, collection, cameras = fixture('default-motion')
for camera in cameras[:2]:
    camera.keyframe_insert('location', frame=1)
check('animated_default_conflict_fails_before_mutation', blocked(scene))

scene, collection, cameras = fixture('manual-choice')
manual = bpy.data.objects.new('manual camera', bpy.data.cameras.new('manual camera'))
scene.collection.objects.link(manual)
scene.camera = manual
addon.scene_camera.migrate(scene)
check('manual_camera_choice_survives', scene.camera == manual and len(scene.objects) == 2)

scene, collection, cameras = fixture('constraint-user')
overview = cameras[2]
user = bpy.data.objects.new('camera target user', None)
scene.collection.objects.link(user)
user.constraints.new('COPY_LOCATION').target = overview
addon.scene_camera.migrate(scene)
check('external_constraint_camera_reference_survives', user.constraints[0].target == overview
      and overview.name in scene.objects and not overview.get('hgt_scene_owner'))

scene, collection, cameras = fixture('shared-collection')
moving = cameras[1]
moving.keyframe_insert('location', frame=1)
other = bpy.data.scenes.new('other scene with shared preset')
other.collection.children.link(collection)
other.camera = moving
addon.scene_camera.migrate(scene)
check('shared_collection_keeps_camera_in_other_scene', other.camera == moving and moving.name in other.objects)

scene, collection, cameras = fixture('marker-user')
overview = cameras[2]
marker = scene.timeline_markers.new('User camera cut', frame=20)
marker.camera = overview
addon.scene_camera.migrate(scene)
check('user_camera_cut_survives', marker.camera == overview and overview.name in scene.objects)

report['complete'] = True
(OUT / 'ownership.json').write_text(json.dumps(report, indent=2) + '\n', 'utf-8')
print('CAMERA_OWNERSHIP', len(report['checks']))
