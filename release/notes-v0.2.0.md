# Hoyo-GI-Toon v0.2.0

将 v0.1.0 自建的简化着色替换为参考方案的原版节点与材质处理。

- 使用 Festivity v3.4 的 Body、Hair、Face、Outlines、Light Vectors、头部控制器与 Lighting Panel。
- 按 Setup Wizard v3 应用五个材质分区的金属、高光、阴影、颜色、Alpha 与描边参数；Pupil 按原版走 Body 模板与 Body 贴图。
- 保留简洁面板、单一 FBX 入口、本地资产解析和角色隔离；输出面板可应用原版后期。
- 36 个节点组、4 个材质模板结构对照通过；原始参数代码交叉核验通过。奥黛塔和尼可分别使用原始库与打包库，在相同装配器、机位和两种光照下渲染，像素最大差异均为 0。
- 两角色数据保留、材质恢复、头部跟随、失败回滚、保存重开和原版后期验证通过。原版基线与验证边界见仓库 docs/upstream-baseline.md。

安装包不含游戏模型或贴图。更新后重新导入角色，已有工程中的旧版简化材质不会被直接替换。PMX 后续接入。

[下载 Blender 安装包](https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/v0.2.0/release/hoyo_gi_toon-0.2.0.zip)

SHA256: `1637a110512646c4e4958ad547a0f53f627d22b77d9aa1a754c1de94ee97fe5e`

Blender 更新源：
`https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/main/release/index.json`
