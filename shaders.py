"""Assemble native Festivity shader paths with per-material texture isolation."""

from pathlib import Path

import bpy

from .asset_tracking import data_pointers, new_data


LIBRARY_PATH = Path(__file__).parent / "assets/original_shader.blend"

CONTROLS_PATH = Path(__file__).parent / "assets/original_controls.blend"

def walk(tree, seen=None):
    seen = set() if seen is None else seen
    if tree.as_pointer() in seen:
        return
    seen.add(tree.as_pointer())
    yield tree
    for node in tree.nodes:
        if node.type == "GROUP" and node.node_tree:
            yield from walk(node.node_tree, seen)

def load_image(path, data=False, owner=""):
    colorspace = "Non-Color" if data else "sRGB"
    if isinstance(path, bpy.types.Image):
        image = next((i for i in bpy.data.images if i.get('hgt_source_image') == path
                      and i.get('hgt_owner') == owner and i.colorspace_settings.name == colorspace), None)
        if image is None:
            image = path.copy()
            image.colorspace_settings.name = colorspace
            image.alpha_mode = 'CHANNEL_PACKED'
            image['hgt_owner'], image['hgt_source_image'] = owner, path
        return image
    key = str(path.resolve()).casefold()
    image = next((i for i in bpy.data.images if i.get("hgt_file") == key
                  and i.get("hgt_owner") == owner
                  and i.colorspace_settings.name == colorspace and i.alpha_mode == "CHANNEL_PACKED"), None)
    if image is None:
        image = bpy.data.images.load(str(path), check_existing=False)
        image.colorspace_settings.name = colorspace
        image.alpha_mode = "CHANNEL_PACKED"
        image["hgt_file"] = key
        image["hgt_owner"] = owner
    return image

def neutral_packed(owner):
    """Explicit neutral ID/AO input for a source with no light-map reference."""
    key = 'Neutral material data'
    image = next((i for i in bpy.data.images if i.get('hgt_owner') == owner and i.get('hgt_generated') == key), None)
    if image is None:
        image = bpy.data.images.new('HGT • ' + key, 4, 4, alpha=True)
        image.colorspace_settings.name = 'Non-Color'
        image.alpha_mode = 'CHANNEL_PACKED'
        image.pixels[:] = [0, 1, 0, 0] * 16
        image['hgt_owner'], image['hgt_generated'] = owner, key
        image.pack()
    return image

def input_value(modifier, name):
    socket = next((s for s in modifier.node_group.interface.items_tree
                   if s.item_type == "SOCKET" and s.in_out == "INPUT" and s.name == name), None)
    if socket is None:
        raise ValueError(f"原版节点缺少输入：{name}")
    return getattr(modifier.properties.inputs, socket.identifier)

def set_input(modifier, name, value):
    input_value(modifier, name).value = value

class ShaderLibrary:
    def __init__(self, root):
        self.root = root
        self.uid = root.hgt_character.uid
        with bpy.data.libraries.load(str(LIBRARY_PATH), link=False) as (source, target):
            target.materials = source.materials
            target.node_groups = [name for name in source.node_groups if name != 'HoYoverse - Post Processing']
        self.materials = {m["hgt_upstream"]:m for m in target.materials}
        self.groups = {g["hgt_upstream"]:g for g in target.node_groups}
        for tree in (*self.groups.values(), *(m.node_tree for m in self.materials.values())):
            undefined = [node.name for node in tree.nodes if node.bl_idname == "NodeUndefined"]
            if undefined:
                raise ValueError(f"材质资源包含不可用节点：{tree.name} / {', '.join(undefined)}")
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
        before = data_pointers()
        with bpy.data.libraries.load(str(CONTROLS_PATH), link=False) as (source, target):
            target.objects = source.objects
        for values in new_data(before).values():
            for item in values:
                item["hgt_owner"] = self.uid
        controls = {}
        for obj in target.objects:
            key = obj["hgt_upstream"]
            controls[key] = obj
            obj["hgt_owner"] = self.uid
            obj["hgt_helper"] = True
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

    def finish(self):
        for material in self.materials.values():
            if material.users == 0:
                bpy.data.materials.remove(material)

    def build_material(self, assets):
        from .pmx_materials import build
        return build(self, assets)

def set_controls(root):
    settings = root.hgt_character
    tree = settings.global_properties
    if tree is None:
        return
    socket = tree.nodes["Global Properties"].inputs["Shadow Position"]
    if abs(socket.default_value - settings.shadow_position) > 1e-6:
        socket.default_value = settings.shadow_position
