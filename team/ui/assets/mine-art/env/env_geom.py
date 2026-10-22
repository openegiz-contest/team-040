"""Rock massif, workings and terrain of the illustrated mine (Blender, Z-up).

The clean isometric cutaway: one dark rock body cut by vertical section faces and
horizontal benches, the workings cut into it as tunnels opened along their length.

All coordinates are Blender world metres: bx = x - cx, by = y - cy, bz = k * z
(mine_map.py). FY is the by of the mine plane y = 0 that holds the four drifts and all
ramp legs (the "face plane").

- Face-plane galleries are slots in a terraced section face south of FY: a flat floor
  from the back wall (B_BACK behind the walking line) to its front edge (F in front of
  it), a back wall, and a ceiling that is the underside of the rock band above, whose
  front edge hangs down in irregular drips. F of every floor is chosen so that the walking
  line of the gallery below stays visible under the band (sight rise RISE_S per metre
  south); the lower a floor, the further out it may reach (terraces).
- Above level -120 between junctions a and c the rock is cut down to a low bench (the
  bay): the crosscut a-d is a slot in the bay's north-west wall, d-c an open trench at the
  foot of its north-east wall, the drifts run along its south edge.
- The zone drifts run toward the viewer on a promontory (w-07, level -120) and a
  peninsula (w-12, level -240); the promontory's underside rises toward the viewer as
  the lines of sight do, so everything under it stays visible.
- The surface is a dark plateau at 0 m; ramp w-02 climbs to portal B in a trench through
  a hillside that descends with the road (EastSlope).
"""

import math
import random

import bmesh
import bpy
from mathutils import Vector

import mine_map

# Material slots shared by every rock object (order matters).
M_FLOOR, M_WALL, M_TOP, M_CUT, M_CEIL = range(5)
SLOT_NAMES = ["floor", "wall", "top", "cut", "ceiling"]

HALF = 7.0          # half width of a working (14 m)
B_BACK = 10.0       # back wall of a face-plane gallery behind the walking line
SLAB = 2.5          # thinnest rock between two stacked galleries
F_MIN = 8.0         # shallowest front edge of a floor in front of the walking line
F_RAMP = 22.0       # front edge of a ramp floor where the gallery below allows it
F_DRIFT = 22.0      # front edge of the level -120 drift floors
F_FACE = 22.0       # the lowest floor at x (no gallery below): the section face below it
F_SLOPE = 0.5       # floor fronts change by at most 0.5 m per metre along a gallery
F_MID = 30.0        # ... under the level -240 drifts
F_DRILL = 40.0      # ... the drill terrace in front of w-10
HC_RAMP = 38.0      # clear height of a gallery under the band above (where the stack allows)
HC_LOW = 42.0       # ... of the level -240 drifts
ISL = 7.0           # the bench (island) of the bay above level -120
CC_FRONT = 12.0     # the bay's north-west wall: 12 m on the island side of the a-d line
CC_OPEN = 4.0       # open floor in front of that wall
CHAMBER_N = 19.0    # zone face chambers reach 19 m north of the face (8 m beyond it), 46 m west
EXT_LAND = 12.0     # landing beyond a hairpin bend: its rounded (elliptical) end ...
FLARE = 9.0         # ... plus a fillet where that end meets the rock face (no sharp vertical edge)
EXT_BEND = EXT_LAND + FLARE
F_SMOOTH = 7.0      # floor fronts: opened (min, then mean) over +-7 m, so they flow in curves
R_TIP = 18.0        # crosscut-loop island corners
R_MOUTH = 9.0       # zone drift mouths and the drift/chamber corners
RING = 2.0          # loft ring spacing of the slots (drip width)
TOP_Y = 900.0
X_MIN, X_MAX = -780.0, 780.0
Z_BOT = -900.0
Z_SKY = 400.0

_back = mine_map.cam_basis()[0]
VB = Vector((_back[0], _back[1])).normalized()          # toward the camera, in plan
TAN_EL = _back[2] / math.hypot(_back[0], _back[1])
RISE_S = TAN_EL / -VB.y                                  # sight rise per metre toward -y
RISE_X = TAN_EL / VB.x                                   # ... per metre toward +x


# --------------------------------------------------------------------------- utils

def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def bump(x, a, b, r):
    """1 inside [a, b], easing to 0 over r outside."""
    return smooth((x - (a - r)) / r) * smooth(((b + r) - x) / r)


def hash01(seed, i):
    h = (seed * 374761393 + int(i) * 668265263) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h >> 8) & 0xFFFF) / 65535.0


def make_mesh(name, verts, faces, face_mats=None, face_uvs=None, mats=None, coll=None, recalc=True):
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


def loft(name, rings, band_mats, uvf=None, cap_mats=(M_WALL, M_WALL), mats=None, coll=None):
    """Closed loft through rings (lists of Vector, equal counts). band_mats[j] is the
    material of the band between ring vertex j and j+1; uvf(i, j, k, p) gives the UV of
    ring i's vertex k (k = j or j+1) as a corner of band j."""
    n, m = len(rings), len(rings[0])
    verts = [p for ring in rings for p in ring]
    faces, fm, fuv = [], [], []
    for i in range(n - 1):
        for j in range(m):
            j2 = (j + 1) % m
            faces.append((i * m + j, i * m + j2, (i + 1) * m + j2, (i + 1) * m + j))
            fm.append(band_mats[j])
            if uvf is None:
                fuv.append(((0, 0),) * 4)
            else:
                fuv.append((uvf(i, j, j, rings[i][j]), uvf(i, j, j2, rings[i][j2]),
                            uvf(i + 1, j, j2, rings[i + 1][j2]), uvf(i + 1, j, j, rings[i + 1][j])))
    for idx, ri in ((0, 0), (1, n - 1)):
        f = tuple(ri * m + j for j in range(m))
        if not idx:
            f = f[::-1]
        faces.append(f)
        fm.append(cap_mats[idx])
        fuv.append(tuple((verts[k].x, verts[k].z) for k in f))
    ob = make_mesh(name, verts, faces, fm, fuv, mats, coll)
    return ob


def prism(name, poly, z0, z1, mats, coll, bottom_mat=M_FLOOR, side_mat=M_WALL, top_mat=M_CEIL,
          wall_top=None, grid=None):
    """Vertical prism over a plan polygon (counter-clockwise). Side UV v = distance below
    wall_top (the rim) when given. grid = (step, z_hi): side walls in ~step quads up to z_hi."""
    if grid is not None:
        return _grid_prism(name, poly, z0, z1, mats, coll, bottom_mat, side_mat, top_mat, grid)
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
    wt = z1 if wall_top is None else wall_top
    for i in range(n):
        j = (i + 1) % n
        L = (Vector(poly[j]) - Vector(poly[i])).length
        faces.append((i, j, j + n, i + n))
        fm.append(side_mat)
        fuv.append(((s, wt - z0), (s + L, wt - z0), (s + L, wt - z1), (s, wt - z1)))
        s += L
    return make_mesh(name, verts, faces, fm, fuv, mats, coll)


