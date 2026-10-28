"""Persist character ownership and only user-adjustable rendering settings."""
import bpy
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup


def update_appearance(self, context):
    if not self.managed or self.building:
        return
    from .workflow import refresh_character
    refresh_character(self.id_data)


class HGTMaterialBinding(PropertyGroup):
    source: PointerProperty(type=bpy.types.Material)
    generated: PointerProperty(type=bpy.types.Material)
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


class HGTCharacterSettings(PropertyGroup):
    managed: BoolProperty()
    building: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})
    uid: StringProperty()
    source_file: StringProperty(subtype="FILE_PATH")
    height: FloatProperty(default=1.7)
    bindings: CollectionProperty(type=HGTMaterialBinding)
    slots: CollectionProperty(type=HGTSlotSnapshot)
    meshes: CollectionProperty(type=HGTMeshReference)
    light: PointerProperty(type=bpy.types.Object)
    head: PointerProperty(type=bpy.types.Object)
    head_forward: FloatVectorProperty(size=3, default=(0, -1, 0))
    head_right: FloatVectorProperty(size=3, default=(1, 0, 0))
    threshold: FloatProperty(name="明暗分界", default=0.5, min=0.05, max=0.95, update=update_appearance)
    softness: FloatProperty(name="阴影柔和度", default=0.06, min=0.005, max=0.4, update=update_appearance)
    rim: FloatProperty(name="轮廓光", default=0.12, min=0, max=1, update=update_appearance)
    outline: FloatProperty(name="描边", default=1.0, min=0, max=3, update=update_appearance)
    shadow_color: FloatVectorProperty(name="阴影色", subtype="COLOR", size=4,
        default=(0.62, 0.67, 0.78, 1), min=0, max=1, update=update_appearance)
    light_azimuth: FloatProperty(name="光照方位", subtype="ANGLE", default=0.65, min=-3.14159, max=3.14159, update=update_appearance)
    light_elevation: FloatProperty(name="光照高度", subtype="ANGLE", default=0.6, min=-1.4, max=1.55, update=update_appearance)
    light_energy: FloatProperty(name="光照强度", default=2, min=0, max=10, update=update_appearance)


CLASSES = (HGTMaterialBinding, HGTSlotSnapshot, HGTMeshReference, HGTCharacterSettings)


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
