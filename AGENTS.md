# Hoyo-GI-Toon

## 产品与当前范围

- 遵循上级 `../AGENTS.md`；本项目是独立的原神角色渲染插件，不继承 MAVR 或 Kimodo 的项目授权与验证结果。
- 用户于 2026-10-28 明确要求在本目录开发、通过 GitHub 交付，并为本地 Blender 配置远程更新。
- 用户随后明确纠正实现方向：先复刻参考仓库及其配套原版 Shader 的结构、材质和处理流程，不自行设计替代着色或扩展效果。固定上游版本，直接使用其原生节点库；仅适配当前 Blender API、角色归属与既定简洁入口。
- 首版只完成 FBX 角色流程，实际跑通后再接入 PMX；两种格式始终使用同一个导入入口，以文件后缀分派适配器。
- 按当前稳定 Blender API 开发。版本信息保留在扩展元数据和维护资料中，不在产品面板反复展示。
- 面板简洁实用，不展示“默认”“自动”“XX 已提供”等无须用户决策的信息。只有缺失、歧义和错误需要提示，常用外观参数直接提供调节。
- 用户选择模型文件后，从模型目录及有关联的资源目录解析贴图、材质 JSON 和引用；不要求逐个选择纹理，不在无关目录或其他角色资源中猜测匹配。
- 后续 PMX 通过 MMD Tools 导入：显式启用 `fix_bone_order`，导入后调用 `fix_bone_issues` 并检查结果，保留原骨名别名。修复限于本次导入的模型，不裁剪骨架或替代骨轴、拓扑校准。

## 实现约束

- 角色、材质、描边、控制对象均记录归属；重建更新本插件已有数据，不按全场景第一个骨架或固定对象名称定位。
- 保留原材质引用、骨架、形态键、UV 和导入法线。只修改当前角色及本插件创建的资源，不删除其他场景对象或节点。
- 文件自动匹配要有明确依据，遇到同分歧义或关键资源缺失时给出可操作错误；不吞异常或以空白材质伪装成功。
- 引擎 API 与文件格式隔离。着色核心直接使用固定原版节点库，原版基线及当前 API 适配以 `docs/upstream-baseline.md` 为准；原始角色、贴图、外部验证工程和个人路径不进入发布仓库或安装包。
- 独立验证数据放在忽略的 `.verification/`；不覆盖用户工程。实际 FBX、程序化夹具和未执行的检查分别记录，不将夹具冒充游戏模型实测。

## 交付

- 源码、构建脚本、文档、发布索引归入本目录。扩展 ID 为 `hoyo_gi_toon`。
- GitHub 仓库为当前用户账号下的同名公开项目；发布索引放在 `release/index.json`，包从对应版本标签下的固定 ZIP 获取，Release 正文提供下载入口。
- 构建检查 Python 语法、清单、精确包内容、CRC 和 SHA256。已发布版本不可覆盖，载荷变化须递增版本。
- 本地配置仅新增或更新本项目远程扩展仓库，不覆盖其他插件配置，不关闭或改写用户当前工程。
- 用户指定奥黛塔、尼可的本地原始游戏 FBX 交叉验证。v0.1.0 的基础着色验证保存在 `.verification/fbx-verification.json` 和 `lifecycle.json`，仅作旧版历史证据。
- v0.2.0 改用 Festivity v3.4 原版节点和 Setup Wizard v3 参数映射。当前验证保存在 `.verification/original/`，包括 `fbx-verification.json`、`lifecycle.json`、`original-conformance.json`。原版结构核对与同装配器渲染比较不等于完整原版安装向导运行，更不等于游戏画面逐项复现。PMX 后续接入。
- 公开仓库为 `https://github.com/muchuanhehua/Hoyo-GI-Toon`；历史 v0.1.0 标签源码为 `933d9c5ddfc0243414991ccc9ea576b87eacd8db`，旧包与标签不覆盖。
- 历史 v0.1.0 ZIP SHA256 为 `e57a724fc0f64346198696df2acd0b46fee05aee8e5785b9f4502fb209721112`，初次远程安装与新进程核验通过；旧安装证据保存在 `.verification/installed.json` 与 `installed-fresh-process.json`。
- 本地模块为 `bl_ext.Hoyo_GI_Toon.hoyo_gi_toon`。配置入口为 `tools/configure_installed.py`；`--check-only` 只读核验已安装文件与持久配置。
- 当前发布为 v0.2.1，固定标签源码 `fbf24f70f1d14a62f3f048b776773777f814d991`，安装包 SHA256 为 `bdcacd9965cdb61d1e9854bc9436a08a8833f3ce6cb5cee9099243bf269c39d3`。19 个安装文件与标签源码逐一一致。v0.2.0 及 v0.1.0 均保留。
- v0.2.1 已从公开更新源安装，本地启用和新进程 19 文件核验通过；当前安装证据在 `.verification/original/installed.json` 与 `installed-fresh-process.json`。当前 Blender 的远程通道断开，未完成当前会话热加载；不将新进程核验表述为当前会话已加载新版。
