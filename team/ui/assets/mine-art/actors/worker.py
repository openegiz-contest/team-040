"""
worker.py - the miner (worker) actor of the mine art, with walk and idle clips.

Builds team/ui/public/models/mine-art/actors/worker.glb (SPEC section 6):
    worker (root empty, origin on the ground between the feet, facing +X, extras)
      worker_rig        armature, 13 bones (root, hips, spine, head, thigh/shin/foot,
                        upperarm/forearm per side); the root never moves
        worker_body     one skinned mesh, one unlit material, one 512 px baked texture
    clips: walk (1.0 s loop, root fixed, the feet cover extras.strideM metres per
    cycle), idle (4.0 s breath loop, barely visible) and three work loops on the spot
    (work_drill 2.0 s, work_scale 2.4 s, work_inspect 3.0 s; root fixed).
Props of the work loops (a jackleg rock drill, a scaling bar, a geologist's hammer) are
part of the one skinned mesh, each on its own bone (prop_drill, prop_bar, prop_hammer,
children of root): the bind pose holds them small inside the pelvis, and every clip keys
their scale, PROP_REST_S^-1 in the clip that uses the prop, PROP_HIDDEN_S (a speck inside
the body) in all others, so a prop shows only while its clip plays (a cross-fade grows or
shrinks it).
A stylised figure 5 m tall in scene metres (SPEC section 3): orange coveralls with
reflective bands, a yellow-white helmet with a cap lamp, dark boots and gloves,
a belt with the lamp battery. Chunky proportions so it reads at 40 px.

The walk is computed, not hand keyed: the stance foot is planted on the floor
(heel strike, flat foot, roll over the ball) and moves back at exactly strideM per
cycle; the legs follow by analytic two-bone IK; pelvis bob, sway, yaw and hip drop,
counter-rotating shoulders and arm swing make it natural.

Run (background Blender only):
    "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" --background --factory-startup
        --python team/ui/assets/mine-art/actors/worker.py [-- --no-render] [-- --samples N]
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import actors_style as S  # noqa: E402
import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

NAME = "worker"
FPS = 30
WALK_FRAMES = 30          # 1.0 s per cycle
IDLE_FRAMES = 120         # 4.0 s
STRIDE = 3.0              # metres per walk cycle (two steps), scene metres
STANCE = 0.60             # fraction of the cycle a foot is on the floor
# work loops: name -> frames (30 fps); each a loop on the spot, the root fixed
WORK_FRAMES = {"work_drill": 60, "work_scale": 72, "work_inspect": 90}
WORK_PROP = {"work_drill": "prop_drill", "work_scale": "prop_bar", "work_inspect": "prop_hammer"}
PROP_BONES = ("prop_drill", "prop_bar", "prop_hammer")
PROP_REST = Vector((-0.10, 0.0, 2.60))   # bind pose of every prop: its origin here, inside the pelvis
PROP_REST_S = 0.15                      # ... drawn at this scale (keeps the bounding box of the figure)
PROP_HIDDEN_S = 0.001                   # a prop's bone scale in the clips that do not use it
HAND_REACH = 0.20                       # wrist to the middle of the mitten, along the forearm

# skeleton (armature space = Blender object space, metres)
HIP_Y = 0.25
HIP_Z = 2.45
KNEE_Z = 1.38
ANKLE_Z = 0.30
SHOULDER = (0.0, 0.70, 3.74)
ELBOW = (-0.01, 0.74, 2.94)
WRIST = (0.05, 0.77, 2.24)
BONES = [
    # name, head, tail, parent
    ("root", (0, 0, 0), (0, 0, 0.6), None),
    ("hips", (0, 0, 2.50), (0, 0, 2.86), "root"),
    ("spine", (0, 0, 2.86), (0, 0, 3.90), "hips"),
    ("head", (0, 0, 3.96), (0, 0, 4.70), "spine"),
]
for _s, _n in ((1, "L"), (-1, "R")):
    BONES += [
        (f"thigh.{_n}", (0, _s * HIP_Y, HIP_Z), (0, _s * HIP_Y, KNEE_Z), "hips"),
        (f"shin.{_n}", (0, _s * HIP_Y, KNEE_Z), (0, _s * HIP_Y, ANKLE_Z), f"thigh.{_n}"),
        (f"foot.{_n}", (0, _s * HIP_Y, ANKLE_Z), (0.42, _s * HIP_Y, 0.08), f"shin.{_n}"),
        (f"upperarm.{_n}", (SHOULDER[0], _s * SHOULDER[1], SHOULDER[2]), (ELBOW[0], _s * ELBOW[1], ELBOW[2]), "spine"),
        (f"forearm.{_n}", (ELBOW[0], _s * ELBOW[1], ELBOW[2]), (WRIST[0], _s * WRIST[1], WRIST[2]), f"upperarm.{_n}"),
    ]
for _p in ("prop_drill", "prop_bar", "prop_hammer"):
    BONES.append((_p, (-0.10, 0.0, 2.60), (-0.10, 0.0, 3.00), "root"))
BONE_NAMES = [b[0] for b in BONES]

# foot (boot) geometry relative to the ankle, in the sagittal plane (x fwd, z up)
HEEL = Vector((-0.18, -ANKLE_Z))
BALL = Vector((0.30, -ANKLE_Z))
HS_PITCH = math.radians(14)     # toes up at heel strike
# preview scales: from the main view the figure is ~4.8 m tall on screen (5 m x cos 28 deg
# plus the depth of the helmet), so these give 40 px and 150 px tall figures
PPM_40 = 8.4
PPM_150 = 31.3
TO_PITCH = math.radians(-25)    # heel up at toe off


# --------------------------------------------------------------------------- geometry


def clamp01(x):
    return max(0.0, min(1.0, x))


def smooth(e0, e1, x):
    t = clamp01((x - e0) / (e1 - e0))
    return t * t * (3 - 2 * t)


class Piece(S.Part):
    """A Part with per-vertex bone weights given by a function of the position."""

    def loft(self, sections, n=8, power=2.0, slot_of=None, cap0=True, cap1=True, phase=0.5, default="orange"):
        """Rings (cx, cy, z, rx, ry) joined in order; slot_of(i_band, k_side) -> palette key."""
        rings = []
        for cx, cy, z, rx, ry in sections:
            ring = []
            for k in range(n):
                a = 2 * math.pi * (k + phase) / n
                c, s = math.cos(a), math.sin(a)
                e = 2.0 / power
                ring.append(self.bm.verts.new((cx + rx * math.copysign(abs(c) ** e, c),
                                               cy + ry * math.copysign(abs(s) ** e, s), z)))
            rings.append(ring)
        for i, (r0, r1) in enumerate(zip(rings, rings[1:])):
            for k in range(n):
                j = (k + 1) % n
                slot = slot_of(i, k) if slot_of else default
                self.face((r0[k], r0[j], r1[j], r1[k]), slot or default)
        if cap0:
            self.face(list(reversed(rings[0])), slot_of(-1, 0) if slot_of else default)
        if cap1:
            self.face(rings[-1], slot_of(len(rings) - 1, 0) if slot_of else default)
        return rings

    def ellipsoid(self, c, rx, ry, rz, segs, rings, slot, z_from=-1.0):
        cx, cy, cz = c
        lat0 = math.asin(max(-1.0, min(1.0, z_from)))
        rows = []
        for i in range(rings):
            lat = lat0 + (math.pi / 2 - lat0) * i / rings
            rows.append([self.bm.verts.new((cx + rx * math.cos(lat) * math.cos(2 * math.pi * k / segs),
                                            cy + ry * math.cos(lat) * math.sin(2 * math.pi * k / segs),
                                            cz + rz * math.sin(lat))) for k in range(segs)])
        top = self.bm.verts.new((cx, cy, cz + rz))
        for r0, r1 in zip(rows, rows[1:]):
            for k in range(segs):
                j = (k + 1) % segs
                self.face((r0[k], r0[j], r1[j], r1[k]), slot)
        for k in range(segs):
            self.face((rows[-1][k], rows[-1][(k + 1) % segs], top), slot)
        if z_from > -1.0:
            self.face(list(reversed(rows[0])), slot)
        return rows


def band_slot(bands, slot, default="orange"):
    """slot_of for a loft: faces of the listed band indices get `slot`."""
    def f(i, k):
        return slot if i in bands else default
    return f


def build_pieces(mats):
    """Separate objects (for per-part occlusion in the bake), each with a weight rule."""
    pieces = []

    for s, n in ((1, "L"), (-1, "R")):
        # leg: hip -> ankle, one reflective band below the knee
        leg = Piece(f"leg.{n}", mats)
        y = s * HIP_Y
        secs = [(0.0, y, 2.58, 0.31, 0.25), (0.01, y, 2.36, 0.32, 0.26), (0.02, y, 2.00, 0.29, 0.24),
                (0.02, y, 1.62, 0.25, 0.22), (0.03, y, 1.38, 0.235, 0.21), (0.0, y, 1.12, 0.245, 0.215),
                (-0.01, y, 0.80, 0.21, 0.19), (-0.01, y, 0.66, 0.205, 0.185), (0.0, y, 0.36, 0.18, 0.165)]
        leg.loft(secs, n=8, slot_of=band_slot({6}, "reflect"), cap0=False, cap1=False)

        def w_leg(co, n=n):
            k = smooth(1.22, 1.54, co.z)
            hip = 0.5 * smooth(2.36, 2.58, co.z)
            return {f"thigh.{n}": k * (1 - hip), f"shin.{n}": 1 - k, "hips": k * hip}
        pieces.append((leg, w_leg))

        # boot: side profile with toe spring, rigid to the foot
        boot = Piece(f"boot.{n}", mats)
        prof = [(-0.24, 0.0), (0.30, 0.0), (0.48, 0.04), (0.56, 0.12), (0.50, 0.22), (0.24, 0.29),
                (0.17, 0.48), (-0.24, 0.48)]
        boot.prism_xz(prof, y - 0.19, y + 0.19, "boot")
        boot.box((-0.25, y - 0.195, 0.0), (0.30, y + 0.195, 0.07), "chassis")
        pieces.append((boot, lambda co, n=n: {f"foot.{n}": 1.0}))

        # arm: shoulder -> wrist, a reflective band on the upper arm
        arm = Piece(f"arm.{n}", mats)
        ax = [(0.00, 0.70, 3.93, 0.14, 0.14), (0.00, 0.73, 3.78, 0.235, 0.23), (-0.01, 0.755, 3.50, 0.225, 0.215),
              (-0.01, 0.76, 3.26, 0.212, 0.205), (-0.01, 0.765, 3.12, 0.21, 0.20), (-0.01, 0.77, 2.94, 0.195, 0.188),
              (0.01, 0.78, 2.64, 0.182, 0.175), (0.035, 0.79, 2.42, 0.168, 0.16), (0.05, 0.795, 2.26, 0.152, 0.145)]
        arm.loft([(cx, s * cy, z, rx, ry) for cx, cy, z, rx, ry in ax], n=8,
                 slot_of=band_slot({3}, "reflect"), cap0=False, cap1=True)
        arm.loft([(0.0, s * 0.70, 3.93, 0.14, 0.14), (0.0, s * 0.69, 4.00, 0.07, 0.07)], n=8, cap0=False, cap1=True)

        def w_arm(co, n=n):
            k = smooth(2.84, 3.06, co.z)
            top = 0.35 * smooth(3.80, 3.95, co.z)
            return {f"upperarm.{n}": k * (1 - top), f"forearm.{n}": 1 - k, "spine": k * top}
        pieces.append((arm, w_arm))

        # glove (mitten), rigid to the forearm
        hand = Piece(f"hand.{n}", mats)
        hand.loft([(0.05, s * 0.795, 2.32, 0.135, 0.12), (0.08, s * 0.80, 2.12, 0.155, 0.10),
                   (0.09, s * 0.805, 1.98, 0.14, 0.09), (0.08, s * 0.805, 1.89, 0.08, 0.06)],
                  n=6, default="glove", cap0=False, cap1=True)
        pieces.append((hand, lambda co, n=n: {f"forearm.{n}": 1.0}))

    # pelvis with the belt, the lamp battery on the back
    pel = Piece("pelvis", mats)
    pel.loft([(0.0, 0.0, 2.28, 0.33, 0.42), (0.0, 0.0, 2.45, 0.38, 0.50), (0.0, 0.0, 2.68, 0.39, 0.51),
              (0.0, 0.0, 2.80, 0.385, 0.50), (0.0, 0.0, 2.93, 0.38, 0.495)], n=10, power=2.4,
             slot_of=band_slot({3}, "gear"), cap0=True, cap1=False)
    pel.box((-0.50, -0.24, 2.60), (-0.34, 0.08, 2.92), "gear")
    pel.box((0.10, 0.40, 2.58), (0.32, 0.51, 2.80), "orange_dk")
    pieces.append((pel, lambda co: {"hips": 1.0}))

    # torso: waist -> shoulders; chest band; two vertical bands front and back
    tor = Piece("torso", mats)
    secs = [(0.00, 0.0, 2.84, 0.36, 0.46), (0.01, 0.0, 3.05, 0.39, 0.49), (0.02, 0.0, 3.28, 0.41, 0.53),
            (0.02, 0.0, 3.42, 0.415, 0.545), (0.015, 0.0, 3.62, 0.41, 0.555), (0.0, 0.0, 3.80, 0.38, 0.565),
            (-0.01, 0.0, 3.93, 0.32, 0.46), (0.0, 0.0, 4.02, 0.22, 0.23)]
    nside = 12

    def torso_slot(i, k):
        if i == 2:
            return "reflect"
        centre = (k + 0.5 + 0.5) * 360.0 / nside % 360.0      # face centre angle (deg), 0 = front
        if i in (0, 1, 3, 4) and min(abs(centre - a) for a in (30, 330, 150, 210)) < 1:
            return "reflect"
        if i >= 5:
            return "orange_dk"
        return "orange"
    tor.loft(secs, n=nside, power=2.6, slot_of=torso_slot, cap0=False, cap1=True, phase=0.5)
    pieces.append((tor, lambda co: {"spine": smooth(2.84, 3.10, co.z), "hips": 1 - smooth(2.84, 3.10, co.z)}))

    # head, neck, helmet with brim, ridge and cap lamp
    hd = Piece("head", mats)
    hd.loft([(0.0, 0.0, 3.92, 0.17, 0.17), (0.02, 0.0, 4.16, 0.16, 0.16)], n=8, default="skin",
            cap0=False, cap1=False)
    hd.ellipsoid((0.03, 0.0, 4.35), 0.31, 0.29, 0.34, 10, 5, "skin", z_from=-0.9)
    hd.hexa([(0.31, -0.055, 4.27), (0.385, -0.04, 4.28), (0.385, 0.04, 4.28), (0.31, 0.055, 4.27),
             (0.31, -0.045, 4.40), (0.34, -0.035, 4.40), (0.34, 0.035, 4.40), (0.31, 0.045, 4.40)], "skin")
    hc = Vector((0.02, 0.0, 4.48))
    hd.ellipsoid(tuple(hc), 0.43, 0.40, 0.52, 12, 4, "helmet", z_from=0.0)
    rings = []
    for z, grow in ((hc.z + 0.02, 0.0), (hc.z - 0.03, 0.0), (hc.z - 0.05, 1.0), (hc.z, 1.0)):
        ring = []
        for k in range(12):
            a = 2 * math.pi * k / 12
            front = max(0.0, math.cos(a)) ** 2
            rx = 0.435 + grow * (0.08 + 0.13 * front)
            ry = 0.405 + grow * 0.08
            ring.append(hd.bm.verts.new((hc.x + rx * math.cos(a), hc.y + ry * math.sin(a), z)))
        rings.append(ring)
    for r0, r1 in zip(rings, rings[1:] + [rings[0]]):
        for k in range(12):
            j = (k + 1) % 12
            hd.face((r0[k], r0[j], r1[j], r1[k]), "helmet")
    hd.hexa([(-0.32, -0.045, hc.z + 0.30), (0.32, -0.045, hc.z + 0.30), (0.32, 0.045, hc.z + 0.30), (-0.32, 0.045, hc.z + 0.30),
             (-0.21, -0.045, hc.z + 0.54), (0.21, -0.045, hc.z + 0.54), (0.21, 0.045, hc.z + 0.54), (-0.21, 0.045, hc.z + 0.54)],
            "helmet")
    hd.box((0.38, -0.085, hc.z + 0.08), (0.51, 0.085, hc.z + 0.23), "gear")
    hd.decal((0.51, 0.0, hc.z + 0.155), "+x", 0.13, 0.11, "lens_paint", off=0.006)
    pieces.append((hd, lambda co: {"head": smooth(3.92, 4.06, co.z), "spine": 1 - smooth(3.92, 4.06, co.z)}))
    return pieces


# props of the work loops, in their own frame: origin at the right (rear) hand's grip,
# +X along the tool, Z up; LEFT_GRIP is where the left hand holds it
DRILL_P0 = Vector((0.73, -0.22, 2.54))          # mean place of the drill grip in the work_drill clip
DRILL_FOOT = Vector((-0.25, -1.05, 0.02))       # the feed leg's foot on the floor (armature space)
LEFT_GRIP = {"prop_drill": Vector((0.55, 0.10, 0.15)), "prop_bar": Vector((1.0, 0.0, 0.0)), "prop_hammer": None}


def drill_rot(t=None):
    """World rotation of the drill (the mean one without t)."""
    tau = 2 * math.pi
    jit = 0.0 if t is None else math.radians(1.2) * math.sin(tau * 15 * t + 0.4)
    return Rz(math.radians(-4.0)) @ Ry(-(math.radians(5.0) + jit))


def build_props(mats):
    """The three props (pieces rigid to their bones), placed small at the bind pose (PROP_REST, PROP_REST_S)."""
    out = []
    drill = Piece("prop_drill", mats)
    drill.box((-0.06, -0.12, -0.13), (0.85, 0.12, 0.15), "steel_dk")       # rock drill body with the handle
    drill.cylinder((0.85, 0, 0.0), (2.70, 0, 0.0), 0.045, 4, "steel", caps=False)  # drill steel
    leg_end = drill_rot().inverted() @ (DRILL_FOOT - DRILL_P0)
    drill.cylinder((0.45, 0, -0.12), tuple(leg_end), 0.06, 4, "chassis", caps=False)  # feed leg (jackleg)
    out.append(drill)
    bar = Piece("prop_bar", mats)
    bar.cylinder((-0.40, 0, 0), (3.80, 0, 0), 0.07, 4, "steel", caps=True)  # scaling bar
    out.append(bar)
    hammer = Piece("prop_hammer", mats)
    hammer.cylinder((-0.08, 0, 0), (0.62, 0, 0), 0.05, 4, "rim", caps=False)  # handle
    hammer.box((0.50, -0.07, -0.20), (0.66, 0.07, 0.15), "steel_dk")         # head
    out.append(hammer)
    pieces = []
    for piece in out:
        for v in piece.bm.verts:
            v.co = PROP_REST + PROP_REST_S * v.co
        pieces.append((piece, lambda co, n=piece.name: {n: 1.0}))
    return pieces


# --------------------------------------------------------------------------- rig


def build_rig(root):
    arm = bpy.data.armatures.new("worker_rig")
    ob = bpy.data.objects.new("worker_rig", arm)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = root
    S.select_only([ob])
    bpy.ops.object.mode_set(mode="EDIT")
    eb = {}
    for name, head, tail, parent in BONES:
        b = arm.edit_bones.new(name)
        b.head, b.tail = Vector(head), Vector(tail)
        b.roll = 0.0
        if parent:
            b.parent = eb[parent]
            b.use_connect = False
        eb[name] = b
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.display_type = "STICK"
    return ob


# --------------------------------------------------------------------------- motion


def rot2(v, a):
    """Rotate a 2D (x, z) vector by angle a (positive lifts +x toward +z)."""
    c, s = math.cos(a), math.sin(a)
    return Vector((v.x * c - v.y * s, v.x * s + v.y * c))


def hermite(p0, p1, m0, m1, t):
    t2, t3 = t * t, t * t * t
    return ((2 * t3 - 3 * t2 + 1) * p0 + (t3 - 2 * t2 + t) * m0 + (-2 * t3 + 3 * t2) * p1 + (t3 - t2) * m1)


X_HEEL0 = 0.60     # heel x (relative to the hip) at heel strike


def foot_state(p):
    """(ankle (x, z) relative to the hip column, pitch) for a foot at cycle phase p."""
    p %= 1.0
    sb = STRIDE * STANCE
    if p < STANCE:
        u = p / STANCE
        heel_x = X_HEEL0 - STRIDE * p
        if u < 0.15:
            pitch = HS_PITCH * (1 - smooth(0.0, 0.15, u))
            ankle = Vector((heel_x, 0.0)) + rot2(-HEEL, pitch)
        elif u < 0.62:
            pitch = 0.0
            ankle = Vector((heel_x, 0.0)) - HEEL
        else:
            pitch = TO_PITCH * smooth(0.62, 1.0, u)
            ball_x = heel_x + (BALL.x - HEEL.x)
            ankle = Vector((ball_x, 0.0)) + rot2(-BALL, pitch)
        return ankle, pitch
    w = (p - STANCE) / (1 - STANCE)
    a0, _ = foot_state(STANCE - 1e-9)
    ball_end = X_HEEL0 - sb + (BALL.x - HEEL.x)
    a0 = Vector((ball_end, 0.0)) + rot2(-BALL, TO_PITCH)
    a1 = Vector((X_HEEL0, 0.0)) + rot2(-HEEL, HS_PITCH)
    x = hermite(a0.x, a1.x, -0.25 * STRIDE * (1 - STANCE), -0.30 * STRIDE * (1 - STANCE), w)
    z = a0.y + (a1.y - a0.y) * smooth(0.0, 1.0, w) + 0.30 * math.sin(math.pi * w) ** 1.1
    pitch = TO_PITCH + (HS_PITCH - TO_PITCH) * smooth(0.08, 0.92, w)
    return Vector((x, z)), pitch


def lowest_boot_points():
    """Lowest toe-tip and heel heights over the whole cycle (0 = floor)."""
    toe, heel = Vector((0.53, 0.11 - ANKLE_Z)), Vector((-0.22, -ANKLE_Z))
    lt = lh = 9.0
    for i in range(240):
        a, pitch = foot_state(i / 240)
        lt = min(lt, a.y + rot2(toe, pitch).y)
        lh = min(lh, a.y + rot2(heel, pitch).y)
    return lt, lh


def Rx(a):
    return Matrix.Rotation(a, 3, "X")


def Ry(a):
    return Matrix.Rotation(a, 3, "Y")


def Rz(a):
    return Matrix.Rotation(a, 3, "Z")


def align(rest_dir, new_dir):
    return rest_dir.rotation_difference(new_dir).to_matrix()


class Rig:
    def __init__(self, ob):
        self.ob = ob
        self.bones = ob.data.bones
        self.rest = {b.name: b.matrix_local.copy() for b in self.bones}
        self.head = {b.name: b.head_local.copy() for b in self.bones}
        self.tail = {b.name: b.tail_local.copy() for b in self.bones}
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in self.bones}
        self.max_reach = 0.0

    def rest_dir(self, n):
        return (self.tail[n] - self.head[n]).normalized()

    def length(self, n):
        return (self.tail[n] - self.head[n]).length

    def leg_ik(self, side, hip, ankle, pitch, twist):
        """Two-bone IK in 3D, knee toward +X. Returns D for thigh, shin, foot."""
        n = side
        l1, l2 = self.length(f"thigh.{n}"), self.length(f"shin.{n}")
        d = ankle - hip
        dist = d.length
        self.max_reach = max(self.max_reach, dist / (l1 + l2))
        dist = min(dist, (l1 + l2) * 0.9995)
        u = d.normalized()
        ca = (l1 * l1 + dist * dist - l2 * l2) / (2 * l1 * dist)
        a = math.acos(max(-1.0, min(1.0, ca)))
        pole = Vector((1.0, 0.0, 0.0))
        w = (pole - u * pole.dot(u)).normalized()
        knee = hip + l1 * (math.cos(a) * u + math.sin(a) * w)
        end = hip + u * dist
        d_thigh = align(self.rest_dir(f"thigh.{n}"), (knee - hip).normalized()) @ Rz(twist)
        d_shin = align(self.rest_dir(f"shin.{n}"), (end - knee).normalized())
        d_foot = Ry(-pitch)
        return d_thigh, d_shin, d_foot

    def shoulder(self, side, D, H):
        """World head of the upper arm for the rotations D of hips and spine and the hips head H['hips']."""
        sp = H["hips"] + D["hips"] @ (self.head["spine"] - self.head["hips"])
        return sp + D["spine"] @ (self.head[f"upperarm.{side}"] - self.head["spine"])

    def arm_ik(self, side, D, H, grip, pole):
        """Two-bone IK: the middle of the mitten on `grip`, the elbow toward `pole`. Sets D of upper arm and forearm."""
        n = side
        sh = self.shoulder(side, D, H)
        l1, l2 = self.length(f"upperarm.{n}"), self.length(f"forearm.{n}") + HAND_REACH
        d = grip - sh
        dist = d.length
        self.arm_reach = max(getattr(self, "arm_reach", 0.0), dist / (l1 + l2))
        dist = max(min(dist, (l1 + l2) * 0.999), abs(l1 - l2) + 0.02)
        u = d.normalized()
        a = math.acos(max(-1.0, min(1.0, (l1 * l1 + dist * dist - l2 * l2) / (2 * l1 * dist))))
        w = (pole - u * pole.dot(u)).normalized()
        elbow = sh + l1 * (math.cos(a) * u + math.sin(a) * w)
        D[f"upperarm.{n}"] = align(self.rest_dir(f"upperarm.{n}"), (elbow - sh).normalized())
        D[f"forearm.{n}"] = align(self.rest_dir(f"forearm.{n}"), (sh + u * dist - elbow).normalized())

    def apply(self, D, H, frame, scales=None):
        """D: bone -> world delta rotation (3x3); H: explicit head positions (hips, props); scales: prop bone -> scale
        (a prop not named is hidden)."""
        M = {}
        heads = {}
        for name in BONE_NAMES:
            par = self.parent[name]
            Dm = D.get(name, Matrix.Identity(3))
            if name in H:
                h = H[name]
            elif par is None:
                h = self.head[name]
            else:
                Dp = D.get(par, Matrix.Identity(3))
                h = heads[par] + Dp @ (self.head[name] - self.head[par])
            heads[name] = h
            M[name] = Matrix.Translation(h) @ (Dm @ self.rest[name].to_3x3()).to_4x4()
            if par is None:
                basis = self.rest[name].inverted() @ M[name]
            else:
                basis = (self.rest[par].inverted() @ self.rest[name]).inverted() @ M[par].inverted() @ M[name]
            pb = self.ob.pose.bones[name]
            pb.rotation_mode = "QUATERNION"
            pb.matrix_basis = basis
            pb.keyframe_insert("location", frame=frame)
            pb.keyframe_insert("rotation_quaternion", frame=frame)
            if name in PROP_BONES:
                s = (scales or {}).get(name, PROP_HIDDEN_S)
                pb.scale = (s, s, s)
                pb.keyframe_insert("scale", frame=frame)
        return heads


def walk_pose(rig, p):
    """Pose at walk phase p in [0, 1): left heel strikes at p = 0, right at 0.5."""
    tau = 2 * math.pi
    bob = 0.045 * math.cos(2 * tau * (p - 0.30))
    sway = 0.035 * math.cos(tau * (p - 0.30))
    yaw = math.radians(-5.0) * math.cos(tau * p)
    roll = math.radians(3.0) * math.cos(tau * (p - 0.30))
    hips_h = Vector((0.0, sway, 2.50 - 0.07 + bob))
    D = {"hips": Rz(yaw) @ Rx(roll)}
    spine_yaw = -1.4 * yaw
    D["spine"] = Rz(spine_yaw) @ Ry(math.radians(4.0)) @ Rx(-0.6 * roll)
    D["head"] = Ry(math.radians(-2.0 + 1.0 * math.cos(2 * tau * (p - 0.30)))) @ Rz(0.3 * spine_yaw)
    for side, s, ph in (("L", 1, 0.0), ("R", -1, 0.5)):
        hip = hips_h + D["hips"] @ (rig.head[f"thigh.{side}"] - rig.head["hips"])
        a2, pitch = foot_state(p - ph)
        ankle = Vector((a2.x, s * HIP_Y, a2.y))
        D[f"thigh.{side}"], D[f"shin.{side}"], D[f"foot.{side}"] = rig.leg_ik(side, hip, ankle, pitch, yaw)
        # arms: opposite to the leg of the same side, a little late
        swing = math.radians(20.0) * -math.cos(tau * (p - ph - 0.04))
        flex = math.radians(10.0) + math.radians(16.0) * max(0.0, swing) / math.radians(20.0)
        D[f"upperarm.{side}"] = Rz(spine_yaw) @ Ry(-swing) @ Rx(s * math.radians(2.0))
        D[f"forearm.{side}"] = Rz(spine_yaw) @ Ry(-(swing + flex))
    return D, {"hips": hips_h}


def idle_pose(rig, t):
    """Pose at idle time t in [0, 1): slow breath and a slight weight shift."""
    tau = 2 * math.pi
    br = math.sin(tau * t)
    shift = math.sin(tau * t + 0.6)
    hips_h = Vector((0.0, 0.015 * shift, 2.50 - 0.02 + 0.006 * br))
    D = {"hips": Rx(math.radians(0.8) * shift)}
    D["spine"] = Ry(math.radians(1.5 + 0.7 * br)) @ Rx(math.radians(-0.6) * shift)
    D["head"] = Ry(math.radians(-1.0 - 0.6 * br)) @ Rz(math.radians(3.0) * math.sin(tau * t + 1.3))
    for side, s in (("L", 1), ("R", -1)):
        hip = hips_h + D["hips"] @ (rig.head[f"thigh.{side}"] - rig.head["hips"])
        ankle = Vector((0.02, s * HIP_Y, ANKLE_Z))
        D[f"thigh.{side}"], D[f"shin.{side}"], D[f"foot.{side}"] = rig.leg_ik(side, hip, ankle, 0.0, 0.0)
        sw = math.radians(1.2) * br
        D[f"upperarm.{side}"] = Ry(-sw) @ Rx(s * math.radians(1.5 + 0.8 * br))
        D[f"forearm.{side}"] = Ry(-(sw + math.radians(8.0)))
    return D, {"hips": hips_h}


def stand(rig, D, H, feet):
    """Legs by IK to flat feet at feet = {(side): (x, y)} on the floor."""
    for side in ("L", "R"):
        hip = H["hips"] + D["hips"] @ (rig.head[f"thigh.{side}"] - rig.head["hips"])
        x, y = feet[side]
        D[f"thigh.{side}"], D[f"shin.{side}"], D[f"foot.{side}"] = rig.leg_ik(side, hip, Vector((x, y, ANKLE_Z)), 0.0, 0.0)


def hold(rig, D, H, prop, P, R, right_grip=Vector((0, 0, 0)), poles=None):
    """The prop's bone at P turned by R (world); the right hand on right_grip, the left on LEFT_GRIP (prop frame)."""
    H[prop] = P
    D[prop] = R
    poles = poles or {"R": Vector((-0.35, -0.80, -0.50)), "L": Vector((-0.30, 0.80, -0.60))}
    rig.arm_ik("R", D, H, P + R @ right_grip, poles["R"])
    if LEFT_GRIP[prop] is not None:
        rig.arm_ik("L", D, H, P + R @ LEFT_GRIP[prop], poles["L"])
    return {prop: 1.0 / PROP_REST_S}


