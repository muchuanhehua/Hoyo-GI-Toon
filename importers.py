"""One file entry routes FBX to Better FBX and PMX to native MMD Tools."""
from pathlib import Path
import bpy
from .asset_tracking import DataTransaction, ImportBatch, new_data, restore_state

# Explicitly disable destructive repair/optimization and attachment to existing rigs.
# These options are required rather than silently ignored on a different interface.
PRESERVE_OPTIONS = {
    "my_scale": 1.0,
    "use_auto_bone_orientation": False,
    "my_calculate_roll": "None",
    "primary_bone_axis": "Y",
    "secondary_bone_axis": "X",
    "my_rotation_mode": "QUATERNION",
    "my_fbx_unit": "cm",
    "use_fix_bone_poses": False,
    "use_fix_attributes": False,
    "use_only_deform_bones": False,
    "use_single_armature": False,
    "use_detect_deform_bone": False,
    "use_attach_to_selected_armature": False,
    "use_animation": True,
    "use_vertex_animation": True,
    "use_raw_keyframe": False,
    "my_animation_offset": 0,
    "use_animation_prefix": False,
    "use_pivot": False,
    "use_triangulate": False,
    "my_import_normal": "Import",
    "use_optimize_for_blender": False,
    "use_reset_mesh_origin": False,
    "use_reset_mesh_rotation": False,
    "use_fix_mesh_scaling": False,
    "use_import_materials": True,
    "use_rename_by_filename": False,
    "use_separate_collection": False,
    "my_vertex_color_space": "sRGB",
    "my_edge_smoothing": "Import",
    "use_auto_smooth": False,
    "use_edge_crease": True,
    "my_edge_crease_scale": 1.0,
}


def better_fbx_options(path, operator=None):
    operator = operator or bpy.ops.better_import.fbx
    try:
        properties = operator.get_rna_type().properties
    except (AttributeError, KeyError, RuntimeError) as exc:
        raise RuntimeError("请安装并启用 Better FBX Importer & Exporter，再导入模型") from exc
    options = {"filepath": str(path), "files": [{"name": path.name}], **PRESERVE_OPTIONS}
    if "directory" in properties:
        options["directory"] = str(path.parent)
    missing = sorted(set(options) - set(properties.keys()))
    if missing:
        raise RuntimeError("Better FBX 缺少保留数据所需的接口，请更新插件：" + ", ".join(missing))
    for name, value in options.items():
        prop = properties[name]
        if prop.type == "ENUM" and value not in prop.enum_items.keys():
            raise RuntimeError(f"Better FBX 参数不支持 {name}={value}，请核对插件版本")
    return options


def import_character(filepath, context=None):
    context = context or bpy.context
    path = Path(filepath).resolve()
    if not path.is_file():
        raise ValueError("模型文件不存在")
    extension = path.suffix.lower()
    if extension not in {'.fbx', '.pmx'}:
        raise ValueError('请选择 FBX 或 PMX 模型')
    if context.object and context.object.mode != "OBJECT":
        raise ValueError("请先退出编辑或姿态模式，再导入模型")
    if extension == '.pmx':
        from .mmd_importer import import_model
        return import_model(path, context)
    operator = bpy.ops.better_import.fbx
    options = better_fbx_options(path, operator)
    transaction = DataTransaction(context)
    try:
        result = operator("EXEC_DEFAULT", **options)
        if result != {"FINISHED"}:
            raise RuntimeError(f"Better FBX 导入未完成：{', '.join(sorted(result))}")
        batch = ImportBatch(str(path), new_data(transaction.before), options)
        if not batch.meshes:
            raise ValueError("Better FBX 未导入可渲染网格，请检查模型文件")
        # Better FBX sets global unit/frame settings; a model import must not change
        # an existing scene's timeline, units or render configuration.
        restore_state(transaction.state)
        return batch
    except Exception:
        transaction.rollback()
        raise
