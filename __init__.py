bl_info = {
    "name": "VertexColRefineKit",
    "blender": (4, 2, 0),
    "category": "Object",
    "author": "Sir Uka",
    "version": (1, 0),
    "description": "Tools for advanced vertex color manipulation",
    "support": "COMMUNITY",
}

import bpy

from . import bake_light_to_vcol
from . import dynamic_vcol
from . import general_menu_vcol
from . import random_vcol
from . import report_vcol

modules = [
    bake_light_to_vcol,
    dynamic_vcol,
    general_menu_vcol,
    random_vcol,
    report_vcol,
]

def register():
    for module in modules:
        if hasattr(module, "register"):
            try:
                module.register()
            except Exception as e:
                print(f"Error registering module {module.__name__}: {e}")

def unregister():
    for module in reversed(modules):
        if hasattr(module, "unregister"):
            try:
                module.unregister()
            except Exception as e:
                print(f"Error unregistering module {module.__name__}: {e}")

if __name__ == "__main__":
    register()
