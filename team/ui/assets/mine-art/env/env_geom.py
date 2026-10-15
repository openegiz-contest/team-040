"""Rock massif, workings and terrain for the mine-art environment (Blender, Z-up).

All coordinates are Blender world metres: bx = x - cx, by = y - cy, bz = k * z
(see mine_map.py). The main face plane is the vertical plane y = 0 of the mine
(by = -cy) that holds the four drifts and all ramp legs; the massif lies north of
it, the spurs of the two zone drifts stick out toward the viewer (south).
"""

import math
import random

import bmesh
import bpy
from mathutils import Vector
from mathutils.geometry import delaunay_2d_cdt

import mine_map

# Material slots shared by every rock-type object (order matters).
M_FLOOR, M_WALL, M_ROCK, M_GROUND, M_CUT = range(5)
SLOT_NAMES = ["floor", "wall", "rock", "ground", "rockcut"]

PROW_SLOPE = 2.2    # rock prows at the loop corners rise 2.2 m per metre inward
GALLERY = 45.0      # clear height of a gallery under the section band above
HALF = 7.0          # half width of a working (14 m trench)
WALL = 9.0          # wall height of a trench
FRONT = -64.0       # mean by of the massif front (cliff face of the face plane)
BACK_LINE_OFF = 10.0  # back wall of face-plane galleries is 10 m north of the centreline (floor 24 m deep)
CHAMBER_X = 36.0     # zone face chambers reach 36 m west of the zone drift centreline
TOP_Y = 900.0       # northern end of the massif block
X_MIN, X_MAX = -660.0, 660.0
Z_BOT = -900.0


# --------------------------------------------------------------------------- utils

def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def hash_noise(seed, *xs):
    """Deterministic value noise in [-1, 1] from integer-ish coordinates."""
    h = seed * 374761393
    for x in xs:
        h = (h ^ (int(math.floor(x * 1000.0)) * 668265263)) & 0xFFFFFFFF
        h = (h * 1274126177) & 0xFFFFFFFF
    return ((h >> 8) & 0xFFFF) / 32767.5 - 1.0


def link(ob, coll):
    coll.objects.link(ob)
    return ob


