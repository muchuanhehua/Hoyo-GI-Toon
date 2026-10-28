"""File-format dispatch for the single import action."""
from pathlib import Path
import bpy


def import_character(filepath):
    path = Path(filepath)
    if not path.is_file():
        raise ValueError("模型文件不存在")
    suffix = path.suffix.lower()
    if suffix != ".fbx":
        raise ValueError("本版支持 FBX；PMX 将在 FBX 流程验收后接入同一入口")
    existing = {obj.as_pointer() for obj in bpy.data.objects}
    result = bpy.ops.wm.fbx_import(filepath=str(path), use_custom_normals=True,
                                   mtl_name_collision_mode="MAKE_UNIQUE")
    if result != {"FINISHED"}:
        raise RuntimeError("FBX 导入未完成")
    created = [obj for obj in bpy.data.objects if obj.as_pointer() not in existing]
    if not any(obj.type == "MESH" for obj in created):
        raise ValueError("模型中没有可渲染网格")
    return created
