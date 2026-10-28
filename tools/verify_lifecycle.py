"""Check two-character isolation, head tracking, reload, and failure rollback."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch
import bpy

parser = argparse.ArgumentParser()
parser.add_argument("--model", action="append", required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
if len(args.model) != 2:
    raise ValueError("Provide two different FBX assets")
project = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hoyo_gi_toon", project / "__init__.py", submodule_search_locations=[str(project)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
bpy.ops.wm.read_factory_settings(use_empty=True)


def controls(root):
    return round(root.hgt_character.global_properties.nodes['Global Properties'].inputs['Shadow Position'].default_value,5)


def counts():
    return {kind: len(getattr(bpy.data, kind)) for kind in ("objects", "materials", "meshes", "armatures", "collections", "node_groups", "images", "lights", "cameras", "actions")}


first = addon.workflow.build(args.model[0], bpy.context)
second = addon.workflow.build(args.model[1], bpy.context)
first_uid, second_uid = first.hgt_character.uid, second.hgt_character.uid
assert first_uid != second_uid
first_before = controls(first)
second.hgt_character.shadow_position = 0.65
assert controls(first) == first_before, "Changing one character changed another"
assert controls(second) != first_before
for root, path in ((first, args.model[0]), (second, args.model[1])):
    directory = Path(path).resolve().parent
    for binding in root.hgt_character.bindings:
        for tree in addon.workflow.shaders.walk(binding.generated.node_tree):
          for node in tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                assert Path(bpy.path.abspath(node.image.filepath)).resolve().is_relative_to(directory), "Cross-character texture match"

head = second.hgt_character.head
constraint=head.constraints['Child Of']
bone = constraint.target.pose.bones[constraint.subtarget]
before_head=head.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.copy()
old_mode, old_rotation = bone.rotation_mode, bone.rotation_quaternion.copy()
bone.rotation_mode = "QUATERNION"
from mathutils import Euler
bone.rotation_quaternion = Euler((0.2, 0.4, 0.3)).to_quaternion()
bpy.context.view_layer.update()
addon.workflow.refresh_character(second, bpy.context.evaluated_depsgraph_get())
assert head.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world != before_head, "Original head driver did not follow pose"
bone.rotation_quaternion = old_rotation
bone.rotation_mode = old_mode
bpy.context.view_layer.update()
second.scale = (1.5, 0.8, 1.2)
bpy.context.view_layer.update()
addon.workflow.refresh_character(second)
assert all(s.mesh.data.shape_keys is not None for s in second.hgt_character.slots if s.mesh.name.startswith("Brow"))

before_failure = counts()
selected, active = tuple(bpy.context.selected_objects), bpy.context.view_layer.objects.active
original = addon.workflow.AssetCatalog.resolve
calls = 0


def fail_second(catalog, name):
    global calls
    calls += 1
    if calls == 2:
        raise ValueError("Injected missing asset")
    return original(catalog, name)


with patch.object(addon.workflow.AssetCatalog, "resolve", fail_second):
    try:
        addon.workflow.build(args.model[0], bpy.context)
    except ValueError as exc:
        assert str(exc) == "Injected missing asset"
    else:
        raise AssertionError("Fault did not interrupt the transaction")
assert counts() == before_failure, (before_failure, counts())
assert tuple(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active
addon.panels.post_processing.configure(bpy.context.scene,second)
node_count=len(bpy.context.scene.compositing_node_group.nodes)
addon.panels.post_processing.configure(bpy.context.scene,second)
assert len(bpy.context.scene.compositing_node_group.nodes)==node_count
bpy.context.scene.render.resolution_x=256
bpy.context.scene.render.resolution_y=320
bpy.context.scene.render.filepath=str(project / '.verification/original/post-processing.png')
bpy.ops.render.render(write_still=True)
scene_file = project / ".verification/original/two-characters.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(scene_file), relative_remap=False)
bpy.ops.wm.open_mainfile(filepath=str(scene_file))
roots = [o for o in bpy.context.scene.objects if o.hgt_character.managed]
assert {o.hgt_character.uid for o in roots} == {first_uid, second_uid}
for root in roots:
    addon.workflow.refresh_character(root)
report = {"two_character_isolation": True, "local_asset_boundaries": True,
          "head_shadow_tracking": True, "nonuniform_scale_update": True,
          "failed_import_rollback": True, "save_reload": True, "original_post_processing":True}
(project / ".verification/original/lifecycle.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print("HGT_LIFECYCLE", json.dumps(report), flush=True)
addon.unregister()
