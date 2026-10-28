"""Compare bundled graphs and applied parameters with the pinned upstream code."""
import argparse
import ast
from abc import ABC, abstractmethod
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".verification/original"
OUT.mkdir(parents=True, exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument("--model", action="append", type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])


def normalized(value):
    if isinstance(value, bpy.types.ID):
        return None
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    return list(value)


def socket_value(socket):
    return normalized(socket.default_value) if hasattr(socket, "default_value") else None


def signature(tree):
    nodes = []
    for node in tree.nodes:
        settings = {}
        for prop in node.bl_rna.properties:
            if prop.type in {"BOOLEAN", "INT", "FLOAT", "ENUM", "STRING"} and not prop.is_readonly:
                if prop.identifier in {"name", "label", "location", "width", "height", "dimensions", "color",
                                       "select", "hide", "show_texture", "show_options", "show_preview", "use_custom_color"}:
                    continue
                settings[prop.identifier] = normalized(getattr(node, prop.identifier))
        settings["inputs"] = [(s.identifier, socket_value(s)) for s in node.inputs]
        settings["outputs"] = [(s.identifier, socket_value(s)) for s in node.outputs]
        if node.type == "GROUP":
            settings["group"] = node.node_tree.get("hgt_upstream", node.node_tree.name)
        if hasattr(node, "color_ramp"):
            settings["ramp"] = [(e.position, list(e.color)) for e in node.color_ramp.elements]
        nodes.append((node.name, node.bl_idname, settings))
    links = sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in tree.links)
    return {"nodes":sorted(nodes), "links":links,
            "interface":[(s.name, s.in_out, s.socket_type, socket_value(s)) for s in tree.interface.items_tree if s.item_type == "SOCKET"]}


def snapshot():
    return {"groups":{g.get("hgt_upstream",g.name):signature(g) for g in bpy.data.node_groups},
            "materials":{m.get("hgt_upstream",m.name):signature(m.node_tree) for m in bpy.data.materials}}


bpy.ops.wm.read_factory_settings(use_empty=True)
for path in sorted((ROOT / ".verification/upstream/shader").glob("*.blend")):
    with bpy.data.libraries.load(str(path)) as (source,target):
        target.materials, target.node_groups = source.materials, source.node_groups
raw = snapshot()
for item in (*bpy.data.node_groups, *bpy.data.materials):
    item["hgt_upstream"] = item.name
