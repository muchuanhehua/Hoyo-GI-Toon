"""Render Bloom and verify restoration, shared trees and saved projects."""
import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verification_runtime import load_addon, install_candidate, file_hash, load_mmd


def render(path):
    bpy.context.view_layer.update()
    bpy.ops.render.render()
    bpy.data.images['Render Result'].save_render(str(path))
    image = bpy.data.images.load(str(path), check_existing=False)
    values = np.array(image.pixels[:], dtype=np.float32).reshape((*reversed(image.size), 4))
    bpy.data.images.remove(image)
    return values


def graph(tree):
    return ([(n.name, n.bl_idname) for n in tree.nodes],
            sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in tree.links),
            [(s.identifier, s.name, s.in_out) for s in tree.interface.items_tree if s.item_type == 'SOCKET'])


def fixture():
    scene = bpy.context.scene
    for obj in tuple(scene.objects):bpy.data.objects.remove(obj, do_unlink=True)
    scene.render.engine = 'BLENDER_EEVEE'
    scene.eevee.taa_render_samples = 16
    scene.render.resolution_x = scene.render.resolution_y = 256
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.world.color = (.015, .02, .03)
    for name, x, color in (('Bright', -.6, (3, 1.4, .4, 1)), ('Dim', .6, (.12, .16, .2, 1))):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, radius=.32, location=(x, 0, 0))
        obj = bpy.context.object
        obj.name = name
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        nodes = material.node_tree.nodes
        emission = nodes.new('ShaderNodeEmission')
        emission.inputs['Color'].default_value = color
        material.node_tree.links.new(emission.outputs[0], nodes.get('Material Output').inputs['Surface'])
        obj.data.materials.append(material)
    data = bpy.data.cameras.new('Camera')
    camera = bpy.data.objects.new('Camera', data)
    scene.collection.objects.link(camera)
    camera.location = (0, -5, 0)
    camera.rotation_euler = Vector((0, 1, 0)).to_track_quat('-Z', 'Y').to_euler()
    data.type, data.ortho_scale = 'ORTHO', 2.4
    scene.camera = camera
    return scene


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--fixture-directory', type=Path)
    parser.add_argument('--mmd-tools', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    project = Path(__file__).resolve().parents[1]
    out = args.output_dir.resolve()
    assert out.is_relative_to(project / '.verification')
    out.mkdir(parents=True, exist_ok=True)
    if args.fixture_directory:
        assert args.mmd_tools, 'Character checks need MMD Tools'
        load_mmd(args.mmd_tools, out / '_runtime')
    addon = install_candidate(args.candidate, out) if args.candidate else load_addon(project)
    glow = addon.glow if hasattr(addon, 'glow') else addon.panels.glow
    payload = Path(addon.__file__).resolve().parent
    report = {'complete': False, 'scope': 'GI-TOON-GLOW', 'checks': {},
              'source_sha256': {p.name: file_hash(p) for p in payload.glob('*.py')},
              'package_sha256': file_hash(args.candidate) if args.candidate else None}
    checks = report['checks']
    def save():
        (out / 'glow.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    try:
        panels = [c for c in addon.panels.CLASSES if issubclass(c, bpy.types.Panel)]
        assert [c.bl_label for c in panels] == ['角色管理', '材质', '局部调色', '附加效果', '场景', '打光', '相机']
        assert [c.bl_order for c in panels] == list(range(7))
        assert 'DEFAULT_CLOSED' not in getattr(addon.panels.HGT_PT_effects, 'bl_options', set())
        scene = fixture()
        settings = scene.hgt_glow
        assert not glow.is_active(scene) and scene.compositing_node_group is None
        assert abs(settings.threshold - .85) < 1e-6 and settings.strength == 1 and settings.size == .5
        checks['seven_panels_and_off_defaults'] = True
        before_data = {o.name: ([list(v.co) for v in o.data.vertices], [m.name for m in o.data.materials]) for o in scene.objects if o.type == 'MESH'}
        previous = scene.render.use_compositing
        scene.render.use_compositing = False
        baseline = render(out / 'off.png')
        bpy.ops.wm.save_as_mainfile(filepath=str(out / 'fixture.blend'))
        groups = set(bpy.data.node_groups)
        glow.enable(scene)
        bright = render(out / 'on.png')
        assert float(np.abs(bright - baseline).max()) > .05
        report['bloom_response'] = float(np.abs(bright - baseline).max())
        settings.strength = 0
        zero = render(out / 'strength-zero.png')
        assert np.array_equal(zero, baseline)
        settings.strength, settings.threshold = 1, 0
        low = render(out / 'threshold-low.png')
        settings.threshold = 2
        high = render(out / 'threshold-high.png')
        assert float(np.abs(low - high).max()) > .02
        settings.threshold, settings.size = .85, .1
        small = render(out / 'size-small.png')
        settings.size = .8
        wide = render(out / 'size-wide.png')
        assert float(np.abs(wide - small).max()) > .02
        checks['render_and_all_three_controls_respond'] = checks['zero_strength_exact'] = True
        glow.disable(scene)
        assert scene.compositing_node_group is None and not scene.render.use_compositing
        assert set(bpy.data.node_groups) == groups
        assert np.array_equal(render(out / 'disabled.png'), baseline)
        for _ in range(4):glow.enable(scene);glow.disable(scene)
        assert set(bpy.data.node_groups) == groups and scene.compositing_node_group is None
        checks['disable_exact_and_no_resource_growth'] = True
        save()

        # Existing postprocessing and a diagnostic Viewer keep their own paths.
        tree = bpy.data.node_groups.new('User Compositor', 'CompositorNodeTree')
        tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        source = tree.nodes.new('CompositorNodeRLayers')
        exposure = tree.nodes.new('CompositorNodeExposure')
        exposure.inputs['Exposure'].default_value = -.3
        output = tree.nodes.new('NodeGroupOutput')
        viewer = tree.nodes.new('CompositorNodeViewer')
        tree.links.new(source.outputs['Image'], exposure.inputs['Image'])
        tree.links.new(exposure.outputs['Image'], output.inputs['Image'])
        tree.links.new(exposure.outputs['Image'], viewer.inputs['Image'])
        scene.compositing_node_group = tree
        scene.render.use_compositing = True
        original = graph(tree)
        glow.enable(scene)
        assert viewer.inputs['Image'].links[0].from_node == exposure
        # Names can change while enabled; restoration follows real links.
        exposure.name = 'User renamed exposure'
        glow.disable(scene)
        exposure.name = 'Exposure'
        assert graph(tree) == original
        checks['existing_chain_viewer_and_renaming_restored'] = True

        other = bpy.data.scenes.new('Other scene')
        other.compositing_node_group = tree
        glow.enable(scene)
        assert scene.compositing_node_group != tree and graph(tree) == original
        glow.disable(scene)
        assert other.compositing_node_group == tree and graph(tree) == original
        checks['shared_original_tree_isolated'] = True
        glow.enable(scene)
        active = scene.compositing_node_group
        other.compositing_node_group = active
        old_strength = glow.node(other).inputs['Strength'].default_value
        settings.strength = .3
        assert scene.compositing_node_group != active and glow.node(other).inputs['Strength'].default_value == old_strength
        glow.disable(scene)
        checks['shared_active_tree_isolated'] = True
        other.compositing_node_group = None
        bpy.data.scenes.remove(other)

        glow.enable(scene)
        active = scene.compositing_node_group
        effect = glow.node(scene)
        incoming = effect.inputs['Image'].links[0].from_socket
        active.links.remove(effect.inputs['Image'].links[0])
        damaged = graph(active)
        try:glow.disable(scene)
        except ValueError:pass
        else:raise AssertionError('Damaged input silently removed')
        assert graph(active) == damaged and glow.is_active(scene)
        active.links.new(incoming, effect.inputs['Image'])
        glow.disable(scene)
        checks['damaged_input_error_preserves_graph'] = True
        bpy.ops.wm.save_as_mainfile(filepath=str(out / 'user-chain.blend'))
        settings.threshold, settings.strength, settings.size = .85, .7, .5
        glow.enable(scene)
        expected = render(out / 'before-save.png')
        bpy.ops.wm.save_as_mainfile(filepath=str(out / 'glow-active.blend'))
        bpy.ops.wm.open_mainfile(filepath=str(out / 'glow-active.blend'), load_ui=False)
        scene = bpy.context.scene
        assert glow.is_active(scene) and np.array_equal(expected, render(out / 'reopened.png'))
        glow.disable(scene)
        assert {o.name: ([list(v.co) for v in o.data.vertices], [m.name for m in o.data.materials]) for o in scene.objects if o.type == 'MESH'} == before_data
        checks['saved_project_exact_and_source_meshes_unchanged'] = True

        scene.compositing_node_group = None
        scene.render.use_compositing = previous
        scene.render.film_transparent = True
        transparent_off = render(out / 'transparent-off.png')
        glow.enable(scene)
        transparent_on = render(out / 'transparent-on.png')
        halo = (transparent_off[:, :, 3] < 1e-6) & (transparent_on[:, :, :3].max(axis=2) > .02)
        report['transparent_halo_pixels'] = int(halo.sum())
        report['transparent_halo_alpha_max'] = float(transparent_on[halo, 3].max()) if halo.any() else None
        assert halo.sum() > 50 and report['transparent_halo_alpha_max'] > .01
        checks['transparent_halo_has_visible_alpha'] = True
        glow.disable(scene)
        checks['transparent_background_disable_exact'] = np.array_equal(transparent_off, render(out / 'transparent-disabled.png'))
        assert checks['transparent_background_disable_exact']
        if args.fixture_directory:
            from verify_lighting_controls import source_state
            report['models'] = []
            for name in ('安柏', '纳西妲', '奥黛塔'):
                folder = out / name
                folder.mkdir(exist_ok=True)
                reference = args.fixture_directory / name / 'verified.blend'
                reference_hash = file_hash(reference)
                bpy.ops.wm.open_mainfile(filepath=str(reference), load_ui=False)
                scene = bpy.context.scene
                root = scene.hgt_target
                protected = source_state(root)
                settings_before = (root.hgt_character.shadow_softness, root.hgt_character.outline_difference,
                                   root.hgt_character.outline, scene.camera.matrix_world.copy())
                topology = {t.as_pointer(): len(t.nodes) for b in root.hgt_character.bindings
                            for t in addon.shaders.walk(b.generated.node_tree)}
                base = render(folder / 'off.png')
                old = bpy.data.images.load(str(reference.parent / 'before-save.png'), check_existing=False)
                old_pixels = np.array(old.pixels[:], dtype=np.float32).reshape(base.shape)
                bpy.data.images.remove(old)
                baseline_error = float(np.abs(base - old_pixels).max())
                assert baseline_error == 0, (name, baseline_error)
                glow.enable(scene)
                on = render(folder / 'on.png')
                scene.hgt_glow.threshold = .45
                low = render(folder / 'threshold-low.png')
                response = float(np.abs(on - base).max())
                assert response > .01 and float(np.abs(low - on).max()) > .01, name
                glow.disable(scene)
                assert np.array_equal(base, render(folder / 'disabled.png'))
                assert source_state(root) == protected and file_hash(reference) == reference_hash
                assert settings_before == (root.hgt_character.shadow_softness, root.hgt_character.outline_difference,
                                           root.hgt_character.outline, scene.camera.matrix_world)
                assert topology == {t.as_pointer(): len(t.nodes) for b in root.hgt_character.bindings
                                    for t in addon.shaders.walk(b.generated.node_tree)}
                report['models'].append({'name': name, 'off_matches_262_exact': True,
                                         'glow_response': response, 'parameters_and_source_preserved': True,
                                         'shader_topology_unchanged': True, 'disable_exact': True})
                save()
            checks['three_characters_off_on_and_source_protection'] = True
        addon.unregister()
        addon.register()
        assert hasattr(bpy.types.Scene, 'hgt_glow')
        assert bpy.app.handlers.undo_post.count(glow.sync_undo) == 1
        assert bpy.app.handlers.redo_post.count(glow.sync_undo) == 1
        assert bpy.app.handlers.load_post.count(glow.on_load) == 1
        checks['register_unregister'] = True
        report['complete'] = True
        assert report['source_sha256'] == {p.name: file_hash(p) for p in payload.glob('*.py')}
        save()
        print('HGT_GLOW_VERIFIED', len(checks), report['transparent_halo_alpha_max'], flush=True)
    except Exception:
        import traceback
        report['error'] = traceback.format_exc()
        save()
        raise


if __name__ == '__main__':main()
