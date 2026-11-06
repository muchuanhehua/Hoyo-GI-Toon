"""Exercise native glare modes, scope, nested sharing and convolution data."""
import bpy
import numpy as np


def verify(addon, scene, out, render):
    out.mkdir(exist_ok=True)
    glow, modes = addon.glow, addon.glow_modes
    checks, results = {}, []
    scene.render.film_transparent = False
    scene.compositing_node_group = None
    bpy.context.view_layer.objects.active = scene.objects['Bright']
    scene.hgt_model = scene.objects['Subject A']
    settings = scene.hgt_glow
    settings.threshold, settings.strength, settings.size = .85, 1, .5
    baseline = render(out / 'off.png')
    collections = {o.name: sorted(c.name for c in o.users_collection) for o in scene.objects}
    glow.enable(scene)
    for mode, _, _ in modes.MODE_ITEMS:
        settings.mode = mode
        assert not settings.error, settings.error
        assert modes.glare(glow.node(scene)).inputs['Type'].default_value == mode
        on = render(out / (mode.replace(' ', '-') + '.png'))
        response = float(np.abs(on - baseline).max())
        assert response > .01, mode
        settings.strength = 0
        assert np.array_equal(render(out / (mode.replace(' ', '-') + '-zero.png')), baseline), mode
        settings.strength = 1
        path = out / (mode.replace(' ', '-') + '.blend')
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
        scene, settings = bpy.context.scene, bpy.context.scene.hgt_glow
        assert settings.mode == mode
        reopened = render(out / (mode.replace(' ', '-') + '-reopened.png'))
        assert np.array_equal(on, reopened), mode
        results.append({'mode': mode, 'render_response': response, 'zero_exact': True, 'saved_project_exact': True})
    checks['seven_modes_render_and_zero_and_save_reopen'] = True
    # An equally bright unselected actor and HDR world must never drive an effect.
    material = scene.objects['Bright'].data.materials[0]
    emission = next(n for n in material.node_tree.nodes if n.type == 'EMISSION')
    original = tuple(emission.inputs['Color'].default_value)
    emission.inputs['Color'].default_value = (0, 0, 0, 1)
    background = scene.world.node_tree.nodes.get('Background')
    sky = (tuple(background.inputs['Color'].default_value), background.inputs['Strength'].default_value)
    background.inputs['Color'].default_value = (3, 3, 3, 1)
    settings.strength = 0
    reference = render(out / 'unselected-bright-off.png')
    settings.strength = 1
    for mode, _, _ in modes.MODE_ITEMS:
        settings.mode = mode
        image = render(out / ('unselected-bright-' + mode.replace(' ', '-') + '.png'))
        assert np.array_equal(image, reference), mode
    checks['all_modes_ignore_unselected_actor_and_bright_world'] = True
    emission.inputs['Color'].default_value = original
    background.inputs['Color'].default_value, background.inputs['Strength'].default_value = sky
    for mode, field, value in (('Ghosts', 'iterations', 2), ('Streaks', 'streaks', 8),
                               ('Simple Star', 'diagonal', False), ('Sun Beams', 'sun_position', (.2, .8)),
                               ('Fog Glow', 'size', .8)):
        settings.mode = mode
        before = render(out / (mode.replace(' ', '-') + '-control-before.png'))
        old = getattr(settings, field)
        old = tuple(old) if hasattr(old, '__len__') else old
        setattr(settings, field, value)
        after = render(out / (mode.replace(' ', '-') + '-control-after.png'))
        assert float(np.abs(before - after).max()) > .01, (mode, field)
        setattr(settings, field, old)
    checks['mode_specific_controls_respond'] = True
    settings.mode = 'Kernel'
    default = render(out / 'kernel-default.png')
    custom = bpy.data.images.new('User Convolution', width=65, height=65, alpha=True, float_buffer=True)
    pixels = np.zeros((65, 65, 4), dtype=np.float32)
    pixels[:, 31:34, :3] = 1
    pixels[:, :, 3] = 1
    custom.pixels.foreach_set(pixels.ravel())
    custom.update()
    before = (tuple(custom.pixels[:]), custom.colorspace_settings.name, custom.file_format)
    settings.kernel_image = custom
    result = render(out / 'kernel-custom.png')
    assert float(np.abs(result - default).max()) > .01
    settings.kernel_image = None
    assert np.array_equal(default, render(out / 'kernel-default-restored.png'))
    assert before == (tuple(custom.pixels[:]), custom.colorspace_settings.name, custom.file_format)
    checks['custom_kernel_responds_and_user_image_unchanged'] = True
    # Nested groups must also separate before changing native mode constants.
    settings.mode = 'Bloom'
    original_kernel = glow.node(scene).node_tree
    holder = bpy.data.node_groups.new('User sharing kernel', 'CompositorNodeTree')
    holder.nodes.new('CompositorNodeGroup').node_tree = original_kernel
    settings.mode = 'Ghosts'
    assert glow.node(scene).node_tree != original_kernel
    assert original_kernel.nodes['Bloom'].inputs['Type'].default_value == 'Bloom'
    bpy.data.node_groups.remove(holder)
    if original_kernel.users == 0:bpy.data.node_groups.remove(original_kernel)
    checks['nested_kernel_copy_preserves_other_users'] = True
    settings.mode = 'Kernel'
    glow.disable(scene)
    assert not any(i.get(modes.IMAGE_TAG) for i in bpy.data.images)
    assert custom in set(bpy.data.images)
    bpy.data.images.remove(custom)
    assert scene.compositing_node_group is None
    assert collections == {o.name: sorted(c.name for c in o.users_collection) for o in scene.objects}
    # The file was reopened above: compare group names, not invalid old pointers.
    assert not any(t.get(glow.KERNEL) or t.get(glow.CREATED_TREE) for t in bpy.data.node_groups)
    for _ in range(3):
        glow.enable(scene)
        for mode, _, _ in modes.MODE_ITEMS:settings.mode = mode
        glow.disable(scene)
    assert not any(i.get(modes.IMAGE_TAG) for i in bpy.data.images)
    checks['switching_cycles_restore_data_and_release_default_kernel'] = True
    return {'checks': checks, 'modes': results}


def verify_legacy(addon, previous, out, render):
    source = previous / 'glow-active.blend'
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
    scene = bpy.context.scene
    assert addon.glow.is_active(scene) and scene.hgt_glow.mode == 'Bloom'
    image = bpy.data.images.load(str(previous / 'before-save.png'), check_existing=False)
    expected = np.array(image.pixels[:], dtype=np.float32).reshape((*reversed(image.size), 4))
    bpy.data.images.remove(image)
    assert np.array_equal(render(out / 'legacy-272.png'), expected)
    scene.hgt_glow.mode = 'Ghosts'
    assert not scene.hgt_glow.error
    scene.hgt_glow.mode = 'Bloom'
    assert np.array_equal(render(out / 'legacy-272-restored.png'), expected)
    addon.glow.disable(scene)
    return True
