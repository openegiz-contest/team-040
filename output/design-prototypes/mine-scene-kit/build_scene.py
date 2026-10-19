"""Rebuild an editable ART BLOCKOUT, not a surveyed mine or routing model.
Run: blender -b --factory-startup --python build_scene.py
No GUI session, installed add-on, network, external texture or current .blend is used.
"""
import bpy
import json
import math
import random
from pathlib import Path
from mathutils import Vector, Matrix

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "build"
OUT.mkdir(exist_ok=True)
random.seed(40)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"

COLORS = {
    "rock": (0.115, 0.105, 0.095, 1),
    "rock_light": (0.19, 0.17, 0.145, 1),
    "rock_dark": (0.065, 0.061, 0.057, 1),
    "floor": (0.32, 0.285, 0.23, 1),
    "ore": (0.23, 0.21, 0.18, 1),
    "yellow": (0.95, 0.49, 0.025, 1),
    "yellow_dark": (0.51, 0.25, 0.02, 1),
    "steel": (0.115, 0.13, 0.14, 1),
    "silver": (0.39, 0.42, 0.43, 1),
    "rubber": (0.024, 0.028, 0.029, 1),
    "glass": (0.035, 0.072, 0.083, 1),
    "orange": (1.0, 0.17, 0.025, 1),
    "reflector": (0.72, 0.77, 0.73, 1),
    "lamp": (1.0, 0.65, 0.17, 1),
    "red": (0.37, 0.045, 0.025, 1),
}
MATERIALS = {}
for name, color in COLORS.items():
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = 0.88
    if name == "lamp":
        bsdf.inputs["Emission Color"].default_value = color
        bsdf.inputs["Emission Strength"].default_value = 2.0
    MATERIALS[name] = mat

