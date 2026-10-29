"""Install or verify only this project's remote Blender extension."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import bpy
import addon_utils

URL = "https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/main/release/index.json"
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    prefs = bpy.context.preferences
    before_addons = set(prefs.addons.keys())
    before_repos = {repo.module: repo.remote_url for repo in prefs.extensions.repos}
    matches = [(i, repo) for i, repo in enumerate(prefs.extensions.repos) if repo.remote_url == URL]
    if not matches:
        if args.check_only:
            raise RuntimeError("Hoyo-GI-Toon 远程仓库尚未配置")
        result = bpy.ops.preferences.extension_repo_add(name="Hoyo-GI-Toon", remote_url=URL,
                                                        use_sync_on_startup=True)
        if result != {"FINISHED"}:
            raise RuntimeError("远程仓库创建未完成")
        matches = [(i, repo) for i, repo in enumerate(prefs.extensions.repos) if repo.remote_url == URL]
    if len(matches) != 1:
        raise RuntimeError("远程仓库配置存在歧义")
    index, repo = matches[0]
    if not args.check_only:
        if bpy.ops.extensions.repo_sync(repo_index=index) != {"FINISHED"}:
            raise RuntimeError("Hoyo-GI-Toon 仓库同步未完成")
        if bpy.ops.extensions.package_install(repo_index=index, pkg_id="hoyo_gi_toon", enable_on_install=True) != {"FINISHED"}:
            raise RuntimeError("Hoyo-GI-Toon 安装未完成")
    module_name = f"bl_ext.{repo.module}.hoyo_gi_toon"
    if module_name not in prefs.addons:
        raise RuntimeError("Hoyo-GI-Toon 未启用")
    addon = importlib.import_module(module_name)
    installed = Path(addon.__file__).resolve().parent
    manifest = json.loads((ROOT / "release/index.json").read_text(encoding="utf-8"))["data"][0]
    record = json.loads((ROOT / f"release/build-v{manifest['version']}.json").read_text(encoding="utf-8"))
    registered_version = '.'.join(map(str, addon_utils.module_bl_info(addon)['version']))
    if registered_version != manifest['version']:
        raise RuntimeError('已加载版本与发布版本不一致：' + registered_version)
    for name, expected in record["payload"].items():
        if hashlib.sha256((installed / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError("安装文件与发布包不一致：" + name)
    if not before_addons <= set(prefs.addons.keys()):
        raise RuntimeError("原有插件启用状态发生变化")
    for module, remote_url in before_repos.items():
        found = next((r for r in prefs.extensions.repos if r.module == module), None)
        if not found or found.remote_url != remote_url:
            raise RuntimeError("原有远程仓库配置发生变化")
    if not args.check_only:
        bpy.ops.wm.save_userpref()
    report = {"version":manifest["version"], "module":module_name, "repository":URL,
              "registered_version":registered_version,
              "directory":str(installed), "payload_files_verified":len(record["payload"]),
              "existing_preferences_preserved":True, "fresh_process":args.check_only}
    directory = (args.output_dir or ROOT / '.verification/original').resolve()
    if not directory.is_relative_to(ROOT / '.verification'):
        raise ValueError('安装验证记录须保存在项目 .verification 目录')
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / ('installed-fresh-process.json' if args.check_only else 'installed.json')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("HGT_INSTALLED", json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
