"""Debug renders from build/env_scene.blend: blender -b build/env_scene.blend --python render_debug.py -- name zoom fx fy fz [samples] [w h]"""
import os, sys
import bpy
from mathutils import Vector
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import env_export as X
argv = sys.argv[sys.argv.index("--") + 1:]
name, zoom = argv[0], float(argv[1])
focus = Vector((float(argv[2]), float(argv[3]), float(argv[4]))) if len(argv) > 4 else None
samples = int(argv[5]) if len(argv) > 5 else 64
res = (int(argv[6]), int(argv[7])) if len(argv) > 7 else (960, 540)
cam = bpy.data.objects["MainView"]
X.render_view(os.path.join(HERE, "previews", f"_dbg_{name}.png"), cam, zoom=zoom, focus=focus, samples=samples, res=res)
