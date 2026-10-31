# PMX 脸部 SDF 接入研究

研究日期：2026-10-31。本文记录接入前的源码、节点与资产核查。用户随后确认 F01–F04 并选定 FBX 脸部资源与 MAVR 绑定模块的组合，组合已获确认并整合至 2.2.0 源码，面板及动态自检完成；已安装版本仍为 2.1.0；当前开发及验收状态以 [DEVELOPMENT.md](DEVELOPMENT.md) 为准。

## 结论与推荐方向

可以接入，属于 P04 共用基础材质。推荐在原生 Festivity Face／Face Factor 上增加独立的脸部资源与采样适配，沿用现有头骨和光向参照，保持 PMX 原网格、UV、Morph 与原材质。

当前缺口同时涉及 Face 分支装配、贴图通道和脸部用途识别。不能只把 `Body` 改名为 `Face`，也不能将五种内置体型 SDF 无条件套到所有 PMX。先验证旧式 FaceLightmap，再查清新式 FaceSDF 的解码并纳入同一模块。

本地具备对应脸部资源。建议仅从明确匹配的同角色资源读取贴图与材质引用，不需要重新导入 FBX 或处理其中附件。当前源码已增加资源解析与目录入口，缺资源时保留基础阴影。私人模型及游戏贴图仍不进入安装包。

## 本次实际检查

在独立后台 Blender 中读取上一轮三份校准工程，核对源 UV、脸部材质、头部参照及原生和项目裁剪后的 Face 节点。未操作前台工程，未写回原工程。

| 样本 | 源 PMX 脸部 UV | 同角色材质实际引用 | 接入判断 |
|---|---|---|---|
| 安柏 | 仅 UVMap；1,648 个面具有有效 UV 面积 | `_FaceMapTex` → `Avatar_Girl_Tex_FaceLightmap`；`_UseFaceMapNew=1` | 可优先验证旧式 SDF，主 UV 是候选采样坐标 |
| 纳西妲 | 仅 UVMap；2,204 个面具有有效 UV 面积 | `_FaceMapTex` → `Avatar_Loli_Tex_FaceLightmap`；`_UseFaceMapNew=1` | 与安柏共用旧式接口，按资源引用确定图像 |
| 奥黛塔 | UVMap 有效；脸部 UV1、UV2 均为单点 `(0,1)`，2,176 个面的附加 UV 面积全为零 | `_FaceSdfMap` → `Avatar_Girl_Tex_FaceSDF`；`_UseFaceSDF=1`、`_UseFaceMapNew=0` | 需要新式解码，不能按旧 FaceLightmap 直接替换；脸部附加 UV 不可用 |

原工程渲染网格上额外存在的 UV0／UV1 可能只是源主 UV 的别名，不代表源 PMX 提供了独立的脸部展开。三份样本均未满足晨星混合 UV 的识别条件；本次没有判定它们必须重建 UV。主 UV 与 SDF 的最终适配仍须通过侧光、转头和表情实际出图确认。

证据位于私有目录 `.verification/research/pmx-face-sdf-20261031/`：[UV 布局](../.verification/research/pmx-face-sdf-20261031/face-uv-layouts.jpg)、[原始 RGBA 通道](../.verification/research/pmx-face-sdf-20261031/sdf-source-channels.jpg)、[UV 数量与面积](../.verification/research/pmx-face-sdf-20261031/uv-statistics.json)、[完整节点及资产记录](../.verification/research/pmx-face-sdf-20261031/evidence.json)。图中的新式 A 通道只用于观察布局，尚未认定为其正确解码。

## 两个参考插件的可取部分

| 参考模块 | 可复用内容 | 本项目需要补齐的部分 |
|---|---|---|
| Setup Wizard：`texture_importer_types.set_face_diffuse_texture` | 用明确资源命名选择 Loli／Boy／Girl／Male／Lady 原生体型分支 | PMX 贴图名通常不保留这些英文前缀，应从匹配的资源记录读取，不能猜体型 |
| Setup Wizard：`set_face_lightmap_texture`、`set_face_shadow_texture` | 区分 FaceLightmap 与 Face Shadow，按数据图读取 | 按当前角色、材质及实例绑定，不写全局同名节点；旧、新格式需要显式区分 |
| 晨星 Festivity：`face_uv` | 在节点中切换采样坐标，源网格与源 UV 保持不变；先检查布局再应用 | 三份样本不满足其双 UV 条件，不能直接照搬混合规则 |
| 晨星 Festivity：自定义 SDF 与眼部遮罩处理 | 将 SDF 阈值图与模板眼部遮罩分别处理，避免遮罩坐标错位 | 采用通用贴图接口和遮罩契约，角色姓名特例不进入共用代码 |
| Festivity 原生 Face／Face Factor | 头部相对光向、左右翻转、阈值比较、软硬边和脸部颜色组合 | 恢复必要的数据输入，并进入当前 PMX 材质与参数链路 |

本地参考入口为 `research/setup_wizard/` 与 `research/festivity_genshin_addon/`。对比的是实际源码及二进制节点，不以面板选项存在代替功能验证。

## SDF 的职责与已确认接口