def _grid_prism(name, poly, z0, z1, mats, coll, bottom_mat, side_mat, top_mat, grid):
    step, z_hi = grid
    pts = []
    for i in range(len(poly)):
        a, b = Vector(poly[i]), Vector(poly[(i + 1) % len(poly)])
        k = max(1, int(math.ceil((b - a).length / step)))
        pts += [a.lerp(b, j / k) for j in range(k)]
    zh = min(z_hi, z1)
    nz = max(1, int(math.ceil((zh - z0) / step)))
    zs = [z0 + (zh - z0) * k / nz for k in range(nz + 1)]
    if z1 > zs[-1] + 1e-6:
        zs.append(z1)
    n, L = len(pts), len(zs)
    verts = [Vector((p.x, p.y, z)) for z in zs for p in pts]
    faces, fm = [], []
    # the bottom as ~step triangles (interior grid points, constrained Delaunay)
    from mathutils.geometry import delaunay_2d_cdt
    xs_ = [p.x for p in pts]
    ys_ = [p.y for p in pts]

    def inside(x, y):
        c = False
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            if (a.y > y) != (b.y > y) and x < a.x + (y - a.y) * (b.x - a.x) / (b.y - a.y):
                c = not c
        return c
    inner = []
    gx = min(xs_) + step * 0.5
    while gx < max(xs_):
        gy = min(ys_) + step * 0.5
        while gy < max(ys_):
            if inside(gx, gy) and min((Vector((gx, gy)) - p.xy).length for p in pts) > step * 0.45:
                inner.append(Vector((gx, gy)))
            gy += step
        gx += step
    cdt = delaunay_2d_cdt([p.xy for p in pts] + inner, [(i, (i + 1) % n) for i in range(n)], [list(range(n))], 1, 1e-5)
    base = len(verts)
    lookup = {}
    for k, v in enumerate(cdt[0]):
        lookup[k] = len(verts)
        verts.append(Vector((v.x, v.y, z0)))
    for f in cdt[2]:
        faces.append(tuple(lookup[i] for i in f)[::-1])
        fm.append(bottom_mat)
    faces.append(tuple(range((L - 1) * n, L * n)))
    fm.append(top_mat)
    for l in range(L - 1):
        for i in range(n):
            j = (i + 1) % n
            faces.append((l * n + i, l * n + j, (l + 1) * n + j, (l + 1) * n + i))
            fm.append(side_mat)
    return make_mesh(name, verts, faces, fm, None, mats, coll)


def rounded_rect(x0, x1, y0, y1, r, seg=6):
    """Counter-clockwise plan polygon of a rectangle with rounded corners."""
    r = min(r, (x1 - x0) / 2 - 0.01, (y1 - y0) / 2 - 0.01)
    pts = []
    for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        for k in range(seg + 1):
            a = math.radians(a0 + 90.0 * k / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def column(p, z0, z1, n):
    """n+1 points from z0 to z1 at plan point p (x, y): a vertical edge split in n."""
    return [Vector((p[0], p[1], z0 + (z1 - z0) * k / n)) for k in range(n + 1)]


GRID = 12.0         # visible rock faces are built from ~12 m quads (the sculpted skin needs no slivers)


def triangulate(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 3],
                          quad_method="BEAUTY", ngon_method="BEAUTY")
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


# --------------------------------------------------------------------- the topology

class Mine:
    """Topology in Blender coordinates plus the face-plane segments."""

    def __init__(self, topo):
        self.topo = topo
        self.cx, self.cy = topo["cx"], topo["cy"]
        self.nodes = {k: Vector(mine_map.to_blender((n["x"], n["y"], n["z"]), self.cx, self.cy))
                      for k, n in topo["nodes"].items()}
        self.workings = {}
        for wid, w in topo["workings"].items():
            pts = [Vector(mine_map.to_blender(p, self.cx, self.cy)) for p in w["polyline"]]
            self.workings[wid] = dict(w, pts=pts)
        self.face_y = mine_map.to_blender((0, 0, 0), self.cx, self.cy)[1]   # FY
        self.back_y = self.face_y + B_BACK
        self.z120 = self.nodes["a"].z
        self.z240 = self.nodes["e"].z
        self.segments = self._face_segments()

    def _face_segments(self):
        segs = []
        for wid, w in self.workings.items():
            pts = w["pts"]
            names = [w["from"]] + [None] * (len(pts) - 2) + [w["to"]]
            for i in range(len(pts) - 1):
                a, b = pts[i], pts[i + 1]
                if abs(a.y - self.face_y) > 0.01 or abs(b.y - self.face_y) > 0.01:
                    continue
                s = dict(wid=wid, kind=w["kind"], idx=i, a=a.copy(), b=b.copy(), na=names[i], nb=names[i + 1])
                for end in ("a", "b"):
                    name = s["n" + end]
                    if name is None:
                        s["ext_" + end] = EXT_BEND
                        s["bend_" + end] = True
                    else:
                        s["ext_" + end] = 0.5 if self.topo["nodes"][name]["node_kind"] != "exit" else 0.0
                        s["bend_" + end] = False
                s["x0"], s["x1"] = min(a.x, b.x), max(a.x, b.x)
                segs.append(s)
        return segs

    @staticmethod
    def seg_h(s, x):
        a, b = s["a"], s["b"]
        if abs(b.x - a.x) < 1e-6:
            return a.z
        t = max(0.0, min(1.0, (x - a.x) / (b.x - a.x)))
        return a.z + (b.z - a.z) * t

    @staticmethod
    def seg_range(s):
        a, b = s["a"], s["b"]
        lo_ext = s["ext_a"] if a.x < b.x else s["ext_b"]
        hi_ext = s["ext_b"] if a.x < b.x else s["ext_a"]
        return s["x0"] - lo_ext, s["x1"] + hi_ext

    @staticmethod
    def seg_bend_beyond(s, x):
        """Distance beyond a hairpin bend end of the segment (0 inside)."""
        a, b = s["a"], s["b"]
        lo, hi = (a, b) if a.x < b.x else (b, a)
        lo_bend = s["bend_a"] if a.x < b.x else s["bend_b"]
        hi_bend = s["bend_b"] if a.x < b.x else s["bend_a"]
        if lo_bend and x < lo.x:
            return lo.x - x
        if hi_bend and x > hi.x:
            return x - hi.x
        return 0.0


# ------------------------------------------------------------------- the east slope

class EastSlope:
    """Terrain above ramp w-02's second leg (bend -> surface-b): a hillside that descends
    with the road, so the trench walls stay low (5 m on the camera side, 9 m beyond)."""

    def __init__(self, mine):
        w = mine.workings["w-02"]
        self.B = w["pts"][1].copy()
        self.S = w["pts"][2].copy()
        d = self.S.xy - self.B.xy
        self.L = d.length
        self.dir = d / self.L

    def road(self, x, y):
        p = Vector((x, y))
        t = max(0.0, min(self.L, (p - self.B.xy).dot(self.dir)))
        q = self.B.xy + self.dir * t
        h = lerp(self.B.z, self.S.z, t / self.L)
        return h, (p - q).length, (p - q).dot(VB), t

    def T(self, x, y):
        h, perp, side, t = self.road(x, y)
        wall = 5.0 if side > 0 else 9.0
        return min(0.0, h + wall + 0.55 * max(0.0, perp - HALF))


