"""Fetch the pinned, GPL-licensed reference sources; never fetch game assets."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SHADER_COMMIT = "b79f0f3fb47b4de2b6d187ee6b66d93cb965968d"
WIZARD_COMMIT = "fb942ecc30d9ed3889f5afb0dfb3a23c13601a54"
SHADERS = (
    "HoYoverse - Genshin Impact v3.4.blend",
    "HoYoverse - Genshin Impact Outlines v3.blend",
    "HoYoverse - Genshin Impact Post-Processing.blend",
    "LICENSE", "README.md",
)
WIZARD = (
    "README.md", "LICENSE", "setup_wizard/README.md",
    "setup_wizard/material_data_import_setup/material_data_applier.py",
    "setup_wizard/material_data_import_setup/game_material_data_importers.py",
    "setup_wizard/texture_import_setup/texture_importer_types.py",
    "setup_wizard/texture_import_setup/texture_node_names.py",
    "setup_wizard/texture_import_setup/material_default_value_setters.py",
    "setup_wizard/texture_import_setup/outline_texture_importers.py",
    "setup_wizard/texture_import_setup/game_texture_importers.py",
    "setup_wizard/material_import_setup/game_material_importers.py",
    "setup_wizard/domain/shader_material_names.py",
    "setup_wizard/domain/shader_node_names.py",
    "setup_wizard/domain/body_hair_ramp_switch_values.py",
    "setup_wizard/utils/genshin_body_part_deducer.py",
    "setup_wizard/geometry_nodes_setup/geometry_nodes_setups.py",
    "setup_wizard/outline_import_setup/outline_importers.py",
    "setup_wizard/genshin_import_character_model.py",
    "setup_wizard/set_up_head_driver.py",
    "setup_wizard/genshin_compositing_node_setup.py",
    "setup_wizard/character_rig_setup/LightingPanel_Shader_v3_4.blend",
    "setup_wizard/character_rig_setup/lighting_panel_setup.py",
    "setup_wizard/geometry_nodes_setup/lighting_panel_names.py",
    "setup_wizard/replace_default_materials_setup/game_default_material_replacers.py",
    "setup_wizard/config_ui.json",
    "setup_wizard/import_order.py",
    "setup_wizard/domain/game_types.py",
    "setup_wizard/domain/shader_identifier_service.py",
    "setup_wizard/domain/shader_material_name_keywords.py",
    "setup_wizard/domain/shader_material.py",
    "setup_wizard/domain/star_cloak_types.py",
    "setup_wizard/domain/vfx_shader_types.py",
    "setup_wizard/texture_import_setup/original_texture_locator_utils.py",
    "setup_wizard/material_import_setup/empty_names.py",
    "setup_wizard/outline_import_setup/outline_node_groups.py",
)


def fetch(item):
    repository, commit, relative, folder = item
    url = f"https://raw.githubusercontent.com/{repository}/{commit}/{quote(relative)}"
    target = ROOT / ".verification/upstream" / folder / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with urlopen(url, timeout=90) as response:
            target.write_bytes(response.read())
    return {"repository": repository, "commit": commit, "path": relative,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "bytes": target.stat().st_size}


if __name__ == "__main__":
    items = [("festivities/Blender-miHoYo-Shaders", SHADER_COMMIT, path, "shader") for path in SHADERS]
    items += [("michael-gh1/Addons-And-Tools-For-Blender-miHoYo-Shaders", WIZARD_COMMIT, path, "wizard") for path in WIZARD]
    with ThreadPoolExecutor(max_workers=4) as executor:
        records = list(executor.map(fetch, items))
    output = ROOT / ".verification/upstream/downloads.json"
    output.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(f"Pinned upstream: {len(records)} files, {sum(r['bytes'] for r in records)} bytes")
