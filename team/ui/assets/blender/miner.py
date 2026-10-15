"""
miner.py - procedural low-poly underground miner figure for the dispatcher UI
of the team's fictional copper mine.

Provenance
    Authored by Claude (Anthropic) on 15 October 2026 as this Python script for
    Blender 5.1. No external models, textures or add-ons: every vertex is produced
    by the code below. Licence: the repository's licence (MIT).
    How it was run is recorded in ../README.md (section "Горняк").

What it builds (neutral standing pose, arms slightly away from the body)
    root empty "miner" with four meshes, identity transforms:
      miner_body    overalls, face and neck, gloves, boots, belt, battery pack,
                    self-rescuer, lamp cable
      miner_bands   reflective bands: chest, both forearms, both shins, two
                    braces over the chest and back
      miner_helmet  hard hat shell with brim and ridge
      miner_lamp    cap lamp housing on the helmet front + its lens (material
                    `miner_lamp`, emissive, the scene can tint or dim it)
    Height 1.80 m to the helmet top, origin on the ground between the feet,
    facing +X. Blender +X forward, +Y left, +Z up; in glTF: forward +X, up +Y,
    left -Z.

Budget (checked from the exported file): <= 1 500 triangles, no textures,
no glTF extensions, no Draco.

Materials (Principled BSDF, no images)
    miner_overalls #2E3946  miner_band #D8D3C7 (bright, low roughness)
    miner_helmet   #E6E1D6  miner_skin #A47F68  miner_boots #1C1D20
    miner_gear     #34373C (gloves, belt, battery, lamp housing)
    miner_lamp     #FFF0CF emissive strength 1.0 (emissiveFactor only)

Outputs
    ./miner.blend, ../../public/models/miner.glb, ./previews/miner_*.png

Run from the repository root:
    "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" -b --factory-startup --python team/ui/assets/blender/miner.py
Options after "--": --no-render, --samples N (default 48).
"""

import json
import math
import os
import struct
import sys
import time

import bmesh
import bpy
from mathutils import Vector


def _script_path():
    try:
        return os.path.abspath(__file__)
    except NameError:
        argv = sys.argv
        return os.path.abspath(argv[argv.index("--python") + 1])


HERE = os.path.dirname(_script_path())
UI_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
BLEND_PATH = os.path.join(HERE, "miner.blend")
GLB_PATH = os.path.join(UI_ROOT, "public", "models", "miner.glb")
PREVIEW_DIR = os.path.join(HERE, "previews")
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
DO_RENDER = "--no-render" not in ARGS
SAMPLES = int(ARGS[ARGS.index("--samples") + 1]) if "--samples" in ARGS else 48
MAX_TRIANGLES = 1500
T0 = time.perf_counter()


def reset_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras,
                 bpy.data.worlds, bpy.data.images, bpy.data.node_groups):
        for block in list(coll):
            coll.remove(block)
    bpy.context.scene.name = "miner"


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_rgba(h):
    h = h.lstrip("#")
    return tuple(srgb_to_linear(int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4)) + (1.0,)


def principled(name, hex_color, roughness, metallic=0.0, emissive=False):
    mat = bpy.data.materials.new(name)
    if getattr(mat, "node_tree", None) is None:
        mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    rgba = hex_rgba(hex_color)
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if emissive:
        bsdf.inputs["Emission Color"].default_value = rgba
        bsdf.inputs["Emission Strength"].default_value = 1.0
    mat.diffuse_color = rgba
    return mat


def make_materials():
    return {
        "overalls": principled("miner_overalls", "#2E3946", 0.85),
        "band": principled("miner_band", "#D8D3C7", 0.35),
        "helmet": principled("miner_helmet", "#E6E1D6", 0.4),
        "skin": principled("miner_skin", "#A47F68", 0.7),
        "boots": principled("miner_boots", "#1C1D20", 0.8),
        "gear": principled("miner_gear", "#34373C", 0.7),
        "lamp": principled("miner_lamp", "#FFF0CF", 0.2, emissive=True),
    }


