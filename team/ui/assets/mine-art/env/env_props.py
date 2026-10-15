"""Props: steel sets, lamps, duct, cables, rubble, cabinets, portals, tyre tracks.

Props are rendered into the camera-projected textures. Only the few that can stand in
front of a person (portal gantries) are also exported as geometry; everything else is
painted onto the surfaces behind it by the projection (see env_export.py).
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

import env_geom as G
import env_shading as SH

PROP_COLL = "PROPS"
GLB_PROP_COLL = "PROPS_GLB"


class Batch:
    """Accumulates primitives for one material into one bmesh."""

    def __init__(self, name, mat):
        self.name = name
        self.mat = mat
        self.bm = bmesh.new()

    def cube(self, centre, size, rot=None):
        m = Matrix.Translation(Vector(centre))
        if rot is not None:
            m = m @ rot.to_4x4()
        m = m @ Matrix.Diagonal((size[0], size[1], size[2], 1.0))
        bmesh.ops.create_cube(self.bm, size=1.0, matrix=m)

    def beam(self, a, b, w, h, up=Vector((0, 0, 1))):
        """Box from a to b with cross-section w (horizontal) x h (vertical)."""
        a, b = Vector(a), Vector(b)
        d = b - a
        L = d.length
        if L < 1e-6:
            return
        x = d / L
        y = up.cross(x)
        if y.length < 1e-6:
            y = Vector((0, 1, 0)).cross(x)
        y.normalize()
        z = x.cross(y)
        rot = Matrix((x, y, z)).transposed()
        self.cube((a + b) / 2, (L, w, h), rot)

    def cyl(self, a, b, r, segs=12, r2=None, cap=True):
        a, b = Vector(a), Vector(b)
        d = b - a
        L = d.length
        if L < 1e-6:
            return
        q = d.normalized().to_track_quat("Z", "Y")
        m = Matrix.Translation((a + b) / 2) @ q.to_matrix().to_4x4()
        bmesh.ops.create_cone(self.bm, cap_ends=cap, cap_tris=False, segments=segs,
                              radius1=r, radius2=r if r2 is None else r2, depth=L, matrix=m)

    def rock(self, centre, size, rnd, flat=0.6):
        pts = []
        for _ in range(14):
            v = Vector((rnd.gauss(0, 1), rnd.gauss(0, 1), rnd.gauss(0, 1))).normalized()
            pts.append(v)
        bm2 = bmesh.new()
        for p in pts:
            bm2.verts.new(p)
        bmesh.ops.convex_hull(bm2, input=bm2.verts)
        rot = Vector((rnd.random(), rnd.random(), rnd.random())).to_track_quat("Z", "Y").to_matrix()
        s = Vector((size * rnd.uniform(0.8, 1.25), size * rnd.uniform(0.8, 1.25), size * flat))
        for v in bm2.verts:
            p = rot @ v.co
            v.co = Vector(centre) + Vector((p.x * s.x, p.y * s.y, p.z * s.z))
        me = bpy.data.meshes.new("tmp")
        bm2.to_mesh(me)
        bm2.free()
        self.bm.from_mesh(me)
        bpy.data.meshes.remove(me)

    def finish(self, coll):
        me = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(me)
        self.bm.free()
        me.materials.append(self.mat)
        ob = bpy.data.objects.new(self.name, me)
        coll.objects.link(ob)
        return ob


def cable(coll, pts, r, mat, name="CABLE"):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = r
    cu.bevel_resolution = 1
    sp = cu.splines.new("POLY")
    sp.points.add(len(pts) - 1)
    for p, q in zip(sp.points, pts):
        p.co = (q[0], q[1], q[2], 1.0)
    ob = bpy.data.objects.new(name, cu)
    cu.materials.append(mat)
    coll.objects.link(ob)
    return ob


# ------------------------------------------------------------------- wall runs

class Run:
    """A straight wall run where props mount: the wall line from p0 to p1 (plan), the
    floor height along it, the inward normal (from the wall into the working)."""

    def __init__(self, p0, p1, h0, h1, normal, wh=G.WALL, kind="drift", wid=None):
        self.p0, self.p1 = Vector(p0), Vector(p1)
        self.h0, self.h1 = h0, h1
        self.n = Vector((normal[0], normal[1], 0.0)).normalized()
        self.wh = wh
        self.kind = kind
        self.wid = wid
        self.L = (self.p1 - self.p0).length
        self.t = (self.p1 - self.p0).normalized()

    def at(self, s):
        f = s / self.L
        p = self.p0.lerp(self.p1, f)
        return Vector((p.x, p.y, self.h0 + (self.h1 - self.h0) * f))


def face_runs(mine):
    runs = []
    by = mine.back_y
    for s in mine.segments:
        a, b = s["a"], s["b"]
        if a.x > b.x:
            a, b = b, a
        kind = "drift" if mine.workings[s["wid"]]["kind"] == "drift" else "ramp"
        runs.append(Run((a.x, by), (b.x, by), a.z, b.z, (0, -1), wh=12.0, kind=kind, wid=s["wid"]))
    return runs


def crosscut_runs(mine):
    runs = []
    H = mine.nodes["a"].z
    for wid, (na, nb), side in (("w-05", ("a", "d"), 1), ("w-06", ("d", "c"), 1)):
        a, b = mine.nodes[na].xy, mine.nodes[nb].xy
        t = (b - a).normalized()
        left = Vector((-t.y, t.x))           # outer side (NW for a-d, NE for d-c)
        p0, p1 = a + left * G.HALF + t * 12.0, b + left * G.HALF - t * 6.0
        runs.append(Run(p0, p1, H, H, -left, wh=12.0, kind="crosscut", wid=wid))
    return runs


def zone_runs(mine, wid):
    w = mine.workings[wid]
    root, face = w["pts"][0], w["pts"][-1]
    H = root.z
    y_ch = face.y + 34.0
    x0 = root.x
    runs = [Run((x0 - G.HALF, mine.back_y - 16.0), (x0 - G.HALF, y_ch), H, H, (1, 0), kind="zone", wid=wid),
            Run((x0 - G.CHAMBER_X, y_ch), (x0 - G.HALF, y_ch), H, H, (0, -1), kind="chamber", wid=wid),
            Run((x0 - G.CHAMBER_X, face.y - 12.0), (x0 - G.CHAMBER_X, y_ch), H, H, (1, 0), kind="chamberwest", wid=wid)]
    return runs


# ------------------------------------------------------------------- builders

def build_props(mine, slope):
    sc = bpy.context.scene
    coll = bpy.data.collections.new(PROP_COLL)
    sc.collection.children.link(coll)
    glb = bpy.data.collections.new(GLB_PROP_COLL)
    sc.collection.children.link(glb)
    M = dict(
        steel=SH.flat_material("steel", "#4b4f53"),
        steel_dark=SH.flat_material("steel_dark", "#2c2f32"),
        duct=SH.flat_material("duct", "#7d8387"),
        duct_ring=SH.flat_material("duct_ring", "#555b5f"),
        cable=SH.flat_material("cable", "#151515"),
        cable_y=SH.flat_material("cable_y", "#9c7a22"),
        housing=SH.flat_material("lamp_housing", "#3b3d3f"),
        lens=SH.emissive_material("lamp_lens", "#ffd9a0", 38.0),
        yellow=SH.flat_material("machine_yellow", "#d9a425"),
        red=SH.flat_material("cabinet_red", "#8c2a1e"),
        concrete=SH.flat_material("concrete", "#7b776f"),
        stone=SH.flat_material("stone", "#6b665f"),
        stone_d=SH.flat_material("stone_dark", "#45413d"),
        roof=SH.flat_material("roof", "#55595b"),
        wood=SH.flat_material("wood", "#6a4a2c"),
        track=track_material(),
    )
    B = {k: Batch("P_" + k, m) for k, m in M.items() if k != "track"}
    rnd = random.Random(7)
    runs = face_runs(mine) + crosscut_runs(mine) + zone_runs(mine, "w-07") + zone_runs(mine, "w-12")
    for r in runs:
        steel_run(B, r, rnd, mine)
    for wid in ("w-03", "w-04", "w-10", "w-11"):
        duct_face(B, mine, wid, rnd)
    for wid in ("w-07", "w-12"):
        duct_zone(B, mine, wid, rnd)
        chamber_props(B, mine, wid, rnd)
    for node in ("b", "f"):
        junction_props(B, mine, node, rnd)
    for r in runs:
        cables(coll, M, r, rnd)
    rubble_edges(B, mine, rnd)
    bays(B, mine, rnd)
    portals(B, glb, M, mine, slope, rnd)
    tracks(coll, M["track"], mine)
    for b in B.values():
        if len(b.bm.verts):
            b.finish(coll)
        else:
            b.bm.free()


def steel_run(B, r, rnd, mine):
    step = {"drift": 20.0, "ramp": 30.0, "crosscut": 24.0, "zone": 15.0, "chamber": 9.0,
            "chamberwest": 13.0}[r.kind]
    n = max(1, int(r.L // step))
    off = (r.L - n * step) / 2.0
    wall_top = []
    for i in range(n + 1):
        s = off + i * step
        if s < 2.0 or s > r.L - 2.0:
            continue
        base = r.at(s)
        H = base.z
        wh = r.wh
        if r.kind == "ramp":
            # posts only where the wall is full height (no ledge right above)
            if not _full_wall(mine, base.x, H):
                continue
        foot = base + r.n * 0.45
        # I-beam post: flanges + web
        B["steel"].beam(foot, foot + Vector((0, 0, wh - 0.2)), 0.9, 0.2, up=r.n)
        B["steel_dark"].beam(foot + r.n * 0.35, foot + r.n * 0.35 + Vector((0, 0, wh - 0.2)), 0.25, 0.5, up=r.n)
        B["steel"].beam(foot + r.n * 0.7, foot + r.n * 0.7 + Vector((0, 0, wh - 0.2)), 0.9, 0.2, up=r.n)
        # base plate
        B["steel_dark"].cube(foot + r.n * 0.35 + Vector((0, 0, 0.15)), (1.6, 1.6, 0.3))
        wall_top.append(foot + Vector((0, 0, wh - 0.6)))
        # lamp hanging from an arm at the top of the set, in front of the duct
        reach = 4.6 if wh > 7.0 else 2.4
        arm0 = foot + r.n * 0.8 + Vector((0, 0, wh - 0.35))
        lamp_at = foot + r.n * (0.8 + reach - 0.3) + Vector((0, 0, wh - 1.2))
        B["steel_dark"].beam(arm0, arm0 + r.n * reach, 0.35, 0.35)
        B["steel_dark"].beam(arm0 + r.n * 1.6 - Vector((0, 0, 1.6)), arm0 + r.n * 0.05, 0.2, 0.2)
        B["steel_dark"].beam(arm0 + r.n * (reach - 0.3), lamp_at + Vector((0, 0, 0.6)), 0.1, 0.1)
        lamp(B, lamp_at, r.n)
        if r.kind in ("drift", "ramp") and i % 2 == 0:
            front = Vector((base.x, G.FRONT - 13.0, H))
            SH.add_lamp_light(front + Vector((0, 0, -7.0)), Vector((0, 0, -1)), power=SH.LAMP_POWER * 1.1,
                              kind="point", radius=3.0)
            if _full_wall(mine, base.x, H, G.GALLERY + 20.0):
                SH.add_lamp_light(front + Vector((0, 0, G.GALLERY + 7.0)), Vector((0, 0, -1)),
                                  power=SH.LAMP_POWER * 0.9, kind="point", radius=3.0)
    # waler beam along the top of the posts
    for a, b in zip(wall_top, wall_top[1:]):
        if (b - a).length < step * 1.6:
            B["steel"].beam(a + r.n * 0.35, b + r.n * 0.35, 0.5, 0.6, up=Vector((0, 0, 1)))


def _full_wall(mine, x, H, clear=28.0):
    for o in mine.segments:
        lo, hi = mine.seg_range(o)
        if lo <= x <= hi:
            h2 = mine.seg_h(o, x)
            if H + 0.5 < h2 < H + clear:
                return False
    return True


def lamp(B, at, n, light=True, power=None):
    at = Vector(at)
    B["housing"].cyl(at + Vector((0, 0, 0.25)), at + Vector((0, 0, 0.75)), 0.25, segs=8)
    B["housing"].cyl(at - Vector((0, 0, 0.15)), at + Vector((0, 0, 0.25)), 0.85, segs=12, r2=0.35)
    B["lens"].cyl(at - Vector((0, 0, 0.32)), at - Vector((0, 0, 0.12)), 0.62, segs=12)
    if light:
        p = power or SH.LAMP_POWER
        # pool on the floor and the foot of the wall
        SH.add_lamp_light(at - Vector((0, 0, 0.45)), Vector((0, 0, -1)) - n * 0.55, power=p,
                          kind="spot", radius=0.6, angle=135.0)
        # wash up the tall gallery wall behind the lamp
        SH.add_lamp_light(at - n * 0.5, Vector((0, 0, 0.6)) - n * 0.8, power=p * 0.9,
                          kind="spot", radius=0.8, angle=95.0)
        SH.add_lamp_light(at + n * 0.3 - Vector((0, 0, 0.5)), Vector((0, 0, -1)), power=p * 0.2,
                          kind="point", radius=1.5)


def duct_face(B, mine, wid, rnd):
    w = mine.workings[wid]
    a, b = w["pts"][0], w["pts"][-1]
    if a.x > b.x:
        a, b = b, a
    y = mine.back_y - 2.0
    z = a.z + 9.6
    x0, x1 = a.x + 4.0, b.x - 4.0
    if wid in ("w-04", "w-11"):
        x1 = b.x - 18.0
    if wid in ("w-03", "w-10"):
        x0 = a.x + 18.0
    duct_line(B, Vector((x0, y, z)), Vector((x1, y, z)), rnd)


def duct_zone(B, mine, wid, rnd):
    w = mine.workings[wid]
    root, face = w["pts"][0], w["pts"][-1]
    z = root.z + 7.4
    x = root.x - G.HALF + 1.9
    duct_line(B, Vector((x, mine.back_y - 2.0, z)), Vector((x, face.y + 40.0, z)), rnd)
    # elbow into the main duct and an outlet with a flexible bag at the chamber
    B["duct"].cyl(Vector((x, face.y + 40.0, z)), Vector((x, face.y + 30.0, z - 1.0)), 1.2, segs=16, r2=1.05)
    B["duct_ring"].cyl(Vector((x, face.y + 30.5, z - 0.95)), Vector((x, face.y + 29.6, z - 1.05)), 1.18, segs=16)


def duct_line(B, a, b, rnd):
    d = b - a
    L = d.length
    t = d / L
    seg = 9.0
    n = max(1, int(L // seg))
    B["duct"].cyl(a, b, 1.2, segs=20)
    for i in range(n + 1):
        p = a + t * (i * L / n)
        B["duct_ring"].cyl(p - t * 0.25, p + t * 0.25, 1.32, segs=20)
        # hanger strap to the wall top
        B["steel_dark"].beam(p + Vector((0, 0, 1.25)), p + Vector((0, 0, 1.9)), 0.15, 0.15)


def cables(coll, M, r, rnd):
    posts = []
    step = 6.0
    n = max(2, int(r.L // step))
    for k, (dz, mat, rr) in enumerate(((5.9, M["cable"], 0.13), (6.5, M["cable_y"], 0.11), (4.4, M["cable"], 0.16))):
        if r.kind in ("chamber", "chamberwest") and k == 2:
            continue
        pts = []
        sag_len = 24.0
        for i in range(int(r.L // 1.5) + 1):
            s = i * 1.5
            if s < 3.0 or s > r.L - 3.0:
                continue
            p = r.at(s)
            if r.kind == "ramp" and not _full_wall_cache(r, s):
                continue
            ph = (s % sag_len) / sag_len
            sag = 0.9 * 4 * ph * (1 - ph)
            pts.append(p + r.n * (0.35 + 0.15 * k) + Vector((0, 0, dz - sag)))
        if len(pts) > 2:
            cable(coll, pts, rr, mat)


def _full_wall_cache(r, s):
    return True


def rubble_edges(B, mine, rnd):
    """Rock chunks along the front lips of face-plane ledges and at the wall feet."""
    for s in mine.segments:
        lo, hi = mine.seg_range(s)
        x = lo + 3.0
        while x < hi - 3.0:
            H = mine.seg_h(s, x)
            y = G.FRONT + rnd.uniform(-1.0, 3.0)
            for _ in range(rnd.randint(1, 3)):
                size = rnd.uniform(0.5, 1.6)
                B["stone"].rock((x + rnd.uniform(-2, 2), y + rnd.uniform(-1.5, 1.5), H + size * 0.3), size, rnd)
            if rnd.random() < 0.18:
                for _ in range(rnd.randint(4, 9)):
                    size = rnd.uniform(0.4, 1.3)
                    B["stone_d"].rock((x + rnd.uniform(-3, 3), mine.back_y - rnd.uniform(0.6, 2.2), H + size * 0.3), size, rnd)
            x += rnd.uniform(3.0, 7.0)


def heap(B, centre, radius, height, rnd, n=40, key="stone"):
    c = Vector(centre)
    for _ in range(n):
        a = rnd.uniform(0, 2 * math.pi)
        r = radius * math.sqrt(rnd.random())
        h = height * (1 - (r / radius) ** 1.6)
        size = rnd.uniform(0.5, 1.5)
        B[key if rnd.random() < 0.7 else "stone_d"].rock(
            (c.x + r * math.cos(a), c.y + r * math.sin(a), c.z + max(0.2, h * rnd.uniform(0.5, 1.0))), size, rnd)


def chamber_props(B, mine, wid, rnd):
    """The zone face chamber: the richest corner of the art (the 3x zoom goes here).
    A corridor x in [-21, -11] m from the drift centreline stays free for the LHD anchor."""
    w = mine.workings[wid]
    root, face = w["pts"][0], w["pts"][-1]
    H = root.z
    x0 = root.x
    y_ch = face.y + 34.0
    xw = x0 - G.CHAMBER_X
    upper = H > -300
    # muck piles at the open face end, low so the walking line end stays visible
    heap(B, (x0 + 1.0, face.y - 12.0, H), 7.0, 2.6, rnd, n=55)
    heap(B, (x0 - 18.0, face.y - 13.0, H), 9.0, 3.4, rnd, n=70)
    heap(B, (xw + 6.0, face.y - 11.0, H), 7.0, 3.0, rnd, n=50)
    # cabinets, tool chests and a switch panel against the chamber north wall
    for dx, key, size in ((2.5, "yellow", (3.2, 1.5, 4.8)), (6.2, "yellow", (2.8, 1.5, 3.9)),
                          (10.0, "red", (3.4, 1.6, 3.2)), (13.6, "red", (2.6, 1.4, 2.4))):
        c = Vector((xw + dx, y_ch - 1.1, H + size[2] / 2))
        B[key].cube(c, size)
        B["steel_dark"].cube(c + Vector((0, -0.78, 0.2)), (size[0] * 0.8, 0.06, size[2] * 0.7))
    B["steel_dark"].cube((xw + 18.5, y_ch - 0.6, H + 4.0), (3.0, 0.4, 2.4))
    # cable reels between the cabinets and the drift
    for k, dx in enumerate((-9.0, -5.5)):
        reel = Vector((x0 + dx, y_ch - 3.5 - k * 0.5, H + 1.6))
        B["wood"].cyl(reel - Vector((1.0, 0, 0)), reel + Vector((1.0, 0, 0)), 1.6, segs=16)
        B["cable_y" if k else "cable"].cyl(reel - Vector((0.8, 0, 0)), reel + Vector((0.8, 0, 0)), 1.25, segs=16)
    # pipe stack on timber bearers along the west wall
    base = Vector((xw + 3.0, face.y + 2.0, H))
    for yy in (base.y - 5.0, base.y + 5.0):
        B["wood"].cube((base.x, yy, H + 0.25), (5.0, 0.6, 0.5))
    for row, cnt in enumerate((4, 3, 2)):
        for k in range(cnt):
            xx = base.x + (k - (cnt - 1) / 2) * 1.25
            zz = base.z + 1.1 + row * 1.08
            B["steel_dark"].cyl(Vector((xx, base.y - 6.5, zz)), Vector((xx, base.y + 6.5, zz)), 0.6, segs=10)
            B["yellow"].cyl(Vector((xx, base.y - 4.5, zz)), Vector((xx, base.y - 4.1, zz)), 0.62, segs=10)
    # spare steel arches stacked against the west wall
    for k in range(4 if upper else 3):
        arch(B, Vector((xw + 1.5, face.y + 15.0 + k * 2.2, H)), 3.4, rnd)
    # ventilation fan unit
    fan = Vector((xw + 6.0, y_ch - 6.0, H + 2.6))
    B["duct"].cyl(fan + Vector((0, 3.0, 0)), fan - Vector((0, 2.5, 0)), 2.2, segs=20)
    B["duct_ring"].cyl(fan - Vector((0, 2.5, 0)), fan - Vector((0, 2.9, 0)), 2.35, segs=20)
    B["steel_dark"].cube(fan - Vector((0, 0, 2.3)), (3.6, 4.2, 0.6))
    # timber, crates, a spare tyre
    for k in range(5):
        B["wood"].cube((xw + 11.0, face.y + 2.0, H + 0.35 + k * 0.7), (5.5, 1.8 - 0.15 * k, 0.6))
    for dx, dy, h in ((13.5, 14.0, 1.8), (15.8, 13.2, 1.4), (14.6, 15.6, 1.2)):
        B["wood"].cube((xw + dx, face.y + dy, H + h / 2), (2.0, 2.0, h))
    tyre = Vector((xw + 4.0, face.y - 3.0, H + 2.0))
    B["cable"].cyl(tyre - Vector((0, 0.9, 0)), tyre + Vector((0, 0.9, 0)), 2.0, segs=18)
    B["steel"].cyl(tyre - Vector((0, 0.95, 0)), tyre + Vector((0, 0.95, 0)), 0.9, segs=12)
    # floodlights on stands lighting the face and the chamber
    for sx, sy, aim in ((xw + 8.0, face.y - 4.0, Vector((0.6, -0.4, -0.7))),
                        (x0 - 9.5, face.y - 2.0, Vector((-0.3, -0.5, -0.8)))):
        p = Vector((sx, sy, H))
        B["steel"].beam(p, p + Vector((0, 0, 9.0)), 0.4, 0.4)
        for lx, ly in ((1.0, 0.0), (-0.5, 0.87), (-0.5, -0.87)):
            B["steel_dark"].beam(p + Vector((lx * 1.8, ly * 1.8, 0)), p + Vector((0, 0, 3.0)), 0.18, 0.18)
        head = p + Vector((0, 0, 9.3))
        B["housing"].cube(head, (1.6, 1.0, 1.1))
        B["lens"].cube(head + Vector((0, -0.52, -0.1)), (1.3, 0.08, 0.8))
        SH.add_lamp_light(head + Vector((0, -0.8, -0.2)), aim, power=SH.LAMP_POWER * 1.6, kind="spot",
                          radius=0.7, angle=110.0)
    # rubble along the west chamber wall
    for _ in range(26):
        size = rnd.uniform(0.6, 1.6)
        B["stone"].rock((xw + rnd.uniform(0.3, 2.8), face.y + rnd.uniform(-10, 32), H + size * 0.3), size, rnd)
    # warm spill on the spur nose and flanks below the floor (lit edges)
    SH.add_lamp_light(Vector((x0 - 12.0, face.y - 30.0, H - 8.0)), Vector((0, 0, -1)),
                      power=SH.LAMP_POWER * 1.4, kind="point", radius=3.0)
    SH.add_lamp_light(Vector((x0 + 22.0, face.y + 20.0, H - 10.0)), Vector((0, 0, -1)),
                      power=SH.LAMP_POWER * 1.0, kind="point", radius=3.0)


def junction_props(B, mine, node, rnd):
    """Supplies along the back wall beside the zone junction (behind the walking line)."""
    n = mine.nodes[node]
    H = n.z
    y = mine.back_y - 1.3
    # electrical cabinets and a tool chest between two steel sets
    B["yellow"].cube((n.x - 19.0, y, H + 2.3), (3.0, 1.6, 4.6))
    B["steel_dark"].cube((n.x - 19.0, y - 0.82, H + 2.6), (2.4, 0.06, 3.2))
    B["yellow"].cube((n.x - 15.4, y, H + 1.9), (2.6, 1.6, 3.8))
    B["red"].cube((n.x - 11.6, y + 0.1, H + 1.5), (3.2, 1.5, 3.0))
    for k in range(4):
        B["steel_dark"].cube((n.x - 11.6, y - 0.66, H + 0.5 + k * 0.7), (2.8, 0.08, 0.08))
    # pipe stack on timber bearers
    for xx in (n.x + 10.0, n.x + 20.0):
        B["wood"].cube((xx, y - 0.6, H + 0.25), (0.6, 3.6, 0.5))
    for row, cnt in enumerate((3, 2, 1)):
        for k in range(cnt):
            yy = y - 0.6 + (k - (cnt - 1) / 2) * 1.15
            zz = H + 1.05 + row * 1.0
            B["steel_dark"].cyl(Vector((n.x + 8.5, yy, zz)), Vector((n.x + 21.5, yy, zz)), 0.55, segs=10)
            B["yellow"].cyl(Vector((n.x + 9.0, yy, zz)), Vector((n.x + 9.4, yy, zz)), 0.57, segs=10)
    # spare steel arches stacked upright, crates
    for k in range(3):
        base = Vector((n.x + 30.0 + k * 1.6, y + 0.2, H))
        segs = 10
        pts = [base + Vector((-3.0 * math.cos(math.pi * i / segs), -0.5, 0.6 + 3.4 * math.sin(math.pi * i / segs)))
               for i in range(segs + 1)]
        for a, b in zip(pts, pts[1:]):
            B["steel"].beam(a, b, 0.3, 0.3)
    for k, (dx, h) in enumerate(((38.5, 1.8), (40.8, 1.4), (39.6, 1.2))):
        B["wood"].cube((n.x + dx, y - 0.4, H + h / 2 + (1.8 if k == 2 else 0)), (2.0, 2.0, h))
    # rubble at the wall foot
    for _ in range(14):
        size = rnd.uniform(0.5, 1.3)
        B["stone_d"].rock((n.x + rnd.uniform(-30, 45), y + rnd.uniform(0.0, 1.2), H + size * 0.3), size, rnd)


def arch(B, base, r, rnd):
    segs = 10
    pts = []
    for i in range(segs + 1):
        a = math.pi * i / segs
        pts.append(base + Vector((0.6 + 0.25 * i / segs, -r * math.cos(a), 1.0 + r * math.sin(a) * 1.15)))
    for a, b in zip(pts, pts[1:]):
        B["steel"].beam(a, b, 0.35, 0.35)
    B["steel"].beam(base + Vector((0.6, -r, 0.0)), pts[0], 0.35, 0.35)
    B["steel"].beam(base + Vector((0.85, r, 0.0)), pts[-1], 0.35, 0.35)


def bays(B, mine, rnd):
    H = mine.nodes["a"].z
    y = mine.back_y + 15.0
    for x in (72.0, 102.0):
        lamp(B, Vector((x, y - 2.2, H + 5.3)), Vector((0, -1, 0)))
        B["steel"].beam(Vector((x, y - 0.4, H)), Vector((x, y - 0.4, H + 6.4)), 0.8, 0.8)
        B["steel_dark"].beam(Vector((x, y - 0.4, H + 6.0)), Vector((x, y - 2.2, H + 6.0)), 0.3, 0.3)
    B["yellow"].cube((64.5, y - 1.2, H + 2.2), (2.6, 1.4, 4.4))
    He = mine.nodes["e"].z
    y2 = mine.back_y + 15.0
    for x in (-92.0, -62.0):
        lamp(B, Vector((x, y2 - 2.2, He + 5.0)), Vector((0, -1, 0)))
        B["steel"].beam(Vector((x, y2 - 0.4, He)), Vector((x, y2 - 0.4, He + 6.2)), 0.8, 0.8)
        B["steel_dark"].beam(Vector((x, y2 - 0.4, He + 5.8)), Vector((x, y2 - 2.2, He + 5.8)), 0.3, 0.3)
    B["red"].cube((-56.0, y2 - 1.2, He + 1.5), (3.0, 1.4, 3.0))
    heap(B, (-97.0, y2 - 3.0, He), 4.0, 2.0, rnd, n=20)


def portals(B, glb, M, mine, slope, rnd):
    """Portal gantries at both surface exits, a lamp room, light masts, gravel aprons."""
    gB = {k: Batch("G_" + k, M[k]) for k in ("steel", "concrete", "roof")}
    # portal A: the ramp w-01 arrives heading east at surface-a
    sa = mine.nodes["surface-a"]
    t = Vector((1, 0, 0))
    gantry(gB, B, Vector((sa.x - 14.0, mine.face_y, sa.z + 0.0)), t, "A", slope, rnd)
    # portal B: w-02 arrives heading north-west at surface-b
    sb = mine.nodes["surface-b"]
    d = (slope.S.xy - slope.B.xy).normalized()
    gantry(gB, B, Vector((*(sb.xy - d * 14.0), sb.z - 14.0 / slope.L * (slope.S.z - slope.B.z))),
           Vector((d.x, d.y, 0)), "B", slope, rnd)
    # aprons and lamp rooms on the plateau
    apron(B, Vector((sa.x - 18.0, mine.face_y + 40.0, 0.0)), 34.0, 52.0)
    hut(gB, Vector((sa.x - 46.0, mine.face_y + 46.0, 0.0)), 22.0, 13.0, 9.0)
    mast(B, Vector((sa.x - 30.0, mine.face_y + 12.0, 0.0)), Vector((0.5, -1.0, 0)))
    apron(B, Vector((sb.x - 8.0, sb.y + 22.0, 0.0)), 40.0, 40.0)
    hut(gB, Vector((sb.x + 26.0, sb.y + 26.0, 0.0)), 20.0, 12.0, 8.5)
    mast(B, Vector((sb.x - 26.0, sb.y + 4.0, 0.0)), Vector((0.6, -0.8, 0)))
    for b in gB.values():
        b.finish(glb)


def gantry(gB, B, centre, t, label, slope, rnd):
    n = Vector((-t.y, t.x, 0)).normalized()
    hw = G.HALF + 1.6
    h = 13.0
    for side in (-1, 1):
        foot = centre + n * hw * side
        gB["concrete"].cube(foot + Vector((0, 0, 0.9)), (2.6, 2.6, 1.8))
        gB["steel"].beam(foot + Vector((0, 0, 1.8)), foot + Vector((0, 0, h)), 1.1, 1.1, up=Vector((1, 0, 0)) if abs(t.x) < 0.9 else Vector((0, 1, 0)))
    a, b = centre - n * (hw + 0.6) + Vector((0, 0, h)), centre + n * (hw + 0.6) + Vector((0, 0, h))
    gB["steel"].beam(a, b, 1.4, 1.6)
    gB["steel"].beam(a - Vector((0, 0, 2.3)), b - Vector((0, 0, 2.3)), 0.6, 0.6)
    # canopy
    gB["roof"].beam(a + Vector((0, 0, 1.0)) - t * 3.0, b + Vector((0, 0, 1.0)) - t * 3.0, 7.0, 0.35)
    # blank plate on the beam (no text)
    gB["concrete"].beam(centre - n * 4.0 + Vector((0, 0, h + 0.1)) - t * 0.9,
                        centre + n * 4.0 + Vector((0, 0, h + 0.1)) - t * 0.9, 0.2, 2.2)
    for side in (-1, 1):
        at = centre + n * (hw - 1.2) * side + Vector((0, 0, h - 3.4)) - t * 1.2
        lamp(B, at, -t, power=SH.LAMP_POWER * 1.3)


def apron(B, c, w, d):
    B["concrete"].cube(c + Vector((0, 0, 0.06)), (w, d, 0.12))


def hut(gB, c, w, d, h):
    gB["concrete"].cube(c + Vector((0, 0, h / 2)), (w, d, h))
    gB["roof"].beam(c + Vector((-w / 2 - 0.8, 0, h + 0.4)), c + Vector((w / 2 + 0.8, 0, h + 0.4)), d + 1.6, 0.8)


def mast(B, base, aim):
    B["steel"].beam(base, base + Vector((0, 0, 30.0)), 0.7, 0.7)
    head = base + Vector((0, 0, 30.0))
    B["steel_dark"].beam(head - Vector((2.5, 0, 0)), head + Vector((2.5, 0, 0)), 0.5, 0.5)
    for dx in (-1.8, 1.8):
        p = head + Vector((dx, 0, -0.6))
        B["housing"].cube(p, (1.4, 1.0, 1.0))
        B["lens"].cube(p + Vector((0, -0.52, 0)), (1.2, 0.06, 0.8))
        SH.add_lamp_light(p + Vector((0, -0.8, 0)), Vector((aim.x, aim.y, -1.0)), power=SH.LAMP_POWER * 9.0,
                          kind="spot", radius=0.8, angle=70.0)


def tracks(coll, mat, mine):
    """Tyre track decals along every working: two strips beside the centreline."""
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    for wid, w in mine.workings.items():
        pts = w["pts"]
        for a, b in zip(pts, pts[1:]):
            d = b - a
            dp = Vector((d.x, d.y, 0))
            if dp.length < 1e-6:
                continue
            t = dp.normalized()
            n = Vector((-t.y, t.x, 0))
            L = d.length
            steps = max(1, int(L // 6.0))
            for side in (-2.6, 2.6):
                prev = None
                for i in range(steps + 1):
                    p = a + d * (i / steps) + Vector((0, 0, 0.04))
                    l = bm.verts.new(p + n * (side - 0.75))
                    r = bm.verts.new(p + n * (side + 0.75))
                    s = L * i / steps
                    if prev:
                        f = bm.faces.new((prev[0], prev[1], r, l))
                        for loop, c in zip(f.loops, ((prev[2], 0), (prev[2], 1), (s, 1), (s, 0))):
                            loop[uv].uv = c
                    prev = (l, r, s)
    me = bpy.data.meshes.new("TRACKS")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    ob = bpy.data.objects.new("TRACKS", me)
    coll.objects.link(ob)


def track_material():
    mat = bpy.data.materials.new("tyre_track")
    nb = SH.NB(mat)
    uvn = nb.n("ShaderNodeUVMap", uv_map="UVMap")
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.link(uvn.outputs[0], sep.inputs[0])
    u, v = sep.outputs[0], sep.outputs[1]
    tread = nb.math("LESS_THAN", nb.math("FRACT", nb.math("DIVIDE", nb.math("ADD", u, nb.math("MULTIPLY", v, 0.35)), 0.55)), 0.45)
    edge = nb.math("MULTIPLY", nb.math("GREATER_THAN", v, 0.12), nb.math("LESS_THAN", v, 0.88))
    noise = nb.n("ShaderNodeTexNoise", in_Scale=0.08, in_Detail=2.0)
    nb.link(sep.outputs[0], noise.inputs["Vector"]) if False else None
    alpha = nb.math("MULTIPLY", edge, nb.math("ADD", 0.25, nb.math("MULTIPLY", tread, 0.35)))
    dark = nb.n("ShaderNodeBsdfDiffuse")
    dark.inputs["Color"].default_value = SH.srgb("#3f3a33")
    tr = nb.n("ShaderNodeBsdfTransparent")
    mix = nb.n("ShaderNodeMixShader")
    nb.link(alpha, mix.inputs[0])
    nb.link(tr.outputs[0], mix.inputs[1])
    nb.link(dark.outputs[0], mix.inputs[2])
    out = nb.n("ShaderNodeOutputMaterial")
    nb.link(mix.outputs[0], out.inputs["Surface"])
    return mat
