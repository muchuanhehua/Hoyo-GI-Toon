"""Private, isolated runtimes for background and hidden-window verification."""
import hashlib
import importlib
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import zipfile


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def copy_better(source, runtime):
    source, runtime = Path(source).resolve(), Path(runtime).resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(runtime)
    destination = runtime / 'better_fbx'
    names = ('__init__.py','importer.py','exporter.py','blender_manifest.toml','gpl-3.0.txt',
             'bin/Windows/x64/fbx-utility.exe')
    hashes = {}
    for name in names:
        original, target = source / name, destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original,target)
        hashes[name] = file_hash(original)
        assert file_hash(target) == hashes[name]
    (destination/'data').mkdir(exist_ok=True)
    sys.path.insert(0,str(runtime))
    addon = importlib.import_module('better_fbx')
    addon.register()
    return addon, hashes


def load_addon(folder, name='hoyo_gi_toon'):
    folder = Path(folder).resolve()
    spec = importlib.util.spec_from_file_location(name,folder/'__init__.py',submodule_search_locations=[str(folder)])
    addon = importlib.util.module_from_spec(spec)
    sys.modules[name] = addon
    spec.loader.exec_module(addon)
    addon.register()
    return addon


def install_candidate(archive, output):
    import bpy
    configuration=Path(bpy.utils.user_resource('CONFIG')).resolve()
    assert configuration.is_relative_to(Path(output).resolve()),'Candidate must use a private configuration directory'
    repository = Path(output).resolve()/'extensions'
    repository.mkdir(parents=True,exist_ok=True)
    result=bpy.ops.preferences.extension_repo_add(name='HGT Candidate',type='LOCAL',
                        use_custom_directory=True,custom_directory=str(repository))
    assert result=={'FINISHED'}
    repo=next(repo for repo in bpy.context.preferences.extensions.repos if Path(repo.directory).resolve()==repository)
    result=bpy.ops.extensions.package_install_files(filepath=str(Path(archive).resolve()),repo=repo.module,enable_on_install=True)
    assert result=={'FINISHED'}
    addon=importlib.import_module(f'bl_ext.{repo.module}.hoyo_gi_toon')
    assert hasattr(bpy.types.Object,'hgt_character'),'Installed extension did not register its properties'
    folder=Path(addon.__file__).resolve().parent
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        for name in package.namelist(): assert (folder/name).read_bytes()==package.read(name),name
    return addon


def unload_addon(addon):
    if addon.__name__.startswith('bl_ext.'):
        import addon_utils
        addon_utils.disable(addon.__name__,default_set=True)
    else:
        addon.unregister()