# ------------------------------------------------------------------ the gallery stack

def f_face(x):
    """Front edge (metres in front of the walking line) of the lowest floor at x."""
    f = F_FACE + (F_MID - F_FACE) * bump(x, -172.0, 172.0, 40.0)
    f += (F_DRILL - F_MID) * bump(x, -136.0, -64.0, 14.0)
    return f


def kind_of(mine, s):
    if s["kind"] == "drift":
        return "drift_low" if s["a"].z < mine.z120 - 1.0 else "drift_up"
    return "ramp"


def raw_groups(mine, x):
    """The face-plane galleries at x, bottom to top: [{z, segs}]."""
    groups = []
    for s in mine.segments:
        lo, hi = mine.seg_range(s)
        if not (lo - 1e-6 <= x <= hi + 1e-6):
            continue
        z = mine.seg_h(s, x)
        for g in groups:
            if abs(g["z"] - z) < 0.6:
                g["segs"].append(s)
                break
        else:
            groups.append(dict(z=z, segs=[s]))
    groups.sort(key=lambda g: g["z"])
    return groups


def _fmax(mine, s):
    return F_DRIFT if kind_of(mine, s) == "drift_up" else F_RAMP


def _raw_F(mine, s, x):
    """The deepest front the gallery below allows at x (or the face front for the lowest)."""
    gs = raw_groups(mine, x)
    i = next(k for k, g in enumerate(gs) if any(t is s for t in g["segs"]))
    if i == 0:
        return f_face(x)
    gap = gs[i]["z"] - gs[i - 1]["z"]
    return max(F_MIN, min(_fmax(mine, s), (gap - SLAB - 3.5) / RISE_S))


def _slope_limit(xs, v, fixed=()):
    v = list(v)
    for k, val in fixed:
        v[k] = min(v[k], val)
    for k in range(1, len(xs)):
        v[k] = min(v[k], v[k - 1] + F_SLOPE * (xs[k] - xs[k - 1]))
    for k in range(len(xs) - 2, -1, -1):
        v[k] = min(v[k], v[k + 1] + F_SLOPE * (xs[k + 1] - xs[k]))
    return v


