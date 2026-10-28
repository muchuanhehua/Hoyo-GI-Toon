# Hoyo-GI-Toon

面向新手的原神角色渲染插件，围绕模型导入、材质装配、光照、描边和渲染组织操作。

通过单入口调用 Better FBX，读取本地配套资产，完成保留原始数据的基础 FBX 渲染。

## 开发与验收

详细工作项、交付标准和实时进度统一保存在 [开发清单与验收进度](design/DEVELOPMENT.md)。按用户批准的编号范围实施，提交验收后继续。

模块接口、来源与接入要求见 [模块来源与接入标准](docs/upstream-baseline.md)，维护规则见 [AGENTS.md](AGENTS.md)。

## 使用流程

1. 在 Blender“偏好设置 → 插件”中安装并启用 Better FBX。
2. 从磁盘安装 Hoyo-GI-Toon 的 ZIP，打开 3D 视图侧栏的 **Hoyo-GI-Toon**。
3. 点击 **导入模型**，选择角色 FBX。配套贴图与 JSON 放在同一资产包内。
4. 按需调整阴影、描边和光照，在 **输出** 中设置图片尺寸与保存位置，点击 **渲染**。

渲染完成后保存 PNG。透明背景和后期在输出中切换；“重新构图”调整本插件的角色相机。

导入按钮旁的菜单可查看材质对应关系，或恢复导入状态。多次导入时再选择当前角色。

模型网格、骨架与配套文件保留。渲染材质和属性使用派生数据，输出在临时场景中执行，已有相机、灯光和合成链保持独立。当前按整份 FBX 处理，附属对象保留。

基础渲染保留材质实际贴图引用，按源标记处理特效和默认未启用的表情覆盖层。实现与参考对照见 [基础渲染装配](docs/basic-rendering.md)。

## 交付

源码与安装包见 [GitHub](https://github.com/muchuanhehua/Hoyo-GI-Toon) 和 [Releases](https://github.com/muchuanhehua/Hoyo-GI-Toon/releases)。

Blender 远程更新源：

`https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/main/release/index.json`

角色模型、游戏贴图和私人验证工程仅在本地使用。