def make_mesh(name, verts, faces, face_mats=None, face_uvs=None, mats=None, coll=None,
              recalc=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    if mats:
        for m in mats:
            me.materials.append(m)
    if face_mats is not None:
        me.polygons.foreach_set("material_index", face_mats)
    if face_uvs is not None:
        uv = me.uv_layers.new(name="UVMap")
        flat = []
        for poly, fuv in zip(me.polygons, face_uvs):
            assert len(fuv) == poly.loop_total, (name, len(fuv), poly.loop_total)
            for c in fuv:
                flat.extend(c)
        uv.data.foreach_set("uv", flat)
    me.validate(clean_customdata=False)
    me.update()
    if recalc:
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
    ob = bpy.data.objects.new(name, me)
    if coll is not None:
        coll.objects.link(ob)
    return ob


def loft(name, rings, edge_mats, svals=None, cap_mats=(M_ROCK, M_ROCK), mats=None, coll=None,
         caps=True, flip=()):
    """Closed loft through rings of equal vertex count. edge_mats[j] is the material of
    the side band between ring vertex j and j+1. UV: u = svals[i], v = distance along the
    band from vertex j (from vertex j+1 for bands in `flip`)."""
    n, m = len(rings), len(rings[0])
    if svals is None:
        svals = [0.0]
        for i in range(1, n):
            svals.append(svals[-1] + (rings[i][0] - rings[i - 1][0]).length)
    verts = [p for ring in rings for p in ring]
    faces, fm, fuv = [], [], []
    for i in range(n - 1):
        for j in range(m):
            j2 = (j + 1) % m
            la = (rings[i][j2] - rings[i][j]).length
            lb = (rings[i + 1][j2] - rings[i + 1][j]).length
            va0, va1, vb0, vb1 = 0.0, la, 0.0, lb
            if j in flip:
                va0, va1, vb0, vb1 = la, 0.0, lb, 0.0
            a, b = i * m + j, i * m + j2
            c, d = (i + 1) * m + j2, (i + 1) * m + j
            faces.append((a, b, c, d))
            fm.append(edge_mats[j])
            fuv.append(((svals[i], va0), (svals[i], va1), (svals[i + 1], vb1), (svals[i + 1], vb0)))
    if caps:
        for idx, ring_i in ((0, 0), (1, n - 1)):
            f = tuple(ring_i * m + j for j in range(m))
            if not idx:
                f = f[::-1]
            faces.append(f)
            fm.append(cap_mats[idx])
            fuv.append(tuple((verts[k].y, verts[k].z) for k in f))
    return make_mesh(name, verts, faces, fm, fuv, mats, coll)


def heightfield_solid(name, poly2d, height_fn, bottom_fn, spacing, mats, coll, seed=1,
                      top_mat=M_ROCK, side_mat=M_ROCK, bottom_mat=M_ROCK, side_v_from=None,
                      jitter=0.3):
    """Closed solid over a simple plan polygon: top z = height_fn(x, y), bottom z =
    bottom_fn(x, y). Interior Steiner points on a jittered grid give facets."""
    rnd = random.Random(seed)
    # subdivide boundary
    boundary = []
    for i in range(len(poly2d)):
        a, b = Vector(poly2d[i]), Vector(poly2d[(i + 1) % len(poly2d)])
        L = (b - a).length
        k = max(1, int(round(L / spacing)))
        for t in range(k):
            boundary.append(a.lerp(b, t / k))
    pts = [Vector((p.x, p.y)) for p in boundary]
    nb = len(pts)
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]

    def inside(x, y):
        c = False
        for i in range(nb):
            a, b = pts[i], pts[(i + 1) % nb]
            if (a.y > y) != (b.y > y):
                xi = a.x + (y - a.y) * (b.x - a.x) / (b.y - a.y)
                if x < xi:
                    c = not c
        return c

    def dist_edge(x, y):
        best = 1e9
        p = Vector((x, y))
        for i in range(nb):
            a, b = pts[i], pts[(i + 1) % nb]
            ab = b - a
            t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-9)))
            best = min(best, (p - (a + ab * t)).length)
        return best

    gx = min(xs)
    while gx < max(xs):
        gy = min(ys)
        while gy < max(ys):
            x = gx + rnd.uniform(-jitter, jitter) * spacing
            y = gy + rnd.uniform(-jitter, jitter) * spacing
            if inside(x, y) and dist_edge(x, y) > spacing * 0.45:
                pts.append(Vector((x, y)))
            gy += spacing
        gx += spacing
    edges = [(i, (i + 1) % nb) for i in range(nb)]
    out = delaunay_2d_cdt(pts, edges, [list(range(nb))], 1, 1e-5)
    overts, oedges, ofaces = out[0], out[1], out[2]
    orig = out[3] if len(out) > 3 else None
    nv = len(overts)
    verts = [Vector((v.x, v.y, height_fn(v.x, v.y))) for v in overts]
    verts += [Vector((v.x, v.y, bottom_fn(v.x, v.y))) for v in overts]
    faces, fm, fuv = [], [], []
    for f in ofaces:
        faces.append(tuple(f))
        fm.append(top_mat)
        fuv.append(tuple((overts[i].x, overts[i].y) for i in f))
        faces.append(tuple(i + nv for i in f[::-1]))
        fm.append(bottom_mat)
        fuv.append(tuple((overts[i].x, overts[i].y) for i in f[::-1]))
    # boundary vertices in output: find by matching coordinates to the input boundary
    lookup = {}
    for i, v in enumerate(overts):
        lookup[(round(v.x, 4), round(v.y, 4))] = i
    bidx = [lookup[(round(p.x, 4), round(p.y, 4))] for p in boundary]
    s = 0.0
    for i in range(nb):
        a, b = bidx[i], bidx[(i + 1) % nb]
        L = (overts[b] - overts[a]).length
        faces.append((a, b, b + nv, a + nv))
        fm.append(side_mat)
        za, zb = verts[a].z, verts[b].z
        ref_a = side_v_from(overts[a].x, overts[a].y) if side_v_from else bottom_fn(overts[a].x, overts[a].y)
        ref_b = side_v_from(overts[b].x, overts[b].y) if side_v_from else bottom_fn(overts[b].x, overts[b].y)
        fuv.append(((s, za - ref_a), (s + L, zb - ref_b),
                    (s + L, verts[b + nv].z - ref_b), (s, verts[a + nv].z - ref_a)))
        s += L
    return make_mesh(name, verts, faces, fm, fuv, mats, coll)


# --------------------------------------------------------------------- the topology

class Mine:
    """Topology in Blender coordinates plus the face-plane analysis."""

    def __init__(self, topo):
        self.topo = topo
        self.cx, self.cy = topo["cx"], topo["cy"]
        self.nodes = {k: Vector(mine_map.to_blender((n["x"], n["y"], n["z"]), self.cx, self.cy))
                      for k, n in topo["nodes"].items()}
        self.workings = {}
        for wid, w in topo["workings"].items():
            pts = [Vector(mine_map.to_blender(p, self.cx, self.cy)) for p in w["polyline"]]
            self.workings[wid] = dict(w, pts=pts)
        self.face_y = mine_map.to_blender((0, 0, 0), self.cx, self.cy)[1]   # by of mine y = 0
        self.back_y = self.face_y + BACK_LINE_OFF
        self.segments = self._face_segments()

    def _face_segments(self):
        """Polyline segments lying in the face plane (mine y = 0 at both ends)."""
        segs = []
        kinds = {}
        for wid, w in self.workings.items():
            pts = w["pts"]
            names = [w["from"]] + [None] * (len(pts) - 2) + [w["to"]]
            for i in range(len(pts) - 1):
                a, b = pts[i], pts[i + 1]
                if abs(a.y - self.face_y) > 0.01 or abs(b.y - self.face_y) > 0.01:
                    continue
                segs.append(dict(wid=wid, idx=i, a=a.copy(), b=b.copy(), na=names[i], nb=names[i + 1]))
        # extensions: hairpin bends get a landing; surface ends and junction ends none
        for s in segs:
            for end in ("a", "b"):
                name = s["n" + end]
                if name is None:
                    s["ext_" + end] = 10.0 if s["idx"] == 0 else 9.5
                else:
                    s["ext_" + end] = 0.5 if self.topo["nodes"][name]["node_kind"] != "exit" else 0.0
        for s in segs:
            s["x0"], s["x1"] = min(s["a"].x, s["b"].x), max(s["a"].x, s["b"].x)
        return segs

    @staticmethod
    def seg_h(s, x):
        a, b = s["a"], s["b"]
        if abs(b.x - a.x) < 1e-6:
            return a.z
        t = (x - a.x) / (b.x - a.x)
        t = max(0.0, min(1.0, t))
        return a.z + (b.z - a.z) * t

    @staticmethod
    def seg_range(s):
        a, b = s["a"], s["b"]
        lo_ext = s["ext_a"] if a.x < b.x else s["ext_b"]
        hi_ext = s["ext_b"] if a.x < b.x else s["ext_a"]
        return s["x0"] - lo_ext, s["x1"] + hi_ext


