"""Format-neutral subject records and reversible, evaluated surface selection."""
import json
import re
from collections import defaultdict
import bpy
from . import asset_tracking, surface_layers
from .asset_resolver import source_name

PART_ID = 'hgt_part_id'
VISIBLE = 'hgt_part_visible'
_STATES = {}


def explicit_role(name):
    """Match namespaces/whole labels; Avatar_Girl_Bow is a character, not a bow."""
    text = source_name(name).strip().casefold()
    if text.startswith(('flycloak_', 'glider_')) or re.fullmatch(r'(?:风之翼|風之翼|glider|flycloak)(?:[ _.-]*\d+)?', text):
        return 'GLIDER'
    if text.startswith(('equip_', 'equipskin_', 'weapon_')) or re.fullmatch(r'(?:武器|weapon|sword|claymore|polearm|catalyst)(?:[ _.-]*\d+)?', text):
        return 'WEAPON'
    if text.startswith(('skillobj_', 'eff_')) or re.fullmatch(r'(?:特效|effect|vfx)(?:[ _.-]*\d+)?', text):
        return 'EFFECT'
    if text.startswith('avatar_') and '_mat_' in text and text != 'avatar_default_mat':
        return 'BODY'
    return None


def material_role(material):
    if material is None:
        return None
    names = [material.name]
    mmd = getattr(material, 'mmd_material', None)
    if mmd:
        names = [mmd.name_j, mmd.name_e, *names]
    return next((role for name in names if (role := explicit_role(name))), None)


def bone_role(name):
    text = name.casefold()
    if 'weaponbox' in text or 'weapon_box' in text:
        return None
    if re.search(r'(?:^|[ _.+-])(?:weapon|equip)(?:[ _.-]|\d|$)', text) or '武器' in text:
        return 'WEAPON'
    if text.startswith(('flycloak', 'glider')) or '风之翼' in text or '風之翼' in text:
        return 'GLIDER'
    return None


def armature_for(obj):
    rig = obj.find_armature()
    parent = obj.parent
    while rig is None and parent:
        if parent.type == 'ARMATURE':
            rig = parent
        parent = parent.parent
    return rig


def _bone_roles(obj, mesh, rig):
    if rig is None:
        return [None] * len(mesh.vertices)
    roles = {}
    for group in obj.vertex_groups:
        bone = rig.data.bones.get(group.name)
        if bone is None:
            continue  # MMD edge/order groups are not skinning evidence.
        role = None
        while bone and role is None:
            role = bone_role(bone.name)
            bone = bone.parent
        roles[group.index] = role
    result = []
    for vertex in mesh.vertices:
        weights = defaultdict(float)
        total = 0
        for group in vertex.groups:
            if group.group in roles:
                total += group.weight
                weights[roles[group.group]] += group.weight
        selected = next((role for role in ('WEAPON','GLIDER') if total > 0 and weights[role] / total >= .9), None)
        result.append(selected)
    return result


def _components(mesh):
    parents = list(range(len(mesh.vertices)))
    def find(v):
        while parents[v] != v:
            parents[v] = parents[parents[v]]
            v = parents[v]
        return v
    for edge in mesh.edges:
        a,b = map(find,edge.vertices)
        if a != b:
            parents[b] = a
    return [find(p.vertices[0]) for p in mesh.polygons]


