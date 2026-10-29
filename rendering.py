"""Owned framing and PNG output through a temporary scene."""
from dataclasses import dataclass, field
from pathlib import Path
import re
import struct
import uuid
import bpy
from bpy.app.handlers import persistent
from mathutils import Vector
from . import post_processing

_JOBS = {}


def character_bounds(root):
    meshes = [entry.object for entry in root.hgt_character.meshes
              if entry.object and entry.render_data and not entry.object.hide_render]
    # Frame posed base geometry. Render/view-dependent outline geometry must not
    # determine the camera, and the character's modifiers stay untouched.
    probes = []
    try:
        for obj in meshes:
            probe = obj.copy()
            probe.name = "HGT Framing"
            for modifier in tuple(probe.modifiers):
                if modifier.type == "NODES" and modifier.node_group and modifier.node_group.get("hgt_owner"):
                    probe.modifiers.remove(modifier)
            bpy.context.scene.collection.objects.link(probe)
            probes.append(probe)
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        points = [obj.matrix_world @ Vector(corner) for obj in probes
                  for corner in obj.evaluated_get(graph).bound_box]
    finally:
        if probes:
            bpy.data.batch_remove(ids=set(probes))
    if not points:
        raise ValueError("角色没有可用于构图的网格")
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    if high.z - low.z < 1e-5:
        raise ValueError("角色尺寸无效，请检查导入模型")
    return low, high


def frame_camera(scene, root):
    camera = scene.hgt_output.camera
    if camera is None or camera.type != "CAMERA":
        raise ValueError("请在输出中选择相机")
    if camera != root.hgt_character.camera:
        raise ValueError("请选择本角色的相机后重新构图；其他相机可直接用于渲染")
    bpy.context.view_layer.update()
    low, high = character_bounds(root)
    center = (low + high) * .5
    height = high.z - low.z
    aspect = scene.hgt_output.width / scene.hgt_output.height
    camera.data.type = "ORTHO"
    camera.data.sensor_fit = "VERTICAL"
    camera.data.ortho_scale = max(height, (high.x - low.x) / aspect) * 1.15
    camera.data.clip_start = max(.001, height * .001)
    camera.data.clip_end = max(100, height * 10)
    camera.location = center + Vector((0, -height * 3, 0))
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()


def prepare(scene, root, collection):
    settings = root.hgt_character
    camera = settings.camera
    if camera is None:
        data = bpy.data.cameras.new(f"HGT • {root.name}")
        data["hgt_owner"] = settings.uid
        camera = bpy.data.objects.new(data.name, data)
        camera["hgt_owner"], camera["hgt_helper"] = settings.uid, True
        collection.objects.link(camera)
        settings.camera = camera
    scene.hgt_output.camera = camera
    frame_camera(scene, root)
    if not scene.hgt_output.filepath:
        base = Path(bpy.data.filepath).parent if bpy.data.filepath else Path.home() / "Pictures" / "Hoyo-GI-Toon"
        name = re.sub(r'[<>:"/\\|?*]', "_", root.name).strip(" .") or "角色"
        scene.hgt_output.filepath = str(base / f"{name}.png")


def preview(context, root):
    if bpy.app.background or not context.window:
        return
    area = context.area if context.area and context.area.type == "VIEW_3D" else next(
        (area for area in context.window.screen.areas if area.type == "VIEW_3D"), None)
    if area is None:
        return
    space = area.spaces.active
    space.use_local_camera = True
    space.camera = root.hgt_character.camera
    space.region_3d.view_perspective = "CAMERA"
    space.shading.type = "MATERIAL"
    space.overlay.show_overlays = False


def output_path(scene):
    value = scene.hgt_output.filepath.strip()
    if not value:
        raise ValueError("请在输出中设置 PNG 保存位置")
    path = Path(bpy.path.abspath(value)).expanduser()
    if not path.suffix:
        path = path.with_suffix(".png")
    if path.suffix.lower() != ".png":
        raise ValueError("请选择 PNG 保存路径")
    if path.exists() and path.is_dir():
        raise ValueError("保存位置需要包含文件名，例如 角色.png")
    return path.resolve()


@dataclass
class RenderJob:
    source: object
    proxy: object
    path: Path
    size: tuple
    resources: set = field(default_factory=set)
    state: str = "running"
    previous_file: tuple | None = None


def _file_signature(path):
    if not path.is_file():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _validate_png(job):
    if not job.path.is_file() or _file_signature(job.path) == job.previous_file:
        raise RuntimeError("渲染结束但图片未保存，请检查输出路径和目录权限")
    with job.path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise RuntimeError("保存的文件不是有效 PNG")
    if struct.unpack(">II", header[16:24]) != job.size:
        raise RuntimeError("保存图片的尺寸与输出设置不一致")


def _copy_compositor(tree, source, proxy, resources, copies=None):
    copies = {} if copies is None else copies
    if tree in copies:
        return copies[tree]
    copied = tree.copy()
    copied.use_fake_user = False
    copies[tree] = copied
    resources.add(copied)
    for node in copied.nodes:
        if node.type == "R_LAYERS" and node.scene in {None, source}:
            node.scene = proxy
        if node.type == "GROUP" and node.node_tree:
            node.node_tree = _copy_compositor(node.node_tree, source, proxy, resources, copies)
        if node.type == "OUTPUT_FILE":
            node.mute = True
    return copied


