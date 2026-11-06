"""PMX workflow state, owned material controls and optional eye tracking."""
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup
from .face_catalog import ITEMS as SDF_ITEMS

def update_appearance(self, context):
    root = self.id_data
    if not root.hgt_character.building:
        from .workflow import refresh_character
        refresh_character(root)


def update_light_source(self, context):
    if self.light_source:
        self.light_reference_energy = (2 if self.light_source.get('hgt_scene_light')
                                       else max(self.light_source.data.energy, 1))
    update_appearance(self, context)


def update_uniforms(self, context):
    if self.managed and not self.building:
        from .shaders import set_controls
        set_controls(self.id_data)
        from .rendering import preview_materials
        preview_materials(context)


def update_softness(self, context):
    if self.building:
        return
    self.building = True
    try:
        legacy_range = max(.001, self.shadow_softness)
        self.shadow_transition = legacy_range
        self.face_softness = min(.2, max(.001, legacy_range * (.02 / .035) * self.face_softness_adjust))
    finally:
        self.building = False
    update_uniforms(self, context)


def update_body_softness(self, context):
    if not self.building:
        self.shadow_softness = self.shadow_transition


def update_face_softness(self, context):
    if not self.building:
        self.face_softness_adjust = self.face_softness / (max(.001, self.shadow_softness) * (.02 / .035))


def get_shadow_bias(self):
    from .pmx_materials import DEFAULT_SHADOW_POSITION
    value = self.shadow_position - DEFAULT_SHADOW_POSITION
    return 0.0 if abs(value) < 1e-6 else value


def set_shadow_bias(self, value):
    from .pmx_materials import DEFAULT_SHADOW_POSITION
    self.shadow_position = value + DEFAULT_SHADOW_POSITION


def get_outline_top(self):
    from .outline_profile import endpoint
    return endpoint(self, True)


def set_outline_top(self, value):
    from .outline_profile import set_endpoint
    set_endpoint(self, value, True)


def get_outline_lower(self):
    from .outline_profile import endpoint
    return endpoint(self, False)


def set_outline_lower(self, value):
    from .outline_profile import set_endpoint
    set_endpoint(self, value, False)


def get_outline_difference(self):
    from .outline_profile import difference
    return difference(self)


def set_outline_difference(self, value):
    from .outline_profile import set_difference
    set_difference(self, value)


def update_outline(self, context):
    if self.managed and not self.building:
        from .outlines import update
        for entry in self.meshes:
            if entry.object:
                update(entry.object, self.id_data)
        from .rendering import preview_materials
        preview_materials(context)


def update_material(self, context):
    if not self.id_data.hgt_character.building:
        from .material_controls import apply_binding
        apply_binding(self)
        from .rendering import preview_materials
        if context.scene:
            preview_materials(context)


def update_sdf(self, context):
    if self.building:
        return
    if self.managed:
        from .workflow import change_face_sdf
        change_face_sdf(self.id_data, context)


def update_lighting(self, context):
    from .lighting import update_parameters
    update_parameters(self.id_data, self)


def update_glow(self, context):
    from . import glow
    try:
        glow.update(self.id_data)
        self.error = ''
    except (ValueError, RuntimeError) as exc:
        self.error = str(exc)
        import traceback
        traceback.print_exc()


class HGTGlowSettings(PropertyGroup):
    threshold: FloatProperty(name='辉光阈值', description='仅亮于此值的区域产生辉光；越低覆盖越广',
                             default=.85, min=0, max=2, update=update_glow)
    strength: FloatProperty(name='辉光强度', default=1, min=0, max=2, update=update_glow)
    size: FloatProperty(name='扩散范围', description='高亮周围光晕的扩散范围',
                        default=.5, min=0, max=1, update=update_glow)
    error: StringProperty(options={'SKIP_SAVE'})
    target: PointerProperty(type=bpy.types.Object)
    scope_id: StringProperty()
    source_collection: PointerProperty(type=bpy.types.Collection)
    master_collection: PointerProperty(type=bpy.types.Collection)
    render_layer: StringProperty()
    base_layer: StringProperty()
    previous_single_layer: BoolProperty()

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
    tint: FloatVectorProperty(name='颜色', subtype='COLOR', size=3, default=(1, 1, 1), min=0, max=1, update=update_material)
    shadow_color: FloatVectorProperty(name='阴影颜色', subtype='COLOR', size=3, default=(0.8, 0.8, 0.8), min=0, max=1, update=update_material)
    outline_color: FloatVectorProperty(name='描边颜色', subtype='COLOR', size=3, default=(0, 0, 0), min=0, max=1, update=update_material)
    brightness: FloatProperty(name='亮度', default=1, min=0, max=2, update=update_material)
    saturation: FloatProperty(name='饱和度', default=1, min=0, max=2, update=update_material)
    opacity: FloatProperty(name='不透明度', default=1, min=0, max=1, update=update_material)
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


