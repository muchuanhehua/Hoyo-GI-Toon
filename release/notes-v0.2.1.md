# Hoyo-GI-Toon v0.2.1

按参考仓库的原版渲染方案重做：使用 Festivity v3.4 的 Body、Hair、Face、Outlines、Light Vectors、头部控制器和 Setup Wizard v3 材质参数映射。保留简洁面板、单一 FBX 入口和本地配套资产解析，不添加自行设计的替代着色或角色特效。

相较 0.2.0，补充旧版角色的兼容保护：更新插件后保留旧材质与灯光，重新导入角色后才使用原版节点。

36 个节点组、4 个材质模板结构对照通过。奥黛塔、尼可的参数已调用原始代码交叉核验；原始库与打包库使用相同装配器、机位和两种光照时，像素最大差异均为 0。数据保留、恢复、双角色隔离、头部跟随、回滚、后期、保存重开及旧工程保护检查通过。

[下载 Blender 安装包](https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/v0.2.1/release/hoyo_gi_toon-0.2.1.zip)

SHA256: `bdcacd9965cdb61d1e9854bc9436a08a8833f3ce6cb5cee9099243bf269c39d3`

安装包不含游戏模型和贴图；更新后重新导入角色。原版基线与验证边界见 docs/upstream-baseline.md。PMX 后续接入。

更新源：`https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/main/release/index.json`
