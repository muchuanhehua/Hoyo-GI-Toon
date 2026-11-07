"""Native, stateless eye deformation on the already posed iris surface."""
import bpy

MAX_SQUEEZE = .24


class Graph:
    def __init__(self, tree):
        self.tree = tree

    def node(self, kind, **attributes):
        node = self.tree.nodes.new(kind)
        for name, value in attributes.items():
            setattr(node, name, value)
        return node

    def link(self, value, socket):
        if isinstance(value, bpy.types.NodeSocket):
            self.tree.links.new(value, socket)
        else:
            socket.default_value = value

    def math(self, operation, a, b=0):
        node = self.node('ShaderNodeMath', operation=operation)
        self.link(a, node.inputs[0])
        self.link(b, node.inputs[1])
        return node.outputs[0]

    def vector(self, operation, a, b=None, scale=None):
        node = self.node('ShaderNodeVectorMath', operation=operation)
        self.link(a, node.inputs[0])
        if b is not None:
            self.link(b, node.inputs[1])
        if scale is not None:
            self.link(scale, node.inputs['Scale'])
        return node.outputs['Value' if operation in {'DOT_PRODUCT', 'LENGTH'} else 'Vector']

    def sample(self, geometry, position, index):
        node = self.node('GeometryNodeSampleIndex', data_type='FLOAT_VECTOR', domain='POINT')
        self.link(geometry, node.inputs['Geometry'])
        self.link(position, node.inputs['Value'])
        self.link(index, node.inputs['Index'])
        return node.outputs['Value']

    def surface(self, geometry, position, target):
        node = self.node('GeometryNodeSampleNearestSurface', data_type='FLOAT_VECTOR')
        self.link(geometry, node.inputs['Mesh'])
        self.link(position, node.inputs['Value'])
        self.link(target, node.inputs['Sample Position'])
        return node.outputs['Value']


