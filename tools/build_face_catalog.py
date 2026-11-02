"""Collect referenced Genshin face fields and masks; deduplicate exact bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--resources', type=Path, required=True)
args = parser.parse_args()
records, images, protected = {}, {}, {}
labels = {'Boy': '少年', 'Boy01': '少年 01', 'Girl': '少女', 'Girl01': '少女 01',
          'Lady': '成女', 'Lady01': '成女 01', 'Loli': '幼女', 'Loli01': '幼女 01'}
for path in sorted(args.resources.rglob('*_Mat_Face.json')):
    raw = path.read_bytes()
    protected[path] = hashlib.sha256(raw).hexdigest()
    props = json.loads(raw.decode('utf-8-sig'))['m_SavedProperties']
    floats, envs = props.get('m_Floats', {}), props['m_TexEnvs']
    key = ('_FaceSdfMap' if floats.get('_UseFaceSDF', 0) > 0 else
           '_FaceMapTex' if floats.get('_UseFaceMapNew', 0) > 0 else None)
    if key is None:
        continue
    encoding = 'genshin_face_sdf_rgba' if key == '_FaceSdfMap' else 'genshin_face_lightmap_alpha'
    textures, settings, hashes = {}, {}, {}
    for role, prop in (('face_sdf', key), ('face_mask', '_LightMapTex')):
        env = envs[prop]
        name = env['m_Texture']['Name']
        matches = [p for p in (path.parent.parent / 'Textures').iterdir() if p.is_file() and p.stem == name]
        if len(matches) != 1:
            raise ValueError(f'{path.name}: missing or ambiguous {prop}: {name}')
        source = matches[0]
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        protected[source] = digest
        destination = f'faces/{source.stem}-{digest[:12]}{source.suffix.lower()}'
        images[destination] = source
        textures[role], hashes[role] = destination, digest
        settings[role] = {p: env.get(p, {}) for p in ('m_Scale', 'm_Offset')}
    identity = json.dumps((encoding, hashes, settings), sort_keys=True)
    if identity not in records:
        body = name = envs[key]['m_Texture']['Name'].split('_Tex_')[0].removeprefix('Avatar_')
        if encoding == 'genshin_face_lightmap_alpha':
            identifier, label = 'LEGACY_' + body.upper(), labels[body] + ' · FaceLightmap'
        else:
            identifier = f'SDF_{body.upper()}_{hashes["face_sdf"][:8]}_{hashes["face_mask"][:8]}'.upper()
            atlas = 'A' if hashes['face_sdf'].startswith('c622a8') else 'B'
            mask = '02' if 'Face02_' in textures['face_mask'] else '01'
            label = f'{labels[body]} · FaceSDF {atlas} / 遮罩 {mask}'
        records[identity] = {'id': identifier, 'name': label, 'encoding': encoding,
                             'property': key, 'textures': textures, 'sha256': hashes,
                             'settings': settings, 'source_materials': []}
    records[identity]['source_materials'].append(path.name)
presets = sorted(records.values(), key=lambda item: item['id'])
assert len({p['id'] for p in presets}) == len(presets)
for destination, source in images.items():
    target = ROOT / 'assets' / destination
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != source.read_bytes():
        raise ValueError('Refusing to replace a different face asset: ' + destination)
    shutil.copy2(source, target)
catalog = {'schema_version': 1, 'source': 'HoYoverse / Genshin Impact', 'presets': presets}
(ROOT / 'assets/faces.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', 'utf-8')
assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in protected.items())
print(json.dumps({'presets': len(presets), 'images': len(images),
                  'bytes': sum(p.stat().st_size for p in images.values()),
                  'source_files_unchanged': len(protected)}, ensure_ascii=False))