class HGTVisibility(PropertyGroup):
    object: PointerProperty(type=bpy.types.Object)
    hidden: BoolProperty()

class HGTScenePresetSettings(PropertyGroup):
    preset: StringProperty()
    uid: StringProperty()
    collection: PointerProperty(type=bpy.types.Collection)
    previous_world: PointerProperty(type=bpy.types.World)
    previous_camera: PointerProperty(type=bpy.types.Object)
    previous_light: PointerProperty(type=bpy.types.Object)
    world: PointerProperty(type=bpy.types.World)
    camera: PointerProperty(type=bpy.types.Object)
    light: PointerProperty(type=bpy.types.Object)
    muted_light: PointerProperty(type=bpy.types.Object)
    muted_render: BoolProperty()
    muted_viewport: BoolProperty()


class HGTLightParameters(PropertyGroup):
    key: StringProperty()
    energy: FloatProperty(name='强度', default=2, min=0, soft_max=10, update=update_lighting)
    color: FloatVectorProperty(name='颜色', subtype='COLOR', size=3, default=(1, 1, 1), min=0, max=1, update=update_lighting)
    azimuth: FloatProperty(name='光向方位', subtype='ANGLE', min=-3.141593, max=3.141593, update=update_lighting)
    elevation: FloatProperty(name='光向高度', subtype='ANGLE', min=-1.570796, max=1.570796, update=update_lighting)
    angle: FloatProperty(name='光源角度', subtype='ANGLE', default=.1, min=0, max=3.141593, update=update_lighting)


class HGTLightingSettings(PropertyGroup):
    selected: EnumProperty(name='打光预设', items=(('DEFAULT', '默认光', ''), ('SOFT', '柔和正面', ''),
                         ('SIDE', '侧面塑形', ''), ('BACK', '背光轮廓', '')))
    active: StringProperty()
    presets: CollectionProperty(type=HGTLightParameters)

class HGTCharacterSettings(PropertyGroup):
    imported: BoolProperty()
    managed: BoolProperty()
    building: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})
    lighting_version: IntProperty(default=0)
    schema_version: IntProperty(default=0)
    uid: StringProperty()
    source_file: StringProperty(subtype='FILE_PATH')
    face_resource_directory: StringProperty(subtype='DIR_PATH')
    face_sdf_preset: EnumProperty(name='脸部 SDF', items=SDF_ITEMS, default='AUTO', update=update_sdf)
    applied_sdf_preset: StringProperty(default='AUTO')
    preview_error: StringProperty(options={'SKIP_SAVE'})
    source_format: StringProperty(default='pmx')
    source_digest: StringProperty()
    resource_digests: StringProperty(default='{}')
    source_root: PointerProperty(type=bpy.types.Object)
    source_armature: PointerProperty(type=bpy.types.Object)
    camera: PointerProperty(type=bpy.types.Object)
    light_source: PointerProperty(name='灯光', type=bpy.types.Object, poll=lambda self, obj: obj.type == 'LIGHT' and obj.data.type in {'SUN', 'AREA', 'POINT', 'SPOT'}, update=update_light_source)
    light_reference_energy: FloatProperty(default=2, min=1e-6)
    light: PointerProperty(type=bpy.types.Object)
    head: PointerProperty(type=bpy.types.Object)
    global_properties: PointerProperty(type=bpy.types.NodeTree)
    light_vectors: PointerProperty(type=bpy.types.NodeTree)
    outline_graph: PointerProperty(type=bpy.types.NodeTree)
    outline_profile: PointerProperty(type=bpy.types.NodeTree)
    outline_profile_state: StringProperty()
    has_outline: BoolProperty()
    height: FloatProperty(default=1.7)
    meshes: CollectionProperty(type=HGTMeshReference)
    slots: CollectionProperty(type=HGTSlotSnapshot)
    bindings: CollectionProperty(type=HGTMaterialBinding)
    controls: CollectionProperty(type=HGTControlReference)
    display_meshes: CollectionProperty(type=HGTVisibility)
    active_material: IntProperty(default=0)
    show_material_advanced: BoolProperty(name='高级', default=False)
    shadow_bias: FloatProperty(name='明暗分界偏移', description='微调明暗覆盖范围，0 为默认；日常光向通过打光控制',
                               min=-.52, max=.48, soft_min=-.3, soft_max=.3, get=get_shadow_bias, set=set_shadow_bias)
    shadow_softness: FloatProperty(name='整体阴影软硬', description='0 保留二分阴影；数值越大，只柔化身体、头发与脸部的原明暗边界',
                                   default=.035, min=0, max=.5, precision=3, update=update_softness)
    face_softness_adjust: FloatProperty(name='脸部软硬补偿', description='脸部 SDF 相对整体阴影软硬的比例', default=1,
                                        min=0, soft_max=3, update=update_softness)
    shadow_position: FloatProperty(name='明暗分界阈值', default=0.55, min=0, max=1, update=update_uniforms)
    shadow_transition: FloatProperty(default=0.035, min=0.001, max=0.5, update=update_body_softness)
    face_softness: FloatProperty(default=0.02, min=0.001, max=0.2, update=update_face_softness)
    outline: FloatProperty(name='描边粗细', default=0.25, min=0, soft_max=5, update=update_outline)
    outline_difference: FloatProperty(name='上下描边差', description='0 上下等粗；正值上粗下细，负值上细下粗；上下同时变化',
                                      min=-1, max=1, precision=2, get=get_outline_difference,
                                      set=set_outline_difference, update=update_outline)
    outline_top: FloatProperty(name='顶部比例', description='旧工程兼容参数', min=0, soft_max=1,
                               get=get_outline_top, set=set_outline_top, update=update_outline)
    outline_lower: FloatProperty(name='底部比例', description='旧工程兼容参数', min=0, soft_max=1,
                                 get=get_outline_lower, set=set_outline_lower, update=update_outline)
    initial_shadow: FloatProperty(default=0.55)
    initial_face_softness: FloatProperty(default=0.02)
    initial_outline: FloatProperty(default=0.25)
    gaze_bones: CollectionProperty(type=HGTGazeBone)
    look_camera: BoolProperty(default=False)

