"""Extract Festivity v3 parameter mappings verbatim from the pinned wizard."""
import ast
from pathlib import Path
import pprint

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / ".verification/upstream/wizard/setup_wizard/material_data_import_setup/material_data_applier.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
version = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "V3_MaterialDataApplier")
names = {"face_material_mapping":"FACE_MAPPING", "outline_mapping":"OUTLINE_MAPPING",
         "local_material_mapping":"MATERIAL_MAPPING", "additional_local_material_mapping":"ADDITIONAL_MAPPING"}
result = [
    '"""Parameter mappings from michael-gh1 Setup Wizard, GPL-3.0.',
    '',
    'Source: material_data_import_setup/material_data_applier.py',
    'Commit: fb942ecc30d9ed3889f5afb0dfb3a23c13601a54',
    'Extracted by tools/build_upstream_mappings.py; no shader formulas are replaced.',
    '"""', '',
]
for node in version.body:
    if isinstance(node, ast.Assign) and node.targets[0].id in names:
        result += [names[node.targets[0].id] + " = " + pprint.pformat(ast.literal_eval(node.value), sort_dicts=False), ""]
result += ['ALPHA_MAPPING = {0: {"Use Alpha": 0, "0 = Emission, 1 = Transparency": 0},',
           '                 1: {"Use Alpha": 1, "0 = Emission, 1 = Transparency": 1},',
           '                 2: {"Use Alpha": 1, "0 = Emission, 1 = Transparency": 0}, 3: {}}', '']
(ROOT / "upstream_mapping.py").write_text("\n".join(result), encoding="utf-8", newline="\n")
print("Original v3 parameter mappings extracted")
