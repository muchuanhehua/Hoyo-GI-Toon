"""Persist character ownership and only user-adjustable rendering settings."""
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup


def update_appearance(self, context):
    if not self.managed or self.building:
        return
    from .workflow import refresh_character
    refresh_character(self.id_data)


def update_view(self, context):
    if self.managed and not self.building and context.scene.hgt_output.camera == self.camera:
        from .framing import frame
        frame(context.scene, self.id_data)


def update_floor(self, context):
    if not self.managed or self.building:
        return
    from .framing import is_auto
    if context.scene.hgt_output.camera == self.camera and is_auto(self.id_data):
        if self.show_floor and self.view_elevation < .12:
            self.floor_previous_elevation = self.view_elevation
            self.view_elevation = .12
        elif not self.show_floor and abs(self.view_elevation - .12) < 1e-6:
            self.view_elevation = self.floor_previous_elevation


def update_expression(self, context):
    from .expressions import set_value
    set_value(self)


class HGTShapeTarget(PropertyGroup):
    object: PointerProperty(type=bpy.types.Object)
    key: StringProperty()
    original_value: FloatProperty()
    driver_muted: BoolProperty()


class HGTExpression(PropertyGroup):
    label: StringProperty()
    value: FloatProperty(name='强度', default=0, min=0, max=1, update=update_expression)
    touched: BoolProperty()
    targets: CollectionProperty(type=HGTShapeTarget)


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
    schema_version: IntProperty(default=0)
    source_digest: StringProperty()
    resource_digests: StringProperty(default='{}')
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
    camera_signature: StringProperty()
    auto_frame: BoolProperty(default=True)
    shot: EnumProperty(name='构图', items=[('FULL', '全身', ''), ('HALF', '半身', ''), ('HEAD', '头像', '')], default='FULL', update=update_view)
    view_azimuth: FloatProperty(name='水平角度', subtype='ANGLE', default=0, min=-3.14159, max=3.14159, update=update_view)
    view_elevation: FloatProperty(name='俯仰角度', subtype='ANGLE', default=0, min=-1.2, max=1.2, update=update_view)
    frame_margin: FloatProperty(name='留白', default=.15, min=.02, max=.8, update=update_view)
    show_floor: BoolProperty(name='地面', default=False, update=update_floor)
    floor_previous_elevation: FloatProperty()
    expressions_version: IntProperty(default=0)
    expressions: CollectionProperty(type=HGTExpression)
    has_expression_edits: BoolProperty(default=False)
    active_expression: IntProperty(default=0)
    gaze_bones: CollectionProperty(type=HGTGazeBone)
    look_camera: BoolProperty(default=False)
    shadow_position: FloatProperty(name="阴影位置", default=0.55, min=0, max=1, update=update_appearance)
    outline: FloatProperty(name="描边", default=0.25, min=0, max=1, update=update_appearance)
    light_azimuth: FloatProperty(name="光照方位", subtype="ANGLE", default=0.35, min=-3.14159, max=3.14159, update=update_appearance)
    light_elevation: FloatProperty(name="光照高度", subtype="ANGLE", default=0.35, min=-1.55, max=1.55, update=update_appearance)


class HGTOutputSettings(PropertyGroup):
    camera: PointerProperty(name="相机", type=bpy.types.Object, poll=lambda self, obj: obj.type == "CAMERA")
    width: IntProperty(name="宽", default=1024, min=64, max=16384)
    height: IntProperty(name="高", default=1536, min=64, max=16384)
    transparent: BoolProperty(name="透明背景", default=True)
    background_color: FloatVectorProperty(name='背景', subtype='COLOR', size=3, default=(.04, .055, .08), min=0, max=1)
    filepath: StringProperty(name="保存到", subtype="FILE_PATH")
    last_render: StringProperty(subtype='FILE_PATH')
    last_auto_path: StringProperty(subtype='FILE_PATH')
    post_processing: BoolProperty(name="后期", default=False)
    rendering: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})


def update_target(self, context):
    root = self.hgt_target
    if root and root.hgt_character.managed and root.hgt_character.camera:
        self.hgt_output.camera = root.hgt_character.camera
        from .rendering import configure_output
        configure_output(self, root)


CLASSES = (HGTShapeTarget, HGTExpression, HGTGazeBone, HGTMaterialBinding, HGTSlotSnapshot, HGTMeshReference, HGTControlReference,
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