def _proxy(scene, root, path):
    proxy = scene.copy()
    proxy.name = "HGT Render • " + uuid.uuid4().hex[:8]
    job = RenderJob(scene, proxy, path, (scene.hgt_output.width, scene.hgt_output.height))
    job.resources.add(proxy)
    try:
        proxy.camera = scene.hgt_output.camera
        proxy.render.engine = "BLENDER_EEVEE"
        proxy.view_settings.view_transform = "Standard"
        proxy.view_settings.look = 'None'
        proxy.view_settings.exposure = 0
        proxy.view_settings.gamma = 1
        proxy.render.resolution_x, proxy.render.resolution_y = job.size
        proxy.render.resolution_percentage = 100
        proxy.render.pixel_aspect_x = proxy.render.pixel_aspect_y = 1
        proxy.render.film_transparent = scene.hgt_output.transparent
        proxy.render.image_settings.file_format = "PNG"
        proxy.render.image_settings.color_mode = "RGBA"
        proxy.render.image_settings.color_depth = "8"
        proxy.render.use_file_extension = True
        proxy.render.use_sequencer = False
        proxy.render.use_compositing = scene.render.use_compositing or scene.hgt_output.post_processing
        proxy.render.filepath = str(path)
        if scene.compositing_node_group:
            proxy.compositing_node_group = _copy_compositor(scene.compositing_node_group, scene, proxy, job.resources)
        if scene.hgt_output.post_processing:
            post_processing.configure(proxy, root, job.resources)
        if proxy.compositing_node_group:
            _render_alpha(proxy)
        return job
    except Exception:
        bpy.data.batch_remove(ids=job.resources)
        raise


def _render_alpha(scene):
    tree = scene.compositing_node_group
    output = next((n for n in tree.nodes if n.type == "GROUP_OUTPUT" and n.is_active_output), None)
    if output is None or not output.inputs.get("Image") or not output.inputs["Image"].is_linked:
        raise ValueError("当前合成器没有已连接的 Image 输出")
    source = output.inputs["Image"].links[0].from_socket
    layers = tree.nodes.new("CompositorNodeRLayers")
    layers.scene = scene
    alpha = tree.nodes.new("CompositorNodeSetAlpha")
    alpha.inputs["Type"].default_value = "Replace Alpha"
    tree.links.new(source, alpha.inputs["Image"])
    tree.links.new(layers.outputs["Alpha"], alpha.inputs["Alpha"])
    tree.links.new(alpha.outputs["Image"], output.inputs["Image"])


def start(scene, root, invoke=False):
    if _JOBS or bpy.app.is_job_running("RENDER"):
        raise ValueError("请等待当前渲染结束")
    if not root or not root.hgt_character.managed:
        raise ValueError("请先导入模型")
    camera = scene.hgt_output.camera
    if camera is None or camera.type != "CAMERA" or camera.name not in scene.objects:
        raise ValueError("请在输出中选择当前场景的相机")
    if camera == root.hgt_character.camera:
        frame_camera(scene, root)
    path = output_path(scene)
    path.parent.mkdir(parents=True, exist_ok=True)
    job = _proxy(scene, root, path)
    job.previous_file = _file_signature(path)
    key = job.proxy.name
    _JOBS[key] = job
    scene.hgt_output.rendering = True
    try:
        result = bpy.ops.render.render("INVOKE_DEFAULT" if invoke else "EXEC_DEFAULT",
                                       scene=key, write_still=True)
        if invoke:
            if result != {"RUNNING_MODAL"}:
                raise RuntimeError("渲染任务未启动")
            return key
        if result != {"FINISHED"}:
            raise RuntimeError("渲染未完成")
        job.state = "complete"
        return finish(key)
    except Exception:
        if key in _JOBS:
            _cleanup(key)
        raise


def _cleanup(key):
    job = _JOBS.pop(key)
    job.source.hgt_output.rendering = False
    bpy.data.batch_remove(ids=job.resources)


def finish(key):
    job = _JOBS[key]
    try:
        if job.state == "cancelled":
            raise RuntimeError("渲染已取消")
        _validate_png(job)
        return str(job.path)
    finally:
        _cleanup(key)


def job_state(key):
    return _JOBS[key].state


@persistent
def render_complete(scene, *_):
    if scene.name in _JOBS:
        _JOBS[scene.name].state = "complete"


@persistent
def render_cancel(scene, *_):
    if scene.name in _JOBS:
        _JOBS[scene.name].state = "cancelled"


def register():
    bpy.app.handlers.render_complete.append(render_complete)
    bpy.app.handlers.render_cancel.append(render_cancel)


def check_idle():
    if _JOBS:
        raise RuntimeError("请先结束渲染，再停用插件")


def unregister():
    check_idle()
    for handlers, function in ((bpy.app.handlers.render_complete, render_complete),
                               (bpy.app.handlers.render_cancel, render_cancel)):
        if function in handlers:
            handlers.remove(function)
