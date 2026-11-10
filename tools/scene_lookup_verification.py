"""Switch only affected functions against the immutable 2.11.1 release."""
import ast
from pathlib import Path
import zipfile

import bpy


class LookupRoutes:
    def __init__(self, addon):
        self.current, self.reference = {}, {}
        archive = Path(__file__).resolve().parents[1] / 'release/hoyo_gi_toon-2.11.1.zip'
        with zipfile.ZipFile(archive) as package:
            for module, names in ((addon.workflow, ('update_scene', 'update_frame')),
                                  (addon.lighting, ('update',)), (addon.animation_uniforms, ('sync',))):
                source = package.read(module.__name__.rpartition('.')[2] + '.py').decode('utf-8')
                namespace = dict(module.__dict__)
                for node in ast.parse(source).body:
                    if isinstance(node, ast.FunctionDef) and node.name in names:
                        exec(compile(ast.Module(body=[node], type_ignores=[]), '<2.11.1-reference>', 'exec'), namespace)
                        self.current[module, node.name] = getattr(module, node.name)
                        self.reference[module, node.name] = namespace[node.name]

    def select(self, mode):
        chosen = self.reference if mode.startswith('baseline') else self.current
        for (module, name), function in chosen.items():
            previous = getattr(module, name)
            for handlers in (bpy.app.handlers.depsgraph_update_post,
                             bpy.app.handlers.frame_change_post, bpy.app.handlers.render_pre):
                if previous in handlers:
                    handlers[handlers.index(previous)] = function
            setattr(module, name, function)