class Geometry:
    def __init__(self):
        self.vertices, self.faces, self.materials = [], [], []

    def mesh(self, vertices, faces, mat):
        offset = len(self.vertices)
        self.vertices.extend(vertices)
        self.faces.extend(tuple(offset + i for i in f) for f in faces)
        self.materials.extend([mat] * len(faces))

    def box(self, p, size, mat):
        x, y, z = p
        a, b, c = (s / 2 for s in size)
        self.mesh([(x+i*a, y+j*b, z+k*c) for i,j,k in
                   [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
                    (-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]],
                  [(3,2,1,0),(0,1,5,4),(1,2,6,5),(2,3,7,6),
                   (3,0,4,7),(4,5,6,7)], mat)

    def beam(self, a, b, radius, mat, segments=8):
        a, b = Vector(a), Vector(b)
        axis = (b-a).normalized()
        helper = Vector((0,0,1)) if abs(axis.z) < .9 else Vector((0,1,0))
        u = axis.cross(helper).normalized() * radius
        v = axis.cross(u).normalized() * radius
        vertices = [tuple(p + math.cos(i*math.tau/segments)*u
                          + math.sin(i*math.tau/segments)*v)
                    for p in (a,b) for i in range(segments)]
        faces = [(i,(i+1)%segments,(i+1)%segments+segments,i+segments)
                 for i in range(segments)]
        faces += [tuple(reversed(range(segments))),
                  tuple(range(segments,2*segments))]
        self.mesh(vertices, faces, mat)

    def stone(self, p, size, mat="ore"):
        x,y,z = p
        sx,sy,sz = size
        self.mesh([(x-sx,y-sy,z),(x+sx,y-sy,z),(x+sx,y+sy,z),
                   (x-sx,y+sy,z),(x-.3*sx,y-.2*sy,z+sz),
                   (x+.5*sx,y+.4*sy,z+.7*sz)],
                  [(0,1,4),(1,5,4),(1,2,5),(2,3,5),(3,4,5),
                   (3,0,4),(3,2,1,0)],mat)

    def object(self, name, location=(0,0,0), angle=0, role="static"):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(self.vertices, [], self.faces)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(obj)
        slots = list(dict.fromkeys(self.materials))
        for key in slots:
            mesh.materials.append(MATERIALS[key])
        for face, key in zip(mesh.polygons, self.materials):
            face.material_index = slots.index(key)
        obj.location = location
        obj.rotation_euler.z = angle
        obj["role"] = role
        return obj

static = Geometry()
# Open front and ceiling: only camera-facing geology is built.
for floor in (0,9):
    static.box((0,0,floor-.25),(38,7,.5),"floor")
    # Deliberately faceted continuous back wall.
    for i in range(20):
        x = -19 + i*1.9
        vertices = [(x,3.5,floor), (x+1.9,3.5,floor),
                    (x+1.9,3.7,floor+4), (x,3.7,floor+4),
                    (x+.9,3.2+random.uniform(-.2,.2),floor+2)]
        for face in [(0,1,4),(1,2,4),(2,3,4),(3,0,4)]:
            static.mesh(vertices,[face],random.choice(["rock","rock_light","rock_dark"]))
    for x in range(-17,19,5):
        static.box((x,3.05,floor+1.95),(.16,.22,3.9),"steel")
        static.box((x,0,floor+3.95),(.16,6.2,.18),"steel")
        static.beam((x,2.8,floor+3.6),(x,2.8,floor+3.2),.07,"steel")
        static.beam((x,2.8,floor+3.15),(x,2.8,floor+3.3),.16,"lamp")
    static.beam((-18,2.9,floor+3.6),(18,2.9,floor+3.6),.32,"silver",12)
    for x in range(-18,19,2):
        static.beam((x-.025,2.9,floor+3.6),(x+.025,2.9,floor+3.6),.35,"steel",12)
    for z in (2.8,2.9):
        static.beam((-19,3.13,floor+z),(19,3.13,floor+z),.025,"rubber")
    for i in range(55):
        x = random.uniform(-18,18)
        static.stone((x,random.uniform(2.3,3.1),floor),(.12,.1,random.uniform(.1,.3)))
# Thick cutaway between levels, leaving lower gallery unobstructed.
for i in range(20):
    x=-19+i*1.9
    pts=[(x,3.6,4.1),(x+1.9,3.6,4.1),(x+1.9,-.3,8.7),
         (x,-.3,8.7),(x+.85,random.uniform(-.2,.2),6.5)]
    for face in [(0,1,4),(1,2,4),(2,3,4),(3,0,4)]:
        static.mesh(pts,[face],random.choice(["rock","rock_light","rock_dark"]))
# Continuous scenic switchback; this is an art reference, NOT a route graph.
ramp=[(-18,0,9),(-23,-2,6),(-21,-6,4.5),(-14,-5,2),(-9,-2,0)]
width=2.4
edges=[]
for i,p in enumerate(ramp):
    before=Vector(ramp[max(0,i-1)])
    after=Vector(ramp[min(len(ramp)-1,i+1)])
    tangent=after-before
    tangent.z=0
    tangent.normalize()
    normal=Vector((-tangent.y,tangent.x,0))*width/2
    edges.append((tuple(Vector(p)+normal),tuple(Vector(p)-normal)))
for first,second in zip(edges,edges[1:]):
    top=[first[0],first[1],second[1],second[0]]
    bottom=[(x,y,z-.35) for x,y,z in top]
    static.mesh(top+bottom,[(0,1,2,3),(7,6,5,4),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)],"floor")
# Display-only decorative shaft; model has walkable exits, not elevator transport.
for x in (16,18):
    static.beam((x,1,-1),(x,1,14),.09,"steel")
    static.beam((x,1.2,-1),(x,1.2,14),.025,"silver")
for z in (0,9):
    for x in (15.4,18.6):
        for y in (-1,1.6):
            static.beam((x,y,z),(x,y,z+1),.045,"yellow")
        for h in (.5,1):
            static.beam((x,-1,z+h),(x,1.6,z+h),.045,"yellow")
    static.beam((15.4,1.6,z+1),(18.6,1.6,z+1),.045,"yellow")
for z in (4.8,6.9):
    static.box((17,1,z),(1.7,1.7,.13),"yellow")
for x in (16.2,17.8):
    for y in (.2,1.8):
        static.beam((x,y,4.8),(x,y,6.9),.055,"yellow")
static.beam((17,1,6.9),(17,1,14),.035,"steel")
# Tool bay, no tiny unreadable pseudo-labels.
static.box((8,2.5,.8),(1.1,.7,1.6),"yellow_dark")
static.box((10,2.5,.55),(1.3,.7,1.1),"red")
for z in (.2,.4,.6,.8):
    static.box((10,2.13,z),(1.1,.03,.04),"silver")
for i in range(5):
    static.beam((11.5,2+i*.22,.2),(13.8,2+i*.22,.2),.09,"steel")
