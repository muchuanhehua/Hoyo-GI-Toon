# 模块来源与接口

目标是原生 Blender 中的原神 PMX 材质渲染和 MMD 流程。参考实现按模块选用，保留原节点与来源；游戏资产仅从用户所选本地 PMX 引用读取。

| 模块 | 接口与责任 | 来源 |
|---|---|---|
| PMX 导入 | importers.import_character、mmd_importer.import_model；导入、骨骼修复及前后记录 | MMD Tools 公开 Operator |
| 资产保护 | asset_tracking；导入引用、派生网格、恢复及事务 | Hoyo-GI-Toon |
| 材质适配 | pmx_materials.Catalog / build；Toon、Sphere、Alpha、边线 | Gacha Setup 的 PMX 适配原则 |
| 原生着色 | shaders.ShaderLibrary；Body、Hair、光向与描边节点 | Festivity、michael-gh1 的原生模板 |
| 参数 | material_controls；逐材质颜色与全局阴影描边 | Hoyo-GI-Toon |
| 默认光 | lighting.default_light；主动调用，复用自有灯 | Hoyo-GI-Toon |
| 视线 | gaze；可移除眼骨约束及实时跟随 | Hoyo-GI-Toon；MMD 骨名语义参考晨星 |
| 工程与输出 | project_io、rendering；资源重关联、原机位、临时输出与 PNG 保护 | Hoyo-GI-Toon |
| 编排与面板 | workflow、panels；导入、应用材质、参数、打光和输出分离 | Hoyo-GI-Toon |

来源资源版本与摘要见 `assets/upstream.json`，版权与许可见 `NOTICE`。旧版完整功能及参考范围保留于 v1.0.1，当前不接入 FBX、附件分类、表情编辑、背景或地面模块。