class Mesh:
    def __init__(self, name, mats):
        self.name, self.mats = name, mats
        self.bm = bmesh.new()
        self.slots = []

    def m(self, slot):
        if slot not in self.slots:
            self.slots.append(slot)
        return self.slots.index(slot)

    def loft(self, sections, slot, n=8, power=2.0, cap0=True, cap1=True, phase=0.5):
        """Rings (cx, cy, z, rx, ry) joined in order; superellipse cross-section when power > 2."""
        bm, mi = self.bm, self.m(slot)
        rings = []
        for cx, cy, z, rx, ry in sections:
            ring = []
            for k in range(n):
                a = 2 * math.pi * (k + phase) / n
                c, s = math.cos(a), math.sin(a)
                e = 2.0 / power
                ring.append(bm.verts.new((cx + rx * math.copysign(abs(c) ** e, c),
                                          cy + ry * math.copysign(abs(s) ** e, s), z)))
            rings.append(ring)
        for r0, r1 in zip(rings, rings[1:]):
            for k in range(n):
                j = (k + 1) % n
                bm.faces.new((r0[k], r0[j], r1[j], r1[k])).material_index = mi
        if cap0:
            bm.faces.new(list(reversed(rings[0]))).material_index = mi
        if cap1:
            bm.faces.new(rings[-1]).material_index = mi
        return rings

    def band(self, cx, cy, z0, z1, rx, ry, n=8, power=2.0, slot="band"):
        self.loft([(cx, cy, z0, rx, ry), (cx, cy, z1, rx, ry)], slot, n, power, cap0=False, cap1=False)

    def hexa(self, pts, slot):
        bm, mi = self.bm, self.m(slot)
        v = [bm.verts.new(p) for p in pts]
        for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            bm.faces.new([v[i] for i in f]).material_index = mi

    def box(self, mn, mx, slot):
        (x0, y0, z0), (x1, y1, z1) = mn, mx
        self.hexa([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                   (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], slot)

    def prism_xz(self, pts, y0, y1, slot):
        bm, mi = self.bm, self.m(slot)
        a = [bm.verts.new((x, y0, z)) for x, z in pts]
        b = [bm.verts.new((x, y1, z)) for x, z in pts]
        bm.faces.new(a).material_index = mi
        bm.faces.new(list(reversed(b))).material_index = mi
        for i in range(len(pts)):
            j = (i + 1) % len(pts)
            bm.faces.new((a[i], a[j], b[j], b[i])).material_index = mi

    def cylinder(self, p0, p1, r, sides, slot, r1=None):
        p0, p1 = Vector(p0), Vector(p1)
        d = (p1 - p0).normalized()
        u = d.orthogonal().normalized()
        w = d.cross(u).normalized()
        bm, mi = self.bm, self.m(slot)
        r1 = r if r1 is None else r1
        ring0, ring1 = [], []
        for k in range(sides):
            a = 2 * math.pi * (k + 0.5) / sides
            off = u * math.cos(a) + w * math.sin(a)
            ring0.append(bm.verts.new(p0 + off * r))
            ring1.append(bm.verts.new(p1 + off * r1))
        for k in range(sides):
            j = (k + 1) % sides
            bm.faces.new((ring0[k], ring0[j], ring1[j], ring1[k])).material_index = mi
        bm.faces.new(list(reversed(ring0))).material_index = mi
        bm.faces.new(ring1).material_index = mi

    def ellipsoid(self, c, rx, ry, rz, segs, rings, slot, z_from=-1.0):
        """UV ellipsoid; z_from > -1 cuts it (e.g. 0 gives the upper half, open at the bottom)."""
        bm, mi = self.bm, self.m(slot)
        cx, cy, cz = c
        lat0 = math.asin(max(-1.0, min(1.0, z_from)))
        rows = []
        for i in range(rings):
            lat = lat0 + (math.pi / 2 - lat0) * i / rings
            rows.append([bm.verts.new((cx + rx * math.cos(lat) * math.cos(2 * math.pi * k / segs),
                                       cy + ry * math.cos(lat) * math.sin(2 * math.pi * k / segs),
                                       cz + rz * math.sin(lat))) for k in range(segs)])
        top = bm.verts.new((cx, cy, cz + rz))
        for r0, r1 in zip(rows, rows[1:]):
            for k in range(segs):
                j = (k + 1) % segs
                bm.faces.new((r0[k], r0[j], r1[j], r1[k])).material_index = mi
        for k in range(segs):
            bm.faces.new((rows[-1][k], rows[-1][(k + 1) % segs], top)).material_index = mi
        return rows

    def tube(self, points, radius, sides, segments, slot):
        p0, p1, p2 = (Vector(p) for p in points)
        path = [(1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2
                for t in (i / segments for i in range(segments + 1))]
        bm, mi = self.bm, self.m(slot)
        loops = []
        for i, p in enumerate(path):
            tangent = (path[min(i + 1, segments)] - path[max(i - 1, 0)]).normalized()
            side = tangent.cross(Vector((0, 1, 0)))
            if side.length < 1e-4:
                side = tangent.cross(Vector((1, 0, 0)))
            side.normalize()
            up = side.cross(tangent).normalized()
            loops.append([bm.verts.new(p + radius * (math.cos(2 * math.pi * s / sides) * side
                                                     + math.sin(2 * math.pi * s / sides) * up))
                          for s in range(sides)])
        for a, b in zip(loops, loops[1:]):
            for s in range(sides):
                t = (s + 1) % sides
                bm.faces.new((a[s], a[t], b[t], b[s])).material_index = mi

    def to_object(self, parent, smooth_angle):
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts, dist=1e-6)
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces)
        me = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(me)
        self.bm.free()
        ob = bpy.data.objects.new(self.name, me)
        bpy.context.scene.collection.objects.link(ob)
        for s in self.slots:
            me.materials.append(self.mats[s])
        ob.parent = parent
        for o in bpy.context.scene.objects:
            o.select_set(False)
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(smooth_angle))
        ob.select_set(False)
        return ob


