"""Browser-like check: load env.glb into an empty Blender scene, give every material an
emission-only (unlit) shader from its base colour texture, hide PICK_ meshes, and render
from the GLB's own MainView camera with no lights (overview + 3x zooms on both zones).

  blender --background --factory-startup --python check_unlit.py
Writes previews/unlit_overview.png, previews/unlit_zone_a_3x.png, previews/unlit_zone_b_3x.png
"""

import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mine_map  # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", ".."))
GLB = os.path.join(ROOT, "team", "ui", "public", "models", "mine-art", "env.glb")
OUT = os.path.join(HERE, "previews")


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=GLB)
    sc = bpy.context.scene
    cam = bpy.data.objects["MainView"]
    sc.camera = cam
    for ob in bpy.data.objects:
        if ob.name.startswith("PICK_"):
            ob.hide_render = True
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        nt = mat.node_tree
        img_node = next((n for n in nt.nodes if n.type == "TEX_IMAGE"), None)
        out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Strength"].default_value = 1.0
        if img_node is not None:
            img_node.interpolation = "Linear"
            nt.links.new(img_node.outputs["Color"], em.inputs["Color"])
        nt.links.new(em.outputs[0], out.inputs["Surface"])
    world = bpy.data.worlds.new("black")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
    sc.world = world
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 16
    sc.cycles.use_denoising = False
    sc.cycles.max_bounces = 0
    sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.render.image_settings.file_format = "PNG"
    print("camera ortho_scale", cam.data.ortho_scale, "lights", len([o for o in bpy.data.objects if o.type == "LIGHT"]))
    base_scale = cam.data.ortho_scale
    right = cam.matrix_world.to_3x3().col[0].normalized()
    up = cam.matrix_world.to_3x3().col[1].normalized()
    loc0 = cam.location.copy()
    topo = mine_map.load()
    cx, cy = topo["cx"], topo["cy"]

    def focus(wid):
        w = topo["workings"][wid]
        a, b = Vector(mine_map.to_blender(w["polyline"][0], cx, cy)), Vector(mine_map.to_blender(w["polyline"][-1], cx, cy))
        return a.lerp(b, 0.6)

    views = [("unlit_overview.png", 1.0, None), ("unlit_zone_a_3x.png", 3.0, focus("w-07")),
             ("unlit_zone_b_3x.png", 3.0, focus("w-12"))]
    for name, zoom, f in views:
        cam.data.ortho_scale = base_scale / zoom
        cam.location = loc0
        if f is not None:
            d = f - loc0
            sx, sy = d.dot(right), d.dot(up)
            hw = (base_scale - base_scale / zoom) / 2
            hh = hw * 9 / 16
            sx, sy = max(-hw, min(hw, sx)), max(-hh, min(hh, sy))
            cam.location = loc0 + right * sx + up * sy
        sc.render.filepath = os.path.join(OUT, name)
        bpy.ops.render.render(write_still=True)
        print("rendered", name)


main()
