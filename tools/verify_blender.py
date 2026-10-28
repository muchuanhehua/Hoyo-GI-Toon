"""Verify the supplied game FBX assets; keep source paths and renders private."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import bpy
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("--model", type=Path, action="append", required=True)
parser.add_argument("--render", action="store_true")
parser.add_argument("--output-dir", type=Path)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
project = Path(__file__).resolve().parents[1]
out = (args.output_dir or project / ".verification/original").resolve()
out.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location("hoyo_gi_toon", project / "__init__.py", submodule_search_locations=[str(project)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
reports = []

def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


for model in args.model:
    before = fingerprint(model)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    root = addon.workflow.build(str(model), bpy.context)
    settings = root.hgt_character
    meshes = [e.object for e in settings.meshes]
    source_keys = {mesh.name: len(mesh.data.shape_keys.key_blocks) if mesh.data.shape_keys else 0 for mesh in meshes}
    counts = {"materials": len(bpy.data.materials), "objects": len(bpy.data.objects), "groups": len(bpy.data.node_groups)}
    for _ in range(3):
        addon.workflow.refresh_character(root)
    assert counts == {"materials": len(bpy.data.materials), "objects": len(bpy.data.objects), "groups": len(bpy.data.node_groups)}, "Repeated refresh duplicated data"
    assert all(b.generated and b.generated.node_tree for b in settings.bindings), "Missing generated material"
    assert all(any(n.type == "TEX_IMAGE" and n.image for n in b.generated.node_tree.nodes) for b in settings.bindings), "Material has no texture"
    assert bpy.context.scene.camera, "Missing camera"
    assert fingerprint(model) == before, "Source FBX was modified"
    record = {"model": model.stem, "format": "FBX", "source_sha256": before,
              "meshes": len(meshes), "bindings": len(settings.bindings),
              "shape_keys": source_keys, "refresh_idempotent": True,
              "source_preserved": True, "textures": [], "renders": []}
    attachments = [s.material for mesh in meshes for s in mesh.material_slots
                   if s.material and s.material.name.startswith("Flycloak_")]
    for material in attachments:
        assert not material.get("hgt_owner"), "Original accessory material was replaced"
    record["preserved_accessory_materials"] = sorted({m.name for m in attachments})
    for binding in settings.bindings:
        assert all(n.image.alpha_mode == "CHANNEL_PACKED"
                   for t in addon.workflow.shaders.walk(binding.generated.node_tree)
                   for n in t.nodes if n.type == "TEX_IMAGE" and n.image), "Texture alpha mode changed"
        record["textures"].append({"material": binding.source_name,
            "images": [n.image.name for t in addon.workflow.shaders.walk(binding.generated.node_tree)
                       for n in t.nodes if n.type == "TEX_IMAGE" and n.image]})
    bpy.context.scene.render.resolution_x = 768
    bpy.context.scene.render.resolution_y = 896
    bpy.context.scene.render.resolution_percentage = 100
    bpy.context.scene.render.image_settings.file_format = "PNG"
    if args.render:
        for name, angle in (("front", 0.65), ("side-light", -1.0)):
            settings.light_azimuth = angle
            image = out / f"{model.stem}-{name}.png"
            bpy.context.scene.render.filepath = str(image)
            bpy.ops.render.render(write_still=True)
            assert image.is_file() and image.stat().st_size > 1000, "Render output missing"
            rendered = bpy.data.images.load(str(image), check_existing=False)
            pixels = np.asarray(rendered.pixels[:], dtype=np.float32).reshape((-1, 4))
            visible = pixels[:,3] > 0.5
            assert visible.mean() > 0.05, "Render is blank"
            # White clothing and skin can occupy most pixels in valid renders.
            assert (np.ptp(pixels[visible,:3], axis=1) > 0.02).mean() > 0.05, "Packed texture RGB was lost"
            assert ((pixels[visible,0] > 0.9) & (pixels[visible,2] > 0.9) & (pixels[visible,1] < 0.1)).mean() < 0.01, "Missing texture magenta"
            bpy.data.images.remove(rendered)
            record["renders"].append(image.name)
    settings.light_azimuth = 0.65
    file = out / f"{model.stem}-render.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(file), relative_remap=False)
    for snapshot in settings.slots:
        assert snapshot.mesh.material_slots[snapshot.index].material == snapshot.generated
    addon.workflow.restore(root)
    assert all(s.mesh.material_slots[s.index].material == s.original for s in settings.slots), "Material restore failed"
    assert source_keys == {m.name: len(m.data.shape_keys.key_blocks) if m.data.shape_keys else 0 for m in meshes}
    record["material_restore"] = True
    record["shape_keys_preserved"] = True
    record["visual_content_checks"] = bool(args.render)
    reports.append(record)
    (out / "fbx-verification.json").write_text(json.dumps({"blender": bpy.app.version_string,
        "models": reports}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("HGT_VERIFIED", json.dumps({key:value for key,value in record.items() if key != "textures"}, ensure_ascii=False), flush=True)
core_files = ("__init__.py", "asset_resolver.py", "importers.py", "properties.py", "shaders.py", "outlines.py", "workflow.py", "panels.py", "post_processing.py", "upstream_mapping.py", "assets/original_shader.blend", "assets/original_controls.blend", "assets/upstream.json")
report = {"blender": bpy.app.version_string, "models": reports,
          "core_sha256": {name:fingerprint(project/name) for name in core_files}}
(out / "fbx-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
addon.unregister()
