"""Optional compositor attachment on the isolated render scene."""
import bpy


def configure(scene, root, resources):
    group = next((g for g in bpy.data.node_groups
                  if g.get("hgt_owner") == root.hgt_character.uid
                  and g.get("hgt_upstream") == "HoYoverse - Post Processing"), None)
    if group is None:
        raise ValueError("缺少后期资源，请重新导入模型")
    tree = scene.compositing_node_group
    if tree and any(n.type == "GROUP" and n.node_tree and
                    n.node_tree.get("hgt_upstream") == "HoYoverse - Post Processing" for n in tree.nodes):
        return
    if tree:
        output = next((n for n in tree.nodes if n.type == "GROUP_OUTPUT" and n.is_active_output), None)
        if output is None or output.inputs.get("Image") is None or not output.inputs["Image"].is_linked:
            raise ValueError("当前合成器没有已连接的 Image 输出")
        source = output.inputs["Image"].links[0].from_socket
    else:
        tree = bpy.data.node_groups.new("HGT • Compositing", "CompositorNodeTree")
        resources.add(tree)
        tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        render = tree.nodes.new("CompositorNodeRLayers")
        render.scene = scene
        source = render.outputs["Image"]
        output = tree.nodes.new("NodeGroupOutput")
        scene.compositing_node_group = tree
    node = tree.nodes.new("CompositorNodeGroup")
    node.node_tree = group
    node.location = (200, 0)
    tree.links.new(source, node.inputs["Image"])
    tree.links.new(node.outputs["Image"], output.inputs["Image"])