def _seg_xs(s):
    lo, hi = s["x0"], s["x1"]        # the true range: the junction ends are merged floors
    return [lo + i * 1.0 for i in range(int((hi - lo) // 1.0) + 1)] + [hi]


def _sm_F(mine, s):
    tab = mine.__dict__.setdefault("_smtab", {}).get(id(s))
    if tab is None:
        xs = _seg_xs(s)
        tab = mine._smtab[id(s)] = (xs, _slope_limit(xs, [_raw_F(mine, s, x) for x in xs]))
    return tab


def _interp(xs, v, x):
    if x <= xs[0]:
        return v[0]
    if x >= xs[-1]:
        return v[-1]
    k = max(0, min(len(xs) - 2, int(x - xs[0])))
    while xs[k + 1] < x:
        k += 1
    t = (x - xs[k]) / max(1e-9, xs[k + 1] - xs[k])
    return v[k] + (v[k + 1] - v[k]) * t


def seg_F(mine, s, x):
    """Front edge of segment s's floor at x when another gallery lies below it: as deep as
    the lower gallery's visibility allows (its band must clear the sight line), then
    slope-limited along the gallery (F_SLOPE) so the section face never steps. At a junction
    every floor meeting there ends at the shallowest of their fronts (one continuous edge
    through the junction, no step where a ramp meets a drift), and the whole profile is
    opened (running min, then running mean over F_SMOOTH): kinks become curves and the
    result never exceeds the visibility limit."""
    key = id(s)
    tab = mine.__dict__.setdefault("_ftab", {}).get(key)
    if tab is None:
        xs, sm = _sm_F(mine, s)
        fixed = []
        for end in ("a", "b"):
            name = s["n" + end]
            if name is None or mine.topo["nodes"][name]["node_kind"] == "exit":
                continue
            xn = s[end].x
            others = [t for t in mine.segments if (t["na"] == name or t["nb"] == name)]
            vn = min(_interp(*_sm_F(mine, t), xn) for t in others)
            fixed.append((0 if abs(xn - xs[0]) < abs(xn - xs[-1]) else len(xs) - 1, vn))
        sm = _slope_limit(xs, sm, fixed)
        n, w = len(xs), int(F_SMOOTH)
        er = [min(sm[max(0, k - w):k + w + 1]) for k in range(n)]
        op = [sum(er[max(0, k - w):k + w + 1]) / len(er[max(0, k - w):k + w + 1]) for k in range(n)]
        op = _slope_limit(xs, op, fixed)
        tab = mine._ftab[key] = (xs, op)
    return _interp(*tab, x)


class Stack:
    """The galleries of the face plane at one x, bottom to top, with their floor front
    edges, clear heights and the line of the band face above each one."""

    def __init__(self, mine, slope, x):
        groups = raw_groups(mine, x)
        n = len(groups)
        FY = mine.face_y
        for i, g in enumerate(groups):
            kinds = {kind_of(mine, s) for s in g["segs"]}
            if i == 0:
                g["F"] = f_face(x)
                # a hairpin landing on the side the lines of sight run to (east) stays as shallow
                # as the upper leg arriving there, or its floor would hide the lower leg's bend
                beyond = [s for s in g["segs"] if (mine.seg_bend_beyond(s, x) > 0.0 or
                                                   (s["kind"] == "ramp" and len(g["segs"]) > 1))
                          and VB.x * (x - (s["x0"] + s["x1"]) / 2.0) > 0.0]
                if beyond and len(g["segs"]) > 1:
                    g["F"] = min(g["F"], min(seg_F(mine, s, x) for s in g["segs"]))
            else:
                # floors meeting at a junction are one floor: the union reaches the furthest
                g["F"] = max(seg_F(mine, s, x) for s in g["segs"])
            g["Feff"] = g["F"]      # every floor keeps its own front (a band may overhang a lower floor)
            hc = HC_LOW if "drift_low" in kinds else HC_RAMP
            g["open"] = False
            if i == n - 1:
                cover = slope.T(x, FY + B_BACK) - g["z"]
                if cover - hc < 14.0:
                    if cover > 30.0:
                        hc = cover - 14.0
                    else:
                        g["open"] = True
                        hc = cover + 80.0
            else:
                hc = min(hc, max(0.6, groups[i + 1]["z"] - g["z"] - SLAB))
            g["Hc"] = hc
        for i, g in enumerate(groups):
            above = groups[i + 1]["Feff"] if i + 1 < n else g["Feff"]
            g["yc"] = FY - above
        self.groups = groups

    def of(self, s):
        for i, g in enumerate(self.groups):
            if any(t is s for t in g["segs"]):
                return i, g
        raise KeyError(s["wid"])


def drip(seed, x, k):
    """How far the rock edge hangs down at ring k: a calm, slightly wavy line (0-1.2 m)
    with a sharper jag now and then (2-5.5 m); the light drips are painted on the wall."""
    wave = 0.6 + 0.35 * math.sin(0.23 * x + seed) + 0.25 * math.sin(0.071 * x + 2.0 * seed)
    h = hash01(seed, k)
    if h > 0.84:
        return 2.0 + 3.5 * hash01(seed + 7, k)
    return max(0.0, wave)


# ------------------------------------------------------------------ the cutters

def _xs(lo, hi, step):
    n = max(2, int(math.ceil((hi - lo) / step)))
    return [lo + (hi - lo) * i / n for i in range(n + 1)]


def slot_cutters(mine, slope, mats, coll):
    """One loft per face-plane segment: floor, back wall, ceiling with drips at the band face."""
    FY = mine.face_y
    out = []
    for si, s in enumerate(mine.segments):
        lo, hi = mine.seg_range(s)
        xs = _xs(lo, hi, RING)
        # finer rings over the rounded landing ends
        fine = []
        for x in xs:
            if mine.seg_bend_beyond(s, x) > EXT_LAND - 4.0:
                continue
            fine.append(x)
        for x0_, sg in ((lo, -1.0), (hi, 1.0)):
            e0 = mine.seg_bend_beyond(s, x0_)
            if e0 > 0.0:
                fine += [x0_ - sg * (e0 - (EXT_LAND - 4.0)) * (1.0 - k / 16.0) for k in range(17)]
        xs = sorted(set(round(x, 4) for x in fine))
        rings, vb = [], []
        for k, x in enumerate(xs):
            st = Stack(mine, slope, x)
            i, g = st.of(s)
            z = mine.seg_h(s, x)
            yf = FY - g["Feff"] - 2.0
            yb = FY + B_BACK
            e = mine.seg_bend_beyond(s, x)
            hc = g["Hc"]
            if e > 0.0:
                # the landing ends in a half ellipse (back wall) that turns into the rock face
                # through a fillet of radius FLARE (no sharp vertical edge); the ceiling arcs
                # down to the floor over the whole landing
                face = yf + 2.0
                D = max(1e-3, yb - face)
                e_st = EXT_LAND * math.sqrt(max(0.0, 1.0 - (FLARE / D) ** 2)) if D > FLARE else 0.0
                ell = face + D * math.sqrt(max(0.0, 1.0 - (e / EXT_LAND) ** 2))
                q = max(0.0, e - e_st)
                flare = face + FLARE - math.sqrt(max(0.0, FLARE * FLARE - (FLARE - q) ** 2)) if q < FLARE else face - 1.0
                yb = max(yf + 1.0, min(yb, max(ell, flare)))
                if not g["open"]:
                    e_end = e_st + FLARE + 0.3
                    hc = max(0.8, hc * math.sqrt(max(0.0, 1.0 - (e / e_end) ** 2)))
            zc = z + hc
            # drips fade out where the ceiling gets low (the wedges where ramps part at a junction)
            d = 0.0 if g["open"] or hc < 6.0 else min(drip(si + 1, x, k), hc * 0.35) * smooth((hc - 6.0) / 10.0)
            r = min(4.0, hc * 0.25, (yb - yf) * 0.3)
            y3 = yb - r
            y4 = max(yf + 0.4, min(g["yc"] + 3.0, y3 - 0.3))
            y5 = max(yf + 0.2, min(g["yc"], y4 - 0.2))
            ring = [Vector((x, yf, z)), Vector((x, yb, z)), Vector((x, yb, zc - r)), Vector((x, y3, zc)),
                    Vector((x, y4, zc)), Vector((x, y5, zc - d)), Vector((x, yf, zc - d))]
            rings.append(ring)
            # the wall shows up to where the band's edge cuts the line of sight
            vb.append(zc if g["open"] else min(zc, zc - d - RISE_S * max(0.0, yb - y5)))

        def uvf(i, j, k, p, vb=vb):
            if j == 0:
                return (p.x, p.y)
            if j in (1, 2):
                return (p.x, vb[i] - p.z)
            return (p.x, 0.0)
        ob = loft(f"CUT_slot_{s['wid']}_{s['idx']}", rings,
                  [M_FLOOR, M_WALL, M_WALL, M_CEIL, M_CEIL, M_CEIL, M_CUT], uvf,
                  cap_mats=(M_WALL, M_WALL), mats=mats, coll=coll)
        triangulate(ob)
        out.append(ob)
    return out


def air_cutters(mine, slope, mats, coll):
    """In front of every gallery that has another below it: south of its floor edge, from
    the lower floor up to its own ceiling (to the sky for the top-most one), is air."""
    FY = mine.face_y
    out = []
    for s in mine.segments:
        lo, hi = mine.seg_range(s)
        xs = _xs(lo, hi, 6.0)
        runs, cur = [], []
        deep_runs = set()
        for x in xs:
            st = Stack(mine, slope, x)
            i, g = st.of(s)
            deep = i == 0 and g["F"] < f_face(x) - 0.5      # a shallow landing: the face below steps back
            if i == 0 and not deep:
                if len(cur) > 1:
                    runs.append(cur)
                cur = []
                continue
            top = Z_SKY if i == len(st.groups) - 1 else g["z"] + g["Hc"] + 0.3
            zb = Z_BOT if deep else st.groups[i - 1]["z"]
            if cur and abs(zb - cur[-1][2]) > 4.0:
                # another gallery below from here on: close this run, start the next at the same x
                if len(cur) > 1:
                    runs.append(cur + [(x, cur[-1][1], cur[-1][2], cur[-1][3])])
                cur = []
            cur.append((x, g["F"], zb, top))
        if len(cur) > 1:
            runs.append(cur)
        # overlap the neighbouring x a little at both ends (no rock slab left between samples);
        # a recess under a shallow landing reaches on 14 m in the direction the sight lines run
        ext = []
        for r in runs:
            deep = r[0][2] <= Z_BOT + 1.0
            e0 = 14.0 if deep and VB.x < 0 else 3.0
            e1 = 14.0 if deep and VB.x > 0 else 3.0
            # the overlap rises away from the run's end faster than any neighbouring front can
            # (F_SLOPE): the neighbour's front wins there, so no thin recess opens in the face
            # below a junction
            sh0 = 0.0 if deep else 0.6 + F_SLOPE * e0
            sh1 = 0.0 if deep else 0.6 + F_SLOPE * e1
            ext.append([(r[0][0] - e0, r[0][1] + sh0) + r[0][2:]] + r + [(r[-1][0] + e1, r[-1][1] + sh1) + r[-1][2:]])
        runs = ext
        for ri, run in enumerate(runs):
            nf = max(1, int(math.ceil(max(min(zt, 60.0) - max(zb, -700.0) for x, F, zb, zt in run) / GRID)))
            rings = [[Vector((x, FY - 600.0, zb))] + column((x, FY - F), zb, zt, nf) + [Vector((x, FY - 600.0, zt))]
                     for x, F, zb, zt in run]
            out.append(loft(f"CUT_air_{s['wid']}_{s['idx']}_{ri}", rings, [M_FLOOR] + [M_CUT] * nf + [M_CUT, M_CUT],
                            lambda i, j, k, p: (p.x, p.y), cap_mats=(M_CUT, M_CUT), mats=mats, coll=coll))
    return out


def _line_frame(a, b):
    t = (b - a).xy.normalized()
    return t, Vector((t.y, -t.x))      # direction, right-hand normal


def bay_polygon(mine, south=-110.0, fillet=26.0):
    """The bay above level -120: west side 12 m on the island side of a-d (the slot's wall
    face), east side 8 m beyond d-c (the trench's back wall), apex rounded."""
    a, d, c = mine.nodes["a"].xy, mine.nodes["d"].xy, mine.nodes["c"].xy
    t1, n1 = _line_frame(mine.nodes["a"], mine.nodes["d"])      # n1: south-east (island)
    t2, n2 = _line_frame(mine.nodes["d"], mine.nodes["c"])      # n2: south-west (island)
    p1 = a + n1 * CC_FRONT
    p2 = c - n2 * B_BACK
    # intersection p1 + t1 u = p2 + (-t2) v
    m = (t1.x * (t2.y) - t1.y * (t2.x))
    r = p2 - p1
    u = (r.x * t2.y - r.y * t2.x) / m
    apex = p1 + t1 * u
    w_south = p1 + t1 * ((south - p1.y) / t1.y)
    e_south = p2 + t2 * ((south - p2.y) / t2.y)
    # fillet at the apex
    da, db = (w_south - apex).normalized(), (e_south - apex).normalized()
    half = math.acos(max(-1.0, min(1.0, da.dot(db)))) / 2.0
    dist = fillet / math.tan(half)
    pa, pb = apex + da * dist, apex + db * dist
    bis = (da + db).normalized()
    centre = apex + bis * (fillet / math.sin(half))
    a0 = math.atan2(pb.y - centre.y, pb.x - centre.x)
    a1 = math.atan2(pa.y - centre.y, pa.x - centre.x)
    while a1 < a0:
        a1 += 2 * math.pi
    arc = []
    for k in range(5):                       # ~12 m arc steps (the sculpted skin needs no narrow columns)
        ang = a0 + (a1 - a0) * k / 4
        arc.append((centre.x + fillet * math.cos(ang), centre.y + fillet * math.sin(ang)))
    poly = [tuple(w_south), tuple(e_south)] + arc     # counter-clockwise: south-west, south-east, arc east->west
    return poly


_bay_cache = {}


def inside_bay(mine, x, y):
    """Is the plan point inside the bay (the rock above level -120 is cut away there)?"""
    poly = _bay_cache.get(id(mine))
    if poly is None:
        poly = _bay_cache[id(mine)] = bay_polygon(mine)
    c = False
    n = len(poly)
    for i in range(n):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        if (ay > y) != (by > y):
            xi = ax + (y - ay) * (bx - ax) / (by - ay)
            if x < xi:
                c = not c
    return c


def bay_cutter(mine, mats, coll):
    poly = bay_polygon(mine)
    return prism("CUT_bay", poly, mine.z120 + ISL, Z_SKY, mats, coll, bottom_mat=M_TOP, side_mat=M_CUT,
                 top_mat=M_CUT, grid=(GRID, 20.0))


def line_loft(name, pts, offsets, zf_fn, top_fn, mats, coll, band_mats, wall_tops, step=2.0, ext=(0.0, 0.0),
              drips=None):
    """A loft along a straight plan line from pts[0] to pts[1]: ring = floor across the
    offsets (right-hand normal), walls up to top_fn. offsets = (right, left) signed
    distances; drips = (offset of the drip line, seed) puts drips on the ceiling edge."""
    a, b = pts
    t, n = _line_frame(a, b)
    L = (b.xy - a.xy).length
    s_vals = _xs(-ext[0], L + ext[1], step)
    o_r, o_l = offsets
    rings = []
    dd_k = {}
    for k, s in enumerate(s_vals):
        f = max(0.0, min(1.0, s / L))
        p = a.xy + t * s
        zf = zf_fn(f)
        zt = top_fn(f)
        if drips is None:
            ring = [Vector((*(p + n * o_r), zf)), Vector((*(p + n * o_l), zf)),
                    Vector((*(p + n * o_l), zt)), Vector((*(p + n * o_r), zt))]
        else:
            o_d, seed = drips
            dd = min(drip(seed, s, k), (zt - zf) * 0.35)
            dd_k[k] = dd
            r = 4.0
            ring = [Vector((*(p + n * o_r), zf)), Vector((*(p + n * o_l), zf)),
                    Vector((*(p + n * o_l), zt - r)), Vector((*(p + n * (o_l + r)), zt)),
                    Vector((*(p + n * (o_d - 3.0)), zt)), Vector((*(p + n * o_d), zt - dd)),
                    Vector((*(p + n * o_r), zt - dd))]
        rings.append(ring)
    m = len(rings[0])

    def uvf(i, j, k, pt):
        if j == 0:
            return (pt.x, pt.y)
        wt = wall_tops.get(j)
        if wt is not None:
            top = wt(max(0.0, min(1.0, s_vals[i] / L)))
            if drips is not None:
                # the visible top of the back wall under the drip edge (sight rise across the slot)
                rise = TAN_EL / max(0.2, VB.dot(n))
                top = top - dd_k.get(i, 0.0) - rise * max(0.0, drips[0] - o_l)
            return (s_vals[i], top - pt.z)
        return (s_vals[i], 0.0)
    ob = loft(name, rings, band_mats[:m], uvf, cap_mats=(M_WALL, M_WALL), mats=mats, coll=coll)
    triangulate(ob)
    return ob


def crosscut_cutters(mine, mats, coll):
    z = mine.z120
    out = []
    a, d, c = mine.nodes["a"], mine.nodes["d"], mine.nodes["c"]
    # a-d: a slot in the bay's north-west wall, opened toward the island (south-east)
    out.append(line_loft("CUT_cc_w-05", (a, d), (CC_FRONT + CC_OPEN, -B_BACK), lambda f: z,
                         lambda f: z + HC_RAMP, mats, coll,
                         [M_FLOOR, M_WALL, M_WALL, M_CEIL, M_CEIL, M_CEIL, M_WALL],
                         {1: lambda f: z + HC_RAMP, 2: lambda f: z + HC_RAMP}, ext=(6.0, 0.0),
                         drips=(CC_FRONT, 51)))
    # d-c: an open trench at the foot of the bay's north-east wall (its back wall 0.5 m
    # behind the bay wall, 20 m of wall band, then the cut face)
    out.append(line_loft("CUT_cc_w-06", (d, c), (HALF + 0.5, -(B_BACK + 0.5)), lambda f: z,
                         lambda f: z + 20.0, mats, coll, [M_FLOOR, M_WALL, M_CEIL, M_WALL],
                         {1: lambda f: z + 20.0, 3: lambda f: z + ISL}, ext=(0.0, 3.0)))
    out.append(loop_corner(mine, mats, coll))
    return out


def zone_cutters(mine, wid, level_z, mats, coll):
    """The zone drift trench and its face chamber (west, away from the camera)."""
    w = mine.workings[wid]
    root, face = w["pts"][0], w["pts"][-1]
    out = []
    start = Vector((root.x, mine.face_y - 6.0, level_z))
    end = Vector((face.x, face.y - 11.0, level_z))
    out.append(line_loft(f"CUT_zone_{wid}", (start, end), (-HALF - 0.5, HALF), lambda f: level_z,
                         lambda f: level_z + 60.0, mats, coll, [M_FLOOR, M_WALL, M_CEIL, M_WALL],
                         {1: lambda f: zone_top(level_z, -HALF), 3: lambda f: level_z + ZONE_RIM_E}))
    ch = rounded_rect(face.x - 46.0, face.x + 4.0, face.y - 8.0, face.y + CHAMBER_N, 13.4, seg=10)
    out.append(prism(f"CUT_chamber_{wid}", ch, level_z, level_z + 60.0, mats, coll, bottom_mat=M_FLOOR,
                     side_mat=M_WALL, top_mat=M_CEIL, wall_top=zone_top(level_z, -46.0)))
    # fillets: the drift mouth (the trench walls meet the drift floor's front edge) and the
    # corners where the trench's west wall meets the chamber's north and south walls
    seg = next(s for s in mine.segments if s["kind"] == "drift" and abs(s["a"].z - level_z) < 0.5
               and abs(s["b"].x - root.x) < 0.5)
    y_lip = mine.face_y - Stack(mine, EastSlope(mine), root.x).of(seg)[1]["Feff"] - 2.0
    x_e, x_w = root.x + HALF + 0.5, root.x - HALF
    fil = [((x_e, y_lip), (1.0, 0.0), (0.0, -1.0), R_MOUTH, level_z + ZONE_RIM_E),
           ((x_w, y_lip), (-1.0, 0.0), (0.0, -1.0), R_MOUTH, level_z + ZONE_RIM_W),
           ((x_w, face.y + CHAMBER_N), (-1.0, 0.0), (0.0, 1.0), R_MOUTH, zone_top(level_z, -HALF)),
           ((x_w, face.y - 8.0), (-1.0, 0.0), (0.0, -1.0), 5.0, level_z + 3.0)]
    for k, (tip, ua, ub, R, wt) in enumerate(fil):
        poly = fillet_poly(Vector(tip), ua, ub, R, back=3.0, n=8)
        out.append(prism(f"CUT_zfil_{wid}_{k}", poly, level_z, level_z + 60.0, mats, coll, bottom_mat=M_FLOOR,
                         side_mat=M_WALL, top_mat=M_CEIL, wall_top=wt))
    return out


def ramp_trench_cutter(mine, slope, mats, coll):
    """w-02's second leg: an open trench climbing through the hillside to portal B."""
    w = mine.workings["w-02"]
    B, S = w["pts"][1], w["pts"][2]
    return line_loft("CUT_trench_w-02", (B, S), (HALF + 0.5, -HALF - 0.5), lambda f: lerp(B.z, S.z, f),
                     lambda f: lerp(B.z, S.z, f) + 60.0, mats, coll, [M_FLOOR, M_WALL, M_CEIL, M_WALL],
                     {1: lambda f: lerp(B.z, S.z, f) + 9.0, 3: lambda f: lerp(B.z, S.z, f) + 5.0},
                     ext=(10.0, 6.0))


def pocket_cutters(mine, mats, coll):
    """The truck pocket in the island behind drift w-04."""
    z = mine.z120
    y0 = mine.back_y - 1.0
    poly = rounded_rect(64.0, 110.0, y0, y0 + 16.0, 6.0)
    return [prism("CUT_pocket_truck", poly, z, z + 60.0, mats, coll, bottom_mat=M_FLOOR, side_mat=M_WALL,
                  top_mat=M_CEIL, wall_top=z + ISL)]


# ------------------------------------------------------------------ the rock bodies

def massif_block(mine, slope, mats, coll):
    """The rock body: south face at the lowest floor's front edge, plateau on top."""
    FY = mine.face_y
    ys_top = [-45.0, -38.0, -30.0, -20.0, -10.0] + [float(v) for v in range(0, 420, 12)] + \
        [440.0, 480.0, 520.0, 580.0, 640.0, 700.0, 780.0, 840.0, TOP_Y]
    nv = int(math.ceil((0.0 - Z_BOT) / GRID))
    rings = []
    for x in _xs(X_MIN, X_MAX, GRID):
        yf = FY - f_face(x)
        ring = [Vector((x, yf, Z_BOT)), Vector((x, TOP_Y, Z_BOT))]
        tops = [Vector((x, yf, slope.T(x, yf)))] + [Vector((x, y, slope.T(x, y))) for y in ys_top if y > yf + 1.0]
        ring += tops[::-1]
        # the south face from the top edge down, in ~12 m steps
        ring += column((x, yf), slope.T(x, yf), Z_BOT, nv)[1:-1]
        rings.append(ring)
    m = len(rings[0])
    assert all(len(r) == m for r in rings)
    nt = m - 2 - (nv - 1)
    bands = [M_CUT, M_CUT] + [M_TOP] * (nt - 1) + [M_CUT] * nv
    ob = loft("MASSIF", rings, bands, lambda i, j, k, p: (p.x, p.y), cap_mats=(M_CUT, M_CUT), mats=mats, coll=coll)
    triangulate(ob)
    return ob


def promontory(mine, mats, coll):
    """Rock under zone drift w-07: from its bench down to an underside that rises toward
    the viewer as the lines of sight from the level -240 walking lines do."""
    FY = mine.face_y
    z240 = mine.z240
    y0, y1 = mine.nodes["face-a"].y - 20.0, FY - F_DRIFT + 5.0

    def under(y):
        return z240 + max(HC_LOW, 22.0 + RISE_S * 1.04 * (FY - y))
    return _body("PROMONTORY", y0, y1, mine.z120, under, mats, coll)


def peninsula(mine, mats, coll):
    FY = mine.face_y
    y0, y1 = mine.nodes["face-b"].y - 20.0, FY - F_MID + 5.0
    return _body("PENINSULA", y0, y1, mine.z240, lambda y: Z_BOT, mats, coll)


ZONE_X0, ZONE_X1 = -72.0, 24.0     # plan extent of the zone benches (east of the drift: the camera side)
ZONE_RIM_E = 5.5                    # the bench east of the drift: low, the walking line shows over it
ZONE_RIM_W = 16.0                   # ... rising to the west (the chamber's far wall)


def _body(name, y0, y1, level, under, mats, coll, r=16.0):
    rings = []
    ys = _xs(y0, y1, 6.0)
    nb = int(math.ceil((ZONE_X1 - ZONE_X0) / GRID))
    ne = int(math.ceil(max(level + ZONE_RIM_W - under(y) for y in ys) / GRID))
    nt_ = int(math.ceil((HALF + 2.0 - ZONE_X0) / GRID))
    xm = HALF + 2.0
    for k, y in enumerate(ys):
        dy = y - y0
        inset = r - math.sqrt(max(0.0, r * r - (r - dy) ** 2)) if dy < r else 0.0
        zb = under(y)
        if zb > Z_BOT + 1.0:
            zb -= drip(5, y, k)
        x0, x1 = ZONE_X0 + inset, ZONE_X1 - inset
        # low toward the south end too (the camera side of the face), so the face end shows
        rim_w = ZONE_RIM_E + 0.4 + (ZONE_RIM_W - ZONE_RIM_E - 0.4) * smooth((dy - 8.0) / 22.0)
        low = 2.5 + (1.0 - 2.5 / ZONE_RIM_E) * 0.0
        f = smooth((dy - 2.0) / 12.0)          # the last metres before the south end: a low lip

        def h(v):
            return level + low + (v - low) * f
        bottom = [Vector((x0 + (x1 - x0) * k2 / nb, y, zb)) for k2 in range(nb + 1)]
        east = column((x1, y), zb, h(ZONE_RIM_E), ne)[1:]
        xa = min(xm, x1 - 0.5)
        tops = [Vector((xa + (x0 - xa) * k2 / nt_, y, h(ZONE_RIM_E + 0.4 + (rim_w - ZONE_RIM_E - 0.4) * k2 / nt_)))
                for k2 in range(nt_ + 1)]
        rings.append(bottom + east + tops)
    bands = [M_CUT] * nb + [M_CUT] * ne + [M_TOP] * (nt_ + 1) + [M_CUT]
    ob = loft(name, rings, bands, lambda i, j, k, p: (p.x, p.y),
              cap_mats=(M_CUT, M_CUT), mats=mats, coll=coll)
    triangulate(ob)
    return ob


def zone_top(level, x):
    """Height of the zone bench at plan x (the drift centreline at x = 0)."""
    xm = HALF + 2.0
    if x >= xm:
        return level + ZONE_RIM_E
    return level + ZONE_RIM_E + 0.4 + (ZONE_RIM_W - ZONE_RIM_E - 0.4) * (xm - x) / (xm - ZONE_X0)


def fillet_poly(tip, ua, ub, R, back=4.0, n=10):
    """Plan polygon (counter-clockwise) that rounds the rock corner at `tip` whose two edges
    leave along the unit directions ua and ub (into the rock): the region between both
    edges and the arc of radius R tangent to them, plus `back` metres on the open side so
    the cutter overlaps the void it widens."""
    ua, ub = Vector(ua).normalized(), Vector(ub).normalized()
    tip = Vector(tip)
    half = math.acos(max(-1.0, min(1.0, ua.dot(ub)))) / 2.0
    dist = R / math.tan(half)
    pa, pb = tip + ua * dist, tip + ub * dist
    bis = (ua + ub).normalized()
    cen = tip + bis * (R / math.sin(half))

    def norm(v):
        while v < -math.pi:
            v += 2 * math.pi
        while v > math.pi:
            v -= 2 * math.pi
        return v
    a0 = math.atan2(pa.y - cen.y, pa.x - cen.x)
    a1 = math.atan2(pb.y - cen.y, pb.x - cen.x)
    dt = math.atan2(tip.y - cen.y, tip.x - cen.x)
    span = norm(a1 - a0)
    if not (min(0.0, span) <= norm(dt - a0) <= max(0.0, span)):
        span = span - 2 * math.pi if span > 0 else span + 2 * math.pi
    arc = [(cen.x + R * math.cos(a0 + span * i / n), cen.y + R * math.sin(a0 + span * i / n)) for i in range(n + 1)]
    poly = [tuple(tip - bis * back)] + arc
    area = sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
               for i in range(len(poly)))
    return poly[::-1] if area < 0 else poly


def column_prism(name, poly, zf, zt, mats, coll, wall_top=None, top_mat=M_CEIL):
    """A prism over a counter-clockwise plan polygon whose floor and top heights may vary
    per vertex (zf(x, y), zt(x, y)): fan-triangulated floor and top, quads up the sides."""
    n = len(poly)
    verts = [Vector((x, y, zf(x, y))) for x, y in poly] + [Vector((x, y, zt(x, y))) for x, y in poly]
    cx_ = sum(p[0] for p in poly) / n
    cy_ = sum(p[1] for p in poly) / n
    verts += [Vector((cx_, cy_, zf(cx_, cy_))), Vector((cx_, cy_, zt(cx_, cy_)))]
    cb, ct = 2 * n, 2 * n + 1
    faces, fm, fuv = [], [], []
    for i in range(n):
        j = (i + 1) % n
        faces.append((cb, j, i))
        fm.append(M_FLOOR)
        fuv.append(((cx_, cy_), poly[j], poly[i]))
        faces.append((ct, n + i, n + j))
        fm.append(top_mat)
        fuv.append(((cx_, cy_), poly[i], poly[j]))
    s_ = 0.0
    for i in range(n):
        j = (i + 1) % n
        L = (Vector(poly[j]) - Vector(poly[i])).length
        faces.append((i, j, j + n, i + n))
        fm.append(M_WALL)
        if wall_top is not None:
            ti, tj = wall_top(*poly[i]), wall_top(*poly[j])
        else:
            ti, tj = verts[i + n].z, verts[j + n].z
        fuv.append(((s_, ti - verts[i].z), (s_ + L, tj - verts[j].z), (s_ + L, tj - verts[j + n].z),
                    (s_, ti - verts[i + n].z)))
        s_ += L
    return make_mesh(name, verts, faces, fm, fuv, mats, coll)


def island_tips(mine, mats, coll, R=R_TIP):
    """Round the three corners of the island inside the crosscut loop."""
    FY = mine.face_y
    a, d, c = mine.nodes["a"].xy, mine.nodes["d"].xy, mine.nodes["c"].xy
    t1, n1 = _line_frame(mine.nodes["a"], mine.nodes["d"])
    t2, n2 = _line_frame(mine.nodes["d"], mine.nodes["c"])
    L1 = (a + n1 * (CC_FRONT + CC_OPEN), t1)              # island edge along a-d
    L2 = (d + n2 * (HALF + 0.5), t2)                      # island edge along d-c
    L3 = (Vector((0.0, FY + B_BACK)), Vector((1.0, 0.0)))  # island edge along the drifts

    def meet(P, Q):
        (p, u), (q, v) = P, Q
        m = u.x * v.y - u.y * v.x
        r = q - p
        return p + u * ((r.x * v.y - r.y * v.x) / m)
    centroid = (a + d + c) / 3.0
    out = []
    for k, (P, Q) in enumerate(((L1, L3), (L1, L2), (L2, L3))):
        tip = meet(P, Q)
        ua = P[1] if P[1].dot(centroid - tip) > 0 else -P[1]
        ub = Q[1] if Q[1].dot(centroid - tip) > 0 else -Q[1]
        poly = fillet_poly(tip, ua, ub, R, n=12)
        out.append(prism(f"CUT_tip_{k}", poly, mine.z120, mine.z120 + ISL + 1.0, mats, coll, bottom_mat=M_FLOOR,
                         side_mat=M_WALL, top_mat=M_CEIL, wall_top=mine.z120 + ISL))
    return out


def loop_corner(mine, mats, coll):
    """The outer corner of the crosscut loop at d: both crosscuts end at d and a sector of
    radius B_BACK..B_BACK + 0.5 around d joins their back walls (the round offset of the
    polyline: d keeps its full floor around it)."""
    d = mine.nodes["d"]
    z = mine.z120
    t1, n1 = _line_frame(mine.nodes["a"], d)
    t2, n2 = _line_frame(d, mine.nodes["c"])
    a0 = math.atan2(-n1.y, -n1.x)
    a1 = math.atan2(-n2.y, -n2.x)
    while a1 > a0:
        a1 -= 2 * math.pi
    pts = [tuple(d.xy + (n1 + n2).normalized() * 4.0)]
    k = 12
    for i in range(k + 1):
        u = i / k
        ang = a0 + (a1 - a0) * u
        r = B_BACK + 0.5 * smooth(u)
        pts.append((d.x + r * math.cos(ang), d.y + r * math.sin(ang)))
    area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts)))
    if area < 0:
        pts = pts[::-1]
    return prism("CUT_loop_corner", pts, z, z + 20.0, mats, coll, bottom_mat=M_FLOOR, side_mat=M_WALL,
                 top_mat=M_CEIL, wall_top=z + 20.0)


