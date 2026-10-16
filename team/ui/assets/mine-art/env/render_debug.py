"""Debug renders from build/env_scene.blend:
blender -b build/env_scene.blend --python render_debug.py -- name zoom [fx fy fz | -] [samples] [w h]
The focus is a Blender world point (clamped into the overview frame) or "-" for the frame centre."""
import os, sys
import bpy
from mathutils import Vector
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import env_export as X
argv = sys.argv[sys.argv.index("--") + 1:]
name, zoom = argv[0], float(argv[1])
rest = argv[2:]
focus = None
if rest and rest[0] != "-":
    focus = Vector((float(rest[0]), float(rest[1]), float(rest[2])))
    rest = rest[3:]
elif rest:
    rest = rest[1:]
samples = int(rest[0]) if rest else 64
res = (int(rest[1]), int(rest[2])) if len(rest) > 2 else (960, 540)
cam = bpy.data.objects["MainView"]
X.render_view(os.path.join(HERE, "previews", f"_dbg_{name}.png"), cam, zoom=zoom, focus=focus, samples=samples, res=res)
