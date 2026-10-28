"""Run original V3 wizard components independently of the HGT assembler.

Blender API access is bridged for native FBX import and modifier fields.
Optional flags explicitly normalize the missing V3 VFX name and local lookup
inputs. Routing, texture setters, defaults, material data and geometry-node
setup execute directly from pinned upstream source.
Private reference scenes and images must never be included in a release.
"""
import __future__
from abc import ABC, abstractmethod
import argparse
import ast
from enum import Enum, auto
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import List

import bpy
from mathutils import Vector
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / ".verification/upstream/wizard/setup_wizard"
parser = argparse.ArgumentParser()
parser.add_argument("--model", type=Path, action="append", required=True)
parser.add_argument("--output-dir", type=Path, required=True)
parser.add_argument("--no-outlines", action="store_true", help="Isolate shading from outline setup")
parser.add_argument("--compat-v3-names", action="store_true", help="Give the unavailable V4 VFX material a nonempty name")
parser.add_argument("--local-inputs", action="store_true", help="Use the same supplied lookup images instead of embedded defaults")
parser.add_argument("--audit-only", action="store_true", help="Record source incompatibilities without treating them as a pass")
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
OUT = args.output_dir.resolve()
OUT.mkdir(parents=True, exist_ok=True)

env = {"bpy": bpy, "os": os, "ABC": ABC, "abstractmethod": abstractmethod,
       "Enum": Enum, "auto": auto, "List": List, "ShaderNodeGroup": bpy.types.ShaderNodeGroup}
executed = {}


def original(relative, names=None, assignments=False):
    path = UPSTREAM / relative
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    body = [node for node in tree.body
            if (isinstance(node, (ast.ClassDef, ast.FunctionDef)) and (names is None or node.name in names))
            or (assignments and isinstance(node, ast.Assign))]
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec",
                 flags=__future__.annotations.compiler_flag), env)
    executed[relative] = hashlib.sha256(path.read_bytes()).hexdigest()


for file in ("domain/game_types.py", "domain/shader_node_names.py", "domain/shader_material_names.py",
             "domain/shader_material_name_keywords.py", "domain/star_cloak_types.py", "domain/vfx_shader_types.py",
             "texture_import_setup/texture_node_names.py", "domain/shader_identifier_service.py",
             "domain/shader_material.py", "domain/body_hair_ramp_switch_values.py",
             "material_import_setup/empty_names.py", "outline_import_setup/outline_node_groups.py",
             "geometry_nodes_setup/lighting_panel_names.py", "texture_import_setup/original_texture_locator_utils.py"):
    original(file)
original("import_order.py", {"get_actual_material_name_for_dress", "material_replacer_get_actual_material_name_for_dress"})
original("replace_default_materials_setup/game_default_material_replacers.py",
         {"GameDefaultMaterialReplacer", "GenshinImpactDefaultMaterialReplacer"})
original("texture_import_setup/texture_importer_types.py",
         {"TextureImporterType", "TextureType", "GenshinTextureImporter", "GenshinAvatarTextureImporter",
          "GenshinNPCTextureImporter", "GenshinMonsterTextureImporter"})
original("texture_import_setup/material_default_value_setters.py",
         {"MaterialDefaultValueSetter", "GenshinImpactMaterialDefaultValueSetter"})
original("geometry_nodes_setup/geometry_nodes_setups.py",
         {"GameGeometryNodesSetup", "V3_GenshinImpactGeometryNodesSetup"}, assignments=True)
original("character_rig_setup/lighting_panel_setup.py", {"LightingPanel", "GlobalPropertiesNames"})
original("texture_import_setup/outline_texture_importers.py",
         {"OutlineTextureImporter", "GenshinImpactOutlineTextureImporter"})
original("material_data_import_setup/material_data_applier.py",
         {"MaterialDataApplier", "V2_MaterialDataApplier", "V3_MaterialDataApplier", "V2_HSR_MaterialDataApplier"})

names = env["V3_BonnyFestivityGenshinImpactMaterialNames"]
if args.compat_v3_names:
    class V3Names(names):
        # The empty VFX string makes the current upstream outline importer
        # exclude every V3 material. This does not create any VFX material.
        VFX = names.MATERIAL_PREFIX + "VFX"
    names = V3Names
node_names = env["V3_GenshinShaderNodeNames"]
BaseGeometry = env["GameGeometryNodesSetup"]
OriginalGeometry = env["V3_GenshinImpactGeometryNodesSetup"]


