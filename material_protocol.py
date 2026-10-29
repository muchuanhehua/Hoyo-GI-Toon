"""Identify active material paths from source switches and texture references."""
from .asset_resolver import AssetError


def enabled(assets, key, default=0):
    return bool(assets.floats.get(key, default))


def require(assets, role, reason):
    if role not in assets.textures:
        reference = assets.unresolved.get(role)
        detail = f"：{reference}" if reference else ""
        raise AssetError(f"{assets.source} 的 {reason} 缺少 {role} 贴图{detail}")


def describe(assets):
    f = assets.floats
    normal = "none"
    strength = float(f.get("_BumpScale", 1))
    if enabled(assets, "_PackageNormalMapToggle"):
        strength = float(f.get("_NormalMapScale", 0))
        if strength != 0:
            require(assets, "normal_package", "打包高度法线")
            normal = "height"
    elif enabled(assets, "_UseBumpMap") or enabled(assets, "_isNativeMainNormal"):
        if "normal" in assets.textures:
            normal = "tangent"
        elif assets.unresolved.get("normal"):
            require(assets, "normal", "直接法线")
        # A source null reference uses the shader's neutral normal, rather
        # than inventing a missing filename or sampling an unrelated image.
    metal = enabled(assets, "_MetalMaterial")
    specular_ramp = metal and enabled(assets, "_MTUseSpecularRamp")
    if metal:
        require(assets, "metal", "金属反射")
    if specular_ramp:
        require(assets, "specular_ramp", "金属高光 Ramp")
    shadow_ramp = enabled(assets, "_UseShadowRamp", int("ramp" in assets.textures))
    if shadow_ramp:
        require(assets, "ramp", "阴影 Ramp")
    layered_eye = assets.role == "eye" and any(enabled(assets, f"_ParallaxLayer{i}") for i in (1, 2, 3))
    if layered_eye:
        for i in (1, 2, 3):
            if enabled(assets, f"_ParallaxLayer{i}"):
                require(assets, f"eye_layer_{i}", f"眼部第 {i} 层")
                if enabled(assets, f'_ParallaxLayer{i}UseRamp'):
                    require(assets, 'eye_layer_ramp', f'眼部第 {i} 层 Ramp')
        require(assets, 'eye_highlight', '眼部外表面高光')
        for role in ("eye_normal", "eye_matcap", "eye_highlight"):
            if role in assets.unresolved:
                require(assets, role, "眼部")
        if enabled(assets, "_UseHighlightRamp"):
            require(assets, "eye_ramp", "眼部高光 Ramp")
    stockings = enabled(assets, "_UseCharacterStockings")
    silk = enabled(assets, "_EnableCharacterSilksAnisotropy")
    shining = enabled(assets, "_UseCharacterShining_V2") or enabled(assets, '_UseCharacterShining')
    crystal = enabled(assets, "_EnableMatCap") and "matcap" in assets.textures
    for active, role, label in ((stockings, "stocking_detail", "丝袜细节"),
                                (silk, "silk_detail", "丝绸细节"),
                                (shining and enabled(assets, "_UseShiningCustomShape_V2"), "shining_shape", "闪点形状")):
        if active and role in assets.unresolved:
            require(assets, role, label)
    channel = int(f.get('_NormalMapLayerEnum', 0))
    if normal == 'height' and channel not in range(4):
        raise AssetError(f'{assets.source} 的打包高度通道无效：{channel}')
    return {"normal": normal, "normal_strength": strength, "normal_uv": 0, 'normal_channel': channel,
            "metal": metal, "specular_ramp": specular_ramp, "shadow_ramp": shadow_ramp,
            "layered_eye": layered_eye, "stockings": stockings, "silk": silk,
            "shining": shining, "crystal": crystal, "normal_material_ids": enabled(assets, "_UseNormalBAsID")}
