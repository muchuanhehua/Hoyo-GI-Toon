"""PMX material semantics adapted from the two reference render workflows."""
from pathlib import Path
import unicodedata
import sys
import bpy
import numpy as np
from .material_assets import MaterialAssets, AssetError
from .node_graph import Graph

FACE_NAMES = {'颜', '顏', '顔', '脸', '臉', '白目', '眼白', '口舌', '口', '齿', '歯', '二重', '颜饰'}
EYE_NAMES = {'目', '瞳', '眼睛', '虹膜'}
BROW_NAMES = {'睫眉', '眉', '睫', 'まつげ'}
HIDDEN_NAMES = {'星目', '星眼', 'eyestar'}
DEFAULT_SHADOW_COLOR = (.96, .94, .94)
DEFAULT_SHADOW_POSITION = .52
DEFAULT_OUTLINE = .18
SHADOW_TRANSITION = .035
AMBIENT_COLOR_STRENGTH = .20


def material_color(pmx):
    # PMX's own ambient color offsets the darkening of legacy diffuse factors.
    # Clamp the coefficient, keeping white albedos from receiving an HDR gain.
    return tuple(min(1.0, max(0.0, diffuse + ambient * AMBIENT_COLOR_STRENGTH))
                 for diffuse, ambient in zip(pmx['diffuse'], pmx['ambient']))


def configure_transparency(material, role, overlay):
    # Blended meshes have no per-triangle sorting. Rendering every fragment
    # lets rear skin/cloth triangles overwrite the front in UV-shaped patches.
    # Keep intentional eye/expression and additive layers on their own path.
    overlap = overlay or role in {'eye', 'brow', 'expression'}
    if material.use_transparency_overlap != overlap:
        material.use_transparency_overlap = overlap


def role_for(material):
    data = material.mmd_material
    names = [unicodedata.normalize('NFKC', n).casefold() for n in (data.name_j, data.name_e, material.name) if n]
    for name in names:
        if name in HIDDEN_NAMES:
            return 'expression'
        if name in BROW_NAMES or any(t in name for t in ('eyebrow', 'eyelash')):
            return 'brow'
        if name in EYE_NAMES or name.startswith(('目', '瞳')) or any(t in name for t in ('pupil', 'iris')):
            return 'eye'
        if name in FACE_NAMES or name.startswith(('颜', '顏', '顔')) or 'face' in name:
            return 'face'
        if any(t in name for t in ('髮', '髪', '头发', 'hair', '前发')):
            return 'hair'
    return 'body'


class Catalog:
    def __init__(self, source='', face_directory=''):
        from .face_assets import FaceResources
        self.face_resources=FaceResources(source, face_directory)
        self.alpha_min = {}

    def resolve(self, name, material):
        result = MaterialAssets(name, role_for(material))
        data = material.mmd_material
        result.source_format = 'pmx'
        result.pmx = {'alpha': float(data.alpha), 'diffuse': tuple(data.diffuse_color),
                      'ambient': tuple(data.ambient_color),
                      'double_sided': data.is_double_sided, 'sphere_mode': str(data.sphere_texture_type),
                      'edge': data.enabled_toon_edge, 'edge_weight': float(data.edge_weight),
                      'edge_color': tuple(data.edge_color),
                      'overlay': any(n.endswith('+') for n in (data.name_j, data.name_e))}
        result.pmx['texture_alpha_min'] = 1.0
        for role, node_name in (('diffuse', 'mmd_base_tex'), ('toon', 'mmd_toon_tex'), ('sphere', 'mmd_sphere_tex')):
            if role == 'sphere' and result.pmx['sphere_mode'] == '0':
                continue
            node = material.node_tree.nodes.get(node_name) if material.node_tree else None
            image = node.image if node else None
            if image is None:
                continue
            path = Path(bpy.path.abspath(image.filepath, library=image.library)).resolve()
            basis = f'PMX {node_name} reference'
            packed = bool(image.packed_file) or image.source == 'GENERATED'
            if role == 'toon' and data.is_shared_toon_texture and not path.is_file() and not packed:
                # MMD's indexed shared ramp belongs to its importer package.
                # An unconfigured MMD preference can leave a relative image path.
                package = sys.modules.get(type(data).__module__.split('.properties.')[0])
                if package and getattr(package, '__file__', None):
                    path = Path(package.__file__).parent / 'externals' / 'MikuMikuDance' / f'toon{data.shared_toon_texture+1:02d}.bmp'
                    basis = f'MMD shared Toon index {data.shared_toon_texture}'
            if not path.is_file() and not packed:
                raise AssetError(f'{name} 缺少 PMX {role} 贴图：{path.name}')
            result.textures[role] = image if packed else path
            result.evidence[role] = basis
            if role == 'diffuse':
                if image not in self.alpha_min:
                    pixels = np.empty(len(image.pixels), dtype=np.float32)
                    image.pixels.foreach_get(pixels)
                    if not len(pixels):
                        raise AssetError(f'{name} 的基础贴图无法读取：{path.name}')
                    self.alpha_min[image] = float(pixels[3::4].min())
                result.pmx['texture_alpha_min'] = self.alpha_min[image]
        if 'diffuse' not in result.textures:
            # PMX permits solid-color materials. Preserve their explicit color.
            result.pmx['solid_color'] = True
        if result.pmx['sphere_mode'] not in {'0', '1', '2', '3'}:
            raise AssetError(f'{name} 的 Sphere 混合模式无法识别')
        if result.pmx['sphere_mode'] != '0' and 'sphere' not in result.textures:
            raise AssetError(f'{name} 缺少已启用的 Sphere 贴图')
        result.features = {'template':'Hair' if result.role == 'hair' else 'Body', 'uses_body':True}
        from .face_assets import skin_material
        if skin_material(material):
            result.role='face'
            self.face_resources.bind(result, material)
        return result


