"""Layered iris, source color ramps and the independent clear eye surface."""
from .node_graph import Graph
from .eye_surfaces import OUTER_MASK


def _view_offset(graph, uv, scale):
    if not scale:
        return uv
    tangent = graph.node('ShaderNodeTangent', 'Eye UV Tangent')
    tangent.direction_type, tangent.uv_map = 'UV_MAP', 'UV0'
    bitangent = graph.vector('CROSS_PRODUCT', graph.geometry('Normal'), tangent.outputs[0])
    denominator = graph.math('MAXIMUM', graph.vector('DOT_PRODUCT', graph.view, graph.geometry('Normal')), .2)
    x = graph.math('DIVIDE', graph.vector('DOT_PRODUCT', graph.view, tangent.outputs[0]), denominator)
    y = graph.math('DIVIDE', graph.vector('DOT_PRODUCT', graph.view, bitangent), denominator)
    return graph.vector('ADD', uv, graph.vector('SCALE', graph.combine(x, y), scale=scale))


def _layer(graph, index, uv):
    assets, f = graph.assets, graph.assets.floats
    prefix = f'_ParallaxLayer{index}'
    rotation = assets.color(prefix + 'UVRotation', (.5, .5, 0, 1))
    x, y, _ = graph.split(graph.vector('SUBTRACT', uv, (*rotation[:2], 0)))
    rotated = graph.combine(graph.math('SUBTRACT', graph.math('MULTIPLY', x, rotation[3]), graph.math('MULTIPLY', y, rotation[2])),
                            graph.math('ADD', graph.math('MULTIPLY', x, rotation[2]), graph.math('MULTIPLY', y, rotation[3])))
    uv = graph.vector('ADD', rotated, (*rotation[:2], 0))
    scroll = assets.color(prefix + 'UVScrollAndScale', (0, 0, 1, 1))
    uv = graph.vector('ADD', graph.vector('MULTIPLY', uv, (scroll[2], scroll[3], 1)), (scroll[0], scroll[1], 0))
    uv = _view_offset(graph, uv, f.get('_ParallaxScale', 0) * f.get(prefix + 'ParallaxScale', 0))
    texture = graph.texture(f'eye_layer_{index}', data=False, vector=uv)
    color = graph.multiply(texture.outputs['Color'], assets.color(prefix + 'Tint', (1, 1, 1, 1)))
    color = graph.multiply(color, f.get(prefix + 'Intensity', 1))
    if f.get(prefix + 'UseRamp', 0):
        params = assets.color(prefix + 'RampParams', (1, 0, 0, 0))
        coordinate = graph.vector('DOT_PRODUCT', graph.vector('SUBTRACT', uv, (.5, .5, 0)), (*params[:2], 0))
        coordinate = graph.clamp(graph.math('ADD', coordinate, .5))
        # Four packed two-pixel rows, ordered from the top of the source image.
        ramp = graph.texture('eye_layer_ramp', data=False, vector=graph.combine(coordinate, 1 - (index - .5) / 4))
        operation = 'MULTIPLY' if f.get(prefix + 'RampBlendMode', 0) == 1 else 'ADD'
        color = graph.mix(f.get(prefix + 'RampStrength', 1), color, ramp.outputs['Color'], operation)
    return color, texture.outputs['Alpha']


