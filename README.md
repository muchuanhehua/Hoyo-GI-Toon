# Hoyo-GI-Toon

原神角色渲染插件。以参考仓库的 Festivity v3.4 渲染方案为基线，直接装配原版材质、Light Vectors、头部控制器与描边节点。

首版支持 FBX，随后接入 PMX。两种格式共用一个导入入口；后续 PMX 使用 MMD Tools 导入后执行骨骼顺序和骨名问题修复。

## 使用流程

1. 在侧栏 `Hoyo-GI-Toon` 点击“导入角色”，选择模型。
2. 插件读取模型目录及关联目录中的贴图、材质参数，建立角色材质和描边。
3. 按需调节阴影位置、描边和灯光方向。
4. 点击“渲染当前帧”。输出设置中可应用原版后期。已有相机继续使用，没有相机时建立角色预览相机。

面板只保留操作和参数，缺失或歧义时才提示。源码中的资源解析不将 PMX、FBX 后缀当作贴图完整度判断依据。

## 开发状态

项目按 [AGENTS.md](AGENTS.md) 维护，原版基线和适配边界见 [原版对齐记录](docs/upstream-baseline.md)。

0.2.0 替换了 0.1.0 的简化着色。原版的材质分区、金属、高光、双 UV、法线、脸部阴影、描边颜色及可选后期均使用原版节点与参数映射。`Pupil` 按原版走 Body 模板和 Body 贴图；不添加自行设计的新瞳孔或角色特效。技能和出场效果网格保留但不参与静态预览。

已用奥黛塔、尼可检查模型数据保留、材质恢复、双角色隔离、头部控制器跟随、失败回滚和保存重开。节点结构与原版库逐项比较，材质参数调用原始映射代码交叉核验；打包库和原始库使用相同装配器进行同机位、双光照渲染比较。这些检查针对固定原版基线，不将其表述为游戏画面的完整复现。

从 0.1.0 更新后，重新导入角色以使用原版节点。已有工程中的旧材质不会被远程更新直接改写。

## 交付与更新

源码和安装包通过 [GitHub](https://github.com/muchuanhehua/Hoyo-GI-Toon) 交付，Blender 使用项目远程扩展仓库更新：

`https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/main/release/index.json`

安装包见 [Releases](https://github.com/muchuanhehua/Hoyo-GI-Toon/releases)。也可从磁盘安装发布 ZIP。

开发构建：`python tools/build_release.py --blender <Blender executable>`。工具检查精确包内容、CRC、SHA256，以及当前源码与两模型实际验证指纹的一致性。

私人角色、贴图和验证工程不随源码或安装包分发。
