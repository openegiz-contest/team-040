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
SLAB = 9.0          # thinnest rock slab between two stacked galleries (near junctions and bends)
HALF = 7.0          # half width of a working (14 m trench)
WALL = 9.0          # wall height of a trench
FRONT = -64.0       # mean by of the massif front (cliff face of the face plane)
BACK_LINE_OFF = 10.0  # back wall of face-plane galleries is 10 m north of the centreline (floor 24 m deep)
CHAMBER_X = 36.0     # zone face chambers reach 36 m west of the zone drift centreline
TOP_Y = 900.0       # northern end of the massif block
X_MIN, X_MAX = -780.0, 780.0
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
                g = min(GALLERY, max(gap - SLAB, 0.6))
            elif top is None:
                # inside the crosscut loop: the ceiling rises from the rock prows at the
                # loop corners and is capped by the alcove roof (see loop_roof)
                dist_end = min(x + 155.0, 155.0 - x)
                z_cap = H + 40.0 + PROW_SLOPE * max(0.0, dist_end)
                roof = loop_roof(mine)
                zb, zf = min(z_cap, roof(by0)), min(z_cap, roof(F))
                rings.append([Vector((x, F, H)), Vector((x, by0, H)), Vector((x, by0, zb)), Vector((x, F, zf))])
                continue
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
        triangulate(ob, seed=si)
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


def loop_roof(mine):
    """The crosscut loop is an alcove, not an open pit: its roof is the plane through the
    top of the 45 m back wall that rises toward the viewer as the lines of sight do (slope
    back.z / -back.y, a hair less), so from MainView the roof is seen edge-on: everything
    under it (crosscuts, island, back wall) stays visible, and the window it cuts in the
    massif front ends on the same screen line as the top of the back wall."""
    back = mine_map.cam_basis()[0]
    S = back[2] / -back[1] - 0.003
    poly = loop_polygon(mine, HALF, -155.0, 155.0, mine.back_y - 3.0)
    y_back = max(p.y for p in poly)
    H = mine.nodes["a"].z

    def roof(y):
        return H + GALLERY + S * max(0.0, y_back - y)
    return roof


def loop_cutter(mine, mats, coll, seed=21):
    """Opens the crosscut loop behind level -120 under the alcove roof (loop_roof): a
    45 m lit back wall along the outer side of the crosscuts, faceted rock above it on
    the arms where the roof is higher, rock prows sloping in at the loop corners."""
    rnd = random.Random(seed)
    H = mine.nodes["a"].z
    south = mine.back_y - 3.0
    roof = loop_roof(mine)
    a, d, c = mine.nodes["a"].xy, mine.nodes["d"].xy, mine.nodes["c"].xy
    centre = (a + d + c) / 3.0
    m_side = 10  # subdivisions per long side
    rings = []
    for f in (None, 0.0, 0.34, 0.67, 1.0):
        zs = H if f is None else lerp(H + GALLERY, roof(south), f)
        xw = -155.0 + max(0.0, zs - (H + 40)) / PROW_SLOPE
        xe = 155.0 - max(0.0, zs - (H + 40)) / PROW_SLOPE
        P = loop_polygon(mine, HALF, xw, xe, south)
        ring = [P[0]]
        for kk in range(m_side):
            ring.append(P[1].lerp(P[2], kk / m_side))
        for kk in range(m_side):
            ring.append(P[2].lerp(P[3], kk / m_side))
        ring.append(P[3])
        ring.append(P[4])
        ring3 = []
        for idx, p in enumerate(ring):
            if f is None:
                z = H
            else:
                z = lerp(H + GALLERY, max(H + GALLERY, roof(p.y)), f)
            q = Vector((p.x, p.y, z))
            inner = 1 < idx < len(ring) - 2
            if f is not None and 0.0 < f < 1.0 and inner and z > H + GALLERY + 4.0:
                # facets: every vertex pushed away from the crosscuts by its own amount
                q.xy += (p.xy - centre).normalized() * rnd.uniform(0.0, 9.0)
                q.z += rnd.uniform(-4.0, 4.0)
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
    return triangulate(make_mesh("CUT_loop", verts, faces, fm, fuv, mats, coll), seed=seed)


