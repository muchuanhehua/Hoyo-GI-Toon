"""Keep original node graphs, remove preview models and all embedded textures."""
import hashlib
import json
from pathlib import Path
import bpy

ROOT = Path(__file__).resolve().parents[1]
reference = ROOT / ".verification/upstream/shader"
bpy.ops.wm.read_factory_settings(use_empty=True)
for path in sorted(reference.glob("*.blend")):
    with bpy.data.libraries.load(str(path), link=False) as (source, target):
        target.materials = source.materials
        target.node_groups = source.node_groups
for material in bpy.data.materials:
    material["hgt_upstream"] = material.name
for group in bpy.data.node_groups:
    group["hgt_upstream"] = group.name
trees = list(bpy.data.node_groups) + [m.node_tree for m in bpy.data.materials if m.node_tree]
references = []
for tree in trees:
    for node in tree.nodes:
        if node.type == "TEX_IMAGE" and node.image:
            node["hgt_texture_reference"] = node.image.name
            references.append({"tree":tree.name, "node":node.name, "image":node.image.name,
                               "colorspace":node.image.colorspace_settings.name,
                               "alpha_mode":node.image.alpha_mode})
            node.image = None
for image in list(bpy.data.images):
    bpy.data.images.remove(image)
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
output = ROOT / "assets/original_shader.blend"
output.parent.mkdir(exist_ok=True)
ids = set(bpy.data.materials) | set(bpy.data.node_groups)
bpy.data.libraries.write(str(output), ids, fake_user=True, compress=True)
records = json.loads((ROOT / ".verification/upstream/downloads.json").read_text(encoding="utf-8"))
provenance = {"shader_repository":"https://github.com/festivities/Blender-miHoYo-Shaders",
              "shader_commit":"b79f0f3fb47b4de2b6d187ee6b66d93cb965968d",
              "wizard_repository":"https://github.com/michael-gh1/Addons-And-Tools-For-Blender-miHoYo-Shaders",
              "wizard_commit":"fb942ecc30d9ed3889f5afb0dfb3a23c13601a54",
              "sources":[r for r in records if r["path"].endswith(".blend")],
              "library_sha256":hashlib.sha256(output.read_bytes()).hexdigest(),
              "changes":["Converted by Blender 5.2", "Removed all images and preview objects; nodes keep original image-name references"],
              "texture_references":references,
              "materials":[m.name for m in bpy.data.materials],
              "node_groups":[g.name for g in bpy.data.node_groups]}
bpy.ops.wm.read_factory_settings(use_empty=True)
with bpy.data.libraries.load(str(reference / "HoYoverse - Genshin Impact v3.4.blend"), link=False) as (source, target):
    target.objects = [name for name in source.objects if name != "Preview"]
panel = ROOT / ".verification/upstream/wizard/setup_wizard/character_rig_setup/LightingPanel_Shader_v3_4.blend"
with bpy.data.libraries.load(str(panel), link=False) as (source, target):
    target.objects = source.objects
for obj in bpy.data.objects:
    obj["hgt_upstream"] = obj.name
for image in list(bpy.data.images):
    bpy.data.images.remove(image)
controls = ROOT / "assets/original_controls.blend"
bpy.data.libraries.write(str(controls), set(bpy.data.objects), fake_user=True, compress=True)
provenance["controls_sha256"] = hashlib.sha256(controls.read_bytes()).hexdigest()
provenance["controls_source"] = next(r for r in records if r["path"].endswith("LightingPanel_Shader_v3_4.blend"))
(ROOT / "assets/upstream.json").write_text(json.dumps(provenance, indent=2)+"\n", encoding="utf-8", newline="\n")
print("ORIGINAL_LIBRARY", len(ids), "datablocks; no images or objects", output.stat().st_size)
