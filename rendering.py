"""PNG output from the user's camera through an isolated scene."""
from dataclasses import dataclass, field
from pathlib import Path
import struct
import uuid
import bpy
from bpy.app.handlers import persistent
from . import post_processing, lighting, project_io, gaze

_JOBS = {}


def prepare(scene, root, collection):
    settings = root.hgt_character
    data = bpy.data.cameras.new('HGT • Camera')
    camera = bpy.data.objects.new(data.name, data)
    for item in (data, camera):
        item['hgt_owner'], item['hgt_stage'] = settings.uid, 'import'
    camera['hgt_helper'] = True
    collection.objects.link(camera)
    settings.camera = scene.hgt_output.camera = camera
    if scene.camera is None:scene.camera = camera


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
    path = path.resolve()
    automatic = scene.hgt_output.last_auto_path
    if automatic and path == Path(bpy.path.abspath(automatic)).resolve():
        original = path;index = 1
        while path.exists():
            path = original.with_stem(f'{original.stem}_{index:03d}')
            index += 1
    return path


@dataclass
class RenderJob:
    source: object
    proxy: object
    path: Path
    size: tuple
    resources: set = field(default_factory=set)
    state: str = "running"
    temporary: Path | None = None


def _validate_png(job):
    if not job.temporary.is_file():
        raise RuntimeError("渲染结束但图片未保存，请检查输出路径和目录权限")
    with job.temporary.open("rb") as stream:
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
    job = RenderJob(scene, proxy, path, (max(1, scene.render.resolution_x * scene.render.resolution_percentage // 100),
                                        max(1, scene.render.resolution_y * scene.render.resolution_percentage // 100)))
    job.temporary = path.with_name('.hgt-' + uuid.uuid4().hex + '.png')
    job.resources.add(proxy)
    try:
        proxy.camera = scene.hgt_output.camera
        # Scene.copy owns its master collection. Build this output's membership
        # there, retaining all objects of the selected import without editing
        # shared source collections or global object visibility.
        for child in tuple(proxy.collection.children):
            proxy.collection.children.unlink(child)
        for obj in tuple(proxy.collection.objects):
            proxy.collection.objects.unlink(obj)
        collection = bpy.data.collections.new('HGT • Render Batch')
        job.resources.add(collection)
        proxy.collection.children.link(collection)
        uid = root.hgt_character.uid
        objects = {obj for obj in scene.objects if obj.get('hgt_owner') == uid
                   or (obj.type == 'LIGHT' and not obj.get('hgt_owner'))}
        objects.add(proxy.camera)
        # Stable insertion also makes coplanar/transparent draw ties repeatable
        # after reload, when ID addresses and Python set order have changed.
        for obj in sorted(objects, key=lambda item: item.name_full):
            collection.objects.link(obj)
        proxy.render.engine = "BLENDER_EEVEE"
        proxy.view_settings.view_transform = "Standard"
        proxy.view_settings.look = 'None'
        proxy.view_settings.exposure = 0
        proxy.view_settings.gamma = 1
        proxy.render.resolution_x, proxy.render.resolution_y = job.size
        proxy.render.resolution_percentage = 100
        proxy.render.pixel_aspect_x = proxy.render.pixel_aspect_y = 1
        proxy.render.film_transparent = scene.render.film_transparent
        proxy.render.image_settings.file_format = "PNG"
        proxy.render.image_settings.color_mode = "RGBA"
        proxy.render.image_settings.color_depth = "8"
        proxy.render.use_file_extension = True
        proxy.render.use_sequencer = False
        proxy.render.use_compositing = scene.render.use_compositing or scene.hgt_output.post_processing
        proxy.render.filepath = str(job.temporary)
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
        raise ValueError("请先导入 PMX 并应用材质")
    project_io.validate(root)
    camera = scene.hgt_output.camera
    if camera is None or camera.type != "CAMERA" or camera.name not in scene.objects:
        raise ValueError("请在输出中选择当前场景的相机")
    if root.hgt_character.look_camera:gaze.update_gaze(root, scene)
    lighting.update(root)
    path = output_path(scene)
    protect_assets(scene, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    job = _proxy(scene, root, path)
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
    job.temporary.unlink(missing_ok=True)


def finish(key):
    job = _JOBS[key]
    try:
        if job.state == "cancelled":
            raise RenderCancelled('渲染已取消')
        _validate_png(job)
        # A cancelled or failed render never replaces an existing output file.
        job.temporary.replace(job.path)
        job.source.hgt_output.last_render = str(job.path)
        return str(job.path)
    finally:
        _cleanup(key)


def protect_assets(scene, path):
    """A render target must never replace any part of an imported package."""
    for obj in scene.objects:
        settings = obj.hgt_character
        if settings.uid and settings.source_file:
            folder = Path(settings.source_file).resolve().parent
            if path.is_relative_to(folder):
                raise ValueError('请选择模型资产目录以外的位置保存图片')
    for image in bpy.data.images:
        if image.source == 'FILE' and image.filepath:
            source = Path(bpy.path.abspath(image.filepath)).resolve()
            if path == source:
                raise ValueError('保存位置与已有贴图相同，请选择其他 PNG 文件')


def job_state(key):
    if key not in _JOBS:
        raise RuntimeError('渲染任务已结束，请重新渲染')
    return _JOBS[key].state


class RenderCancelled(RuntimeError):
    pass


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
