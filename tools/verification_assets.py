"""Exercise deterministic matching and actionable resource errors."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import bpy


def check_resolver(module, output):
    with TemporaryDirectory(prefix='resolver-',dir=output) as directory:
        root=Path(directory)
        file=root/'Model.fbx'
        file.touch()
        texture=root/'Diffuse.png'
        texture.touch()
        name='Avatar_Girl_Test_Mat_Body'
        json_file=root/(name+'.json')
        json_file.write_text(json.dumps({'m_SavedProperties':{
            'm_Floats':[{'first':'_MainTexAlphaUse','second':2}],
            'm_TexEnvs':[{'Key':'_MainTex','Value':{'m_Texture':{'Name':'Diffuse'}}}]}}),encoding='utf-8')
        assets=module.AssetCatalog(file).resolve(name)
        assert assets.textures['diffuse']==texture and assets.floats['_MainTexAlphaUse']==2
        assert '_MainTex' in assets.evidence['diffuse']
        duplicate=root/'Duplicate'/'Diffuse.png'
        duplicate.parent.mkdir()
        duplicate.touch()
        try: module.AssetCatalog(file).resolve(name)
        except module.AssetError as exc: assert '重名' in str(exc)
        else: raise AssertionError('Duplicate texture was chosen silently')
        duplicate.unlink()
        texture.unlink()
        try: module.AssetCatalog(file).resolve(name)
        except module.AssetError as exc: assert '缺少贴图' in str(exc)
        else: raise AssertionError('Missing referenced texture was ignored')
        json_file.write_text('[]',encoding='utf-8')
        try: module.AssetCatalog(file).resolve(name)
        except module.AssetError as exc: assert 'JSON' in str(exc)
        else: raise AssertionError('Malformed JSON was accepted')
        json_file.unlink()
        texture.touch()
        material=bpy.data.materials.new(name)
        material.use_nodes=True
        image=bpy.data.images.new('Resolver source',1,1)
        image.filepath=str(texture)
        node=material.node_tree.nodes.new('ShaderNodeTexImage')
        node.image=image
        material.node_tree.links.new(node.outputs['Color'],material.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
        assets=module.AssetCatalog(file).resolve(name,material)
        assert assets.textures['diffuse']==texture and assets.evidence['diffuse']=='imported material Base Color'
        outside=Path(output)/'outside.png'
        outside.touch()
        image.filepath=str(outside)
        try: module.AssetCatalog(file).resolve(name,material)
        except module.AssetError: pass
        else: raise AssertionError('Outside-package texture was accepted')
        outside.unlink()
        bpy.data.batch_remove(ids={material,image})
        # Active native paths, rather than inherited unused source switches,
        # decide which references are actually required.
        from importlib import import_module
        describe = import_module(module.__package__+'.material_protocol').describe
        face = module.MaterialAssets('Avatar_Girl_Test_Mat_Face','face',
                                    textures={'diffuse':root/'Avatar_Girl_Test_Tex_Face_Diffuse.png'},
                                    floats={'_MetalMaterial':1,'_MTUseSpecularRamp':1,'_UseShadowRamp':1})
        assert describe(face)['template']=='Face' and not describe(face)['metal']
        eye = module.MaterialAssets('Avatar_Girl_Test_Mat_Pupil','eye',
                                   textures={'diffuse':texture,'eye_layer_1':texture,'eye_highlight':texture},
                                   floats={'_ParallaxLayer1':1,'_MetalMaterial':1,'_UseShadowRamp':1})
        assert describe(eye)['layered_eye'] and not describe(eye)['uses_body']
        normal = module.MaterialAssets(name,'body',textures={'diffuse':texture},
                                      unresolved={'normal':'DeclaredNormal'},floats={'_UseBumpMap':1,'_BumpScale':0})
        assert describe(normal)['normal']=='none'
        normal.floats['_BumpScale']=.5
        try:describe(normal)
        except module.AssetError:pass
        else:raise AssertionError('Active declared normal was not required')
    return {'json_dict_and_pairs':True,'duplicate_error':True,'missing_map_error':True,
            'malformed_json_error':True,'imported_base_color_reference':True,'package_boundary':True,
            'inactive_native_branches':True,'zero_normal_strength':True,'active_normal_error':True}
