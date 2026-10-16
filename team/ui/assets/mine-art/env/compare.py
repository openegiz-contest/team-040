"""Side-by-side comparison sheet: previous pass | this pass | reference (Blender, background).

  blender --background --factory-startup --python compare.py -- PREV_OVERVIEW PREV_ZONE_A REFERENCE

Row 1: the unlit 1x overviews (16:9) and the reference, all 600 px high.
Row 2: the unlit zone A views at 3x and the reference again, all 600 px high.
Writes previews/compare_prev_new_ref.png. The previous pass's images come from git
(git show c33b22f:team/ui/assets/mine-art/env/previews/unlit_overview.png etc.).
"""

import os
import sys

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PREVIEWS = os.path.join(HERE, "previews")
H = 600
GAP = 12


def load(path, h=H):
    img = bpy.data.images.load(path, check_existing=False)
    w0, h0 = img.size
    w = int(round(w0 * h / h0))
    img.scale(w, h)
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    bpy.data.images.remove(img)
    return a.reshape(h, w, 4)


def row(paths):
    tiles = [load(p) for p in paths]
    w = sum(t.shape[1] for t in tiles) + GAP * (len(tiles) - 1)
    out = np.zeros((H, w, 4), np.float32)
    out[..., 3] = 1.0
    x = 0
    for t in tiles:
        out[:, x:x + t.shape[1]] = t
        x += t.shape[1] + GAP
    return out


def main():
    prev_ov, prev_za, ref = sys.argv[sys.argv.index("--") + 1:][:3]
    r1 = row([prev_ov, os.path.join(PREVIEWS, "unlit_overview.png"), ref])
    r2 = row([prev_za, os.path.join(PREVIEWS, "unlit_zone_a_3x.png"), ref])
    w = max(r1.shape[1], r2.shape[1])
    sheet = np.zeros((2 * H + GAP, w, 4), np.float32)
    sheet[..., 3] = 1.0
    sheet[H + GAP:, :r1.shape[1]] = r1          # rows bottom-up in Blender pixel order
    sheet[:H, :r2.shape[1]] = r2
    img = bpy.data.images.new("compare", w, 2 * H + GAP)
    img.pixels.foreach_set(sheet.ravel())
    out = os.path.join(PREVIEWS, "compare_prev_new_ref.png")
    img.filepath_raw = out
    img.file_format = "PNG"
    img.save()
    print("wrote", out, w, "x", 2 * H + GAP)


main()
