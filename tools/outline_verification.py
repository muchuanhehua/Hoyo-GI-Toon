"""Immutable outline reference and route controls for private Blender checks."""
from pathlib import Path
import zipfile

import bpy


class OutlineRoutes:
    def __init__(self, addon, root):
        self.addon, self.root = addon, root
        project = Path(__file__).resolve().parents[1]
        namespace = {'__package__': addon.__name__, '__name__': addon.__name__ + '.reference_outlines'}
        with zipfile.ZipFile(project / 'release/hoyo_gi_toon-2.11.0.zip') as package:
            exec(compile(package.read('outlines.py'), '<2.11.0-outlines>', 'exec'), namespace)
        self.items = []
        for entry in root.hgt_character.meshes:
            mesh = entry.object
            modifier = next((m for m in mesh.modifiers if m.type == 'NODES' and m.node_group
                             and m.node_group.get('hgt_pmx_outline')), None)
            if modifier is None:
                continue
            current = modifier.node_group
            switch = next(n for n in current.nodes if n.get('hgt_preview_switch'))
            condition = switch.inputs['Switch'].links[0].from_socket
            previous = namespace['build'](mesh, root)
            reference = previous.node_group
            mesh.modifiers.remove(previous)
            self.items.append((mesh, modifier.name, reference, current, switch, condition))
        assert self.items, 'Fixture has no outline modifier'

    def select(self, mode):
        assert mode in {'baseline', 'final', 'preview'}
        for mesh, name, reference, current, switch, condition in self.items:
            for link in tuple(switch.inputs['Switch'].links):
                current.links.remove(link)
            if mode == 'preview':
                # Render the exact viewport geometry branch for stable pixel comparisons.
                switch.inputs['Switch'].default_value = True
            else:
                current.links.new(condition, switch.inputs['Switch'])
            mesh.modifiers[name].node_group = reference if mode == 'baseline' else current
        self.addon.workflow.refresh_character(self.root, scene=bpy.context.scene)
        bpy.context.view_layer.update()


def protected(root):
    from verification_data import mesh_data, digest, properties
    settings = root.hgt_character
    meshes = {}
    for entry in settings.meshes:
        data = mesh_data(entry.original_data)
        for shape in data['shapes'].values():
            shape.pop('value')
        data['weights'] = [(v.index, [(g.group, g.weight) for g in v.groups]) for v in entry.original_data.vertices]
        meshes[entry.object.name] = data
    actions = {}
    for action in bpy.data.actions:
        actions[action.name] = [(f.data_path, f.array_index,
            [(list(k.co), k.interpolation, list(k.handle_left), list(k.handle_right)) for k in f.keyframe_points])
            for layer in action.layers for strip in layer.strips for bag in strip.channelbags for f in bag.fcurves]
    return digest({'meshes': meshes, 'actions': actions,
        'materials': {b.source_name: properties(b.source.mmd_material) for b in settings.bindings},
        'bones': [(b.name, b.parent.name if b.parent else None, [list(r) for r in b.matrix_local])
                  for b in settings.source_armature.data.bones]})
