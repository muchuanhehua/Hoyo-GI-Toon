# 基础渲染装配

基础流程按材质引用、表面用途和源数据标记处理 FBX，不使用角色姓名配置。

## 贴图引用

Pupil 和其他材质使用各自 JSON 的 `_MainTex`、LightMap、Ramp 引用。瞳孔可以使用独立图片，也可以位于头发图集；材质名称不能成为替换成 Body 贴图的依据。

对应实现为 `asset_resolver.AssetCatalog.resolve`。缺少 JSON 时，继续沿导入材质的 Base Color 链及精确文件名解析。

`material_protocol.describe` 先确定实际 Body、Hair 或 Face 模板，再将源开关、强度、通道和依赖整理为启用功能。分层眼和 Face 不继承未使用的 Body 资源要求，法线强度为零时不要求法线图。声明且启用的资源无法找到时给出错误。

无 LightMap 引用的 Body 使用明确的中性数据 `(0, 1, 0, 0)`，分别关闭额外高光与遮蔽，不借用其他材质的贴图。`sampling.configure` 与扩展节点共用源 `m_Scale / m_Offset`；变换只接入自有采样节点，原 UV 和图像设置保留。

`normal_maps.apply` 将切线图接入原生 TBN 路径，保留负值和大于一的源强度；打包高度图通过 Bump 生成着色法线，不位移顶点。`_NormalMapLayerEnum` 选择打包通道，UV 与通道分开处理；使用源强度与采样间隔，未导出间隔时使用一个源图像素的间距。

## 眼部与表面细节

`eye_surfaces.mark` 在派生网格上按连通表面与深度区分外层和虹膜，保留全部面与原材质槽索引，不使用固定面数或角色名称。

材质开启 `_ParallaxLayer1 / 2 / 3` 时，`eye_layers.apply` 读取对应图片、Alpha、Tint、强度、UV 参数和层色 Ramp，按原生 `PupilaTodo` 的 `01 → 04 → 02 → 03` 顺序及 OVERLAY Ramp 合成。内层虹膜不透明；外层按 SDF 红通道覆盖透明高光，Matcap、打包法线和高光强度作用于该外层，UV 视向偏移不移动网格。旧图集眼部继续使用基础路径。

`eye_surfaces.attach` 在求值几何上分派内外层材质，避免 Eevee 将同一个混合透明材质用于重叠虹膜与高光时丢失高光。基础网格的面数、材质槽和面索引保持原样，恢复时移除自有节点及派生数据。

`textiles` 将丝袜、方向性丝绸和静态闪点分别装配。读取源细节纹理、材质区域、法线 B 中的面料分区、顶点色遮罩及指定图案通道。源材质未启用的功能不添加。

`reflections` 根据材质特征启用 Matcap、晶面法线、Fresnel 与内部反射近似。LightMap 的指定通道限定反射区域；反射保留原表面颜色，Hair 图集中的普通头发不整体改成晶面。

上述新增模块提供原生节点下的静帧近似。游戏运行时的闪点动画、引擎 Cubemap 与眼部深度写入不计作已复现；源 JSON 中有对象引用但没有可定位本地图像的 Cubemap，不替换成无关图片。

## 渲染参与

`surface_layers.participation` 根据引用材质区分常驻 Avatar 表面、`SkillObj_*` 技能附件、`Eff_*` 技能光效和默认材质占位面。共用 Face 图集的 `EyeStar` 为默认未启用的表情网格。后四类在基础展示中关闭可见性；常驻表面即使名含 EffectMesh 也保留显示。

`workflow` 保存用途、依据与原显示状态，恢复时还原。全部对象、原网格、材质和挂接关系保留；这里的预览可见性判定不拆分或导出混合资产。

源 `_CullMode` 分别映射双面、正面剔除与背面剔除；透明模式沿用源 Alpha 用途。已有风之翼和武器有明确配套材质时，也进入同一装配接口；风之翼的透明区域不再显示黑底。源位置和挂接继续保留。

