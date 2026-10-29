# 22–34 基础材质核对

本轮以通用材质链路为范围，复用原生 Body、Hair、Face、光照和描边资源。已有功能先核对，实际缺口再补齐；不按角色姓名切换着色算法。候选、技术结果及用户验收状态统一见 [开发进度](DEVELOPMENT.md)。

## 模块与依据

| 编号 | 采用与实现 | 检查依据 |
|---|---|---|
| 22 | Gacha Setup 3.8.3、晨星 Festivity 1.0.2.1 按模块对照，沿用已固定来源的原生资源 | 参考代码、实际节点、材质 JSON 与贴图摘要 |
| 23 | `asset_resolver`、`material_protocol` 依实际模板与父分支解析 FBX 资源 | 独立材质引用、关闭分支不要求资源、启用缺图报错 |
| 24 | `pmx_materials` 处理主贴图、Toon、Sphere、Alpha、双面与边线 | 三份 PMX、原 MMD 材质与 Morph 元数据、修复前后记录 |
| 25 | 原生 Body、Face、SDF 与头部参照 | 全身、头部、转角、侧光和骨骼跟随 |
| 26 | `eye_layers` 按 PupilaTodo 顺序合成；`eye_surfaces` 分派虹膜和透明高光 | 原生组同输入渲染、旧图集与新分层眼、内外表面及材质槽核对 |
| 27 | 原生 Hair、源贴图轮廓与表情覆盖规则 | 头部近景、转角、眉睫与常驻装饰保留 |
| 28 | `textiles`、`reflections` 与原生高光、金属分支 | 丝袜、丝绸、闪点、晶面反射和高度法线的逐功能差分 |
| 29 | `surface_layers`、眼部独立通道及源 `_CullMode` | Alpha 覆盖和正面剔除夹具；默认关闭表情面的求值筛选、深度残影与附件交叠 |
| 30 | `sampling` 共用源 ST；原生 TBN 与高度采样 | 两条采样路径同图对照、负值及大于一的法线强度、原 UV/法线/图像设置保留 |
| 31 | 原生 Light Vectors、Lighting Panel 与分区描边 | 头部跟随、不同光向及姿态、跨格式调节与恢复 |
| 32 | 明确配套材质的已有武器、风之翼进入共用工厂 | 真实风之翼透明及双面；源位置、挂接与引用保留 |
| 33 | 场景灯光材质预览、统一临时 PNG 输出及查看结果 | 透明与后期 Alpha、原工程设置、当前批次与部件、保存重开、路径保护 |
| 34 | 精确源码与 ZIP 安装的完整验证 | 实际图片、可重开工程、数据报告；外观由用户验收 |

参考入口为 [Gacha Setup](https://github.com/PaoloESAN/gacha-setup) 的 `texture_import_setup/texture_importer_types.py`、`replace_default_materials_setup/game_default_material_replacers.py` 与 `utils/mmd_model_adapter.py`，以及 [晨星 Festivity](https://github.com/AstraMorningstar/Morningstar-Festivity-render-assistant) 的 `character_system.py` 和眼部、表情处理。沿用的基础节点与映射来源见 [NOTICE](../NOTICE)、[模块接口](../docs/upstream-baseline.md) 与 `assets/upstream.json`。

## 实际样本

| 格式 | 样本 | 覆盖 |
|---|---|---|
| FBX | 芭芭拉、雷电将军、纳西妲、芙宁娜、玛薇卡、桑多涅、奥黛塔 | 早中后期资源、Loli/Girl/Lady 三种模板、旧图集与分层眼、服装细节 |
| PMX | 安柏、纳西妲、奥黛塔 | 独立 PMX 材质语义、不同体型、Toon/Sphere/Alpha/边线与 MMD 元数据 |
| FBX 回归 | 安柏、刻晴、奥黛塔、尼可 | 导入、装配、头部跟随、重复装配、恢复与失败回滚 |
| 主体与附件 | 真实风之翼、技能附件、PMX 主体和两种格式的混合网格夹具 | 显示切回、分组、保存重开、恢复与数据保护 |

材质矩阵每个样本保留全身、头部、头部转角、服装近景与侧光 PNG。FBX 与冻结的 0.6.0 工程使用同机位重放；PMX 同既有候选工程对照。真实界面覆盖分层眼 FBX 和混合 PMX 的单入口、撤销重做、取消、分组及异步出图。

## 证据与验收边界

`tools/verify_material_pipeline.py` 汇总材质矩阵，`tools/verification_materials.py` 用实际渲染验证原生 PupilaTodo 合成、源 ST、Alpha 和剔除。基础数据、PMX、主体、混合格式、界面、旧工程各自保留独立报告；`tools/collect_verification.py` 核对实际安装的 ZIP、源码和资源摘要后汇总。

原生 PupilaTodo 对照使用受控输入验证合成顺序与混合方式；真实眼睛另检查 SDF、Ramp、Matcap、视向与内外表面。该结果不能替代眼睛外观验收，也不代表游戏深度写入、引擎 Cubemap、动态闪点或整个参考插件已完全复现。面料、晶面及高度细节沿用原生静帧近似。

游戏截图与验证图的姿态、机位、环境和表情可能不同，作为色彩、纹理、眼层及主要细节的人工对照，不计算游戏还原百分比。当前矩阵覆盖三种体型，不据此声称所有体型均已验证。

模型、截图和验证工程只保留于忽略的 `.verification/`。公开候选摘要不包含私人路径或角色资产。34 只有在用户明确确认基础材质外观后才完成，35 以后不在本轮实施范围内。
