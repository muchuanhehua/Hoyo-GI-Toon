"""Source-masked stockings, directional silk and packed/procedural glints."""
import math


def _channel(graph, texture, index):
    return graph.channels(texture)[max(0, min(3, int(index)))]


def _material_mask(graph):
    assets = graph.assets
    if assets.features['normal_material_ids'] and 'normal' in assets.textures:
        # Modern normal maps carry an independent fabric ID in B, not normal Z.
        return graph.smooth(.75, .85, _channel(graph, graph.texture('normal'), 2))
    alpha = graph.texture('lightmap').outputs['Alpha']
    return graph.math('MULTIPLY', graph.math('GREATER_THAN', alpha, .2), graph.math('LESS_THAN', alpha, .4))


def _ndot(graph, direction):
    return graph.clamp(graph.vector('DOT_PRODUCT', graph.normal, direction))


def _light(graph):
    node = graph.node('ShaderNodeAttribute', 'Material Light Direction')
    node.attribute_name = 'lightDir'
    return graph.vector('NORMALIZE', node.outputs['Vector'])


def stockings(graph, color):
    assets, f = graph.assets, graph.assets.floats
    mask = _material_mask(graph)
    # Translate the source's Y-up view shift to Blender's Z-up coordinates.
    view = graph.vector('NORMALIZE', graph.vector('ADD', graph.view, (0, 0, f.get('_StockingsSpecularShift', 0))))
    ndv = _ndot(graph, view)
    shadow = graph.math('SUBTRACT', 1, graph.math('POWER', ndv, max(.001, f.get('_StockingsShadowRange', 1))))
    light = graph.math('POWER', ndv, max(.001, f.get('_StockingsLightRange', 1)))
    shadow_color = assets.color('_StockingsShadowColor', (1, 1, 1, 1))
    shaded = graph.mix(shadow, color, graph.multiply(color, shadow_color))
    bright = graph.multiply(color, assets.color('_StockingsLightColor', (1, 1, 1, 1)))
    bright = graph.multiply(bright, f.get('_StockingsLightScale', 1))
    shaded = graph.mix(light, shaded, bright)
    half = graph.vector('NORMALIZE', graph.vector('ADD', view, _light(graph)))
    ndh = _ndot(graph, half)
    for detail, default_range, default_scale in (('', 32, .1), ('Detail', 64, 0)):
        power = graph.math('POWER', ndh, max(.001, f.get('_StockingsSpecular' + detail + 'Range', default_range)))
        spec = graph.smooth(.5, max(.501, f.get('_StockingsSpecular' + detail + 'Sharpe', .8)), power)
        spec = graph.math('MULTIPLY', spec, f.get('_StockingsSpecular' + detail + 'Scale', default_scale))
        shaded = graph.add(shaded, graph.multiply(assets.color('_StockingsSpecular' + detail + 'Color', (1, 1, 1, 1)), spec))
    if 'stocking_detail' in assets.textures:
        uv = graph.vector('SCALE', graph.uv(), scale=f.get('_StockingsDetailPattenTiling', 1))
        detail = graph.texture('stocking_detail', vector=uv)
        blue = _channel(graph, detail, 2)
        pattern = graph.mix(f.get('_StockingsDetailPattenScale', 0), (1, 1, 1, 1), blue)
        shaded = graph.multiply(shaded, graph.mix(pattern, assets.color('_StockingsDetailPattenColor', (1, 1, 1, 1)), (1, 1, 1, 1)))
    if f.get('_UseGradientStocking', 0):
        gradient = graph.mix(ndv, assets.color('_StockingsGradientDarkColor', (1, 1, 1, 1)), assets.color('_StockingsGradientLightColor', (1, 1, 1, 1)))
        shaded = graph.mix(f.get('_StockingsGradientStrength', 0), shaded, graph.multiply(shaded, gradient))
    return graph.mix(mask, color, shaded)


