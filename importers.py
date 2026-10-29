"""The active workflow imports PMX through MMD Tools only."""
from pathlib import Path
import bpy
from .mmd_importer import import_model


def import_character(filepath, context=None):
    context = context or bpy.context
    path = Path(filepath).resolve()
    if not path.is_file():raise ValueError('模型文件不存在')
    if path.suffix.casefold() != '.pmx':raise ValueError('请选择 PMX 模型')
    if context.object and context.object.mode != 'OBJECT':raise ValueError('请先退出编辑或姿态模式')
    return import_model(path, context)
