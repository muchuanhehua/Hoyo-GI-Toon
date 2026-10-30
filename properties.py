"""PMX workflow state, owned material controls and optional eye tracking."""
import bpy
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup

def update_appearance(self, context):
    root = self.id_data
    if not root.hgt_character.building:
        from .workflow import refresh_character
        refresh_character(root)

class HGTGazeBone(PropertyGroup):
    bone: StringProperty()
    helper: PointerProperty(type=bpy.types.Object)
    active_constraint: StringProperty()

class HGTMaterialBinding(PropertyGroup):
    source: PointerProperty(type=bpy.types.Material)
    generated: PointerProperty(type=bpy.types.Material)
    outline: PointerProperty(type=bpy.types.Material)
    source_name: StringProperty()
    role: StringProperty()
    tint: FloatVectorProperty(name='颜色', subtype='COLOR', size=3, default=(1, 1, 1), min=0, max=1, update=update_appearance)
    shadow_color: FloatVectorProperty(name='阴影颜色', subtype='COLOR', size=3, default=(0.8, 0.8, 0.8), min=0, max=1, update=update_appearance)
    outline_color: FloatVectorProperty(name='描边颜色', subtype='COLOR', size=3, default=(0, 0, 0), min=0, max=1, update=update_appearance)
    defaults: StringProperty()

class HGTSlotSnapshot(PropertyGroup):
    mesh: PointerProperty(type=bpy.types.Object)
    index: IntProperty()
    original: PointerProperty(type=bpy.types.Material)
    generated: PointerProperty(type=bpy.types.Material)

class HGTMeshReference(PropertyGroup):
    object: PointerProperty(type=bpy.types.Object)
    original_data: PointerProperty(type=bpy.types.Mesh)
    render_data: PointerProperty(type=bpy.types.Mesh)
    original_material_links: StringProperty()
    original_hidden: BoolProperty()
    original_view_hidden: BoolProperty()

class HGTControlReference(PropertyGroup):
    object: PointerProperty(type=bpy.types.Object)
    key: StringProperty()

class HGTCharacterSettings(PropertyGroup):
    imported: BoolProperty()
    managed: BoolProperty()
    building: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})
    schema_version: IntProperty(default=0)
    uid: StringProperty()
    source_file: StringProperty(subtype='FILE_PATH')
    source_format: StringProperty(default='pmx')
    source_digest: StringProperty()
    resource_digests: StringProperty(default='{}')
    source_root: PointerProperty(type=bpy.types.Object)
    source_armature: PointerProperty(type=bpy.types.Object)
    camera: PointerProperty(type=bpy.types.Object)
    light_source: PointerProperty(name='灯光', type=bpy.types.Object, poll=lambda self, obj: obj.type == 'LIGHT' and obj.data.type == 'SUN', update=update_appearance)
    light: PointerProperty(type=bpy.types.Object)
    head: PointerProperty(type=bpy.types.Object)
    global_properties: PointerProperty(type=bpy.types.NodeTree)
    light_vectors: PointerProperty(type=bpy.types.NodeTree)
    outline_graph: PointerProperty(type=bpy.types.NodeTree)
    has_outline: BoolProperty()
    height: FloatProperty(default=1.7)
    meshes: CollectionProperty(type=HGTMeshReference)
    slots: CollectionProperty(type=HGTSlotSnapshot)
    bindings: CollectionProperty(type=HGTMaterialBinding)
    controls: CollectionProperty(type=HGTControlReference)
    active_material: IntProperty(default=0)
    shadow_position: FloatProperty(name='阴影位置', default=0.55, min=0, max=1, update=update_appearance)
    outline: FloatProperty(name='描边粗细', default=0.25, min=0, max=1, update=update_appearance)
    initial_shadow: FloatProperty(default=0.55)
    initial_outline: FloatProperty(default=0.25)
    gaze_bones: CollectionProperty(type=HGTGazeBone)
    look_camera: BoolProperty(default=False)

def model_poll(self, obj):
    from .scene_models import source_root
    return source_root(obj) is not None and obj.name in self.objects


def update_model(self, context):
    from . import scene_models
    scene_models.remember_active(context)
    self.hgt_target = scene_models.tracked(self.hgt_model, self) if self.hgt_model else None


def update_light(self, context):
    from .workflow import current, refresh_character
    for root in tuple(self.objects):
        if current(root):
            if self.hgt_light is None:
                root.hgt_character.light_source = None
            refresh_character(root, scene=self)


CLASSES = (HGTGazeBone, HGTMaterialBinding, HGTSlotSnapshot, HGTMeshReference, HGTControlReference, HGTCharacterSettings)

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.hgt_character = PointerProperty(type=HGTCharacterSettings)
    bpy.types.Scene.hgt_target = PointerProperty(type=bpy.types.Object)
    bpy.types.Scene.hgt_model = PointerProperty(name='模型', type=bpy.types.Object, poll=model_poll, update=update_model)
    bpy.types.Scene.hgt_light = PointerProperty(name='灯光', type=bpy.types.Object, poll=lambda self, obj: obj.type == 'LIGHT' and obj.data.type == 'SUN' and obj.name in self.objects, update=update_light)

def unregister():
    del bpy.types.Scene.hgt_target
    del bpy.types.Scene.hgt_model
    del bpy.types.Scene.hgt_light
    del bpy.types.Object.hgt_character
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
