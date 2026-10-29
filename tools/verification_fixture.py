"""A small animated FBX fixture covering data absent from the character samples."""
from pathlib import Path
import shutil
import bpy


def animated_fbx(addon, source, output, accessories=False):
    bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
    output.mkdir(parents=True, exist_ok=True)
    for path in Path(source).parent.rglob('*'):
        if path.is_file() and path.suffix.lower() != '.fbx':
            dest = output / path.relative_to(Path(source).parent)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    file = output / '动画保留 验证.fbx'
    file.touch()
    assets = addon.workflow.AssetCatalog(file).resolve('Avatar_Girl_Bow_Ambor_Mat_Body')
    mesh = bpy.data.meshes.new('Fixture mesh')
    vertices=[(-.5,0,0),(.5,0,0),(.5,0,1.5),(-.5,0,1.5)]
    faces=[(0,1,2,3)]
    if accessories:
        vertices += [(3,0,0),(3.3,0,0),(3.3,0,1),(3,0,1)]
        faces += [(4,5,6,7)]
    mesh.from_pydata(vertices,[],faces)
    mesh.uv_layers.new(name='SourceUV')
    for i,point in enumerate(mesh.uv_layers.active.data):point.uv=[(0,0),(1,0),(1,1),(0,1)][i%4]
    colors = mesh.color_attributes.new(name='SourceColor',type='FLOAT_COLOR',domain='POINT')
    for color in colors.data: color.color=(.2,.5,.8,1)
    mesh.normals_split_custom_set([(0,-1,0)]*len(mesh.loops))
    obj = bpy.data.objects.new('Fixture body',mesh)
    bpy.context.scene.collection.objects.link(obj)
    material=bpy.data.materials.new(assets.source)
    material.use_nodes=True
    image=material.node_tree.nodes.new('ShaderNodeTexImage')
    image.image=bpy.data.images.load(str(assets.textures['diffuse']))
    material.node_tree.links.new(image.outputs['Color'],material.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
    mesh.materials.append(material)
    obj.shape_key_add(name='Basis')
    key=obj.shape_key_add(name='Smile')
    key.data[0].co.x+=.2
    key.value=0
    key.keyframe_insert('value',frame=1)
    key.value=.8
    key.keyframe_insert('value',frame=10)
    arm=bpy.data.armatures.new('Fixture rig')
    rig=bpy.data.objects.new(arm.name,arm)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active=rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    root=arm.edit_bones.new('Root')
    root.head,root.tail=(0,0,0),(0,0,.5)
    head=arm.edit_bones.new('Head')
    head.head,head.tail,head.parent=(0,0,1.3),(0,0,1.6),root
    if accessories:
        weapon=arm.edit_bones.new('Weapon_Root')
        weapon.head,weapon.tail,weapon.parent=(3,0,0),(3,0,1),root
    bpy.ops.object.mode_set(mode='OBJECT')
    group=obj.vertex_groups.new(name='Root')
    group.add([0,1,2,3],1,'REPLACE')
    if accessories:
        weapon_group=obj.vertex_groups.new(name='Weapon_Root')
        weapon_group.add([4,5,6,7],1,'REPLACE')
    modifier=obj.modifiers.new('Source armature','ARMATURE')
    modifier.object=rig
    obj.parent=rig
    if accessories:
        for name,points,known in [
            ('Bow',[(-.1,-.02,1.4),(.1,-.02,1.4),(0,-.02,1.6)],True),
            ('Unclassified prop',[(-2,0,.3),(-1.8,0,.3),(-1.9,0,.6)],False)]:
            detail=bpy.data.meshes.new(name);detail.from_pydata(points,[],[(0,1,2)])
            detail.uv_layers.new(name='SourceUV')
            detail.color_attributes.new(name='SourceColor',type='FLOAT_COLOR',domain='POINT')
            detail.normals_split_custom_set([(0,-1,0)]*3)
            surface=bpy.data.objects.new(name,detail);bpy.context.scene.collection.objects.link(surface)
            detail.materials.append(material if known else bpy.data.materials.new('Unclassified material'))
            surface.parent=rig
            group=surface.vertex_groups.new(name='Head' if known else 'Root');group.add([0,1,2],1,'REPLACE')
            skin=surface.modifiers.new('Source armature','ARMATURE');skin.object=rig
    bone=rig.pose.bones['Head']
    bone.rotation_mode='XYZ'
    bone.rotation_euler=(0,0,0)
    bone.keyframe_insert('rotation_euler',frame=1)
    bone.rotation_euler=(0,0,.3)
    bone.keyframe_insert('rotation_euler',frame=10)
    obj.location.x=0
    obj.keyframe_insert('location',frame=1)
    obj.location.x=.1
    obj.keyframe_insert('location',frame=10)
    scene=bpy.context.scene
    scene.frame_start,scene.frame_end=1,10
    scene.frame_set(1)
    result=bpy.ops.better_export.fbx(filepath=str(file),use_animation=True,use_timeline_range=True,
                                   use_apply_modifiers=False,use_triangulate=False,use_selection=False)
    assert result=={'FINISHED'} and file.stat().st_size>1000
    bpy.ops.wm.read_homefile(use_empty=True,use_factory_startup=True)
    batch=addon.workflow.importers.import_character(str(file))
    bpy.context.view_layer.update()
    assert batch.data['actions'],'Animated FBX imported without actions'
    assert any(obj.data.shape_keys and len(obj.data.shape_keys.key_blocks)>1 for obj in batch.meshes)
    assert all(obj.data.uv_layers and obj.data.color_attributes and obj.data.has_custom_normals for obj in batch.meshes)
    return batch