def drill_pose(rig, t):
    """Jackleg drilling: a lunge behind the drill, the feed pushing it forward and easing back once a loop, the
    machine shaking (7.5 Hz and 4.5 Hz) through the hands, shoulders and head."""
    tau = 2 * math.pi
    feed = 0.5 - 0.5 * math.cos(tau * t)
    vx = 0.05 * math.sin(tau * 15 * t)
    vz = 0.035 * math.sin(tau * 9 * t + 0.7)
    vy = 0.02 * math.sin(tau * 12 * t + 1.9)
    P = DRILL_P0 + Vector((-0.11 + 0.22 * feed + vx, vy, -0.02 + 0.04 * feed + vz))
    H = {"hips": Vector((-0.10 + 0.10 * feed + 0.3 * vx, 0.0, 2.50 - 0.24 + 0.25 * vz))}
    D = {"hips": Rz(math.radians(-12.0))}
    D["spine"] = Rz(math.radians(-10.0)) @ Ry(math.radians(14.0 + 4.0 * feed)) @ Rx(math.radians(0.8) * math.sin(tau * 12 * t))
    D["head"] = Ry(math.radians(-10.0 + 1.5 * math.sin(tau * 15 * t + 0.5))) @ Rz(math.radians(-6.0))
    stand(rig, D, H, {"L": (0.55, 0.36), "R": (-0.55, -0.34)})
    return D, H, hold(rig, D, H, "prop_drill", P, drill_rot(t))