def _constant_image(library):
    from .shaders import neutral_packed
    return neutral_packed(library.uid)


def build(library, assets):
    from .shaders import walk, load_image
    kind = assets.features['template']
    material = library.materials['HoYoverse - Genshin ' + kind].copy()
    material.name = f'HGT • {library.root.name} • {assets.source}'
    material['hgt_owner'], material['hgt_source'], material['hgt_role'] = library.uid, assets.source, assets.role
    material['hgt_template'] = kind
    material['hgt_format'] = 'pmx'
    library._private_textures(material.node_tree, {})
    graph = Graph(material, assets, library.uid, load_image)
    uv = graph.uv()
    diffuse = graph.texture('diffuse', data=False) if 'diffuse' in assets.textures else None
    for tree in walk(material.node_tree):
        for node in tree.nodes:
            if node.type != 'TEX_IMAGE':
                continue
            if 'Diffuse' in node.name and diffuse:
                node.image = diffuse.image
                node['hgt_texture_role'] = 'diffuse'
                if tree == graph.tree:
                    graph.link(uv, node.inputs['Vector'])
            elif 'Lightmap' in node.name and kind != 'Face':
                node.image = _constant_image(library)
                node['hgt_texture_role'] = 'neutral_packed'
    body = graph.shader
    if kind == 'Face':
        from .face_sdf import configure
        configure(library,assets,graph)
    for key, value in {'Use Shadow Ramp': 0, 'Use Lightmap AO': 0, 'Use Vertex Color AO': 0, 'Use Normal Map': 0,
                       'Enable Metallics?': 0, 'Use Specular Ramp': 0, 'Specular Multiplier': 0, 'Use Alpha': 0,
                       'Shadow Transition Range': SHADOW_TRANSITION}.items():
        socket = body.inputs.get(key)
        if socket is not None:
            socket.default_value = value
    # PMX Toon already supplies its ramp color. Keep the template shadow near
    # neutral so the two stages do not multiply into a strong gray shadow.
    for socket in body.inputs:
        if socket.name.startswith(('Daytime Shadow Color', 'Nighttime Shadow Color')):
            socket.default_value = (*DEFAULT_SHADOW_COLOR, 1)
        elif socket.name.startswith('Use Material '):
            socket.default_value = 0
    color = diffuse.outputs['Color'] if diffuse else (1, 1, 1, 1)
    if assets.role in {'eye', 'brow', 'expression'}:
        result = color
    else:
        if diffuse:
            graph.link(color, body.inputs['Diffuse Color'])
        else:
            body.inputs['Diffuse Color'].default_value = color
        result = graph.source_rgb()
        if 'toon' in assets.textures:
            toon = graph.texture('toon', data=False, vector=graph.combine(.5, body.outputs['Lit Factor']))
            toon.extension = 'EXTEND'
            result = graph.multiply(result, toon.outputs['Color'])
            result.node['hgt_pmx_semantic'] = 'toon'
    result = graph.multiply(result, (*material_color(assets.pmx), 1))
    result.node['hgt_pmx_semantic'] = 'material_color'
    if 'sphere' in assets.textures and assets.pmx['sphere_mode'] != '0':
        coordinates = graph.uv(1) if assets.pmx['sphere_mode'] == '3' else graph.matcap_uv()
        sphere = graph.texture('sphere', data=False, vector=coordinates)
        sphere.extension = 'EXTEND'
        result = graph.mix(1, result, sphere.outputs['Color'], 'ADD' if assets.pmx['sphere_mode'] == '2' else 'MULTIPLY')
        result.node['hgt_pmx_semantic'] = 'sphere'
    opacity = graph.math('MULTIPLY', diffuse.outputs['Alpha'], assets.pmx['alpha']) if diffuse else assets.pmx['alpha']
    if assets.pmx['overlay']:
        gray = graph.node('ShaderNodeRGBToBW', 'PMX Additive Coverage')
        graph.link(color, gray.inputs[0])
        opacity = graph.math('MULTIPLY', opacity, gray.outputs[0])
    graph.surface(result, opacity)
    # Opaque surfaces write depth; transparent overlays use alpha blending.
    # Dithered zero-alpha duplicate shells can occlude underlying PMX faces.
    transparent = (assets.pmx['alpha'] < 1 or assets.pmx['texture_alpha_min'] < 1
                   or assets.pmx['overlay'] or assets.role == 'expression')
    material.surface_render_method = 'BLENDED' if transparent else 'DITHERED'
    configure_transparency(material, assets.role, assets.pmx['overlay'])
    material.use_backface_culling = not assets.pmx['double_sided']
    import json
    material['hgt_features'] = json.dumps(assets.features, sort_keys=True)
    material['hgt_texture_matches'] = json.dumps({role: {'file': path.filepath if isinstance(path, bpy.types.Image) else str(path), 'basis': assets.evidence[role]} for role, path in assets.textures.items()}, ensure_ascii=False)
    material['hgt_pmx'] = json.dumps(assets.pmx, ensure_ascii=False)
    material['hgt_json'] = ''
    material['hgt_applied_parameters'] = ['PMX diffuse', 'PMX ambient', 'Toon', 'Sphere', 'Alpha', 'double-sided', 'edge']
    outline = library.materials['HoYoverse - Genshin Outlines'].copy()
    outline.name = material.name + ' Outlines'
    outline['hgt_owner'], outline['hgt_source'] = library.uid, assets.source
    library._private_textures(outline.node_tree, {})
    node = outline.node_tree.nodes['Outlines']
    for key, value in {'Outline Color 1': assets.pmx['edge_color'], 'Use Alpha': 1,
                       'Use Vertex Color AO': 0, 'Use Lightmap AO': 0}.items():
        if node.inputs.get(key):
            node.inputs[key].default_value = value
    for socket in node.inputs:
        if socket.name.startswith('Outline Color '):
            socket.default_value = assets.pmx['edge_color']
        elif socket.name.startswith('Use Material '):
            socket.default_value = 0
    for tree in walk(outline.node_tree):
        for image_node in tree.nodes:
            if image_node.type == 'TEX_IMAGE' and 'Diffuse' in image_node.name and diffuse:
                image_node.image = diffuse.image
    if diffuse is None:
        alpha = node.inputs['Diffuse Alpha']
        for link in tuple(alpha.links):
            outline.node_tree.links.remove(link)
        alpha.default_value = 1
    # PMX's edge alpha and material alpha also apply to a solid-color edge.
    coverage = assets.pmx['alpha'] * assets.pmx['edge_color'][3]
    if coverage < 1:
        tree = outline.node_tree
        output = next(n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output)
        original = output.inputs['Surface'].links[0].from_socket
        transparent = tree.nodes.new('ShaderNodeBsdfTransparent')
        mix = tree.nodes.new('ShaderNodeMixShader')
        mix.name = 'HGT • PMX Edge Alpha'
        mix.inputs[0].default_value = coverage
        tree.links.new(transparent.outputs[0], mix.inputs[1])
        tree.links.new(original, mix.inputs[2])
        tree.links.new(mix.outputs[0], output.inputs['Surface'])
    return material, outline