def build(tree, helper, eyes, count):
    """No simulation cache or Python frame handler: scrubbing and renders agree."""
    for name, direction, kind in (('Geometry', 'INPUT', 'NodeSocketGeometry'),
                                  ('Geometry', 'OUTPUT', 'NodeSocketGeometry'),
                                  ('Amount', 'INPUT', 'NodeSocketFloat'),
                                  ('Speed', 'INPUT', 'NodeSocketFloat'),
                                  ('Spring', 'INPUT', 'NodeSocketFloat')):
        tree.interface.new_socket(name=name, in_out=direction, socket_type=kind)
    g = Graph(tree)
    inputs = g.node('NodeGroupInput').outputs
    output = g.node('NodeGroupOutput')
    position = g.node('GeometryNodeInputPosition').outputs[0]
    index = g.node('GeometryNodeInputIndex').outputs[0]
    info = g.node('GeometryNodeObjectInfo', transform_space='ORIGINAL')
    info.inputs['Object'].default_value = helper
    geometry = inputs['Geometry']
    names = []
    for attribute in ('region', 'core'):
        source = g.node('GeometryNodeInputNamedAttribute', data_type='FLOAT')
        source.inputs['Name'].default_value = attribute
        sample = g.node('GeometryNodeSampleIndex', data_type='FLOAT', domain='POINT')
        for name, value in (('Geometry', info.outputs['Geometry']), ('Value', source.outputs['Attribute']), ('Index', index)):
            g.link(value, sample.inputs[name])
        # Capture in POINT domain before using these fields on FACE selections.
        name = tree.name + '/' + attribute
        store = g.node('GeometryNodeStoreNamedAttribute', data_type='FLOAT', domain='POINT')
        for socket, value in (('Geometry', geometry), ('Name', name), ('Value', sample.outputs['Value'])):
            g.link(value, store.inputs[socket])
        geometry = store.outputs['Geometry']
        field = g.node('GeometryNodeInputNamedAttribute', data_type='FLOAT')
        field.inputs['Name'].default_value = name
        names.append((name, field.outputs['Attribute']))
    region, core = [field for _, field in names]
    seconds = g.node('GeometryNodeInputSceneTime').outputs['Seconds']
    phase = g.math('MULTIPLY', g.math('MULTIPLY', seconds, inputs['Speed']), 6.283185307179586)
    ripple = g.math('MULTIPLY', g.math('SINE', g.math('MULTIPLY', phase, 2)),
                    g.math('MULTIPLY', inputs['Spring'], .9))
    wave = g.math('SINE', g.math('ADD', phase, ripple))
    amount = g.math('MINIMUM', g.math('MAXIMUM', inputs['Amount'], 0), 1)
    amplitude = g.math('MULTIPLY', amount, MAX_SQUEEZE * .5)
    squeeze_x = g.math('MULTIPLY', amplitude, g.math('ADD', 1, wave))
    squeeze_y = g.math('MULTIPLY', amplitude, g.math('SUBTRACT', 1, wave))
    offset = (0, 0, 0)
    for side, anchors in eyes.items():
        selected = g.math('COMPARE', region, side)
        body = g.math('MULTIPLY', selected, core)
        stats = g.node('GeometryNodeAttributeStatistic', data_type='FLOAT_VECTOR', domain='POINT')
        for name, value in (('Geometry', geometry), ('Selection', body), ('Attribute', position)):
            g.link(value, stats.inputs[name])
        center = stats.outputs['Mean']
        a, b, c = [g.sample(geometry, position, i) for i in anchors]
        horizontal = g.vector('NORMALIZE', g.vector('SUBTRACT', b, a))
        cross = g.vector('CROSS_PRODUCT', horizontal, g.vector('SUBTRACT', c, a))
        normal = g.vector('NORMALIZE', cross)
        vertical = g.vector('NORMALIZE', g.vector('CROSS_PRODUCT', normal, horizontal))
        delta = g.vector('SUBTRACT', position, center)
        dx = g.vector('SCALE', horizontal, scale=g.math('MULTIPLY', g.vector('DOT_PRODUCT', delta, horizontal), squeeze_x))
        dy = g.vector('SCALE', vertical, scale=g.math('MULTIPLY', g.vector('DOT_PRODUCT', delta, vertical), squeeze_y))
        target = g.vector('SUBTRACT', position, g.vector('ADD', dx, dy))
        iris = g.node('GeometryNodeSeparateGeometry', domain='FACE')
        g.link(geometry, iris.inputs['Geometry'])
        g.link(body, iris.inputs['Selection'])
        # Project back to the ORIGINAL current iris, retaining each highlight's
        # existing surface offset. Neither iris nor highlights can float forward.
        moved = g.surface(iris.outputs['Selection'], position, target)
        original = g.surface(iris.outputs['Selection'], position, position)
        valid = g.math('GREATER_THAN', g.vector('LENGTH', cross), 1e-7)
        part = g.vector('SCALE', g.vector('SUBTRACT', moved, original),
                        scale=g.math('MULTIPLY', selected, valid))
        offset = g.vector('ADD', offset, part)
    set_position = g.node('GeometryNodeSetPosition')
    g.link(geometry, set_position.inputs['Geometry'])
    # Pass a real index mask to field evaluation: surface queries on the whole
    # character would needlessly scale with clothing/hair vertex counts.
    g.link(g.math('GREATER_THAN', region, 0), set_position.inputs['Selection'])
    g.link(offset, set_position.inputs['Offset'])
    geometry = set_position.outputs['Geometry']
    for name, _ in names:
        remove = g.node('GeometryNodeRemoveAttribute')
        g.link(geometry, remove.inputs['Geometry'])
        remove.inputs['Name'].default_value = name
        geometry = remove.outputs['Geometry']
    size = g.node('GeometryNodeAttributeDomainSize', component='MESH')
    g.link(inputs['Geometry'], size.inputs['Geometry'])
    unchanged = g.math('COMPARE', size.outputs['Point Count'], count)
    enabled = g.math('MULTIPLY', unchanged, g.math('GREATER_THAN', inputs['Amount'], 0))
    switch = g.node('GeometryNodeSwitch', input_type='GEOMETRY')
    for name, value in (('Switch', enabled), ('False', inputs['Geometry']), ('True', geometry)):
        g.link(value, switch.inputs[name])
    g.link(switch.outputs[0], output.inputs['Geometry'])


def add_drivers(obj, modifier, root):
    for socket in modifier.node_group.interface.items_tree:
        if socket.item_type != 'SOCKET' or socket.in_out != 'INPUT' or socket.name == 'Geometry':
            continue
        field = {'Amount': 'amount', 'Speed': 'speed', 'Spring': 'spring'}[socket.name]
        value = getattr(modifier.properties.inputs, socket.identifier)
        value.value = getattr(root.hgt_jelly, field)
        driver = value.driver_add('value').driver
        driver.type = 'SUM'
        variable = driver.variables.new()
        variable.name = field
        variable.targets[0].id = root
        variable.targets[0].data_path = 'hgt_jelly.' + field


def remove_drivers(obj, modifier):
    for socket in modifier.node_group.interface.items_tree:
        if socket.item_type == 'SOCKET' and socket.in_out == 'INPUT' and socket.name != 'Geometry':
            getattr(modifier.properties.inputs, socket.identifier).driver_remove('value')