def classify(entry, source_format):
    obj = entry.object
    mesh = entry.original_data or obj.data
    rig = armature_for(obj)
    if getattr(obj, 'mmd_type', '') in {'RIGID_BODY','JOINT'}:
        return [('OTHER',True,'MMD physics helper',list(range(len(mesh.polygons))))], rig
    participation, basis = surface_layers.participation(obj) if source_format == 'fbx' else ('surface','MMD surfaces')
    if participation in {'placeholder','inactive_expression'}:
        return [('OTHER',True,basis,list(range(len(mesh.polygons))))], rig
    slots = [s.material for s in obj.material_slots]
    slot_roles = [material_role(m) for m in slots]
    weighted = _bone_roles(obj,mesh,rig)
    parent_role = bone_role(obj.parent_bone) if obj.parent_type == 'BONE' else None
    object_role = explicit_role(obj.name)
    components = _components(mesh)
    groups = defaultdict(list)
    for face, component in zip(mesh.polygons,components):
        skin_roles = {weighted[v] for v in face.vertices}
        role = next(iter(skin_roles)) if len(skin_roles)==1 else None
        evidence = 'weighted accessory bone' if role else ''
        if not role:
            role = slot_roles[face.material_index] if face.material_index < len(slot_roles) else None
            evidence = 'source material namespace' if role else ''
        if not role and parent_role:
            role,evidence = parent_role,'source bone parent'
        if not role and object_role:
            # A character atlas takes precedence over a loose mesh name.
            role,evidence = object_role,'source object label'
        if not role and source_format == 'pmx' and rig:
            role,evidence = 'BODY','MMD character rig and retained material'
        if not role:
            role,evidence = 'OTHER','unclassified surface; original visibility retained'
        # Keep disconnected unknowns independently correctable; merge body and
        # named attachments within one object, avoiding hundreds of face rows.
        island = component if role=='OTHER' else -1
        groups[(role,False,evidence,island)].append(face.index)
    return [(role,locked,basis,faces) for (role,locked,basis,_),faces in groups.items()], rig


def _filter(mesh, root):
    graph = next((m.node_group for m in mesh.modifiers if m.type=='NODES' and m.node_group
                  and m.node_group.get('hgt_subject_filter') and m.node_group.get('hgt_owner')==root.hgt_character.uid), None)
    if graph:
        return
    graph = bpy.data.node_groups.new(f'HGT • {mesh.name} • Selected Surfaces','GeometryNodeTree')
    graph['hgt_owner'],graph['hgt_subject_filter'] = root.hgt_character.uid,True
    graph.interface.new_socket(name='Geometry',in_out='INPUT',socket_type='NodeSocketGeometry')
    graph.interface.new_socket(name='Geometry',in_out='OUTPUT',socket_type='NodeSocketGeometry')
    start,end = graph.nodes.new('NodeGroupInput'),graph.nodes.new('NodeGroupOutput')
    marker = graph.nodes.new('GeometryNodeInputNamedAttribute');marker.data_type='BOOLEAN'
    marker.inputs['Name'].default_value=VISIBLE
    inverse=graph.nodes.new('FunctionNodeBooleanMath');inverse.operation='NOT'
    delete=graph.nodes.new('GeometryNodeDeleteGeometry');delete.domain='FACE'
    graph.links.new(start.outputs['Geometry'],delete.inputs['Geometry'])
    graph.links.new(marker.outputs['Attribute'],inverse.inputs[0])
    graph.links.new(inverse.outputs[0],delete.inputs['Selection'])
    graph.links.new(delete.outputs['Geometry'],end.inputs['Geometry'])
    modifier=mesh.modifiers.new('HGT • Selected Surfaces','NODES');modifier.node_group=graph


