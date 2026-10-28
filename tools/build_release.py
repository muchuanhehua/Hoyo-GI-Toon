"""Build and validate the extension from the verified source payload."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = {"__init__.py", "asset_resolver.py", "importers.py", "properties.py", "shaders.py",
           "asset_tracking.py", "lighting.py",
           "outlines.py", "workflow.py", "panels.py", "post_processing.py", "upstream_mapping.py",
           "assets/original_shader.blend", "assets/original_controls.blend", "assets/upstream.json",
           "blender_manifest.toml", "README.md", "CHANGELOG.md", "LICENSE", "NOTICE",
           "docs/upstream-baseline.md"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    args = parser.parse_args()
    manifest = tomllib.loads((ROOT / "blender_manifest.toml").read_text(encoding="utf-8"))
    for name in PAYLOAD:
        if name.endswith(".py"):
            ast.parse((ROOT/name).read_text(encoding="utf-8"), filename=name)
    tree = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
    info = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign) and
                                any(isinstance(t, ast.Name) and t.id == "bl_info" for t in n.targets)))
    if ".".join(map(str, info["version"])) != manifest["version"]:
        raise ValueError("Version metadata mismatch")
    evidence = json.loads(args.verification.read_text(encoding="utf-8"))
    required = {"fresh_package_process", "register_unregister", "save_reload", "undo_redo"}
    integration = evidence.get("integration_checks", {})
    if evidence.get("scope") != "01–08" or not all(integration.get(k) is True for k in required):
        raise ValueError("需要 08 集成验证记录；01–05 模块记录不能作为发布依据")
    hashes = {**evidence["source_sha256"], **evidence["resource_sha256"]}
    runtime = {name for name in PAYLOAD if name.endswith(".py") or name.startswith("assets/")}
    if set(hashes) != runtime:
        raise ValueError("Verification does not cover the exact runtime payload")
    for name, expected in hashes.items():
        if sha((ROOT/name).read_bytes()) != expected:
            raise ValueError("Source changed after verification: " + name)
    flags = ("source_data_unchanged", "derived_geometry_unchanged", "original_mesh_refs_restored",
             "head_follow", "repeat_assembly", "restore_reassembly", "shared_data_preserved")
    if len(evidence["models"]) < 2 or not all(all(m.get(k) is True for k in flags) for m in evidence["models"]):
        raise ValueError("Data protection verification is incomplete")
    if sum(len(m.get("renders", [])) for m in evidence["models"]) < 4 or not all(evidence["lifecycle"].values()):
        raise ValueError("Render and lifecycle verification is incomplete")
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    package = release / f"{manifest['id']}-{manifest['version']}.zip"
    if package.exists():
        raise ValueError("Do not overwrite an existing release archive: " + package.name)
    command = [str(args.blender), "--background", "--factory-startup", "--command", "extension"]
    subprocess.run([*command, "build", "--source-dir", str(ROOT), "--output-filepath", str(package)], check=True)
    subprocess.run([*command, "validate", str(package)], check=True)
    with zipfile.ZipFile(package) as archive:
        if archive.testzip() or set(archive.namelist()) != PAYLOAD:
            raise ValueError("Unexpected archive payload or failed CRC")
        for name in PAYLOAD:
            if archive.read(name) != (ROOT/name).read_bytes():
                raise ValueError("Packaged bytes differ: " + name)
    digest = sha(package.read_bytes())
    payload = {name:sha((ROOT/name).read_bytes()) for name in sorted(PAYLOAD)}
    record = {"version": manifest["version"], "archive": package.name, "sha256": digest,
              "bytes": package.stat().st_size, "payload": payload, "core_sha256": hashes}
    (release / f"build-v{manifest['version']}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    item = {k:v for k,v in manifest.items() if k != "build"}
    item.update(archive_url=f"https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/v{manifest['version']}/release/{package.name}",
                archive_size=package.stat().st_size, archive_hash="sha256:"+digest)
    (release / "index.json").write_text(json.dumps({"version":"v1", "blocklist":[], "data":[item]}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    fields = ("name", "objects", "meshes", "armatures", "materials", *flags)
    summary = {"models":[{k:m[k] for k in fields} for m in evidence["models"]],
               "lifecycle":evidence["lifecycle"], "core_sha256":hashes,
               "integration_checks":integration, "scope":"基础 FBX 导入、数据保护与原生角色渲染"}
    (release / f"verification-v{manifest['version']}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("HGT_BUILD", package.name, digest, len(payload), flush=True)


if __name__ == "__main__":
    main()
