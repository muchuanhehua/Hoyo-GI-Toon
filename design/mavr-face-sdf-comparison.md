# MAVR 与 Hoyo-GI-Toon 脸部 SDF 对比

2026-10-31。MAVR 仅检查当前源码和内置图片，未启动、注册或渲染 MAVR，未修改其文件。Hoyo-GI-Toon 当前对比对象为采用 FBX 脸部资源与 MAVR 绑定校验的 2.2.0 源码候选；已安装 2.1.0 尚无 SDF。

## 结论

两者共享“头部／光向决定采样翻转和阴影阈值”的基本原理，但资源、数值解码和最终着色接口不同。MAVR 将 SDF 接入通用三渲二的明暗遮罩；Hoyo-GI-Toon 保留原生 Festivity Face／Face Factor，并按原神资源分别适配输入。不能仅替换一张图就认定效果或新式编码一致。

| 项目 | MAVR 当前源码 | Hoyo-GI-Toon 源码候选 |
|---|---|---|
| 核心来源 | Autocel 方程的节点重建，输出单一遮罩 | Festivity 原生 Face／Face Factor，输出脸部着色及 Lit Factor |
| 资源选择 | 14 张内置图，由 `mavr_sdf_asset` 选择 | 读取同角色材质 JSON 的明确引用；旧 FaceLightmap 与新 FaceSDF 分开记录 |
| 数值输入 | 图像设为 sRGB／STRAIGHT，Color 输出隐式转 Float | Non-Color／CHANNEL_PACKED，旧式显式 Alpha，新式为 R 实验候选 |
| UV | 默认活动 UV；按光向在 U 与 1−U 间切换，REPEAT | 明确 UV0；原生组在 U 与 −U 间切换，须用 REPEAT，源 UV 不改 |
| 阈值与软硬 | XY 投影归一化后点积，半兰伯特阈值，固定宽度 0.01 的线性 Map Range | 原生 Shadow Position 的幂次调整及 Softness 分支，demo 为位置 0.52、软边 0.02；两套数字不可直接等同 |
| 脸部范围 | `is_primary_face` 仅归一后的颜／脸／面／face／face_；编号后缀归为叠层 | 候选主脸规则包含相应基名及 1／2 后缀；纳西妲的两个绑定均进入 Face。是否适合其他 PMX 仍需检查，不能据此认定更准确 |
| 眼部与颜色 | 没有单独读取游戏 Face Shadow／眼部遮罩，最终颜色由 MAVR 通用材质决定 | 旧式分别接入 Face Shadow；新式停用尚未适配的旧绿色眼遮罩，沿用 PMX 颜色、Toon、Sphere、Alpha |
| 主光源 | 可选一盏 Sun／Area／Point／Spot；非 Sun 使用头部到光源的代表方向 | 借鉴其单光源选择与非 Sun 代表方向，转换为原生 Light Direction 的入射方向；按角色头部位置分别计算 |
| 头部参考 | 结合头骨名称、脸部权重、脸中心和眼骨位置建立参考，有歧义与退化校验 | 借鉴骨名、主脸权重置信与退化检查，保留原生 Head Origin／Child Of；没有替换为 MAVR 的眼骨朝向重建或法线模块 |

两边均有绑定头骨的参照及动态更新路径，不能表述为一边静态、一边实时；本轮没有对 MAVR 做动画或同条件出图，不能据源码宣布哪边视觉更好。两边也都存在 XY 分量处理，不能把 Hoyo 的 `headUp` 输入存在说成已实现完整头部局部平面的光照投影。

## 新式资源的实际发现

MAVR 的 `assets/sdf/Genshin_FaceSDF2.png` 与奥黛塔目录中的 `Avatar_Girl_Tex_FaceSDF.png` 尺寸相同，逐通道平均像素差均约为 0.0014/255，几乎是同一数据。MAVR 程序仍统一读取 Color，没有按这张图单列 R／A 解码或新式开关分支。因此，“内置有这张图”可以证明资源存在，不能证明其完整新式编码已适配。

Hoyo 当前新式 R 仍为实验采样，G／B／A 的完整用途与精确原算法未核实；此次对比没有改变该结论。

## 对比中修正的私有候选问题

之前的私有适配在原生 −U 翻转后使用 EXTEND，负 U 被钳制在第一列。MAVR 的 1−U 明确落回有效范围，帮助定位了这处输入契约不匹配。这是 Hoyo 私有 demo 的适配错误，不是原生 Face Factor 或 MAVR 的错误。

例如 U=0.35 时，原生镜像为 −0.35；REPEAT 读取 0.65，EXTEND 读取 0。安柏源图在本次取样点的 Alpha 分别为 189 和 0，会把正确的阈值数据替换为边缘值。[Blender Image Texture 文档](https://docs.blender.org/manual/en/5.0/render/shader_nodes/textures/image.html)说明了重复与延展的差别。

当前候选恢复 REPEAT，保留原生 −U 公式。三角色重新出图、参数重置、保存重开与恢复通过；未镜像侧 45° 图基本一致，镜像侧 −45° 明显改变，符合只修采样分支的预期。更新后的 48 张主对照、六张重置／重开图及三张 2.1.0 预览复验图替换当前入口；之前的原始证据留在私有 `previous-extend-adapter/`，不再作为左右光向正确性的验收依据。

实际图片：[私有采样修正前后](../.verification/development/pmx-face-sdf-20261031/review/sampler-correction.jpg)、[更新后的 SDF 对照](../.verification/development/pmx-face-sdf-20261031/review/README.md)。两张采样修正图均由 Hoyo 候选渲染，不是 MAVR／Hoyo 的视觉优劣对比。

## 已选择的组合

用户确定优先使用同角色 FBX 的 SDF 资产，其他模块按适用性参考 MAVR。候选已完成：可选资源解析、头骨权重置信与退化检查、单主光源选择、非 Sun 代表方向及渲染前更新。原神贴图的通道、遮罩和 Face 主着色链路保持独立；不移植 MAVR 的通用着色或脸部法线重建。

缺少同角色资产时保留 PMX 基础阴影；发现明确引用缺图、多份同角色资源或无效显式目录时给出错误，不误用相邻角色。已有工程可利用原贴图路径定位，也可通过模块目录输入明确指定资源包；菜单已提供目录入口；更换已应用的资源需先恢复原材质。

安柏、纳西妲、奥黛塔重新导入、保存重开及恢复重装配通过，太阳光下头部与 `repeat-v1` 严格像素一致。双角色图像／头部隔离、单角色恢复、头部及整体转向跟随、三类非 Sun 的位置更新和失败回滚已自检。后续批次已补充俯仰与眼口顶点 Morph 自检；新式完整编码与完整 MMD 演出仍未验证。入口：[集成候选记录](../.verification/development/pmx-face-sdf-integration-20261031/README.md)。

源码入口：[MAVR SDF](../../MAVR/presets/face_sdf.py)、[MAVR 头部参考](../../MAVR/presets/face_normal.py)、[MAVR 光源](../../MAVR/presets/light_source.py)、[MAVR 分类](../../MAVR/presets/material_groups.py)；Hoyo 源码实现为 `face_assets.py`、`face_sdf.py`，原生节点记录见 `.verification/research/pmx-face-sdf-20261031/evidence.json`。本次比较的机器记录位于 `.verification/research/mavr-sdf-comparison-20261031/evidence.json`。
