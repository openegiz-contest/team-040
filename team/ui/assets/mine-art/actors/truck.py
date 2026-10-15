"""
truck.py - the 6-wheel underground dump truck actor of the mine art.

Builds team/ui/public/models/mine-art/actors/truck.glb (SPEC section 6):
    truck (root, origin on the ground at the centre of the footprint, facing +X, extras)
      truck_body    tractor with cab and front grille, articulation, dump box with a
                    heap of ore, hoist cylinders, tandem bogie: one mesh, baked texture
      WHEELS        WHEEL_FL, WHEEL_FR (tractor), WHEEL_ML, WHEEL_MR, WHEEL_RL, WHEEL_RR
      LAMPS         headlights, roof lamps, rear lamps, beacon (flat emissive colour)
      SHADOW        soft contact shadow (vertex alpha, BLEND)
Shape after the art references (an articulated hauler, cab front-left, box heaped
with rock), about 40 t class, real metres (length ~10.8 m), scaled 1.5x to scene metres.

Run (background Blender only):
    "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" --background --factory-startup
        --python team/ui/assets/mine-art/actors/truck.py [-- --no-render] [-- --samples N]
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import actors_style as S  # noqa: E402

NAME = "truck"
AX_F, AX_M, AX_R = 3.45, -1.45, -3.30
TYRE_R = 0.80
LUG = 0.10
WHEEL_Z = TYRE_R * (1 + LUG)          # 0.88
WHEEL_Y = 1.10
TYRE_W = 0.68
RIM_R = 0.42
FENDER_R = WHEEL_Z + 0.14
BOX_Z0, BOX_Z1 = 1.92, 2.92


def tractor(p):
    # frame and articulation
    p.box((1.95, -0.56, 0.56), (4.70, 0.56, 1.14), "chassis")
    p.prism_xz([(1.40, 0.62), (2.00, 0.62), (2.00, 1.12), (1.40, 1.12)], -0.32, 0.32, "chassis")
    p.cylinder((1.70, 0.0, 0.50), (1.70, 0.0, 1.22), 0.09, 8, "steel")
    # engine block, full width, with a rounded nose
    p.prism_xz([(2.30, 0.98), (4.82, 0.98), (5.02, 1.16), (5.02, 1.70), (4.84, 1.86), (2.30, 1.86)],
               -1.30, 1.30, "yellow")
    # front grille and lamps
    p.decal((5.02, 0.0, 1.38), "+x", 1.10, 0.62, "chassis")
    for k in range(5):
        p.decal((5.02, 0.0, 1.14 + k * 0.12), "+x", 1.02, 0.04, "steel_dk", off=0.009)
    for s in (1, -1):
        p.box((4.96, s * 0.98 - 0.20, 1.24), (5.04, s * 0.98 + 0.20, 1.62), "chassis")
        p.lamp((5.08, s * 0.98, 1.43), (1, 0, 0), r=0.13, depth=0.08, square=True)
    p.box((4.96, -1.26, 0.62), (5.16, 1.26, 0.98), "chassis")
    p.decal((5.16, 0.0, 0.80), "+x", 0.50, 0.14, "plate")
    # front fenders
    for s in (1, -1):
        y0, y1 = sorted((s * 0.76, s * 1.48))
        p.strip_xz(S.arc(AX_F, WHEEL_Z, FENDER_R, 176, 30, 6), 0.09, y0, y1, "yellow")
        y0, y1 = sorted((s * 0.60, s * 0.78))
        p.box((AX_F - 0.90, y0, 1.00), (AX_F - 0.76, y1, 1.86), "chassis")
    # cab front-left on top of the engine block, big glass
    x0, x1 = 2.36, 3.92
    yl, yr = 1.30, -0.22
    zb, zw, zr = 1.86, 2.18, 3.02
    p.box((x0, yr, zb), (x1, yl, zw), "yellow")
    p.box((x0 + 0.05, yr + 0.05, zw), (x1 - 0.05, yl - 0.05, zr - 0.08), "glass")
    for x in (x0, x1 - 0.11):
        for y in (yr, yl - 0.11):
            p.box((x, y, zw), (x + 0.11, y + 0.11, zr - 0.06), "yellow")
    for y in (yl - 0.10, yr):
        p.box(((x0 + x1) / 2 - 0.05, y, zw), ((x0 + x1) / 2 + 0.05, y + 0.10, zr - 0.06), "yellow")
    p.box((x0 - 0.10, yr - 0.08, zr - 0.08), (x1 + 0.16, yl + 0.08, zr + 0.05), "yellow")
    p.box((x0 + 0.08, yr + 0.08, zr + 0.05), (x1 - 0.08, yl - 0.08, zr + 0.10), "yellow_dk")
    p.lamp((x1 + 0.18, 0.10, zr - 0.02), (1, 0, 0), r=0.08, depth=0.10)
    p.lamp((x1 + 0.18, 0.95, zr - 0.02), (1, 0, 0), r=0.08, depth=0.10)
    p.cylinder((2.80, 0.95, zr + 0.10), (2.80, 0.95, zr + 0.16), 0.10, 8, "chassis")
    p.lens.cylinder((2.80, 0.95, zr + 0.16), (2.80, 0.95, zr + 0.34), 0.08, 8, "lens", r1=0.055)
    # right of the cab: hood top with air cleaner and exhaust
    p.box((2.30, -1.28, 1.86), (4.40, yr, 2.04), "yellow_dk")
    p.decal((3.40, -0.76, 2.04), "+z", 1.4, 0.8, "chassis", off=0.006)
    for k in range(5):
        p.decal((2.84 + k * 0.28, -0.76, 2.04), "+z", 0.10, 0.74, "steel_dk", off=0.012)
    p.cylinder((2.55, -1.00, 2.04), (2.55, -1.00, 2.70), 0.08, 6, "steel")
    p.cylinder((4.00, -0.98, 2.04), (4.00, -0.98, 2.40), 0.15, 8, "chassis")
    # door seams, steps and handrails on the cab side
    for s, y in ((1, yl), (-1, -1.30)):
        ax = "+y" if s > 0 else "-y"
        p.decal((3.10, y, 1.42), ax, 1.8, 0.04, "seam")
        p.decal((4.30, s * 1.30, 1.42), ax, 0.30, 0.18, "chassis")
    for z in (0.80, 1.30):
        p.box((2.40, 1.22, z), (2.84, 1.46, z + 0.06), "steel")
    p.cylinder((2.36, 1.38, 1.40), (2.36, 1.38, 2.50), 0.03, 4, "steel")
    p.cylinder((2.36, 1.38, 2.50), (2.90, 1.38, 2.50), 0.03, 4, "steel")
    # mirror
    p.cylinder((x1, yl, 2.50), (x1 + 0.26, yl + 0.22, 2.52), 0.03, 4, "chassis")
    p.box((x1 + 0.22, yl + 0.18, 2.24), (x1 + 0.28, yl + 0.36, 2.56), "chassis")


def trailer(p):
    # frame rails and the tandem bogie
    p.box((-4.62, -0.56, 0.58), (1.40, 0.56, 1.24), "chassis")
    for s in (1, -1):
        y0, y1 = sorted((s * 0.62, s * 0.84))
        p.box((AX_R - 0.40, y0, 0.60), (AX_M + 0.40, y1, 1.10), "chassis")
        # hoist cylinders from the frame to the box underside
        p.hydraulic((0.70, s * 0.72, 0.96), (0.30, s * 0.72, BOX_Z0 + 0.02), 0.11, 0.55)
        # rear lamps on the frame end
        p.lamp((-4.68, s * 0.40, 1.04), (-1, 0, 0), r=0.08, depth=0.08, square=True)
    p.box((-4.74, -0.62, 0.60), (-4.60, 0.62, 0.86), "chassis")
    # dump box: tapered tub, tail rising to the rear
    xb0, xb1 = -4.30, 1.70
    xt0, xt1 = -4.96, 1.76
    yb, yt = 1.20, 1.48
    p.hexa([(xb0, -yb, BOX_Z0), (xb1, -yb, BOX_Z0), (xb1, yb, BOX_Z0), (xb0, yb, BOX_Z0),
            (xt0, -yt, BOX_Z1), (xt1, -yt, BOX_Z1), (xt1, yt, BOX_Z1), (xt0, yt, BOX_Z1)], "yellow")
    # top rails, headboard, rear lip
    for s in (1, -1):
        y0, y1 = sorted((s * (yt - 0.10), s * (yt + 0.06)))
        p.box((xt0, y0, BOX_Z1 - 0.04), (xt1, y1, BOX_Z1 + 0.10), "yellow_dk")
        # side ribs following the tapered wall
        for k in range(5):
            x = xb0 + 0.55 + k * (xb1 - xb0 - 1.1) / 4
            yi, yo = s * yb, s * yt
            wi, wo = s * (yb + 0.08), s * (yt + 0.07)
            p.hexa([(x - 0.06, yi, BOX_Z0), (x + 0.06, yi, BOX_Z0), (x + 0.06, wi, BOX_Z0), (x - 0.06, wi, BOX_Z0),
                    (x - 0.06, yo, BOX_Z1 - 0.04), (x + 0.06, yo, BOX_Z1 - 0.04),
                    (x + 0.06, wo, BOX_Z1 - 0.04), (x - 0.06, wo, BOX_Z1 - 0.04)], "yellow_dk")
        # a long painted panel line and a light plate on each side
        ax = "+y" if s > 0 else "-y"
        p.decal((-1.30, s * 1.37, 2.50), ax, 4.6, 0.05, "seam")
        p.decal((0.90, s * 1.40, 2.66), ax, 0.60, 0.16, "plate")
    p.box((xt1 - 0.20, -yt - 0.06, BOX_Z1 - 0.04), (xt1 + 0.10, yt + 0.06, BOX_Z1 + 0.40), "yellow")
    p.box((xt1 - 0.08, -yt + 0.10, BOX_Z1 + 0.40), (xt1 + 0.24, yt - 0.10, BOX_Z1 + 0.48), "yellow_dk")
    p.box((xt0 - 0.06, -yt, BOX_Z1 - 0.04), (xt0 + 0.16, yt, BOX_Z1 + 0.08), "yellow_dk")
    heap(p, xt0 + 0.30, xt1 - 0.30, yt - 0.18)


def heap(p, x0, x1, hw):
    """Rock heap above the rim: a faceted mound plus individual rocks on it (deterministic)."""
    bm = p.bm
    nx, ny = 10, 6
    cx, L = (x0 + x1) / 2, (x1 - x0) / 2
    rnd = S._Rand(31)

    def height(x, y):
        u, v = (x - cx) / L, y / hw
        return BOX_Z1 + 0.04 + 0.58 * max(0.0, 1.0 - 0.7 * u * u - 0.8 * v * v)

    rows = []
    for i in range(nx + 1):
        x = x0 + (x1 - x0) * i / nx
        row = []
        for j in range(ny + 1):
            y = -hw + 2 * hw * j / ny
            inner = 0 < i < nx and 0 < j < ny
            row.append(bm.verts.new((x, y, height(x, y) + (0.10 * rnd.next() if inner else 0.0))))
        rows.append(row)
    for i in range(nx):
        for j in range(ny):
            slot = ("rock_dk", "rock", "rock_dk", "ore", "rock_dk")[(i * 2 + j * 3) % 5]
            p.face((rows[i][j], rows[i + 1][j], rows[i + 1][j + 1], rows[i][j + 1]), slot, loose=True)
    k = 0
    for i in range(9):
        for j in range(4):
            x = x0 + 0.30 + (x1 - x0 - 0.6) * (i + 0.5 * (j % 2)) / 9
            y = -hw + 0.30 + (2 * hw - 0.6) * j / 3
            if abs(x - cx) / L > 0.97:
                continue
            r = 0.20 + 0.13 * rnd.next()
            z = height(x, y) + r * 0.35
            slot = ("rock", "rock", "rock_dk", "ore", "rock")[(i * 3 + j) % 5]
            p.rock((x + 0.18 * (rnd.next() - 0.5), y + 0.18 * (rnd.next() - 0.5), z), r, 200 + k, slot, squash=0.75)
            k += 1


def main():
    S.reset_scene(NAME)
    S.setup_cycles(64)
    mats = S.Palette()
    lamps = S.Part("LAMPS", mats)
    body = S.Part("truck_body", mats, lens=lamps)
    tractor(body)
    trailer(body)
    wheel = S.build_wheel(mats, "truck_wheel", TYRE_R, TYRE_W, RIM_R, segments=14, lug=LUG)
    wheels = [("FL", AX_F, WHEEL_Y), ("FR", AX_F, -WHEEL_Y),
              ("ML", AX_M, WHEEL_Y), ("MR", AX_M, -WHEEL_Y),
              ("RL", AX_R, WHEEL_Y), ("RR", AX_R, -WHEEL_Y)]
    S.build_machine(NAME, "underground dump truck, 6 wheels, loaded (decoration)", body, lamps, wheel,
                    wheels, WHEEL_Z, TYRE_W / 2, hull_skip=("rock", "rock_dk", "ore"),
                    extra={"load": "heaped ore in the box (static)"})
    S.log("done")


main()
