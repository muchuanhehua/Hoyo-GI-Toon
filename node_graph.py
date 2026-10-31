"""Small native-node operations shared by the independent material modules."""
import bpy
from .sampling import components


class Graph:
    def __init__(self, material, assets, owner, load_image):
        self.material, self.assets, self.owner, self.load_image = material, assets, owner, load_image
        self.tree = material.node_tree
        from .face_sdf import shader_node
        self.shader = shader_node(material)
        self._geometry = None
        self._textures = {}
        self.normal_override = None
        self._source_rgb = None

    def node(self, kind, name):
        node = self.tree.nodes.new(kind)
        node.name = "HGT • " + name
        return node

    def link(self, value, socket):
        if isinstance(value, bpy.types.NodeSocket):
            self.tree.links.new(value, socket)
        else:
            if socket.type == 'RGBA' and isinstance(value, (int, float)):
                value = (value, value, value, 1)
            socket.default_value = value
        return socket

    def math(self, operation, a, b=None, c=None):
        node = self.node("ShaderNodeMath", operation)
        node.operation = operation
        for socket, value in zip(node.inputs, (a, b, c)):
            if value is not None:
                self.link(value, socket)
        return node.outputs[0]

    def vector(self, operation, a, b=None, scale=None):
        node = self.node("ShaderNodeVectorMath", operation)
        node.operation = operation
        self.link(a, node.inputs[0])
        if b is not None:
            self.link(b, node.inputs[1])
        if scale is not None:
            self.link(scale, node.inputs['Scale'])
        return node.outputs['Value'] if operation in {'DOT_PRODUCT', 'LENGTH', 'DISTANCE'} else node.outputs['Vector']

    def split(self, vector):
        node = self.node('ShaderNodeSeparateXYZ', 'Channels')
        self.link(vector, node.inputs[0])
        return tuple(node.outputs)

    def combine(self, x, y, z=0):
        node = self.node('ShaderNodeCombineXYZ', 'Vector')
        for value, socket in zip((x, y, z), node.inputs):
            self.link(value, socket)
        return node.outputs[0]

    def mix(self, factor, a, b, blend='MIX'):
        node = self.node('ShaderNodeMixRGB', blend)
        node.blend_type = blend
        for value, socket in zip((factor, a, b), node.inputs):
            self.link(value, socket)
        return node.outputs['Color']

    def multiply(self, color, factor):
        return self.mix(1, color, factor, 'MULTIPLY')

    def add(self, color, extra):
        return self.mix(1, color, extra, 'ADD')

    def clamp(self, value, low=0, high=1):
        return self.math('MINIMUM', self.math('MAXIMUM', value, low), high)

    def smooth(self, low, high, value):
        node = self.node('ShaderNodeMapRange', 'Smoothstep')
        node.interpolation_type = 'SMOOTHSTEP'
        self.link(value, node.inputs['Value'])
        self.link(low, node.inputs['From Min'])
        self.link(high, node.inputs['From Max'])
        return node.outputs['Result']

    def geometry(self, socket):
        if self._geometry is None:
            self._geometry = self.node('ShaderNodeNewGeometry', 'Geometry')
        return self._geometry.outputs[socket]

    @property
    def normal(self):
        return self.normal_override if self.normal_override is not None else self.geometry('Normal')

    @property
    def view(self):
        return self.vector('NORMALIZE', self.geometry('Incoming'))

    def uv(self, index=0):
        node = self.node('ShaderNodeUVMap', f'UV{index}')
        node.uv_map = f'UV{index}'
        return node.outputs[0]

    def texture(self, role, data=True, vector=None):
        path = self.assets.textures.get(role)
        if path is None:
            raise ValueError(f'{self.assets.source} 缺少 {role} 贴图')
        key = (role, data)
        if vector is None and key in self._textures:
            return self._textures[key]
        node = self.node('ShaderNodeTexImage', role)
        node.image = self.load_image(path, data, self.owner)
        node['hgt_texture_role'] = role
        coordinate = vector if vector is not None else self.uv()
        settings = self.assets.texture_settings.get(role, {})
        scale, offset = settings.get('m_Scale', {}), settings.get('m_Offset', {})
        xy_scale = (*components(scale, (1, 1)), 1)
        xy_offset = (*components(offset, (0, 0)), 0)
        if xy_scale != (1, 1, 1):
            coordinate = self.vector('MULTIPLY', coordinate, xy_scale)
        if xy_offset != (0, 0, 0):
            coordinate = self.vector('ADD', coordinate, xy_offset)
        self.link(coordinate, node.inputs['Vector'])
        if vector is None:
            self._textures[key] = node
        return node

    def channels(self, texture):
        return (*self.split(texture.outputs['Color']), texture.outputs['Alpha'])

    def matcap_uv(self, normal=None):
        node = self.node('ShaderNodeVectorTransform', 'Camera Normal')
        node.vector_type = 'NORMAL'
        node.convert_from, node.convert_to = 'WORLD', 'CAMERA'
        self.link(normal if normal is not None else self.normal, node.inputs[0])
        return self.vector('ADD', self.vector('SCALE', node.outputs[0], scale=.5), (.5, .5, 0))

    def source_rgb(self):
        if self._source_rgb is None:
            output = next(n for n in self.tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output)
            node = self.node('ShaderNodeShaderToRGB', 'Native Toon Color')
            self.link(output.inputs['Surface'].links[0].from_socket, node.inputs[0])
            self._source_rgb = node
        return self._source_rgb.outputs['Color']

    def surface(self, color, opacity=None):
        emission = self.node('ShaderNodeEmission', 'Surface Color')
        self.link(color, emission.inputs['Color'])
        shader = emission.outputs[0]
        if opacity is not None:
            transparent = self.node('ShaderNodeBsdfTransparent', 'Transparent Surface')
            mix = self.node('ShaderNodeMixShader', 'Surface Opacity')
            self.link(opacity, mix.inputs[0])
            self.link(transparent.outputs[0], mix.inputs[1])
            self.link(shader, mix.inputs[2])
            shader = mix.outputs[0]
        output = next(n for n in self.tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output)
        self.link(shader, output.inputs['Surface'])
