"""Explicit shared face-field choices, independent of character names."""
import hashlib
import json
from pathlib import Path
from .material_assets import AssetError

ASSETS = Path(__file__).resolve().parent / 'assets'
PRESETS = {item['id']: item for item in json.loads((ASSETS / 'faces.json').read_text('utf-8'))['presets']}
ITEMS = (('AUTO', '自动匹配', '使用配套资源引用；也可直接选择内置 SDF'),
         ('NONE', '基础阴影', '关闭脸部 SDF，使用模型法线阴影')) + tuple(
    (key, item['name'], '共用脸部阴影；按模型的脸部 UV 选择') for key, item in PRESETS.items())


def resolve(preset):
    item = PRESETS.get(preset)
    if item is None:
        raise AssetError('内置 SDF 不存在：' + preset)
    paths = {role: ASSETS / name for role, name in item['textures'].items()}
    for role, path in paths.items():
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256'][role]:
            raise AssetError('内置 SDF 缺失或损坏：' + item['name'])
    return {'material': 'bundled:' + preset, 'preset': preset, 'encoding': item['encoding'],
            'property': item['property'], 'textures': paths, 'settings': item['settings'],
            'source_parameters': {}}


def matching(record):
    hashes = {role: hashlib.sha256(path.read_bytes()).hexdigest() for role, path in record['textures'].items()}
    return next((key for key, item in PRESETS.items() if item['encoding'] == record['encoding']
                 and item['sha256'] == hashes and item['settings'] == record['settings']), None)