# --------------------------------------------------------------------------- the figure

HELMET_C = (0.0, 0.0, 1.685)       # helmet ellipsoid centre (top at 1.80)
# torso sections (cx, cy, z, rx, ry): pelvis -> shoulders, rounded-box cross-section
TORSO = [(0.0, 0.0, 0.80, 0.085, 0.110), (0.0, 0.0, 0.88, 0.105, 0.160), (0.0, 0.0, 0.98, 0.110, 0.172),
         (0.0, 0.0, 1.08, 0.105, 0.165), (0.008, 0.0, 1.22, 0.118, 0.178), (0.012, 0.0, 1.34, 0.122, 0.188),
         (0.0, 0.0, 1.44, 0.112, 0.192), (-0.005, 0.0, 1.50, 0.085, 0.150), (-0.005, 0.0, 1.535, 0.055, 0.075)]
TORSO_POWER = 2.6


def torso_x(z, y, front):
    """x of the torso surface at height z and lateral offset y (front or back)."""
    for a, b in zip(TORSO, TORSO[1:]):
        if a[2] <= z <= b[2]:
            t = (z - a[2]) / (b[2] - a[2])
            cx, rx, ry = (a[0] + t * (b[0] - a[0]), a[3] + t * (b[3] - a[3]), a[4] + t * (b[4] - a[4]))
            q = min(abs(y) / ry, 0.999) ** TORSO_POWER
            return cx + (1 if front else -1) * rx * (1 - q) ** (1 / TORSO_POWER)
    raise ValueError(z)


