"""Reversible, character-local jelly eyes; original animation and assets stay read-only."""
import re
import unicodedata
import uuid
import bpy
from . import scene_models, jelly_geometry

OWNER = 'hgt_jelly_owner'
BONE_NAMES = ({'左目', '左眼', 'eyel', 'lefteye', 'eyeleft'},
              {'右目', '右眼', 'eyer', 'righteye', 'eyeright'})
EXCLUDES = ('白目', '眼白', 'sclera', 'eyewhite', '目影', '眼影', 'shadow', '睫', 'lash',
            '眉', 'brow', '眼皮', 'eyelid', 'まぶた', 'outline', '描边')
FOLLOW = ('目光', '目hl', '星目', '星眼', '眼高光', 'catchlight', 'highlight', 'hilight', 'ハイライト')


def normalized(name):
    return re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', name).casefold())


def eye_bones(rig):
    result = {}
    for side, aliases in enumerate(BONE_NAMES, 1):
        candidates = [b for b in rig.pose.bones if not b.name.startswith('_') and
                      any(normalized(n) in aliases for n in (b.name, b.mmd_bone.name_j, b.mmd_bone.name_e))]
        if len(candidates) != 1:
            raise ValueError('无法唯一识别左右眼骨骼，请检查 Left Eye / Right Eye / 左目 / 右目 命名')
        result[side] = candidates[0].bone
    if (result[1].head_local - result[2].head_local).length < 1e-6:
        raise ValueError('左右眼骨骼中心重合，无法安全划分眼睛')
    return result


def material_kind(material):
    if material is None:
        return 'OTHER'
    mmd = material.mmd_material
    names = [normalized(n) for n in (mmd.name_j, mmd.name_e, material.name)]
    if any(token in n for n in names for token in EXCLUDES):
        return 'OTHER'
    if any(token in n for n in names for token in FOLLOW):
        return 'FOLLOW'
    if any(re.fullmatch(r'(目|瞳|瞳孔|眼睛|眼球|虹膜|iris|pupil|eyes?)\d*', n) for n in names):
        return 'CORE'
    return 'OTHER'


def _anchors(obj, indices, matrix):
    coords = {i: matrix @ obj.data.vertices[i].co for i in indices}
    a = min(coords, key=lambda i: coords[i].x)
    b = max(coords, key=lambda i: coords[i].x)
    axis = coords[b] - coords[a]
    if axis.length < 1e-7:
        raise ValueError(obj.name + ' 的虹膜宽度无效')
    c = max(coords, key=lambda i: axis.cross(coords[i] - coords[a]).length_squared)
    if axis.cross(coords[c] - coords[a]).length < 1e-10:
        raise ValueError(obj.name + ' 的虹膜没有有效表面')
    return (a, b, c)


def _modifier_index(obj, rig):
    if obj.mode != 'OBJECT' or not obj.is_editable:
        raise ValueError('请先退出编辑／雕刻模式，并将角色对象设为可编辑：' + obj.name)
    armatures = [m for m in obj.modifiers if m.type == 'ARMATURE' and m.object == rig]
    if len(armatures) != 1:
        raise ValueError(obj.name + ' 需要唯一且启用的原模型骨架修改器')
    armature = armatures[0]
    if not armature.show_viewport or not armature.show_render:
        raise ValueError(obj.name + ' 的原骨架修改器在视口或渲染中关闭')
    index = list(obj.modifiers).index(armature) + 1
    if any(m.type not in {'ARMATURE', 'SMOOTH', 'CORRECTIVE_SMOOTH', 'LAPLACIANSMOOTH', 'DISPLACE', 'CAST', 'WARP', 'SIMPLE_DEFORM'}
           for m in list(obj.modifiers)[:index]):
        raise ValueError(obj.name + ' 的骨架前有改变拓扑的修改器，无法安全对应原眼睛顶点')
    return index