def silk(graph, color):
    assets, f = graph.assets, graph.assets.floats
    tangent = graph.node('ShaderNodeTangent', 'Silk Thread Tangent')
    tangent.direction_type, tangent.uv_map = 'UV_MAP', 'UV0'
    half = graph.vector('NORMALIZE', graph.vector('ADD', graph.view, _light(graph)))
    dot = graph.vector('DOT_PRODUCT', tangent.outputs[0], half)
    anisotropy = abs(f.get('_AnisoSilkAnisotropy', .5))
    lobe = graph.math('POWER', graph.clamp(graph.math('SUBTRACT', 1, graph.math('MULTIPLY', dot, dot))), 8 + anisotropy * 120)
    # Silk and stockings have different source masks, even when both features
    # are enabled on the same material. Do not intersect their unrelated IDs.
    mask = graph.texture('lightmap').outputs['Alpha']
    if 'silk_detail' in assets.textures:
        detail = graph.texture('silk_detail', vector=graph.uv(int(f.get('_AnisoSilkThreadUVSelect', 0))))
        if f.get('_AnisoSilkUseThreadMapMask', 0):
            mask = _channel(graph, detail, f.get('_AnisoSilkMaskChannel', 3))
        lobe = graph.math('MULTIPLY', lobe, graph.mix(f.get('_AnisoSilkThreadNoiseStrength', 0), (1, 1, 1, 1), detail.outputs['Color']))
    intensity = f.get('_AnisoSilkSpecularIntensity', 1) * f.get('_AnisoSilkSpecularFinalIntensity', 1)
    highlight = graph.math('MULTIPLY', graph.math('MULTIPLY', mask, lobe), intensity)
    tint = assets.color('_AnisoSilkFresnelEdgeColor', (1, 1, 1, 1))
    return graph.add(color, graph.multiply(tint, highlight))


def _glint_layer(graph, color, suffix, mask, index=None):
    assets, f = graph.assets, graph.assets.floats
    region_suffix = f'_ID{index}' if index else suffix
    uv_index = int(f.get('_ShiningUVSwitch' + region_suffix, 0))
    if uv_index < 2:
        uv = graph.uv(uv_index)
    else:
        # Spatial mode is independent of unused expression UV channels.
        position = graph.node('ShaderNodeTexCoord', 'Glint Object Position').outputs['Object']
        x, y, z = graph.split(position)
        uv = graph.combine(x, y)
    tiling = f.get('_ShiningTiling' + region_suffix, f.get('_ShiningTiling' + suffix, 40))
    tiled = graph.vector('SCALE', uv, scale=tiling)
    cell = graph.vector('FLOOR', tiled)
    noise = graph.node('ShaderNodeTexWhiteNoise', 'Glint Cell Seed')
    noise.noise_dimensions = '3D'
    graph.link(cell, noise.inputs['Vector'])
    jitter_x, jitter_y, _ = graph.split(noise.outputs['Color'])
    point = graph.vector('SUBTRACT', graph.vector('FRACTION', tiled), graph.combine(jitter_x, jitter_y))
    rotation = graph.node('ShaderNodeVectorRotate', 'Source Glint Rotation')
    rotation.rotation_type = 'AXIS_ANGLE'
    rotation.inputs['Axis'].default_value = (0, 0, 1)
    graph.link(point, rotation.inputs['Vector'])
    angle = graph.math('ADD', math.radians(f.get('_ShiningRotation' + region_suffix, 0)),
                       graph.math('MULTIPLY', noise.outputs['Value'], math.tau * f.get('_ShiningRandomRotation' + region_suffix, 0)))
    graph.link(angle, rotation.inputs['Angle'])
    point = rotation.outputs['Vector']
    size = max(.0001, f.get('_ShiningSize' + suffix, .02))
    density = f.get('_ShiningDensity' + suffix, 1)
    present = graph.math('LESS_THAN', noise.outputs['Value'], density)
    if suffix == '_V2' and f.get('_UseShiningCustomShape_V2', 0) and 'shining_shape' in assets.textures:
        low = f.get('_ShiningRandomSizeMin' + region_suffix, 1)
        span = f.get('_ShiningRandomSizeMax' + region_suffix, low) - low
        scale = graph.math('ADD', low, graph.math('MULTIPLY', noise.outputs['Value'], span)) if f.get('_ShiningRandomSize' + region_suffix, 0) else 1
        denominator = graph.math('MAXIMUM', graph.math('MULTIPLY', size, scale), .001)
        coordinate = graph.vector('ADD', graph.vector('SCALE', point, scale=graph.math('DIVIDE', 1, denominator)), (.5, .5, 0))
        x, y, _ = graph.split(coordinate)
        inside = graph.math('MULTIPLY', graph.math('MULTIPLY', graph.math('GREATER_THAN', x, 0), graph.math('LESS_THAN', x, 1)),
                            graph.math('MULTIPLY', graph.math('GREATER_THAN', y, 0), graph.math('LESS_THAN', y, 1)))
        rect = assets.color('_ShiningCustomIDTextureRectSizeOffset' + region_suffix, (1, 1, 0, 0))
        coordinate = graph.vector('ADD', graph.vector('MULTIPLY', coordinate, (*rect[:2], 1)), (*rect[2:], 0))
        shape = graph.texture('shining_shape', vector=coordinate)
        shape.extension = 'CLIP'
        channel = f.get('_ShiningCustomMaskChannel' + (f'_ID{index}' if index else '_V2'), 2)
        spot = graph.math('MULTIPLY', inside, _channel(graph, shape, channel))
    else:
        radius = math.sqrt(size) * .5
        distance = graph.vector('LENGTH', point)
        spot = graph.math('SUBTRACT', 1, graph.smooth(radius * .5, radius, distance))
    visible = graph.math('MULTIPLY', graph.math('MULTIPLY', spot, present), mask)
    intensity = f.get('_ShiningIntensity' + suffix, 1)
    tint = assets.color('_ShiningColor' + suffix, (1, 1, 1, 1))
    return graph.add(color, graph.multiply(tint, graph.math('MULTIPLY', visible, intensity)))