def build_body(mats, root):
    b = Mesh("miner_body", mats)
    for s in (1, -1):
        # leg: ankle -> hip, slightly converging
        b.loft([(0.0, s * 0.105, 0.10, 0.055, 0.050), (0.005, s * 0.105, 0.30, 0.068, 0.062),
                (0.012, s * 0.100, 0.50, 0.064, 0.060), (0.005, s * 0.098, 0.66, 0.080, 0.075),
                (0.0, s * 0.095, 0.84, 0.095, 0.090), (0.0, s * 0.085, 0.94, 0.100, 0.090)],
               "overalls", n=8, cap0=False, cap1=False)
        # boot: side profile, toe forward
        b.prism_xz([(-0.085, 0.0), (0.205, 0.0), (0.225, 0.035), (0.19, 0.085), (0.075, 0.115),
                    (0.06, 0.17), (-0.085, 0.17)], s * 0.105 - 0.062, s * 0.105 + 0.062, "boots")
        # arm: shoulder -> wrist, forearm slightly forward
        b.loft([(0.0, s * 0.175, 1.49, 0.030, 0.030), (0.0, s * 0.195, 1.455, 0.060, 0.058),
                (-0.005, s * 0.212, 1.33, 0.055, 0.052), (-0.01, s * 0.226, 1.17, 0.047, 0.044),
                (0.01, s * 0.232, 1.08, 0.045, 0.042), (0.045, s * 0.236, 0.90, 0.036, 0.032)],
               "overalls", n=8, cap0=True, cap1=True)
        # glove (mitten shape)
        b.loft([(0.045, s * 0.236, 0.915, 0.040, 0.034), (0.052, s * 0.238, 0.86, 0.048, 0.026),
                (0.055, s * 0.238, 0.80, 0.044, 0.022), (0.052, s * 0.236, 0.765, 0.028, 0.016)],
               "gear", n=6, cap0=False, cap1=True)
    # torso: pelvis -> shoulders, rounded-box cross-section
    b.loft(TORSO, "overalls", n=12, power=TORSO_POWER, cap0=True, cap1=True)
    # neck and head
    b.loft([(0.005, 0.0, 1.51, 0.048, 0.048), (0.01, 0.0, 1.60, 0.046, 0.046)], "skin", n=8, cap0=False, cap1=False)
    b.ellipsoid((0.012, 0.0, 1.645), 0.092, 0.080, 0.105, 10, 5, "skin", z_from=-0.95)
    # nose: a small wedge, so the facing reads at mid zoom
    b.hexa([(0.095, -0.015, 1.62), (0.125, -0.010, 1.625), (0.125, 0.010, 1.625), (0.095, 0.015, 1.62),
            (0.095, -0.012, 1.665), (0.105, -0.008, 1.665), (0.105, 0.008, 1.665), (0.095, 0.012, 1.665)], "skin")
    # belt, battery pack on the back, self-rescuer on the left hip
    b.band(0.0, 0.0, 1.00, 1.05, 0.116, 0.178, n=12, slot="gear")
    b.box((-0.175, -0.13, 0.97), (-0.105, 0.01, 1.11), "gear")
    b.cylinder((0.03, 0.165, 0.94), (0.03, 0.165, 1.07), 0.048, 8, "gear")
    # lamp cable from the battery up the back to the helmet
    b.tube([(-0.15, -0.06, 1.11), (-0.20, -0.10, 1.48), (-0.115, -0.05, 1.70)], 0.012, 4, 7, "gear")
    return b.to_object(root, smooth_angle=55)


def build_bands(mats, root):
    b = Mesh("miner_bands", mats)
    # chest band around the torso
    b.band(0.009, 0.0, 1.24, 1.29, 0.125, 0.184, n=12, power=TORSO_POWER)
    for s in (1, -1):
        b.band(0.01, s * 0.232, 1.08, 1.12, 0.050, 0.047, n=8)       # forearm
        b.band(-0.004, s * 0.206, 1.36, 1.40, 0.060, 0.057, n=8)     # upper arm
        b.band(0.006, s * 0.104, 0.31, 0.36, 0.073, 0.067, n=8)      # shin
        # braces: front and back strips lying on the torso, from the belt over the shoulder
        bm, mi = b.bm, b.m("band")
        zs = [1.05, 1.15, 1.25, 1.35, 1.44, 1.50]
        yc, hw, lift = s * 0.085, 0.022, 0.007
        rows = []
        for front in (True, False):
            for z in (zs if front else list(reversed(zs))):
                xo = torso_x(z, yc, front) + (lift if front else -lift)
                rows.append((bm.verts.new((xo, yc - hw, z)), bm.verts.new((xo, yc + hw, z))))
        for (a0, a1), (b0, b1) in zip(rows, rows[1:]):
            bm.faces.new((a0, a1, b1, b0)).material_index = mi
    return b.to_object(root, smooth_angle=55)


