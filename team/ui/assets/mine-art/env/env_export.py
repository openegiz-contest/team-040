"""Camera, renders, camera-projected textures and the GLB export."""

import json
import math
import os
import struct
import time

import bpy
import bmesh
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

import mine_map

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build")
PREVIEWS = os.path.join(HERE, "previews")
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", ".."))
OUT_DIR = os.path.join(ROOT, "team", "ui", "public", "models", "mine-art")

# Overview frame in screen metres (orthographic, relative to the world origin): set by
# frame() from the screen bounds of the workings (16:9, height-bound).
FRAME_W = None
ASPECT = 16.0 / 9.0
TOP_MARGIN = 46.0       # above the highest working point (portal frames, lamp rooms)
BOTTOM_MARGIN = 40.0    # below the lowest working point (its floor in front of it)
SIDE_MARGIN = 60.0
STAGE = 1920            # stage width in pixels the texel rule is checked for
# Projected textures, 2048 px square each, windows in screen metres of MainView.
TEX_SIZE = 2048
NEAR_WIN = None     # (centre sx, centre sy, side): both zone faces, for the 3x zoom
# The far texture is an atlas (set by frame()): a main block covering every 1x stage from
# 16:9 to 4:3 (taller stages show more top and bottom) at >= 1 texel per pixel, and two
# side wings (stored rotated: screen x along the rows, screen y along the columns) that a
# stage wider than 16:9 (up to 21:9) shows left and right of it.
FAR_MAIN = None     # (left, bottom, width, height)
FAR_WINGS = None    # [(left, bottom, width, height) west, east]
MAIN_W = MAIN_H = None
MAIN_ROWS = None
WING_W = WING_H = None
WING_ROWS = None
WING_ROW0 = None
WING_SPLIT = None   # |sx - frame centre| where the main block hands over to a wing
GUTTER = 4


def log(*a):
    print("[env]", time.strftime("%H:%M:%S"), *a, flush=True)


def frame(mine):
    """Frame centre (sx, sy) and width from the screen bounds of all workings, plus the
    texture windows (far atlas blocks, near window)."""
    global NEAR_WIN, FAR_MAIN, FAR_WINGS, FRAME_W, MAIN_W, MAIN_H, MAIN_ROWS, WING_W, WING_H, WING_ROWS,         WING_ROW0, WING_SPLIT
    xs, ys = [], []
    for w in mine.workings.values():
        for p in w["pts"]:
            sx, sy = mine_map.to_screen(p)
            xs.append(sx)
            ys.append(sy)
    cx = (min(xs) + max(xs)) / 2.0
    top = max(ys) + TOP_MARGIN
    bottom = min(ys) - BOTTOM_MARGIN
    FRAME_W = math.ceil(max((top - bottom) * ASPECT, max(xs) - min(xs) + 2 * SIDE_MARGIN) / 2.0) * 2.0
    H = FRAME_W / ASPECT
    cy = (top + bottom) / 2.0
    # far atlas: main block at 1.006 texels per pixel on a 16:9 stage 1920 px wide
    MAIN_W = FRAME_W * 1.06
    tex_m = MAIN_W / TEX_SIZE
    MAIN_H = FRAME_W * 0.75 + 16.0                   # the 4:3 stage plus 8 m top and bottom
    MAIN_ROWS = int(math.ceil(MAIN_H / tex_m))
    MAIN_H = MAIN_ROWS * tex_m
    WING_SPLIT = MAIN_W / 2.0 - 4.0
    wide = H * 21.0 / 9.0                             # the 21:9 stage at 1x
    w_out = wide / 2.0 + 8.0
    WING_W = w_out - (WING_SPLIT - 4.0)
    WING_H = H + 16.0
    WING_ROWS = int(math.ceil(WING_W / (wide / STAGE) * 1.06))
    WING_ROW0 = (MAIN_ROWS + GUTTER, MAIN_ROWS + 2 * GUTTER + WING_ROWS)
    assert WING_ROW0[1] + WING_ROWS <= TEX_SIZE, ("atlas overflow", WING_ROW0, WING_ROWS)
    FAR_MAIN = (cx - MAIN_W / 2.0, cy - MAIN_H / 2.0, MAIN_W, MAIN_H)
    FAR_WINGS = [(cx - w_out, cy - WING_H / 2.0, WING_W, WING_H),
                 (cx + WING_SPLIT - 4.0, cy - WING_H / 2.0, WING_W, WING_H)]
    # near window: >= 1 texel per pixel at 3x on a 1920 px stage, between both zone views
    side = math.floor(TEX_SIZE * (FRAME_W / 3.0 / STAGE) / 1.01)
    foci = []
    for wid in ("w-07", "w-12"):
        w = mine.workings[wid]
        f = w["pts"][0].lerp(w["pts"][-1], 0.6)
        foci.append(mine_map.to_screen(f))
    ncx = (foci[0][0] + foci[1][0]) / 2.0 - 12.0
    ncy = (foci[0][1] + foci[1][1]) / 2.0
    NEAR_WIN = (ncx, ncy, float(side))
    return cx, cy, (min(xs), max(xs), min(ys), max(ys))


