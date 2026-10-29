"""Rendered reference/coverage fixtures for the shared material pipeline."""
import math
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector
from verification_data import mesh_data


def pixels(path):
    image=bpy.data.images.load(str(path),check_existing=False)
    values=np.array(image.pixels[:],dtype=np.float32).reshape((-1,4))
    bpy.data.images.remove(image)
    return values


def compare(before,after):
    delta=np.abs(before-after)
    return {'maximum':float(delta.max()),'mean':float(delta.mean()),
            'changed_fraction':float(np.any(delta>0,axis=1).mean())}


def fixtures(addon,reference,output):
    output=Path(output);source=output/'inputs';source.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
    scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE'
    scene.view_settings.view_transform='Standard';scene.view_settings.look='None'
    scene.view_settings.exposure=0;scene.view_settings.gamma=1
    scene.render.resolution_x,scene.render.resolution_y=256,192
    scene.render.resolution_percentage=100;scene.render.film_transparent=True
    scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA'
    camera=bpy.data.objects.new('Fixture camera',bpy.data.cameras.new('Fixture camera'))
    scene.collection.objects.link(camera);scene.camera=camera
    camera.data.type='ORTHO';camera.data.ortho_scale=1.5
    def aim(y):
        camera.location=(0,y,0)
        camera.rotation_euler=(-camera.location).to_track_quat('-Z','Y').to_euler()
    aim(-3)
    points=[];faces=[]
    for x in (-.55,.55):
        for y in (0,-.01):
            i=len(points);points += [(x-.4,y,-.4),(x+.4,y,-.4),(x+.4,y,.4),(x-.4,y,.4)]
            faces.append(tuple(range(i,i+4)))
    mesh=bpy.data.meshes.new('Fixture source');mesh.from_pydata(points,[],faces)
    uv=mesh.uv_layers.new(name='UV0')
    for face in mesh.polygons:
        for loop,value in zip(face.loop_indices,((0,0),(1,0),(1,1),(0,1))):uv.data[loop].uv=value
    obj=bpy.data.objects.new('Fixture surfaces',mesh);scene.collection.objects.link(obj)
    root=bpy.data.objects.new('Fixture owner',None);scene.collection.objects.link(root)
    root.hgt_character.uid='material-reference-fixture'
    library=addon.workflow.shaders.ShaderLibrary(root)
    asset_type=addon.workflow.AssetCatalog.__module__
    from importlib import import_module
    assets_module=import_module(asset_type)
    protocol=import_module(addon.__name__+'.material_protocol')
    Graph=import_module(addon.__name__+'.node_graph').Graph
    sampling=import_module(addon.__name__+'.sampling')
    shader=addon.workflow.shaders
    files={}
    def image(name,color):
        values=color if isinstance(color,list) else list(color)*16
        item=bpy.data.images.new(name,4,4,alpha=True)
        item.pixels[:]=values;item.filepath_raw=str(source/(name+'.png'))
        item.file_format='PNG';item.save();bpy.data.images.remove(item)
        files[name]=source/(name+'.png');return files[name]
    image('base',(.2,.3,.6,1));image('02',(.8,.1,.2,.35))
    image('04',(.1,.7,.3,.55));image('03',(.8,.8,.1,.2))
    image('ramp',(.4,.5,.65,1));image('highlight',(0,0,0,1))
    image('normal',(.65,.55,1,1))
    image('pattern',[value for y in range(4) for x in range(4) for value in (x/3,y/3,.2,1)])
    image('coverage',[value for y in range(4) for x in range(4) for value in (.7,.3,.2,0 if x<2 else 1)])
    def material(name,role,textures,floats=None,settings=None):
        assets=assets_module.MaterialAssets('Avatar_Girl_Fixture_Mat_'+name,role,textures=textures,
            floats={'_UseLightMapColorAO':0,'_UseVertexColorAO':0,'_UseShadowRamp':0,
                    '_MetalMaterial':0,'_UseToonSpecular':0,**(floats or {})},texture_settings=settings or {})
        assets.features=protocol.describe(assets)
        result,_=library.build_material(assets)
        return result,assets
    inner,assets=material('Pupil','eye',{'diffuse':files['base'],'eye_layer_1':files['02'],
        'eye_layer_2':files['04'],'eye_layer_3':files['03'],'eye_layer_ramp':files['ramp'],
        'eye_highlight':files['highlight']},{'_ParallaxLayer1':1,'_ParallaxLayer2':1,'_ParallaxLayer3':1,
        '_ParallaxLayer1UseRamp':1,'_ParallaxLayer2UseRamp':1})
    mesh.materials.append(inner);original=mesh_data(mesh)
    entry=root.hgt_character.meshes.add();entry.object=obj
    addon.workflow.asset_tracking.derive_mesh(entry,root.hgt_character.uid)
    addon.workflow.eye_surfaces.mark(entry,0)
    addon.workflow.eye_surfaces.attach(entry,inner)
    def render(name,mat):
        obj.material_slots[0].material=mat
        scene.render.filepath=str(output/(name+'.png'))
        bpy.ops.render.render(write_still=True)
        return pixels(scene.render.filepath)
    current=render('pupil-hgt',inner)
    with bpy.data.libraries.load(str(reference),link=False) as (src,target):
        assert 'PupilaTodo' in src.node_groups;target.node_groups=['PupilaTodo']
    native=target.node_groups[0]
    assert not any(n.bl_idname=='NodeUndefined' for n in native.nodes)
    mapping={'Pupil01_Diffuse_UV0':'base','Pupil02_Diffuse_UV0':'02','Pupil04_Diffuse_UV0':'04',
             'Pupil03_Diffuse_UV0':'03','Pupil_ramp1':'ramp','Pupil_ramp2':'ramp'}
    for name,key in mapping.items():native.nodes[name].image=shader.load_image(files[key],False,library.uid)
    ref=bpy.data.materials.new('Actual native PupilaTodo reference');ref.use_nodes=True
    tree=ref.node_tree;group=tree.nodes.new('ShaderNodeGroup');group.node_tree=native
    uv=tree.nodes.new('ShaderNodeUVMap');uv.uv_map='UV0'
    tree.links.new(uv.outputs[0],group.inputs['Vector'])
    emission=tree.nodes.new('ShaderNodeEmission');tree.links.new(group.outputs['Result'],emission.inputs['Color'])
    tree.links.new(emission.outputs[0],tree.nodes['Material Output'].inputs['Surface'])
    expected=render('pupil-native-reference',ref)
    pupil=compare(expected,current)
    assert pupil['mean']<.00001 and pupil['maximum']<=1/255+.00001,pupil
    assert mesh_data(mesh)==original
    assert mesh_data(entry.render_data,set(original['uv']),set(original['colors']))==original

    settings={'m_Scale':{'X':.5,'Y':1},'m_Offset':{'X':.25,'Y':0}}
    a=bpy.data.materials.new('Graph source transform');a.use_nodes=True
    transformed=assets_module.MaterialAssets('UV fixture','body',textures={'diffuse':files['pattern']},
                                            texture_settings={'diffuse':settings})
    graph=Graph(a,transformed,library.uid,shader.load_image)
    graph.surface(graph.texture('diffuse',data=False).outputs['Color'])
    a_pixels=render('uv-graph',a)
    b=bpy.data.materials.new('Native source transform');b.use_nodes=True
    node=b.node_tree.nodes.new('ShaderNodeTexImage');node.image=shader.load_image(files['pattern'],False,library.uid)
    node.name='Body_Diffuse_UV0';sampling.configure(node,settings)
    emission=b.node_tree.nodes.new('ShaderNodeEmission')
    b.node_tree.links.new(node.outputs['Color'],emission.inputs['Color'])
    b.node_tree.links.new(emission.outputs[0],b.node_tree.nodes['Material Output'].inputs['Surface'])
    b_pixels=render('uv-native',b)
    transform=compare(a_pixels,b_pixels)
    assert transform['maximum']<=1/255+.00001,transform
    transformed.texture_settings.clear()
    identity=bpy.data.materials.new('Identity source transform');identity.use_nodes=True
    graph=Graph(identity,transformed,library.uid,shader.load_image)
    graph.surface(graph.texture('diffuse',data=False).outputs['Color'])
    assert np.abs(a_pixels-render('uv-identity',identity)).max()>.1
    try:sampling.components({'X':float('nan')},(1,1))
    except ValueError:pass
    else:raise AssertionError('Non-finite UV transform accepted')

    normals=[]
    for strength in (.5,-.5,2):
        mat,_=material('Normal','body',{'diffuse':files['base'],'normal':files['normal']},
                       {'_UseBumpMap':1,'_BumpScale':strength})
        tree=mat.node_tree;body=tree.nodes['Body Shader']
        normal=tree.nodes.new('ShaderNodeGroup');normal.node_tree=library.groups['Optimized Normal Map']
        normal.inputs['Strength'].default_value=body.inputs['Use Normal Map'].default_value
        tree.links.new(body.inputs['Normal Map'].links[0].from_socket,normal.inputs['Normal Map'])
        encoded=tree.nodes.new('ShaderNodeVectorMath');encoded.operation='SCALE'
        encoded.inputs['Scale'].default_value=.5;tree.links.new(normal.outputs['For NdotV only'],encoded.inputs[0])
        shifted=tree.nodes.new('ShaderNodeVectorMath');shifted.operation='ADD';shifted.inputs[1].default_value=(.5,.5,.5)
        tree.links.new(encoded.outputs['Vector'],shifted.inputs[0])
        emission=tree.nodes.new('ShaderNodeEmission');tree.links.new(shifted.outputs['Vector'],emission.inputs['Color'])
        tree.links.new(emission.outputs[0],tree.nodes['Material Output'].inputs['Surface'])
        normals.append(render('normal-'+str(strength),mat))
    assert np.abs(normals[0]-normals[1]).max()>.05
    assert np.abs(normals[0]-normals[2]).max()>.05

    opaque,_=material('Opaque','body',{'diffuse':files['coverage']},{'_MainTexAlphaUse':0,'_CullMode':0})
    alpha,_=material('Alpha','body',{'diffuse':files['coverage']},{'_MainTexAlphaUse':1,'_MainTexAlphaCutoff':.5,'_CullMode':0})
    solid=render('coverage-opaque',opaque);cut=render('coverage-alpha',alpha)
    ratio=float((cut[:,3]>.5).sum()/max(1,(solid[:,3]>.5).sum()))
    assert .35<ratio<.65,ratio
    front,_=material('Cull','body',{'diffuse':files['base']},{'_CullMode':1})
    hidden=render('cull-front',front)
    assert hidden[:,3].max()==0
    aim(3);visible=render('cull-back',front);assert (visible[:,3]>.5).mean()>.05
    aim(-3)
    unfiltered=render('expression-unfiltered',opaque)
    marker=entry.render_data.attributes.new(addon.workflow.surface_layers.EXPRESSION_MASK,'FLOAT','FACE')
    for polygon in entry.render_data.polygons:marker.data[polygon.index].value=int(polygon.index>=2)
    addon.workflow.surface_layers.attach_expression(entry,library.uid)
    filtered=render('expression-filtered',opaque)
    evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    assert len(evaluated.polygons)==2 and len(entry.render_data.polygons)==len(mesh.polygons)==4
    obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
    expression_ratio=float((filtered[:,3]>.5).sum()/max(1,(unfiltered[:,3]>.5).sum()))
    assert .4<expression_ratio<.6,expression_ratio
    assert mesh_data(mesh)==original
    return {'pupil_native_reference':pupil,'source_uv_transform':transform,'coverage_ratio':ratio,
            'expression_coverage_ratio':expression_ratio,
            'checks':{'native_pupil_composition':True,'derived_slots_preserved':True,'source_uv_sampling':True,
                      'invalid_uv_error':True,'normal_negative_and_above_one':True,
                      'source_alpha_coverage':True,'front_culling':True,'expression_depth_excluded':True}}
