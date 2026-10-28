"""Assemble the pinned original shader graphs; do not approximate their math."""
from pathlib import Path
import bpy
from .upstream_mapping import ADDITIONAL_MAPPING, ALPHA_MAPPING, FACE_MAPPING, MATERIAL_MAPPING, OUTLINE_MAPPING

LIBRARY_PATH = Path(__file__).parent / "assets/original_shader.blend"
CONTROLS_PATH = Path(__file__).parent / "assets/original_controls.blend"
FACE_TYPES = {"Loli":1, "Boy":2, "Girl":3, "Male":4, "Lady":5}
FACE_NODES = {1:"Face_Lightmap", 2:"Face_Lightmap.001", 3:"Face_Lightmap.002",
              4:"Face_Lightmap.003", 5:"Face_Lightmap.004"}


def walk(tree, seen=None):
    seen = set() if seen is None else seen
    if tree.as_pointer() in seen:
        return
    seen.add(tree.as_pointer())
    yield tree
    for node in tree.nodes:
        if node.type == "GROUP" and node.node_tree:
            yield from walk(node.node_tree, seen)


def load_image(path, data=False):
    colorspace = "Non-Color" if data else "sRGB"
    key = str(path.resolve()).casefold()
    image = next((i for i in bpy.data.images if i.get("hgt_file") == key
                  and i.colorspace_settings.name == colorspace and i.alpha_mode == "CHANNEL_PACKED"), None)
    if image is None:
        image = bpy.data.images.load(str(path), check_existing=False)
        image.colorspace_settings.name = colorspace
        image.alpha_mode = "CHANNEL_PACKED"
        image["hgt_file"] = key
    return image


def input_value(modifier, name):
    socket = next((s for s in modifier.node_group.interface.items_tree
                   if s.item_type == "SOCKET" and s.in_out == "INPUT" and s.name == name), None)
    if socket is None:
        raise ValueError(f"原版节点缺少输入：{name}")
    return getattr(modifier.properties.inputs, socket.identifier)


def set_input(modifier, name, value):
    input_value(modifier, name).value = value


def apply_mapping(node, mapping, assets):
    applied = {}
    for key, name in mapping.items():
        value = assets.colors.get(key, assets.floats.get(key))
        if value is None:
            continue
        socket = node.inputs.get(name)
        if socket is None:
            raise ValueError(f"原版材质节点缺少参数：{node.name} / {name}")
        if isinstance(value, dict):
            value = tuple(float(value[k]) for k in ("r", "g", "b", "a"))
        socket.default_value = value
        applied[key] = name
    return applied