# ------------------------------------------------------------------- the east slope

class EastSlope:
    """Terrain above the ramp w-02 second leg (bend -> surface-b): a hillside that
    descends with the road so that the trench walls stay low (camera side 5 m)."""

    def __init__(self, mine, cam_back):
        w = mine.workings["w-02"]
        self.B = w["pts"][1].copy()
        self.S = w["pts"][2].copy()
        d = self.S.xy - self.B.xy
        self.L = d.length
        self.dir = d / self.L
        self.c = Vector((cam_back[0], cam_back[1])).normalized()

    def road(self, x, y):
        p = Vector((x, y))
        t = max(0.0, min(self.L, (p - self.B.xy).dot(self.dir)))
        q = self.B.xy + self.dir * t
        h = lerp(self.B.z, self.S.z, t / self.L)
        return h, (p - q).length, (p - q).dot(self.c)

    def T(self, x, y):
        h, perp, side = self.road(x, y)
        wall = 5.0 if side > 0 else 9.0
        return min(0.0, h + wall + 0.30 * max(0.0, perp - HALF), self.dip(x, y))

    @staticmethod
    def dip(x, y, cx=0.0, cy=165.0, rx=270.0, ry=215.0, depth=0.0):
        """A valley in the massif above the crosscut loop: keeps the rock behind the loop
        from standing as one tall block; both portals stay on the 0 m surface."""
        r = math.sqrt(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2)
        return -depth * smooth(1.0 - r) if r < 1.0 else 0.0


def plateau_top(mine, slope, x):
    """Top of the massif above the face plane at x (None = open, the loop)."""
    if x >= 152.0:
        return slope.T(x, mine.face_y - 10.0)
    if x > -152.0:
        return None
    return 0.0


# ------------------------------------------------------------------ the cutters

def face_plane_cutters(mine, slope, mats, coll, seed=11):
    """One loft cutter per face-plane segment: floor, back wall and an undercut that
    opens the ledge toward the viewer. Heights adapt to the ledge above."""
    objs = []
    F = -260.0
    by0 = mine.back_y           # back wall line
    for si, s in enumerate(mine.segments):
        rnd = random.Random(seed * 100 + si)
        lo, hi = mine.seg_range(s)
        n = max(2, int(math.ceil((hi - lo) / 8.0)))
        xs = [lo + (hi - lo) * i / n for i in range(n + 1)]
        xs = [x if i in (0, n) else x + rnd.uniform(-1.6, 1.6) for i, x in enumerate(xs)]
        rings = []
        for x in xs:
            H = mine.seg_h(s, x)
            above = None
            for o in mine.segments:
                if o is s:
                    continue
                olo, ohi = mine.seg_range(o)
                if olo - 1e-6 <= x <= ohi + 1e-6:
                    h2 = mine.seg_h(o, x)
                    if h2 > H + 0.01 and (above is None or h2 < above):
                        above = h2
            top = plateau_top(mine, slope, x)
            if above is not None:
                gap = above - H
                g = min(GALLERY, max(gap - 14.0, 0.6))
            elif top is None:
                dist_end = min(x + 155.0, 155.0 - x)
                z_cap = H + 40.0 + PROW_SLOPE * max(0.0, dist_end)
                g = 600.0 if z_cap >= -1.0 else z_cap - H
            else:
                gap = top - H
                g = min(GALLERY, max(gap, 0.6))
                if gap - g < 14.0:
                    g = 600.0
            # gallery: floor, tall back wall, flat ceiling (the underside of the section
            # band above), open toward the viewer
            ring = [Vector((x, F, H)), Vector((x, by0, H)), Vector((x, by0, H + g)), Vector((x, F, H + g))]
            rings.append(ring)
        ob = loft(f"CUT_face_{s['wid']}_{s['idx']}", rings,
                  [M_FLOOR, M_WALL, M_CUT, M_CUT], svals=xs,
                  cap_mats=(M_WALL, M_WALL), mats=mats, coll=coll)
        objs.append(ob)
    return objs


