"""Private fixtures for mixed surfaces and shared-material accessory bones."""
from pathlib import Path
import bpy


def mixed_pmx(output):
    from mmd_tools.core import pmx
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    image=bpy.data.images.new('Subject fixture color',2,2,alpha=True)
    image.pixels[:]=[.25,.65,.9,1]*4
    image.filepath_raw=str(output/'color.png');image.file_format='PNG';image.save()
    bpy.data.images.remove(image)
    model=pmx.Model();model.name='Mixed subject fixture';model.name_e='Mixed subject fixture'
    texture=pmx.Texture();texture.path=str(output/'color.png');model.textures.append(texture)
    material=pmx.Material();material.name='衣服';material.name_e='Shared surface'
    material.diffuse=[1,1,1,1];material.specular=[0,0,0];material.ambient=[.5,.5,.5]
    material.edge_color=[0,0,0,1];material.enabled_toon_edge=True;material.edge_size=.2
    material.texture=0;material.is_shared_toon_texture=False;material.toon_texture=-1
    # Both disconnected surfaces share one material; only skinning identifies
    # the distant weapon, so a material-only splitter cannot pass this fixture.
    coords=[(-4,0,0),(4,0,0),(4,20,0),(-4,20,0),
            (35,5,0),(39,5,0),(39,16,0),(35,16,0)]
    for i,co in enumerate(coords):
        vertex=pmx.Vertex();vertex.co=list(co);vertex.normal=[0,0,1]
        vertex.uv=[(0,1,1,0)[i%4],(1,1,0,0)[i%4]]
        vertex.weight=pmx.BoneWeight();vertex.weight.type=pmx.BoneWeight.BDEF1
        vertex.weight.bones=[1 if i<4 else 2];model.vertices.append(vertex)
    model.faces=[(0,1,2),(0,2,3),(4,5,6),(4,6,7)]
    material.vertex_count=12;model.materials.append(material)
    for i,(name,pos,parent) in enumerate([('Root',(0,0,0),-1),('頭',(0,18,0),0),('Weapon_Root',(35,5,0),0)]):
        bone=pmx.Bone();bone.name=bone.name_e=name;bone.location=list(pos);bone.parent=parent
        bone.displayConnection=[0,1,0];model.bones.append(bone)
    morph=pmx.VertexMorph('Blink','Blink',2)
    offset=pmx.VertexMorphOffset();offset.index=2;offset.offset=[0,-1,0];morph.offsets.append(offset)
    model.morphs.append(morph)
    file=output/'混合角色.pmx';pmx.save(str(file),model)
    return file
