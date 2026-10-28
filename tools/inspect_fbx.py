"""Read supplied FBX models in an isolated process; write only local evidence."""
import argparse
import json
from pathlib import Path
import sys
import bpy
from mathutils import Vector

parser = argparse.ArgumentParser()
parser.add_argument("--model", action="append", type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
reports = []
for path in args.model:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    result = bpy.ops.wm.fbx_import(filepath=str(path), use_custom_normals=True)
    if result != {"FINISHED"}:
        raise RuntimeError(f"FBX import failed: {path.name}")
    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    points = [obj.matrix_world @ Vector(p) for obj in meshes for p in obj.bound_box]
    data = {"file": path.name, "meshes": [], "armatures": [], "bounds":
            [[min(p[a] for p in points), max(p[a] for p in points)] for a in range(3)]}
    for obj in meshes:
        data["meshes"].append({"name": obj.name, "vertices": len(obj.data.vertices),
                               "materials": [m.name if m else None for m in obj.data.materials],
                               "shape_keys": len(obj.data.shape_keys.key_blocks) if obj.data.shape_keys else 0,
                               "uvs": [uv.name for uv in obj.data.uv_layers]})
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            data["armatures"].append({"name": obj.name, "bones": len(obj.data.bones),
                "head_bones": [{"name": b.name, "head": list(b.head_local), "tail": list(b.tail_local)}
                               for b in obj.data.bones if "head" in b.name.lower()]})
    reports.append(data)
out = Path(__file__).resolve().parents[1] / ".verification/source-inspection.json"
out.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("HGT_SOURCE", json.dumps(reports, ensure_ascii=False), flush=True)