def loop_polygon(mine, o, xw, xe, south):
    """Plan polygon of the crosscut loop: outer offset o of a-d and d-c, clipped by
    x = xw (west) and x = xe (east), south side at by = south."""
    a, d, c = mine.nodes["a"].xy, mine.nodes["d"].xy, mine.nodes["c"].xy
    t1 = (d - a).normalized()
    n1 = Vector((-t1.y, t1.x))            # left of a->d = north-west
    t2 = (c - d).normalized()
    n2 = Vector((-t2.y, t2.x))            # left of d->c = north-east
    p1 = a + n1 * o
    p2 = d + n2 * o

    def at_x(p, t, x):
        return p + t * ((x - p.x) / t.x)

    # apex: intersection of the two offset lines
    # p1 + t1*u = p2 + t2*v
    det = t1.x * (-t2.y) - t1.y * (-t2.x)
    rhs = p2 - p1
    u = (rhs.x * (-t2.y) - rhs.y * (-t2.x)) / det
    apex = p1 + t1 * u
    w1 = at_x(p1, t1, xw)
    e1 = at_x(p2, t2, xe)
    return [Vector((xw, south)), w1, apex, e1, Vector((xe, south))]


def loop_cutter(mine, mats, coll, seed=21):
    """Opens the crosscut loop behind level -120 down to its floor; outer walls flare
    back with height and carry facets."""
    rnd = random.Random(seed)
    H = mine.nodes["a"].z
    south = mine.back_y - 3.0
    levels = [H, H + GALLERY, H + 58, H + 76, H + 96, H + 108, H + 112, H + 134, H + 158, H + 180, H + 260]
    rings = []
    m_side = 10  # subdivisions per long side
    for li, z in enumerate(levels):
        up = max(0.0, z - (H + GALLERY))
        o = HALF + 0.12 * up + (14.0 if z > H + 110.0 else 0.0)
        xw = -155.0 + max(0.0, z - (H + 40)) / PROW_SLOPE
        xe = 155.0 - max(0.0, z - (H + 40)) / PROW_SLOPE
        P = loop_polygon(mine, o, xw, xe, south)
        ring = [P[0]]
        for k in range(m_side):
            ring.append(P[1].lerp(P[2], k / m_side))
        for k in range(m_side):
            ring.append(P[2].lerp(P[3], k / m_side))
        ring.append(P[3])
        ring.append(P[4])
        ring3 = []
        for idx, p in enumerate(ring):
            q = Vector((p.x, p.y, z))
            if 2 <= li < len(levels) - 1 and 1 < idx < len(ring) - 2:
                q.x += rnd.uniform(-7.0, 7.0)
                q.y += rnd.uniform(-7.0, 7.0)
                q.z += rnd.uniform(-5.0, 5.0)
            ring3.append(q)
        rings.append(ring3)
    # loft vertically: build manually (rings are horizontal)
    n, m = len(rings), len(rings[0])
    verts = [p for r in rings for p in r]
    faces, fm, fuv = [], [], []
    for i in range(n - 1):
        s = 0.0
        for j in range(m):
            j2 = (j + 1) % m
            L = (rings[i][j2] - rings[i][j]).length
            faces.append((i * m + j, i * m + j2, (i + 1) * m + j2, (i + 1) * m + j))
            fm.append(M_WALL if i == 0 else M_CUT)
            fuv.append(((s, rings[i][j].z - H), (s + L, rings[i][j2].z - H),
                        (s + L, rings[i + 1][j2].z - H), (s, rings[i + 1][j].z - H)))
            s += L
    faces.append(tuple(range(m))[::-1])
    fm.append(M_FLOOR)
    fuv.append(tuple((p.x, p.y) for p in rings[0][::-1]))
    faces.append(tuple((n - 1) * m + j for j in range(m)))
    fm.append(M_CUT)
    fuv.append(tuple((p.x, p.y) for p in rings[-1]))
    return make_mesh("CUT_loop", verts, faces, fm, fuv, mats, coll)