def plan(root, scene):
    rig = scene_models.armature(root)
    if not rig or not root.is_editable:
        raise ValueError('请选择可编辑的本地 MMD 模型')
    if abs(rig.matrix_world.determinant()) < 1e-12:
        raise ValueError('骨架缩放为零，无法建立眼睛参照')
    bones = eye_bones(rig)
    groups = {b.name: side for side, bone in bones.items() for b in (bone, *bone.children_recursive)}
    tracked = scene_models.tracked(root, scene)
    originals = {b.generated: b.source for b in tracked.hgt_character.bindings if b.generated} if tracked else {}
    plans, found = [], set()
    for obj in scene_models.meshes(root):
        kinds = [material_kind(originals.get(s.material, s.material)) for s in obj.material_slots]
        if not any(k != 'OTHER' for k in kinds):
            continue
        matrix = rig.matrix_world.inverted() @ obj.matrix_world
        region = [0.] * len(obj.data.vertices)
        core = [0.] * len(region)
        used, other, sides = set(), set(), {}
        for polygon in obj.data.polygons:
            kind = kinds[polygon.material_index] if polygon.material_index < len(kinds) else 'OTHER'
            if kind == 'OTHER':
                other.update(polygon.vertices)
                continue
            assignments = []
            for i in polygon.vertices:
                vertex = obj.data.vertices[i]
                weights = {1: 0., 2: 0.}
                for assignment in vertex.groups:
                    side = groups.get(obj.vertex_groups[assignment.group].name)
                    if side:
                        weights[side] += assignment.weight
                side = max(weights, key=weights.get)
                assignments.append((i, side, weights[side] >= .8 and weights[3 - side] <= .05))
            # A generically named highlight can belong to a shiny accessory.
            # Only eye-bound faces may follow an iris.
            if kind == 'FOLLOW' and not any(valid for _, _, valid in assignments):
                other.update(polygon.vertices)
                continue
            if not all(valid for _, _, valid in assignments) or len({side for _, side, _ in assignments}) != 1:
                raise ValueError(obj.name + ' 的眼睛／高光没有明确绑定到单侧眼骨，未修改模型')
            for i, side, _ in assignments:
                region[i] = float(side)
                core[i] = max(core[i], float(kind == 'CORE'))
                used.add(i)
                if kind == 'CORE':
                    sides.setdefault(side, set()).add(i)
        if used & other:
            raise ValueError(obj.name + ' 的虹膜与非眼睛面共享顶点，无法隔离果冻眼')
        if any(int(region[i]) not in sides for i in used):
            raise ValueError(obj.name + ' 的高光与对应虹膜不在同一网格，无法可靠约束，请先合并眼睛网格')
        if not used:
            continue
        index = _modifier_index(obj, rig)
        anchors = {side: _anchors(obj, indices, matrix) for side, indices in sides.items()}
        found.update(sides)
        plans.append(dict(obj=obj, region=region, core=core, eyes=anchors, index=index))
    if found != {1, 2}:
        raise ValueError('未识别完整的左右虹膜，请检查眼睛材质（目 / 眼睛 / 瞳 / Iris / Pupil）及眼骨权重')
    return plans


def is_active(root):
    return bool(root and root.hgt_jelly.entries)


def error(root):
    if not is_active(root):
        return ''
    for entry in root.hgt_jelly.entries:
        obj, graph = entry.object, entry.graph
        if not obj or not graph or not entry.mask:
            return '果冻眼引用缺失，请关闭后重新启用'
        modifier = obj.modifiers.get(entry.modifier)
        if not modifier or modifier.type != 'NODES' or modifier.node_group != graph:
            return obj.name + ' 的果冻眼修改器已改变，请关闭后重新启用'
        modifiers = list(obj.modifiers)
        rig = scene_models.armature(root)
        armature = next((m for m in modifiers if m.type == 'ARMATURE' and m.object == rig), None)
        if not armature or modifiers.index(modifier) != modifiers.index(armature) + 1:
            return obj.name + ' 的果冻眼须紧接原骨架修改器，请恢复顺序'
        if len(obj.data.vertices) != entry.vertex_count:
            return obj.name + ' 的顶点数已改变，果冻眼已暂停，请关闭后重新启用'
        if any(not (attr := entry.mask.data.attributes.get(name)) or attr.domain != 'POINT' or attr.data_type != 'FLOAT'
               for name in ('region', 'core')):
            return obj.name + ' 的果冻眼范围数据缺失，请关闭后重新启用'
    return ''