def ramp_bend_nose(mine, slope, mats, coll, R=16.0):
    """w-02 turns from the face plane (leg 1) into its trench to portal B (leg 2): round the
    rock nose between leg 1's back wall and the trench's west wall. The floor of the cut
    blends from leg 1's floor at its wall to the trench floor at the other."""
    w = mine.workings["w-02"]
    B, S = w["pts"][1], w["pts"][2]
    seg = next(s for s in mine.segments if s["wid"] == "w-02" and s["idx"] == 0)
    t2 = (S.xy - B.xy).normalized()
    n2 = Vector((t2.y, -t2.x))                      # right-hand normal: east of the trench
    Ltr = (S.xy - B.xy).length
    yb = mine.back_y
    west = B.xy - n2 * (HALF + 0.5)                 # a point on the trench's west wall
    tip = west + t2 * ((yb - west.y) / t2.y)        # the west wall meets leg 1's back wall
    poly = fillet_poly(tip, Vector((-1.0, 0.0)), t2, R, back=3.0, n=12)

    def z1(x, y):
        return mine.seg_h(seg, x)

    def z2(x, y):
        tt = max(0.0, min(1.0, (Vector((x, y)) - B.xy).dot(t2) / Ltr))
        return lerp(B.z, S.z, tt)

    def zf(x, y):
        p = Vector((x, y))
        d1 = max(0.0, p.y - yb)                     # beyond leg 1's back wall
        d2 = max(0.0, (p - west).dot(-n2))          # beyond the trench's west wall
        if d1 + d2 < 1e-6:
            return min(z1(x, y), z2(x, y))
        return lerp(z1(x, y), z2(x, y), d1 / (d1 + d2)) - 0.02

    def zt(x, y):
        try:
            g = Stack(mine, slope, x).of(seg)[1]
            top = 60.0 if g["open"] else g["Hc"]
        except KeyError:
            top = 60.0
        return zf(x, y) + top
    return column_prism("CUT_bend_w-02", poly, zf, zt, mats, coll, wall_top=lambda x, y: zf(x, y) + 9.0)


