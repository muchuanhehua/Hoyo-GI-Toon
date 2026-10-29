# Hoyo-GI-Toon v0.5.3

单入口导入 FBX／PMX，从模型选择、材质装配、光照描边到 PNG 输出。

- FBX 使用 Better FBX；PMX 使用 MMD Tools，导入后自动执行骨骼修复并保留前后记录。
- PMX 按原材质读取基础色、Toon、Sphere、Alpha、双面和描边属性，保留原网格、UV、权重、Morph 与原材质。
- 不透明表面与透明覆盖分别处理；按当前导入批次独立出图，同一文件内的模型与附件保持完整。
- 保留简洁面板、可恢复装配、角色相机、透明背景与图片保存。

三份 PMX、四份 FBX、源数据保护、恢复、失败回滚、混合导入、撤销重做、透明输出及保存重开验证通过。本版按用户要求先发布更新，外观验收继续保留。

[下载 Blender 安装包](https://github.com/muchuanhehua/Hoyo-GI-Toon/releases/download/v0.5.3/hoyo_gi_toon-0.5.3.zip)

SHA256：`612f29b890caab2b5860fb5ab6ddec6225a391713dd2314029e66b1935780dcf`

保留所选模型的原有配套文件与目录，启用对应导入器后点击“导入模型”。安装包不包含游戏模型、贴图或导入器程序。PMX 基础静帧与实现边界见 [PMX 渲染](https://github.com/muchuanhehua/Hoyo-GI-Toon/blob/v0.5.3/docs/pmx-rendering.md)。

Blender 远程更新源：`https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/main/release/index.json`