class ModifierFields:
    """Translate old socket identifiers without changing wizard decisions."""
    def __init__(self, modifier):
        self.modifier = modifier

    def __contains__(self, key):
        return any(s.identifier == key for s in self.modifier.node_group.interface.items_tree
                   if s.item_type == "SOCKET")

    def field(self, key):
        kind = "value"
        for suffix, value in (("_attribute_name", "attribute_name"), ("_use_attribute", "type")):
            if key.endswith(suffix):
                key, kind = key[:-len(suffix)], value
                break
        socket = next((s for s in self.modifier.node_group.interface.items_tree
                       if s.item_type == "SOCKET" and s.identifier == key), None)
        if socket is None:
            raise KeyError(key)
        fields = self.modifier.properties.inputs if socket.in_out == "INPUT" else self.modifier.properties.outputs
        return getattr(fields, key), kind

    def __getitem__(self, key):
        field, kind = self.field(key)
        return field.type == "ATTRIBUTE" if kind == "type" else getattr(field, kind)

    def __setitem__(self, key, value):
        field, kind = self.field(key)
        setattr(field, kind, ("ATTRIBUTE" if value else "VALUE") if kind == "type" else value)


panel = env["LightingPanel"](str(UPSTREAM / "character_rig_setup/LightingPanel_Shader_v3_4.blend"))


class ModernGeometry(OriginalGeometry):
    def set_up_modifier_default_values(self, modifier, mesh):
        OriginalGeometry.set_up_modifier_default_values(self, ModifierFields(modifier), mesh)

    def set_up_light_vectors_modifier(self, modifier):
        BaseGeometry.set_up_light_vectors_modifier(self, ModifierFields(modifier))
        panel.set_up_lighting_panel(ModifierFields(modifier))
        # The old modifier inherited these names from its group interface.
        for socket in modifier.node_group.interface.items_tree:
            if socket.item_type == "SOCKET" and socket.in_out == "OUTPUT" and socket.name != "Geometry":
                getattr(modifier.properties.outputs, socket.identifier).attribute_name = socket.default_attribute_name


