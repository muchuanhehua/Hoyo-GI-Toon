"""Masked native Matcap and facet response for source crystal materials."""


def apply(graph):
    assets, f = graph.assets, graph.assets.floats
    if not assets.features['crystal'] or assets.features['layered_eye']:
        return
    color = graph.source_rgb()
    channel = max(0, min(3, int(f.get('_CrystalMaskCH', 0))))
    mask = graph.channels(graph.texture('lightmap'))[channel]
    normal = graph.normal
    if 'facet_normal' in assets.textures:
        texture = graph.texture('facet_normal')
        node = graph.node('ShaderNodeNormalMap', 'Source Facet Normal')
        node.uv_map = 'UV0'
        graph.link(texture.outputs['Color'], node.inputs['Color'])
        normal = node.outputs['Normal']
    uv = graph.matcap_uv(normal)
    uv = graph.vector('ADD', graph.vector('SCALE', graph.vector('SUBTRACT', uv, (.5, .5, 0)), scale=f.get('_MatCapSize', 1)), (.5, .5, 0))
    matcap = graph.texture('matcap', data=False, vector=uv)
    # Reflection carries the original surface color; additive white Matcap
    # would erase the colored facets already present in the source diffuse.
    reflected_color = graph.multiply(matcap.outputs['Color'], color)
    reflection = graph.multiply(reflected_color, f.get('_MatCapIntensity', 1))
    if f.get('_EnableFresnel', 0):
        ndv = graph.clamp(graph.vector('DOT_PRODUCT', graph.normal, graph.view))
        edge = graph.math('POWER', graph.math('SUBTRACT', 1, ndv), max(.001, f.get('_FresnelPower', 5)))
        edge = graph.math('MULTIPLY', edge, f.get('_FresnelScale', 1))
        reflection = graph.add(reflection, graph.multiply(assets.color('_FresnelColor', (1, 1, 1, 1)), edge))
    if f.get('_EnableFakeDiamondInternalLight', 0):
        reflection = graph.add(reflection, graph.multiply(reflected_color, f.get('_CubeMapBrightness', 1) * f.get('_MatCapIntensity', 1)))
    graph.finish(graph.mix(mask, color, graph.add(color, reflection)))
    graph.material['hgt_reflection_mask'] = 'lightmap.' + 'RGBA'[channel]
