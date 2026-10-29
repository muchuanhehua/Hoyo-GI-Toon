"""Persist character ownership and only user-adjustable rendering settings."""
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
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
    original_data: PointerProperty(type=bpy.types.Mesh)
    render_data: PointerProperty(type=bpy.types.Mesh)
    original_material_links: StringProperty()
    original_hidden: BoolProperty()
    original_view_hidden: BoolProperty()
    participation: StringProperty()
    participation_basis: StringProperty()


class HGTControlReference(PropertyGroup):
    object: PointerProperty(type=bpy.types.Object)
    key: StringProperty()


PART_ROLES = [('BODY', '角色', '身体、头发、服装及角色装饰'),
              ('WEAPON', '武器', '按需加入出图的武器'),
              ('GLIDER', '风之翼', '按需加入出图的风之翼'),
              ('EFFECT', '特效／技能附件', '按需显示的特效或技能附件'),
              ('OTHER', '其它', '保留原状态，可自行调整归属')]


class HGTPartReference(PropertyGroup):
    key: IntProperty()
    object: PointerProperty(type=bpy.types.Object)
    armature: PointerProperty(type=bpy.types.Object)
    role: EnumProperty(items=PART_ROLES, default='OTHER')
    included: BoolProperty(default=True)
    locked: BoolProperty()
    basis: StringProperty()
    face_count: IntProperty()
    source_slots: StringProperty()


def update_part_edit(self, context):
    self.included=self.role in {'BODY','OTHER'}


class HGTPartEdit(PropertyGroup):
    key: IntProperty()
    label: StringProperty()
    role: EnumProperty(items=PART_ROLES, default='OTHER', update=update_part_edit)
    included: BoolProperty(name='显示')


class HGTCharacterSettings(PropertyGroup):
    managed: BoolProperty()
    building: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})
    uid: StringProperty()
    source_file: StringProperty(subtype="FILE_PATH")
    source_format: StringProperty(default='fbx')
    source_root: PointerProperty(type=bpy.types.Object)
    source_armature: PointerProperty(type=bpy.types.Object)
    height: FloatProperty(default=1.7)
    bindings: CollectionProperty(type=HGTMaterialBinding)
    slots: CollectionProperty(type=HGTSlotSnapshot)
    meshes: CollectionProperty(type=HGTMeshReference)
    controls: CollectionProperty(type=HGTControlReference)
    parts: CollectionProperty(type=HGTPartReference)
    parts_version: IntProperty(default=0)
    global_properties: PointerProperty(type=bpy.types.NodeTree)
    light_vectors: PointerProperty(type=bpy.types.NodeTree)
    outline_graph: PointerProperty(type=bpy.types.NodeTree)
    light: PointerProperty(type=bpy.types.Object)
    head: PointerProperty(type=bpy.types.Object)
    camera: PointerProperty(type=bpy.types.Object)
    shadow_position: FloatProperty(name="阴影位置", default=0.55, min=0, max=1, update=update_appearance)
    outline: FloatProperty(name="描边", default=0.25, min=0, max=1, update=update_appearance)
    light_azimuth: FloatProperty(name="光照方位", subtype="ANGLE", default=0.35, min=-3.14159, max=3.14159, update=update_appearance)
    light_elevation: FloatProperty(name="光照高度", subtype="ANGLE", default=0.35, min=-1.55, max=1.55, update=update_appearance)


class HGTOutputSettings(PropertyGroup):
    camera: PointerProperty(name="相机", type=bpy.types.Object, poll=lambda self, obj: obj.type == "CAMERA")
    width: IntProperty(name="宽", default=1024, min=64, max=16384)
    height: IntProperty(name="高", default=1536, min=64, max=16384)
    transparent: BoolProperty(name="透明背景", default=True)
    filepath: StringProperty(name="保存到", subtype="FILE_PATH")
    last_render: StringProperty(subtype='FILE_PATH')
    post_processing: BoolProperty(name="后期", default=False)
    rendering: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})


def update_target(self, context):
    root = self.hgt_target
    if root and root.hgt_character.managed and root.hgt_character.camera:
        self.hgt_output.camera = root.hgt_character.camera


CLASSES = (HGTMaterialBinding, HGTSlotSnapshot, HGTMeshReference, HGTControlReference,
           HGTPartReference, HGTPartEdit, HGTCharacterSettings,
           HGTOutputSettings)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.hgt_character = PointerProperty(type=HGTCharacterSettings)
    bpy.types.Scene.hgt_output = PointerProperty(type=HGTOutputSettings)
    bpy.types.Scene.hgt_target = PointerProperty(type=bpy.types.Object, update=update_target)


def unregister():
    del bpy.types.Scene.hgt_target
    del bpy.types.Scene.hgt_output
    del bpy.types.Object.hgt_character
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