def slope_cutter(mine, slope, mats, coll, seed=31):
    """Hillside above the w-02 trench. The cutter surface is the terrain lifted by 0.6 m,
    so it leaves the flat plateau alone and meets it along a smooth line (no wedges)."""
    rnd = random.Random(seed)
    # bounding box of the dipping terrain (+ a margin), sampled on a coarse grid
    xs_, ys_ = [], []
    for i in range(80):
        for j in range(80):
            x = X_MIN + (X_MAX - X_MIN) * i / 79.0
            y = mine.face_y - 240.0 + (TOP_Y - mine.face_y + 240.0) * j / 79.0
            if slope.T(x, y) < 0.0:
                xs_.append(x)
                ys_.append(y)
    x0, x1 = max(X_MIN - 20.0, min(xs_) - 60.0), min(X_MAX + 20.0, max(xs_) + 60.0)
    y0, y1, st = mine.face_y - 240.0, min(TOP_Y + 20.0, max(ys_) + 60.0), 14.0
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
            if t < -3.0 and perp > HALF + 3.0:
                t += rnd.uniform(-1.4, 1.4) * smooth((-t - 3.0) / 6.0)
            row.append(Vector((x, y, t + 0.6)))
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
                fm.append(M_GROUND)
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

def poisson_2d(x0, x1, y0, y1, r_fn, rnd, aniso=(0.0, 1.0), k=24, seeds=()):
    """Variable-radius Poisson-disc points in the rectangle [x0, x1] x [y0, y1].
    aniso = (angle, stretch): distances are measured in a frame rotated by `angle` whose
    first axis is shrunk by `stretch`, so the point spacing (and the facets of a Delaunay
    triangulation of them) is `stretch` times longer along that direction."""
    ca, sa = math.cos(aniso[0]), math.sin(aniso[0])
    st = aniso[1]

    def to_m(x, y):          # world -> metric frame
        return (x * ca + y * sa) / st, -x * sa + y * ca

    rmin = min(r_fn(x0 + (x1 - x0) * i / 12.0, y0 + (y1 - y0) * j / 12.0) for i in range(13) for j in range(13))
    cell = max(rmin * 0.6, 2.0) / math.sqrt(2.0)
    grid = {}
    pts = []

    def key(u, v):
        return int(math.floor(u / cell)), int(math.floor(v / cell))

    def ok(x, y, r):
        u, v = to_m(x, y)
        ku, kv = key(u, v)
        reach = int(math.ceil(r * 1.6 / cell)) + 1
        for i in range(ku - reach, ku + reach + 1):
            for j in range(kv - reach, kv + reach + 1):
                for q in grid.get((i, j), ()):
                    if (q[3] - u) ** 2 + (q[4] - v) ** 2 < (0.5 * (r + q[2])) ** 2:
                        return False
        return True

    def add(x, y, r):
        u, v = to_m(x, y)
        q = (x, y, r, u, v)
        grid.setdefault(key(u, v), []).append(q)
        pts.append(q)
        return q

    for (x, y) in seeds:
        add(x, y, r_fn(x, y))
    active = list(pts)
    x, y = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
    if ok(x, y, r_fn(x, y)):
        active.append(add(x, y, r_fn(x, y)))
    while active:
        i = rnd.randrange(len(active))
        px, py, pr, pu, pv = active[i]
        found = False
        for _ in range(k):
            a = rnd.uniform(0.0, 2.0 * math.pi)
            d = rnd.uniform(pr, 1.8 * pr)
            u, v = pu + d * math.cos(a), pv + d * math.sin(a)
            x = (u * st) * ca - v * sa
            y = (u * st) * sa + v * ca
            if not (x0 + 1.0 < x < x1 - 1.0 and y0 + 1.0 < y < y1 - 1.0):
                continue
            r = r_fn(x, y)
            if ok(x, y, r):
                active.append(add(x, y, r))
                found = True
                break
        if not found:
            active.pop(i)
    return [(q[0], q[1]) for q in pts]


