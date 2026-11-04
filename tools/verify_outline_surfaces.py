"""Compare real 2.4.0 projects with independently isolated inner shells."""
import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verification_runtime import load_addon, load_mmd, install_candidate, file_hash
from verification_data import mesh_data, properties, digest

parser = argparse.ArgumentParser()
for option in ('output-dir', 'fixture-directory', 'mmd-tools'):
    parser.add_argument('--' + option, type=Path, required=True)
parser.add_argument('--candidate', type=Path)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
project = Path(__file__).resolve().parents[1]
out = args.output_dir.resolve()
assert out.is_relative_to(project / '.verification')
out.mkdir(parents=True, exist_ok=True)
load_mmd(args.mmd_tools, out / '_runtime')
addon = install_candidate(args.candidate, out) if args.candidate else load_addon(project)
if bpy.app.timers.is_registered(addon.project_io._migrate_open_project):
    bpy.app.timers.unregister(addon.project_io._migrate_open_project)
payload = Path(addon.__file__).resolve().parent
hashes = {p.name: file_hash(p) for p in payload.glob('*.py')}
report = {'scope': 'GI-TOON-OUTLINE-SURFACES', 'complete': False, 'models': [],
          'source_sha256': hashes, 'package_sha256': file_hash(args.candidate) if args.candidate else None}


def save():
    assert hashes == {p.name: file_hash(p) for p in payload.glob('*.py')}
    (out / 'outline-surfaces.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')


def selectors(root):
    return [node for entry in root.hgt_character.meshes for modifier in entry.object.modifiers
            if modifier.type == 'NODES' and modifier.node_group and modifier.node_group.get('hgt_pmx_outline')
            for node in modifier.node_group.nodes if node.bl_idname == 'GeometryNodeMaterialSelection'
            and node.inputs['Material'].default_value]


def selected_names(root):
    return sorted(node.inputs['Material'].default_value['hgt_source'] for node in selectors(root))


def reference_sheet_faces(mesh, names):
    """Independent reference: match reversed cyclic vertex order, not normals."""
    data = mesh.data
    source_names = [material['hgt_source'] for material in data.materials]
    positions = [tuple(vertex.co) for vertex in data.vertices]
    data.calc_loop_triangles()
    oriented = {}
    allowed = [True] * len(data.polygons)
    for triangle in data.loop_triangles:
        points = tuple(positions[i] for i in triangle.vertices)
        forward = min(points[i:] + points[:i] for i in range(3))
        points = points[::-1]
        reverse = min(points[i:] + points[:i] for i in range(3))
        if forward == reverse:
            continue
        for other_face, other_material in oriented.get(reverse, ()):
            if source_names[triangle.material_index] in names:
                allowed[triangle.polygon_index] = False
            if source_names[other_material] in names:
                allowed[other_face] = False
        oriented.setdefault(forward, []).append((triangle.polygon_index, triangle.material_index))
    attribute = data.attributes.new('outline_reference_surface', 'BOOLEAN', 'FACE')
    attribute.data.foreach_set('value', allowed)
    for modifier in mesh.modifiers:
        if modifier.type != 'NODES' or not modifier.node_group or not modifier.node_group.get('hgt_pmx_outline'):
            continue
        graph = modifier.node_group
        field = graph.nodes.new('GeometryNodeInputNamedAttribute')
        field.data_type = 'BOOLEAN'
        field.inputs['Name'].default_value = attribute.name
        for separate in tuple(graph.nodes):
            if separate.bl_idname != 'GeometryNodeSeparateGeometry':
                continue
            original = separate.inputs['Selection'].links[0].from_socket
            both = graph.nodes.new('FunctionNodeBooleanMath')
            both.operation = 'AND'
            graph.links.new(original, both.inputs[0])
            graph.links.new(field.outputs['Attribute'], both.inputs[1])
            graph.links.new(both.outputs[0], separate.inputs['Selection'])
    return len(allowed) - sum(allowed)


def parameters(root):
    s = root.hgt_character
    return {'global': {name: getattr(s, name) for name in
                       ('outline', 'outline_lower', 'shadow_position', 'shadow_transition', 'face_softness',
                        'face_softness_adjust', 'shadow_softness')},
            'materials': {b.source_name: {name: list(getattr(b, name)) if name.endswith('color') or name == 'tint'
                                         else getattr(b, name) for name in
                                         ('tint', 'shadow_color', 'outline_color', 'brightness', 'saturation', 'opacity')}
                          for b in s.bindings}}


def source_state(root):
    s = root.hgt_character
    return digest({'meshes': {e.object.name: mesh_data(e.original_data or e.object.data) for e in s.meshes},
                   'materials': {b.source.name: properties(b.source.mmd_material) for b in s.bindings},
                   'bones': [(b.name, b.parent.name if b.parent else None, [list(row) for row in b.matrix_local])
                             for b in s.source_armature.data.bones]})


def counts():
    return {name: len(getattr(bpy.data, name)) for name in ('objects', 'meshes', 'materials', 'node_groups')}


def render(path, root):
    addon.workflow.refresh_character(root, scene=bpy.context.scene)
    bpy.context.view_layer.update()
    bpy.ops.render.render()
    bpy.data.images['Render Result'].save_render(str(path))
    image = bpy.data.images.load(str(path), check_existing=False)
    pixels = np.array(image.pixels[:], dtype=np.float32).reshape((-1, 4))
    bpy.data.images.remove(image)
    return pixels