## 表情覆盖层

当材质的 `_FacialUVExpressionEnable` 开启、`_FacialExpEnable` 和 `_FacialExpAdditionEnable` 均关闭时，读取源 `UV2`。具有零／非零分区的该通道可区分基础面与默认未启用的表情面。

`surface_layers.mark_expression_faces` 将标记写入派生网格的 `hgt_facial_expression` 面属性。`attach_expression` 在求值几何中筛选默认关闭的表情面，使其同时退出深度和描边，避免重叠透明面在脸部留下残影。基础网格的全部顶点、面、UV、权重和形态键保留。缺少必要通道或不能区分基础面时给出明确错误，避免隐藏整张脸。

描边仅对有效表面生成；筛选节点位于光向与描边之前，不应用到基础网格。`Face_Eye` 与眉毛、瞳孔一样保留贴图轮廓，不生成外扩轮廓。

此路径处理表情层的默认可见性；表情图集的交互控制另行开发。脸图的 Alpha 可能承载腮红等数据，不将其统一当作皮肤透明度。

## 两个参考插件的取用

| 检查点 | Gacha Setup 3.8.3 | 晨星 Festivity 1.0.2.1 | 本项目采用 |
|---|---|---|---|
| 瞳孔引用与分层 | `texture_import_setup/texture_importer_types.py` 解析独立 Pupil 图片，`PupilaTodo` 合成多层，`classify_pupil_faces` 区分表面 | 材质分派保留主贴图，眼部有独立 Alpha 路径 | 按实际引用、源 Ramp 与连通表面装配 |
| 特效 | 导入阶段区分 `EffectMesh / EyeStar`；`Eff_*` 材质单独处理并排除描边 | `_prepare_fbx_selection` 区分特效与角色网格 | 取用用途区分；在记录层可逆关闭显示 |
| 重叠眼部与表情 | Face、Pupil 和高光层分别装配 | `expression_layers.py` 以可恢复的透明材质处理覆盖面，眼部另有 Alpha 路径 | 保留分层思路；本项目根据源参数与第三套 UV 标记补充适配 |

源 UV 标记的适配由本项目的单变量检查补充验证，并非将两个参考插件整套接入。运行代码集中在 `surface_layers.py`，由编排层与材质层调用。

参考源入口见 [模块来源与接入标准](upstream-baseline.md)。

## 预览与图片

材质预览使用场景灯光与世界，避免额外叠加工作室环境。PNG 使用当前角色、姿态与勾选部件，由临时场景统一设置输出光照、Standard 色彩显示、透明和可选后期；用户原场景的色彩、合成链和渲染设置保留。工作视图仍受用户场景的显示设置影响，最终外观以保存的 PNG 为检查依据，图片图标打开的正是该文件。

输出拒绝写入已导入模型的资产目录或覆盖已加载贴图。保存重开前后的临时场景使用稳定对象顺序，核对透明重叠和共面表面的实际像素。

## 验证入口

- `tools/verify_development.py`：导入快照、派生几何、恢复、重复装配、共享数据与失败回滚。
- `tools/verify_characters.py`：实际候选包导入、多角色统一光照渲染、源文件与导入数据核对。
- `tools/verify_render_surfaces.py`：保存重开后的贴图引用、表情层、近景、透明与后期 Alpha、原网格与可见性恢复。
- `tools/verify_material_features.py`：同机位逐功能关闭、眼部转角、游戏截图摘要与原数据还原；技术结果与外观验收分开记录。
- `tools/verify_material_pipeline.py`：七 FBX、三 PMX 的全身、头部、转角、服装近景与侧光；实际原生 PupilaTodo 合成、两条采样路径、法线强度、Alpha 与剔除夹具，源文件及恢复核对。
- 私人索引、单变量图片和工程均在忽略的 `.verification/development/`，不进入发布包。

当前检查结果与验收状态统一记录于 `design/DEVELOPMENT.md`。