def initialize(root):
    from .properties import PART_ROLES
    settings=root.hgt_character
    if settings.parts_version:
        apply(root,force=True)
        return
    labels={role:label for role,label,_ in PART_ROLES}
    settings.parts.clear()
    for entry in settings.meshes:
        obj=entry.object
        if not obj:
            raise ValueError('导入对象引用缺失，请重新导入模型')
        groups,rig=classify(entry,settings.source_format)
        if rig and rig.get('hgt_owner')!=settings.uid:
            raise ValueError(f'{obj.name} 引用了其他导入批次的骨架，请检查模型归属')
        original=entry.original_data or obj.data
        records=[]
        for role,locked,basis,faces in groups:
            part=settings.parts.add();part.key=len(settings.parts)
            part.object,part.armature,part.role,part.locked=obj,rig,role,locked
            part.name=obj.name if len(groups)==1 else f'{obj.name} · {labels[role]}'
            part.basis,part.face_count=basis,len(faces)
            part.source_slots=json.dumps(sorted({original.polygons[i].material_index for i in faces}))
            part.included=not entry.original_hidden and role in {'BODY','OTHER'} and not locked
            records.append((part.key,faces))
        if any(not locked for _,locked,_,_ in groups):
            data=asset_tracking.derive_mesh(entry,settings.uid)
            ids=data.attributes.new(PART_ID,'INT','FACE')
            values=[0]*len(data.polygons)
            for key,faces in records:
                for index in faces:values[index]=key
            ids.data.foreach_set('value',values)
            data.attributes.new(VISIBLE,'BOOLEAN','FACE')
            if len(groups)>1:
                _filter(obj,root)
    settings.parts_version=1
    _STATES.pop(settings.uid,None)
    apply(root,force=True)


def validate(root):
    settings=root.hgt_character
    groups=defaultdict(list)
    for part in settings.parts:
        if part.object is None or part.object.get('hgt_owner')!=settings.uid:
            raise ValueError('角色部件引用缺失或归属改变，请重新导入模型')
        groups[part.object].append(part)
        if part.object.name not in bpy.context.view_layer.objects:
            raise ValueError('角色集合被排除，请先在当前视图层启用该集合')
    for entry in settings.meshes:
        if not entry.render_data:
            continue
        if entry.object.data!=entry.render_data:
            raise ValueError(f'{entry.object.name} 的渲染网格引用已改变，请恢复后重新装配')
        ids=entry.render_data.attributes.get(PART_ID)
        visible=entry.render_data.attributes.get(VISIBLE)
        keys={p.key for p in groups[entry.object]}
        if (ids is None or visible is None or ids.data_type!='INT' or ids.domain!='FACE'
                or visible.data_type!='BOOLEAN' or visible.domain!='FACE'
                or len(ids.data)!=sum(p.face_count for p in groups[entry.object])
                or any(item.value not in keys for item in ids.data)):
            raise ValueError(f'{entry.object.name} 的部件数据已改变，请恢复后重新装配')
    return groups


def apply(root, force=False):
    settings=root.hgt_character
    if not settings.parts_version:
        return
    signature=(tuple((p.key,p.role,p.included,p.locked,p.object.as_pointer() if p.object else 0) for p in settings.parts),
               tuple(e.render_data.as_pointer() if e.render_data else 0 for e in settings.meshes))
    if not force and _STATES.get(settings.uid)==signature:
        return
    groups=validate(root)
    for entry in settings.meshes:
        obj=entry.object
        selected={p.key:p.included and not p.locked for p in groups[obj]}
        visible=any(selected.values())
        obj.hide_render=not visible
        obj.hide_set(not visible)
        if entry.render_data:
            data=entry.render_data
            ids=data.attributes[PART_ID]
            values=[selected.get(item.value,False) for item in ids.data]
            data.attributes[VISIBLE].data.foreach_set('value',values)
            data.update()
    _STATES[settings.uid]=signature


def set_part(root, key, included=None, role=None):
    validate(root)
    part=next((p for p in root.hgt_character.parts if p.key==key and not p.locked),None)
    if part is None:
        raise ValueError('部件不存在或不允许显示')
    old_role,old_included=part.role,part.included
    if role is not None and role!=part.role:
        part.role=role
        if included is None:included=role in {'BODY','OTHER'}
    if included is not None:part.included=included
    if not any(p.included and not p.locked and p.face_count for p in root.hgt_character.parts):
        part.role,part.included=old_role,old_included
        raise ValueError('请至少选择一个可出图的部件')
    apply(root,force=True)


def clear(root):
    _STATES.pop(root.hgt_character.uid,None)
    root.hgt_character.parts.clear()
    root.hgt_character.parts_version=0
