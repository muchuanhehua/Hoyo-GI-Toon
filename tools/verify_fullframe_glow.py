"""Verify native full-frame glare, restoration and legacy-source retirement."""
import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verification_runtime import file_hash, install_candidate, load_mmd
from verify_glow import fixture, graph, render

parser = argparse.ArgumentParser()
for key in ('output-dir', 'candidate', 'mmd-tools', 'legacy-fixture'):
    parser.add_argument('--' + key, type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
OUT = args.output_dir.resolve()
assert OUT.is_relative_to(ROOT / '.verification')
OUT.mkdir(parents=True, exist_ok=True)
load_mmd(args.mmd_tools, OUT / '_runtime')
addon = install_candidate(args.candidate, OUT)
glow = addon.glow
payload = Path(addon.__file__).resolve().parent
report = {'scope': 'FULLFRAME-GLOW-COMPATIBILITY', 'complete': False,
          'package_sha256': file_hash(args.candidate),
          'source_sha256': {p.name: file_hash(p) for p in payload.glob('*.py')},
          'checks': {}, 'modes': []}


def check(name, condition):
    assert condition, name
    report['checks'][name] = True


def save():
    (OUT / 'compatibility.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')


def no_source(scene):
    return not any(v.get(addon.glow_source.TAG) for v in scene.view_layers) and not scene.hgt_glow.source_collection


def raw_outputs():
    result = {}
    for path in (OUT / 'user-file-output').glob('*.png'):
        image = bpy.data.images.load(str(path), check_existing=False)
        result[path.name] = np.array(image.pixels[:], dtype=np.float32)
        bpy.data.images.remove(image)
    return result


scene = fixture()
scene.hgt_model = None
tree = bpy.data.node_groups.new('User Compositor', 'CompositorNodeTree')
tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
source = tree.nodes.new('CompositorNodeRLayers')
exposure = tree.nodes.new('CompositorNodeExposure')
output = tree.nodes.new('NodeGroupOutput')
viewer = tree.nodes.new('CompositorNodeViewer')
file_output = tree.nodes.new('CompositorNodeOutputFile')
file_output.file_output_items.new('RGBA', 'Raw')
file_output.directory = str(OUT / 'user-file-output')
file_output.file_name = 'raw_'
file_output.format.media_type = 'IMAGE'
file_output.format.file_format = 'PNG'
file_output.format.color_mode = 'RGBA'
tree.links.new(source.outputs['Image'], exposure.inputs['Image'])
tree.links.new(exposure.outputs['Image'], output.inputs['Image'])
tree.links.new(exposure.outputs['Image'], viewer.inputs['Image'])
tree.links.new(exposure.outputs['Image'], file_output.inputs[0])
scene.compositing_node_group = tree
scene.render.use_compositing = False
original = graph(tree)
objects = len(bpy.data.objects)
scene.render.use_compositing = True
base = render(OUT / 'off.png')
raw_before = raw_outputs()
assert raw_before, 'Original file output was not written'
for name in raw_before:(OUT / 'user-file-output' / name).unlink()
scene.render.use_compositing = False
glow.enable(scene)
user_tree = tree
tree = scene.compositing_node_group
output = next(n for n in tree.nodes if n.type == 'GROUP_OUTPUT')
check('enable_without_selected_character', glow.is_active(scene) and scene.hgt_model is None)
check('no_auxiliary_layer_or_objects', no_source(scene) and len(bpy.data.objects) == objects)
check('no_capture_module_or_timer', not (payload / 'glow_preview.py').exists()
      and not hasattr(addon.glow_source, 'create') and not hasattr(glow, 'preview_nodes'))
check('viewer_preview_and_restore_record', viewer.inputs['Image'].links[0].from_node == glow.node(scene)
      and bool(viewer.get(glow.VIEWER_TOKEN)))
settings = scene.hgt_glow
for mode, _, _ in addon.glow_modes.MODE_ITEMS:
    settings.mode = mode
    settings.strength = 1
    effect = glow.node(scene)
    actual = render(OUT / (mode.replace(' ', '-') + '-actual.png'))
    if mode == 'Bloom':
        raw_after = raw_outputs()
        check('user_file_output_still_executes', raw_before.keys() == raw_after.keys()
              and all(len(raw_before[n]) > 0 and np.array_equal(raw_before[n], raw_after[n]) for n in raw_before))
    native = addon.glow_modes.glare(effect)
    reference = tree.nodes.new('CompositorNodeGlare')
    for socket in native.inputs:
        if socket.name == 'Image' or socket.is_linked:continue
        destination = next((s for s in reference.inputs if s.name == socket.name and s.type == socket.type), None)
        if destination is not None:destination.default_value = socket.default_value
    reference.inputs['Threshold'].default_value = settings.threshold
    reference.inputs['Size'].default_value = settings.size
    tree.links.new(effect.inputs['Image'].links[0].from_socket, reference.inputs['Image'])
    kernel_node = None
    if mode == 'Kernel':
        kernel_node = tree.nodes.new('CompositorNodeImage')
        kernel_node.image = next(n.image for n in effect.node_tree.nodes if n.get(addon.glow_modes.NODE_TAG))
        destination = next(s for s in reference.inputs if s.name == 'Kernel' and s.type == 'RGBA')
        tree.links.new(kernel_node.outputs['Image'], destination)
    tree.links.new(reference.outputs['Image'], output.inputs['Image'])
    expected = render(OUT / (mode.replace(' ', '-') + '-native.png'))
    error = np.abs(actual[:, :, :3] - expected[:, :, :3])
    check(mode + '-native-rgb', float(error.max()) <= 1 / 255 + 1e-6)
    tree.links.new(effect.outputs['Image'], output.inputs['Image'])
    tree.nodes.remove(reference)
    if kernel_node:tree.nodes.remove(kernel_node)
    settings.strength = 0
    zero = render(OUT / (mode.replace(' ', '-') + '-zero.png'))
    check(mode + '-zero-exact', np.array_equal(zero, base))
    report['modes'].append({'mode': mode, 'native_rgb_max_error': float(error.max()), 'zero_exact': True})
    if mode == 'Bloom':
        difference = np.abs(actual[:, :, :3] - base[:, :, :3])
        middle = difference.shape[1] // 2
        check('both_unselected_highlights_emit', float(difference[:, :middle].sum()) > 1
              and float(difference[:, middle:].sum()) > 1)
    save()

settings.mode = 'Bloom'
scene.render.film_transparent = True
settings.strength = 0
transparent_base = render(OUT / 'transparent-off.png')
settings.strength = 1
transparent = render(OUT / 'transparent-on.png')
halo = (transparent_base[:, :, 3] < 1e-6) & (transparent[:, :, 3] > .001)
check('transparent_halo_alpha', int(halo.sum()) > 20)
report['transparent_halo_pixels'] = int(halo.sum())
scene.render.film_transparent = False
effect = glow.node(scene)
before = graph(tree)
scene.hgt_model = scene.objects['Subject B']
check('character_selection_independent', glow.node(scene) == effect and graph(tree) == before and no_source(scene))
glow.disable(scene)
tree = scene.compositing_node_group
check('disable_restores_original_graph', tree == user_tree and graph(tree) == original and not scene.render.use_compositing)
for _ in range(3):glow.enable(scene);glow.disable(scene)
check('repeated_toggles_do_not_grow_scene', graph(tree) == original and len(bpy.data.objects) == objects and no_source(scene))
glow.enable(scene)
tree.links.new(source.outputs['Image'], viewer.inputs['Image'])
glow.disable(scene)
check('manual_viewer_rewire_preserved', viewer.inputs['Image'].links[0].from_node == source and not viewer.get(glow.VIEWER_TOKEN))
tree.links.new(exposure.outputs['Image'], viewer.inputs['Image'])

other = bpy.data.scenes.new('Shared Compositor Consumer')
other.compositing_node_group = tree
glow.enable(scene)
private = scene.compositing_node_group
check('shared_compositor_protected', private != tree and other.compositing_node_group == tree and graph(tree) == original)
effect = glow.node(scene)
kernel = effect.node_tree
consumer = tree.nodes.new('CompositorNodeGroup')
consumer.node_tree = kernel
settings.mode = 'Streaks'
check('shared_nested_kernel_protected', effect.node_tree != kernel and kernel.nodes['Bloom'].inputs['Type'].default_value == 'Bloom')
tree.nodes.remove(consumer)
bpy.data.scenes.remove(other)
glow.disable(scene)
check('shared_tree_disable_restores_links', graph(scene.compositing_node_group) == original)

glow.enable(scene)
settings.mode = 'Kernel'
settings.threshold, settings.strength = .73, 1.2
saved = render(OUT / 'saved-before.png')
path = OUT / 'native-saved.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(path))
bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
scene = bpy.context.scene
reopened = render(OUT / 'saved-after.png')
check('native_save_reopen_exact', np.array_equal(saved, reopened) and glow.is_active(scene) and no_source(scene))
check('native_parameters_preserved', scene.hgt_glow.mode == 'Kernel'
      and abs(scene.hgt_glow.threshold - .73) < 1e-6 and abs(scene.hgt_glow.strength - 1.2) < 1e-6)


def open_legacy():
    # Read the pre-migration state before invoking the actual migration entry.
    bpy.app.handlers.load_post.remove(glow.on_load)
    try:bpy.ops.wm.open_mainfile(filepath=str(args.legacy_fixture), load_ui=False)
    finally:bpy.app.handlers.load_post.append(glow.on_load)
    scene = bpy.context.scene
    assert glow.node(scene).inputs.get('Glow Source')
    return scene


scene = open_legacy()
old = scene.hgt_glow
parameters = tuple(getattr(old, k) for k in ('mode', 'threshold', 'strength', 'size', 'iterations', 'fade'))
object_state = [(o.name, o.type, o.parent.name if o.parent else None, o.data.name if o.data else None,
                 tuple(x for row in o.matrix_world for x in row)) for o in scene.objects]
glow.migrate(scene)
check('legacy_migrates_to_fullframe', glow.is_active(scene) and no_source(scene))
check('legacy_parameters_preserved', parameters == tuple(getattr(old, k) for k in ('mode', 'threshold', 'strength', 'size', 'iterations', 'fade')))
check('legacy_objects_and_parenting_preserved', object_state == [(o.name, o.type, o.parent.name if o.parent else None,
      o.data.name if o.data else None, tuple(x for row in o.matrix_world for x in row)) for o in scene.objects])
check('legacy_preview_images_retired', not any(i.get(addon.glow_source.PREVIEW_TAG) for i in bpy.data.images))
check('legacy_auxiliary_collections_retired', not any(c.get(addon.glow_source.OWNER) == scene for c in bpy.data.collections))
scene = open_legacy()
user_collection = bpy.data.collections.new('User Additional Collection')
scene.hgt_glow.source_collection.children.link(user_collection)
before = graph(scene.compositing_node_group)
try:
    glow.migrate(scene)
except ValueError as exc:
    check('legacy_user_dependencies_protected', '用户新增集合' in str(exc)
          and graph(scene.compositing_node_group) == before and user_collection.users > 0)
else:raise AssertionError('Migration deleted user-owned dependencies')
for handlers, callback in ((bpy.app.handlers.load_post, glow.on_load), (bpy.app.handlers.undo_post, glow.sync_undo),
                           (bpy.app.handlers.redo_post, glow.sync_undo), (bpy.app.handlers.render_init, glow.render_prepare)):
    check(callback.__name__ + '-registered-once', handlers.count(callback) == 1)
check('no_glow_depsgraph_or_frame_handlers', not any(getattr(f, '__module__', '').startswith(addon.__name__ + '.glow')
      for handlers in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.frame_change_post) for f in handlers))
report['complete'] = True
save()
print('FULLFRAME_GLOW_COMPATIBILITY', len(report['checks']), len(report['modes']), flush=True)