def rect_boundary(x0, x1, y0, y1, step_fn):
    """Points along the rectangle boundary (corners included), counter-clockwise."""
    out = []
    for (ax, ay), (bx, by) in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)),
                               ((x0, y1), (x0, y0))):
        L = math.hypot(bx - ax, by - ay)
        t = 0.0
        while True:
            mx, my = ax + (bx - ax) * t / L, ay + (by - ay) * t / L
            out.append((mx, my))
            st = step_fn(mx, my)
            if t + 1.5 * st > L:
                break
            t += st
    return out


FACET_R = 15.0                              # Poisson radius of the front facets (m)
FACET_GRAIN = (math.radians(28.0), 1.45)    # facets elongated along a rising diagonal


def front_radius(x, z):
    """Facet size on the massif front: varied, coarse where the front is never on screen."""
    from mathutils import noise
    if z < -660.0:
        return 40.0
    n = noise.noise(Vector((x / 210.0, z / 160.0, 3.3)))
    # the big section faces between the galleries get the biggest facets
    band = smooth((420.0 - abs(x)) / 60.0) * smooth((z + 340.0) / 40.0) * smooth((-20.0 - z) / 20.0)
    return FACET_R * (1.0 + 0.45 * n) * (1.0 + 0.35 * band)


class Lumps:
    """The front is a pile of angular blocks: lump centres on a Poisson set (~2 facets
    across); a vertex is pushed toward the viewer by its lump's height times how far it is
    inside the lump (1 at the centre, 0 on the border between two lumps), so every block
    has a lit upper face, darker lower faces and a dark crease around it."""
    R = 27.0

    def __init__(self, rnd):
        from mathutils import noise
        ca, sa = math.cos(FACET_GRAIN[0]), math.sin(FACET_GRAIN[0])
        self.ca, self.sa, self.st = ca, sa, FACET_GRAIN[1]

        def r_fn(x, z):
            if z < -660.0:
                return 70.0
            band = smooth((420.0 - abs(x)) / 60.0) * smooth((z + 340.0) / 40.0) * smooth((-20.0 - z) / 20.0)
            return self.R * (1.0 + 0.3 * noise.noise(Vector((x / 170.0, z / 140.0, 9.4)))) * (1.0 + 0.3 * band)
        self.c = poisson_2d(X_MIN + 10.0, X_MAX - 10.0, Z_BOT + 10.0, -6.0, r_fn, rnd, aniso=FACET_GRAIN)
        self.amp = [rnd.uniform(4.5, 11.0) for _ in self.c]
        self.cell = 45.0
        self.grid = {}
        for i, (x, z) in enumerate(self.c):
            u, v = self.m(x, z)
            self.grid.setdefault((int(math.floor(u / self.cell)), int(math.floor(v / self.cell))), []).append(i)

    def m(self, x, z):
        return (x * self.ca + z * self.sa) / self.st, -x * self.sa + z * self.ca

    def inside(self, x, z):
        u, v = self.m(x, z)
        ku, kv = int(math.floor(u / self.cell)), int(math.floor(v / self.cell))
        best = []
        for i in range(ku - 2, ku + 3):
            for j in range(kv - 2, kv + 3):
                for k in self.grid.get((i, j), ()):
                    cu, cv = self.m(*self.c[k])
                    best.append(((cu - u) ** 2 + (cv - v) ** 2, k))
        best.sort()
        if len(best) < 2:
            return 0.0, 0.0
        d1, d2 = math.sqrt(best[0][0]), math.sqrt(best[1][0])
        return (d2 - d1) / max(d1 + d2, 1e-6), self.amp[best[0][1]]