# Expectations come from inspecting the original assets and independently
# disabling just their unwanted selector in the published 2.4.0 graph.
for name, inner, reversed_sheets in (('安柏', set(), set()), ('纳西妲', set(), {'裙2'}), ('奥黛塔', {'裙内'}, set())):
    folder = out / name
    folder.mkdir(exist_ok=True)
    fixture = args.fixture_directory / name / 'model.blend'
    fixture_hash = file_hash(fixture)
    bpy.app.handlers.load_post.remove(addon.project_io.on_load)
    try:
        bpy.ops.wm.open_mainfile(filepath=str(fixture), load_ui=False)
    finally:
        bpy.app.handlers.load_post.append(addon.project_io.on_load)
    root = bpy.context.scene.hgt_target
    s = root.hgt_character
    assert all(m.node_group.get('hgt_outline_version') == 2 for e in s.meshes for m in e.object.modifiers
               if m.type == 'NODES' and m.node_group and m.node_group.get('hgt_pmx_outline'))
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = 384, 576
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    # This comparison isolates outline geometry. Use the unchanged hard-shadow
    # reference instead of the intentionally revised positive softness style.
    s.shadow_softness = .001
    for obj in scene.objects:
        if obj.name.startswith('Verification scene prop'):
            obj.hide_render = True
    before_source = source_state(root)
    original_selectors = [(node, node.inputs['Material'].default_value) for node in selectors(root)]
    original_names = selected_names(root)
    expected_names = sorted(n for n in original_names if n not in inner)
    assert set(original_names) >= inner and expected_names
    row = {'name': name, 'excluded_inner_surfaces': sorted(inner),
           'manual_reversed_sheet_reference': sorted(reversed_sheets), 'checks': {}, 'widths': {}}
    report['models'].append(row)
    s.outline = .18
    previous = render(folder / 'published-240.png', root)
    references = {}
    if reversed_sheets:
        row['reference_reversed_faces'] = sum(reference_sheet_faces(e.object, reversed_sheets) for e in s.meshes)
        assert row['reference_reversed_faces'] > 0
    for node, material in original_selectors:
        if material['hgt_source'] in inner:
            node.inputs['Material'].default_value = None
    for label, width in (('default', .18), ('wide', .6642105579376221)):
        s.outline = width
        references[label] = render(folder / ('isolated-reference-' + label + '.png'), root)
    for node, material in original_selectors:
        node.inputs['Material'].default_value = material
    prior = parameters(root)
    if prior['global']['shadow_softness'] <= .0010001:
        prior['global']['shadow_softness'] = 0
    addon.project_io.on_load(None)
    assert parameters(root) == prior and source_state(root) == before_source
    assert selected_names(root) == expected_names, (name, expected_names, selected_names(root))
    row['checks']['legacy_upgrade_preserves_parameters_and_source'] = True
    row['checks']['minimum_softness_normalized_to_zero'] = root.hgt_character.shadow_softness == 0
    migrated = {}
    for label, width in (('default', .18), ('wide', .6642105579376221)):
        s.outline = width
        pixels = render(folder / ('fixed-' + label + '.png'), root)
        error = float(np.abs(pixels - references[label]).max())
        assert error <= 1 / 255 + 1e-6, (name, label, error)
        migrated[label] = pixels
        row['widths'][label] = {'outline': s.outline, 'reference_max_error': error}
    row['checks']['material_colors_restored'] = True
    if inner:
        restored_pixels = int(np.count_nonzero(np.max(migrated['default'][:, :3] - previous[:, :3], axis=1) > .15))
        assert restored_pixels > 500, restored_pixels
        row['restored_color_pixels'] = restored_pixels
    s.outline = 0
    no_outline = render(folder / 'outline-off.png', root)
    silhouette_pixels = int(np.count_nonzero(migrated['default'][:, 3] - no_outline[:, 3] > .05))
    wide_pixels = int(np.count_nonzero(migrated['wide'][:, 3] - no_outline[:, 3] > .05))
    assert silhouette_pixels > 5 and wide_pixels > 20, (name, silhouette_pixels, wide_pixels)
    row['silhouette_pixels_with_outline'] = silhouette_pixels
    row['silhouette_pixels_with_wide_outline'] = wide_pixels
    row['checks']['outer_contours_preserved'] = True
    fallback = [b.source_name for b in s.bindings if b.source_name in expected_names and b.source_name not in reversed_sheets
                and not json.loads(b.generated['hgt_pmx'])['edge']]
    assert fallback, (name, 'Source-disabled exterior fallback lost')
    row['source_disabled_outer_surfaces'] = fallback
    row['checks']['source_disabled_outer_edges_preserved'] = True
    s.outline = .6642105579376221
    stable = counts()
    for _ in range(2):
        addon.project_io.on_load(None)
        addon.workflow.apply_materials(root, bpy.context)
        assert counts() == stable and selected_names(root) == expected_names
    row['checks']['no_resource_growth'] = True
    assert source_state(root) == before_source
    prior = parameters(root)
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'fixed.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(folder / 'fixed.blend'), load_ui=False)
    root = bpy.context.scene.hgt_target
    assert parameters(root) == prior
    reopened = render(folder / 'reopened.png', root)
    assert np.array_equal(reopened, migrated['wide'])
    row['checks']['save_reopen_exact'] = True
    before_source = source_state(root)
    addon.workflow.restore(root)
    addon.workflow.apply_materials(root, bpy.context)
    for key, value in prior['global'].items():
        setattr(root.hgt_character, key, value)
    for binding in root.hgt_character.bindings:
        for key, value in prior['materials'][binding.source_name].items():
            setattr(binding, key, value)
    assert source_state(root) == before_source and selected_names(root) == expected_names
    reapplied = render(folder / 'reapplied.png', root)
    assert np.array_equal(reapplied, migrated['wide'])
    row['checks']['restore_reapply_exact'] = True
    assert file_hash(fixture) == fixture_hash
    save()
report['complete'] = True
save()
print('HGT_OUTLINE_SURFACES_PASS', len(report['models']), report['package_sha256'])