def scale_pose(rig, t):
    """Scaling: the bar thrust up at the back, a short pry, then drawn back slowly; the head follows the tip."""
    s = smooth(0.08, 0.30, t) * (1 - smooth(0.52, 0.92, t))
    pry = math.sin(math.pi * clamp01((t - 0.30) / 0.22)) if 0.30 < t < 0.52 else 0.0
    pitch = math.radians(48.0 + 6.0 * s - 4.0 * pry)
    R = Rz(math.radians(-3.0)) @ Ry(-pitch)
    along = R @ Vector((1.0, 0.0, 0.0))
    P = Vector((0.22, -0.12, 2.55)) + along * (0.50 * s) + Vector((0.05 * s, 0.0, 0.10 * s))
    H = {"hips": Vector((-0.05 + 0.10 * s, 0.0, 2.50 - 0.12 - 0.04 * s))}
    D = {"hips": Rz(math.radians(-8.0))}
    D["spine"] = Rz(math.radians(-6.0)) @ Ry(math.radians(-2.0 + 6.0 * s + 2.0 * pry))
    D["head"] = Ry(math.radians(-18.0 - 6.0 * s))
    stand(rig, D, H, {"L": (0.40, 0.34), "R": (-0.50, -0.30)})
    return D, H, hold(rig, D, H, "prop_bar", P, R)


