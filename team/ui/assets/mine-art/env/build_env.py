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
    ap.add_argument("--samples", type=int, default=768)
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


def build_geometry(mine, mats):
    back, _, _ = mine_map.cam_basis()
    slope = G.EastSlope(mine, back)
    c_rock = coll("ROCK")
    c_cut = coll("CUTTERS")
    log("massif block")
    block = G.massif_block(mine, slope, mats, c_rock)
    log("cutters")
    G.face_plane_cutters(mine, slope, mats, c_cut)
    G.loop_cutter(mine, mats, c_cut)
    G.slope_cutter(mine, slope, mats, c_cut)
    G.ramp_trench_cutter(mine, slope, mats, c_cut)
    G.drill_bay_cutter(mine, mats, c_cut)
    log("boolean", len(c_cut.objects), "cutters")
    G.apply_boolean(block, c_cut)
    log("boolean done", len(block.data.polygons), "faces")
    c_cut.hide_render = True
    c_cut.hide_viewport = True
    for o in list(c_cut.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.collections.remove(c_cut)
    log("pillar and spurs")
    rocks = [block, G.pillar(mine, back, mats, c_rock), G.spur(mine, "w-07", mats, c_rock),
             G.spur(mine, "w-12", mats, c_rock)]
    # the faceted rock is real geometry; the GLB gets copies of it as depth proxies, the
    # render additionally gets a facet skin on the working walls
    c_proxy = coll("PROXY")
    from mathutils import Vector

    def want(f):
        """Refine only rock faces that face the camera inside the widest stage (+margin)."""
        if f.normal.dot(Vector(back)) < -0.05:
            return False
        sx, sy = mine_map.to_screen(f.calc_center_median())
        return -680 < sx < 660 and -600 < sy < 220
    for ob in rocks:
        if len(ob.data.polygons) < 50:     # an exact boolean that failed returns an empty mesh
            raise SystemExit(f"[env] {ob.name}: boolean result is empty ({len(ob.data.polygons)} faces)")
    for i, ob in enumerate(rocks):
        px = ob.copy()
        px.data = ob.data.copy()
        px.name = "PROXY_" + ob.name
        c_proxy.objects.link(px)
        G.facet_attributes(ob, seed=i)       # before the skins: their pieces inherit it
        n = G.wall_skin(ob, seed=i * 17 + 3)
        G.facet_attributes(ob, seed=i, only=(G.M_WALL,))   # every wall piece on its own
        n += G.rock_skin(ob, seed=i * 17 + 5, want=want)
        ob.pass_index = 1
        log("wall skin", ob.name, n, "vertices moved,", len(ob.data.polygons), "faces")
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
    PL.full_pipeline(mine, topo, cam, args.samples, do_textures=not args.no_textures,
                     do_previews=not args.no_previews)
    bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)
    log("done")


if __name__ == "__main__":
    main()
