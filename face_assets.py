"""Optional, explicitly related FBX face resources; never import geometry."""
import json
import re
import unicodedata
from pathlib import Path
from .material_assets import AssetError


def skin_material(material):
    names = (material.mmd_material.name_j, material.mmd_material.name_e, material.name)
    for name in names:
        name = unicodedata.normalize('NFKC', name).strip().casefold()
        if re.fullmatch(r'(?:颜|顏|顔|脸|臉|面)[12]?', name) or name in {'face', 'face_skin', 'faceskin'}:
            return True
    return False


def package_identity(name):
    return re.sub(r'(?:fbx|pmx)$', '', unicodedata.normalize('NFKC', name).casefold()).strip(' _-')


class FaceResources:
    def __init__(self, source='', directory=''):
        self.source = Path(source).resolve() if source else None
        self.directory = Path(directory).resolve() if directory else None
        self.record = None
        self.resolved = False
        self.status = 'not-resolved'

    def _packages(self, material):
        if self.directory:
            folder = self.directory
            if folder.name.casefold() in {'materials', 'textures'}:
                folder = folder.parent
            if not folder.is_dir():
                raise AssetError('脸部资源目录不存在')
            return [folder]
        sources = [self.source] if self.source else []
        node = material.node_tree.nodes.get('mmd_base_tex') if material and material.node_tree else None
        if node and node.image and node.image.filepath:
            import bpy
            image_path = Path(bpy.path.abspath(node.image.filepath, library=node.image.library)).resolve()
            sources.extend(p for p in image_path.parents if p.name.casefold().endswith('pmx'))
        packages = set()
        for source in sources:
            package = source if source.is_dir() else source.parent
            identities = {package_identity(package.name)}
            if source.suffix.casefold() in {'.pmx', '.pmd'}:
                identities.add(package_identity(source.stem))
            for parent in (package, package.parent):
                if not parent.is_dir():
                    continue
                for folder in (parent, *(p for p in parent.iterdir() if p.is_dir())):
                    if package_identity(folder.name) in identities:
                        packages.add(folder)
        return sorted(packages)

    @staticmethod
    def _texture(path, env, property_name):
        name = env.get('m_Texture', {}).get('Name', '')
        folder = path.parent.parent / 'Textures'
        matches = [p for p in folder.iterdir() if p.is_file() and p.stem == name] if name and folder.is_dir() else []
        if len(matches) != 1:
            raise AssetError(f'{property_name} 的贴图引用缺失或不唯一：{name}')
        return matches[0]

    def resolve(self, material=None):
        if self.resolved:
            return self.record
        candidates = [p for folder in self._packages(material)
                      for p in (folder / 'Materials').glob('*_Mat_Face.json')]
        if not candidates:
            if self.directory:
                raise AssetError('指定目录没有脸部材质 JSON，请选择对应 FBX 资源包')
            self.resolved, self.status = True, 'no-related-assets'
            return None
        if len(candidates) != 1:
            raise AssetError('同角色存在多份脸部资源，请指定对应 FBX 资源目录')
        path = candidates[0]
        raw = json.loads(path.read_text(encoding='utf-8-sig'))
        props = raw.get('m_SavedProperties')
        if not isinstance(props, dict) or not isinstance(props.get('m_TexEnvs'), dict):
            raise AssetError('脸部材质 JSON 缺少有效的贴图引用：' + path.name)
        floats, envs = props.get('m_Floats', {}), props['m_TexEnvs']
        if floats.get('_UseFaceSDF', 0) > 0:
            key, encoding = '_FaceSdfMap', 'genshin_face_sdf_rgba'
        elif floats.get('_UseFaceMapNew', 0) > 0:
            key, encoding = '_FaceMapTex', 'genshin_face_lightmap_alpha'
        else:
            self.resolved, self.status = True, 'source-sdf-disabled'
            return None
        textures, settings = {}, {}
        for role, property_name in [('face_sdf', key), ('face_mask', '_LightMapTex')]:
            env = envs.get(property_name, {})
            textures[role] = self._texture(path, env, property_name)
            settings[role] = {'m_Scale': env.get('m_Scale', {}), 'm_Offset': env.get('m_Offset', {})}
        self.record = {
            'material': str(path), 'encoding': encoding, 'property': key,
            'textures': textures, 'settings': settings,
            'source_parameters': {k: floats[k] for k in (
                '_UseFaceMapNew', '_UseFaceSDF', '_NewFaceUseLegacySampling',
                '_FaceSdfShadowSharpness', '_FaceMapSoftness') if k in floats}}
        self.resolved, self.status = True, 'matched'
        return self.record

    def bind(self, assets, material=None):
        record = self.resolve(material)
        assets.features['face_sdf_status'] = self.status
        if record is None:
            return False
        assets.features.update(template='Face', face_skin=True)
        assets.features['face_sdf'] = {k: v for k, v in record.items() if k not in {'textures', 'settings'}}
        for role, path in record['textures'].items():
            assets.textures[role] = path
            assets.texture_settings[role] = record['settings'][role]
            property_name = record['property'] if role == 'face_sdf' else '_LightMapTex'
            assets.evidence[role] = record['material'] + ' -> ' + property_name
        return True