def slope_cutter(mine, slope, mats, coll, seed=31):
    rnd = random.Random(seed)
    x0, x1, y0, y1, st = X_MIN - 20.0, X_MAX + 20.0, mine.face_y - 240.0, TOP_Y + 20.0, 14.0
    nx, ny = int((x1 - x0) / st), int((y1 - y0) / st)
    grid = []
    for i in range(nx + 1):
        row = []
        for j in range(ny + 1):
            x = x0 + (x1 - x0) * i / nx
            y = y0 + (y1 - y0) * j / ny
            if 0 < i < nx and 0 < j < ny:
                x += rnd.uniform(-4, 4)
                y += rnd.uniform(-4, 4)
            t = slope.T(x, y)
            h, perp, side = slope.road(x, y)
            if t < -0.6:
                if perp > HALF + 3.0:
                    t += rnd.uniform(-1.6, 1.6)
                z = t
            else:
                z = 4.0
            row.append(Vector((x, y, z)))
        grid.append(row)
    verts, faces, fm, fuv = [], [], [], []
    idx = {}
    for i in range(nx + 1):
        for j in range(ny + 1):
            idx[(i, j)] = len(verts)
            verts.append(grid[i][j])
    top_off = len(verts)
    for i in range(nx + 1):
        for j in range(ny + 1):
            p = grid[i][j]
            verts.append(Vector((p.x, p.y, 200.0)))
    for i in range(nx):
        for j in range(ny):
            a, b, c, d = idx[(i, j)], idx[(i + 1, j)], idx[(i + 1, j + 1)], idx[(i, j + 1)]
            if (i + j) % 2 == 0:
                tris = [(a, d, c), (a, c, b)]
            else:
                tris = [(a, d, b), (b, d, c)]
            for t in tris:
                faces.append(t)
                pa, pb, pc = (verts[k] for k in t)
                nz = abs((pb - pa).cross(pc - pa).normalized().z)
                fm.append(M_GROUND if nz > 0.80 else M_CUT)
                fuv.append(tuple((verts[k].x, verts[k].y) for k in t))
            faces.append((a + top_off, b + top_off, c + top_off, d + top_off))
            fm.append(M_CUT)
            fuv.append(((0, 0), (1, 0), (1, 1), (0, 1)))
    # sides
    def side(seq):
        for k in range(len(seq) - 1):
            a, b = seq[k], seq[k + 1]
            faces.append((a, b, b + top_off, a + top_off))
            fm.append(M_CUT)
            fuv.append(((0, 0), (1, 0), (1, 1), (0, 1)))
    side([idx[(i, 0)] for i in range(nx + 1)])
    side([idx[(nx, j)] for j in range(ny + 1)])
    side([idx[(i, ny)] for i in range(nx, -1, -1)])
    side([idx[(0, j)] for j in range(ny, -1, -1)])
    return make_mesh("CUT_slope", verts, faces, fm, fuv, mats, coll)


def ramp_trench_cutter(mine, slope, mats, coll):
    """Trench of w-02 second leg (bend -> surface-b), with the landing at the bend."""
    B, S = slope.B, slope.S
    d = (S.xy - B.xy).normalized()
    n = Vector((d.y, -d.x))
    L = (S.xy - B.xy).length
    ss = [-11.0] + [L * k / 24 for k in range(25)]
    rings, sv = [], []
    for s in ss:
        t = max(0.0, s) / L
        p = B.xy + d * s
        H = lerp(B.z, S.z, t)
        ring = [Vector((*(p - n * HALF), H)), Vector((*(p + n * HALF), H)),
                Vector((*(p + n * HALF), H + 90.0)), Vector((*(p - n * HALF), H + 90.0))]
        rings.append(ring)
        sv.append(s)
    # loft rings expect a 'y' for caps: use generic loft with svals
    return loft("CUT_w-02_leg2", rings, [M_FLOOR, M_WALL, M_CUT, M_WALL], svals=sv,
                cap_mats=(M_WALL, M_WALL), mats=mats, coll=coll, flip=(3,))


def drill_bay_cutter(mine, mats, coll, x0=-100.0, x1=-52.0):
    H = mine.nodes["e"].z
    by0 = mine.back_y
    rings, xs = [], []
    for k in range(7):
        x = lerp(x0, x1, k / 6)
        ring = [Vector((x, by0 - 4.0, H)), Vector((x, by0 + 15.0, H)), Vector((x, by0 + 15.0, H + 14.0)),
                Vector((x, by0 + 6.0, H + 19.0)), Vector((x, by0 - 4.0, H + 24.0))]
        rings.append(ring)
        xs.append(x)
    return loft("CUT_drill_bay", rings, [M_FLOOR, M_WALL, M_CUT, M_CUT, M_CUT], svals=xs,
                cap_mats=(M_WALL, M_WALL), mats=mats, coll=coll)


# --------------------------------------------------------------------- the massif

