"""Props: steel sets with lamps, the ventilation duct, cables, tyre tracks, stones along
the floor lips, rubble, cabinets, cable reels and spare steel at the faces, the portals.
No rails, trains, crushers, conveyors or shaft: the simulation has none.

Props are rendered into the camera-projected textures. Only the portal frames and lamp
rooms (which a person can walk behind) are also exported as geometry (PROPS_GLB).
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

    def __init__(self, name, mat, smooth=False):
        self.name = name
        self.mat = mat
        self.smooth = smooth
        self.bm = bmesh.new()

    def cube(self, centre, size, rot=None):
        m = Matrix.Translation(Vector(centre))
        if rot is not None:
            m = m @ rot.to_4x4()
        m = m @ Matrix.Diagonal((size[0], size[1], size[2], 1.0))
        bmesh.ops.create_cube(self.bm, size=1.0, matrix=m)

    def beam(self, a, b, w, h, up=Vector((0, 0, 1))):
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

    def stone(self, centre, size, rnd, flat=0.7):
        """A rounded stone: a squashed ico sphere, slightly irregular."""
        bm2 = bmesh.new()
        bmesh.ops.create_icosphere(bm2, subdivisions=2, radius=1.0)
        s = Vector((size * rnd.uniform(0.85, 1.2), size * rnd.uniform(0.85, 1.2), size * flat * rnd.uniform(0.8, 1.1)))
        rot = Matrix.Rotation(rnd.uniform(0, 2 * math.pi), 3, "Z")
        for v in bm2.verts:
            p = v.co * (1.0 + 0.10 * math.sin(7.0 * v.co.x + rnd.random() * 6) * math.cos(5.0 * v.co.y))
            p = rot @ Vector((p.x * s.x, p.y * s.y, p.z * s.z))
            v.co = Vector(centre) + p
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
        if self.smooth:
            me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
        ob = bpy.data.objects.new(self.name, me)
        coll.objects.link(ob)
        return ob


# ------------------------------------------------------------------- lamps

def lamp(B, at, out_dir, floor_z, cone=True, wash=True, power=None):
    """A lamp: a dark housing, a warm lens, a faint light cone, a spot making the pool on
    the floor and (wash) a second spot washing up the wall behind it."""
    at = Vector(at)
    n = Vector((out_dir.x, out_dir.y, 0.0)).normalized()
    B["housing"].cyl(at + Vector((0, 0, 0.25)), at + Vector((0, 0, 0.75)), 0.25, segs=8)
    B["housing"].cyl(at - Vector((0, 0, 0.15)), at + Vector((0, 0, 0.25)), 0.85, segs=12, r2=0.35)
    B["lens"].cyl(at - Vector((0, 0, 0.32)), at - Vector((0, 0, 0.12)), 0.62, segs=12)
    h = at.z - floor_z
    if cone and h > 2.5:
        foot = Vector((at.x, at.y, floor_z + 0.05)) + n * 1.0
        B["cone"].cyl(at - Vector((0, 0, 0.3)), foot, 0.55, segs=16, r2=min(3.8, h * 0.5), cap=False)
    p = power or SH.LAMP_POWER
    SH.add_lamp_light(at - Vector((0, 0, 0.45)), Vector((0, 0, -1)) + n * 0.5, power=p, kind="spot",
                      radius=0.6, angle=130.0)
    if wash:
        SH.add_lamp_light(at + n * 0.6, Vector((0, 0, 0.55)) - n * 0.85, power=p * 1.0, kind="spot",
                          radius=0.8, angle=100.0)


# ------------------------------------------------------------------- wall runs

class Run:
    """A straight wall run where props mount: the wall line from p0 to p1 (plan), the floor
    height along it, the normal from the wall into the working, a wall-height function."""

    def __init__(self, p0, p1, h0, h1, normal, kind, wid, wh_fn):
        self.p0, self.p1 = Vector(p0), Vector(p1)
        self.h0, self.h1 = h0, h1
        self.n = Vector((normal[0], normal[1], 0.0)).normalized()
        self.kind = kind
        self.wid = wid
        self.wh_fn = wh_fn
        self.L = (self.p1 - self.p0).length
        self.t = (self.p1 - self.p0).normalized()

    def at(self, s):
        f = s / self.L
        p = self.p0.lerp(self.p1, f)
        return Vector((p.x, p.y, self.h0 + (self.h1 - self.h0) * f))

    def wh(self, s):
        return self.wh_fn(self.at(s))


def face_runs(mine, slope):
    """Back walls of the face-plane galleries; the usable wall height from the gallery stack
    (the island's 7 m side on the bay drifts, up to 12 m under a band)."""
    runs = []
    by = mine.back_y

    def wh_fn(s):
        def f(p):
            st = G.Stack(mine, slope, p.x)
            try:
                i, g = st.of(s)
            except KeyError:
                return 0.0
            if abs(g["z"] - mine.z120) < 0.5 and G.inside_bay(mine, p.x, mine.back_y + 1.0):
                return G.ISL - 0.6
            vis = g["Hc"] - G.RISE_S * (G.B_BACK + G.F_MIN) - 1.0
            return max(0.0, min(12.0, g["Hc"] - 2.0, vis + 6.0))
        return f
    for s in mine.segments:
        a, b = s["a"], s["b"]
        if a.x > b.x:
            a, b = b, a
        kind = "drift" if s["kind"] == "drift" else "ramp"
        runs.append(Run((a.x, by), (b.x, by), a.z, b.z, (0, -1), kind, s["wid"], wh_fn(s)))
    return runs


def crosscut_runs(mine):
    H = mine.z120
    a, d, c = mine.nodes["a"].xy, mine.nodes["d"].xy, mine.nodes["c"].xy
    runs = []
    t = (d - a).normalized()
    left = Vector((-t.y, t.x))                       # north-west: the slot's back wall
    runs.append(Run(a + left * G.B_BACK + t * 16.0, d + left * G.B_BACK - t * 10.0, H, H, -left, "crosscut", "w-05",
                    lambda p: 12.0))
    t = (c - d).normalized()
    left = Vector((-t.y, t.x))                       # north-east: the trench's back wall
    runs.append(Run(d + left * (G.B_BACK + 0.5) + t * 12.0, c + left * (G.B_BACK + 0.5) - t * 14.0, H, H, -left,
                    "crosscut", "w-06", lambda p: 12.0))
    return runs


def zone_runs(mine, wid):
    w = mine.workings[wid]
    root, face = w["pts"][0], w["pts"][-1]
    H = root.z
    x0 = root.x
    yn = face.y + G.CHAMBER_N
    xw = x0 - 46.0

    def wh(p):
        return max(0.0, min(10.0, G.zone_top(H, p.x - x0) - H - 1.2))
    return [Run((x0 - G.HALF, mine.face_y - 30.0), (x0 - G.HALF, yn), H, H, (1, 0), "zone", wid, wh),
            Run((xw + 10.0, yn), (x0 - G.HALF - 2.0, yn), H, H, (0, -1), "chamber", wid, wh),
            Run((xw, face.y - 6.0), (xw, yn - 10.0), H, H, (1, 0), "chamberwest", wid, wh)]


def steel_run(B, r, rnd):
    """Steel sets (I-beam posts with a waler) along a wall, each carrying a lamp on an arm."""
    step = {"drift": 22.0, "ramp": 30.0, "crosscut": 24.0, "zone": 15.0, "chamber": 11.0,
            "chamberwest": 12.0}[r.kind]
    n = max(1, int(r.L // step))
    off = (r.L - n * step) / 2.0
    tops = []
    for i in range(n + 1):
        s = off + i * step
        if s < 2.0 or s > r.L - 2.0:
            continue
        wh = r.wh(s)
        if wh < 5.5:
            tops.append(None)
            continue
        base = r.at(s)
        foot = base + r.n * 0.45
        B["steel"].beam(foot, foot + Vector((0, 0, wh - 0.2)), 0.9, 0.2, up=r.n)
        B["steel_dark"].beam(foot + r.n * 0.35, foot + r.n * 0.35 + Vector((0, 0, wh - 0.2)), 0.25, 0.5, up=r.n)
        B["steel"].beam(foot + r.n * 0.7, foot + r.n * 0.7 + Vector((0, 0, wh - 0.2)), 0.9, 0.2, up=r.n)
        B["steel_dark"].cube(foot + r.n * 0.35 + Vector((0, 0, 0.15)), (1.6, 1.6, 0.3))
        tops.append(foot + Vector((0, 0, wh - 0.6)))
        reach = 3.6 if wh > 7.0 else 2.2
        arm0 = foot + r.n * 0.8 + Vector((0, 0, wh - 0.35))
        lamp_at = foot + r.n * (0.8 + reach - 0.3) + Vector((0, 0, wh - 1.2))
        B["steel_dark"].beam(arm0, arm0 + r.n * reach, 0.35, 0.35)
        B["steel_dark"].beam(arm0 + r.n * 1.4 - Vector((0, 0, 1.4)), arm0 + r.n * 0.05, 0.2, 0.2)
        B["steel_dark"].beam(arm0 + r.n * (reach - 0.3), lamp_at + Vector((0, 0, 0.6)), 0.1, 0.1)
        lamp(B, lamp_at, r.n, base.z, cone=(i % 2 == 0))
    for a, b in zip(tops, tops[1:]):
        if a is not None and b is not None and (b - a).length < step * 1.6:
            B["steel"].beam(a + r.n * 0.35, b + r.n * 0.35, 0.5, 0.6, up=Vector((0, 0, 1)))


def duct_line(B, a, b):
    d = b - a
    L = d.length
    if L < 4.0:
        return
    t = d / L
    n = max(1, int(L // 9.0))
    B["duct"].cyl(a, b, 1.2, segs=20)
    for i in range(n + 1):
        p = a + t * (i * L / n)
        B["duct_ring"].cyl(p - t * 0.25, p + t * 0.25, 1.32, segs=20)
        B["steel_dark"].beam(p + Vector((0, 0, 1.25)), p + Vector((0, 0, 1.9)), 0.15, 0.15)


def ducts(B, mine, slope):
    """The ventilation duct along the main drifts (high on the tall level -240 walls, low on
    the island side of the bay drifts) and down the zone drifts to the face chambers."""
    y = mine.back_y - 2.0
    for wid, z, x0, x1 in (("w-03", mine.z120 + 5.0, -128.0, -4.0), ("w-04", mine.z120 + 5.0, 4.0, 60.0),
                           ("w-10", mine.z240 + 10.0, -146.0, -4.0), ("w-11", mine.z240 + 10.0, 4.0, 146.0)):
        duct_line(B, Vector((x0, y, z)), Vector((x1, y, z)))
    for wid in ("w-07", "w-12"):
        w = mine.workings[wid]
        root, face = w["pts"][0], w["pts"][-1]
        z = root.z + 6.4
        x = root.x - G.HALF + 1.9
        duct_line(B, Vector((x, mine.back_y - 2.0, z)), Vector((x, face.y + G.CHAMBER_N + 2.0, z)))
        # down from the main duct to the zone duct at the junction
        B["duct"].cyl(Vector((x, mine.back_y - 2.0, z)), Vector((x, mine.back_y - 2.0, root.z + 10.0 if root.z < -300 else z)),
                      1.2, segs=16)
        B["duct"].cyl(Vector((x, face.y + G.CHAMBER_N + 2.0, z)), Vector((x - 3.0, face.y + G.CHAMBER_N - 3.0, z - 1.0)),
                      1.2, segs=16, r2=1.05)


def cables(coll, M, r):
    for k, (dz, mat, rr) in enumerate(((4.9, M["cable"], 0.14), (5.5, M["cable_y"], 0.12), (3.8, M["cable"], 0.17))):
        pts = []
        for i in range(int(r.L // 1.5) + 1):
            s = i * 1.5
            if s < 3.0 or s > r.L - 3.0:
                if len(pts) > 2:
                    cable(coll, pts, rr, mat)
                pts = []
                continue
            if r.wh(s) < dz + 1.0:
                if len(pts) > 2:
                    cable(coll, pts, rr, mat)
                pts = []
                continue
            ph = (s % 24.0) / 24.0
            sag = 0.8 * 4 * ph * (1 - ph)
            pts.append(r.at(s) + r.n * (0.35 + 0.15 * k) + Vector((0, 0, dz - sag)))
        if len(pts) > 2:
            cable(coll, pts, rr, mat)


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


# ------------------------------------------------------------------- floors

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
                    p = a + d * (i / steps) + Vector((0, 0, 0.05))
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


def rubble_edges(B, mine, slope, rnd):
    """Stones along the front lips of the face-plane floors and at the wall feet."""
    FY = mine.face_y
    for s in mine.segments:
        lo, hi = mine.seg_range(s)
        x = lo + 3.0
        while x < hi - 3.0:
            st = G.Stack(mine, slope, x)
            i, g = st.of(s)
            H = mine.seg_h(s, x)
            y = FY - g["F"] + rnd.uniform(0.8, 3.0)
            for _ in range(rnd.randint(1, 3)):
                size = rnd.uniform(0.4, 1.2)
                B["stone"].stone((x + rnd.uniform(-2, 2), y + rnd.uniform(-0.6, 0.6), H + size * 0.35), size, rnd)
            if rnd.random() < 0.2:
                for _ in range(rnd.randint(4, 9)):
                    size = rnd.uniform(0.4, 1.1)
                    B["stone_d"].stone((x + rnd.uniform(-3, 3), mine.back_y - rnd.uniform(0.6, 2.0), H + size * 0.35),
                                       size, rnd)
            x += rnd.uniform(4.0, 9.0)


# ------------------------------------------------------------------- rubble, cabinets, chambers

def heap(B, centre, radius, height, rnd, n=40):
    c = Vector(centre)
    for _ in range(n):
        a = rnd.uniform(0, 2 * math.pi)
        r = radius * math.sqrt(rnd.random())
        h = height * (1 - (r / radius) ** 1.6)
        size = rnd.uniform(0.7, 1.7)
        key = "stone" if rnd.random() < 0.62 else "stone_d"
        B[key].stone((c.x + r * math.cos(a), c.y + r * math.sin(a), c.z + max(size * 0.45, h * rnd.uniform(0.6, 1.0))),
                     size, rnd)


def scatter(B, centre, radius, n, rnd):
    c = Vector(centre)
    for _ in range(n):
        a = rnd.uniform(0, 2 * math.pi)
        r = radius * math.sqrt(rnd.random())
        size = rnd.uniform(0.5, 1.2)
        B["stone" if rnd.random() < 0.6 else "stone_d"].stone((c.x + r * math.cos(a), c.y + r * math.sin(a),
                                                               c.z + size * 0.4), size, rnd)


def cabinet(B, base, facing, colour="cab_red", h=3.4):
    base = Vector(base)
    n = Vector((facing.x, facing.y, 0)).normalized()
    t = Vector((-n.y, n.x, 0))
    rot = Matrix((t, n, Vector((0, 0, 1)))).transposed()
    B["cab_body"].cube(base + Vector((0, 0, h / 2)), (3.0, 1.6, h), rot)
    B[colour].cube(base + n * 0.82 + Vector((0, 0, h / 2 + 0.15)), (2.4, 0.1, h * 0.76), rot)
    B["cab_body"].cube(base + Vector((0, 0, h + 0.1)), (3.4, 2.0, 0.25), rot)


def reel(B, c, axis, r=1.6, key="cable"):
    a = Vector(axis).normalized()
    B["wood"].cyl(c - a * 1.0, c + a * 1.0, r, segs=16)
    B[key].cyl(c - a * 0.8, c + a * 0.8, r * 0.78, segs=16)


def arch(B, base, r):
    segs = 10
    pts = []
    for i in range(segs + 1):
        a = math.pi * i / segs
        pts.append(base + Vector((0.6 + 0.25 * i / segs, -r * math.cos(a), 1.0 + r * math.sin(a) * 1.15)))
    for a, b in zip(pts, pts[1:]):
        B["steel"].beam(a, b, 0.35, 0.35)
    B["steel"].beam(base + Vector((0.6, -r, 0.0)), pts[0], 0.35, 0.35)
    B["steel"].beam(base + Vector((0.85, r, 0.0)), pts[-1], 0.35, 0.35)


def chamber_props(B, mine, wid, rnd):
    """The zone face chamber (the 3x zoom goes here): muck piles at the face, cabinets and a
    switch panel on the north wall, cable reels, a pipe stack and spare arches on the west
    wall, timber and crates, floodlights on stands. The LHD place (x -41..-7 m,
    y face+1.5..face+12.5 m) and the walking line stay free."""
    w = mine.workings[wid]
    face = w["pts"][-1]
    z = face.z
    x0 = face.x
    xw = x0 - 46.0
    yn = face.y + G.CHAMBER_N
    heap(B, (x0 - 14.0, face.y - 3.0, z), 4.4, 2.8, rnd, n=44)
    heap(B, (x0 - 36.0, face.y - 3.0, z), 3.8, 2.4, rnd, n=34)
    heap(B, (x0 + 3.5, face.y - 6.5, z), 2.6, 1.5, rnd, n=16)
    scatter(B, (x0 - 4.0, face.y - 3.0, z), 4.0, 8, rnd)
    scatter(B, (x0 - 26.0, face.y - 4.0, z), 6.0, 10, rnd)
    cabinet(B, (x0 - 36.0, yn - 1.0, z), Vector((0, -1, 0)), "cab_red")
    cabinet(B, (x0 - 32.2, yn - 1.0, z), Vector((0, -1, 0)), "cab_yellow", h=4.4)
    cabinet(B, (x0 - 28.4, yn - 1.0, z), Vector((0, -1, 0)), "cab_yellow", h=3.8)
    B["steel_dark"].cube((x0 - 23.5, yn - 0.5, z + 3.8), (3.0, 0.4, 2.4))
    reel(B, Vector((x0 - 17.0, yn - 3.2, z + 1.6)), (1, 0, 0))
    reel(B, Vector((x0 - 13.2, yn - 3.6, z + 1.6)), (1, 0, 0), key="cable_y")
    # pipe stack on timber bearers along the west wall
    bx, by0 = xw + 2.6, face.y - 2.0
    for yy in (by0 - 4.0, by0 + 4.0):
        B["wood"].cube((bx, yy, z + 0.25), (4.0, 0.6, 0.5))
    for row, cnt in enumerate((3, 2, 1)):
        for k in range(cnt):
            xx = bx + (k - (cnt - 1) / 2) * 1.2
            zz = z + 1.05 + row * 1.05
            B["steel_dark"].cyl(Vector((xx, by0 - 5.5, zz)), Vector((xx, by0 + 5.5, zz)), 0.58, segs=10)
            B["cab_yellow"].cyl(Vector((xx, by0 - 3.8, zz)), Vector((xx, by0 - 3.4, zz)), 0.6, segs=10)
    for k in range(3):
        arch(B, Vector((xw + 1.2, yn - 4.0 - k * 2.0, z)), 3.0)
    for k in range(4):
        B["wood"].cube((x0 - 6.0, yn - 2.0, z + 0.35 + k * 0.7), (4.5, 1.8 - 0.15 * k, 0.6))
    for dx, dy, h in ((-9.0, -1.6, 1.8), (-10.8, -3.2, 1.4)):
        B["wood"].cube((x0 + dx, yn + dy, z + h / 2), (2.0, 2.0, h))
    for sx, sy, aim in ((x0 - 25.0, face.y - 6.5, Vector((0.0, 0.6, -0.8))),
                        (x0 + 2.5, face.y + 15.0, Vector((-0.5, -0.5, -0.7)))):
        p = Vector((sx, sy, z))
        B["steel"].beam(p, p + Vector((0, 0, 8.0)), 0.4, 0.4)
        for lx, ly in ((1.0, 0.0), (-0.5, 0.87), (-0.5, -0.87)):
            B["steel_dark"].beam(p + Vector((lx * 1.6, ly * 1.6, 0)), p + Vector((0, 0, 2.8)), 0.18, 0.18)
        head = p + Vector((0, 0, 8.3))
        B["housing"].cube(head, (1.6, 1.0, 1.1))
        B["lens"].cube(head + Vector((0, -0.52, -0.1)), (1.3, 0.08, 0.8))
        SH.add_lamp_light(head + Vector((0, 0, -0.4)), aim, power=SH.LAMP_POWER * 1.3, kind="spot", radius=0.7,
                          angle=110.0)


def junction_props(B, mine, node):
    """Supplies along the back wall beside the zone junctions (behind the walking line)."""
    n = mine.nodes[node]
    H = n.z
    y = mine.back_y - 1.3
    cabinet(B, (n.x - 19.0, y, H), Vector((0, -1, 0)), "cab_yellow", h=4.4)
    cabinet(B, (n.x - 15.2, y, H), Vector((0, -1, 0)), "cab_yellow", h=3.6)
    cabinet(B, (n.x - 11.4, y, H), Vector((0, -1, 0)), "cab_red", h=3.0)
    for xx in (n.x + 12.0, n.x + 22.0):
        B["wood"].cube((xx, y - 0.6, H + 0.25), (0.6, 3.6, 0.5))
    for row, cnt in enumerate((3, 2, 1)):
        for k in range(cnt):
            yy = y - 0.6 + (k - (cnt - 1) / 2) * 1.15
            zz = H + 1.05 + row * 1.0
            B["steel_dark"].cyl(Vector((n.x + 10.5, yy, zz)), Vector((n.x + 23.5, yy, zz)), 0.55, segs=10)
            B["cab_yellow"].cyl(Vector((n.x + 11.0, yy, zz)), Vector((n.x + 11.4, yy, zz)), 0.57, segs=10)
    for k, (dx, h) in enumerate(((30.5, 1.8), (32.8, 1.4))):
        B["wood"].cube((n.x + dx, y - 0.4, H + h / 2), (2.0, 2.0, h))


def bays(B, mine):
    """The truck pocket behind w-04 and the drill terrace in front of w-10: lamps on posts."""
    H = mine.z120
    y = mine.back_y + 13.0
    for x in (66.8, 107.2):
        B["steel"].beam(Vector((x, y + 1.0, H)), Vector((x, y + 1.0, H + 6.0)), 0.8, 0.8)
        B["steel_dark"].beam(Vector((x, y + 1.0, H + 5.6)), Vector((x, y - 1.0, H + 5.6)), 0.3, 0.3)
        lamp(B, Vector((x, y - 1.0, H + 5.0)), Vector((0, -1, 0)), H)
    He = mine.z240
    yd = mine.face_y - 37.0
    for x in (-128.0, -72.0):
        B["steel"].beam(Vector((x, yd, He)), Vector((x, yd, He + 8.0)), 0.8, 0.8)
        lamp(B, Vector((x, yd + 1.6, He + 7.4)), Vector((0, 1, 0)), He, wash=False)


def portals(B, glb, M, mine, slope, rnd):
    """Portal frames at both surface exits, a lamp room beside each."""
    gB = {k: Batch("G_" + k, M[k]) for k in ("concrete", "roof")}
    sa = mine.nodes["surface-a"]
    gantry(gB, B, Vector((sa.x - 16.0, mine.face_y, _road_z(mine, "w-01", sa.x - 16.0))), Vector((1, 0, 0)))
    hut(gB, Vector((sa.x - 40.0, mine.face_y + 30.0, 0.0)), 20.0, 12.0, 8.0)
    sb = mine.nodes["surface-b"]
    d = (slope.S.xy - slope.B.xy).normalized()
    zb = sb.z - 16.0 / slope.L * (slope.S.z - slope.B.z)
    gantry(gB, B, Vector((*(sb.xy - d * 16.0), zb)), Vector((d.x, d.y, 0)))
    hut(gB, Vector((sb.x + 28.0, sb.y + 22.0, 0.0)), 18.0, 11.0, 7.5)
    for b in gB.values():
        b.finish(glb)


def _road_z(mine, wid, x):
    pts = mine.workings[wid]["pts"]
    a, b = pts[-2], pts[-1]
    t = max(0.0, min(1.0, (x - a.x) / (b.x - a.x)))
    return a.z + (b.z - a.z) * t


def gantry(gB, B, centre, t, h=12.0):
    """A plain concrete portal frame over the road."""
    n = Vector((-t.y, t.x, 0)).normalized()
    hw = G.HALF + 1.4
    for side in (-1, 1):
        foot = centre + n * hw * side
        gB["concrete"].cube(foot + Vector((0, 0, h / 2)), (2.2, 2.2, h))
    gB["concrete"].beam(centre - n * (hw + 1.1) + Vector((0, 0, h + 0.9)),
                        centre + n * (hw + 1.1) + Vector((0, 0, h + 0.9)), 3.0, 1.8)
    gB["roof"].beam(centre - n * (hw + 1.4) + Vector((0, 0, h + 2.0)) - t * 0.6,
                    centre + n * (hw + 1.4) + Vector((0, 0, h + 2.0)) - t * 0.6, 4.4, 0.4)
    for side in (-1, 1):
        at = centre + n * (hw - 1.6) * side + Vector((0, 0, h - 2.6)) - t * 1.4
        lamp(B, at, -t, centre.z, cone=True)


def hut(gB, c, w, d, h):
    gB["concrete"].cube(c + Vector((0, 0, h / 2)), (w, d, h))
    gB["roof"].cube(c + Vector((0, 0, h + 0.35)), (w + 1.4, d + 1.4, 0.7))


# ------------------------------------------------------------------- all props

def build_props(mine, slope):
    sc = bpy.context.scene
    coll = bpy.data.collections.new(PROP_COLL)
    sc.collection.children.link(coll)
    glb = bpy.data.collections.new(GLB_PROP_COLL)
    sc.collection.children.link(glb)
    M = dict(
        steel=SH.flat_material("steel", "#4f5357"),
        steel_dark=SH.flat_material("steel_dark", "#2e3134"),
        duct=SH.flat_material("duct", "#848a8e"),
        duct_ring=SH.flat_material("duct_ring", "#5a6064"),
        cable=SH.flat_material("cable", "#1a1a1a", smooth=True),
        cable_y=SH.flat_material("cable_y", "#a07c24", smooth=True),
        housing=SH.flat_material("lamp_housing", "#3f4143"),
        lens=SH.emissive_material("lamp_lens", "#ffdcaa", 16.0),
        cone=SH.glow_material("lamp_cone", "#ffe2b8", 0.03),
        stone=SH.flat_material("stone", "#a39d94", light=0.80, mid=0.55, dark=0.34, smooth=True),
        stone_d=SH.flat_material("stone_dark", "#6f6a63", light=0.80, mid=0.55, dark=0.34, smooth=True),
        cab_body=SH.flat_material("cabinet", "#8d9093"),
        cab_red=SH.flat_material("cabinet_red", "#9c3324"),
        cab_yellow=SH.flat_material("cabinet_yellow", "#c99a2a"),
        wood=SH.flat_material("wood", "#6e4e30"),
        concrete=SH.flat_material("concrete", "#8a867f"),
        roof=SH.flat_material("roof", "#5a5d60"),
    )
    smooth_keys = ("stone", "stone_d", "cone")
    B = {k: Batch("P_" + k, m, smooth=k in smooth_keys) for k, m in M.items()
         if k not in ("concrete", "roof", "cable", "cable_y")}
    B["cable"] = Batch("P_cable_b", M["cable"], smooth=True)
    B["cable_y"] = Batch("P_cable_y_b", M["cable_y"], smooth=True)
    rnd = random.Random(11)
    runs = face_runs(mine, slope) + crosscut_runs(mine) + zone_runs(mine, "w-07") + zone_runs(mine, "w-12")
    for r in runs:
        steel_run(B, r, rnd)
    ducts(B, mine, slope)
    for r in runs:
        cables(coll, M, r)
    for wid in ("w-07", "w-12"):
        chamber_props(B, mine, wid, rnd)
    for node in ("b", "f"):
        junction_props(B, mine, node)
    bays(B, mine)
    rubble_edges(B, mine, slope, rnd)
    # loose rock at the landings of the hairpin bends
    for s in mine.segments:
        for end in ("a", "b"):
            if s["bend_" + end]:
                p = s[end]
                xo = -1.0 if p.x < 0 else 1.0
                scatter(B, (p.x + xo * 8.0, mine.back_y - 2.0, p.z), 3.0, 6, rnd)
    portals(B, glb, M, mine, slope, rnd)
    tracks(coll, SH.track_material(), mine)
    for b in B.values():
        if len(b.bm.verts):
            b.finish(coll)
        else:
            b.bm.free()