class ShaderLibrary:
    def __init__(self, root):
        self.root = root
        self.uid = root.hgt_character.uid
        with bpy.data.libraries.load(str(LIBRARY_PATH), link=False) as (source, target):
            target.materials = source.materials
            target.node_groups = source.node_groups
        self.materials = {m["hgt_upstream"]:m for m in target.materials}
        self.groups = {g["hgt_upstream"]:g for g in target.node_groups}
        for item in (*self.materials.values(), *self.groups.values()):
            item["hgt_owner"] = self.uid
            item.use_fake_user = False
            item.name = f"HGT • {root.name} • {item['hgt_upstream']}"
        settings = root.hgt_character
        settings.global_properties = self.groups["Global Material Properties"]
        settings.light_vectors = self.groups["Light Vectors"]
        settings.outline_graph = self.groups["HoYoverse - Genshin Impact Outlines"]
        # Same links made by the original LightingPanel v3.4 setup.
        tree = settings.global_properties
        output = tree.nodes["Global Properties"]
        for node_name, socket_name in (("Ambient", "Ambient Colour"), ("SharpLit", "Sharp Lit Colour"),
                                      ("SoftLit", "Soft Lit Colour"), ("SharpShadow", "Sharp Shadow Colour"),
                                      ("SoftShadow", "Soft Shadow Colour"), ("RimLitMult", "Rim Lit"),
                                      ("RimShadowMult", "Rim Shadow")):
            node = tree.nodes.get(node_name)
            if node and output.inputs.get(socket_name):
                source = node.outputs.get("Result") or node.outputs.get("Color")
                if source:
                    tree.links.new(source, output.inputs[socket_name])

    def controls(self, collection):
        with bpy.data.libraries.load(str(CONTROLS_PATH), link=False) as (source, target):
            target.objects = source.objects
        controls = {}
        for obj in target.objects:
            key = obj["hgt_upstream"]
            controls[key] = obj
            obj["hgt_owner"] = self.uid
            obj.name = f"HGT • {self.root.name} • {key}"
            obj.use_fake_user = False
            obj.hide_render = True
            collection.objects.link(obj)
            obj.hide_set(True)
            entry = self.root.hgt_character.controls.add()
            entry.object, entry.key = obj, key
        bpy.context.view_layer.update()
        return controls

    def _private_textures(self, tree, copies):
        # Localize only texture-bearing paths, retaining the original formulas.
        for node in tree.nodes:
            if node.type != "GROUP" or not node.node_tree:
                continue
            original = node.node_tree
            if not any(n.type == "TEX_IMAGE" for g in walk(original) for n in g.nodes):
                continue
            key = original.as_pointer()
            if key not in copies:
                copied = original.copy()
                copies[key] = copied
                copied.use_fake_user = False
                copied["hgt_owner"] = self.uid
                self._private_textures(copied, copies)
            node.node_tree = copies[key]

    def _bind_textures(self, material, assets):
        main = assets.textures.get("diffuse")
        if main is None:
            raise ValueError(f"{assets.source} 缺少基础色贴图")
        face_type = next((v for k,v in FACE_TYPES.items() if f"Avatar_{k}" in assets.source), None)
        if face_type is None:
            raise ValueError(f"无法确定原版脸部类型：{assets.source}")
        for tree in walk(material.node_tree):
            for node in tree.nodes:
                if node.type != "TEX_IMAGE":
                    continue
                name = node.name
                role, data = None, False
                if "Diffuse" in name:
                    role = "diffuse"
                elif "Normalmap" in name:
                    role, data = "normal", True
                elif "Lightmap" in name and not name.startswith("Face_"):
                    role, data = "lightmap", True
                elif name == "Body_Shadow_Ramp":
                    role = "body_ramp"
                elif name == "Hair_Shadow_Ramp":
                    role = "hair_ramp"
                elif name == "MetalMap":
                    role = "metal"
                elif tree.get("hgt_upstream") == "Genshin Specular" and name == "Image Texture":
                    role, data = "specular_ramp", True
                elif name == FACE_NODES[face_type]:
                    role, data = "face_sdf", True
                elif name == "Face_Shadow":
                    role, data = "lightmap", True
                path = assets.textures.get(role) if role else None
                if path:
                    node.image = load_image(path, data)
                    node["hgt_texture_role"] = role
        node = material.node_tree.nodes.get("Face Shader")
        if node:
            if "face_sdf" not in assets.textures or "lightmap" not in assets.textures:
                raise ValueError(f"{assets.source} 缺少原版脸部阴影贴图")
            node.inputs["[Loli/Boy/Girl/Male/Lady]"].default_value = face_type

    def build_material(self, assets):
        diffuse_name = assets.textures.get("diffuse", Path("")).stem
        if assets.role in {"face", "eye", "brow"} and "_Tex_Face_" in diffuse_name:
            kind = "Face"
        else:
            kind = "Hair" if assets.role == "hair" else "Body"
        if kind != "Face":
            for flag, role in (("_UseBumpMap", "normal"), ("_UseShadowRamp", "ramp"),
                               ("_MetalMaterial", "metal"), ("_MTUseSpecularRamp", "specular_ramp")):
                if assets.floats.get(flag, 0) and role not in assets.textures:
                    raise ValueError(f"{assets.source} 启用了 {flag}，但缺少配套 {role} 贴图")
        template = self.materials[f"HoYoverse - Genshin {kind}"]
        material = template.copy()
        material.name = f"HGT • {self.root.name} • {assets.source.rsplit('_Mat_', 1)[-1]}"
        material["hgt_owner"], material["hgt_source"], material["hgt_role"] = self.uid, assets.source, assets.role
        material["hgt_json"] = str(assets.json_path or "")
        material["hgt_template"] = kind
        if assets.source.rsplit('_Mat_', 1)[-1] in {"Face", "Eye", "Pupil"}:
            material.use_raytrace_refraction = True
        self._private_textures(material.node_tree, {})
        self._bind_textures(material, assets)
        node = material.node_tree.nodes["Face Shader" if kind == "Face" else "Body Shader"]
        applied = apply_mapping(node, FACE_MAPPING if kind == "Face" else MATERIAL_MAPPING, assets)
        if kind != "Face":
            applied.update(apply_mapping(node, ADDITIONAL_MAPPING, assets))
            if "_UseShadowRamp" not in assets.floats:
                node.inputs["Use Shadow Ramp"].default_value = int("ramp" in assets.textures)
            if "_UseLightMapColorAO" not in assets.floats:
                node.inputs["Use Lightmap AO"].default_value = int("lightmap" in assets.textures)
            mode = int(assets.floats.get("_MainTexAlphaUse", 0))
            if mode not in ALPHA_MAPPING:
                raise ValueError(f"原版 v3 不支持该 Alpha 模式：{assets.source} / {mode}")
            for key, value in ALPHA_MAPPING[mode].items():
                node.inputs[key].default_value = value
        material["hgt_applied_parameters"] = list(applied)
        outline = self.materials["HoYoverse - Genshin Outlines"].copy()
        outline.name = material.name + " Outlines"
        outline["hgt_owner"], outline["hgt_source"] = self.uid, assets.source
        # The original outline importer skips Face; its face-shader branch
        # supplies the outline color without diffuse/lightmap image nodes.
        if kind != "Face":
            self._bind_textures(outline, assets)
        outline_node = outline.node_tree.nodes["Outlines"]
        apply_mapping(outline_node, OUTLINE_MAPPING, assets)
        if kind == "Face":
            outline_node.inputs["Use Face Shader"].default_value = 1
        if int(assets.floats.get("_MainTexAlphaUse", 0)) == 1:
            outline_node.inputs["Use Alpha"].default_value = 1
        return material, outline

    def finish(self):
        for material in self.materials.values():
            if material.users == 0:
                bpy.data.materials.remove(material)
        self.groups["HoYoverse - Post Processing"].use_fake_user = True


def set_controls(root):
    settings = root.hgt_character
    tree = settings.global_properties
    if tree is None:
        return
    socket = tree.nodes["Global Properties"].inputs["Shadow Position"]
    if abs(socket.default_value - settings.shadow_position) > 1e-6:
        socket.default_value = settings.shadow_position