def build_helmet(mats, root):
    h = Mesh("miner_helmet", mats)
    cx, cy, cz = HELMET_C
    h.ellipsoid((cx, cy, cz), 0.125, 0.112, 0.115, 12, 4, "helmet", z_from=0.0)
    # brim: a thin ring, longer at the front (peak)
    rings = []
    bm, mi = h.bm, h.m("helmet")
    for z, grow in ((cz + 0.004, 0.0), (cz - 0.006, 0.0), (cz - 0.01, 1.0), (cz - 0.002, 1.0)):
        ring = []
        for k in range(12):
            a = 2 * math.pi * k / 12
            front = max(0.0, math.cos(a)) ** 2
            rx = 0.125 + grow * (0.03 + 0.04 * front)
            ry = 0.112 + grow * 0.028
            ring.append(bm.verts.new((cx + rx * math.cos(a), cy + ry * math.sin(a), z)))
        rings.append(ring)
    for r0, r1 in zip(rings + [rings[0]], rings[1:] + [rings[0]]):
        for k in range(12):
            j = (k + 1) % 12
            bm.faces.new((r0[k], r0[j], r1[j], r1[k])).material_index = mi
    # ridge along the crown
    h.hexa([(-0.10, -0.012, cz + 0.06), (0.10, -0.012, cz + 0.06), (0.10, 0.012, cz + 0.06), (-0.10, 0.012, cz + 0.06),
            (-0.07, -0.012, cz + 0.115), (0.07, -0.012, cz + 0.115), (0.07, 0.012, cz + 0.115), (-0.07, 0.012, cz + 0.115)],
           "helmet")
    return h.to_object(root, smooth_angle=50)


def build_lamp(mats, root):
    l = Mesh("miner_lamp", mats)
    cz = HELMET_C[2] + 0.045
    l.box((0.095, -0.025, cz - 0.03), (0.125, 0.025, cz + 0.03), "gear")             # bracket
    l.cylinder((0.11, 0.0, cz), (0.165, 0.0, cz), 0.034, 10, "gear", r1=0.036)       # housing
    l.cylinder((0.163, 0.0, cz), (0.171, 0.0, cz), 0.029, 10, "lamp")                # lens
    return l.to_object(root, smooth_angle=40)


def build(mats):
    root = bpy.data.objects.new("miner", None)
    root.empty_display_type = "PLAIN_AXES"
    bpy.context.scene.collection.objects.link(root)
    return [root, build_body(mats, root), build_bands(mats, root), build_helmet(mats, root), build_lamp(mats, root)]


# --------------------------------------------------------------------------- export, checks, previews


def export_glb(objs):
    os.makedirs(os.path.dirname(GLB_PATH), exist_ok=True)
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=GLB_PATH, export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
        export_texcoords=False, export_normals=True, export_tangents=False, export_materials="EXPORT",
        export_vertex_color="NONE", export_attributes=False, export_image_format="NONE",
        export_cameras=False, export_lights=False, export_extras=False, export_animations=False,
        export_skins=False, export_morph=False, export_draco_mesh_compression_enable=False,
        export_copyright="Team repository licence (MIT); authored by Claude, procedural Blender 5.1 script miner.py")
    for o in objs:
        o.select_set(False)