def inspect_pose(rig, t):
    """Inspecting the rock: three taps of the hammer at the face, the left hand on the rock; then the hammer down,
    the hand sliding up the face and the eyes following it, and back."""
    tau = 2 * math.pi
    if t < 0.5:
        u = (t * 6.0) % 1.0
        k = 1 - smooth(0.0, 0.6, u) ** 1.6 if u < 0.6 else smooth(0.6, 1.0, u)   # 1 raised, 0 at the strike
    else:
        k = 1.0
    hit = max(0.0, 1 - abs((t * 6.0) % 1.0 - 0.62) / 0.08) if t < 0.5 else 0.0
    w = smooth(0.50, 0.62, t) * (1 - smooth(0.86, 1.0, t))
    tap_p = math.radians(78.0 + 52.0 * k)
    tap_g = Vector((0.92 - 0.16 * k, -0.34, 3.20 + 0.14 * k))
    rest_g = Vector((0.50, -0.62, 2.30))
    G = tap_g.lerp(rest_g, w)
    pitch = tap_p + (math.radians(100.0) - tap_p) * w
    R = Rz(math.radians(-6.0)) @ Ry(-pitch)
    H = {"hips": Vector((0.05, 0.02 * w, 2.50 - 0.04))}
    D = {"hips": Rz(math.radians(-4.0 + 4.0 * w))}
    D["spine"] = Rz(math.radians(-6.0 + 6.0 * w)) @ Ry(math.radians(8.0 + 1.5 * hit - 3.0 * w))
    D["head"] = Ry(math.radians(4.0 - 22.0 * w + 2.0 * math.sin(tau * t))) @ Rz(math.radians(-8.0 + 20.0 * w))
    stand(rig, D, H, {"L": (0.25, 0.32), "R": (-0.20, -0.30)})
    scales = hold(rig, D, H, "prop_hammer", G, R)
    rig.arm_ik("L", D, H, Vector((1.22, 0.30, 3.50 + 0.35 * w)), Vector((-0.4, 0.8, -0.5)))
    return D, H, scales


