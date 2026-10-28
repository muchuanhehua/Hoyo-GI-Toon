# 基础渲染装配

基础流程按材质引用、表面用途和源数据标记处理 FBX，不使用角色姓名配置。

## 贴图引用

Pupil 和其他材质使用各自 JSON 的 `_MainTex`、LightMap、Ramp 引用。瞳孔可以使用独立图片，也可以位于头发图集；材质名称不能成为替换成 Body 贴图的依据。

对应实现为 `asset_resolver.AssetCatalog.resolve`。缺少 JSON 时，继续沿导入材质的 Base Color 链及精确文件名解析。

材质明确开启 `_ParallaxLayer1 / 2 / 3` 时，`eye_layers.compose` 读取对应图片并按 Alpha 合成基础颜色，同时应用层颜色与强度。此模块采用参考节点 `PupilaTodo` 的颜色分层思路，保留既有原生明暗着色；视差运动另行验证。

## 渲染参与

`Eff_*`、名称包含 `EffectMesh` 的网格及 `EyeStar` 属于覆盖层。基础渲染关闭这些对象的可见性，保留对象、原网格、材质和挂接关系。恢复导入状态时还原原始可见性。

`surface_layers.is_effect_overlay` 只判定表面用途，`workflow` 负责记录和恢复。混合资产的角色拆分仍按后续清单实施。

## 表情覆盖层

当材质的 `_FacialUVExpressionEnable` 开启、`_FacialExpEnable` 和 `_FacialExpAdditionEnable` 均关闭时，读取源 `UV2`。具有零／非零分区的该通道可区分基础面与默认未启用的表情面。

`surface_layers.mark_expression_faces` 将标记写入派生网格的 `hgt_facial_expression` 面属性。原 UV 不变；材质与描边根据该属性混合透明着色器，全部顶点、面、权重和形态键保留。缺少必要通道或不能区分基础面时给出明确错误，避免隐藏整张脸。

描边仅对有效表面生成；在节点求值的描边分支中排除未启用的表情面，基础几何分支完整保留。`Face_Eye` 与眉毛、瞳孔一样保留贴图轮廓，不生成外扩轮廓。

此路径处理表情层的默认可见性；表情图集的交互控制另行开发。脸图的 Alpha 可能承载腮红等数据，不将其统一当作皮肤透明度。

## 两个参考插件的取用

| 检查点 | Gacha Setup 3.8.3 | 晨星 Festivity 1.0.2.1 | 本项目采用 |
|---|---|---|---|
| 瞳孔引用与分层 | `texture_import_setup/texture_importer_types.py` 分别解析 Pupil 图片，缺少独立层图时读取 `_MainTex`；`PupilaTodo` 按 Alpha 合成多张眼图 | 材质分派先取得 `_primary_texture`，保留主贴图；眼部有独立 Alpha 路径 | 按实际引用解析，按开启的层图合成 |
| 特效 | 导入阶段区分 `EffectMesh / EyeStar`；`Eff_*` 材质单独处理并排除描边 | `_prepare_fbx_selection` 区分特效与角色网格 | 取用用途区分；在记录层可逆关闭显示 |
| 重叠眼部与表情 | Face、Pupil 和高光层分别装配 | `expression_layers.py` 以可恢复的透明材质处理覆盖面，眼部另有 Alpha 路径 | 保留分层思路；本项目根据源参数与第三套 UV 标记补充适配 |

源 UV 标记的适配由本项目的单变量检查补充验证，并非将两个参考插件整套接入。运行代码集中在 `surface_layers.py`，由编排层与材质层调用。

参考源入口见 [模块来源与接入标准](upstream-baseline.md)。

## 验证入口

- `tools/verify_development.py`：导入快照、派生几何、恢复、重复装配、共享数据与失败回滚。
- `tools/verify_characters.py`：实际候选包导入、多角色统一光照渲染、源文件与导入数据核对。
- `tools/verify_render_surfaces.py`：保存重开后的贴图引用、表情层、近景、透明与后期 Alpha、原网格与可见性恢复。
- 私人索引、单变量图片和工程均在忽略的 `.verification/development/`，不进入发布包。

当前检查结果与验收状态统一记录于 `design/DEVELOPMENT.md`。
