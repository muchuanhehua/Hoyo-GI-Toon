# Hoyo-GI-Toon

面向新手的原神角色渲染插件，围绕模型导入、材质装配、光照、描边和渲染组织操作。

当前开发目标是：在原生 Blender 中，通过单入口调用 Better FBX，读取本地配套资产，完成保留原始数据的基础 FBX 渲染。

## 开发与验收

详细工作项、交付标准和实时进度统一保存在 [开发清单与验收进度](design/DEVELOPMENT.md)。按用户批准的编号范围实施，提交验收后继续。

模块接口、来源与接入要求见 [模块来源与接入标准](docs/upstream-baseline.md)，维护规则见 [AGENTS.md](AGENTS.md)。

## 使用流程

1. 启用 Better FBX，选择模型文件。
2. 插件读取配套贴图和材质参数，建立渲染材质与控制器。
3. 按需调整阴影、描边和光照方向。
4. 渲染并保存图片。

常用操作集中在主面板，光照和输出设置按需展开。

## 交付

当前发布为 `0.2.2`。源码与安装包见 [GitHub](https://github.com/muchuanhehua/Hoyo-GI-Toon) 和 [Releases](https://github.com/muchuanhehua/Hoyo-GI-Toon/releases)。

Blender 远程更新源：

`https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/main/release/index.json`

角色模型、游戏贴图和私人验证工程仅在本地使用。
