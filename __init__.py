"""Hoyo-GI-Toon: a dedicated Genshin character rendering workflow."""

bl_info = {
    "name": "Hoyo-GI-Toon",
    "author": "muchuanhehua",
    "version": (0, 7, 1),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > Hoyo-GI-Toon",
    "description": "原神角色导入、卡通材质、描边与调光",
    "category": "Material",
}

from . import panels, properties, rendering, workflow


def register():
    properties.register()
    rendering.register()
    workflow.register()
    panels.register()


def unregister():
    rendering.check_idle()
    panels.unregister()
    workflow.unregister()
    rendering.unregister()
    properties.unregister()
