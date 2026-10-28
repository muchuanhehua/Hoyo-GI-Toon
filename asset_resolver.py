"""Resolve assets inside a selected model package, preferring JSON references."""
from dataclasses import dataclass, field
import json
from pathlib import Path
import re

IMAGE_SUFFIXES = {".png", ".tga", ".dds", ".jpg", ".jpeg", ".bmp", ".exr", ".tif", ".tiff"}
TEXTURE_KEYS = {
    "diffuse": ("_MainTex", "_BaseMap", "_BaseTex"),
    "normal": ("_BumpMap", "_NormalMap"),
    "lightmap": ("_LightMapTex", "_LightMap"),
    "ramp": ("_PackedShadowRampTex", "_ShadowRamp", "_RampTex"),
    "face_sdf": ("_FaceSdfMap", "_FaceMapTex"),
    "metal": ("_MTMap",),
    "specular_ramp": ("_MTSpecularRamp",),
}


class AssetError(ValueError):
    pass


def source_name(name):
    return re.sub(r"\.\d{3}$", "", name)


def role_for(name):
    text = source_name(name).lower()
    part = text.rsplit("_mat_", 1)[-1]
    if text.startswith(("eff_", "skillobj_")) or part == "default_mat":
        return "effect"
    for word, role in (("pupil", "eye"), ("brow", "brow"), ("face", "face"),
                       ("eye", "eye"), ("hair", "hair")):
        if word in part:
            return role
    return "body"


def property_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {item["Key"] if "Key" in item else item["first"]:
                item["Value"] if "Value" in item else item["second"] for item in value}
    raise AssetError("材质参数结构无法识别")


@dataclass
class MaterialAssets:
    source: str
    role: str
    textures: dict = field(default_factory=dict)
    floats: dict = field(default_factory=dict)
    colors: dict = field(default_factory=dict)
    texture_settings: dict = field(default_factory=dict)
    texenvs: dict = field(default_factory=dict)
    json_path: Path | None = None

    def color(self, key, fallback):
        value = self.colors.get(key)
        if value is None:
            return tuple(fallback)
        return tuple(float(value[k]) for k in ("r", "g", "b", "a"))


class AssetCatalog:
    def __init__(self, model_path):
        self.model = Path(model_path).resolve()
        if not self.model.is_file():
            raise AssetError("模型文件不存在")
        self.root = self.model.parent
        self.images = {}
        self.materials = {}
        # Keep the scan within this model package: nearby PMX variants and other
        # characters may contain similarly named but incompatible textures.
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            if path.suffix.lower() in IMAGE_SUFFIXES:
                self.images.setdefault(path.stem.casefold(), []).append(path)
            elif path.suffix.lower() == ".json":
                self.materials.setdefault(path.stem.casefold(), []).append(path)

    def unique(self, choices, label):
        if not choices:
            return None
        if len(choices) != 1:
            names = "、".join(str(p.relative_to(self.root)) for p in choices[:4])
            raise AssetError(f"{label} 存在重名文件，请保留明确的配套文件：{names}")
        return choices[0]

    def image(self, name):
        return self.unique(self.images.get(Path(name).stem.casefold(), []), name)

    def resolve(self, material_name):
        name = source_name(material_name)
        result = MaterialAssets(name, role_for(name))
        path = self.unique(self.materials.get(name.casefold(), []), f"材质 {name}")
        if path:
            self._read_json(path, result)
        if "diffuse" not in result.textures and result.role != "effect":
            base = re.sub("_Mat_", "_Tex_", name, flags=re.IGNORECASE)
            image = self.image(base + "_Diffuse")
            if image:
                result.textures["diffuse"] = image
        # GenshinAvatarTextureImporter binds Body diffuse/lightmap to Pupil;
        # the exported Pupil JSON can reference a placeholder Hair texture.
        if name.rsplit('_Mat_',1)[-1] == 'Pupil':
            body = self.resolve(name.rsplit('_Mat_',1)[0] + '_Mat_Body')
            for role in ('diffuse', 'lightmap', 'ramp'):
                if role in body.textures:
                    result.textures[role] = body.textures[role]
        # The original wizard selects a Hair shader for clothing which uses
        # Hair textures. Use the referenced texture, not a fixed character list.
        diffuse = result.textures.get("diffuse")
        if diffuse and result.role not in {"face", "eye", "brow"} and "_tex_hair" in diffuse.stem.casefold():
            result.role = "hair"
        return result

    def _read_json(self, path, result):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AssetError(f"无法读取材质参数：{path.name}，{exc}") from exc
        props = data.get("m_SavedProperties", data)
        result.json_path = path
        result.floats = property_dict(props.get("m_Floats", {}))
        result.colors = property_dict(props.get("m_Colors", {}))
        envs = property_dict(props.get("m_TexEnvs", {}))
        result.texenvs = envs
        for role, keys in TEXTURE_KEYS.items():
            for key in keys:
                entry = envs.get(key, {})
                reference = entry.get("m_Texture", {})
                name = reference.get("Name", "")
                if not name or reference.get("IsNull"):
                    continue
                image = self.image(name)
                if image is None:
                    # A selected material's main texture is a required reference;
                    # optional shader-specific detail maps may not be exported.
                    if role == "diffuse":
                        raise AssetError(f"{result.source} 缺少贴图：{name}")
                    continue
                result.textures[role] = image
                result.texture_settings[role] = entry
                break
