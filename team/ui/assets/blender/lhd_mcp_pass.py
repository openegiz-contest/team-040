"""Detail pass for the underground loader (ПДМ), applied after lhd.py.

On 14 October 2026 this file was executed in the user's running Blender 5.1.2
through the Blender MCP tool `execute_blender_code` (`exec` of this file), with
lhd.blend open. The same file rebuilds the pass headless, after lhd.py:

    blender -b --factory-startup --python team/ui/assets/blender/lhd.py -- --no-render
    blender -b team/ui/assets/blender/lhd.blend --python team/ui/assets/blender/lhd_mcp_pass.py

What it adds (children of the empty `lhd`, identity transforms, like the rest):
- `lhd_detail_rims`: on the outer face of each tyre a dished wheel disc,
  a hub and six wheel nuts, in worn steel, so the wheels read as wheels and
  not as black discs at the sizes the scene shows them;
- `lhd_detail_hoses`: one hydraulic hose per side along the outside of the
  lift arms, in rubber.
The pass is idempotent (it deletes its own `lhd_detail_*` objects first),
keeps the budget of lhd.py (at most 8 000 triangles, 5 materials, no
textures), saves lhd.blend and re-exports public/models/lhd.glb with the same
exporter settings.
"""

import json
import math
import os
import struct

import bmesh
import bpy
from mathutils import Vector

BLEND_PATH = bpy.data.filepath
HERE = os.path.dirname(BLEND_PATH)
UI_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
GLB_PATH = os.path.join(UI_ROOT, "public", "models", "lhd.glb")
MAX_TRIANGLES = 8000

AXLE_X = 1.75           # axles at x = ±1.75 m (lhd.py)
WHEEL_Z = 0.825         # tyre centre height (tyre 1.65 m)
TYRE_OUTER_Y = 1.298    # outer sidewall of the tyres


def remove_previous():
    for ob in [o for o in bpy.data.objects if o.name.startswith("lhd_detail_")]:
        mesh = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def ring(bm, centre, axis_sign, radius, y, n, phase=0.0):
    """n vertices on a circle in the XZ plane at height y (wheel face)."""
    verts = []
    for i in range(n):
        a = phase + 2 * math.pi * i / n
        verts.append(bm.verts.new((centre.x + radius * math.cos(a), axis_sign * y, centre.z + radius * math.sin(a))))
    return verts


def bridge(bm, a, b):
    n = len(a)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((a[i], a[j], b[j], b[i]))


def cap(bm, loop, flip):
    bm.faces.new(list(reversed(loop)) if flip else loop)


def wheel_detail(bm, x, side):
    """Dished disc, hub and six nuts on the outer face of one wheel (side = +1 left, -1 right)."""
    c = Vector((x, 0.0, WHEEL_Z))
    y0 = TYRE_OUTER_Y - 0.035      # where the disc meets the tyre bead
    disc_outer = ring(bm, c, side, 0.50, y0, 16)
    disc_inner = ring(bm, c, side, 0.27, y0 + 0.05, 16)
    bridge(bm, disc_outer, disc_inner) if side > 0 else bridge(bm, disc_inner, disc_outer)
    hub_base = ring(bm, c, side, 0.17, y0 + 0.05, 12)
    hub_top = ring(bm, c, side, 0.15, y0 + 0.12, 12)
    bridge(bm, hub_base, hub_top) if side > 0 else bridge(bm, hub_top, hub_base)
    cap(bm, hub_top, flip=side < 0)
    # the annulus between the disc's inner edge and the hub base (closes the dish)
    inner16 = disc_inner
    for i in range(12):
        a0 = hub_base[i]
        a1 = hub_base[(i + 1) % 12]
        k0 = round(i * 16 / 12) % 16
        k1 = round((i + 1) * 16 / 12) % 16
        quad = [a0, a1, inner16[k1], inner16[k0]] if k1 != k0 else None
        if quad:
            bm.faces.new(quad if side > 0 else list(reversed(quad)))
    for k in range(6):
        a = 2 * math.pi * k / 6 + math.pi / 6
        nc = Vector((x + 0.215 * math.cos(a), 0.0, WHEEL_Z + 0.215 * math.sin(a)))
        lo = ring(bm, nc, side, 0.032, y0 + 0.05, 6)
        hi = ring(bm, nc, side, 0.032, y0 + 0.085, 6)
        bridge(bm, lo, hi) if side > 0 else bridge(bm, hi, lo)
        cap(bm, hi, flip=side < 0)


