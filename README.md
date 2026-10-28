# Hoyo-GI-Toon

原神角色专用卡通渲染插件。选择角色文件后配置本地配套资产，再调节明暗、轮廓光和描边。

首版支持 FBX，随后接入 PMX。两种格式共用一个导入入口；后续 PMX 使用 MMD Tools 导入后执行骨骼顺序和骨名问题修复。

## 使用流程

1. 在侧栏 `Hoyo-GI-Toon` 点击“导入角色”，选择模型。
2. 插件读取模型目录及关联目录中的贴图、材质参数，建立角色材质和描边。
3. 调节明暗分界、阴影柔和度、轮廓光、描边与灯光方向。
4. 点击“渲染当前帧”；需要时展开灯光、材质与输出设置。已有相机继续使用，没有相机时建立角色预览相机。

面板只保留操作和参数，缺失或歧义时才提示。源码中的资源解析不将 PMX、FBX 后缀当作贴图完整度判断依据。

## 开发状态

项目按 [AGENTS.md](AGENTS.md) 维护。已使用奥黛塔、尼可的原始游戏 FBX 验证导入、材质引用、两种光照下的彩色输出、形态键保留、材质恢复、双角色参数隔离、头部阴影跟随、失败回滚与保存重开。

本版完成基础卡通渲染。玻璃、瞳孔多层视差、角色专属特效、透发与丝袜细节尚未完整还原。技能和出场效果网格保留但不参与角色静态预览。

## 交付与更新

源码和安装包通过 [GitHub](https://github.com/muchuanhehua/Hoyo-GI-Toon) 交付，Blender 使用项目远程扩展仓库更新：

`https://raw.githubusercontent.com/muchuanhehua/Hoyo-GI-Toon/main/release/index.json`

安装包见 [Releases](https://github.com/muchuanhehua/Hoyo-GI-Toon/releases)。也可从磁盘安装发布 ZIP。

开发构建：`python tools/build_release.py --blender <Blender executable>`。工具检查精确包内容、CRC、SHA256，以及当前源码与两模型实际验证指纹的一致性。

私人角色、贴图和验证工程不随源码或安装包分发。
