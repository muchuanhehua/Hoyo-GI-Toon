# 模块来源与接入标准

Hoyo-GI-Toon 通过独立模块组合基础 FBX 渲染流程，参考插件按功能取用，通过本项目接口连接。

## 来源与选用

| 模块 | 参考来源 | 选用重点 |
|---|---|---|
| Better FBX 接入 | Gacha Setup 3.8.3 的 `better_fbx_utils` | 公开 Operator 调用、参数核对和实际导入结果检查 |
| 资产归属与资源隔离 | 晨星 Festivity 渲染助手 1.0.2.1 的 `character_system`，Hoyo-GI-Toon 现有事务逻辑 | 对象与资源归属、共享数据处理、引用重定向和恢复 |
| 资产解析与材质规则 | Gacha Setup 的原神分支，Hoyo-GI-Toon 的资源解析 | 材质 JSON、贴图角色、原材质引用及精确匹配 |
| 基础着色与光照 | Festivity 原生可用节点、已选参考实现 | Body、Hair、Face、Light Vectors 与头部控制器 |
| 描边 | 原生几何节点与材质参数映射 | 材质分区、描边颜色、宽度和修改器顺序 |
| 输出与后期 | 晨星的场景资源归属，Hoyo-GI-Toon 现有输出逻辑 | 相机、图片输出、已有合成链的保留与透明通道 |
| 后台验证 | Gacha Setup 的结果清单与完成检查，项目验证脚本 | 独立进程、明确完成结果、数据与渲染证据 |

Better FBX 为独立安装依赖，通过 `better_import.fbx` 调用。其余参考实现按模块适配，不要求安装整套参考插件。

## 01–05 模块接口

| 文件与入口 | 结果 | 边界 |
|---|---|---|
| `importers.import_character(filepath, context)` | `ImportBatch`：本次新增 ID、Operator、参数 | 先核对实际 RNA，再传递文件与数据保留参数；检查完成状态和网格 |
| `asset_tracking.derive_mesh / restore_mesh` | 派生网格、原 Mesh 引用、材质链接方式 | UV 与顶点色适配只作用于副本；原始形态键和属性保留 |
| `asset_tracking.DataTransaction / remove_render_data` | 失败回滚、按归属清理 | 沿真实 ID 引用保留外部已使用的资源，不进行全场景清理 |
| `AssetCatalog.resolve(name, material)` | `MaterialAssets`：用途、参数、贴图与匹配依据 | JSON 优先，结合导入材质 Base Color 与精确名称；限定所选资产包 |
| `shaders.ShaderLibrary.build_material(assets)` | 渲染材质和对应描边材质 | Body、Hair、Face、基础眼部与 Alpha；含贴图路径按材质独立 |
| `lighting.build / attach / update` | 头部参照、光向控制、Light Vectors | 只引用导入骨架，保留骨架数据和层级；参数更新不重复创建资源 |
| `outlines.build / update` | 按材质分区的描边修改器 | 沿用材质颜色，位于原始修改器和 Light Vectors 之后，不应用到网格 |
| `workflow.build / assemble / restore` | 资产根对象、装配或恢复结果 | 编排上述模块；同批重复装配复用根对象和已建资源 |

基础色、Ramp 与 Matcap 按 sRGB 读取；LightMap、法线、脸部 SDF 与 Specular Ramp 按 Non-Color 读取。生成图像使用 `CHANNEL_PACKED`，不改导入图像的设置。

原生资源保留 Toon 明暗、脸部 SDF、Fresnel、高光、金属、Alpha 与材质描边路径。资源编译入口为 `tools/build_shader_library.py`，节点选择规则为 `tools/native_shader_paths.py`，输入版本与摘要保存在 `assets/upstream.json`。

后台验证入口为 `tools/verify_development.py`。它读取本地资产索引，输出逐材质匹配、导入基准、数据保护、参数响应与生命周期记录；私人路径与测试工程保留在 `.verification/`。

## 接入要求

1. 每个选用模块记录来源版本、代码范围、输入输出、适配理由和可分发资源。
2. 模块只处理传入的资产与资源引用，不依赖全场景第一个骨架或固定全局名称。
3. 原材质、贴图与数据引用保留；新建资源可以定位、恢复和回滚。
4. 节点与接口必须在原生 Blender 中有效。只保留实际使用、已验证的着色分支。
5. 资源解析与渲染装配分开，UI 只调用本项目的编排接口。
6. 一项功能保留一份实现；接入后清理被替代的调用、资源和文档。

## 来源入口

- [Festivity Shader](https://github.com/festivities/Blender-miHoYo-Shaders)：现有资源来源版本和文件摘要见项目 `assets/upstream.json`。
- [Gacha Setup](https://github.com/PaoloESAN/gacha-setup)：本地参考版本 `3.8.3`。
- [晨星 Festivity 渲染助手](https://github.com/AstraMorningstar/Morningstar-Festivity-render-assistant)：本地参考版本 `1.0.2.1`。
- 现有参数映射来源记录见项目 `NOTICE`。

开发项、当前状态与用户验收统一见 [开发清单与验收进度](../design/DEVELOPMENT.md)。