for x,z in [(-16,9),(-15,0)]:
    for i in range(24):
        static.stone((x+random.uniform(-1,1),random.uniform(-.8,1.6),z),
                     (random.uniform(.12,.32),.2,random.uniform(.15,.5)))

static.object("STATIC_ENVIRONMENT",role="art_blockout_static")

def vehicle(name,kind,position,angle=0):
    g=Geometry()
    g.box((0,0,.75),(3.4,1.35,.45),"yellow_dark")
    for x in (-1.1,1.1):
        for side in (-1,1):
            g.beam((x,side*.65,.6),(x,side*.95,.6),.6,"rubber",12)
            g.beam((x,side*.96,.6),(x,side*.99,.6),.28,"silver",12)
    if kind=="loader":
        g.box((1,0,1.25),(1.4,1.25,.7),"yellow")
        g.box((.25,0,1.6),(.7,1.1,1),"yellow")
        g.box((.25,-.56,1.8),(.55,.02,.5),"glass")
        for y in (-.45,.45):
            g.beam((-1,y,1),(-2.1,y,.4),.12,"yellow")
            g.beam((-.7,y,1.3),(-1.7,y,.7),.065,"steel")
        # Open bucket with distinct bottom, back and side plates.
        g.box((-2.25,0,.15),(1,1.75,.12),"yellow")
        g.box((-1.8,0,.5),(.13,1.75,.7),"yellow")
        for y in (-.83,.83):
            g.mesh([(-2.75,y,.12),(-1.75,y,.12),(-1.75,y,.9)],
                   [(0,1,2)],"yellow")
    elif kind=="truck":
        g.box((-1,0,1.5),(1,1.3,1.3),"yellow")
        g.box((-1,-.66,1.7),(.7,.02,.6),"glass")
        g.box((.7,0,1.15),(2.3,1.5,.15),"yellow")
        for y in (-.75,.75):
            g.box((.7,y,1.55),(2.3,.12,.7),"yellow")
        g.box((1.8,0,1.55),(.12,1.5,.7),"yellow")
        for i in range(20):
            g.stone((random.uniform(-.3,1.7),random.uniform(-.6,.6),1.25),(.2,.16,.3))
    else:
        g.box((.8,0,1.4),(1.4,1.2,1.1),"yellow")
        g.box((.8,-.61,1.6),(.8,.02,.55),"glass")
        g.beam((-1,0,1.2),(-3,0,2),.13,"yellow")
        g.beam((-3,0,2),(-4.5,0,2.3),.07,"steel")
    obj=g.object(name,position,angle,role="decorative_machine")
    obj["not_telemetry"]=True
    return obj

vehicle("DECOR_LOADER","loader",(-11,-.8,9))
vehicle("DECOR_TRUCK","truck",(3,-.3,9))
vehicle("DECOR_DRILL","drill",(-11,-.5,0))

def person(name,position):
    root=bpy.data.objects.new(name,None)
    scene.collection.objects.link(root)
    root.location=position
    root["role"]="dynamic_worker_placeholder"
    root["thingId"]="team040.mine:"+name
    g=Geometry()
    g.box((0,0,1.08),(.31,.46,.5),"orange")
    g.box((-.162,0,1.12),(.015,.45,.06),"reflector")
    g.beam((0,0,1.37),(0,0,1.6),.13,"yellow")
    g.beam((0,0,1.58),(0,0,1.65),.17,"yellow")
    body=g.object(name+"_body",role="worker_visual")
    body.parent=root
    for part in ("leg","arm"):
        for side in (-1,1):
            limb=Geometry()
            if part=="leg":
                pivot=(0,side*.13,.85)
                limb.beam((0,0,-.71),(0,0,0),.095,"orange")
                limb.box((-.07,0,-.76),(.32,.19,.18),"rubber")
                limb.beam((0,0,-.49),(0,0,-.43),.101,"reflector")
            else:
                pivot=(0,side*.3,1.25)
                limb.beam((0,0,0),(-.03,0,-.41),.075,"orange")
            ob=limb.object(name+"_"+part+str(side),pivot,role="worker_visual")
            ob.parent=root
            direction=side*(1 if part=="leg" else -1)
            for frame,value in [(0,0),(7.5,.4),(15,0),(22.5,-.4),(30,0)]:
                ob.rotation_euler.y=value*direction
                ob.keyframe_insert(data_path="rotation_euler",index=1,frame=frame)
            action=ob.animation_data.action
            track=ob.animation_data.nla_tracks.new()
            track.name="walk:"+name
            track.strips.new("walk",0,action)
            ob.animation_data.action=None
    return root

