import bpy, json, math
from pathlib import Path
root=Path(__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(root/"build"/"mine-art-blockout.blend"))
scene=bpy.context.scene
scene.frame_set(0)
workers=[bpy.data.objects["worker-"+s+str(i)] for s in "ab" for i in range(1,4)]
positions=[tuple(o.location) for o in workers]
limbs=[o for o in bpy.data.objects if o.get("role")=="worker_visual" and "_body" not in o.name]
start={o.name:tuple(o.rotation_euler) for o in limbs}
scene.frame_set(8)
assert all(abs(o.rotation_euler.y)>.2 for o in limbs), "NLA animation not evaluated"
assert positions==[tuple(o.location) for o in workers], "Root motion must come from model"
scene.frame_set(30)
assert all(max(abs(a-b) for a,b in zip(start[o.name],o.rotation_euler))<1e-5 for o in limbs), "Loop seam"
assert positions==[tuple(o.location) for o in workers]
result={"result":"PASS","animated_limbs":len(limbs),"roots_stationary":True,"loop_seam_tolerance":1e-5}
(root/"build"/"pose-check.json").write_text(json.dumps(result,indent=2))
print(json.dumps(result))
