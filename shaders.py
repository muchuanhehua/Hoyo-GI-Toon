"""Owned EEVEE node graphs for the initial FBX rendering workflow."""
import bpy


class Graph:
    def __init__(self, tree):
        self.tree = tree
        self.column = 0

    def node(self, kind, label=""):
        node = self.tree.nodes.new(kind)
        node.label = label
        node.location = (self.column % 6 * 230, -(self.column // 6) * 220)
        self.column += 1
        return node

    def connect(self, source, target):
        if hasattr(source, "is_output"):
            self.tree.links.new(source, target)
        else:
            target.default_value = source

    def math(self, operation, a, b=0):
        node = self.node("ShaderNodeMath")
        node.operation = operation
        self.connect(a, node.inputs[0])
        self.connect(b, node.inputs[1])
        return node.outputs[0]

    def mix(self, mode, a, b, factor=1):
        node = self.node("ShaderNodeMixRGB")
        node.blend_type = mode
        self.connect(factor, node.inputs[0])
        self.connect(a, node.inputs[1])
        self.connect(b, node.inputs[2])
        return node.outputs[0]

    def value(self, key, value):
        node = self.node("ShaderNodeValue", key)
        node["hgt_control"] = key
        node.outputs[0].default_value = value
        return node.outputs[0]

    def separate(self, value):
        node = self.node("ShaderNodeSeparateXYZ")
        self.connect(value, node.inputs[0])
        return node

    def combine(self, x, y, z=0):
        node = self.node("ShaderNodeCombineXYZ")
        for i, value in enumerate((x, y, z)):
            self.connect(value, node.inputs[i])
        return node.outputs[0]

    def image(self, path, data=False, vector=None, settings=None):
        colorspace = "Non-Color" if data else "sRGB"
        key = str(path.resolve()).casefold()
        image = next((item for item in bpy.data.images if item.get("hgt_file") == key
                      and item.colorspace_settings.name == colorspace
                      and item.alpha_mode == "CHANNEL_PACKED"), None)
        if image is None:
            image = bpy.data.images.load(str(path), check_existing=False)
            image.colorspace_settings.name = colorspace
            # Genshin alpha commonly stores glow/blush/material data, including
            # zero-alpha pixels with valid RGB. Straight-alpha interpretation
            # loses those colors during GPU sampling.
            image.alpha_mode = "CHANNEL_PACKED"
            image["hgt_file"] = key
        node = self.node("ShaderNodeTexImage", path.stem)
        node.image = image
        node.extension = "EXTEND" if vector is not None and settings is None else "REPEAT"
        if vector is None:
            uv = self.node("ShaderNodeTexCoord")
            vector = uv.outputs["UV"]
        if settings:
            scale = settings.get("m_Scale", {})
            offset = settings.get("m_Offset", {})
            if scale or offset:
                mapping = self.node("ShaderNodeVectorMath")
                mapping.operation = "MULTIPLY_ADD"
                self.connect(vector, mapping.inputs[0])
                mapping.inputs[1].default_value = (scale.get("X", 1), scale.get("Y", 1), 1)
                mapping.inputs[2].default_value = (offset.get("X", 0), offset.get("Y", 0), 0)
                vector = mapping.outputs[0]
        self.connect(vector, node.inputs[0])
        return node


def _smooth(g, value, threshold, softness):
    low = g.math("SUBTRACT", threshold, softness)
    high = g.math("ADD", threshold, softness)
    node = g.node("ShaderNodeMapRange")
    node.interpolation_type = "SMOOTHSTEP"
    node.clamp = True
    for socket, source in ((0, value), (1, low), (2, high)):
        g.connect(source, node.inputs[socket])
    return node.outputs[0]


def build_material(material, assets, root):
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    g = Graph(tree)
    material["hgt_owner"] = root.hgt_character.uid
    material["hgt_role"] = assets.role
    material["hgt_source"] = assets.source
    material["hgt_json"] = str(assets.json_path or "")
    main_path = assets.textures.get("pupil") or assets.textures.get("diffuse")
    if not main_path:
        raise ValueError(f"{assets.source} 缺少基础色贴图，请将配套贴图放到模型目录")
    diffuse = g.image(main_path, settings=assets.texture_settings.get("diffuse"))
    base = g.mix("MULTIPLY", diffuse.outputs["Color"], assets.color("_Color", (1, 1, 1, 1)))
    geometry = g.node("ShaderNodeNewGeometry")
    threshold = g.value("threshold", root.hgt_character.threshold)
    softness = g.value("softness", root.hgt_character.softness)
    light = g.node("ShaderNodeCombineXYZ", "Light direction")
    light["hgt_control"] = "light_vector"
    normal = geometry.outputs["Normal"]
    if "normal" in assets.textures and assets.role not in {"face", "brow", "eye"}:
        normal_tex = g.image(assets.textures["normal"], data=True, settings=assets.texture_settings.get("normal"))
        separate = g.node("ShaderNodeSeparateColor")
        g.connect(normal_tex.outputs["Color"], separate.inputs[0])
        # Unity's DXT5nm-style normal maps store tangent X in alpha and Y in G.
        normal_color = g.node("ShaderNodeCombineColor")
        g.connect(normal_tex.outputs["Alpha"], normal_color.inputs[0])
        g.connect(separate.outputs[1], normal_color.inputs[1])
        normal_color.inputs[2].default_value = 1
        normal_map = g.node("ShaderNodeNormalMap")
        normal_map.inputs[0].default_value = max(0, float(assets.floats.get("_BumpScale", 0.5)))
        color_source = normal_tex.outputs["Color"] if assets.floats.get("_isNativeMainNormal", 0) else normal_color.outputs[0]
        g.connect(color_source, normal_map.inputs["Color"])
        normal = normal_map.outputs[0]
    ndotl = g.node("ShaderNodeVectorMath")
    ndotl.operation = "DOT_PRODUCT"
    g.connect(normal, ndotl.inputs[0])
    g.connect(light.outputs[0], ndotl.inputs[1])
    half = g.math("MULTIPLY_ADD", ndotl.outputs["Value"], 0.5)
    half.node.inputs[2].default_value = 0.5
    level = _smooth(g, half, threshold, softness)
    lm = None
    if "lightmap" in assets.textures and assets.role in {"body", "hair"}:
        lm = g.image(assets.textures["lightmap"], data=True, settings=assets.texture_settings.get("lightmap"))
        channels = g.node("ShaderNodeSeparateColor")
        g.connect(lm.outputs["Color"], channels.inputs[0])
        ao = g.math("MULTIPLY_ADD", channels.outputs[1], 0.5)
        ao.node.inputs[2].default_value = 0.5
        level = g.math("MULTIPLY", level, ao)
    if assets.role == "face" and "face_sdf" in assets.textures:
        uv = g.node("ShaderNodeTexCoord")
        split = g.separate(uv.outputs["UV"])
        side = g.value("face_side", 1)
        flip = g.math("LESS_THAN", side, 0)
        x = g.math("ADD", g.math("MULTIPLY", split.outputs[0], g.math("SUBTRACT", 1, g.math("MULTIPLY", flip, 2))), flip)
        sdf = g.image(assets.textures["face_sdf"], data=True, vector=g.combine(x, split.outputs[1]))
        split_sdf = g.node("ShaderNodeSeparateColor")
        g.connect(sdf.outputs[0], split_sdf.inputs[0])
        forward = g.value("face_forward", 1)
        face_cut = g.math("SUBTRACT", 1, g.math("MAXIMUM", forward, 0))
        level = _smooth(g, split_sdf.outputs[0], face_cut, softness)
    shadow = g.node("ShaderNodeRGB", "Shadow tint")
    shadow["hgt_control"] = "shadow_color"
    shadow.outputs[0].default_value = root.hgt_character.shadow_color
    tone = g.mix("MIX", shadow.outputs[0], (1, 1, 1, 1), level)
    if lm and "ramp" in assets.textures and assets.floats.get("_UseShadowRamp", 1):
        row = g.math("ADD", g.math("MULTIPLY", g.math("FLOOR", g.math("MULTIPLY", lm.outputs["Alpha"], 4.99)), 0.1), 0.55)
        ramp_uv = g.combine(g.math("ADD", g.math("MULTIPLY", level, 0.85), 0.15), row)
        ramp = g.image(assets.textures["ramp"], vector=ramp_uv)
        tone = g.mix("MULTIPLY", tone, ramp.outputs[0])
    color = g.mix("MULTIPLY", base, tone)
    # Eye and brow textures carry drawn detail; avoid adding large lighting bands.
    if assets.role in {"eye", "brow"}:
        color = base
    facing = g.node("ShaderNodeVectorMath")
    facing.operation = "DOT_PRODUCT"
    g.connect(geometry.outputs["Normal"], facing.inputs[0])
    g.connect(geometry.outputs["Incoming"], facing.inputs[1])
    edge = g.math("POWER", g.math("SUBTRACT", 1, g.math("ABSOLUTE", facing.outputs["Value"])), 4)
    rim = g.math("MULTIPLY", edge, g.value("rim", root.hgt_character.rim))
    color = g.mix("ADD", color, (1, 0.92, 0.82, 1), rim)
    color = g.mix("MULTIPLY", color, g.value("light_gain", root.hgt_character.light_energy * 0.5))
    emission = g.node("ShaderNodeEmission")
    g.connect(color, emission.inputs[0])
    output = g.node("ShaderNodeOutputMaterial")
    alpha_mode = int(assets.floats.get("_MainTexAlphaUse", 0))
    if alpha_mode in {1, 4}:
        transparent = g.node("ShaderNodeBsdfTransparent")
        alpha = diffuse.outputs["Alpha"]
        if alpha_mode == 1:
            alpha = g.math("GREATER_THAN", alpha, float(assets.floats.get("_MainTexAlphaCutoff", 0.5)))
        mix = g.node("ShaderNodeMixShader")
        g.connect(alpha, mix.inputs[0])
        g.connect(transparent.outputs[0], mix.inputs[1])
        g.connect(emission.outputs[0], mix.inputs[2])
        g.connect(mix.outputs[0], output.inputs[0])
    else:
        g.connect(emission.outputs[0], output.inputs[0])
    material.diffuse_color = (0.65, 0.65, 0.65, 1)
    material.use_backface_culling = False


def set_controls(material, values):
    if not material or not material.node_tree:
        return
    for node in material.node_tree.nodes:
        key = node.get("hgt_control")
        if key not in values:
            continue
        value = values[key]
        if key == "light_vector":
            for i in range(3):
                if abs(node.inputs[i].default_value - value[i]) > 1e-6:
                    node.inputs[i].default_value = value[i]
        elif key == "shadow_color":
            if any(abs(node.outputs[0].default_value[i] - value[i]) > 1e-6 for i in range(4)):
                node.outputs[0].default_value = value
        elif abs(node.outputs[0].default_value - value) > 1e-6:
            node.outputs[0].default_value = value
