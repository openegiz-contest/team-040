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

# Overview frame in screen metres (orthographic, relative to the world origin).
FRAME_W = 924.0
ASPECT = 16.0 / 9.0
# Projected textures, 2048 px square each, windows in screen metres of MainView.
TEX_SIZE = 2048
NEAR_WIN = None     # (centre sx, centre sy, side): both zone faces, for the 3x zoom; set by frame()
# The far texture is an atlas (set by frame()): a main block 980 m x 712 m (rows 0..1487,
# 0.4785 m/texel) covering every 1x stage from 16:9 to 4:3 (taller stages show more top and
# bottom), and two side wings 136 m x 540 m (rows 1492..1767 and 1772..2047, stored rotated:
# screen x along the rows at 0.493 m/texel, screen y along the columns at 0.264 m/texel)
# that a stage wider than 16:9 (up to 21:9) shows left and right of it.
FAR_MAIN = None     # (left, bottom, width, height)
FAR_WINGS = None    # [(left, bottom, width, height) west, east]
MAIN_W, MAIN_H = 980.0, 712.0
MAIN_ROWS = 1488
WING_W, WING_H = 136.0, 540.0
WING_ROWS = 276
WING_ROW0 = (1492, 1772)
WING_SPLIT = 487.0  # |sx - frame centre| where the main block hands over to a wing


def log(*a):
    print("[env]", time.strftime("%H:%M:%S"), *a, flush=True)


def frame(mine):
    """Frame centre (sx, sy) from the screen bounds of all workings, plus windows."""
    global NEAR_WIN, FAR_MAIN, FAR_WINGS
    xs, ys = [], []
    for w in mine.workings.values():
        for p in w["pts"]:
            sx, sy = mine_map.to_screen(p)
            xs.append(sx)
            ys.append(sy)
    cx = (min(xs) + max(xs)) / 2.0
    # vertical: 50 m above the highest working point (the portal B road end) holds the
    # gantries, lamp rooms and masts; the rest of the 16:9 height goes below the faces
    top = max(ys) + 50.0
    bottom = top - FRAME_W / ASPECT
    cy = (bottom + top) / 2.0
    fa = mine_map.to_screen(mine.nodes["face-a"])
    fb = mine_map.to_screen(mine.nodes["face-b"])
    side = 320.0
    ncx = (fa[0] + fb[0]) / 2.0 + 8.0
    ncy = max(bottom + side / 2.0, (fa[1] + fb[1]) / 2.0)
    NEAR_WIN = (ncx, ncy, side)
    FAR_MAIN = (cx - MAIN_W / 2.0, cy - MAIN_H / 2.0, MAIN_W, MAIN_H)
    FAR_WINGS = [(cx - 620.0, cy - WING_H / 2.0, WING_W, WING_H),
                 (cx + 620.0 - WING_W, cy - WING_H / 2.0, WING_W, WING_H)]
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
    w = FRAME_W / zoom if side is None else side
    if centre is not None:
        sx, sy = centre
    elif focus is not None:
        sx, sy = mine_map.to_screen(focus)
        hw, hh = (FRAME_W - w) / 2.0, (FRAME_W / ASPECT - w / ASPECT) / 2.0
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