def massif_block(mine, slope, mats, coll, seed=41):
    """The massif north of the face plane: a box whose south face is a faceted cliff."""
    rnd = random.Random(seed)
    st_x, st_z = 21.0, 19.0
    nx = int((X_MAX - X_MIN) / st_x)
    nz = int((0.0 - Z_BOT) / st_z)
    front = []
    for i in range(nx + 1):
        col = []
        for j in range(nz + 1):
            x = X_MIN + (X_MAX - X_MIN) * i / nx
            z = Z_BOT + (0.0 - Z_BOT) * j / nz
            if 0 < i < nx and 0 < j < nz:
                x += rnd.uniform(-6.5, 6.5)
                z += rnd.uniform(-6.0, 6.0)
            y = FRONT + 1.8 * math.sin(x / 61.0 + z / 37.0) + 1.0 * math.sin(x / 23.0 - z / 31.0) \
                + rnd.uniform(-1.0, 1.0)
            y = max(FRONT - 4.0, min(FRONT + 3.0, y))
            col.append(Vector((x, y, z)))
        front.append(col)
    verts, faces, fm, fuv = [], [], [], []
    idx = {}
    for i in range(nx + 1):
        for j in range(nz + 1):
            idx[(i, j)] = len(verts)
            verts.append(front[i][j])
    for i in range(nx):
        for j in range(nz):
            a, b, c, d = idx[(i, j)], idx[(i + 1, j)], idx[(i + 1, j + 1)], idx[(i, j + 1)]
            tris = [(a, b, c), (a, c, d)] if rnd.random() < 0.5 else [(a, b, d), (b, c, d)]
            for t in tris:
                faces.append(t)
                fm.append(M_ROCK)
                fuv.append(tuple((verts[k].x, verts[k].z) for k in t))
    # back corners
    def addv(p):
        verts.append(Vector(p))
        return len(verts) - 1
    tl = addv((X_MIN, TOP_Y, 0.0))
    tr = addv((X_MAX, TOP_Y, 0.0))
    bl = addv((X_MIN, TOP_Y, Z_BOT))
    br = addv((X_MAX, TOP_Y, Z_BOT))
    top_row = [idx[(i, nz)] for i in range(nx + 1)]
    bot_row = [idx[(i, 0)] for i in range(nx + 1)]
    left_col = [idx[(0, j)] for j in range(nz + 1)]
    right_col = [idx[(nx, j)] for j in range(nz + 1)]
    # top (plateau)
    f = top_row + [tr, tl]
    faces.append(tuple(f))
    fm.append(M_GROUND)
    fuv.append(tuple((verts[k].x, verts[k].y) for k in f))
    # bottom
    f = [bl, br] + bot_row[::-1]
    faces.append(tuple(f))
    fm.append(M_CUT)
    fuv.append(tuple((verts[k].x, verts[k].y) for k in f))
    # left side
    f = left_col[::-1] + [bl, tl][::-1]
    f = [tl] + left_col[::-1][0:0] + []
    f = left_col + [tl, bl]
    faces.append(tuple(f))
    fm.append(M_CUT)
    fuv.append(tuple((verts[k].y, verts[k].z) for k in f))
    f = right_col[::-1] + [br, tr][::-1]
    f = right_col + [tr, br]
    faces.append(tuple(f))
    fm.append(M_CUT)
    fuv.append(tuple((verts[k].y, verts[k].z) for k in f))
    # back
    f = (tl, tr, br, bl)
    faces.append(f)
    fm.append(M_CUT)
    fuv.append(tuple((verts[k].x, verts[k].z) for k in f))
    return make_mesh("MASSIF", verts, faces, fm, fuv, mats, coll)


def apply_boolean(target, cutters_coll, operation="DIFFERENCE"):
    mod = target.modifiers.new("cut", "BOOLEAN")
    mod.operation = operation
    mod.operand_type = "COLLECTION"
    mod.collection = cutters_coll
    mod.solver = "EXACT"
    mod.material_mode = "TRANSFER"
    try:
        mod.use_self = False
        mod.use_hole_tolerant = True
    except AttributeError:
        pass
    bpy.context.view_layer.objects.active = target
    for o in bpy.context.view_layer.objects:
        o.select_set(o == target)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def apply_boolean_object(target, cutter, operation="DIFFERENCE"):
    mod = target.modifiers.new("cut", "BOOLEAN")
    mod.operation = operation
    mod.object = cutter
    mod.solver = "EXACT"
    mod.material_mode = "TRANSFER"
    bpy.context.view_layer.objects.active = target
    for o in bpy.context.view_layer.objects:
        o.select_set(o == target)
    bpy.ops.object.modifier_apply(modifier=mod.name)


# ---------------------------------------------------------------------- the pillar

def crosscut_view_hmax(mine, cam_back, x, y):
    """Highest rock at plan (x, y) that keeps the crosscut walking lines visible:
    the ray from the line toward the camera must pass above it."""
    w = -Vector((cam_back[0], cam_back[1])).normalized()   # away from the camera
    tan_el = cam_back[2] / Vector((cam_back[0], cam_back[1])).length
    p = Vector((x, y))
    best = None
    for a_name, b_name in (("a", "d"), ("d", "c")):
        a, b = mine.nodes[a_name].xy, mine.nodes[b_name].xy
        e = b - a
        # p + w*s = a + e*t
        det = w.x * (-e.y) - w.y * (-e.x)
        if abs(det) < 1e-9:
            continue
        r = a - p
        s = (r.x * (-e.y) - r.y * (-e.x)) / det
        t = (w.x * r.y - w.y * r.x) / det
        if s > 0 and -0.02 <= t <= 1.02:
            h = tan_el * s - 1.2
            best = h if best is None else min(best, h)
    return best


