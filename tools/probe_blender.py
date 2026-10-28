"""Inspect a disposable Blender process without writing user preferences."""
import json
from pathlib import Path
import bpy

result = {"blender": bpy.app.version_string, "binary": bpy.app.binary_path, "operators": {}, "nodes": {}}
for namespace, name in (("wm", "fbx_import"), ("import_scene", "fbx"), ("export_scene", "fbx"),
                        ("extensions", "repo_add"), ("preferences", "extension_repo_add")):
    try:
        operator = getattr(getattr(bpy.ops, namespace), name)
        result["operators"][f"{namespace}.{name}"] = [p.identifier for p in operator.get_rna_type().properties]
    except (RuntimeError, KeyError):
        result["operators"][f"{namespace}.{name}"] = None
material = bpy.data.materials.new("HGT Probe")
material.use_nodes = True
for kind in ("ShaderNodeShaderToRGB", "ShaderNodeBsdfDiffuse", "ShaderNodeEmission", "ShaderNodeVectorRotate"):
    node = material.node_tree.nodes.new(kind)
    result["nodes"][kind] = {"inputs": [x.name for x in node.inputs], "outputs": [x.name for x in node.outputs]}
root = Path(__file__).resolve().parents[1]
output = root / ".verification/probe.json"
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("HGT_PROBE", json.dumps(result, ensure_ascii=False), flush=True)