def apply(material, assets, load_image, owner):
    if not assets.features['layered_eye']:
        return
    graph = Graph(material, assets, owner, load_image)
    f, uv = assets.floats, graph.uv()
    color = graph.texture('diffuse', data=False).outputs['Color']
    layers = []
    for index in (1, 2, 3):
        if not f.get(f'_ParallaxLayer{index}', 0):
            continue
        layer, alpha = _layer(graph, index, uv)
        color = graph.mix(alpha, color, layer)
        layers.append(f'eye_layer_{index}')
    material['hgt_eye_layers'] = layers
    lit = graph.body.outputs['Lit Factor']
    shadow = graph.clamp(graph.math('MULTIPLY', graph.math('SUBTRACT', 1, lit), f.get('_EyeInShadowTintLightDirIntensity', 1)))
    tint = graph.mix(shadow, (1, 1, 1, 1), assets.color('_EyeInShadowTintColor', (1, 1, 1, 1)))
    color = graph.multiply(color, tint)
    center = assets.color('_EyeDiscCenter', (.5, .5, 0, 0))
    distance = graph.vector('DISTANCE', uv, center[:3])
    radius, feather = f.get('_EyeDiscRadius', .5), max(f.get('_EyeDiscFeather', .01), .0001)
    disc = graph.math('SUBTRACT', 1, graph.smooth(radius, radius + feather, distance))
    if 'eye_normal' in assets.textures:
        packed = graph.texture('eye_normal')
        red, green, blue, alpha = graph.channels(packed)
        normal = graph.node('ShaderNodeNormalMap', 'Eye Packed Normal')
        normal.uv_map = 'UV0'
        graph.link(graph.combine(red, green, 1), normal.inputs['Color'])
        spherical = graph.mix(f.get('_EyeMatcapSphericalNormalLerp', 0), normal.outputs['Normal'], graph.geometry('Normal'))
        graph.normal_override = graph.vector('NORMALIZE', spherical)
        intensity = graph.math('MULTIPLY', graph.math('MULTIPLY', blue, alpha), f.get('_BaseMatcapIntensity', 0))
        color = graph.add(color, graph.multiply(assets.color('_BaseMatcapTint', (1, 1, 1, 1)), graph.math('MULTIPLY', intensity, disc)))
    reflection_uv = graph.matcap_uv()
    invert = assets.color('_EyeMatcapInvertUV', (0, 0, 0, 0))
    coords = graph.split(reflection_uv)
    reflection_uv = graph.combine(*(graph.math('SUBTRACT', 1, value) if invert[i] else value for i, value in enumerate(coords[:2])))
    if 'eye_matcap' in assets.textures:
        mask = graph.texture('eye_matcap', data=True, vector=reflection_uv)
        value = graph.split(mask.outputs['Color'])[0]
        if f.get('_EyeMatcapUseBinary', 0):
            threshold = f.get('_EyeMatcapBinaryThreshold', .5)
            value = graph.smooth(threshold, threshold + max(f.get('_EyeMatcapBinarySmoothness', .01), .0001), value)
        reflection = graph.multiply(assets.color('_EyeMatcapTint', (1, 1, 1, 1)), graph.math('MULTIPLY', value, f.get('_EyeMatcapIntensity', 0)))
        color = graph.add(color, reflection)
    iris = graph.node('ShaderNodeEmission', 'Layered Iris')
    graph.link(color, iris.inputs['Color'])
    # SDF is laid out in the original pupil UV; it is not a spherical Matcap.
    field = graph.texture('eye_highlight', data=True)
    sdf = graph.split(field.outputs['Color'])[0]
    if f.get('_InvertSDFMap', 0):
        sdf = graph.math('SUBTRACT', 1, sdf)
    cutoff, pixel = f.get('_SDFCenterValue', .5), 1 / max(field.image.size)
    coverage = graph.math('MULTIPLY', disc, graph.smooth(cutoff - pixel, cutoff + pixel, sdf))
    high_color = assets.color('_HighlightColor', (1, 1, 1, 1))
    if f.get('_UseHighlightRamp', 0):
        ramp = graph.texture('eye_ramp', data=False, vector=graph.combine(sdf, .5))
        high_color = graph.multiply(ramp.outputs['Color'], high_color)
    high = graph.node('ShaderNodeEmission', 'Eye Reflection')
    graph.link(high_color, high.inputs['Color'])
    transparent = graph.node('ShaderNodeBsdfTransparent', 'Clear Eye Surface')
    blend = graph.node('ShaderNodeMixShader', 'SDF Highlight Coverage')
    for value, socket in zip((coverage, transparent.outputs[0], high.outputs[0]), blend.inputs):
        graph.link(value, socket)
    marker = graph.node('ShaderNodeAttribute', 'Eye Surface')
    marker.attribute_name = OUTER_MASK
    surface = graph.node('ShaderNodeMixShader', 'Inner and Outer Eye')
    for value, socket in zip((marker.outputs['Fac'], iris.outputs[0], blend.outputs[0]), surface.inputs):
        graph.link(value, socket)
    output = next(n for n in graph.tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output)
    graph.link(surface.outputs[0], output.inputs['Surface'])
    material.surface_render_method = 'BLENDED'
    material['hgt_eye_surface_mask'] = OUTER_MASK
