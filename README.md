# Hoyo-GI-Toon

面向原神 PMX 角色的材质渲染插件，以接近游戏内的 Toon 表现、接入 MMD 流程为目标。

当前发布为 [2.0.0](https://github.com/muchuanhehua/Hoyo-GI-Toon/releases/tag/v2.0.0)，已更新本机 Blender，供实际操作验收。使用新场景重新导入 PMX。当前进度、实施清单和验收状态统一见 [开发记录](design/DEVELOPMENT.md)。

## 使用流程

1. 启用 MMD Tools，打开 3D 视图侧栏的 Hoyo-GI-Toon。
2. **导入 PMX**：导入并修复骨骼，创建一个相机；模型原结构与显隐保留。
3. **应用材质**：单独装配角色材质。展开 **材质参数** 调整阴影位置、描边及选中材质的颜色。
4. 按需展开 **打光**，点击 **默认光**，或选择现有太阳光。旋转灯光可调整 Toon 光向。
5. 手动设置相机，或主动点击 **相机对齐当前视角**；按需启用 **看向相机**。
6. 在 **输出** 设置图片尺寸和 PNG 路径，点击 **渲染**。

导入不会应用材质、创建灯光、预设构图或切换视图。表情和动作继续使用 MMD Tools／Blender；本插件不提供表情编辑面板。背景和地面由用户自己的场景管理。

**材质参数**提供当前材质的颜色、阴影颜色和有描边时的描边颜色；全局阴影位置、描边粗细也集中于此。**恢复原材质**还原导入时的网格和材质，独立创建的相机与默认光保留。

操作与限制见 [使用说明](docs/workflow.md)，材质语义见 [PMX 渲染](docs/pmx-rendering.md)，来源见 [模块接口](docs/upstream-baseline.md)。

## 交付与保留记录

源码与正式包见 [GitHub](https://github.com/muchuanhehua/Hoyo-GI-Toon) 和 [Releases](https://github.com/muchuanhehua/Hoyo-GI-Toon/releases)。

远程更新源：`https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/main/release/index.json`

FBX、附件分类、旧表情面板、背景和地面已退出当前实现，旧代码与工程使用方式见 [1.0.1 保留记录](design/legacy-v1.0.1.md)。模型、游戏贴图与私人验证工程不进入安装包。
