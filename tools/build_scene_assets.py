"""Export only the two environment collections and their dependencies."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import bpy

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--city-terrace', type=Path)
parser.add_argument('--stage', type=Path)
parser.add_argument('--preset', choices=('CITY_TERRACE', 'STAGE'))
parser.add_argument('--overwrite', action='store_true')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
catalog = json.loads((ROOT / 'assets/scenes.json').read_text('utf-8'))
paths = {'CITY_TERRACE': args.city_terrace, 'STAGE': args.stage}
bpy.data.use_autopack = False
for preset in catalog['presets']:
    if args.preset and preset['id'] != args.preset:
        continue
    assert paths[preset['id']], 'Missing source path for ' + preset['id']
    source_path = paths[preset['id']].resolve()
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert digest == preset['source_sha256'], 'Source scene changed: ' + preset['id']
    with bpy.data.libraries.load(str(source_path), link=False) as (source, target):
        assert len(source.scenes) == 1, 'Expected a single environment scene'
        target.scenes = source.scenes
    scene = target.scenes[0]
    bpy.context.window.scene = scene
    bpy.context.view_layer.update()
    root = bpy.data.collections.new(preset['collection'])
    for child in scene.collection.children:
        root.children.link(child)
    for obj in scene.collection.objects:
        root.objects.link(obj)
    assert not any(obj.type == 'ARMATURE' for obj in root.all_objects)
    assert scene.camera and scene.world
    root['hgt_scene_asset'] = preset['id']
    root['hgt_scene_camera'] = scene.camera
    root['hgt_scene_light'] = scene.objects[preset['key_light']]
    root['hgt_scene_world'] = scene.world
    if preset.get('layout') == 'compact-half-ring-v1':
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from city_terrace_layout import reshape
        reshape(root)
        bpy.context.view_layer.update()
    for image in bpy.data.images:
        if image.source == 'FILE':
            assert image.packed_file or image.packed_files, 'Unpacked scene texture: ' + image.name
            assert image.packed_file, 'Expected a single packed image: ' + image.name
            packed = bytes(image.packed_file.data)
            image.filepath_raw = '//' + (Path(image.filepath).name or 'packed-texture.png')
            image.pack(data=packed, data_len=len(packed))
            assert bytes(image.packed_file.data) == packed
    for item in bpy.data.user_map():
        item.use_fake_user = False
    destination = ROOT / 'assets' / preset['file']
    assert args.overwrite or not destination.exists(), 'Pass --overwrite explicitly to rebuild an existing asset'
    bpy.data.libraries.write(str(destination), {root}, path_remap='RELATIVE', fake_user=False, compress=True)
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == digest
    print('HGT_SCENE_ASSET', preset['id'], destination.name, destination.stat().st_size)