def mark_kinds(ob):
    """Face attribute `mk` (material kind) for the outline pass: the material slot + 1."""
    me = ob.data
    at = me.attributes.get("mk") or me.attributes.new("mk", "FLOAT", "FACE")
    vals = [float(p.material_index + 1) for p in me.polygons]
    at.data.foreach_set("value", vals)


# ------------------------------------------------------------------ sculpted skins (render only)

def _skin(ob, kinds, edge_len, move, seed, max_iter=8, want=None):
    """Refine the faces of the given material slots to ~edge_len triangles, then move every
    vertex whose faces are all of those slots by move(rnd, co, normal). Vertices shared
    with other slots (floor edges, wall feet) never move, so floors stay exact."""
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
    for _ in range(2):
        fs = [f for f in bm.faces if f.material_index in kinds]
        es = [e for e in bm.edges if len(e.link_faces) == 2 and all(f.material_index in kinds for f in e.link_faces)
              and e.link_faces[0].normal.dot(e.link_faces[1].normal) > 0.9995]
        bmesh.ops.beautify_fill(bm, faces=fs, edges=es, method="ANGLE")
    bm.normal_update()
    moved = 0
    moves = []
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
        lmin = min(e.calc_length() for e in v.link_edges)
        moves.append((v, move(rnd, v.co, n) * min(1.0, lmin / (0.6 * edge_len))))
    for v, d in moves:
        v.co += d
        moved += 1
    bm.to_mesh(me)
    bm.free()
    me.update()
    return moved