def main_camera(mine):
    back, right, up = (Vector(v) for v in mine_map.cam_basis())
    cx, cy, bounds = frame(mine)
    cam = bpy.data.cameras.new("MainView")
    cam.type = "ORTHO"
    cam.ortho_scale = FRAME_W
    cam.sensor_fit = "AUTO"
    cam.clip_start = 10.0
    cam.clip_end = 6000.0
    ob = bpy.data.objects.new("MainView", cam)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = right * cx + up * cy + back * 2500.0
    rot = Matrix((right, up, back)).transposed()
    ob.rotation_euler = rot.to_euler()
    ob["frame_centre"] = (cx, cy)
    ob["frame_w"] = FRAME_W
    sc = bpy.context.scene
    sc.render.resolution_x = 1920
    sc.render.resolution_y = 1080
    log("frame centre", round(cx, 1), round(cy, 1), "bounds", [round(b, 1) for b in bounds])
    return ob


def scene_extras(sc, topo):
    sc["mineArt"] = 1
    sc["k"] = mine_map.K
    sc["cx"] = topo["cx"]
    sc["cy"] = topo["cy"]
    sc["zTop"] = mine_map.ZTOP
    sc["topology"] = topo["topology"]
    sc["camera"] = "MainView"


def setup_cycles(samples, res, denoise=True):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.compute_device_type = "OPTIX"
        prefs.get_devices()
        for d in prefs.devices:
            d.use = d.type == "OPTIX"
        sc.cycles.device = "GPU"
    except Exception as e:  # pragma: no cover
        log("GPU unavailable, CPU", e)
        sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.02
    sc.cycles.use_denoising = denoise
    sc.cycles.max_bounces = 6
    sc.cycles.diffuse_bounces = 3
    sc.cycles.glossy_bounces = 1
    sc.cycles.transparent_max_bounces = 8
    sc.cycles.light_sampling_threshold = 0.005
    sc.cycles.pixel_filter_type = "BLACKMAN_HARRIS"
    sc.cycles.filter_width = 1.2
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    sc.view_settings.gamma = 1.0


def set_view(cam, zoom=1.0, focus=None, side=None, centre=None):
    """Place the orthographic camera: zoom relative to the overview, centred on a screen
    point (focus = Blender world point, clamped into the overview frame)."""
    back, right, up = (Vector(v) for v in mine_map.cam_basis())
    fcx, fcy = cam["frame_centre"]
    FW = FRAME_W or cam["frame_w"]
    w = FW / zoom if side is None else side
    if centre is not None:
        sx, sy = centre
    elif focus is not None:
        sx, sy = mine_map.to_screen(focus)
        hw, hh = (FW - w) / 2.0, (FW / ASPECT - w / ASPECT) / 2.0
        sx = min(max(sx, fcx - hw), fcx + hw)
        sy = min(max(sy, fcy - hh), fcy + hh)
    else:
        sx, sy = fcx, fcy
    cam.data.ortho_scale = w
    cam.location = right * sx + up * sy + back * 2500.0
    return sx, sy


def render_view(path, cam, zoom=1.0, focus=None, samples=128, res=(1920, 1080), centre=None,
                side=None):
    setup_cycles(samples, res)
    sc = bpy.context.scene
    old = (cam.data.ortho_scale, cam.location.copy())
    set_view(cam, zoom, focus, side, centre)
    sc.camera = cam
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.color_depth = "8"
    sc.render.image_settings.compression = 90
    sc.render.filepath = path
    t = time.time()
    bpy.ops.render.render(write_still=True)
    cam.data.ortho_scale, cam.location = old
    log("rendered", os.path.basename(path), f"{time.time() - t:.1f}s")
