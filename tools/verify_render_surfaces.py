"""Verify source texture routes and facial layers after loading saved renders."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Vector
from verification_data import mesh_data
from verification_runtime import file_hash, install_candidate, unload_addon

parser = argparse.ArgumentParser()
parser.add_argument('--assets-index', type=Path, required=True)
parser.add_argument('--candidate', type=Path, required=True)
parser.add_argument('--input-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
project = Path(__file__).resolve().parents[1]
out = args.output_dir.resolve()
assert out.is_relative_to(project / '.verification')
out.mkdir(parents=True, exist_ok=True)
addon = install_candidate(args.candidate, out)
models = json.loads(args.assets_index.read_text(encoding='utf-8'))['models']
report = {'package_sha256': file_hash(args.candidate), 'models': []}


def closeup(scene, root):
    face = next(e.object for e in root.hgt_character.meshes if e.object.name.split('.')[0] == 'Face')
    points = [face.matrix_world @ vertex.co for vertex in face.data.vertices]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center = (low + high) * .5
    camera = root.hgt_character.camera.copy()
    camera.data = camera.data.copy()
    scene.collection.objects.link(camera)
    camera.data.ortho_scale = max(high.x - low.x, high.z - low.z) * 1.5
    camera.location = center + Vector((0, -1, 0))
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    scene.hgt_output.camera = camera
    scene.hgt_output.width = scene.hgt_output.height = 640


def render(scene, root, path):
    scene.hgt_output.filepath = str(path)
    addon.rendering.start(scene, root)
    image = bpy.data.images.load(str(path), check_existing=False)
    pixels = np.asarray(image.pixels[:], dtype=np.float32).reshape((-1, 4)).copy()
    bpy.data.images.remove(image)
    return pixels


for model in models:
    name = model['name']
    bpy.ops.wm.open_mainfile(filepath=str(args.input_dir.resolve() / name / 'render.blend'))
    scene = bpy.context.scene
    root = next(obj for obj in scene.objects if obj.hgt_character.managed)
    record = {'name': name, 'texture_routes': [], 'facial_layers': [], 'hidden_overlays': []}
    originals = []
    for entry in root.hgt_character.meshes:
        obj = entry.object
        if obj.name.split('.')[0] == 'Face_Eye':
            assert not any(modifier.type == 'NODES' and modifier.node_group == root.hgt_character.outline_graph
                           for modifier in obj.modifiers), 'Eye overlay generated an exterior outline'
        if entry.participation != 'surface':
            assert obj.hide_render and obj.hide_get(), obj.name
            record['hidden_overlays'].append(obj.name)
        original = entry.original_data or obj.data
        snapshot = mesh_data(original)
        originals.append((obj, original, snapshot, entry.original_hidden, entry.original_view_hidden))
        assert mesh_data(obj.data, set(snapshot['uv']), set(snapshot['colors'])) == snapshot, obj.name
        mask = obj.data.attributes.get(addon.workflow.surface_layers.EXPRESSION_MASK)
        if mask:
            assert mask.domain == 'FACE' and mask.data_type == 'FLOAT'
            assert not original.attributes.get(mask.name), 'Render mask was written to the original mesh'
            hidden = sum(item.value > .5 for item in mask.data)
            assert 0 < hidden < len(original.polygons), 'Expression mask hid the entire mesh'
            record['facial_layers'].append({'mesh': obj.name, 'masked_faces': hidden,
                                           'source_faces': len(original.polygons), 'source_uv': 'UV2'})
    for binding in root.hgt_character.bindings:
        material = binding.generated
        path = Path(material['hgt_json'])
        if not path.is_file():
            continue
        props = json.loads(path.read_text(encoding='utf-8-sig'))['m_SavedProperties']
        # These real verification assets use a dictionary representation.
        expected = props['m_TexEnvs']['_MainTex']['m_Texture']['Name']
        images = [node.image for tree in addon.workflow.shaders.walk(material.node_tree)
                  for node in tree.nodes if node.type == 'TEX_IMAGE'
                  and node.get('hgt_texture_role') == 'diffuse' and node.image]
        assert images and all(Path(image['hgt_file']).stem.casefold() == expected.casefold() for image in images)
        record['texture_routes'].append({'material': binding.source_name, 'main_texture': expected})
        layers = list(material.get('hgt_eye_layers', []))
        if layers:
            for role in layers:
                key = '_ParallaxLayer' + role[-1]
                assert props['m_Floats'][key] != 0
                expected_layer = props['m_TexEnvs'][key + 'Tex']['m_Texture']['Name']
                textures = [node for tree in addon.workflow.shaders.walk(material.node_tree)
                            for node in tree.nodes if node.type == 'TEX_IMAGE'
                            and node.get('hgt_texture_role') == role]
                assert textures and all(node.image and node.outputs['Alpha'].is_linked
                    and Path(node.image['hgt_file']).stem.casefold() == expected_layer.casefold() for node in textures)
            record.setdefault('eye_layers', []).append({'material': binding.source_name, 'layers': layers})
        if root.hgt_character.outline_graph.get('hgt_expression_mask'):
            assert root.hgt_character.outline_graph.nodes['HGT Active Outline Surfaces'].outputs['Geometry'].is_linked
        if material.get('hgt_expression_mask'):
            for generated in (material, binding.outline):
                assert generated.node_tree.nodes['HGT Expression Mask'].attribute_name == addon.workflow.surface_layers.EXPRESSION_MASK
                assert generated.node_tree.nodes['HGT Facial Layers'].outputs[0].is_linked
    folder = out / name
    folder.mkdir(exist_ok=True)
    closeup(scene, root)
    scene.hgt_output.transparent = scene.hgt_output.post_processing = False
    render(scene, root, folder / 'face.png')
    scene.hgt_output.camera = root.hgt_character.camera
    scene.hgt_output.width, scene.hgt_output.height = 640, 960
    scene.hgt_output.transparent = True
    alphas = []
    for post, label in ((False, 'transparent.png'), (True, 'transparent-post.png')):
        scene.hgt_output.post_processing = post
        pixels = render(scene, root, folder / label)
        alpha = pixels[:, 3]
        assert (alpha < .01).mean() > .3 and (alpha > .99).mean() > .05
        alphas.append(alpha)
    assert np.abs(alphas[0] - alphas[1]).max() < .001, 'Post processing changed silhouette alpha'
    addon.workflow.restore(root)
    bpy.context.view_layer.update()
    for obj, original, snapshot, render_hidden, view_hidden in originals:
        assert obj.data == original and mesh_data(original) == snapshot
        assert (obj.hide_render, obj.hide_get()) == (render_hidden, view_hidden)
    record.update(save_reload=True, source_data_preserved=True, visibility_restored=True,
                  transparent_alpha=True, post_alpha=True)
    report['models'].append(record)
    (out / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('HGT_RENDER_SURFACES_PASSED', name, flush=True)
unload_addon(addon)
print('HGT_RENDER_SURFACES_COMPLETE', flush=True)
