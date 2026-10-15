"""
drill.py - the two-boom face drilling rig (drill jumbo) actor of the mine art.

Builds team/ui/public/models/mine-art/actors/drill.glb (SPEC section 6):
    drill (root, origin on the ground at the centre of the footprint, facing +X, extras)
      drill_body    carrier (power pack, cab, hose reel, turret), four stabiliser jacks,
                    two booms with feeds, rock drills and hanging hoses: one mesh, baked
      WHEELS        WHEEL_FL, WHEEL_FR, WHEEL_RL, WHEEL_RR (origin on the axle)
      LAMPS         work lamps on the cab and the booms, rear lamps, beacon
      SHADOW        soft contact shadow (vertex alpha, BLEND)
Shape after the art references (yellow carrier, long yellow-and-black booms reaching
forward, hoses in loops, jacks down), real metres (length ~12.4 m with the feeds),
scaled 1.5x to scene metres. Booms are fixed in the drilling pose.

Run (background Blender only):
    "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" --background --factory-startup
        --python team/ui/assets/mine-art/actors/drill.py [-- --no-render] [-- --samples N]
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import actors_style as S  # noqa: E402
from mathutils import Vector  # noqa: E402

NAME = "drill"
AX_F, AX_R = 1.25, -2.35
TYRE_R = 0.66
LUG = 0.10
WHEEL_Z = TYRE_R * (1 + LUG)          # 0.726
WHEEL_Y = 0.98
TYRE_W = 0.56
RIM_R = 0.36
FENDER_R = WHEEL_Z + 0.13
DECK_Z = 1.30


def beam(p, a, b, w, h, slot, up=(0, 0, 1)):
    """A box-section beam from a to b, w wide (horizontal) and h high."""
    a, b = Vector(a), Vector(b)
    d = (b - a).normalized()
    side = d.cross(Vector(up)).normalized()
    upv = side.cross(d).normalized()
    sw, sh = side * (w / 2), upv * (h / 2)
    p.hexa([a - sw - sh, b - sw - sh, b + sw - sh, a + sw - sh,
            a - sw + sh, b - sw + sh, b + sw + sh, a + sw + sh], slot)


def carrier(p):
    # frame
    p.box((-3.70, -0.62, 0.52), (2.40, 0.62, 1.04), "chassis")
    # deck plates over the wheels
    p.box((-3.70, -1.24, 1.04), (2.30, 1.24, DECK_Z - 0.10), "yellow_dk")
    p.box((-3.70, -1.24, DECK_Z - 0.10), (0.30, 1.24, DECK_Z), "yellow")
    for s in (1, -1):
        y0, y1 = sorted((s * 0.70, s * 1.30))
        p.strip_xz(S.arc(AX_F, WHEEL_Z, FENDER_R, 170, 20, 5), 0.08, y0, y1, "yellow")
        p.strip_xz(S.arc(AX_R, WHEEL_Z, FENDER_R, 170, 20, 5), 0.08, y0, y1, "yellow")
    # power pack at the rear: tall housing, cooler grille, lamps
    p.prism_xz([(-3.80, DECK_Z), (-1.30, DECK_Z), (-1.30, 2.30), (-1.50, 2.46), (-3.60, 2.46), (-3.80, 2.30)],
               -1.18, 1.18, "yellow")
    p.decal((-3.80, 0.0, 1.86), "-x", 1.40, 0.70, "chassis")
    for k in range(5):
        p.decal((-3.80, 0.0, 1.60 + k * 0.13), "-x", 1.30, 0.045, "steel_dk", off=0.009)
    for s in (1, -1):
        p.lamp((-3.82, s * 0.92, 2.10), (-1, 0, 0), r=0.09, depth=0.08, square=True)
        ax = "+y" if s > 0 else "-y"
        p.decal((-2.55, s * 1.18, 1.86), ax, 1.80, 0.62, "chassis")
        for k in range(4):
            p.decal((-2.55, s * 1.18, 1.66 + k * 0.14), ax, 1.70, 0.045, "steel_dk", off=0.009)
        p.decal((-1.42, s * 1.18, 1.86), ax, 0.04, 0.90, "seam")
        p.decal((-3.10, s * 1.18, 2.36), ax, 0.40, 0.10, "plate")
    p.decal((-2.55, 0.0, 2.46), "+z", 1.60, 1.40, "chassis", off=0.006)
    for k in range(6):
        p.decal((-3.20 + k * 0.26, 0.0, 2.46), "+z", 0.09, 1.30, "steel_dk", off=0.012)
    p.cylinder((-1.70, -0.80, 2.46), (-1.70, -0.80, 2.90), 0.07, 6, "steel")
    # cab on the left, hose reel on the right
    x0, x1 = -1.25, 0.35
    yl, yr = 1.20, 0.02
    zw, zr = 1.80, 2.78
    p.box((x0, yr, DECK_Z), (x1, yl, zw), "yellow")
    p.box((x0 + 0.05, yr + 0.05, zw), (x1 - 0.05, yl - 0.05, zr - 0.08), "glass")
    for x in (x0, x1 - 0.10):
        for y in (yr, yl - 0.10):
            p.box((x, y, zw), (x + 0.10, y + 0.10, zr - 0.06), "yellow")
    p.box(((x0 + x1) / 2 - 0.05, yl - 0.10, zw), ((x0 + x1) / 2 + 0.05, yl, zr - 0.06), "yellow")
    p.box((x0 - 0.10, yr - 0.08, zr - 0.08), (x1 + 0.14, yl + 0.08, zr + 0.05), "yellow")
    p.box((x0 + 0.08, yr + 0.08, zr + 0.05), (x1 - 0.08, yl - 0.08, zr + 0.10), "yellow_dk")
    p.decal((x1 - 0.50, yl, 1.55), "+y", 0.04, 0.46, "seam")
    p.lamp((x1 + 0.16, 0.30, zr - 0.02), (1, 0, 0), r=0.08, depth=0.10)
    p.lamp((x1 + 0.16, 0.95, zr - 0.02), (1, 0, 0), r=0.08, depth=0.10)
    p.cylinder((-0.60, 0.95, zr + 0.10), (-0.60, 0.95, zr + 0.16), 0.10, 8, "chassis")
    p.lens.cylinder((-0.60, 0.95, zr + 0.16), (-0.60, 0.95, zr + 0.34), 0.08, 8, "lens", r1=0.055)
    for z in (0.62, 1.00):
        p.box((x1 - 0.70, 1.16, z), (x1 - 0.26, 1.36, z + 0.05), "steel")
    # hose reel: drum with dark hose wound on it, in a yellow cradle
    p.cylinder((-0.45, -1.10, 2.05), (-0.45, -0.10, 2.05), 0.62, 12, "yellow_dk")
    p.cylinder((-0.45, -1.00, 2.05), (-0.45, -0.20, 2.05), 0.66, 12, "hose", caps=False)
    for y in (-1.14, -0.06):
        p.box((-0.60, y - 0.04, DECK_Z), (-0.30, y + 0.04, 2.05), "yellow")
    # turret / boom base at the front
    p.prism_xz([(0.40, DECK_Z - 0.30), (2.50, DECK_Z - 0.30), (2.70, 1.20), (2.70, 1.72), (2.40, 1.92),
                (0.40, 1.92)], -0.95, 0.95, "yellow")
    p.decal((1.50, 0.95, 1.50), "+y", 1.6, 0.04, "seam")
    p.decal((1.50, -0.95, 1.50), "-y", 1.6, 0.04, "seam")
    p.box((2.66, -1.00, 0.56), (2.84, 1.00, 0.86), "chassis")


def jacks(p):
    """Four stabiliser jacks, down on the floor (drilling pose)."""
    for x in (2.30, -3.45):
        for s in (1, -1):
            y0, y1 = sorted((s * 1.02, s * 1.52))
            p.box((x - 0.18, y0, 0.98), (x + 0.18, y1, 1.22), "yellow")
            p.box((x - 0.12, s * 1.40 - 0.12, 0.24), (x + 0.12, s * 1.40 + 0.12, 1.22), "yellow_dk")
            p.cylinder((x, s * 1.40, 0.24), (x, s * 1.40, 0.04), 0.07, 6, "steel")
            p.box((x - 0.24, s * 1.40 - 0.24, 0.0), (x + 0.24, s * 1.40 + 0.24, 0.07), "chassis")


def booms(p):
    for s in (1, -1):
        base = Vector((2.30, s * 0.48, 1.62))
        elbow = Vector((5.10, s * 0.92, 2.32))
        # boom: yellow box beam, a dark wrist at the end, lift cylinder below
        beam(p, base, elbow, 0.30, 0.34, "yellow")
        p.cylinder((base.x, base.y - 0.24, base.z), (base.x, base.y + 0.24, base.z), 0.20, 8, "chassis")
        p.hydraulic((1.40, s * 0.48, 1.20), (3.70, s * 0.70, 1.86), 0.11, 0.55)
        p.box((elbow.x - 0.20, elbow.y - 0.22, elbow.z - 0.24), (elbow.x + 0.22, elbow.y + 0.22, elbow.z + 0.22), "chassis")
        # feed: black beam along the drilling direction, cradle and rock drill in yellow
        f0 = Vector((4.70, s * 1.00, 2.00))
        f1 = Vector((10.20, s * 1.12, 2.30))
        beam(p, f0, f1, 0.22, 0.24, "steel_dk")
        dirf = (f1 - f0).normalized()
        for t in (0.10, 0.62):
            c = f0 + dirf * (f1 - f0).length * t
            beam(p, c - dirf * 0.22, c + dirf * 0.22, 0.34, 0.40, "yellow")
        rd = f0 + dirf * 1.40 + Vector((0, 0, 0.20))
        beam(p, rd - dirf * 0.40, rd + dirf * 0.40, 0.30, 0.30, "yellow_dk")
        p.cylinder(rd + dirf * 0.40, f1 + dirf * 0.25 + Vector((0, 0, 0.20)), 0.04, 5, "steel")
        p.box((f1.x - 0.12, f1.y - 0.15, f1.z - 0.10), (f1.x + 0.14, f1.y + 0.15, f1.z + 0.28), "chassis")
        # work lamp on the boom wrist
        p.lamp((elbow.x + 0.28, elbow.y, elbow.z + 0.34), (1, 0, 0), r=0.08, depth=0.10)
        p.box((elbow.x + 0.04, elbow.y - 0.04, elbow.z + 0.20), (elbow.x + 0.12, elbow.y + 0.04, elbow.z + 0.34), "chassis")
        # hoses hanging in loops from the feed to the turret
        p.tube([(rd.x - 0.2, rd.y, rd.z), (3.60, s * 1.10, 0.70), (2.20, s * 0.80, 1.80)], 0.055, 5, 10)
        p.tube([(rd.x + 0.3, rd.y + s * 0.10, rd.z), (4.20, s * 1.25, 0.95), (2.40, s * 0.95, 1.85)], 0.05, 5, 10)


def main():
    S.reset_scene(NAME)
    S.setup_cycles(64)
    mats = S.Palette()
    lamps = S.Part("LAMPS", mats)
    body = S.Part("drill_body", mats, lens=lamps)
    carrier(body)
    jacks(body)
    booms(body)
    wheel = S.build_wheel(mats, "drill_wheel", TYRE_R, TYRE_W, RIM_R, segments=14, lug=LUG)
    wheels = [("FL", AX_F, WHEEL_Y), ("FR", AX_F, -WHEEL_Y),
              ("RL", AX_R, WHEEL_Y), ("RR", AX_R, -WHEEL_Y)]
    S.build_machine(NAME, "two-boom face drilling rig (drill jumbo), drilling pose (decoration)", body, lamps,
                    wheel, wheels, WHEEL_Z, TYRE_W / 2, hull_skip=("hose", "steel"), shadow_pad=(1.0, 1.15),
                    extra={"booms": "forward (+X), fixed in the drilling pose; jacks down"})
    S.log("done")


main()
