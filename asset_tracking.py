"""Import batches, reversible render data and scoped failure cleanup."""
from dataclasses import dataclass
import bpy

DATA_KINDS = ("objects", "collections", "meshes", "armatures", "materials", "node_groups",
              "images", "actions", "shape_keys", "curves", "lights", "cameras", "texts")


def data_pointers():
    return {kind: {item.as_pointer() for item in getattr(bpy.data, kind)} for kind in DATA_KINDS}


def new_data(before):
    return {kind: tuple(item for item in getattr(bpy.data, kind)
                        if item.as_pointer() not in before[kind]) for kind in DATA_KINDS}


def scene_state(context):
    scene = context.scene
    fields = ((scene, "frame_start"), (scene, "frame_end"), (scene, "frame_current"),
              (scene.unit_settings, "system"), (scene.unit_settings, "scale_length"),
              (scene.render, "fps"), (scene.render, "fps_base"),
              (scene.render, "engine"), (scene.view_settings, "view_transform"),
              (scene.render, "film_transparent"), (scene.render.image_settings, "file_format"),
              (scene.render.image_settings, "color_mode"), (scene, "camera"), (scene, "hgt_target"))
    return [(owner, name, getattr(owner, name)) for owner, name in fields if hasattr(owner, name)]


def restore_state(state):
    for owner, name, value in state:
        if getattr(owner, name) != value:
            setattr(owner, name, value)


class DataTransaction:
    """Rollback deletes only IDs created after entry; existing IDs are untouched."""
    def __init__(self, context):
        self.context = context
        self.before = data_pointers()
        self.state = scene_state(context)
        self.selected = tuple(context.selected_objects)
        self.active = context.view_layer.objects.active

    def rollback(self):
        created = new_data(self.before)
        # Batch removal resolves dependencies, including shape-key data, in one operation.
        bpy.data.batch_remove(ids={item for values in created.values() for item in values})
        restore_state(self.state)
        for obj in self.context.selected_objects:
            obj.select_set(False)
        for obj in self.selected:
            obj.select_set(True)
        self.context.view_layer.objects.active = self.active


@dataclass
class ImportBatch:
    source: str
    data: dict
    parameters: dict
    operator: str = "better_import.fbx"

    @property
    def objects(self):
        return self.data["objects"]

    @property
    def meshes(self):
        return tuple(obj for obj in self.objects if obj.type == "MESH")


def derive_mesh(entry, uid):
    """Render-only aliases and material slots never alter the imported Mesh ID."""
    obj = entry.object
    entry.original_data = obj.data
    entry.original_material_links = ",".join(slot.link for slot in obj.material_slots)
    derived = obj.data.copy()
    derived.name = f"HGT • {obj.name} • Render"
    derived["hgt_owner"] = uid
    obj.data = derived
    entry.render_data = derived
    if not derived.uv_layers.get("UV1"):
        uv = derived.uv_layers.new(name="UV1")
        source = entry.original_data.uv_layers.active
        if source:
            # Preserve UV seams; the extra channel is a render alias of the source UV.
            values = [0.0] * (len(source.data) * 2)
            source.data.foreach_get("uv", values)
            uv.data.foreach_set("uv", values)
    color = derived.color_attributes.active_color
    if color and not derived.color_attributes.get("Col"):
        alias = derived.color_attributes.new(name="Col", type=color.data_type, domain=color.domain)
        values = [0.0] * (len(color.data) * 4)
        color.data.foreach_get("color", values)
        alias.data.foreach_set("color", values)
    return derived


def restore_mesh(entry):
    obj = entry.object
    if not obj or not entry.original_data:
        return
    if obj.data == entry.render_data:
        obj.data = entry.original_data
    links = entry.original_material_links.split(",") if entry.original_material_links else []
    for slot, link in zip(obj.material_slots, links):
        slot.link = link
    entry.render_data = None
    entry.original_data = None


def remove_render_data(uid):
    """Remove owned helpers and unused render IDs; keep every imported object and ID."""
    candidates = {item for kind in DATA_KINDS if kind not in {"objects", "collections"}
                  for item in getattr(bpy.data, kind) if item.get("hgt_owner") == uid}
    candidates.update(obj for obj in bpy.data.objects if obj.get("hgt_owner") == uid and obj.get("hgt_helper"))
    collections = {c for c in bpy.data.collections if c.get("hgt_owner") == uid}
    references = bpy.data.user_map(subset=candidates)
    # Modifier socket fields can retain stale user counters after removal.
    # Follow actual ID references, and keep resources adopted by outside users.
    def outside_users(item, users):
        outside = users - candidates - collections
        if isinstance(item, bpy.types.Object):
            # Scene membership is already represented by the owning collection.
            outside = {user for user in outside if not isinstance(user, bpy.types.Scene) or user.camera == item}
        return outside
    protected = {item for item, users in references.items() if outside_users(item, users)}
    changed = True
    while changed:
        added = {item for item, users in references.items() if users & protected} - protected
        changed = bool(added)
        protected.update(added)
    discard = candidates - protected
    if discard:
        bpy.data.batch_remove(ids=discard)
