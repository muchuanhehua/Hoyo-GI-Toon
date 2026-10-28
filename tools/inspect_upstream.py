"""Read pinned upstream .blend libraries without opening a user's scene."""
import json
from pathlib import Path
import bpy

ROOT = Path(__file__).resolve().parents[1]
reports = []


def value(socket):
    if not hasattr(socket, "default_value"):
        return None
    result = socket.default_value
    if isinstance(result, bpy.types.ID):
        return result.name
    if isinstance(result, (str, int, float, bool)) or result is None:
        return result
    return list(result)


def modifier_inputs(modifier):
    result = {}
    for socket in modifier.node_group.interface.items_tree:
        if socket.item_type != "SOCKET" or socket.in_out != "INPUT":
            continue
        try:
            item = modifier[socket.identifier]
        except (KeyError, TypeError):
            item = None
        result[socket.name] = item.name if isinstance(item, bpy.types.ID) else item
    return result


paths = list((ROOT / ".verification/upstream/shader").glob("*.blend"))
paths += list((ROOT / ".verification/upstream/wizard/setup_wizard/character_rig_setup").glob("*.blend"))
for path in sorted(paths):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    with bpy.data.libraries.load(str(path), link=False) as (source, target):
        names = {key: list(getattr(source, key)) for key in ("materials", "node_groups", "objects", "images")}
        target.materials = source.materials
        target.node_groups = source.node_groups
        target.objects = source.objects
    for obj in target.objects:
        bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.update()
    groups = []
    for group in bpy.data.node_groups:
        groups.append({"name": group.name, "type": group.bl_idname,
            "interface": [{"name": s.name, "direction": s.in_out, "type":s.socket_type,
                           "value":value(s)} for s in group.interface.items_tree if s.item_type == "SOCKET"],
            "nodes": [{"name":n.name, "type":n.bl_idname,
                       "group":n.node_tree.name if n.type == "GROUP" and n.node_tree else None,
                       "inputs": {s.name:value(s) for s in n.inputs if not s.is_linked}}
                      for n in group.nodes if n.type in {"GROUP", "TEX_IMAGE", "ATTRIBUTE", "UVMAP", "TEX_COORD"}],
            "drivers": [{"path": f.data_path, "expression": f.driver.expression,
                         "variables": [{"name":v.name, "type":v.type,
                                        "targets":[{"id":t.id.name if t.id else None, "type":t.id_type,
                                                    "path":t.data_path, "transform":t.transform_type} for t in v.targets]}
                                       for v in f.driver.variables]}
                        for f in group.animation_data.drivers] if group.animation_data else []})
    materials = []
    for material in bpy.data.materials:
        materials.append({"name":material.name, "culling":material.use_backface_culling,
            "nodes":[{"name":n.name, "type":n.bl_idname, "label":n.label,
                      "group":n.node_tree.name if n.type == "GROUP" and n.node_tree else None,
                      "image":n.image.name if n.type == "TEX_IMAGE" and n.image else None,
                      "inputs": {s.name:value(s) for s in n.inputs if not s.is_linked}}
                     for n in material.node_tree.nodes] if material.node_tree else []})
    objects = [{"name":o.name, "type":o.type, "location":list(o.location), "rotation":list(o.rotation_euler),
                "world":[list(row) for row in o.matrix_world], "parent":o.parent.name if o.parent else None,
                "constraints":[{"type":c.type, "name":c.name} for c in o.constraints],
                "modifiers":[{"name":m.name, "group":m.node_group.name,
                              "inputs":modifier_inputs(m)}
                             for m in o.modifiers if m.type == "NODES" and m.node_group]} for o in bpy.data.objects]
    reports.append({"file":path.name, "names":names, "materials":materials, "groups":groups, "objects":objects,
                    "images":[{"name":i.name, "path":i.filepath, "source":i.source} for i in bpy.data.images]})
(ROOT / ".verification/upstream/inspection.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
for report in reports:
    print("UPSTREAM", report["file"], json.dumps(report["names"], ensure_ascii=False))
