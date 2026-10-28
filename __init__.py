"""Hoyo-GI-Toon: a dedicated Genshin character rendering workflow."""

bl_info = {
    "name": "Hoyo-GI-Toon",
    "author": "muchuanhehua",
    "version": (0, 2, 2),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > Hoyo-GI-Toon",
    "description": "原神角色导入、卡通材质、描边与调光",
    "category": "Material",
}

from . import panels, properties, workflow


def register():
    properties.register()
    workflow.register()
    panels.register()


def unregister():
    panels.unregister()
    workflow.unregister()
    properties.unregister()
