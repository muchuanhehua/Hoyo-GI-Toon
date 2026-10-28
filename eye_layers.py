"""Native pupil color layers, using the reference setup's alpha composition."""


def compose(diffuse_nodes, assets, load_image, owner):
    layers = [(index, assets.textures.get(f"eye_layer_{index}")) for index in (1, 2, 3)
              if assets.floats.get(f"_ParallaxLayer{index}", 0)]
    if not layers:
        return []
    if assets.role != "eye":
        return []
    for index, path in layers:
        if path is None:
            raise ValueError(f"{assets.source} 缺少已启用的眼部第 {index} 层贴图")
        if assets.floats.get(f"_ParallaxLayer{index}BlendMode", 0) != 0:
            raise ValueError(f"{assets.source} 的眼部第 {index} 层需要明确的混合模式适配")
    # Gacha's PupilaTodo combines the base iris and detail/highlight images by
    # their packed alpha. Keep the existing native Body/Hair lighting path.
    for base in diffuse_nodes:
        tree = base.id_data
        destinations = [link.to_socket for link in base.outputs['Color'].links]
        color = base.outputs['Color']
        for index, path in layers:
            texture = tree.nodes.new("ShaderNodeTexImage")
            texture.name = f"HGT Eye Layer {index} • {base.name}"
            texture.image = load_image(path, False, owner)
            texture["hgt_texture_role"] = f"eye_layer_{index}"
            for link in base.inputs['Vector'].links:
                tree.links.new(link.from_socket, texture.inputs['Vector'])
            tint = tree.nodes.new("ShaderNodeMixRGB")
            tint.blend_type = 'MULTIPLY'
            tint.inputs[0].default_value = 1
            values = assets.color(f"_ParallaxLayer{index}Tint", (1, 1, 1, 1))
            intensity = assets.floats.get(f"_ParallaxLayer{index}Intensity", 1)
            tint.inputs[2].default_value = tuple(v * intensity for v in values[:3]) + (1,)
            tree.links.new(texture.outputs['Color'], tint.inputs[1])
            mix = tree.nodes.new("ShaderNodeMixRGB")
            mix.name = f"HGT Eye Alpha {index} • {base.name}"
            tree.links.new(texture.outputs['Alpha'], mix.inputs[0])
            tree.links.new(color, mix.inputs[1])
            tree.links.new(tint.outputs['Color'], mix.inputs[2])
            texture.location = (base.location.x, base.location.y - index * 330)
            tint.location = (base.location.x + 220, texture.location.y)
            mix.location = (base.location.x + 450 + index * 180, base.location.y)
            color = mix.outputs['Color']
        for destination in destinations:
            tree.links.new(color, destination)
    return [f"eye_layer_{index}" for index, _ in layers]