def front_depth(lumps, x, z, rnd):
    """by of the massif front at (x, z): the block pile around FRONT."""
    from mathutils import noise
    e, amp = lumps.inside(x, z)
    big = 1.6 * noise.noise(Vector((x / 95.0, z / 70.0, 7.1)))
    y = FRONT + 4.5 - amp * e ** 0.85 + big + rnd.uniform(-1.1, 1.1)
    return max(FRONT - 8.0, min(FRONT + 5.5, y))


def near_floor(mine, x, z, margin):
    """True when (x, z) of the front is within `margin` m (height) of a face-plane floor."""
    for s in mine.segments:
        lo, hi = mine.seg_range(s)
        if lo - 6.0 <= x <= hi + 6.0 and abs(z - mine.seg_h(s, x)) < margin:
            return True
    return False


def massif_block(mine, slope, mats, coll, seed=41):
    """The massif north of the face plane: a box whose south face is a low-poly faceted
    cliff (Poisson points, Delaunay triangles, every vertex pushed in or out on its own,
    a few deep crevices). The facets are real geometry; the boolean cuts keep them flat."""
    rnd = random.Random(seed)
    lumps = Lumps(rnd)
    edge = rect_boundary(X_MIN, X_MAX, Z_BOT, 0.0, lambda x, z: 1.6 * front_radius(x, z))
    pts = poisson_2d(X_MIN, X_MAX, Z_BOT, 0.0, front_radius, rnd, aniso=FACET_GRAIN,
                     seeds=edge + list(lumps.c))
    out = delaunay_2d_cdt([Vector(p) for p in pts], [], [], 0, 1e-4)
    overts, ofaces = out[0], out[2]
    verts = [Vector((v.x, front_depth(lumps, v.x, v.y, rnd), v.y)) for v in overts]

    def on_edge(v):
        return abs(v.x - X_MIN) < 1e-3 or abs(v.x - X_MAX) < 1e-3 or abs(v.y) < 1e-3 or abs(v.y - Z_BOT) < 1e-3
    edge_flags = [on_edge(v) for v in overts]
    # crevices: short chains of vertices pushed deep into the rock
    nbr = [set() for _ in overts]
    for f in ofaces:
        for i in range(len(f)):
            a, b = f[i], f[(i + 1) % len(f)]
            nbr[a].add(b)
            nbr[b].add(a)
    n_cracks = tries = 0
    crev = [0.0] * len(overts)
    while n_cracks < 48 and tries < 4000:
        tries += 1
        i = rnd.randrange(len(overts))
        v = overts[i]
        if edge_flags[i] or v.y < -620.0 or v.y > -14.0 or near_floor(mine, v.x, v.y, 10.0):
            continue
        ang = math.radians(rnd.choice((rnd.uniform(-75, -35), rnd.uniform(35, 75), rnd.uniform(-100, -80))))
        d = Vector((math.cos(ang), math.sin(ang)))
        chain = [i]
        for _ in range(rnd.randint(2, 5)):
            cur = chain[-1]
            best, bd = None, 0.35
            for j in nbr[cur]:
                if j in chain or edge_flags[j]:
                    continue
                w = (overts[j] - overts[cur]).normalized().dot(d) + rnd.uniform(-0.15, 0.15)
                if w > bd:
                    best, bd = j, w
            if best is None or near_floor(mine, overts[best].x, overts[best].y, 10.0):
                break
            chain.append(best)
        if len(chain) < 3:
            continue
        depth = rnd.uniform(7.0, 11.0)
        for k, j in enumerate(chain):
            f = 1.0 if 0 < k < len(chain) - 1 else 0.55
            verts[j].y = max(verts[j].y, FRONT + depth * f)
            crev[j] = max(crev[j], f)
        n_cracks += 1
    faces, fm, fuv = [], [], []
    for f in ofaces:
        faces.append(tuple(f))
        fm.append(M_ROCK)
        fuv.append(tuple((verts[k].x, verts[k].z) for k in f))

    def ring(pred, keyf):
        return sorted([i for i, v in enumerate(overts) if pred(v)], key=keyf)
    top_row = ring(lambda v: abs(v.y) < 1e-3, lambda i: overts[i].x)
    bot_row = ring(lambda v: abs(v.y - Z_BOT) < 1e-3, lambda i: overts[i].x)
    left_col = ring(lambda v: abs(v.x - X_MIN) < 1e-3, lambda i: overts[i].y)
    right_col = ring(lambda v: abs(v.x - X_MAX) < 1e-3, lambda i: overts[i].y)

    def addv(p):
        verts.append(Vector(p))
        return len(verts) - 1
    tl = addv((X_MIN, TOP_Y, 0.0))
    tr = addv((X_MAX, TOP_Y, 0.0))
    bl = addv((X_MIN, TOP_Y, Z_BOT))
    br = addv((X_MAX, TOP_Y, Z_BOT))
    # the plateau: quiet low-poly ground (Poisson points, Delaunay), every inner vertex
    # sunk by up to 2.8 m so the dark ground reads as terrain, flat around the portals
    ring_ids = top_row + [tr, tl]
    bpts = [Vector((verts[i].x, verts[i].y)) for i in ring_ids]
    portals = [mine.nodes["surface-a"].xy, mine.nodes["surface-b"].xy]
    ipts = [Vector(p) for p in poisson_2d(X_MIN, X_MAX, FRONT + 16.0, TOP_Y, lambda x, y: 24.0 + 0.03 * max(0.0, y), rnd)]
    allp = bpts + ipts
    nb = len(bpts)
    cdt = delaunay_2d_cdt(allp, [(i, (i + 1) % nb) for i in range(nb)], [list(range(nb))], 1, 1e-4)
    cverts, cfaces, corig = cdt[0], cdt[2], cdt[3]
    cmap = []
    for k, v in enumerate(cverts):
        src = [o for o in corig[k] if o < nb]
        if src:
            cmap.append(ring_ids[src[0]])
        else:
            near_portal = min((v - q).length for q in portals) < 70.0
            z = 0.0 if near_portal else -rnd.uniform(0.0, 2.8)
            cmap.append(addv((v.x, v.y, z)))
    for f in cfaces:
        faces.append(tuple(cmap[i] for i in f))
        fm.append(M_GROUND)
        fuv.append(tuple((verts[cmap[i]].x, verts[cmap[i]].y) for i in f))
    for f, mi in (([bl, br] + bot_row[::-1], M_CUT),
                  (left_col + [tl, bl], M_CUT), (right_col + [tr, br], M_CUT), ((tl, tr, br, bl), M_CUT)):
        faces.append(tuple(f))
        fm.append(mi)
        fuv.append(tuple((verts[k].x, verts[k].y) for k in f))
    print("[env] massif front:", len(ofaces), "facets,", n_cracks, "crevices", flush=True)
    ob = make_mesh("MASSIF", verts, faces, fm, fuv, mats, coll)
    # `crev` (point attribute): 1 on the crevice vertices, read by the rock shader to sink
    # the facets that slope into a crevice into darkness
    at = ob.data.attributes.new("crev", "FLOAT", "POINT")
    at.data.foreach_set("value", crev + [0.0] * (len(ob.data.vertices) - len(crev)))
    return ob