def model_poll(self, obj):
    from .scene_models import model_root
    return model_root(obj) and obj.name in self.objects


def update_model(self, context):
    from . import scene_models
    obj = self.hgt_model
    root = scene_models.source_root(obj)
    if obj and (obj != root or not scene_models.model_root(obj)):
        self.hgt_model = root if scene_models.model_root(root) and root.name in self.objects else None
        return
    scene_models.remember_active(context)
    self.hgt_target = scene_models.tracked(self.hgt_model, self) if self.hgt_model else None
    from . import glow
    if glow.is_active(self):
        glow.update_target(self)


def update_light(self, context):
    from .lighting import select_light
    select_light(self)
    from .workflow import current, refresh_character
    for root in tuple(self.objects):
        if current(root):
            if self.hgt_light is None:
                root.hgt_character.light_source = None
            refresh_character(root, scene=self, appearance=False)


CLASSES = (HGTGazeBone, HGTMaterialBinding, HGTSlotSnapshot, HGTMeshReference, HGTControlReference, HGTVisibility,
           HGTScenePresetSettings, HGTLightParameters, HGTLightingSettings, HGTCharacterSettings, HGTGlowSettings)

def register():
    from .scene_presets import PRESET_ITEMS
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.hgt_character = PointerProperty(type=HGTCharacterSettings)
    bpy.types.Scene.hgt_target = PointerProperty(type=bpy.types.Object)
    bpy.types.Scene.hgt_model = PointerProperty(name='模型', type=bpy.types.Object, poll=model_poll, update=update_model)
    bpy.types.Scene.hgt_light = PointerProperty(name='灯光', type=bpy.types.Object, poll=lambda self, obj: obj.type == 'LIGHT' and obj.data.type in {'SUN', 'AREA', 'POINT', 'SPOT'} and obj.name in self.objects, update=update_light)
    bpy.types.Scene.hgt_scene = PointerProperty(type=HGTScenePresetSettings)
    bpy.types.Scene.hgt_scene_preset = EnumProperty(name='场景预设', items=PRESET_ITEMS)
    bpy.types.Scene.hgt_lighting = PointerProperty(type=HGTLightingSettings)
    bpy.types.Scene.hgt_glow = PointerProperty(type=HGTGlowSettings)

def unregister():
    del bpy.types.Scene.hgt_glow
    del bpy.types.Scene.hgt_lighting
    del bpy.types.Scene.hgt_scene_preset
    del bpy.types.Scene.hgt_scene
    del bpy.types.Scene.hgt_target
    del bpy.types.Scene.hgt_model
    del bpy.types.Scene.hgt_light
    del bpy.types.Object.hgt_character
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