脸部 SDF 根据头部相对光向，从阈值贴图计算明暗分界。旧式实现通常根据左右光向选择原 UV 或水平镜像 UV，再用前向光阈值比较贴图。HoyoToon 的[实际实现](https://github.com/Hoyotoon/HoyoToon/blob/d9e5ca2f312bf16fba89dee67d32c08b482dcda4/Shaders/Genshin%20Impact/Includes/HoyoToonGenshin-common.hlsl#L430)明确使用 `_FaceMapTex` 的 Alpha 通道；这是旧式算法参考，不代表奥黛塔的新图沿用同样编码。

项目 Face Factor 已读取 `lightDir`、`headForward`、`headUp`。三份 PMX 已有随头骨的 Child Of 参照；无需改骨骼轴或另造一套角色朝向。实际动态跟随仍需测试，包括头部独立转动、整体转身和俯仰。

原生 Face Shader 同时提供 BSDF、Lit Factor、Lit Sharp Factor 等输出，可以沿用本项目的 Toon／Sphere／Alpha、染色和描边组合方式。SDF 应替换脸部的明暗因子，避免额外叠乘一层身体阴影。刘海投影、眼层覆盖和虹膜着色分别处理，不以 SDF 接入替代这些检查。

## 必须明确的数据与模块边界

1. **脸部用途**：仅主脸皮肤进入 SDF。当前 `face` 类还包含白目、口舌、牙齿等，不应整类无差别切换；眉睫、虹膜及表情叠层保留各自用途。识别依据是通用材质语义、贴图及面分布，不建立角色姓名表。
2. **资源解析**：记录图像路径或打包图像、源材质引用、编码类型、通道、采样 UV 与匹配依据。优先明确绑定与同角色资源引用；缺失或多义时提示选择贴图目录，不静默套用其他角色资源。局部目录扫描不等同于启用 FBX 导入。
3. **贴图解码**：SDF 使用 Non-Color、Channel Packed。FaceLightmap 与 Face Shadow／眼部遮罩分别绑定。安柏、纳西妲的本地图和原库内置图蓝通道明显不同；原 Face Factor 的纹理颜色进入浮点运算，不能直接连接未经适配的 RGB。旧式可先按已确认的 Alpha 契约接入并验证；新式 R／G／B／A 的含义尚未查清，不默认选择 Alpha。
4. **坐标适配**：先用有效主 UV，按实际布局验证眼周、鼻翼、耳根和口部。确需重映射时只增加派生采样坐标或派生 UV，保留基础色采样、原 UV 和 Morph。单纯复制 UV 层不能修复布局差异。
5. **材质与参数**：`Graph.shader` 与 `face_sdf.shader_node` 已区分 Face／Body 参数接口，不靠节点改名规避。阴影颜色和软硬范围映射到真实 Face 输入，重置和已有工程参数保持可恢复。
6. **实例隔离**：复用 `ShaderLibrary._private_textures` 的局部节点复制方式，FaceFactor 图像及参数归属当前角色。两个角色不同 SDF、保存重开及资源移动后不串材质。

## 开发清单

以下为 P04 子项；用户已确认 F01–F04 的私有实现与对照，后续资源与绑定组合已补充 F05 的转向与隔离检查，F06 资源菜单和软硬参数已完成源码及真实面板自检。各项当前结果统一记录于 DEVELOPMENT，发布另按明确指令执行。

| 编号 | 开发内容 | 验收要求 |
|---|---|---|
| P04-F01 | 主脸与辅助眼口材质识别；脸部资源解析和编码记录 | 三份样本明确主脸、原始图像引用及有效 UV；不改原网格或源材质；资源缺失／歧义有明确结果 |
| P04-F02 | 旧式 FaceLightmap 接入 Face／Face Factor | 安柏、纳西妲在前光、左右 45°／90°、背光下输出对照；脸部明暗方向正确，眼白与口腔正常，身体材质保持 |
| P04-F03 | 新式 FaceSDF 通道与阈值核实、格式适配 | 奥黛塔的源参数和通道语义有依据；光向扫描与游戏截图对照，没有套旧式图冒充新式接入 |
| P04-F04 | 三角色共用材质参数校准及私有 demo | 同相机和同光照下给出游戏截图／当前基础／SDF 对照；同一套规则，公开实际仍有的差距，用户审阅后再收口 |
| P04-F05 | MMD、恢复与隔离回归 | 转头俯仰、转身、眨眼张嘴；双角色不同 SDF、保存重开、重置及恢复；原网格、UV、Morph、骨架与原资产摘要一致 |
| P04-F06 | 参数面板与交付收口 | 资源可匹配时自动装配；只保留必要脸部阴影参数，不增加体型选择向导；用户验收后按明确指令发布和更新 |

F01–F04 的资源与绑定组合已获用户确认，并整合到源码候选。新式主阴影已有 R 通道实验候选，完整编码与精确原算法仍是 F03 的未决问题。

## 接入前证据与来源

- 后台只读检查完成：三份工程、原生和项目 Face 库；91 个受保护文件、31 个候选载荷及 4 份参考代码摘要核对一致。该接入前探针不包含渲染；后续实际出图、动态与面板自检见 DEVELOPMENT。
- 主探针：[inspect_sdf.py](../.verification/research/pmx-face-sdf-20261031/inspect_sdf.py)；机器证据及图片在同目录，原始角色和参考贴图只保留于私有研究路径。
- 原生来源：[Festivity Shader](https://github.com/festivities/Blender-miHoYo-Shaders)、[Setup Wizard](https://github.com/michael-gh1/Addons-And-Tools-For-Blender-miHoYo-Shaders)。使用的资源提交与摘要由 `assets/upstream.json` 固定。
- 外部交叉参考：[HoyoToon 脸部阈值源码](https://github.com/Hoyotoon/HoyoToon/blob/d9e5ca2f312bf16fba89dee67d32c08b482dcda4/Shaders/Genshin%20Impact/Includes/HoyoToonGenshin-common.hlsl#L430)；[BobH233 的 PMX／Festivity 适配说明](https://github.com/BobH233/blender_mmd_genshin_shader_importer/blob/3360abdee4cd2283ce68013fc3b7e346281893d5/README.md)证明已有用配套游戏资源装配 PMX 的工作流，不能代替本项目新式 FaceSDF 的验证。
