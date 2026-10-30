# Hoyo-GI-Toon 开发进度

更新时间：2026-10-30 15:40，Asia/Shanghai。

目标是还原原神角色的游戏内材质表现，服务 MMD 流程。当前聚焦 PMX 通用材质和已有场景接入，逐角色材质适配最后进行。

## 当前状态

- 当前版本修正为 2.1.0：删除自定义输出区，主要操作直接铺开；已有 MMD 模型可以直接应用材质，打光、相机与原生渲染独立使用。
- 源码和实际 ZIP 验证通过，已发布 [2.1.0](https://github.com/muchuanhehua/Hoyo-GI-Toon/releases/tag/v2.1.0) 并通过远程仓库更新本机 Blender。操作和游戏外观等待用户验收。
- 冻结包为 `release/hoyo_gi_toon-2.1.0.zip`，651,227 字节、31 文件；SHA256 `adf83558dba55accfcff546a8435cc7f999b55806d48e7cbaf998c70b114644d`。与已安装复验的候选逐字节一致。
- 原始证据位于忽略目录 `.verification/development/scene-workflow-210/`；实际 ZIP 的报告为 `candidate/pmx-modules.json`、`candidate-ui/interface.json`，汇总为 `verification.json`，检查点为 `checkpoint.json`。公开摘要见 [候选记录](candidate-v2.1.0.json)。
- 发布和本机更新记录位于 `.verification/release-v2.1.0/`，公开摘要见 [交付记录](delivery-v2.1.0.json)。远程实际下载、31 安装文件、新进程注册、原有插件启用、仓库和启动文件均已核对；旧版本安装和偏好已备份。
- 已打开 2.1.0 Blender 的完整面板供用户继续操作，当前用户工程不转换、不关闭。[面板对照与验证工程](../.verification/development/scene-workflow-210/review/README.md) 保存在私有验证目录。

## 本轮清单

用户在 2.0.0 实测后明确要求删除输出、铺开面板，并支持场景已有模型，按 M09–M12 实施。

| 编号 | 内容 | 实际检查 | 状态 |
|---|---|---|---|
| M09 | 删除重复输出功能，铺开面板 | 空场景和已有模型均显示材质、灯光、相机和渲染入口；没有自定义输出区或折叠分区 | 自检通过，待用户验收 |
| M10 | 已有 MMD 模型接入 | 三份原生 MMD Tools 导入模型直接应用材质，不重新导入或修骨；源数据与 MMD 元数据保持 | 自检通过，待用户验收 |
| M11 | 独立灯光、相机与原生渲染 | 空场景可打光和创建相机；使用场景相机、完整场景和 Render Result，原生输出设置保留 | 自检通过，待用户验收 |
| M12 | 验证和交付 | 打包贴图、2.0 工程、参数差分、骨骼与顶点 Morph 动画、失败回滚、恢复、保存重开、撤销和实际 ZIP 安装 | 已发布并安装 2.1.0，待用户操作验收 |

## 用户流程

已有模型：选中角色网格、骨架或 MMD 根 → 应用材质 → 调材质、灯光与相机 → 原生渲染。

新模型：导入 PMX → 应用材质 → 调整 → 原生渲染。导入自动修骨；已有模型接入不重复修骨。导入仅在场景没有相机时创建相机，构图由用户设置。

图片尺寸、保存和动画渲染使用 Blender 原生功能。材质应用同步 Eevee／Standard 的 Toon 条件，原相机、输出设置和合成设置保留。表情与动作继续通过 MMD Tools／Blender 管理。

## 模块边界

| 模块 | 文件 | 职责 |
|---|---|---|
| 场景模型 | `scene_models.py` | MMD 根、骨架、网格识别；选择同步与材质恢复记录 |
| 可选导入 | `importers.py`、`mmd_importer.py` | 新 PMX 导入与骨骼修复 |
| 资产保护 | `asset_tracking.py`、`project_io.py` | 源数据、资源摘要、失败回滚、恢复与已有工程接入 |
| 材质 | `material_assets.py`、`pmx_materials.py`、`shaders.py`、`node_graph.py`、`sampling.py` | 原材质与打包贴图引用、PMX 语义、原生节点 |
| 参数与描边 | `material_controls.py`、`outlines.py` | 全局阴影描边、逐材质颜色、重置 |
| 光照与视线 | `lighting.py`、`gaze.py` | 场景太阳光、材质光向、实时眼球跟随 |
| 编排与界面 | `workflow.py`、`properties.py`、`panels.py` | 已有模型和可选导入共用材质链路，直接展开的面板 |
| 原生渲染 | `rendering.py` | 当前场景相机、Toon 兼容条件及 Blender 原生渲染 |

## 验证边界与后续

源码与实际 ZIP 分别验证安柏、纳西妲、奥黛塔。三份原生导入模型不带插件导入标记；奥黛塔使用工程打包贴图。已有 2.0.0 纳西妲工程可直接继续使用。场景其他物件参与原生渲染，原生输出路径不被插件写入。源文件、源数据和 MMD 元数据核对通过，保存重开的 PNG 严格像素一致。

完整 VMD、材质／组 Morph 和物理演出尚未验证；游戏外观仍需用户对照截图验收。发布或安装不代表这些项目已通过。

先完成本轮操作与共用材质外观验收，再处理 MMD 演出链路。逐角色材质逐一适配放在最后。FBX 与附件管理暂不恢复。

2.0.0 的 M01–M08 和原出图流程由 [发布标签](https://github.com/muchuanhehua/Hoyo-GI-Toon/tree/v2.0.0) 与 [交付记录](delivery-v2.0.0.json) 保留；更早的 FBX 和旧功能见 [1.0.1 保留记录](legacy-v1.0.1.md)。历史记录不作为当前功能说明。
