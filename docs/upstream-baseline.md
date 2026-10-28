# 原版对齐基线

实现方向：先复刻参考仓库的原版渲染结构与材质处理，不设计替代着色或追加角色特效。

| 来源 | 固定版本 | 使用内容 |
|---|---|---|
| [Blender-miHoYo-Shaders](https://github.com/festivities/Blender-miHoYo-Shaders/tree/b79f0f3fb47b4de2b6d187ee6b66d93cb965968d) | `b79f0f3`，v3.4 | Body、Hair、Face、Outlines，Light Vectors，原版描边与后期 |
| [Setup Wizard](https://github.com/michael-gh1/Addons-And-Tools-For-Blender-miHoYo-Shaders/tree/fb942ecc30d9ed3889f5afb0dfb3a23c13601a54) | `fb942ec` | v3 材质参数映射、材质分派、Pupil→Body 贴图规则、顶点色与双 UV、头部约束、Lighting Panel |

## 保留与适配

节点库保留原版节点类型、运算、常量、接口与连接，不用手写节点近似金属、高光、脸部阴影或描边。资源准备只删除游戏图片和 Preview，增加来源标记，并由当前 Blender 保存格式。

纹理从所选角色包解析。常规材质使用明确的 JSON 引用；服装使用 Hair 贴图时按原版选择 Hair 模板，Pupil 按原版使用 Body 模板和 Body diffuse/lightmap。Body01 等同类材质使用同一原版模板并分别绑定其贴图，避免覆盖其他分区或角色。

Body/Hair 两个 Ramp 分支分别使用对应贴图，包含当前材质未启用的另一分支。原版未识别的风之翼等附属材质保持导入结果；脸部描边按原版跳过贴图绑定，眼部描边沿用原版 v3 装配代码的厚度。头部约束通过原版 Child Of Set Inverse 操作建立。

当前 Blender 的几何节点参数使用 `modifier.properties.inputs/outputs`，替代旧版脚本的 modifier IDProperties。导入使用当前原生 FBX API；不再执行旧导入器专用的硬编码骨架旋转。保留导入网格、骨骼绑定、形态键、UV、权重和法线。缺少 UV1 时按原版补充，活动顶点色按原版命名为 Col。

控制器和节点按角色记录归属；不执行原向导中全场景删除 Empty、删除 Cube/Light 等操作。原版可选后期在“输出”中应用；不追加 Rigify、动作重定向或新游戏特效。

## 验证边界

- 对打包前后的 36 个节点组和 4 个材质比较节点、常量、接口与连接。
- 直接执行上游 `MaterialDataApplier`、`V2_MaterialDataApplier` 和 `V3_MaterialDataApplier` 作为参数对照；校验角色材质与描边输入。
- 两款实际 FBX 比较网格、拓扑、UV、顶点色、法线、权重、形态键、骨骼矩阵和对象变换。
- 原始库与打包库使用相同角色装配器，分别在两个灯光方向渲染并比较像素。这验证资源准备未改变原版着色，不冒充完整旧版 Setup Wizard 的独立运行对照。
- 检查原版后期、双角色隔离、头部约束、重复更新、失败回滚、材质恢复和保存重开。

私有证据位于 `.verification/original/`，发布包保存脱敏摘要。以原版 v3.4 的现有能力为范围；该上游方案本身也不承诺完全重现游戏画面。PMX 尚未接入。

## 旧角色独立对照

0.2.2 使用安柏、刻晴初始服装的 FBX，独立执行固定上游的材质替换、贴图导入、默认值、材质参数、Light Vectors、Lighting Panel 和描边装配代码。参考侧不调用本插件的角色装配器；FBX 导入和几何节点字段使用当前 Blender API。

原版向导的 v3 材质名中 `VFX` 为空，较新的描边导入过滤条件会跳过全部 v3 材质。参考侧只为不存在的 VFX 指定非空名称，使原始导入方法可执行，不创建该材质、不更改节点公式。原始不兼容分支的审计证据另行保存。

原版库内置通用脸图与本地角色包的同名图片像素不同。渲染对照统一使用角色包内的输入图片；不将输入素材差异算作着色器差异，也不把内置游戏图片打入发布包。

统一输入后，绑定纹理像素、材质输入、全局参数、求值几何和四个头部/灯光控制器矩阵一致。两角色各两种光照，最终四组 RGBA 渲染出现极少量边缘差异，最大 4/255；保留实际最大值、均值与变化通道占比，不标为像素完全一致。验收要求上述结构和数据严格相同，渲染最大误差不超过 4/255、均值不超过 0.00001、变化超过 1/255 的通道比例不超过 0.01%。

该结论限于这两个角色和列出的静态渲染路径，不包含完整旧版 UI 向导、Rigify、动作处理或全部角色特效。当前证据为 `.verification/original/independent/upstream-workflow.json`，探索与原始差异记录保留在 `.verification/legacy-20261028/`。