reference = OUT / "reference_library.blend"
bpy.data.libraries.write(str(reference), set(bpy.data.node_groups) | set(bpy.data.materials), fake_user=True, compress=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
with bpy.data.libraries.load(str(ROOT / "assets/original_shader.blend")) as (source,target):
    target.materials, target.node_groups = source.materials, source.node_groups
assert not bpy.data.images, "Package contains texture assets"
assert not bpy.data.objects, "Package contains preview models"
assert snapshot() == raw, "Bundled node formulas, constants or links differ from upstream"

# Execute the original applier classes themselves as the parameter oracle.
source = ROOT / ".verification/upstream/wizard/setup_wizard/material_data_import_setup/material_data_applier.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
classes = [n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in
           {"MaterialDataApplier", "V2_MaterialDataApplier", "V3_MaterialDataApplier"}]
oracle = {"bpy":bpy, "ABC":ABC, "abstractmethod":abstractmethod, "Material":bpy.types.Material,
          "OutlineMaterialGroup":SimpleNamespace, "V2_HSR_MaterialDataApplier":type("unused",(),{}),
          "V3_BonnyFestivityGenshinImpactMaterialNames":SimpleNamespace(FACE="reference-face")}
exec(compile(ast.Module(body=classes,type_ignores=[]),str(source),"exec"),oracle)
spec = importlib.util.spec_from_file_location("hoyo_gi_toon",ROOT / "__init__.py",submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
shader = addon.workflow.shaders


def digest(values):
    return hashlib.sha256(np.asarray(values,dtype=np.float32).tobytes()).hexdigest()


def mesh_data(mesh):
    data = mesh.data
    return {"vertices":digest([x for v in data.vertices for x in v.co]),
            "polygons":[tuple(p.vertices) for p in data.polygons],
            "weights":[[(g.group,g.weight) for g in v.groups] for v in data.vertices],
            "uvs":{u.name:digest([x for c in u.data for x in c.uv]) for u in data.uv_layers},
            "normals":digest([x for n in data.corner_normals for x in n.vector]),
            "vertex_colors":[digest([x for c in a.data for x in c.color]) for a in data.color_attributes],
            "shapes":{k.name:digest([x for v in k.data for x in v.co]) for k in data.shape_keys.key_blocks} if data.shape_keys else {}}


def check_parameters(root, catalog):
    checked = 0
    for binding in root.hgt_character.bindings:
        material, outline = binding.generated, binding.outline
        assets = catalog.resolve(binding.source_name)
        expected, expected_outline = material.copy(), outline.copy()
        kind = material["hgt_template"]
        part=binding.source_name.rsplit('_Mat_',1)[-1]
        if part in {'Face','Eye','Pupil'}:
            expected.use_screen_refraction=True  # Original replacer's setter.
            assert material.use_screen_refraction==expected.use_screen_refraction
        if part == 'Pupil':
            assert kind == 'Body', 'Original Pupil must use Body template'
            body=catalog.resolve(binding.source_name.rsplit('_Mat_',1)[0]+'_Mat_Body')
            assert assets.textures['diffuse']==body.textures['diffuse']
        if part in {'Face','Brow','Eye'}:
            assert kind == 'Face', 'Original Face/Brow/Eye must use Face template'
        expected.name = 'Reference ' + kind
        node_name = "Face Shader" if kind == "Face" else "Body Shader"
        # Reset exposed inputs to raw upstream defaults before the oracle runs.
        baseline = next(m for m in raw['materials'] if m.endswith(' ' + kind))
        upstream_node = next(n for n in raw['materials'][baseline]['nodes'] if n[0] == node_name)
        defaults = dict(upstream_node[2]['inputs'])
        mapping = oracle['V3_MaterialDataApplier'].face_material_mapping if kind=='Face' else {
            **oracle['V3_MaterialDataApplier'].local_material_mapping,
            **oracle['V3_MaterialDataApplier'].additional_local_material_mapping}
        names = set(mapping.values()) | {'Use Alpha','0 = Emission, 1 = Transparency'}
        for socket in expected.node_tree.nodes[node_name].inputs:
            if socket.name in names and defaults.get(socket.identifier) is not None:
                socket.default_value = defaults[socket.identifier]
        outline_defaults=dict(next(n for n in raw['materials']['HoYoverse - Genshin Outlines']['nodes'] if n[0]=='Outlines')[2]['inputs'])
        outline_names=set(oracle['V3_MaterialDataApplier'].outline_mapping.values()) | {'Use Alpha'}
        for socket in expected_outline.node_tree.nodes['Outlines'].inputs:
            if socket.name in outline_names:
                socket.default_value=outline_defaults[socket.identifier]
        color_values = {k:tuple(v[x] for x in ('r','g','b','a')) for k,v in assets.colors.items()}
        params = SimpleNamespace(m_floats=SimpleNamespace(**assets.floats), m_colors=SimpleNamespace(**color_values),
                                 m_texEnvs=SimpleNamespace(**assets.texenvs))
        oracle['V3_BonnyFestivityGenshinImpactMaterialNames'].FACE = expected.name if kind=='Face' else 'reference-face'
        applier = oracle['V3_MaterialDataApplier'](params,SimpleNamespace(material=expected,outlines_material=expected_outline,night_soul_outlines_material=None))
        with redirect_stdout(io.StringIO()) as captured:
            applier.set_up_mesh_material_data()
        for a,b in ((material.node_tree.nodes[node_name],expected.node_tree.nodes[node_name]),
                    (outline.node_tree.nodes['Outlines'],expected_outline.node_tree.nodes['Outlines'])):
            for socket in a.inputs:
                assert socket_value(socket)==socket_value(b.inputs[socket.identifier]), (assets.source,socket.name)
                checked += 1
        bpy.data.materials.remove(expected)
        bpy.data.materials.remove(expected_outline)
    return checked


def render_pair(root, stem):
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = 512, 640
    result=[]
    for angle in (0.65,-1.0):
        root.hgt_character.light_azimuth = angle
        path = OUT / f"{stem}-{angle}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(path),check_existing=False)
        result.append(np.asarray(image.pixels[:],dtype=np.float32))
        bpy.data.images.remove(image)
    return result


models=[]
for model in args.model:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    imported = addon.workflow.importers.import_character(str(model))
    original_meshes = {o.name:mesh_data(o) for o in imported if o.type=='MESH'}
    original_transforms={o.name:[list(r) for r in o.matrix_world] for o in imported if o.type=='MESH'}
    armature = next(o for o in imported if o.type=='ARMATURE')
    bones = {b.name:[list(r) for r in b.matrix_local] for b in armature.data.bones}
    bpy.ops.wm.read_factory_settings(use_empty=True)
    root=addon.workflow.build(str(model),bpy.context)
    for entry in root.hgt_character.meshes:
        assert mesh_data(entry.object)==original_meshes[entry.object.name], entry.object.name
        assert [list(r) for r in entry.object.matrix_world]==original_transforms[entry.object.name], entry.object.name
    armature = next(o for o in root.children_recursive if o.type=='ARMATURE')
    assert bones=={b.name:[list(r) for r in b.matrix_local] for b in armature.data.bones}
    parameters=check_parameters(root,addon.workflow.AssetCatalog(str(model)))
    bundled=render_pair(root,model.stem+'-bundled')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    saved=shader.LIBRARY_PATH
    shader.LIBRARY_PATH=reference
    root=addon.workflow.build(str(model),bpy.context)
    upstream=render_pair(root,model.stem+'-upstream')
    shader.LIBRARY_PATH=saved
    differences=[float(np.max(np.abs(a-b))) for a,b in zip(bundled,upstream)]
    assert max(differences)<=1/255+1e-6, differences
    models.append({"model":model.stem,"structure_preserved":True,"oracle_socket_checks":parameters,
                   "upstream_render_max_error":differences})
report={"upstream_graphs_equal":True,"groups":len(raw['groups']),"materials":len(raw['materials']),
        "game_assets_excluded":True,"models":models,
        "scope":"Pinned original v3.4 graphs and original v3 material applier; same adapter and controls for render comparison"}
core=json.loads((OUT/'fbx-verification.json').read_text(encoding='utf-8'))['core_sha256']
report['core_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in core}
(OUT / 'original-conformance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('HGT_ORIGINAL',json.dumps(report,ensure_ascii=False),flush=True)
addon.unregister()
