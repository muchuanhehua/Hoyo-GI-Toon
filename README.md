# Hoyo-GI-Toon

面向新手的原神角色渲染插件，围绕模型导入、材质装配、光照、描边和渲染组织操作。

单入口导入 FBX、PMX，读取本地配套资产，完成保留原始数据的基础渲染。

## 开发与验收

详细工作项、交付标准和实时进度统一保存在 [开发清单与验收进度](design/DEVELOPMENT.md)。按用户批准的编号范围实施，提交验收后继续。

模块接口、来源与接入要求见 [模块来源与接入标准](docs/upstream-baseline.md)，维护规则见 [AGENTS.md](AGENTS.md)。

## 使用流程

1. 启用所用格式的导入器：FBX 使用 Better FBX，PMX 使用 MMD Tools。
2. 从磁盘安装 Hoyo-GI-Toon 的 ZIP，打开 3D 视图侧栏的 **Hoyo-GI-Toon**。
3. 点击 **导入模型**，选择 FBX 或 PMX。保留模型原有的配套文件和贴图目录。
4. 选择 **全身、半身或头像**。需要其他视角时展开 **构图**，需要光照、背景或地面时展开 **展示**。
5. 按需调整阴影、描边和已有 **表情**；**附件** 中勾选已有部件，分组不合适时点击 **调整分组**。
6. 在 **输出** 中设置尺寸与保存位置，点击 **渲染**。

渲染完成后保存 PNG，图片图标可打开最近结果；Esc 取消后可以继续出图。插件生成的文件名遇到已有文件会编号保留，保存位置应在模型资产目录以外。

导入按钮旁的菜单可查看材质、调整部件分组、重新定位移动后的资源或恢复导入状态。多次导入时再选择当前角色。手动调整的相机在出图时保留；详细操作见 [构图与出图](docs/workflow.md)。

模型网格、骨架与配套文件保留。PMX 导入后自动调用 MMD 骨骼修复并保存前后记录；“恢复导入状态”恢复到修复后的导入基线。渲染材质和属性使用派生数据，输出在临时场景中执行，已有相机、灯光和合成链保持独立。

主体与附件按本次导入的实际数据管理，构图跟随勾选内容；同一网格中的混合部件在派生数据上筛选。已有武器与风之翼按配套材质接入基础渲染，保留源位置、挂接及可恢复的原材质引用。具体约定见 [主体与附件](docs/subjects.md)。

基础渲染保留材质实际贴图引用，按源标记处理特效和默认未启用的表情覆盖层。实现与参考对照见 [基础渲染装配](docs/basic-rendering.md)。

PMX 的 Toon、Sphere、透明与描边约定见 [PMX 渲染](docs/pmx-rendering.md)。

## 交付

源码与安装包见 [GitHub](https://github.com/muchuanhehua/Hoyo-GI-Toon) 和 [Releases](https://github.com/muchuanhehua/Hoyo-GI-Toon/releases)。

Blender 远程更新源：

`https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/main/release/index.json`

角色模型、游戏贴图和私人验证工程仅在本地使用。
