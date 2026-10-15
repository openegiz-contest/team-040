"""
lineup.py - render all four actor GLBs together, as three.js shows them (unlit), from
the main view at the overview and close zoom, to compare scale and style with the
art references. Reads only the GLBs; writes previews/lineup_overview.png and
previews/lineup_close.png.

    "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" --background --factory-startup
        --python team/ui/assets/mine-art/actors/lineup.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import actors_style as S  # noqa: E402
import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

# (asset, x, y, heading deg, clip, frame); x east, y north (Blender), metres
PLACES = [
    ("lhd", -6.0, 6.0, 0.0, None, 0),
    ("truck", 22.0, 9.0, 180.0, None, 0),
    ("drill", -34.0, 4.0, 180.0, None, 0),
    ("worker", 6.0, -3.0, 0.0, "walk", 4),
    ("worker", 10.5, -1.0, 200.0, "idle", 0),
    ("worker", -20.0, -4.0, -60.0, "walk", 19),
    ("worker", 30.0, -3.5, 120.0, "walk", 11),
]


def main():
    S.reset_scene("lineup")
    js_cache = {}
    placed = []
    for asset, x, y, deg, clip, frame in PLACES:
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=os.path.join(S.OUT_DIR, asset + ".glb"))
        new = [o for o in bpy.data.objects if o not in before]
        root = next(o for o in new if o.parent is None and o.type == "EMPTY")
        S.log(asset, root.name, [(o.name, o.type, o.parent.name if o.parent else None) for o in new][:4])
        root.rotation_mode = "XYZ"
        root.location = (x, y, 0.0)
        root.rotation_euler = (0, 0, math.radians(deg))
        if clip:
            rig = next(o for o in new if o.type == "ARMATURE")
            act = next(a for a in bpy.data.actions if a.name.startswith(clip))
            ad = rig.animation_data or rig.animation_data_create()
            for tr in ad.nla_tracks:
                tr.mute = True
            ad.action = act
            try:
                ad.action_slot = act.slots[0]
            except (AttributeError, IndexError):
                pass
            # each worker keeps its own pose: bake the frame into the pose (apply as rest is
            # not needed for a still): evaluate now and copy the pose to a static action
            bpy.context.scene.frame_set(frame)
            for pb in rig.pose.bones:
                pb.keyframe_insert("location", frame=0)
                pb.keyframe_insert("rotation_quaternion", frame=0)
            ad.action = None
        placed.append(root)
        js_cache[asset] = S.read_glb(os.path.join(S.OUT_DIR, asset + ".glb"))[0]
    # unlit materials as in three.js (reuse the re-import converter on the loaded materials)
    gm = {}
    for js in js_cache.values():
        for m in js.get("materials", []):
            gm[m.get("name")] = m
    for mat in bpy.data.materials:
        g = gm.get(mat.name)
        if g is None or getattr(mat, "node_tree", None) is None:
            continue
        t = mat.node_tree
        img = next((n.image for n in t.nodes if n.type == "TEX_IMAGE" and n.image), None)
        fac = g.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
        t.nodes.clear()
        out = t.nodes.new("ShaderNodeOutputMaterial")
        emit = t.nodes.new("ShaderNodeEmission")
        mul = t.nodes.new("ShaderNodeVectorMath")
        mul.operation = "MULTIPLY"
        mul.inputs[1].default_value = fac[:3]
        if img:
            tex = t.nodes.new("ShaderNodeTexImage")
            tex.image = img
            t.links.new(tex.outputs["Color"], mul.inputs[0])
        else:
            mul.inputs[0].default_value = (1, 1, 1)
        t.links.new(mul.outputs[0], emit.inputs["Color"])
        if g.get("alphaMode") == "BLEND":
            va = t.nodes.new("ShaderNodeVertexColor")
            va.layer_name = "Color"
            mix = t.nodes.new("ShaderNodeMixShader")
            tr = t.nodes.new("ShaderNodeBsdfTransparent")
            t.links.new(va.outputs["Alpha"], mix.inputs[0])
            t.links.new(tr.outputs[0], mix.inputs[1])
            t.links.new(emit.outputs[0], mix.inputs[2])
            t.links.new(mix.outputs[0], out.inputs["Surface"])
        else:
            t.links.new(emit.outputs[0], out.inputs["Surface"])
        mat.use_backface_culling = True
    S.setup_cycles(48)
    S.enable_backface_culling_cycles()
    S.make_world(S.FLOOR_HEX)
    bpy.context.scene.frame_set(0)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    for tag, ppm in (("overview", S.PPM_OVERVIEW), ("close", S.PPM_CLOSE)):
        p = os.path.join(S.PREVIEW_DIR, f"lineup_{tag}.png")
        S.render_tile(meshes, ppm, p, pad=12)
        S.log("lineup", p)


main()