spec = importlib.util.spec_from_file_location("hoyo_gi_toon", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()


def value(socket):
    if not hasattr(socket, "default_value"):
        return None
    item = socket.default_value
    if isinstance(item, (str, int, float, bool)):
        return item
    return list(item)


def snapshot(material):
    shader_node = (material.node_tree.nodes.get("Face Shader") or material.node_tree.nodes.get("Body Shader")
                   or material.node_tree.nodes.get("Outlines"))
    return {"inputs": {socket.name: value(socket) for socket in shader_node.inputs},
            "direct_images": {node.name: {"name":Path(bpy.path.abspath(node.image.filepath)).name,
                                           "colorspace":node.image.colorspace_settings.name,
                                           "alpha":node.image.alpha_mode}
                              for node in material.node_tree.nodes if node.type == "TEX_IMAGE" and node.image},
            "refraction": material.use_raytrace_refraction}


def texture_pixels(tree, prefix="", stack=None):
    stack = set() if stack is None else stack
    if tree.as_pointer() in stack:
        return {}
    result = {}
    stack = stack | {tree.as_pointer()}
    for node in tree.nodes:
        key = prefix + node.name
        if node.type == "GROUP" and node.node_tree:
            result.update(texture_pixels(node.node_tree, key + "/", stack))
        elif node.type == "TEX_IMAGE" and node.image:
            values = np.empty(len(node.image.pixels), dtype=np.float32)
            node.image.pixels.foreach_get(values)
            result[key] = {"size":list(node.image.size),"sha256":hashlib.sha256(values.tobytes()).hexdigest(),
                           "channel_sha256":[hashlib.sha256(values.reshape((-1,4))[:,i].tobytes()).hexdigest() for i in range(4)],
                           "colorspace":node.image.colorspace_settings.name,"alpha":node.image.alpha_mode}
    return result


def modifiers(scene):
    result = {}
    for obj in scene.objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        groups = {}
        for modifier in obj.modifiers:
            if modifier.type != "NODES":
                continue
            inputs = {}
            for socket in modifier.node_group.interface.items_tree:
                if socket.item_type != "SOCKET" or socket.in_out != "INPUT" or socket.socket_type == "NodeSocketGeometry":
                    continue
                field = getattr(modifier.properties.inputs, socket.identifier)
                if socket.name in {"Base Geometry", "Use Vertex Colors?", "Vertex Colors", "Outline Thickness"}:
                    field_value = field.value
                    if not isinstance(field_value, (str,int,float,bool)):
                        field_value = list(field_value)
                    inputs[socket.name] = {"value":field_value, "type":getattr(field,"type",None),
                                           "attribute":getattr(field,"attribute_name",None),
                                           "group_attribute":getattr(socket,"default_attribute_name",None)}
            groups[modifier.node_group.get("hgt_upstream",modifier.node_group.name)] = inputs
        result[obj.name] = groups
    return result


def pixels(path):
    loaded = bpy.data.images.load(str(path), check_existing=False)
    result = np.asarray(loaded.pixels[:], dtype=np.float32)
    bpy.data.images.remove(loaded)
    return result


def geometry(scene, object_names):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    result = {}
    for name in object_names:
        obj = scene.objects[name].evaluated_get(depsgraph)
        mesh = obj.to_mesh()
        values = {"positions":np.array([obj.matrix_world @ vertex.co for vertex in mesh.vertices]),
                  "normals":np.array([normal.vector for normal in mesh.corner_normals])}
        for attr in mesh.attributes:
            prop = {"FLOAT_VECTOR":"vector", "FLOAT_COLOR":"color", "BYTE_COLOR":"color", "FLOAT":"value"}.get(attr.data_type)
            if prop and not attr.name.startswith("."):
                values["attribute:" + attr.name] = np.array([getattr(item,prop) for item in attr.data])
        result[name] = values
        obj.to_mesh_clear()
    return result


def render(scene, stem, angle):
    if args.no_outlines:
        for obj in scene.objects:
            for modifier in obj.modifiers:
                if modifier.type == "NODES" and "Outlines" in modifier.node_group.get("hgt_upstream",modifier.node_group.name):
                    modifier.show_render = False
    path = OUT / f"{stem}-{angle}.png"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return pixels(path)


reports = []
for model in args.model:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    root = addon.workflow.build(str(model), bpy.context)
    if args.no_outlines:
        root.hgt_character.outline = 0
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = 512, 640
    scene.render.resolution_percentage = 100
    bpy.context.view_layer.update()
    expected = {binding.source_name: snapshot(binding.generated) for binding in root.hgt_character.bindings}
    expected_outlines = {binding.source_name: snapshot(binding.outline) for binding in root.hgt_character.bindings}
    expected_pixels = {binding.source_name:texture_pixels(binding.generated.node_tree) for binding in root.hgt_character.bindings}
    expected_modifiers = modifiers(scene)
    expected_global = {socket.name:value(socket) for socket in root.hgt_character.global_properties.nodes["Global Properties"].inputs}
    original_slots = {mesh.name: [slot.material.get("hgt_source", slot.material.name) for slot in mesh.material_slots]
                      for mesh in scene.objects if mesh.type == "MESH" and not mesh.hide_render}
    camera_matrix = [list(row) for row in scene.camera.matrix_world]
    camera_location = tuple(scene.camera.location)
    camera_rotation = tuple(scene.camera.rotation_euler)
    camera_rotation_mode = scene.camera.rotation_mode
    camera_object_scale = tuple(scene.camera.scale)
    camera_scale = scene.camera.data.ortho_scale
    output = []
    for angle in (0.65, -1.0):
        root.hgt_character.light_azimuth = angle
        output.append(render(scene, model.stem + "-hgt-independent", angle))
    keys = ("Head Origin", "Head Forward", "Head Up", "Light Direction")
    depsgraph = bpy.context.evaluated_depsgraph_get()
    expected_controls = {entry.key:[list(row) for row in entry.object.evaluated_get(depsgraph).matrix_world]
                         for entry in root.hgt_character.controls if entry.key in keys}
    expected_geometry = geometry(scene, original_slots)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.fbx_import(filepath=str(model), use_custom_normals=True, mtl_name_collision_mode="MAKE_UNIQUE")
    imported = list(bpy.context.scene.objects)
    armature = next(obj for obj in imported if obj.type == "ARMATURE")
    for mesh in (obj for obj in imported if obj.type == "MESH"):
        if not mesh.data.uv_layers.get("UV1"):
            mesh.data.uv_layers.new(name="UV1")
        if mesh.data.color_attributes.active_color:
            mesh.data.color_attributes.active_color.name = "Col"
        if "EffectMesh" in mesh.name or "EyeStar" in mesh.name:
            mesh.hide_render = True
    for file in sorted((ROOT / ".verification/upstream/shader").glob("*.blend")):
        with bpy.data.libraries.load(str(file)) as (source, target):
            target.materials, target.node_groups = source.materials, source.node_groups
    for file in (ROOT / ".verification/upstream/shader/HoYoverse - Genshin Impact v3.4.blend",
                 UPSTREAM / "character_rig_setup/LightingPanel_Shader_v3_4.blend"):
        with bpy.data.libraries.load(str(file)) as (source, target):
            target.objects = [name for name in source.objects if name != "Preview"]
        for control in target.objects:
            bpy.context.scene.collection.objects.link(control)
            control.hide_render = True

    operator = SimpleNamespace(report=lambda level, message: print("REFERENCE", message),
                               file_directory=str(model.parent / "Textures"),
                               filepath=str(model), game_type="GENSHIN_IMPACT")
    context = SimpleNamespace(window_manager=SimpleNamespace(cache_enabled=False))
    env["GenshinImpactDefaultMaterialReplacer"](operator, bpy.context, names, node_names).replace_default_materials()
    env["GenshinAvatarTextureImporter"](names).import_textures(str(model.parent / "Textures"))
    if args.local_inputs:
        local_images = {path.stem:path for path in (model.parent / "Textures").iterdir() if path.is_file()}
        for group in bpy.data.node_groups:
            for node in group.nodes:
                if node.type != "TEX_IMAGE" or node.image is None:
                    continue
                path = local_images.get(Path(node.image.name).stem)
                if path:
                    colorspace = node.image.colorspace_settings.name
                    node.image = bpy.data.images.load(str(path), check_existing=True)
                    node.image.colorspace_settings.name = colorspace
                    node.image.alpha_mode = "CHANNEL_PACKED"
    env["GenshinImpactMaterialDefaultValueSetter"](names, node_names).set_default_values()
    ModernGeometry(operator, bpy.context).setup_geometry_nodes()
    env["GenshinImpactOutlineTextureImporter"](operator, context, names, node_names).import_textures()
    for file in (model.parent / "Materials").glob("*.json"):
        material = bpy.data.materials.get(names.MATERIAL_PREFIX + file.stem.rsplit("_Mat_", 1)[-1])
        if material is None:
            continue
        data = json.loads(file.read_text(encoding="utf-8-sig"))["m_SavedProperties"]
        color_data = {key: tuple(item[c] for c in ("r", "g", "b", "a")) for key, item in data.get("m_Colors", {}).items()}
        params = SimpleNamespace(m_floats=SimpleNamespace(**data.get("m_Floats", {})),
                                 m_colors=SimpleNamespace(**color_data), m_texEnvs=SimpleNamespace(**data.get("m_TexEnvs", {})))
        outline = bpy.data.materials[names.MATERIAL_PREFIX + file.stem.rsplit("_Mat_", 1)[-1] + " Outlines"]
        env["V3_MaterialDataApplier"](params, SimpleNamespace(material=material, outlines_material=outline,
                                                            night_soul_outlines_material=None)).set_up_mesh_material_data()
    head = bpy.data.objects["Head Origin"]
    constraint = head.constraints["Child Of"]
    constraint.target = armature
    constraint.subtarget = next(bone.name for bone in armature.data.bones if "Head" in bone.name)
    bpy.context.view_layer.objects.active = head
    bpy.ops.constraint.childof_set_inverse(constraint="Child Of", owner="OBJECT")

    differences = []
    reference_global = {socket.name:value(socket) for socket in bpy.data.node_groups["Global Material Properties"].nodes["Global Properties"].inputs}
    global_differences = {key:[reference_global.get(key),item] for key,item in expected_global.items()
                          if reference_global.get(key) != item}
    for source, actual in expected.items():
        reference_material = bpy.data.materials[names.MATERIAL_PREFIX + source.rsplit("_Mat_", 1)[-1]]
        reference = snapshot(reference_material)
        reference_pixels = texture_pixels(reference_material.node_tree)
        pixel_differences = {key:{"upstream":reference_pixels.get(key),"hgt":item}
                             for key,item in expected_pixels[source].items() if item != reference_pixels.get(key)}
        if pixel_differences:
            differences.append({"material":source,"field":"texture_pixels","differences":pixel_differences})
        for field in actual:
            if actual[field] != reference[field]:
                if field == "inputs":
                    changes = {key: [reference[field].get(key), item] for key, item in actual[field].items()
                               if reference[field].get(key) != item}
                else:
                    changes = {"upstream": reference[field], "hgt": actual[field]}
                differences.append({"material": source, "field":field, "differences":changes})
        outline_reference = snapshot(bpy.data.materials[names.MATERIAL_PREFIX + source.rsplit("_Mat_", 1)[-1] + " Outlines"])
        if expected_outlines[source] != outline_reference:
            differences.append({"material":source,"field":"outline", "upstream":outline_reference,
                                "hgt":expected_outlines[source]})
    for mesh_name, source_names in original_slots.items():
        reference = [slot.material.name for slot in bpy.data.objects[mesh_name].material_slots]
        converted = [names.MATERIAL_PREFIX + source.rsplit("_Mat_", 1)[-1] if source.startswith("Avatar_") else source
                     for source in source_names]
        if converted != reference:
            differences.append({"mesh":mesh_name,"field":"material_assignment","upstream":reference,"hgt":converted})

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.view_settings.view_transform = "Standard"
    scene.render.film_transparent = True
    scene.render.resolution_x, scene.render.resolution_y = 512, 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    camera = bpy.data.objects.new("Reference Camera", bpy.data.cameras.new("Reference Camera"))
    scene.collection.objects.link(camera)
    camera.data.type, camera.data.ortho_scale = "ORTHO", camera_scale
    # Copy transform components directly; matrix decomposition can round the
    # camera rotation and change rasterization at otherwise identical edges.
    camera.rotation_mode = camera_rotation_mode
    camera.location, camera.rotation_euler, camera.scale = camera_location, camera_rotation, camera_object_scale
    scene.camera = camera
    bpy.context.view_layer.update()
    errors = []
    for angle, actual in zip((0.65, -1.0), output):
        direction = Vector((math.sin(angle), -math.cos(angle), 0))
        bpy.data.objects["Light Direction"].rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        reference = render(scene, model.stem + "-original-workflow", angle)
        difference = np.abs(actual - reference)
        errors.append({"angle":angle,"max":float(difference.max()),"mean":float(difference.mean()),
                       "changed_fraction":float((difference > 1/255+1e-6).mean())})
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / (model.stem + "-original-workflow.blend")), relative_remap=False)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    control_errors = {key:float(np.abs(np.array(expected_controls[key]) -
                                      np.array(bpy.data.objects[key].evaluated_get(depsgraph).matrix_world)).max())
                      for key in keys}
    camera_error = float(np.abs(np.array(camera_matrix) - np.array(camera.matrix_world)).max())
    reference_geometry = geometry(scene, original_slots)
    geometry_errors = {}
    for name, data in expected_geometry.items():
        for field, actual in data.items():
            reference = reference_geometry[name].get(field)
            if reference is None or reference.shape != actual.shape:
                geometry_errors[name + "/" + field] = "different shape or missing"
            elif actual.size and not np.array_equal(actual, reference):
                geometry_errors[name + "/" + field] = float(np.abs(actual-reference).max())
    report = {"model":model.stem,"material_differences":differences,"render_errors":errors,
              "modifier_inputs":{"upstream":modifiers(scene),"hgt":expected_modifiers},
              "control_matrix_errors":control_errors,"global_input_differences":global_differences,
              "evaluated_geometry_differences":geometry_errors,"camera_matrix_error":camera_error}
    reports.append(report)
    core_names = json.loads((ROOT / ".verification/original/fbx-verification.json").read_text(encoding="utf-8"))["core_sha256"]
    # Structural, input and evaluated-geometry equality is mandatory. Keep
    # raster differences visible; distinct material programs can differ by a
    # few 8-bit steps at a tiny number of edges. This is not pixel equality.
    limits = {"max":4/255+1e-6, "mean":1e-5, "changed_fraction":1e-4}
    pixel_exact = all(error["max"] == 0 for item in reports for error in item["render_errors"])
    comparison_passed = all(not item["material_differences"] and not item["global_input_differences"]
                            and all(error[key] <= limit for error in item["render_errors"] for key,limit in limits.items())
                            and max(item["control_matrix_errors"].values()) == 0
                            and not item["evaluated_geometry_differences"] and item["camera_matrix_error"] == 0
                            for item in reports)
    (OUT / "upstream-workflow.json").write_text(json.dumps({"models":reports,"executed_original_sources":executed,
                                                           "comparison_passed":comparison_passed,
                                                           "pixel_exact":pixel_exact,"render_acceptance_limits":limits,
                                                           "core_sha256":{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in core_names},
                                                           "v3_material_names_compatibility":args.compat_v3_names,
                                                           "same_local_lookup_inputs":args.local_inputs,
                                                           "outlines_disabled":args.no_outlines},
                                                           ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("HGT_UPSTREAM_WORKFLOW", json.dumps({"model":model.stem,"render_errors":errors,
          "material_difference_count":len(differences),"geometry_differences":geometry_errors,
          "control_matrix_errors":control_errors,"camera_matrix_error":camera_error}, ensure_ascii=False), flush=True)
addon.unregister()
if not args.audit_only and not comparison_passed:
    raise AssertionError("Independent original workflow comparison differs; inspect upstream-workflow.json")