def _clean(records, collection):
    for obj, name, graph, helper, mesh, animation_created in reversed(records):
        modifier = obj.modifiers.get(name) if obj else None
        if obj and (not modifier or modifier.type != 'NODES' or modifier.node_group != graph):
            modifier = next((m for m in obj.modifiers if m.type == 'NODES' and m.node_group == graph), None)
        if modifier and modifier.type == 'NODES' and modifier.node_group == graph:
            jelly_geometry.remove_drivers(obj, modifier)
            obj.modifiers.remove(modifier)
        animation = obj.animation_data if obj else None
        if animation_created and animation and not animation.action and not animation.drivers and not animation.nla_tracks:
            obj.animation_data_clear()
        if graph and graph.users == 0:
            bpy.data.node_groups.remove(graph)
        # Glow temporarily links all scene objects into its owned source layer.
        # Those links are ours too; genuine external users must survive.
        owned_links = helper and all(c.get(OWNER) == helper.get(OWNER) or c.get('hgt_glow_source') in {'Character', 'Occluders', 'Support'}
                                     for c in helper.users_collection)
        if helper and owned_links and helper.users == len(helper.users_collection):
            bpy.data.objects.remove(helper, do_unlink=True)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    if collection and not collection.objects and not collection.children:
        bpy.data.collections.remove(collection)


def enable(root, scene):
    root = scene_models.source_root(root)
    if is_active(root):
        raise ValueError('当前角色已开启果冻眼')
    plans = plan(root, scene)
    settings, records = root.hgt_jelly, []
    collection = bpy.data.collections.new('HGT • Jelly Eyes')
    collection[OWNER] = root
    try:
        scene.collection.children.link(collection)
        for item in plans:
            obj = item['obj']
            mesh = bpy.data.meshes.new('HGT • Jelly Mask')
            helper = bpy.data.objects.new('HGT • Jelly Mask', mesh)
            graph = bpy.data.node_groups.new('HGT • Jelly ' + uuid.uuid4().hex[:12], 'GeometryNodeTree')
            animation_created = obj.animation_data is None
            records.append((obj, '', graph, helper, mesh, animation_created))
            for data in (mesh, helper, graph):
                data[OWNER] = root
            mesh.from_pydata([(0, 0, 0)] * len(item['region']), [], [])
            for name in ('region', 'core'):
                attr = mesh.attributes.new(name, 'FLOAT', 'POINT')
                attr.data.foreach_set('value', item[name])
            collection.objects.link(helper)
            helper.hide_render = helper.hide_select = True
            helper.hide_set(True)
            jelly_geometry.build(graph, helper, item['eyes'], len(mesh.vertices))
            modifier = obj.modifiers.new('HGT • Jelly Eyes', 'NODES')
            modifier.node_group = graph
            records[-1] = (obj, modifier.name, graph, helper, mesh, animation_created)
            modifier_index = len(obj.modifiers) - 1
            obj.modifiers.move(modifier_index, item['index'])
            modifier = obj.modifiers.get(records[-1][1])
            jelly_geometry.add_drivers(obj, modifier, root)
            entry = settings.entries.add()
            entry.object, entry.graph, entry.mask = obj, graph, helper
            entry.modifier, entry.vertex_count = modifier.name, len(mesh.vertices)
            entry.animation_created = animation_created
        settings.collection = collection
    except Exception:
        settings.entries.clear()
        settings.collection = None
        _clean(records, collection)
        raise


def disable(root):
    root = scene_models.source_root(root)
    settings = root.hgt_jelly
    if settings.collection and settings.collection.get(OWNER) != root:
        raise ValueError('果冻眼集合归属已改变，未清理其他数据')
    records = []
    for entry in settings.entries:
        graph, helper = entry.graph, entry.mask
        if (graph and graph.get(OWNER) != root or helper and helper.get(OWNER) != root or
                helper and (helper.type != 'MESH' or helper.data.get(OWNER) != root)):
            raise ValueError('果冻眼资源归属已改变，未清理其他数据')
        records.append((entry.object, entry.modifier, graph, helper, helper.data if helper else None, entry.animation_created))
    collection = settings.collection
    settings.entries.clear()
    settings.collection = None
    _clean(records, collection)
