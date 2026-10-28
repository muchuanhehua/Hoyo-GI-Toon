"""Select the supported native paths when compiling the Festivity resources."""
import bpy


def bypass(tree, node, source, output):
    incoming = tuple(source.links)
    for link in tuple(output.links):
        destination = link.to_socket
        tree.links.remove(link)
        if incoming:
            tree.links.new(incoming[0].from_socket, destination)
        elif hasattr(destination, "default_value"):
            destination.default_value = source.default_value


def select_native_paths():
    body = bpy.data.node_groups["HoYoverse - GI Body"]
    face = bpy.data.node_groups["Face Factor"]
    for tree, name in ((body, "Ramps Mix -- Cast Shadows Toggle"),
                       (body, "AO Mix -- Cast Shadows Toggle"), (face, "Mix.010")):
        node = tree.nodes[name]
        source = next(s for s in node.inputs if s.identifier == "A_Float")
        output = next(s for s in node.outputs if s.identifier == "Result_Float")
        bypass(tree, node, source, output)
        tree.nodes.remove(node)
    # Keep the original color/Fresnel paths. Depth-sampled rim is a separate
    # feature and is absent from the native base-rendering resource.
    rim = bpy.data.node_groups["Depth-based Rim"]
    for tree in bpy.data.node_groups:
        for node in tuple(tree.nodes):
            if node.type != "GROUP" or node.node_tree != rim:
                continue
            bypass(tree, node, node.inputs["Color"], node.outputs["Color"])
            for link in tuple(node.outputs["Factor"].links):
                socket = link.to_socket
                tree.links.remove(link)
                socket.default_value = 0.0
            tree.nodes.remove(node)
    bpy.data.node_groups.remove(rim)
    for tree in (body, face):
        for node in tuple(tree.nodes):
            if node.bl_idname == "NodeUndefined":
                tree.nodes.remove(node)
        reachable = set()
        stack = [n for n in tree.nodes if n.type == "GROUP_OUTPUT"]
        while stack:
            node = stack.pop()
            if node in reachable:
                continue
            reachable.add(node)
            stack.extend(link.from_node for socket in node.inputs for link in socket.links)
        for node in tuple(tree.nodes):
            if node not in reachable:
                tree.nodes.remove(node)
    trees = list(bpy.data.node_groups) + [m.node_tree for m in bpy.data.materials if m.node_tree]
    assert not any(n.bl_idname == "NodeUndefined" for t in trees for n in t.nodes)
    return {"base": ["Body", "Hair", "Face", "Alpha", "Genshin Specular", "Metallic Matcap"],
            "lighting": ["Light Vectors", "Face Factor", "Fresnel"],
            "outlines": "HoYoverse - Genshin Impact Outlines"}