def sculpt_rock(ob, seed=0, want=None, cell=50.0):
    """The rock body as sculpted masses with big facets: cut faces and tops are refined to
    ~12 m triangles and every inner vertex is pushed into the rock by a piecewise-planar
    field - each Voronoi cell (~34 m) is one tilted plane at its own depth (0.6-7 m on the
    cut faces, 0.3-2.6 m on the tops) - so the planes break into large lit and shaded
    facets with creases between them, independent of the triangulation (no mosaic). A slow
    150 m swell adds the large masses. Nothing moves toward the camera side of a face."""
    from mathutils import noise

    def cell_of(co):
        _, pts = noise.voronoi(co * (1.0 / cell) + Vector((seed * 7.3, 1.1, 2.9)), distance_metric="DISTANCE")
        c = pts[0]
        h = (int(math.floor(c.x * 1000.0)) * 73856093) ^ (int(math.floor(c.y * 1000.0)) * 19349663) ^             (int(math.floor(c.z * 1000.0)) * 83492791)
        return (c - Vector((seed * 7.3, 1.1, 2.9))) * cell, random.Random(h & 0xFFFFFFFF)

    def move(rnd, co, n):
        c, r = cell_of(co)
        top = n.z > 0.6
        g = Vector((r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(-1, 1)))
        g -= n * g.dot(n)
        slope = 0.04 if top else 0.085
        d0 = r.uniform(0.3, 2.6) if top else r.uniform(0.6, 7.0)
        d = d0 + slope * g.dot(co - c)
        d += (0.5 if top else 1.2) * max(0.0, noise.noise(co * (1.0 / 220.0) + Vector((0.0, seed, 3.0))) + 0.2)
        return -n * max(0.3, d)
    return _skin(ob, (M_CUT, M_TOP), 12.0, move, seed, want=want)