def pillar(mine, cam_back, mats, coll, bay=(60.0, 114.0, 15.0), seed=51):
    """Rock island inside the crosscut loop, low where it would hide a crosscut."""
    a, d, c = mine.nodes["a"].xy, mine.nodes["d"].xy, mine.nodes["c"].xy
    H = mine.nodes["a"].z
    south = mine.back_y
    t1 = (d - a).normalized()
    n1 = Vector((t1.y, -t1.x))          # right of a->d = south-east (inside)
    t2 = (c - d).normalized()
    n2 = Vector((t2.y, -t2.x))          # right of d->c = south-west (inside)
    p1, p2 = a + n1 * HALF, d + n2 * HALF

    def at_y(p, t, y):
        return p + t * ((y - p.y) / t.y)
    det = t1.x * (-t2.y) - t1.y * (-t2.x)
    rhs = p2 - p1
    u = (rhs.x * (-t2.y) - rhs.y * (-t2.x)) / det
    apex = p1 + t1 * u
    pa = at_y(p1, t1, south)
    pc = at_y(p2, t2, south)
    bx0, bx1, bdep = bay
    poly = [pa, Vector((bx0, south)), Vector((bx0, south + bdep)), Vector((bx1, south + bdep)),
            Vector((bx1, south)), pc, apex]
    rnd = random.Random(seed)
    edges = [(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))]

    def dist_south(x, y):
        return y - south

    s_edges = edges[:5]
    c_edges = edges[5:]

    def _dist(x, y, eds):
        p = Vector((x, y))
        best = 1e9
        for a_, b_ in eds:
            ab = b_ - a_
            t = max(0.0, min(1.0, (p - a_).dot(ab) / ab.length_squared))
            best = min(best, (p - (a_ + ab * t)).length)
        return best

    def dist_s(x, y):
        return _dist(x, y, s_edges)

    def dist_cc(x, y):
        return _dist(x, y, c_edges)

    def dist_edges(x, y):
        p = Vector((x, y))
        best = 1e9
        for a_, b_ in edges:
            ab = b_ - a_
            t = max(0.0, min(1.0, (p - a_).dot(ab) / ab.length_squared))
            best = min(best, (p - (a_ + ab * t)).length)
        return best

    def height(x, y):
        hm = crosscut_view_hmax(mine, cam_back, x, y)
        de_c = dist_cc(x, y)
        de_s = dist_s(x, y)
        h = min(WALL + 1.5 * de_s, 4.0 + 0.8 * de_c, 62.0)
        h += hash_noise(seed, x * 0.37, y * 0.37) * 1.4
        if hm is not None:
            h = min(h, hm)
        return H + max(2.2, h)

    return heightfield_solid("PILLAR", [tuple(p) for p in poly], height, lambda x, y: H - 6.0,
                             9.0, mats, coll, seed=seed, top_mat=M_CUT, side_mat=M_WALL,
                             bottom_mat=M_CUT, side_v_from=lambda x, y: H, jitter=0.35)


# ------------------------------------------------------------------------- spurs

def spur(mine, wid, mats, coll, seed=61):
    """Promontory carrying a zone drift toward the viewer, with a face chamber."""
    w = mine.workings[wid]
    root, face = w["pts"][0], w["pts"][-1]
    H = root.z
    upper = H > -300
    rnd = random.Random(seed + (0 if upper else 7))
    x0 = root.x
    y_root = mine.face_y - 8.0
    y_nose = face.y - 17.0
    ys = []
    y = y_root
    while y > y_nose + 0.1:
        ys.append(y)
        y -= 7.0
    ys.append(y_nose)
    nside = 6
    rings = []
    for k, y in enumerate(ys):
        cham = smooth((-(y - (face.y + 36.0))) / 8.0)       # 0 near root, 1 in chamber
        xl = x0 - lerp(15.0, CHAMBER_X + 9.0, cham) + rnd.uniform(-1.2, 1.2)
        xr = x0 + 15.5 + rnd.uniform(-1.2, 1.2)
        top = H - 0.3 + 9.3 * smooth((-(y - (mine.face_y - 10.0))) / 18.0)
        if upper:
            tb = (y - y_nose) / (y_root - y_nose)          # 0 at nose, 1 at root
            bot = lerp(H - 26.0, H - 150.0, tb)
            shrink_b = 0.55
        else:
            bot = Z_BOT
            shrink_b = 1.0
        # nose rounding: last rings narrow
        nose = smooth((y_nose + 9.0 - y) / 9.0) if y < y_nose + 9.0 else 0.0
        # (nose factor grows toward the tip)
        nose = 1.0 - smooth((y - y_nose) / 9.0)
        cxm = (xl + xr) / 2
        sx = 1.0 - 0.35 * nose
        xl2, xr2 = cxm + (xl - cxm) * sx, cxm + (xr - cxm) * sx
        ring = []
        # bottom left -> bottom right
        bl = Vector((cxm + (xl2 - cxm) * shrink_b - (0 if upper else 12.0), y, bot))
        br = Vector((cxm + (xr2 - cxm) * shrink_b + (0 if upper else 12.0), y, bot))
        ring.append(bl)
        ring.append(br)
        for q in range(1, nside):
            f = q / nside
            z = lerp(bot, top, f)
            xx = lerp(br.x, xr2, f ** 0.6) + rnd.uniform(-1.8, 1.8)
            ring.append(Vector((xx, y + rnd.uniform(-1.0, 1.0), z + rnd.uniform(-2.5, 2.5))))
        ring.append(Vector((xr2, y, top)))
        ring.append(Vector((xl2, y, top)))
        for q in range(nside - 1, 0, -1):
            f = q / nside
            z = lerp(bot, top, f)
            xx = lerp(bl.x, xl2, f ** 0.6) + rnd.uniform(-1.8, 1.8)
            ring.append(Vector((xx, y + rnd.uniform(-1.0, 1.0), z + rnd.uniform(-2.5, 2.5))))
        if nose > 0:
            for p in ring:
                p.z = lerp(p.z, p.z, 1.0)
        rings.append(ring)
    m = len(rings[0])
    mats_e = [M_CUT] * m
    mats_e[nside] = M_CUT           # right top edge band: top surface
    mats_e[nside + 1] = M_CUT
    ob = loft(f"SPUR_{wid}", rings, mats_e, svals=ys, cap_mats=(M_CUT, M_CUT), mats=mats, coll=coll)
    # trench with the face chamber
    yb = mine.back_y + 2.0
    y_ch = face.y + 34.0
    poly = [(x0 - HALF, yb), (x0 + HALF, yb), (x0 + HALF, y_nose - 40.0), (x0 - CHAMBER_X, y_nose - 40.0),
            (x0 - CHAMBER_X, y_ch), (x0 - HALF, y_ch)]
    cut = prism(f"CUT_{wid}", poly, H, H + 34.0, mats, coll, bottom_mat=M_FLOOR, side_mat=M_WALL)
    apply_boolean_object(ob, cut)
    bpy.data.objects.remove(cut, do_unlink=True)
    return ob


