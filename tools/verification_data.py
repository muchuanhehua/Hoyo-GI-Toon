"""Data fingerprints for source-preservation checks in background Blender."""
import hashlib
import json
import numpy as np
import bpy


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def array_hash(collection, attribute, width=1, dtype=np.float32):
    values = np.empty(len(collection) * width, dtype=dtype)
    if len(values):
        collection.foreach_get(attribute, values)
    return hashlib.sha256(values.tobytes()).hexdigest()


def matrix(value):
    return [[round(v, 6) for v in row] for row in value]


def scalar(value):
    if isinstance(value, bpy.types.ID):
        return value.as_pointer()
    if hasattr(value, 'to_list'):
        return value.to_list()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return list(value)


def properties(item):
    result = {}
    for prop in item.bl_rna.properties:
        name = prop.identifier
        if name in {'rna_type', 'name', 'is_updated', 'is_updated_data', 'is_active', 'execution_time'} or prop.type == 'COLLECTION':
            continue
        try:
            result[name] = scalar(getattr(item, name))
        except (AttributeError, TypeError):
            continue
    return result


def mesh_data(mesh, uv_names=None, color_names=None):
    result = {
        'vertices': array_hash(mesh.vertices, 'co', 3),
        'edges': array_hash(mesh.edges, 'vertices', 2, np.int32),
        'loops': array_hash(mesh.loops, 'vertex_index', 1, np.int32),
        'polygons': {a: array_hash(mesh.polygons, a, 1, np.int32) for a in ('loop_start', 'loop_total', 'material_index')},
        'custom_normals': mesh.has_custom_normals,
        'normals': array_hash(mesh.corner_normals, 'vector', 3),
        'uv': {uv.name: array_hash(uv.data, 'uv', 2) for uv in mesh.uv_layers
               if uv_names is None or uv.name in uv_names},
        'colors': {c.name: {'domain':c.domain, 'type':c.data_type, 'values':array_hash(c.data, 'color', 4)}
                   for c in mesh.color_attributes if color_names is None or c.name in color_names},
        'shapes': {},
    }
    if mesh.shape_keys:
        for key in mesh.shape_keys.key_blocks:
            result['shapes'][key.name] = {'coordinates':array_hash(key.data, 'co', 3),
                                         'relative':key.relative_key.name, 'value':key.value,
                                         'min':key.slider_min, 'max':key.slider_max, 'mute':key.mute,
                                         'vertex_group':key.vertex_group}
    return result


def source_snapshot(batch):
    result = {'objects':{}, 'meshes':{}, 'armatures':{}, 'images':{}, 'materials':{}, 'actions':{}}
    for obj in batch.objects:
        result['objects'][str(obj.as_pointer())] = {
            'name':obj.name, 'type':obj.type, 'parent':obj.parent.as_pointer() if obj.parent else None,
            'parent_type':obj.parent_type, 'parent_bone':obj.parent_bone,
            'basis':matrix(obj.matrix_basis), 'parent_inverse':matrix(obj.matrix_parent_inverse),
            'world':matrix(obj.matrix_world),
            'weights':digest([(v.index,[(g.group, g.weight) for g in v.groups]) for v in obj.data.vertices]) if obj.type=='MESH' else None,
            'groups':[(g.name,g.index,g.lock_weight) for g in obj.vertex_groups] if obj.type=='MESH' else [],
            'modifiers': [properties(m) for m in obj.modifiers if not (m.type=='NODES' and m.node_group and m.node_group.get('hgt_owner'))],
        }
    for mesh in batch.data.get('meshes', ()):
        result['meshes'][str(mesh.as_pointer())] = mesh_data(mesh)
    for arm in batch.data.get('armatures', ()):
        result['armatures'][str(arm.as_pointer())] = [
            {'name':b.name,'parent':b.parent.name if b.parent else None, 'matrix':matrix(b.matrix_local),
             'deform':b.use_deform,'connected':b.use_connect,'inherit_scale':b.inherit_scale}
            for b in arm.bones]
    for image in batch.data.get('images', ()):
        result['images'][str(image.as_pointer())] = {'name':image.name,'path':image.filepath,
               'colorspace':image.colorspace_settings.name,'alpha':image.alpha_mode, 'packed':bool(image.packed_file)}
    for material in batch.data.get('materials', ()):
        result['materials'][str(material.as_pointer())] = {
            'diffuse':list(material.diffuse_color), 'use_nodes':material.use_nodes,
            'nodes':[(n.name,n.bl_idname,properties(n),
                     [(s.identifier,scalar(s.default_value)) for s in n.inputs if hasattr(s,'default_value')])
                     for n in material.node_tree.nodes] if material.node_tree else [],
            'links':[(l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier)
                     for l in material.node_tree.links] if material.node_tree else []}
    for action in batch.data.get('actions', ()):
        bags = [bag for layer in action.layers for strip in layer.strips for bag in strip.channelbags]
        result['actions'][str(action.as_pointer())] = [(f.data_path,f.array_index,
                [(list(k.co), k.interpolation, list(k.handle_left), list(k.handle_right)) for k in f.keyframe_points])
                for bag in bags for f in bag.fcurves]
    return result
