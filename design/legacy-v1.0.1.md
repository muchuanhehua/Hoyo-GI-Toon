# 保留的旧实现

当前开发改为 PMX 材质渲染和 MMD 流程。旧版源码、资源、构建和验证工具保留在不可变的 [v1.0.1](https://github.com/muchuanhehua/Hoyo-GI-Toon/tree/v1.0.1)，原安装包及本地原始证据保留。

| 退出本轮的内容 | 旧版入口 | 后续用途 |
|---|---|---|
| Better FBX 导入、JSON 与额外贴图解析 | `importers.py`、`asset_resolver.py`、`material_protocol.py` | 后续重新评估 FBX 与附件资产 |
| 主体及附件分类、混合面筛选 | `subjects.py`、`surface_layers.py` | 保留旧识别与数据保护依据 |
| 表情列表、手动强度与重置 | `expressions.py` | 原用于静帧调表情；MMD 主线交给既有 Morph 和动画 |
| 取景与展示预设、背景与地面 | `framing.py`、`presentation.py`、`panels.py` | 保留旧构图与临时资源处理记录 |
| FBX 眼层、面料、反射与法线扩展 | `eye_layers.py`、`eye_surfaces.py`、`textiles.py`、`reflections.py`、`normal_maps.py` | 保留源节点、引用和对照证据 |

旧工程使用 1.0.1 继续打开；当前重构使用新场景重新导入 PMX。用户原 FBX／PMX、贴图、保存工程和旧发布标签不做删除或转换。

旧版的 [功能覆盖](https://github.com/muchuanhehua/Hoyo-GI-Toon/blob/v1.0.1/design/workflow-coverage.md)、[材质核对](https://github.com/muchuanhehua/Hoyo-GI-Toon/blob/v1.0.1/design/material-coverage.md) 和 [游戏截图评审](https://github.com/muchuanhehua/Hoyo-GI-Toon/blob/v1.0.1/design/GAME-REFERENCE-REVIEW.md) 随标签保留，不作为当前候选的验证结论。
