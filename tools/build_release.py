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
           "outlines.py", "workflow.py", "panels.py", "post_processing.py", "upstream_mapping.py",
           "assets/original_shader.blend", "assets/original_controls.blend", "assets/upstream.json",
           "blender_manifest.toml", "README.md", "CHANGELOG.md", "LICENSE", "NOTICE",
           "docs/upstream-baseline.md"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", type=Path, required=True)
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
    evidence = json.loads((ROOT / ".verification/original/fbx-verification.json").read_text(encoding="utf-8"))
    lifecycle = json.loads((ROOT / ".verification/original/lifecycle.json").read_text(encoding="utf-8"))
    original = json.loads((ROOT / ".verification/original/original-conformance.json").read_text(encoding="utf-8"))
    if len(evidence["models"]) != 2 or not all(lifecycle.values()):
        raise ValueError("Actual two-model and lifecycle verification is required")
    for name, expected in evidence["core_sha256"].items():
        if sha((ROOT/name).read_bytes()) != expected:
            raise ValueError("Source changed after verification: " + name)
    if original['core_sha256'] != evidence['core_sha256'] or not original['upstream_graphs_equal']:
        raise ValueError("Current-source original conformance verification is required")
    if len(original['models']) != 2 or any(not m['structure_preserved'] or max(m['upstream_render_max_error']) > 1/255+1e-6 for m in original['models']):
        raise ValueError("Original model/render comparison is incomplete")
    if not all(m["visual_content_checks"] and m["source_preserved"] and m["material_restore"] for m in evidence["models"]):
        raise ValueError("Model verification incomplete")
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
              "bytes": package.stat().st_size, "payload": payload, "core_sha256": evidence["core_sha256"]}
    (release / f"build-v{manifest['version']}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    item = {k:v for k,v in manifest.items() if k != "build"}
    item.update(archive_url=f"https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/v{manifest['version']}/release/{package.name}",
                archive_size=package.stat().st_size, archive_hash="sha256:"+digest)
    (release / "index.json").write_text(json.dumps({"version":"v1", "blocklist":[], "data":[item]}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    summary = {"models":[{k:m[k] for k in ("model", "format", "meshes", "bindings", "source_preserved", "shape_keys_preserved", "refresh_idempotent", "material_restore", "visual_content_checks")} for m in evidence["models"]],
               "lifecycle":lifecycle, "core_sha256":evidence["core_sha256"],
               "original_conformance":{k:v for k,v in original.items() if k != 'core_sha256'},
               "scope":"固定原版 v3.4 节点与参数映射；原始库和打包库使用相同装配器对照，不代表游戏画面完整复现"}
    (release / f"verification-v{manifest['version']}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("HGT_BUILD", package.name, digest, len(payload), flush=True)


if __name__ == "__main__":
    main()
