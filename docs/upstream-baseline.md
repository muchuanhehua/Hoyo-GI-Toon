# 模块来源与接入标准

Hoyo-GI-Toon 通过独立模块组合基础 FBX 渲染流程。以下实现作为模块候选，选用结果在对应开发项验收时登记。

## 模块候选

| 模块 | 参考来源 | 选用重点 |
|---|---|---|
| Better FBX 接入 | Gacha Setup 3.8.3 的 `better_fbx_utils` | 公开 Operator 调用、参数核对和实际导入结果检查 |
| 资产归属与资源隔离 | 晨星 Festivity 渲染助手 1.0.2.1 的 `character_system`，Hoyo-GI-Toon 现有事务逻辑 | 对象与资源归属、共享数据处理、引用重定向和恢复 |
| 资产解析与材质规则 | Gacha Setup 的原神分支，Hoyo-GI-Toon 的资源解析 | 材质 JSON、贴图角色、原材质引用及精确匹配 |
| 基础着色与光照 | Festivity 原生可用节点、已选参考实现 | Body、Hair、Face、Light Vectors 与头部控制器 |
| 描边 | 原生几何节点与材质参数映射 | 材质分区、描边颜色、宽度和修改器顺序 |
| 输出与后期 | 晨星的场景资源归属，Hoyo-GI-Toon 现有输出逻辑 | 相机、图片输出、已有合成链的保留与透明通道 |
| 后台验证 | Gacha Setup 的结果清单与完成检查，项目验证脚本 | 独立进程、明确完成结果、数据与渲染证据 |

原生接口和数据保留能力在实际模块验证中确认。单个参考模块通过后，再接入统一流程。

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