def wall_skin(ob, seed=0):
    """Tunnel walls in small flat facets: refined to ~6 m, inner vertices pushed into the
    rock by 0.3-1.8 m (never toward the walking lines)."""
    return _skin(ob, (M_WALL,), 6.0, lambda rnd, co, n: -n * rnd.uniform(0.3, 1.8), seed)


def facet_attributes(ob, seed=0):
    """Face attributes for the shaders and the outline pass: `fr` (colour) a random value
    per facet, equal for coplanar pieces; `mk` (float) material slot + 1."""
    me = ob.data
    for name in ("fr", "mk"):
        if name in me.attributes:
            me.attributes.remove(me.attributes[name])
    fr = me.attributes.new("fr", "FLOAT_COLOR", "FACE")
    mk = me.attributes.new("mk", "FLOAT", "FACE")
    cols, kinds = [], []
    for p in me.polygons:
        kinds.append(float(p.material_index + 1))
        n = p.normal
        key = (round(n.x * 40.0), round(n.y * 40.0), round(n.z * 40.0), seed)
        r = random.Random(hash(key) & 0xFFFFFFFF)
        cols += [r.random(), r.random(), r.random(), 1.0]
    fr.data.foreach_set("color", cols)
    mk.data.foreach_set("value", kinds)
    me.polygons.foreach_set("use_smooth", [False] * len(me.polygons))
    me.update()
