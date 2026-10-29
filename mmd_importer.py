"""Scoped MMD import with audited bone ordering and MMD repair operators."""
import json
import bpy
from .asset_tracking import DataTransaction, ImportBatch, new_data, restore_state

OPTIONS = {'scale': .08, 'types': {'MESH', 'ARMATURE', 'PHYSICS', 'DISPLAY', 'MORPHS'},
           'clean_model': False, 'remove_doubles': False, 'rename_bones': False,
           'fix_bone_order': False, 'fix_ik_links': False, 'apply_bone_fixed_axis': False}


def _bones(armature):
    return {bone.name: {'mmd': _rna(bone.mmd_bone),
                        'parent': bone.parent.name if bone.parent else None,
                        'rest': [list(row) for row in bone.bone.matrix_local],
                        'pose': [list(row) for row in bone.matrix_basis],
                        'constraints': [_rna(c) for c in bone.constraints]}
            for bone in armature.pose.bones}


def _rna(item):
    """Serialize the repair's real metadata and ID references for audit."""
    result = {}
    for prop in item.bl_rna.properties:
        name = prop.identifier
        if name in {'rna_type', 'id_data'}:
            continue
        value = getattr(item, name)
        if prop.type == 'COLLECTION':
            result[name] = [_rna(child) for child in value]
        elif prop.type == 'POINTER':
            result[name] = value.name_full if isinstance(value, bpy.types.ID) else None
        elif isinstance(value, (str, int, float, bool)) or value is None:
            result[name] = value
        else:
            result[name] = _array(value)
    return result


def _array(value):
    return [v if isinstance(v, (str, int, float, bool)) else _array(v) for v in value]


def _state(root, armature):
    return {'bones': _bones(armature),
            'bone_morphs': [_rna(m) for m in root.mmd_root.bone_morphs],
            'display': [_rna(f) for f in root.mmd_root.display_item_frames],
            'collections': {c.name: [b.name for b in c.bones] for c in armature.data.collections_all}}


def import_model(path, context):
    try:
        properties = bpy.ops.mmd_tools.import_model.get_rna_type().properties
        bpy.ops.mmd_tools.fix_bone_order.get_rna_type()
        bpy.ops.mmd_tools.fix_bone_issues.get_rna_type()
    except (AttributeError, KeyError, RuntimeError) as exc:
        raise RuntimeError('请安装并启用 MMD Tools，再导入 PMX 模型') from exc
    options = {'filepath': str(path), **OPTIONS}
    missing = set(options) - set(properties.keys())
    if missing:
        raise RuntimeError('MMD Tools 缺少所需接口：' + ', '.join(sorted(missing)))
    transaction = DataTransaction(context)
    try:
        result = bpy.ops.mmd_tools.import_model('EXEC_DEFAULT', **options)
        if result != {'FINISHED'}:
            raise RuntimeError('MMD Tools 导入未完成：' + ', '.join(sorted(result)))
        data = new_data(transaction.before)
        roots = [o for o in data['objects'] if getattr(o, 'mmd_type', '') == 'ROOT']
        arms = [o for o in data['objects'] if o.type == 'ARMATURE']
        if len(roots) != 1 or len(arms) != 1:
            raise ValueError('PMX 未产生唯一模型根和骨架，请检查所选模型')
        root, armature = roots[0], arms[0]
        before = _state(root, armature)
        for obj in tuple(context.selected_objects):
            obj.select_set(False)
        armature.hide_set(False)
        armature.select_set(True)
        context.view_layer.objects.active = armature
        operators = ('fix_bone_order', 'fix_bone_issues')
        for operator in operators:
            result = getattr(bpy.ops.mmd_tools, operator)('EXEC_DEFAULT')
            if result != {'FINISHED'}:
                raise RuntimeError(f'MMD 骨骼修复未完成：{operator}')
        after = _state(root, armature)
        repair = {'operators': list(operators), 'before': before, 'after': after,
                  'import_fix_ik_links': False, 'import_apply_fixed_axis': False,
                  'effects': ['bone IDs and references', 'append-transform constraints',
                              'IK limit metadata migration', 'MMD bone-name validation']}
        root['hgt_mmd_repair'] = json.dumps(repair, ensure_ascii=False)
        restore_state(transaction.state)
        serial = {k: sorted(v) if isinstance(v, set) else v for k, v in options.items()}
        batch = ImportBatch(str(path), new_data(transaction.before), serial, 'mmd_tools.import_model',
                            'pmx', root, armature, repair)
        if not any(o.type == 'MESH' and getattr(o, 'mmd_type', '') not in {'RIGID_BODY', 'JOINT'} for o in batch.objects):
            raise ValueError('PMX 没有可渲染网格')
        return batch
    except Exception:
        transaction.rollback()
        raise
