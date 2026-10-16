"""Build the mine-art environment in Blender (background mode only).

  "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" --background --factory-startup \\
      --python build_env.py -- [--stage geo|full] [--samples N] [--quick]

Stages:
  geo   geometry + materials + lights, saves build/env_scene.blend and a quick preview
  full  geo + camera-projected texture renders + GLB export + previews (default)
Reads build/topology.json (run dump_topology.py first; rebuild.ps1 does both).
"""

import argparse
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import mine_map  # noqa: E402
import env_geom as G  # noqa: E402
import env_shading as SH  # noqa: E402
import env_props as P  # noqa: E402
import env_export as X  # noqa: E402
import env_pipeline as PL  # noqa: E402

BUILD = os.path.join(HERE, "build")
PREVIEWS = os.path.join(HERE, "previews")


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="full", choices=["geo", "full"])
    ap.add_argument("--no-previews", action="store_true")
    ap.add_argument("--no-textures", action="store_true")
    ap.add_argument("--samples", type=int, default=256)
    ap.add_argument("--quick", action="store_true", help="low samples, small preview")
    return ap.parse_args(argv)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    return sc


def coll(name, parent=None):
    c = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(c)
    return c


def log(*a):
    print("[env]", time.strftime("%H:%M:%S"), *a, flush=True)


def cut(target, cutters, name):
    c = coll("CUT_" + name)
    for o in cutters:
        for u in list(o.users_collection):
            u.objects.unlink(o)
        c.objects.link(o)
    log("boolean", target.name, len(cutters), "cutters")
    G.apply_boolean(target, c)
    if len(target.data.polygons) < 50:     # an exact boolean that failed returns an empty mesh
        raise SystemExit(f"[env] {target.name}: boolean result is empty")
    log("boolean done", target.name, len(target.data.polygons), "faces")
    for o in list(c.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.collections.remove(c)


def build_geometry(mine, mats):
    slope = G.EastSlope(mine)
    c_rock = coll("ROCK")
    c_tmp = coll("TMP")
    log("massif")
    block = G.massif_block(mine, slope, mats, c_rock)
    prom = G.promontory(mine, mats, c_rock)
    pen = G.peninsula(mine, mats, c_rock)
    log("cutters")
    slots = G.slot_cutters(mine, slope, mats, c_tmp)
    by_wid = {}
    for s_, ob in zip(mine.segments, slots):
        by_wid.setdefault(s_["wid"], []).append(ob)

    def copies(obs):
        out = []
        for o in obs:
            cp = o.copy()
            cp.data = o.data.copy()
            c_tmp.objects.link(cp)
            out.append(cp)
        return out
    prom_cut = copies(by_wid["w-03"] + by_wid["w-04"]) + G.zone_cutters(mine, "w-07", mine.z120, mats, c_tmp)
    pen_cut = copies(by_wid["w-10"] + by_wid["w-11"]) + G.zone_cutters(mine, "w-12", mine.z240, mats, c_tmp)
    block_cut = (G.air_cutters(mine, slope, mats, c_tmp) + [G.bay_cutter(mine, mats, c_tmp)] + slots +
                 G.crosscut_cutters(mine, mats, c_tmp) + [G.ramp_trench_cutter(mine, slope, mats, c_tmp)] +
                 G.pocket_cutters(mine, mats, c_tmp) + G.island_tips(mine, mats, c_tmp))
    cut(prom, prom_cut, "prom")
    cut(pen, pen_cut, "pen")
    cut(block, block_cut, "block")
    bpy.data.collections.remove(c_tmp)
    # the GLB gets the clean geometry (PROXY_ copies); the render gets the sculpted skins
    from mathutils import Vector
    back = Vector(mine_map.cam_basis()[0])
    ss = [mine_map.to_screen(p) for w in mine.workings.values() for p in w["pts"]]
    scx = (min(s[0] for s in ss) + max(s[0] for s in ss)) / 2.0
    sy0, sy1 = min(s[1] for s in ss) - 330.0, max(s[1] for s in ss) + 260.0

    def want(f):
        if f.normal.dot(back) < -0.05:
            return False
        sx, sy = mine_map.to_screen(f.calc_center_median())
        return abs(sx - scx) < 640.0 and sy0 < sy < sy1
    c_proxy = coll("PROXY")
    for i, ob in enumerate((block, prom, pen)):
        px = ob.copy()
        px.data = ob.data.copy()
        px.name = "PROXY_" + ob.name
        c_proxy.objects.link(px)
        G.mark_kinds(px)
        n1 = G.sculpt_rock(ob, seed=i, want=want)
        n2 = G.wall_skin(ob, seed=i * 7 + 3)
        G.facet_attributes(ob, seed=i)
        ob.pass_index = 1
        log("sculpt", ob.name, n1, "+", n2, "vertices moved,", len(ob.data.polygons), "faces")
    c_proxy.hide_render = True
    return slope


def main():
    args = parse_args()
    os.makedirs(BUILD, exist_ok=True)
    os.makedirs(PREVIEWS, exist_ok=True)
    topo = mine_map.load()
    sc = reset()
    mine = G.Mine(topo)
    mats = SH.rock_materials([mine.nodes["face-a"], mine.nodes["face-b"]])
    slope = build_geometry(mine, mats)
    log("props")
    P.build_props(mine, slope)
    log("lights, world, camera")
    SH.world_and_lights(mine)
    cam = X.main_camera(mine)
    sc.camera = cam
    X.scene_extras(sc, topo)
    blend = os.path.join(BUILD, "env_scene.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)
    log("saved", blend)
    if args.stage == "geo":
        X.render_view(os.path.join(PREVIEWS, "_geo_overview.png"), cam, zoom=1.0, focus=None,
                      samples=48 if args.quick else 128, res=(960, 540) if args.quick else (1920, 1080))
        return
    PL.full_pipeline(mine, topo, cam, slope, args.samples, do_textures=not args.no_textures,
                     do_previews=not args.no_previews)
    bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)
    log("done")


if __name__ == "__main__":
    main()