def prism(name, poly, z0, z1, mats, coll, bottom_mat=M_FLOOR, side_mat=M_WALL, top_mat=M_CUT):
    n = len(poly)
    verts = [Vector((x, y, z0)) for x, y in poly] + [Vector((x, y, z1)) for x, y in poly]
    faces, fm, fuv = [], [], []
    faces.append(tuple(range(n))[::-1])
    fm.append(bottom_mat)
    fuv.append(tuple((poly[i][0], poly[i][1]) for i in range(n)[::-1]))
    faces.append(tuple(range(n, 2 * n)))
    fm.append(top_mat)
    fuv.append(tuple((poly[i][0], poly[i][1]) for i in range(n)))
    s = 0.0
    for i in range(n):
        j = (i + 1) % n
        L = (Vector(poly[j]) - Vector(poly[i])).length
        faces.append((i, j, j + n, i + n))
        fm.append(side_mat)
        fuv.append(((s, 0.0), (s + L, 0.0), (s + L, z1 - z0), (s, z1 - z0)))
        s += L
    return make_mesh(name, verts, faces, fm, fuv, mats, coll)


# ------------------------------------------------------------------ rock faceting

def facet_rock(ob, protect=(M_FLOOR, M_WALL, M_GROUND), edge_len=4.5, cell=19.0, amp=5.0,
               falloff=5.0, seed=0.0, max_iter=8, want=None):
    """Crystalline rock skin for rendering: refine rock faces to ~edge_len triangles,
    then displace each Voronoi cell along the normal by its own random plane, so the
    rock breaks into flat facets with crisp creases. Floors and walls stay exact; the
    displacement fades to zero within `falloff` metres of them."""
    from mathutils import noise
    import heapq
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    prot = set(protect)
    for it in range(max_iter):
        long_edges = [e for e in bm.edges
                      if e.calc_length() > edge_len
                      and any(f.material_index not in prot and (want is None or want(f)) for f in e.link_faces)]
        if not long_edges:
            break
        res = bmesh.ops.subdivide_edges(bm, edges=long_edges, cuts=1, use_grid_fill=False)
        bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 3])
    bm.verts.ensure_lookup_table()
    bm.normal_update()
    # distance from protected vertices (Dijkstra over edges)
    dist = {}
    heap = []
    for v in bm.verts:
        if any(f.material_index in prot for f in v.link_faces):
            dist[v.index] = 0.0
            heap.append((0.0, v.index))
    heapq.heapify(heap)
    while heap:
        d, i = heapq.heappop(heap)
        if d > dist.get(i, 1e9) or d > falloff:
            continue
        v = bm.verts[i]
        for e in v.link_edges:
            o = e.other_vert(v)
            nd = d + e.calc_length()
            if nd < dist.get(o.index, 1e9):
                dist[o.index] = nd
                heapq.heappush(heap, (nd, o.index))
    offs = []
    for v in bm.verts:
        d = dist.get(v.index, 1e9)
        w = smooth(d / falloff) if d < falloff else 1.0
        if w <= 0.0:
            offs.append(None)
            continue
        p = v.co / cell
        _, pts = noise.voronoi(p + Vector((seed, seed * 0.5, 0.0)), distance_metric="DISTANCE")
        s = pts[0]
        g = noise.noise_vector(s * 1.73 + Vector((5.1, 2.3, seed)))
        b = noise.noise(s * 2.31 + Vector((1.7, seed, 4.4)))
        disp = (b * 0.55 + (p - s).dot(g) * 0.9) * amp
        disp = max(-amp, min(amp, disp))
        n = Vector((0, 0, 0))
        for f in v.link_faces:
            if f.material_index not in prot:
                n += f.normal * f.calc_area()
        if n.length < 1e-9:
            offs.append(None)
            continue
        n.normalize()
        disp *= 0.55 + 0.45 * abs(n.z)
        if n.z > 0.55:
            disp = -abs(disp)      # tops are only carved, never raised toward walking lines
        offs.append(n * disp * w)
    for v, o in zip(bm.verts, offs):
        if o is not None:
            v.co += o
    bm.to_mesh(me)
    bm.free()
    me.update()
    return len(me.polygons)
