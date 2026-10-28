"""Persist character ownership and only user-adjustable rendering settings."""
import bpy
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup


def update_appearance(self, context):
    if not self.managed or self.building:
        return
    from .workflow import refresh_character
    refresh_character(self.id_data)


class HGTMaterialBinding(PropertyGroup):
    source: PointerProperty(type=bpy.types.Material)
    generated: PointerProperty(type=bpy.types.Material)
    outline: PointerProperty(type=bpy.types.Material)
    source_name: StringProperty()
    role: StringProperty()


class HGTSlotSnapshot(PropertyGroup):
    mesh: PointerProperty(type=bpy.types.Object)
    index: IntProperty()
    original: PointerProperty(type=bpy.types.Material)
    generated: PointerProperty(type=bpy.types.Material)


class HGTMeshReference(PropertyGroup):
    object: PointerProperty(type=bpy.types.Object)
    original_hidden: BoolProperty()
    original_view_hidden: BoolProperty()


class HGTControlReference(PropertyGroup):
    object: PointerProperty(type=bpy.types.Object)
    key: StringProperty()


class HGTCharacterSettings(PropertyGroup):
    managed: BoolProperty()
    building: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})
    uid: StringProperty()
    source_file: StringProperty(subtype="FILE_PATH")
    height: FloatProperty(default=1.7)
    bindings: CollectionProperty(type=HGTMaterialBinding)
    slots: CollectionProperty(type=HGTSlotSnapshot)
    meshes: CollectionProperty(type=HGTMeshReference)
    controls: CollectionProperty(type=HGTControlReference)
    global_properties: PointerProperty(type=bpy.types.NodeTree)
    light_vectors: PointerProperty(type=bpy.types.NodeTree)
    outline_graph: PointerProperty(type=bpy.types.NodeTree)
    light: PointerProperty(type=bpy.types.Object)
    head: PointerProperty(type=bpy.types.Object)
    shadow_position: FloatProperty(name="阴影位置", default=0.55, min=0, max=1, update=update_appearance)
    outline: FloatProperty(name="描边", default=0.25, min=0, max=1, update=update_appearance)
    light_azimuth: FloatProperty(name="光照方位", subtype="ANGLE", default=0, min=-3.14159, max=3.14159, update=update_appearance)
    light_elevation: FloatProperty(name="光照高度", subtype="ANGLE", default=0, min=-1.55, max=1.55, update=update_appearance)


CLASSES = (HGTMaterialBinding, HGTSlotSnapshot, HGTMeshReference, HGTControlReference, HGTCharacterSettings)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.hgt_character = PointerProperty(type=HGTCharacterSettings)
    bpy.types.Scene.hgt_target = PointerProperty(type=bpy.types.Object)


def unregister():
    del bpy.types.Scene.hgt_target
    del bpy.types.Object.hgt_character
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
