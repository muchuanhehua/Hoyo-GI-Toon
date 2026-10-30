"""Hoyo-GI-Toon: a dedicated Genshin character rendering workflow."""

bl_info = {
    "name": "Hoyo-GI-Toon",
    "author": "muchuanhehua",
    "version": (2, 1, 0),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > Hoyo-GI-Toon",
    "description": "原神角色导入、卡通材质、描边与调光",
    "category": "Material",
}

from . import panels, properties, rendering, workflow, project_io


def register():
    properties.register()
    workflow.register()
    panels.register()
    project_io.register()


def unregister():
    rendering.check_idle()
    project_io.unregister()
    panels.unregister()
    workflow.unregister()
    properties.unregister()