WORK_POSES = {"work_drill": drill_pose, "work_scale": scale_pose, "work_inspect": inspect_pose}


def make_clip(rig, name, frames, pose_fn):
    ob = rig.ob
    ob.animation_data_create()
    act = bpy.data.actions.new(name)
    ob.animation_data.action = act
    for f in range(frames + 1):
        D, H, *rest = pose_fn(rig, (f % frames) / frames)
        rig.apply(D, H, f, rest[0] if rest else None)
    # linear keys (the clip is sampled every frame anyway)
    try:
        curves = act.fcurves
    except AttributeError:
        curves = [fc for layer in act.layers for strip in layer.strips
                  for bag in strip.channelbags for fc in bag.fcurves]
    for fc in curves:
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
    ob.animation_data.action = None
    track = ob.animation_data.nla_tracks.new()
    track.name = name
    strip = track.strips.new(name, 0, act)
    strip.name = name
    try:
        if act.slots:
            strip.action_slot = act.slots[0]
    except AttributeError:
        pass
    track.mute = False
    return act


# --------------------------------------------------------------------------- previews


def render_worker_previews(glb):
    roots, _ = S.reimport_unlit(glb)
    S.make_world(S.FLOOR_HEX)
    root = next(o for o in roots if o.name == NAME)
    rig = next(o for o in root.children_recursive if o.type == "ARMATURE")
    meshes = [o for o in root.children_recursive if o.type == "MESH"]
    acts = {a.name: a for a in bpy.data.actions}
    walk = next(a for n, a in acts.items() if n.startswith("walk"))
    idle = next(a for n, a in acts.items() if n.startswith("idle"))
    ad = rig.animation_data or rig.animation_data_create()
    for tr in list(ad.nla_tracks):
        tr.mute = True

    def use(act):
        ad.action = act
        try:
            if act.slots:
                ad.action_slot = act.slots[0]
        except AttributeError:
            pass

    scene = bpy.context.scene
    scene.render.fps = FPS
    tmp = os.path.join(S.PREVIEW_DIR, "_tiles")
    os.makedirs(tmp, exist_ok=True)
    root.rotation_mode = "XYZ"
    out = []
    # standing and walking at 40 px and 150 px tall, four headings
    for tag, ppm in (("40px", PPM_40), ("150px", PPM_150)):
        rows = []
        for act, frame in ((idle, 0), (walk, 7)):
            use(act)
            scene.frame_set(frame)
            row = []
            for hname, deg in S.HEADINGS:
                root.rotation_euler = (0, 0, math.radians(deg))
                bpy.context.view_layer.update()
                pth = os.path.join(tmp, f"worker_{tag}_{act.name}_{hname}.png")
                size = (int(3.4 * ppm) + 16, int(5.6 * ppm) + 16)
                c = Vector((0, 0, 2.4))
                S.render_tile(meshes, ppm, pth, centre=c, size=size)
                row.append(pth)
            rows.append(row)
        p = os.path.join(S.PREVIEW_DIR, f"worker_glb_unlit_{tag}.png")
        S.compose_grid(rows, p)
        out.append(p)
        if tag == "40px":
            q = os.path.join(S.PREVIEW_DIR, "worker_glb_unlit_40px_x4.png")
            import numpy as np
            arr = S.load_rgba(p)
            S.save_rgba(arr.repeat(4, axis=0).repeat(4, axis=1), q)
            out.append(q)
    # walk-cycle contact sheet: 8 frames, side (E) and three-quarter (SE) rows
    use(walk)
    rows = []
    for hname, deg in (("E", 0.0), ("SE", -45.0)):
        root.rotation_euler = (0, 0, math.radians(deg))
        row = []
        for i in range(8):
            f = i * WALK_FRAMES / 8
            scene.frame_set(int(f), subframe=f - int(f))
            pth = os.path.join(tmp, f"worker_walk_{hname}_{i}.png")
            ppm = PPM_150
            S.render_tile(meshes, ppm, pth, centre=Vector((0, 0, 2.4)), size=(int(3.6 * ppm), int(5.6 * ppm) + 10))
            row.append(pth)
        rows.append(row)
    p = os.path.join(S.PREVIEW_DIR, "worker_walk_contact_sheet.png")
    S.compose_grid(rows, p)
    out.append(p)
    # work loops: two rows per clip (side view E, then facing south as at the zones' faces), 8 frames over the
    # loop; and the frames 0 and 3 at 40 px (x4)
    rows = []
    small = []
    for clip, frames in [(c, f) for c, f in WORK_FRAMES.items() for _ in (0, 1)]:
        deg = 0.0 if len(rows) % 2 == 0 else -90.0
        root.rotation_euler = (0, 0, math.radians(deg))
        act = next(a for n, a in acts.items() if n.startswith(clip))
        use(act)
        row = []
        for i in range(8):
            f = i * frames / 8
            scene.frame_set(int(f), subframe=f - int(f))
            pth = os.path.join(tmp, f"worker_{clip}_{int(-deg)}_{i}.png")
            ppm = 24.0
            S.render_tile(meshes, ppm, pth, centre=Vector((1.0, 0, 2.9)), size=(int(5.6 * ppm), int(6.6 * ppm)))
            row.append(pth)
            if i in (0, 3) and deg != 0.0:
                pth = os.path.join(tmp, f"worker_{clip}_{i}_40.png")
                S.render_tile(meshes, PPM_40, pth, centre=Vector((1.0, 0, 2.9)), size=(int(5.6 * PPM_40), int(6.6 * PPM_40)))
                small.append(pth)
        rows.append(row)
    p = os.path.join(S.PREVIEW_DIR, "worker_work_contact_sheet.png")
    S.compose_grid(rows, p)
    out.append(p)
    q = os.path.join(S.PREVIEW_DIR, "worker_work_40px_x4.png")
    S.compose_row(small, q, upscale=4)
    out.append(q)
    return out