def triangulate(ob, seed=0):
    """Split every polygon of a jittered loft or cutter into triangles (random diagonals)
    so its facets are defined before a boolean uses it."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    rnd = random.Random(seed)
    quads = [f for f in bm.faces if len(f.verts) == 4]
    a = [f for f in quads if rnd.random() < 0.5]
    sa = set(a)
    b = [f for f in quads if f not in sa]
    if a:
        bmesh.ops.triangulate(bm, faces=a, quad_method="FIXED", ngon_method="BEAUTY")
    if b:
        bmesh.ops.triangulate(bm, faces=b, quad_method="ALTERNATE", ngon_method="BEAUTY")
    rest = [f for f in bm.faces if len(f.verts) > 4]
    if rest:
        bmesh.ops.triangulate(bm, faces=rest, ngon_method="BEAUTY")
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()
    return ob


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
        h += hash_noise(seed, x * 0.37, y * 0.37) * 2.6
        if hm is not None:
            h = min(h, hm)
        return H + max(2.2, h)

    return heightfield_solid("PILLAR", [tuple(p) for p in poly], height, lambda x, y: H - 6.0,
                             12.0, mats, coll, seed=seed, top_mat=M_CUT, side_mat=M_WALL,
                             bottom_mat=M_CUT, side_v_from=lambda x, y: H, jitter=0.38)


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
        y -= 12.5
    if y_nose > ys[-1] - 6.0:
        ys[-1] = y_nose
    else:
        ys.append(y_nose)
    # flank subdivisions, denser toward the top (the part on screen)
    nside, gpow = (6, 1.3) if upper else (14, 1.6)

    def fz(f):
        return 1.0 - (1.0 - f) ** gpow
    rings = []
    for k, y in enumerate(ys):
        cham = smooth((-(y - (face.y + 36.0))) / 8.0)       # 0 near root, 1 in chamber
        xl = x0 - lerp(15.0, CHAMBER_X + 9.0, cham) + rnd.uniform(-1.5, 1.5)
        xr = x0 + 15.5 + rnd.uniform(-1.5, 1.5)
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
            f = fz(q / nside)
            z = lerp(bot, top, f)
            xx = lerp(br.x, xr2, f ** 0.6) + rnd.uniform(-4.0, 4.0)
            ring.append(Vector((xx, y + rnd.uniform(-2.5, 2.5), z + rnd.uniform(-5.0, 5.0))))
        ring.append(Vector((xr2, y, top)))
        ring.append(Vector((xl2, y, top)))
        for q in range(nside - 1, 0, -1):
            f = fz(q / nside)
            z = lerp(bot, top, f)
            xx = lerp(bl.x, xl2, f ** 0.6) + rnd.uniform(-4.0, 4.0)
            ring.append(Vector((xx, y + rnd.uniform(-2.5, 2.5), z + rnd.uniform(-5.0, 5.0))))
        rings.append(ring)
    # a faceted nose: two smaller rings bulging toward the viewer below the floor
    last = rings[-1]
    cen = sum(last, Vector((0.0, 0.0, 0.0))) / len(last)
    cen.z = max(cen.z, H - 55.0)
    for k, (dy, sc) in enumerate(((-6.0, 0.72), (-11.0, 0.38))):
        ring = []
        for p in last:
            q = cen + (p - cen) * sc
            q.y = y_nose + dy + rnd.uniform(-1.5, 1.5)
            q.x += rnd.uniform(-1.2, 1.2) * sc
            q.z = min(q.z + rnd.uniform(-1.2, 1.2) * sc, H - 2.0 - 0.01 * len(ring))
            ring.append(q)
        rings.append(ring)
        ys.append(y_nose + dy)
    m = len(rings[0])
    mats_e = [M_CUT] * m
    mats_e[nside] = M_CUT           # right top edge band: top surface
    mats_e[nside + 1] = M_CUT
    ob = loft(f"SPUR_{wid}", rings, mats_e, svals=ys, cap_mats=(M_CUT, M_CUT), mats=mats, coll=coll)
    triangulate(ob, seed=seed + (0 if upper else 7))
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

def _skin(ob, kinds, edge_len, move, seed, max_iter=7, want=None):
    """Refine the faces of the given material slots to ~edge_len triangles, then move
    every vertex whose faces are all of those slots by move(rnd, normal) (render only)."""
    rnd = random.Random(seed)
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    kinds = set(kinds)
    for _ in range(max_iter):
        long_edges = [e for e in bm.edges if e.calc_length() > edge_len
                      and any(f.material_index in kinds and (want is None or want(f)) for f in e.link_faces)]
        if not long_edges:
            break
        bmesh.ops.subdivide_edges(bm, edges=long_edges, cuts=1, use_grid_fill=False)
        bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 3])
    # flip edges between coplanar pieces toward well-shaped triangles (no slivers)
    for _ in range(2):
        fs = [f for f in bm.faces if f.material_index in kinds]
        es = [e for e in bm.edges if len(e.link_faces) == 2 and all(f.material_index in kinds for f in e.link_faces)
              and e.link_faces[0].normal.dot(e.link_faces[1].normal) > 0.9995]
        bmesh.ops.beautify_fill(bm, faces=fs, edges=es, method="ANGLE")
    bm.normal_update()
    moved = 0
    for v in bm.verts:
        fs = v.link_faces
        if not fs or any(f.material_index not in kinds for f in fs) or v.is_boundary:
            continue
        n = Vector((0.0, 0.0, 0.0))
        for f in fs:
            n += f.normal * f.calc_area()
        if n.length < 1e-9:
            continue
        n.normalize()
        # a short edge next to the vertex gets a proportionally small move (no spikes)
        lmin = min(e.calc_length() for e in v.link_edges)
        v.co += move(rnd, n) * min(1.0, lmin / (0.6 * edge_len))
        moved += 1
    bm.to_mesh(me)
    bm.free()
    me.update()
    return moved


def wall_skin(ob, seed=0):
    """Render-only skin of the working walls: refined to ~9 m triangles, every inner
    vertex pushed into the rock by its own depth (0.4-3.4 m), so the lit walls break into
    small flat facets. Vertices shared with floors and rock stay; nothing moves toward
    the walking lines."""
    return _skin(ob, (M_WALL,), 9.0, lambda rnd, n: -n * rnd.uniform(0.4, 3.4), seed)


def rock_skin(ob, seed=0, want=None):
    """Render-only second facet level on the rock: the big facets are split into ~9 m
    pieces tilted by a few degrees (+-0.45 m), a quiet variation inside each facet that
    shows at 3x and stays below the outline threshold. Tops are only carved."""
    def move(rnd, n):
        d = rnd.uniform(-0.45, 0.45)
        if n.z > 0.55:
            d = -abs(d)
        return n * d
    return _skin(ob, (M_ROCK, M_CUT), 9.0, move, seed, want=want)


def facet_attributes(ob, seed=0, only=None):
    """Face attributes read by the shaders and the outline pass:
    `fr` (colour) a random value per facet, equal for coplanar pieces of one facet;
    `mk` (float) material slot + 1 (floor 1, wall 2, rock 3, ground 4, rockcut 5)."""
    me = ob.data
    if only is None:
        for name in ("fr", "mk"):
            if name in me.attributes:
                me.attributes.remove(me.attributes[name])
        me.attributes.new("fr", "FLOAT_COLOR", "FACE")
        me.attributes.new("mk", "FLOAT", "FACE")
    fr, mk = me.attributes["fr"], me.attributes["mk"]
    cols = [0.0] * (4 * len(me.polygons))
    fr.data.foreach_get("color", cols)
    kinds = []
    for i, p in enumerate(me.polygons):
        kinds.append(float(p.material_index + 1))
        if only is not None and p.material_index not in only:
            continue
        n = p.normal
        key = (round(n.x * 40.0), round(n.y * 40.0), round(n.z * 40.0), seed)
        r = random.Random(hash(key) & 0xFFFFFFFF)
        cols[4 * i:4 * i + 4] = [r.random(), r.random(), r.random(), 1.0]
    fr.data.foreach_set("color", cols)
    mk.data.foreach_set("value", kinds)
    me.polygons.foreach_set("use_smooth", [False] * len(me.polygons))
    me.update()
