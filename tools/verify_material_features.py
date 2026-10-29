"""Reload actual renders; compare isolated features and retain source evidence."""
import argparse
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Vector
from verification_data import mesh_data
from verification_runtime import file_hash, install_candidate, load_addon, unload_addon

parser = argparse.ArgumentParser()
parser.add_argument('--assets-index', type=Path, required=True)
parser.add_argument('--candidate', type=Path)
parser.add_argument('--input-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
project = Path(__file__).resolve().parents[1]
out = args.output_dir.resolve()
assert out.is_relative_to(project / '.verification')
out.mkdir(parents=True, exist_ok=True)
addon = install_candidate(args.candidate, out) if args.candidate else load_addon(project)
models = json.loads(args.assets_index.read_text(encoding='utf-8'))['models']
report = {'package_sha256': file_hash(args.candidate) if args.candidate else None,
          'source_sha256': {p.name: file_hash(p) for p in Path(addon.__file__).parent.glob('*.py')},
          'models': [], 'visual_review': 'requires_user_review'}


def render(scene, root, path):
    scene.hgt_output.filepath = str(path)
    addon.rendering.start(scene, root)
    image = bpy.data.images.load(str(path), check_existing=False)
    data = np.asarray(image.pixels[:], dtype=np.float32).reshape((-1, 4)).copy()
    bpy.data.images.remove(image)
    return data


def head_camera(scene, root, angle=0):
    faces = [e.object for e in root.hgt_character.meshes if e.object.name.split('.')[0] in {'Face', 'Face_Eye'}]
    points = [obj.matrix_world @ vertex.co for obj in faces for vertex in obj.data.vertices]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center = (low + high) * .5
    camera = root.hgt_character.camera.copy()
    camera.data = camera.data.copy()
    scene.collection.objects.link(camera)
    camera.data.ortho_scale = max(high.x - low.x, high.z - low.z) * 1.45
    camera.location = center + Vector((math.sin(angle), -math.cos(angle), 0))
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    scene.hgt_output.camera = camera
    scene.hgt_output.width = scene.hgt_output.height = 768
    return camera


for model in models:
    name = model['name']
    folder = out / name
    folder.mkdir(exist_ok=True)
    print('HGT_FEATURE_START', name, flush=True)
    references = {ref['path']: file_hash(ref['path']) for ref in model.get('references', [])}
    assert all(value == ref['sha256'] for ref in model.get('references', []) for path, value in references.items() if path == ref['path'])
    bpy.ops.wm.open_mainfile(filepath=str(args.input_dir.resolve() / name / 'render.blend'))
    scene = bpy.context.scene
    root = next(o for o in scene.objects if o.hgt_character.managed)
    originals, derived, participation, eyes = [], [], [], []
    for entry in root.hgt_character.meshes:
        obj = entry.object
        original = entry.original_data or obj.data
        snapshot = mesh_data(original)
        originals.append((obj, original, snapshot, entry.original_hidden, entry.original_view_hidden))
        assert mesh_data(obj.data, set(snapshot['uv']), set(snapshot['colors'])) == snapshot
        if entry.render_data:
            derived.append((entry.render_data, snapshot))
        participation.append({'mesh': obj.name, 'class': entry.participation,
                              'basis': entry.participation_basis, 'hidden': obj.hide_render})
        if entry.participation != 'surface':
            assert obj.hide_render and obj.hide_get(), obj.name
        marker = obj.data.attributes.get('hgt_eye_outer')
        if marker:
            count = sum(v.value > .5 for v in marker.data)
            assert 0 < count < len(obj.data.polygons) and not original.attributes.get(marker.name)
            eyes.append({'mesh': obj.name, 'outer_faces': count, 'inner_faces': len(obj.data.polygons) - count})
    record = {'name': name, 'eyes': eyes, 'participation': participation, 'feature_response': {},
              'materials': [{'source': b.source_name, 'features': json.loads(b.generated['hgt_features']),
                             'resources': json.loads(b.generated['hgt_texture_matches'])} for b in root.hgt_character.bindings]}
    front = render(scene, root, folder / 'front.png')
    for feature in ('stockings', 'silk', 'shining', 'reflection', 'height_normal'):
        controls = []
        for binding in root.hgt_character.bindings:
            for node in binding.generated.node_tree.nodes:
                if node.get('hgt_material_module') == feature:
                    controls.append(node.inputs[0])
                elif feature == 'reflection' and binding.generated.get('hgt_reflection_mask') and node.get('hgt_feature_switch'):
                    controls.append(node.inputs[0])
                elif feature == 'height_normal' and node.name == 'HGT • Packed Height Normal':
                    controls.append(node.inputs['Strength'])
        if not controls:
            continue
        values = [socket.default_value for socket in controls]
        for socket in controls:
            socket.default_value = 0
        variant = render(scene, root, folder / (feature + '-off.png'))
        for socket, value in zip(controls, values):
            socket.default_value = value
        delta = np.abs(front[:, :3] - variant[:, :3])
        record['feature_response'][feature] = {'max': float(delta.max()), 'changed_pixels': int((delta.max(axis=1) > .002).sum())}
        assert delta.max() > .002, (name, feature, 'No visible feature response')
    head_camera(scene, root)
    head = render(scene, root, folder / 'head.png')
    replacements = []
    for binding in root.hgt_character.bindings:
        if not binding.generated.get('hgt_eye_surface_mask'):
            continue
        tree = binding.generated.node_tree
        output = next(n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output)
        replacements.append((tree, output.inputs['Surface'], output.inputs['Surface'].links[0].from_socket))
        tree.links.new(tree.nodes['Body Shader'].outputs['BSDF'], output.inputs['Surface'])
    if replacements:
        variant = render(scene, root, folder / 'eye-layers-off.png')
        record['feature_response']['layered_eye'] = {'max': float(np.abs(head[:, :3] - variant[:, :3]).max())}
        assert record['feature_response']['layered_eye']['max'] > .01
        for tree, socket, source in replacements:
            tree.links.new(source, socket)
    head_camera(scene, root, math.radians(18))
    render(scene, root, folder / 'head-turn.png')
    # The review camera is intentionally independent of the owned auto-frame camera.
    camera = head_camera(scene, root)
    low, high = addon.rendering.character_bounds(root)
    center = (low + high) * .5
    center.z = low.z + (high.z - low.z) * .69
    camera.location = center + Vector((0, -1, 0))
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.ortho_scale = (high.z - low.z) * .48
    render(scene, root, folder / 'torso.png')
    for mesh, snapshot in derived:
        assert mesh_data(mesh, set(snapshot['uv']), set(snapshot['colors'])) == snapshot
    addon.workflow.restore(root)
    for obj, original, snapshot, hidden, view_hidden in originals:
        assert obj.data == original and mesh_data(original) == snapshot
        assert (obj.hide_render, obj.hide_get()) == (hidden, view_hidden)
    assert references == {path: file_hash(path) for path in references}
    record.update(source_geometry_preserved=True, visibility_restored=True, game_references_unchanged=True,
                  technical_checks_passed=True, visual_review='requires_user_review')
    report['models'].append(record)
    (out / 'features.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('HGT_FEATURE_PASSED', name, flush=True)
unload_addon(addon)
print('HGT_FEATURE_MATRIX_COMPLETE', flush=True)