for key,position in [
    ("worker-a1",(-15,1,9)),("worker-a2",(-3,-1,9)),
    ("worker-a3",(13,2,9)),("worker-b1",(-6,-1,0)),
    ("worker-b2",(5,-1,0)),("worker-b3",(14,2,0))]:
    person(key,position)

def camera(name,pos,target,scale):
    data=bpy.data.cameras.new(name)
    data.type="ORTHO"
    data.ortho_scale=scale
    obj=bpy.data.objects.new(name,data)
    scene.collection.objects.link(obj)
    obj.location=pos
    obj.rotation_euler=(Vector(target)-obj.location).to_track_quat("-Z","Y").to_euler()
    return obj

scene.camera=camera("CAMERA_FIXED",(26,-55,29),(-1,0,6),53)
scene.camera["interaction"]="pan + orthographic zoom only; no orbit"
reference=ROOT/"reference-overview.png"
if reference.exists():
    img=bpy.data.images.load(str(reference))
    img.pack()
    scene.camera.data.show_background_images=True
    bg=scene.camera.data.background_images.new()
    bg.image=img
    bg.alpha=.35
    bg.display_depth="FRONT"
    bg.frame_method="FIT"
    # Reference appears in camera viewport only, never in render or GLB.

world=bpy.data.worlds.new("Mine ambient")
world.use_nodes=True
world.node_tree.nodes["Background"].inputs[0].default_value=(.25,.22,.18,1)
world.node_tree.nodes["Background"].inputs[1].default_value=.4
scene.world=world
def area(name,pos,power,size,target):
    d=bpy.data.lights.new(name,"AREA")
    d.energy=power
    d.shape="DISK"
    d.size=size
    ob=bpy.data.objects.new(name,d)
    scene.collection.objects.link(ob)
    ob.location=pos
    ob.rotation_euler=(Vector(target)-ob.location).to_track_quat("-Z","Y").to_euler()
area("KEY_BAKE_ONLY",(-5,-10,22),3500,22,(0,0,4))
area("FILL_BAKE_ONLY",(10,-12,8),1400,15,(0,0,4))
scene.render.engine="CYCLES"
scene.cycles.device="CPU"
scene.cycles.samples=20
scene.cycles.use_denoising=True
scene.render.threads_mode="FIXED"
scene.render.threads=4
scene.render.resolution_x=1600
scene.render.resolution_y=900
scene.render.resolution_percentage=100
scene.view_settings.view_transform="AgX"
scene.render.image_settings.file_format="PNG"
scene.render.filepath=str(OUT/"blockout-preview.png")
scene.render.fps=30
scene.frame_start=0
scene.frame_end=30
scene.frame_set(0)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/"mine-art-blockout.blend"))

# Export geometry/camera only; bake-preview lights are deliberately excluded.
bpy.ops.object.select_all(action="DESELECT")
for obj in scene.objects:
    if obj.type in {"MESH","CAMERA","EMPTY"}:
        obj.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(OUT/"mine-art-blockout.glb"),
                          use_selection=True,export_format="GLB",
                          export_cameras=True,export_extras=True,
                          export_yup=True,export_lights=False,
                          export_animations=True,export_animation_mode="NLA_TRACKS")
objects=[o for o in scene.objects if o.type=="MESH"]
triangles=0
for ob in objects:
    ob.data.calc_loop_triangles()
    triangles+=len(ob.data.loop_triangles)
report={
    "status":"editable art blockout; NOT final reference-quality art; NOT production routing topology",
    "camera":"fixed orthographic; pan/zoom only",
    "mesh_objects":len(objects),
    "triangles":triangles,
    "material_slots_total":sum(len(o.data.materials) for o in objects),
    "glb_bytes":(OUT/"mine-art-blockout.glb").stat().st_size,
    "runtime_shadow_lights_exported":0,
    "worker_objects":6,
    "reference_packed_in_blend":reference.exists(),
    "gpu_frame_time_measured":False,
}
(OUT/"asset-report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
bpy.ops.render.render(write_still=True)
print("MINE_KIT_READY "+json.dumps(report))
