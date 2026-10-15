"""
lhd.py - the articulated underground loader (LHD, "ПДМ") actor of the mine art.

Builds team/ui/public/models/mine-art/actors/lhd.glb (SPEC section 6):
    lhd (root, origin on the ground at the centre of the footprint, facing +X, extras)
      lhd_body      frame, boom, bucket, cab, engine hood: one mesh, baked texture
      WHEELS        WHEEL_FL, WHEEL_FR, WHEEL_RL, WHEEL_RR (origin on the axle)
      LAMPS         head/rear lamp lenses and the roof beacon (flat emissive colour)
      SHADOW        soft contact shadow (vertex alpha, BLEND)
Geometry follows team/ui/assets/blender/lhd_v2.py (10 t class, real metres, pin of the
articulation at x = 0), restyled after the art references: chunkier proportions (big
tyres, tall boxy hood, central cab with large glass), yellow paint, painted grilles and
panel lines; then scaled 1.5x to scene metres (SPEC section 3).

Run (background Blender only):
    "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" --background --factory-startup
        --python team/ui/assets/mine-art/actors/lhd.py [-- --no-render] [-- --samples N]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import actors_style as S  # noqa: E402

NAME = "lhd"
AXLE_F, AXLE_R = 1.85, -1.85
TYRE_R = 0.88
LUG = 0.10
WHEEL_Z = TYRE_R * (1 + LUG)          # 0.968
WHEEL_Y = 1.10
TYRE_W = 0.74
RIM_R = 0.46
FENDER_R = WHEEL_Z + 0.15
DECK_Z = 1.86
HOOD_Z = 2.36


def front_unit(p):
    # frame: chamfered box between the front tyres
    p.prism_xz([(0.34, 0.52), (2.80, 0.52), (3.16, 0.72), (3.16, 1.10), (2.94, 1.28),
                (1.40, 1.28), (0.34, 1.22)], -0.60, 0.60, "yellow")
    # boom tower
    p.prism_xz([(0.30, 1.18), (1.50, 1.18), (1.36, 1.66), (1.08, 2.24), (0.52, 2.32),
                (0.30, 2.06)], -0.56, 0.56, "yellow")
    for s in (1, -1):
        ax = "+y" if s > 0 else "-y"
        p.decal((0.90, s * 0.56, 1.70), ax, 0.70, 0.05, "seam")
        # fenders over the front tyres: arched plates with a flat lamp shelf
        y0, y1 = sorted((s * 0.70, s * 1.50))
        p.strip_xz(S.arc(AXLE_F, WHEEL_Z, FENDER_R, 172, 14, 6), 0.09, y0, y1, "yellow")
        y0, y1 = sorted((s * 0.56, s * 0.74))
        p.box((AXLE_F - 0.92, y0, 1.02), (AXLE_F - 0.76, y1, 1.92), "chassis")
        # lamp pod on the front of the fender
        yc = s * 1.16
        p.box((2.40, yc - 0.20, 1.86), (2.78, yc + 0.20, 2.10), "yellow_dk")
        p.lamp((2.84, yc, 1.98), (1, 0, 0), r=0.12, depth=0.12, square=True)
        # front corner guard
        y0, y1 = sorted((s * 0.30, s * 0.60))
        p.box((3.06, y0, 0.58), (3.22, y1, 0.86), "steel")
        # steering-cylinder lug
        y0, y1 = sorted((s * 0.50, s * 0.72))
        p.box((0.36, y0, 0.74), (0.62, y1, 1.00), "chassis")
    p.box((0.42, -0.54, 0.44), (2.90, 0.54, 0.52), "chassis")
    p.box((3.10, -0.68, 0.48), (3.24, 0.68, 0.66), "chassis")
    for z0 in (0.46, 1.04):
        p.prism_xz([(0.36, z0), (0.36, z0 + 0.12), (-0.10, z0 + 0.12), (-0.20, z0 + 0.06), (-0.10, z0)],
                   -0.30, 0.30, "chassis")


def boom(p):
    pivot, knee1, knee2, pin = (0.86, 2.06), (2.42, 1.84), (3.08, 1.24), (3.46, 0.66)
    for s in (1, -1):
        y0, y1 = sorted((s * 0.42, s * 0.64))
        p.strip_xz([pivot, knee1, knee2, pin], 0.40, y0, y1, "yellow")
        y0, y1 = sorted((s * 0.64, s * 0.67))
        p.strip_xz([(1.10, 2.02), knee1, (2.96, 1.30)], 0.14, y0, y1, "yellow_dk")
        p.cylinder((pivot[0], s * 0.36, pivot[1]), (pivot[0], s * 0.70, pivot[1]), 0.19, 8, "chassis")
        p.cylinder((pin[0], s * 0.36, pin[1]), (pin[0], s * 0.70, pin[1]), 0.15, 8, "chassis")
        y0, y1 = sorted((s * 0.62, s * 0.80))
        p.prism_xz([(2.12, 1.74), (2.50, 1.74), (2.42, 1.52), (2.22, 1.46)], y0, y1, "yellow")
        p.hydraulic((1.40, s * 0.71, 0.86), (2.31, s * 0.71, 1.56), 0.12, 0.58)
        p.tube([(0.70, s * 0.30, 2.22), (1.30, s * 0.72, 2.52), (2.00, s * 0.70, 2.04)], 0.04, 5, 6)
        p.tube([(0.50, s * 0.40, 1.30), (0.90, s * 0.80, 1.20), (1.36, s * 0.74, 0.92)], 0.04, 5, 5)
    p.cylinder((2.50, -0.64, 1.76), (2.50, 0.64, 1.76), 0.13, 8, "yellow")
    for y in (0.07, -0.07):
        y0, y1 = sorted((y, y + (0.09 if y > 0 else -0.09)))
        p.strip_xz([(2.30, 2.48), (2.50, 1.76), (2.72, 1.16)], 0.28, y0, y1, "yellow")
    p.cylinder((2.30, -0.20, 2.48), (2.30, 0.20, 2.48), 0.10, 8, "chassis")
    p.strip_xz([(2.72, 1.16), (3.40, 1.10)], 0.18, -0.08, 0.08, "yellow_dk")
    # tilt cylinder: tower top -> bellcrank top (the big one in the reference)
    p.hydraulic((0.74, 0.0, 2.40), (2.30, 0.0, 2.48), 0.17, 0.56, sides=10)
    p.box((0.58, -0.19, 2.26), (0.94, 0.19, 2.48), "chassis")


def bucket(p):
    """Bucket 2.9 m wide, lowered and level, a few rocks left inside."""
    lip = 5.02
    heel = S.arc(3.98, 0.56, 0.50, 270, 180, 4)
    shell = [(4.56, 0.07)] + heel + [(3.48, 1.02), (3.56, 1.34), (4.26, 1.46)]
    p.strip_xz(shell, 0.08, -1.38, 1.38, "yellow")
    outline = ([(lip + 0.02, 0.03), (lip - 0.01, 0.36), (4.28, 1.50), (3.52, 1.40), (3.40, 1.00)]
               + [(x - 0.04, z) for x, z in reversed(heel)][1:] + [(3.98, 0.02)])
    for y0, y1 in S.sides_of(1.37, 1.46):
        p.prism_xz(outline, y0, y1, "yellow")
    for y0, y1 in S.sides_of(1.46, 1.48):
        p.prism_xz([(5.04, 0.03), (5.02, 0.34), (4.62, 0.72), (4.36, 0.72), (4.36, 0.03)], y0, y1, "yellow_dk")
    p.prism_xz([(4.52, 0.035), (5.06, 0.035), (5.06, 0.08), (4.90, 0.14), (4.52, 0.14)], -1.39, 1.39, "steel")
    p.box((3.48, -1.38, 1.34), (3.72, 1.38, 1.50), "yellow_dk")
    for y in (-0.90, 0.0, 0.90):
        p.prism_xz([(3.54, 1.32), (4.10, 1.42), (3.54, 1.60)], y - 0.04, y + 0.04, "yellow")
    for y0, y1 in S.sides_of(0.38, 0.66):
        p.prism_xz([(3.26, 0.50), (3.34, 0.38), (3.50, 0.34), (3.50, 0.84), (3.34, 0.80)], y0, y1, "chassis")
    for k, (x, y, z, r) in enumerate(((4.20, -0.70, 0.34, 0.26), (4.40, 0.15, 0.28, 0.22),
                                      (4.05, 0.85, 0.40, 0.24), (4.62, -0.10, 0.20, 0.16))):
        p.rock((x, y, z), r, 11 + k, ("rock", "rock_dk", "ore", "rock")[k])


def rear_unit(p):
    p.prism_xz([(-0.34, 0.60), (0.06, 0.60), (0.14, 0.68), (0.14, 1.00), (0.06, 1.06), (-0.34, 1.06)],
               -0.26, 0.26, "chassis")
    p.cylinder((0.0, 0.0, 0.42), (0.0, 0.0, 1.20), 0.09, 8, "steel")
    p.box((-2.80, -0.66, 0.52), (-0.30, 0.66, DECK_Z - 0.08), "chassis")
    p.box((-2.86, -1.46, DECK_Z - 0.10), (-0.96, 1.46, DECK_Z), "yellow_dk")
    # engine bay + hood: one tall box, chamfered at the back, crown on top
    p.prism_xz([(-2.70, 0.54), (-4.86, 0.54), (-5.06, 0.76), (-5.06, DECK_Z), (-2.70, DECK_Z)],
               -1.40, 1.40, "yellow")
    p.prism_xz([(-1.84, DECK_Z - 0.02), (-1.84, HOOD_Z - 0.10), (-2.02, HOOD_Z), (-4.50, HOOD_Z),
                (-5.06, HOOD_Z - 0.22), (-5.06, DECK_Z - 0.02)], -1.32, 1.32, "yellow")
    # rear face: big black grille between two round lamps
    p.decal((-5.06, 0.0, 1.46), "-x", 1.10, 1.10, "chassis")
    for k in range(6):
        p.decal((-5.06, 0.0, 1.00 + k * 0.18), "-x", 1.00, 0.05, "steel_dk", off=0.009)
    for s in (1, -1):
        p.lamp((-5.08, s * 0.98, 1.86), (-1, 0, 0), r=0.13, depth=0.10)
        p.lamp((-5.08, s * 0.98, 1.50), (-1, 0, 0), r=0.09, depth=0.08)
    p.box((-5.14, -1.30, 0.60), (-5.04, 1.30, 0.84), "chassis")
    # hydraulic tank on the right beside the cab
    p.prism_xz([(-0.30, 0.56), (-0.30, 1.62), (-0.56, 1.98), (-0.96, 2.04), (-0.96, 0.56)],
               -1.42, -0.52, "yellow")
    p.decal((-0.64, -1.42, 1.30), "-y", 0.42, 0.30, "plate")
    for y0, y1 in S.sides_of(0.72, 1.48):
        p.strip_xz(S.arc(AXLE_R, WHEEL_Z, FENDER_R, 162, 126, 2), 0.09, y0, y1, "yellow")
        p.strip_xz(S.arc(AXLE_R, WHEEL_Z, FENDER_R, 54, 18, 2), 0.09, y0, y1, "yellow")
    for s in (1, -1):
        p.hydraulic((-0.52, s * 0.62, 0.88), (0.50, s * 0.62, 0.88), 0.09, 0.55)
        y_face = s * 1.40
        ax = "+y" if s > 0 else "-y"
        # side grille of the engine bay: dark panel with lighter louvres
        p.decal((-3.95, y_face, 1.28), ax, 1.70, 0.74, "chassis")
        for k in range(5):
            p.decal((-3.95, y_face, 1.00 + k * 0.14), ax, 1.60, 0.045, "steel_dk", off=0.009)
        for xd in (-2.92, -4.92):
            p.decal((xd, y_face, 1.20), ax, 0.04, 1.14, "seam")
        p.decal((-3.95, s * 1.32, 2.12), ax, 2.2, 0.04, "seam")
        p.decal((-2.30, y_face, 1.60), ax, 0.20, 0.10, "plate")
        y0, y1 = sorted((s * 1.30, s * 1.52))
        p.box((-4.86, y0, 0.60), (-4.36, y1, 0.66), "steel")
        y0, y1 = sorted((s * 0.62, s * 0.80))
        p.box((AXLE_R + 0.74, y0, 1.14), (AXLE_R + 0.90, y1, DECK_Z), "chassis")
    # top grille on the hood: dark panel and slats (painted)
    p.decal((-3.70, 0.0, HOOD_Z), "+z", 1.50, 1.70, "chassis", off=0.006)
    for k in range(7):
        p.decal((-4.34 + k * 0.215, 0.0, HOOD_Z), "+z", 0.08, 1.60, "steel_dk", off=0.012)
    p.cylinder((-2.20, -0.86, HOOD_Z), (-2.20, -0.86, HOOD_Z + 0.26), 0.14, 8, "chassis")
    p.cylinder((-2.20, -0.86, HOOD_Z + 0.26), (-2.20, -0.86, HOOD_Z + 0.32), 0.18, 8, "chassis", r1=0.12)
    p.cylinder((-4.62, -0.90, HOOD_Z - 0.1), (-4.62, -0.90, HOOD_Z + 0.16), 0.15, 8, "steel")
    p.cylinder((-4.62, -0.90, HOOD_Z + 0.16), (-4.62, -0.90, HOOD_Z + 0.40), 0.065, 6, "steel")


def cab(p):
    """Enclosed ROPS/FOPS cab across the middle-left of the rear frame, big glass."""
    x0, x1 = -1.78, -0.28
    yl, yr = 1.42, -0.46
    zw, zr = 1.92, 2.78
    p.box((x0, yr, DECK_Z - 0.32), (x1, yl, zw), "yellow")
    p.box((x1 - 0.70, yr + 0.34, 1.10), (x1, yl, DECK_Z - 0.32), "yellow")
    p.box((x0 + 0.05, yr + 0.05, zw), (x1 - 0.05, yl - 0.05, zr - 0.08), "glass")
    for x in (x0, x1 - 0.11):
        for y in (yr, yl - 0.11):
            p.box((x, y, zw), (x + 0.11, y + 0.11, zr - 0.06), "yellow")
    for s, y in ((1, yl - 0.10), (-1, yr)):
        p.box(((x0 + x1) / 2 - 0.05, y, zw), ((x0 + x1) / 2 + 0.05, y + 0.10, zr - 0.06), "yellow")
    p.box((x1 - 0.10, (yl + yr) / 2 - 0.05, zw), (x1, (yl + yr) / 2 + 0.05, zr - 0.06), "yellow")
    p.box((x0 - 0.12, yr - 0.10, zr - 0.08), (x1 + 0.14, yl + 0.10, zr + 0.05), "yellow")
    p.box((x0 + 0.06, yr + 0.08, zr + 0.05), (x1 - 0.06, yl - 0.08, zr + 0.10), "yellow_dk")
    for s, y in ((1, yl), (-1, yr)):
        ax = "+y" if s > 0 else "-y"
        p.decal((x1 - 0.40, y, (DECK_Z - 0.32 + zw) / 2), ax, 0.04, zw - DECK_Z + 0.30, "seam")
        p.decal((x1 - 0.64, y, zw - 0.12), ax, 0.16, 0.04, "chassis")
    for y in (-0.10, 1.00):
        p.lamp((x1 + 0.16, y, zr - 0.02), (1, 0, 0), r=0.08, depth=0.10)
    p.lamp((x0 - 0.16, 0.48, zr - 0.02), (-1, 0, 0), r=0.08, depth=0.10)
    p.cylinder((-1.10, 1.06, zr + 0.10), (-1.10, 1.06, zr + 0.16), 0.10, 8, "chassis")
    p.lens.cylinder((-1.10, 1.06, zr + 0.16), (-1.10, 1.06, zr + 0.34), 0.08, 8, "lens", r1=0.055)
    p.cylinder((x1, yl, 2.30), (x1 + 0.24, yl + 0.24, 2.32), 0.03, 4, "chassis")
    p.box((x1 + 0.20, yl + 0.20, 2.06), (x1 + 0.26, yl + 0.38, 2.36), "chassis")
    for s, y in ((1, yl), (-1, yr)):
        for z in (0.70, 1.12):
            y0, y1 = sorted((y - s * 0.12, y + s * 0.10))
            p.box((x1 - 0.64, y0, z), (x1 - 0.18, y1, z + 0.06), "steel")
        p.cylinder((x1 + 0.04, y + s * 0.06, 1.50), (x1 + 0.04, y + s * 0.06, 2.30), 0.03, 4, "steel")


def main():
    S.reset_scene(NAME)
    S.setup_cycles(64)
    mats = S.Palette()
    lamps = S.Part("LAMPS", mats)
    body = S.Part("lhd_body", mats, lens=lamps)
    front_unit(body)
    boom(body)
    bucket(body)
    rear_unit(body)
    cab(body)
    wheel = S.build_wheel(mats, "lhd_wheel", TYRE_R, TYRE_W, RIM_R, segments=16, lug=LUG)
    wheels = [("FL", AXLE_F, WHEEL_Y), ("FR", AXLE_F, -WHEEL_Y),
              ("RL", AXLE_R, WHEEL_Y), ("RR", AXLE_R, -WHEEL_Y)]
    S.build_machine(NAME, "LHD loader, 10 t class (decoration)", body, lamps, wheel, wheels, WHEEL_Z, TYRE_W / 2,
                    extra={"bucket": "front (+X), lowered"})
    S.log("done")


main()
