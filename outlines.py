"""An owned, deforming inverted hull without changing the source mesh."""
import bpy


def build(mesh, root):
    settings = root.hgt_character
    owned = next((m for m in mesh.modifiers if m.type == "NODES" and m.node_group
                  and m.node_group.get("hgt_owner") == settings.uid), None)
    if owned:
        return owned
    if all(m and m.get("hgt_role") in {"face", "brow", "eye", "effect"} for m in mesh.data.materials):
        return None
    material = next((m for m in bpy.data.materials if m.get("hgt_outline") == settings.uid), None)
    if material is None:
        material = bpy.data.materials.new(f"HGT • {root.name} • 描边")
        material["hgt_outline"] = settings.uid
        material.use_nodes = True
        material.node_tree.nodes.clear()
        emission = material.node_tree.nodes.new("ShaderNodeEmission")
        emission.inputs[0].default_value = (0.025, 0.018, 0.028, 1)
        output = material.node_tree.nodes.new("ShaderNodeOutputMaterial")
        material.node_tree.links.new(emission.outputs[0], output.inputs[0])
        material.use_backface_culling = True
    tree = bpy.data.node_groups.new(f"HGT • {mesh.name} • 描边", "GeometryNodeTree")
    tree["hgt_owner"] = settings.uid
    tree.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = tree.nodes, tree.links
    original = nodes.new("NodeGroupInput")
    result = nodes.new("NodeGroupOutput")
    position = nodes.new("GeometryNodeSetPosition")
    normal = nodes.new("GeometryNodeInputNormal")
    scale = nodes.new("ShaderNodeVectorMath")
    scale.operation = "SCALE"
    scale["hgt_control"] = "outline_width"
    inverse_normal = nodes.new("ShaderNodeVectorMath")
    inverse_normal.operation = "DIVIDE"
    inverse_normal["hgt_control"] = "outline_scale"
    inverse_normal.inputs[1].default_value = (1, 1, 1)
    links.new(normal.outputs[0], inverse_normal.inputs[0])
    normalized = nodes.new("ShaderNodeVectorMath")
    normalized.operation = "NORMALIZE"
    links.new(inverse_normal.outputs[0], normalized.inputs[0])
    inverse_offset = nodes.new("ShaderNodeVectorMath")
    inverse_offset.operation = "DIVIDE"
    inverse_offset["hgt_control"] = "outline_scale"
    inverse_offset.inputs[1].default_value = (1, 1, 1)
    links.new(normalized.outputs[0], inverse_offset.inputs[0])
    links.new(inverse_offset.outputs[0], scale.inputs[0])
    links.new(scale.outputs[0], position.inputs["Offset"])
    links.new(original.outputs[0], position.inputs["Geometry"])
    flip = nodes.new("GeometryNodeFlipFaces")
    links.new(position.outputs[0], flip.inputs[0])
    set_material = nodes.new("GeometryNodeSetMaterial")
    links.new(flip.outputs[0], set_material.inputs["Geometry"])
    set_material.inputs["Material"].default_value = material
    joined = nodes.new("GeometryNodeJoinGeometry")
    links.new(original.outputs[0], joined.inputs[0])
    links.new(set_material.outputs[0], joined.inputs[0])
    links.new(joined.outputs[0], result.inputs[0])
    for i, node in enumerate(nodes):
        node.location = (i * 190, 0)
    modifier = mesh.modifiers.new("HGT 描边", "NODES")
    modifier.node_group = tree
    return modifier


def update(mesh, root):
    settings = root.hgt_character
    value = settings.height * 0.0007 * settings.outline
    for modifier in mesh.modifiers:
        if modifier.type != "NODES" or not modifier.node_group or modifier.node_group.get("hgt_owner") != settings.uid:
            continue
        enabled = settings.outline > 0
        if modifier.show_viewport != enabled:
            modifier.show_viewport = enabled
        if modifier.show_render != enabled:
            modifier.show_render = enabled
        # A nonuniformly scaled object needs a vector correction before the hull
        # offset is applied in local coordinates. Imported transforms are retained.
        scales = mesh.matrix_world.to_scale()
        for node in modifier.node_group.nodes:
            if node.get("hgt_control") == "outline_width":
                if abs(node.inputs[3].default_value - value) > 1e-8:
                    node.inputs[3].default_value = value
            elif node.get("hgt_control") == "outline_scale":
                target = tuple(max(1e-6, abs(s)) for s in scales)
                if any(abs(node.inputs[1].default_value[i] - target[i]) > 1e-8 for i in range(3)):
                    node.inputs[1].default_value = target
