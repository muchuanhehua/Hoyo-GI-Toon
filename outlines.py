"""Connect the original material-aware outline geometry node, without new math."""
from .shaders import input_value, set_input

PAIRS = ("Hair", "Body", "Face", "Dress", "Dress 2", "Other")
# Fixed V3_GenshinImpactGeometryNodesSetup mask routing, in upstream order.
PART_PAIRS = {"Hair":"Hair", "Body":"Body", "Face":"Face", "Dress":"Dress", "Dress1":"Dress",
              "Helmet":"Dress", "Dress2":"Dress 2", "Arm":"Other", "Effect":"Other",
              "EffectHair":"Other", "Gauntlet":"Other", "HelmetEmo":"Other"}


def build(mesh, root):
    if mesh.name.split('.')[0] in {"Brow", "Pupil"}:
        return None
    bindings = {b.generated:b.outline for b in root.hgt_character.bindings}
    materials = list(dict.fromkeys(s.material for s in mesh.material_slots if s.material in bindings))
    if len(materials) > len(PAIRS):
        raise ValueError(f"{mesh.name} 超出原版描边的六个材质分区")
    modifier = mesh.modifiers.new("HGT • Outlines", "NODES")
    modifier.node_group = root.hgt_character.outline_graph
    set_input(modifier, "Base Geometry", True)
    set_input(modifier, "Use Vertex Colors?", True)
    color = input_value(modifier, "Vertex Colors")
    color.type = "ATTRIBUTE"
    color.attribute_name = "Col"
    by_part = {b.source_name.rsplit("_Mat_",1)[-1]:b.generated for b in root.hgt_character.bindings}
    routed = {pair:by_part[part] for part,pair in PART_PAIRS.items() if part in by_part}
    # Newer exports can have additional Body01/Body02 parts. Reuse unused
    # original slots on this mesh without reordering the standard V3 masks.
    for material in materials:
        if material in routed.values():
            continue
        available = [pair for pair in PAIRS if routed.get(pair) not in materials]
        preferred = material["hgt_template"]
        pair = preferred if preferred in available else available[0]
        routed[pair] = material
    for part, material in routed.items():
        set_input(modifier, part, material)
        set_input(modifier, part + " Outline", bindings[material])
    update(mesh, root)
    return modifier


def update(mesh, root):
    settings = root.hgt_character
    for modifier in mesh.modifiers:
        if modifier.type != "NODES" or modifier.node_group != settings.outline_graph:
            continue
        value = settings.outline
        field = input_value(modifier, "Outline Thickness")
        if abs(field.value - value) > 1e-7:
            field.value = value
        enabled = value > 0
        if modifier.show_viewport != enabled:
            modifier.show_viewport = enabled
        if modifier.show_render != enabled:
            modifier.show_render = enabled