def inspect_glb(path):
    with open(path, "rb") as fh:
        data = fh.read()
    clen = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20:20 + clen])
    acc = gltf["accessors"]
    per_mesh, lo, hi = {}, [1e9] * 3, [-1e9] * 3
    for node in gltf["nodes"]:
        assert "rotation" not in node and "scale" not in node and "translation" not in node
        if "mesh" in node:
            prims = gltf["meshes"][node["mesh"]]["primitives"]
            per_mesh[node["name"]] = sum(acc[p["indices"]]["count"] // 3 for p in prims)
            for p in prims:
                a = acc[p["attributes"]["POSITION"]]
                lo = [min(u, v) for u, v in zip(lo, a["min"])]
                hi = [max(u, v) for u, v in zip(hi, a["max"])]
    return {"bytes": len(data), "triangles": sum(per_mesh.values()), "per_mesh": per_mesh,
            "materials": [m["name"] for m in gltf.get("materials", [])],
            "textures": len(gltf.get("textures", [])), "extensionsUsed": gltf.get("extensionsUsed", []),
            "bounds_min_gltf": [round(v, 3) for v in lo], "bounds_max_gltf": [round(v, 3) for v in hi]}


def render_previews():
    scene = bpy.context.scene
    world = bpy.data.worlds.new("graphite")
    if getattr(world, "node_tree", None) is None:
        world.use_nodes = True
    next(n for n in world.node_tree.nodes if n.type == "BACKGROUND").inputs["Color"].default_value = hex_rgba("#0E1012")
    scene.world = world
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=20.0)
    me = bpy.data.meshes.new("preview_floor")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(principled("preview_floor", "#191B1E", 0.9))
    scene.collection.objects.link(bpy.data.objects.new("preview_floor", me))

    def light(name, color, energy, size, loc):
        ld = bpy.data.lights.new(name, "AREA")
        ld.color, ld.energy, ld.size = hex_rgba(color)[:3], energy, size
        ob = bpy.data.objects.new(name, ld)
        ob.location = loc
        ob.rotation_euler = (Vector((0, 0, 1.0)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(ob)

    light("key_warm", "#FFD7A1", 120, 2.0, (2.0, 1.6, 2.6))
    light("fill_cool", "#B9C6D2", 60, 3.0, (1.5, -2.5, 1.4))
    light("rim_verdigris", "#9FF5DF", 90, 1.5, (-2.2, 0.5, 2.2))

    def camera(name, loc, target, ortho=None, lens=60):
        cd = bpy.data.cameras.new(name)
        if ortho:
            cd.type, cd.ortho_scale = "ORTHO", ortho
        else:
            cd.lens = lens
        ob = bpy.data.objects.new(name, cd)
        ob.location = loc
        ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(ob)
        return ob

    shots = [("miner_three_quarter", camera("cam_q", (2.6, 2.0, 1.7), (0.0, 0.0, 0.92), lens=55), 700, 900),
             ("miner_front_side", None, 1200, 800),
             ("miner_small_96", camera("cam_small", (4.6, 3.6, 3.6), (0.0, 0.0, 0.9), lens=60), 96, 128)]
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.view_settings.view_transform = "Standard"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    # front + side in one frame: a second copy of the figure turned 90 degrees, for the preview only
    root = bpy.data.objects["miner"]
    twin = []
    for o in [root] + list(root.children):
        c = o.copy()
        bpy.context.scene.collection.objects.link(c)
        twin.append(c)
    for c in twin[1:]:
        c.parent = twin[0]
    twin[0].location = (0.0, -0.75, 0.0)
    twin[0].rotation_euler = (0.0, 0.0, math.radians(-90))
    for c in twin:
        c.hide_render = True
    cam_fs = camera("cam_front_side", (12.0, -0.375, 0.95), (0.0, -0.375, 0.95), ortho=3.0)
    for name, cam, w, h in shots:
        for c in twin:
            c.hide_render = name != "miner_front_side"
        scene.camera = cam or cam_fs
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = w, h, 100
        scene.render.filepath = os.path.join(PREVIEW_DIR, name + ".png")
        bpy.ops.render.render(write_still=True)
        print(f"[miner] rendered {name}.png")
    for c in twin:
        bpy.data.objects.remove(c, do_unlink=True)
    scene.camera = shots[0][1]


def main():
    reset_scene()
    mats = make_materials()
    objs = build(mats)
    export_glb(objs)
    info = inspect_glb(GLB_PATH)
    print("[miner] glb", json.dumps(info, indent=1))
    problems = []
    if info["triangles"] > MAX_TRIANGLES:
        problems.append(f"{info['triangles']} triangles > {MAX_TRIANGLES}")
    if info["textures"] or info["extensionsUsed"]:
        problems.append("textures or extensions present")
    if DO_RENDER:
        render_previews()
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH, compress=True)
    if os.path.exists(BLEND_PATH + "1"):
        os.remove(BLEND_PATH + "1")
    print(f"[miner] total {time.perf_counter() - T0:.1f} s; {info['triangles']} tris, {info['bytes']} B")
    if problems:
        print("[miner] BUDGET FAILED: " + "; ".join(problems))
        if bpy.app.background:
            sys.exit(1)
        raise RuntimeError("; ".join(problems))
    print("[miner] budget ok")


main()
