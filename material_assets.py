"""Material data resolved strictly from the selected PMX package."""
from dataclasses import dataclass, field

class AssetError(ValueError):
    pass

@dataclass
class MaterialAssets:
    source: str
    role: str
    textures: dict = field(default_factory=dict)
    texture_settings: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)
    source_format: str = 'pmx'
    pmx: dict = field(default_factory=dict)