def tube(bm, points, radius, sides=6, segments=12):
    """A closed-end tube along a quadratic Bézier through three control points."""
    p0, p1, p2 = (Vector(p) for p in points)
    path = []
    for i in range(segments + 1):
        t = i / segments
        path.append((1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2)
    loops = []
    for i, p in enumerate(path):
        tangent = (path[min(i + 1, segments)] - path[max(i - 1, 0)]).normalized()
        side = tangent.cross(Vector((0.0, 1.0, 0.0))).normalized()
        up = side.cross(tangent).normalized()
        loop = []
        for s in range(sides):
            a = 2 * math.pi * s / sides
            loop.append(bm.verts.new(p + radius * (math.cos(a) * side + math.sin(a) * up)))
        loops.append(loop)
    for a, b in zip(loops, loops[1:]):
        bridge(bm, a, b)
    cap(bm, loops[0], flip=True)
    cap(bm, loops[-1], flip=False)


def make_object(name, bm, material, smooth):
    me = bpy.data.meshes.new(name)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    for poly in me.polygons:
        poly.use_smooth = smooth
    me.materials.append(material)
    ob = bpy.data.objects.new(name, me)
    parent = bpy.data.objects["lhd"]
    parent.users_collection[0].objects.link(ob)
    ob.parent = parent
    return ob


def build():
    remove_previous()
    steel = bpy.data.materials["lhd_steel_worn"]
    rubber = bpy.data.materials["lhd_rubber"]

    bm = bmesh.new()
    for x in (AXLE_X, -AXLE_X):
        for side in (1, -1):
            wheel_detail(bm, x, side)
    rims = make_object("lhd_detail_rims", bm, steel, smooth=False)

    bm = bmesh.new()
    for side in (1, -1):
        y = 0.79 * side
        tube(bm, [(0.86, y, 1.05), (1.35, y * 1.02, 1.85), (2.25, y, 1.93)], radius=0.035)
    hoses = make_object("lhd_detail_hoses", bm, rubber, smooth=True)
    return [rims, hoses]


def export_glb():
    lhd = bpy.data.objects["lhd"]
    objs = [lhd] + [o for o in lhd.children if o.type == "MESH"]
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=GLB_PATH, export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
        export_texcoords=False, export_normals=True, export_tangents=False, export_materials="EXPORT",
        export_vertex_color="NONE", export_attributes=False, export_image_format="NONE",
        export_cameras=False, export_lights=False, export_extras=False, export_animations=False,
        export_skins=False, export_morph=False, export_draco_mesh_compression_enable=False,
        export_copyright="Team repository licence (MIT); authored by Claude via Blender 5.1 command line script and a Blender MCP detail pass",
    )
    for o in objs:
        o.select_set(False)


def inspect_glb(path):
    with open(path, "rb") as fh:
        data = fh.read()
    clen = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20:20 + clen])
    acc = gltf["accessors"]
    tris = sum(acc[p["indices"]]["count"] // 3 for m in gltf["meshes"] for p in m["primitives"])
    return {"bytes": len(data), "triangles": tris, "materials": [m["name"] for m in gltf.get("materials", [])],
            "textures": len(gltf.get("textures", [])), "extensionsUsed": gltf.get("extensionsUsed", [])}


added = build()
export_glb()
info = inspect_glb(GLB_PATH)
ok = info["triangles"] <= MAX_TRIANGLES and len(info["materials"]) <= 5 and not info["textures"] and not info["extensionsUsed"]
bpy.ops.wm.save_mainfile(filepath=BLEND_PATH, compress=True)
if os.path.exists(BLEND_PATH + "1"):
    os.remove(BLEND_PATH + "1")
result = {"added": [o.name for o in added], "glb": info, "budget_ok": ok}
print("[lhd_mcp_pass]", json.dumps(result))
if not ok:
    raise SystemExit("[lhd_mcp_pass] budget exceeded")