def shining(graph, color):
    assets, f = graph.assets, graph.assets.floats
    modern = bool(f.get('_UseCharacterShining_V2', 0))
    suffix = '_V2' if modern else ''
    custom = modern and f.get('_UseShiningCustomShape_V2', 0) and 'normal' in assets.textures and assets.features['normal_material_ids']
    mask = 1 if custom else _material_mask(graph)
    if modern and f.get('_UseShiningVColorMask_V2', 0):
        vertex = graph.node('ShaderNodeVertexColor', 'Source Glint Mask')
        vertex.layer_name = 'Col'
        channels = (*graph.split(vertex.outputs['Color']), vertex.outputs['Alpha'])
        mask = graph.math('MULTIPLY', mask, channels[int(f.get('_ShiningVColorMaskChannel_V2', 3))])
    if custom:
        ids = _channel(graph, graph.texture('normal'), 2)
        for index, (low, high) in enumerate(((-.001, .2), (.2, .4), (.4, .8), (.8, 1.01)), 1):
            region = graph.math('MULTIPLY', graph.math('GREATER_THAN', ids, low), graph.math('LESS_THAN', ids, high))
            color = _glint_layer(graph, color, suffix, graph.math('MULTIPLY', region, mask), index)
        return color
    return _glint_layer(graph, color, suffix, mask)


def apply(graph):
    active = [key for key in ('stockings', 'silk', 'shining') if graph.assets.features[key]]
    if not active or graph.assets.features['layered_eye']:
        return
    color = graph.source_rgb()
    modules = {'stockings': stockings, 'silk': silk, 'shining': shining}
    for key in active:
        generated = modules[key](graph, color)
        color = graph.mix(1, color, generated)
        color.node['hgt_material_module'] = key
    graph.finish(color)
    graph.material['hgt_textiles'] = active