# --------------------------------------------------------------------------- main


def main():
    S.reset_scene(NAME)
    S.setup_cycles(64)
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 0, WALK_FRAMES
    mats = S.Palette(style={"ao_dist": 0.35, "ao_local": True, "cavity_dist": 0.08,
                            "bevel_wide": 0.06, "bevel_thin": 0.03, "dust_height": 0.9})
    root = S.empty(NAME)
    rig_ob = build_rig(root)

    objs = []
    props = []
    for piece, wfn in build_pieces(mats) + build_props(mats):
        ob = piece.to_object(None, smooth_angle=50.0)
        for b in BONE_NAMES:
            ob.vertex_groups.new(name=b)
        for v in ob.data.vertices:
            w = wfn(v.co)
            tot = sum(w.values())
            for b, x in w.items():
                if x > 1e-4:
                    ob.vertex_groups[b].add([v.index], x / tot, "REPLACE")
        objs.append(ob)
        if piece.name in PROP_BONES:
            props.append(ob)
    S.unwrap(objs, margin=0.008, angle=55.0)
    # the props bake away from the body (no shared occlusion), at their full size
    for ob in props:
        ob.location = (40.0, 0.0, 0.0)
    img = S.bake_emit(objs, "worker_paint", 512, margin=3)
    for ob in props:
        ob.location = (0.0, 0.0, 0.0)
    S.save_image(img, os.path.join(S.HERE, "textures", "worker_paint.png"))

    if S.DO_RENDER:
        S.make_world(S.FLOOR_HEX)
        S.setup_cycles(48)
        tmp_root = S.empty("_src")
        for o in props:
            o.hide_render = True
        for o in objs:
            o.parent = tmp_root
        S.render_headings(tmp_root, objs, PPM_150, "150px", "worker_source")
        for o in objs:
            o.parent = None
        bpy.data.objects.remove(tmp_root, do_unlink=True)
        for o in props:
            o.hide_render = False

    body = S.join(objs, "worker_body")
    paint = S.unlit_texture_material("worker_paint", img)
    body.data.materials.clear()
    body.data.materials.append(paint)
    for m in list(mats.values()):
        m.use_fake_user = True
    body.parent = rig_ob
    mod = body.modifiers.new("rig", "ARMATURE")
    mod.object = rig_ob
    tris = S.tri_count(body)
    S.log("triangles", tris)

    rig = Rig(rig_ob)
    make_clip(rig, "walk", WALK_FRAMES, walk_pose)
    reach_walk = rig.max_reach
    make_clip(rig, "idle", IDLE_FRAMES, idle_pose)
    for clip, frames in WORK_FRAMES.items():
        make_clip(rig, clip, frames, WORK_POSES[clip])
    S.log(f"max leg reach: walk {reach_walk:.3f}, all {rig.max_reach:.3f} of the leg length;"
          f" max arm reach (work) {rig.arm_reach:.3f} of the arm")
    S.log("lowest boot points over the cycle: toe %.3f m, heel %.3f m (0 = floor)" % lowest_boot_points())

    scene.frame_set(0)
    root["actor"] = NAME
    root["kind"] = "underground worker (miner), stylised"
    root["heightM"] = 5.0
    root["facing"] = "+X"
    root["origin"] = "ground, between the feet"
    root["strideM"] = STRIDE
    root["walkCycleS"] = WALK_FRAMES / FPS
    root["walkSpeedAtRate1"] = STRIDE / (WALK_FRAMES / FPS)
    root["walkRate"] = "timeScale = groundSpeed / walkSpeedAtRate1"
    root["idleCycleS"] = IDLE_FRAMES / FPS
    root["clips"] = ["walk", "idle"] + list(WORK_FRAMES)
    root["workClips"] = list(WORK_FRAMES)
    root["workCycleS"] = {k: v / FPS for k, v in WORK_FRAMES.items()}
    root["props"] = "bones prop_*: scale 1/%g in the clip that uses the prop, %g in the others" % (PROP_REST_S, PROP_HIDDEN_S)

    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(S.HERE, "worker.blend"), compress=True)
    glb = os.path.join(S.OUT_DIR, "worker.glb")
    S.export_glb(root, glb, animations=True)
    S.patch_glb(glb, scene_extras={"mineArtActor": NAME, "strideM": STRIDE},
                anim_extras={"walk": {"strideM": STRIDE, "loop": True}, "idle": {"loop": True},
                             **{k: {"loop": True, "work": True, "prop": WORK_PROP[k]} for k in WORK_FRAMES}})
    S.log("exported", glb, os.path.getsize(glb))
    if S.DO_RENDER:
        for p in render_worker_previews(glb):
            S.log("preview", p)
    S.log("done")


main()
