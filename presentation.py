"""Small lighting choices and output-only background and floor resources."""
import bpy
from . import framing, lighting

LIGHTS = {'SOFT': ('柔光', .35, .35), 'SIDE': ('侧光', -1.0, .35), 'RIM': ('逆光', 2.6, .55)}
SIZES = {'PORTRAIT': ('竖图', 1024, 1536), 'SQUARE': ('方图', 1024, 1024), 'LANDSCAPE': ('横图', 1920, 1080)}


def background(job):
    scene = job.proxy
    if scene.hgt_output.transparent:
        return
    scene.render.film_transparent = True
    scene.render.use_compositing = True
    tree = scene.compositing_node_group
    if tree is None:
        tree = bpy.data.node_groups.new('HGT • Background', 'CompositorNodeTree')
        job.resources.add(tree)
        tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        output = tree.nodes.new('NodeGroupOutput')
        layers = tree.nodes.new('CompositorNodeRLayers');layers.scene = scene
        source = layers.outputs['Image']
        scene.compositing_node_group = tree
    else:
        output = next(n for n in tree.nodes if n.type == 'GROUP_OUTPUT' and n.is_active_output)
        source = output.inputs['Image'].links[0].from_socket
    color = tree.nodes.new('CompositorNodeRGB')
    color.outputs[0].default_value = (*scene.hgt_output.background_color, 1)
    over = tree.nodes.new('CompositorNodeAlphaOver')
    over.inputs['Factor'].default_value = 1
    tree.links.new(color.outputs[0], over.inputs['Background'])
    tree.links.new(source, over.inputs['Foreground'])
    tree.links.new(over.outputs[0], output.inputs['Image'])


def floor(job, root, collection):
    if not root.hgt_character.show_floor:
        return
    low, high = framing.bounds(root)
    size = (high.z - low.z) * 5
    x, y, z = (low.x + high.x) * .5, (low.y + high.y) * .5, low.z - size * .0002
    mesh = bpy.data.meshes.new('HGT • Floor')
    mesh.from_pydata([(x - size, y - size, z), (x + size, y - size, z),
                      (x + size, y + size, z), (x - size, y + size, z)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new(mesh.name, mesh);collection.objects.link(obj)
    material = bpy.data.materials.new('HGT • Floor');material.use_nodes = True
    material.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (.22, .24, .28, 1)
    material.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = .85
    mesh.materials.append(material)
    receivers = bpy.data.collections.new('HGT • Floor Receiver');receivers.objects.link(obj)
    data = bpy.data.lights.new('HGT • Floor Light', 'SUN');data.energy = 2;data.angle = .12
    light = bpy.data.objects.new(data.name, data);collection.objects.link(light)
    light.rotation_euler = (-lighting.light_direction(root.hgt_character)).to_track_quat('-Z', 'Y').to_euler()
    light.light_linking.receiver_collection = receivers
    job.resources.update({mesh, obj, material, receivers, data, light})
