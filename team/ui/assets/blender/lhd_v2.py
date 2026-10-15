"""
lhd_v2.py - procedural generator of the underground loader (LHD, "ПДМ"), version 2,
10-tonne class, for the dispatcher UI of the team's fictional copper mine.

Provenance
    Authored by Claude (Anthropic) on 15 October 2026 as this Python script for
    Blender 5.1. No external models, textures, HDRIs or add-ons: every vertex is
    produced by the code below. Licence: the repository's licence (MIT).
    How it was run is recorded in ../README.md (section "LHD v2").

What it builds (static "parked" pose: bucket lowered and level, frames straight)
    Full model, root empty "lhd_v2" (<= 15 000 triangles):
      lhd_v2_front (empty)  front frame group, articulates about the origin
        lhd_v2_front_frame  frame, boom tower, fenders, front lamps, joint clevis
        lhd_v2_boom         two lift arms, cross tube, Z-bar bellcrank and link,
                            two lift cylinders, tilt cylinder, hydraulic hoses
        lhd_v2_bucket       bucket shell, side plates, cutting edge, 7 teeth,
                            heel and side wear plates, spill-guard gussets
        lhd_v2_wheel_fl/fr  tyre with staggered L5-style lugs + steel rim, hub, nuts
      lhd_v2_rear (empty)   rear frame group
        lhd_v2_rear_frame   rear frame, hinge, pin, steering cylinders, deck,
                            engine bay with side grilles, sloping hood with a top
                            grille, counterweight, hydraulic tank, exhaust with
                            purifier, air precleaner, steps, rear lamps
        lhd_v2_cab          side-mounted enclosed ROPS/FOPS cab on the left,
                            glazing, door, mirror, roof lamps, grab handle
        lhd_v2_wheel_rl/rr
    The four wheel objects have their origin on their own axle centre, so the
    scene can spin them about their axle (glTF local Z).
    LOD model, root empty "lhd_v2_lod" (<= 3 000 triangles), same layout and
    materials, exported to its own file:
        lhd_v2_lod_front_frame (frame + boom), lhd_v2_lod_bucket, lhd_v2_lod_rear
        (rear body + cab), lhd_v2_lod_wheel_fl/fr/rl/rr.

Dimensions (metres, real-world scale), same frame as lhd.glb v1
    length ~10.2 incl. teeth (teeth tips +5.00 ... rear lamps -5.21)
    width 2.62 over the tyres, height 2.32 at the cab roof, wheelbase 3.50,
    axles at x = +1.75 / -1.75, tyre diameter 1.65,
    origin: ground level (z = 0) under the articulation pin.

Axes
    Blender: +X forward, +Y left, +Z up. The glTF exporter converts to Y-up:
    forward = +X, up = +Y, left (cab side) = -Z.

Materials (Principled BSDF, no image textures; names are the contract for the scene)
    lhd_paint       #56606A  body paint (the scene tints it)
    lhd_paint_dark  #25292E  chassis, counterweight, grille frames, lamp housings
    lhd_steel       #8C877E  rods, teeth, cutting edge, wear plates, rims, grille slats
    lhd_rubber      #1B1C1E  tyres, hoses, bumper, seat
    lhd_glass       #1B252D  cab glazing (opaque, glossy)
    lhd_lens        #FFE6BD  lamp lenses, emissive with strength 1.0 (emissiveFactor,
                             no KHR_materials_emissive_strength extension)

Outputs (paths relative to this file)
    ./lhd_v2.blend                       saved source scene (both models + preview rig)
    ../../public/models/lhd_v2.glb       full model
    ../../public/models/lhd_v2_lod.glb   LOD model
    ./previews/lhd_v2_*.png              Cycles previews

Run from the repository root (Windows example):
    "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" -b --factory-startup --python team/ui/assets/blender/lhd_v2.py
Options after "--":  --no-render   skip previews;   --samples N   Cycles samples (default 48)
Inside a running Blender (e.g. through Blender MCP `execute_blender_code`):
    exec(open(r"<repo>/team/ui/assets/blender/lhd_v2.py", encoding="utf-8").read(), {"__file__": r"<repo>/team/ui/assets/blender/lhd_v2.py", "__name__": "__main__"})
    It empties the current file first: run it in a new or throw-away file.
"""

import json
import math
import os
import struct
import sys
import time

import bmesh
import bpy
from mathutils import Vector

T0 = time.perf_counter()


def _script_path():
    try:
        return os.path.abspath(__file__)
    except NameError:
        argv = sys.argv
        if "--python" in argv:
            return os.path.abspath(argv[argv.index("--python") + 1])
        raise


HERE = os.path.dirname(_script_path())
UI_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
BLEND_PATH = os.path.join(HERE, "lhd_v2.blend")
GLB_PATH = os.path.join(UI_ROOT, "public", "models", "lhd_v2.glb")
GLB_LOD_PATH = os.path.join(UI_ROOT, "public", "models", "lhd_v2_lod.glb")
PREVIEW_DIR = os.path.join(HERE, "previews")

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
DO_RENDER = "--no-render" not in ARGS
SAMPLES = int(ARGS[ARGS.index("--samples") + 1]) if "--samples" in ARGS else 48

MAX_TRIANGLES = 15000
MAX_TRIANGLES_LOD = 3000

AXLE_F = 1.75
AXLE_R = -1.75
WHEEL_Z = 0.825         # axle height = tyre radius incl. lugs (0.775 + 0.05)
WHEEL_Y = 1.04          # tyre centre |y|; half width 0.27 -> outer face at 1.31
DECK_Z = 1.70

# --------------------------------------------------------------------------- scene reset


def reset_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                 bpy.data.cameras, bpy.data.worlds, bpy.data.images, bpy.data.node_groups):
        for block in list(coll):
            coll.remove(block)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    scene = bpy.context.scene
    scene.name = "lhd_v2"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


# --------------------------------------------------------------------------- materials


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_rgba(h):
    h = h.lstrip("#")
    return tuple(srgb_to_linear(int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4)) + (1.0,)


def principled(name, hex_color, roughness, metallic=0.0, emissive=False):
    mat = bpy.data.materials.new(name)
    if getattr(mat, "node_tree", None) is None:
        mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    rgba = hex_rgba(hex_color)
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if emissive:
        bsdf.inputs["Emission Color"].default_value = rgba
        bsdf.inputs["Emission Strength"].default_value = 1.0
    mat.diffuse_color = rgba
    mat.roughness = roughness
    mat.metallic = metallic
    return mat


def make_materials():
    return {
        "paint": principled("lhd_paint", "#56606A", 0.5, 0.15),
        "dark": principled("lhd_paint_dark", "#25292E", 0.6, 0.1),
        "steel": principled("lhd_steel", "#8C877E", 0.45, 0.45),
        "rubber": principled("lhd_rubber", "#1B1C1E", 0.9, 0.0),
        "glass": principled("lhd_glass", "#1B252D", 0.08, 0.0),
        "lens": principled("lhd_lens", "#FFE6BD", 0.15, 0.0, emissive=True),
    }


# --------------------------------------------------------------------------- mesh builder


class Part:
    """A bmesh plus its material slots; becomes one Blender object."""

    def __init__(self, name, mats):
        self.name = name
        self.bm = bmesh.new()
        self.nobevel = self.bm.verts.layers.int.new("nobevel")
        self.slots = []
        self.mats = mats

    def _idx(self, slot):
        if slot not in self.slots:
            self.slots.append(slot)
        return self.slots.index(slot)

    def _flag(self, verts, bevel):
        if not bevel:
            for v in verts:
                v[self.nobevel] = 1

    def hexa(self, pts, slot="paint", bevel=True):
        """Eight corners: bottom face 0-3, top face 4-7 (same winding)."""
        bm = self.bm
        v = [bm.verts.new(p) for p in pts]
        self._flag(v, bevel)
        m = self._idx(slot)
        for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            bm.faces.new([v[i] for i in f]).material_index = m

    def box(self, mn, mx, slot="paint", bevel=True):
        (x0, y0, z0), (x1, y1, z1) = mn, mx
        self.hexa([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                   (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], slot, bevel)

    def prism_xz(self, pts, y0, y1, slot="paint", bevel=True):
        bm = self.bm
        a = [bm.verts.new((x, y0, z)) for x, z in pts]
        b = [bm.verts.new((x, y1, z)) for x, z in pts]
        self._flag(a + b, bevel)
        m = self._idx(slot)
        bm.faces.new(a).material_index = m
        bm.faces.new(list(reversed(b))).material_index = m
        n = len(pts)
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((a[i], a[j], b[j], b[i])).material_index = m

    def prism_xy(self, pts, z0, z1, slot="paint", bevel=True):
        """Polygon in plan (XY), extruded from z0 to z1."""
        bm = self.bm
        a = [bm.verts.new((x, y, z0)) for x, y in pts]
        b = [bm.verts.new((x, y, z1)) for x, y in pts]
        self._flag(a + b, bevel)
        m = self._idx(slot)
        bm.faces.new(a).material_index = m
        bm.faces.new(list(reversed(b))).material_index = m
        n = len(pts)
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((a[i], a[j], b[j], b[i])).material_index = m

    def strip_xz(self, line, thick, y0, y1, slot="paint", bevel=True):
        pts = [Vector((x, z)) for x, z in line]
        normals = []
        for i in range(len(pts)):
            segs = []
            if i > 0:
                segs.append((pts[i] - pts[i - 1]).normalized())
            if i < len(pts) - 1:
                segs.append((pts[i + 1] - pts[i]).normalized())
            ns = [Vector((-d.y, d.x)) for d in segs]
            n = sum(ns, Vector((0, 0))).normalized()
            scale = (thick / 2) / max(0.35, n.dot(ns[0]))
            normals.append(n * scale)
        left = [tuple(p + n) for p, n in zip(pts, normals)]
        right = [tuple(p - n) for p, n in zip(pts, normals)]
        self.prism_xz(left + list(reversed(right)), y0, y1, slot, bevel)

    def cylinder(self, p0, p1, r, sides=10, slot="paint", caps=True, r1=None):
        p0, p1 = Vector(p0), Vector(p1)
        d = (p1 - p0).normalized()
        u = d.orthogonal().normalized()
        w = d.cross(u).normalized()
        bm = self.bm
        m = self._idx(slot)
        r1 = r if r1 is None else r1
        ring0, ring1 = [], []
        for k in range(sides):
            a = 2 * math.pi * (k + 0.5) / sides
            off = u * math.cos(a) + w * math.sin(a)
            ring0.append(bm.verts.new(p0 + off * r))
            ring1.append(bm.verts.new(p1 + off * r1))
        self._flag(ring0 + ring1, False)
        for k in range(sides):
            j = (k + 1) % sides
            bm.faces.new((ring0[k], ring0[j], ring1[j], ring1[k])).material_index = m
        if caps:
            bm.faces.new(list(reversed(ring0))).material_index = m
            bm.faces.new(ring1).material_index = m

    def hydraulic(self, base, tip, r_barrel, frac=0.6, sides=12, eyes=True):
        """Barrel (paint) with a gland ring, rod (steel), eye bosses across both ends."""
        base, tip = Vector(base), Vector(tip)
        d = (tip - base).normalized()
        mid = base.lerp(tip, frac)
        self.cylinder(base + d * r_barrel * 0.6, mid, r_barrel, sides, "paint")
        self.cylinder(mid - d * 0.06, mid + d * 0.02, r_barrel * 1.12, sides, "dark")
        self.cylinder(mid, tip - d * r_barrel * 0.4, r_barrel * 0.48, max(6, sides - 4), "steel")
        if eyes:
            side = d.cross(Vector((0, 0, 1)))
            if side.length < 1e-3:
                side = Vector((0, 1, 0))
            side.normalize()
            for c, r in ((base, r_barrel * 0.85), (tip, r_barrel * 0.6)):
                self.cylinder(c - side * r_barrel * 0.7, c + side * r_barrel * 0.7, r, 8, "dark")

    def tube(self, points, radius, sides=6, segments=10, slot="rubber"):
        """A hose along a quadratic Bezier through three control points."""
        p0, p1, p2 = (Vector(p) for p in points)
        path = [(1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2
                for t in (i / segments for i in range(segments + 1))]
        bm = self.bm
        m = self._idx(slot)
        loops = []
        ref = Vector((0.0, 1.0, 0.0))
        for i, p in enumerate(path):
            tangent = (path[min(i + 1, segments)] - path[max(i - 1, 0)]).normalized()
            side = tangent.cross(ref)
            if side.length < 1e-4:
                side = tangent.cross(Vector((0, 0, 1)))
            side.normalize()
            up = side.cross(tangent).normalized()
            loop = [bm.verts.new(p + radius * (math.cos(2 * math.pi * s / sides) * side
                                               + math.sin(2 * math.pi * s / sides) * up))
                    for s in range(sides)]
            self._flag(loop, False)
            loops.append(loop)
        for a, b in zip(loops, loops[1:]):
            for s in range(sides):
                t = (s + 1) % sides
                bm.faces.new((a[s], a[t], b[t], b[s])).material_index = m
        bm.faces.new(list(reversed(loops[0]))).material_index = m
        bm.faces.new(loops[-1]).material_index = m

    def lamp(self, centre, direction, r=0.085, depth=0.13, sides=12, bracket=True):
        """Round work lamp: dark housing, emissive lens, a small bracket below."""
        c, d = Vector(centre), Vector(direction).normalized()
        self.cylinder(c - d * depth, c, r, sides, "dark", r1=r * 1.04)
        self.cylinder(c - d * 0.005, c + d * 0.012, r * 0.86, sides, "lens")
        if bracket:
            self.box((c.x - 0.03 - (depth / 2 if d.x > 0 else -depth / 2), c.y - 0.025, c.z - r - 0.07),
                     (c.x + 0.03 - (depth / 2 if d.x > 0 else -depth / 2), c.y + 0.025, c.z - r + 0.01),
                     "dark", bevel=False)

    def to_object(self, parent, bevel=0.0, smooth_angle=40.0, origin=None):
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts, dist=1e-5)
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces)
        if bevel > 0:
            bw = self.bm.edges.layers.float.new("bevel_weight_edge")
            limit = math.radians(35)
            for e in self.bm.edges:
                if (e.is_manifold and not (e.verts[0][self.nobevel] or e.verts[1][self.nobevel])
                        and e.calc_face_angle(0.0) > limit):
                    e[bw] = 1.0
        self.bm.verts.layers.int.remove(self.nobevel)
        if origin is not None:
            bmesh.ops.translate(self.bm, vec=-Vector(origin), verts=self.bm.verts)
        me = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(me)
        self.bm.free()
        ob = bpy.data.objects.new(self.name, me)
        bpy.context.scene.collection.objects.link(ob)
        for s in self.slots:
            me.materials.append(self.mats[s])
        ob.parent = parent
        if origin is not None:
            ob.location = Vector(origin)
        finish_object(ob, bevel, smooth_angle)
        return ob


def finish_object(ob, bevel, smooth_angle):
    view_layer = bpy.context.view_layer
    for o in bpy.context.scene.objects:
        o.select_set(False)
    view_layer.objects.active = ob
    ob.select_set(True)
    if bevel > 0:
        mod = ob.modifiers.new("bevel", "BEVEL")
        mod.width = bevel
        mod.segments = 1
        mod.limit_method = "WEIGHT"
        mod.edge_weight = "bevel_weight_edge"
        mod.use_clamp_overlap = True
        bpy.ops.object.modifier_apply(modifier=mod.name)
        attr = ob.data.attributes.get("bevel_weight_edge")
        if attr is not None:
            ob.data.attributes.remove(attr)
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(smooth_angle))
    mod = ob.modifiers.new("weighted_normals", "WEIGHTED_NORMAL")
    mod.mode = "FACE_AREA"
    mod.weight = 50
    mod.keep_sharp = True
    bpy.ops.object.modifier_apply(modifier=mod.name)
    ob.select_set(False)


def arc(cx, cz, r, a0, a1, n):
    """Points on a circle in XZ from angle a0 to a1 (degrees), n+1 points."""
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cz + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def sides_of(y_in, y_out):
    """Both mirrored y-intervals [in, out] for s = +1 (left) and -1 (right)."""
    return [tuple(sorted((s * y_in, s * y_out))) for s in (1, -1)]


# --------------------------------------------------------------------------- front group


def build_front_frame(mats, parent, lod=False, name="lhd_v2_front_frame"):
    p = Part(name, mats)
    # frame: chamfered box between the front tyres
    p.prism_xz([(0.34, 0.50), (2.70, 0.50), (3.06, 0.68), (3.06, 1.02), (2.86, 1.16),
                (1.40, 1.16), (0.34, 1.12)], -0.56, 0.56, "paint")
    # boom tower: carries the arm pivots and the tilt cylinder
    p.prism_xz([(0.30, 1.08), (1.48, 1.08), (1.32, 1.52), (1.06, 2.00), (0.52, 2.08),
                (0.30, 1.84)], -0.52, 0.52, "paint")
    # fenders over the front tyres: arched plates + flat lamp shelf at the front
    for y0, y1 in sides_of(0.72, 1.34):
        line = arc(AXLE_F, WHEEL_Z, 0.95, 168, 12, 4 if lod else 7)
        p.strip_xz(line, 0.05, y0, y1, "paint")
    if lod:
        p.box((0.40, -0.48, 0.42), (2.80, 0.48, 0.50), "dark", bevel=False)
        # boom in the LOD: arms and the tilt cylinder as simple solids
        for y0, y1 in sides_of(0.40, 0.58):
            p.strip_xz([(0.86, 1.82), (2.36, 1.56), (2.96, 1.06), (3.34, 0.56)], 0.32, y0, y1, "paint", bevel=False)
            p.cylinder((1.40, (y0 + y1) / 2 * 1.12, 0.78), (2.25, (y0 + y1) / 2 * 1.12, 1.38), 0.085, 6, "paint", caps=False)
        p.cylinder((0.75, 0.0, 2.10), (2.30, 0.0, 2.12), 0.11, 6, "paint", caps=False)
        p.cylinder((2.45, -0.58, 1.52), (2.45, 0.58, 1.52), 0.11, 6, "paint", caps=False)
        p.box((0.62, -0.16, 2.02), (0.92, 0.16, 2.22), "dark", bevel=False)
        p.box((3.00, -0.62, 0.46), (3.14, 0.62, 0.62), "dark", bevel=False)
        for z0 in (0.44, 1.00):
            p.box((-0.18, -0.30, z0), (0.36, 0.30, z0 + 0.12), "dark", bevel=False)
        for s in (1, -1):
            y0, y1 = sorted((s * 0.54, s * 0.76))
            p.box((AXLE_F + 0.66, y0, 1.00), (AXLE_F + 0.80, y1, 1.70), "dark", bevel=False)
            yc = s * 1.05
            p.box((2.40, yc - 0.13, 1.66), (2.70, yc + 0.13, 1.71), "dark", bevel=False)
            p.box((2.64, yc - 0.09, 1.72), (2.80, yc + 0.09, 1.90), "dark", bevel=False)
            p.box((2.80, yc - 0.07, 1.74), (2.82, yc + 0.07, 1.88), "lens", bevel=False)
        return p.to_object(parent, bevel=0.0, smooth_angle=30.0)
    for s in (1, -1):
        # fender stays to the frame
        for x in (AXLE_F - 0.80, AXLE_F + 0.66):
            y0, y1 = sorted((s * 0.54, s * 0.76))
            p.box((x, y0, 1.00), (x + 0.14, y1, 1.70), "dark")
        # lift-cylinder base brackets (pairs of lugs)
        for yy in (0.56, 0.74):
            y0, y1 = sorted((s * yy, s * (yy + 0.04)))
            p.prism_xz([(1.22, 0.62), (1.58, 0.62), (1.52, 0.92), (1.30, 0.98)], y0, y1, "paint")
        # steering-cylinder lugs at the rear of the frame
        y0, y1 = sorted((s * 0.50, s * 0.70))
        p.box((0.36, y0, 0.72), (0.62, y1, 0.96), "dark")
        # tower side cheeks with the arm pivot boss
        y0, y1 = sorted((s * 0.52, s * 0.58))
        p.prism_xz([(0.50, 1.30), (1.18, 1.30), (1.06, 1.98), (0.62, 2.04)], y0, y1, "dark")
        # front lamps on the fenders, on a shelf, facing forward
        yc = s * 1.05
        p.box((2.40, yc - 0.13, 1.66), (2.70, yc + 0.13, 1.71), "dark")
        p.lamp((2.78, yc, 1.82), (1, 0, 0), r=0.085, depth=0.14, bracket=False)
        p.box((2.62, yc - 0.03, 1.70), (2.68, yc + 0.03, 1.76), "dark", bevel=False)
        # reflector-free front corner guard
        y0, y1 = sorted((s * 0.30, s * 0.56))
        p.box((2.95, y0, 0.55), (3.12, y1, 0.80), "steel")
    # tilt-cylinder clevis on the tower top
    p.box((0.62, -0.16, 2.02), (0.92, 0.16, 2.22), "dark")
    # belly / skid plate
    p.box((0.42, -0.50, 0.42), (2.80, 0.50, 0.50), "steel")
    # joint: front clevis plates reaching back over the pin
    for z0 in (0.44, 1.00):
        p.prism_xz([(0.36, z0), (0.36, z0 + 0.12), (-0.10, z0 + 0.12), (-0.20, z0 + 0.06), (-0.10, z0)],
                   -0.30, 0.30, "dark")
    # front bumper bar under the bucket
    p.box((3.00, -0.62, 0.46), (3.14, 0.62, 0.62), "dark")
    return p.to_object(parent, bevel=0.022)


def build_boom(mats, parent):
    p = Part("lhd_v2_boom", mats)
    pivot, knee1, knee2, pin = (0.86, 1.82), (2.36, 1.56), (2.96, 1.06), (3.34, 0.56)
    for s in (1, -1):
        y0, y1 = sorted((s * 0.40, s * 0.58))
        p.strip_xz([pivot, knee1, knee2, pin], 0.32, y0, y1, "paint")
        # reinforcing flange on the outer face of the arm
        y0, y1 = sorted((s * 0.58, s * 0.61))
        p.strip_xz([(1.10, 1.78), knee1, (2.86, 1.12)], 0.12, y0, y1, "dark")
        # pin bosses
        p.cylinder((pivot[0], s * 0.36, pivot[1]), (pivot[0], s * 0.64, pivot[1]), 0.17, 12, "dark")
        p.cylinder((pin[0], s * 0.36, pin[1]), (pin[0], s * 0.64, pin[1]), 0.14, 12, "dark")
        # lug under the arm for the lift cylinder
        y0, y1 = sorted((s * 0.56, s * 0.76))
        p.prism_xz([(2.08, 1.48), (2.44, 1.48), (2.36, 1.30), (2.18, 1.24)], y0, y1, "paint")
        # lift cylinders: frame bracket -> arm lug
        p.hydraulic((1.40, s * 0.66, 0.78), (2.27, s * 0.66, 1.33), 0.088, 0.58)
        # hoses: from the frame up along the arm to the lift cylinder head and the tilt cylinder
        p.tube([(1.05, s * 0.66, 1.05), (1.35, s * 0.70, 1.30), (1.62, s * 0.70, 0.98)], 0.03)
        p.tube([(0.70, s * 0.30, 1.96), (1.10, s * 0.62, 2.20), (1.80, s * 0.62, 1.82)], 0.032)
    # cross tube between the arms carrying the bellcrank
    p.cylinder((2.45, -0.58, 1.52), (2.45, 0.58, 1.52), 0.11, 12, "paint")
    # Z-bar bellcrank: pair of plates, upper eye for the tilt cylinder, lower eye for the link
    for y in (0.07, -0.07):
        y0, y1 = sorted((y, y + (0.07 if y > 0 else -0.07)))
        p.strip_xz([(2.30, 2.14), (2.45, 1.52), (2.62, 1.02)], 0.24, y0, y1, "paint")
    p.cylinder((2.30, -0.16, 2.14), (2.30, 0.16, 2.14), 0.08, 10, "dark")
    p.cylinder((2.62, -0.16, 1.02), (2.62, 0.16, 1.02), 0.075, 10, "dark")
    # link from the bellcrank to the bucket lug
    p.strip_xz([(2.62, 1.02), (3.30, 0.98)], 0.15, -0.065, 0.065, "paint")
    # tilt cylinder: tower top -> bellcrank top
    p.hydraulic((0.77, 0.0, 2.12), (2.30, 0.0, 2.14), 0.115, 0.56, sides=14)
    return p.to_object(parent, bevel=0.015)


def build_bucket(mats, parent, lod=False, name="lhd_v2_bucket"):
    """~4.6 m3 bucket, 2.60 m wide, lowered and level."""
    p = Part(name, mats)
    lip = 4.78
    heel = arc(3.82, 0.50, 0.43, 270, 180, 2 if lod else 5)
    shell = [(4.40, 0.07)] + heel + [(3.39, 0.88), (3.47, 1.12), (4.06, 1.22)]
    p.strip_xz(shell, 0.06, -1.23, 1.23, "paint", bevel=not lod)
    outline = ([(lip + 0.02, 0.03), (lip - 0.01, 0.30), (4.08, 1.26), (3.44, 1.17), (3.33, 0.88)]
               + [(x - 0.03, z) for x, z in reversed(heel)][1:] + [(3.82, 0.02)])
    outline = [(x, z) for x, z in outline]
    for y0, y1 in sides_of(1.22, 1.30):
        p.prism_xz(outline, y0, y1, "paint", bevel=not lod)
    # cutting edge (thick wear plate)
    p.prism_xz([(4.36, 0.035), (4.80, 0.035), (4.80, 0.075), (4.68, 0.125), (4.36, 0.125)],
               -1.24, 1.24, "steel", bevel=not lod)
    if lod:
        p.box((3.40, -1.23, 1.12), (3.58, 1.23, 1.24), "paint", bevel=False)
        for i in range(7):
            y = -1.02 + i * 0.34
            p.hexa([(4.64, y - 0.07, 0.05), (4.98, y - 0.04, 0.045), (4.98, y + 0.04, 0.045), (4.64, y + 0.07, 0.05),
                    (4.64, y - 0.07, 0.16), (4.98, y - 0.04, 0.075), (4.98, y + 0.04, 0.075), (4.64, y + 0.07, 0.16)],
                   "steel", bevel=False)
        return p.to_object(parent, bevel=0.0, smooth_angle=30.0)
    # side cutters: steel wear plates on the lower front of the side plates
    for y0, y1 in sides_of(1.30, 1.32):
        p.prism_xz([(4.80, 0.03), (4.78, 0.30), (4.42, 0.66), (4.20, 0.66), (4.20, 0.03)], y0, y1, "steel")
    # seven teeth on adapters along the lip
    for i in range(7):
        y = -1.02 + i * 0.34
        w0, w1 = 0.075, 0.04
        p.hexa([(4.64, y - w0, 0.05), (5.00, y - w1, 0.045), (5.00, y + w1, 0.045), (4.64, y + w0, 0.05),
                (4.64, y - w0, 0.17), (5.00, y - w1, 0.075), (5.00, y + w1, 0.075), (4.64, y + w0, 0.17)],
               "steel")
    # wear strips under the floor and on the heel
    for y in (-0.92, -0.46, 0.0, 0.46, 0.92):
        p.box((3.70, y - 0.07, 0.0), (4.44, y + 0.07, 0.045), "steel")
        p.strip_xz(arc(3.82, 0.50, 0.475, 262, 200, 3), 0.04, y - 0.07, y + 0.07, "steel")
    # spill guard: top bar and gussets
    p.box((3.40, -1.23, 1.13), (3.60, 1.23, 1.25), "paint")
    for y in (-0.80, 0.0, 0.80):
        p.prism_xz([(3.46, 1.12), (3.95, 1.20), (3.46, 1.36)], y - 0.03, y + 0.03, "paint")
    # pin lugs on the back: two for the arms, one for the link
    for y0, y1 in sides_of(0.38, 0.62):
        p.prism_xz([(3.14, 0.44), (3.22, 0.34), (3.38, 0.30), (3.38, 0.76), (3.22, 0.72)], y0, y1, "dark")
    p.prism_xz([(3.18, 0.92), (3.26, 0.86), (3.40, 0.84), (3.40, 1.10), (3.26, 1.08)], -0.15, 0.15, "dark")
    return p.to_object(parent, bevel=0.012)


def build_wheel(mats, parent, name, x, side, lod=False):
    """Tyre with staggered lugs (rubber) + dished rim, hub and nuts (steel), around Y."""
    p = Part(name, mats)
    bm = p.bm
    s = 1 if side == "l" else -1
    yc = s * WHEEL_Y
    segments = 16 if lod else 26
    if lod:
        prof = [(0.42, -0.24), (0.70, -0.27), (0.775, -0.20), (0.775, 0.0), (0.775, 0.20), (0.70, 0.27), (0.42, 0.24)]
    else:
        prof = [(0.42, -0.24), (0.62, -0.275), (0.72, -0.265), (0.765, -0.22), (0.775, -0.11),
                (0.778, 0.0), (0.775, 0.11), (0.765, 0.22), (0.72, 0.265), (0.62, 0.275), (0.42, 0.24)]
    if lod:
        rim = [(0.42, 0.24), (0.30, 0.15), (0.0, 0.17)]
    else:
        rim = [(0.42, 0.24), (0.40, 0.205), (0.31, 0.13), (0.22, 0.13), (0.20, 0.175), (0.0, 0.18)]
    inner = [(0.0, -0.17), (0.42, -0.24)]
    full = inner[:-1] + prof + rim[1:]
    n_in = len(inner) - 1
    mat_of_edge = []
    for i in range(len(full) - 1):
        if i < n_in:
            mat_of_edge.append("dark")
        elif i < n_in + len(prof) - 1:
            mat_of_edge.append("rubber")
        else:
            mat_of_edge.append("steel")

    def ring(r, yl, a):
        return (x + r * math.cos(a), yc + s * yl, WHEEL_Z + r * math.sin(a))

    grid = []
    for k in range(segments):
        a = 2 * math.pi * k / segments
        grid.append([bm.verts.new(ring(r, yl, a)) if r > 0 else None for r, yl in full])
    centres = [bm.verts.new((x, yc + s * full[0][1], WHEEL_Z)), bm.verts.new((x, yc + s * full[-1][1], WHEEL_Z))]
    faces = {}
    for k in range(segments):
        k2 = (k + 1) % segments
        for i in range(len(full) - 1):
            a0, a1 = grid[k][i], grid[k][i + 1]
            b0, b1 = grid[k2][i], grid[k2][i + 1]
            if a0 is None:
                f = bm.faces.new((centres[0], b1, a1))
            elif a1 is None:
                f = bm.faces.new((a0, b0, centres[1]))
            else:
                f = bm.faces.new((a0, b0, b1, a1))
            f.material_index = p._idx(mat_of_edge[i])
            faces[(k, i)] = f
    p._flag(list(bm.verts), False)
    if lod:
        # one lug per segment, alternating halves of the tread
        for k in range(segments):
            ret = bmesh.ops.extrude_face_region(bm, geom=[faces[(k, n_in + 2 + (k % 2))]])
            for v in [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]:
                v.co += Vector((v.co.x - x, 0.0, v.co.z - WHEEL_Z)).normalized() * 0.05
    else:
        # staggered lugs: shoulder + two tread bands on one side, alternating sides
        t0 = n_in + 2          # prof edge 2: shoulder (0.72 -> 0.765) inner side
        left = [t0, t0 + 1, t0 + 2]
        right = [t0 + 3, t0 + 4, t0 + 5]
        for k in range(segments):
            region = [faces[(k, i)] for i in (left if k % 2 == 0 else right)]
            ret = bmesh.ops.extrude_face_region(bm, geom=region)
            for v in [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]:
                radial = Vector((v.co.x - x, 0.0, v.co.z - WHEEL_Z)).normalized()
                v.co += radial * 0.05
        # wheel nuts on the hub flange
        for k in range(8):
            a = 2 * math.pi * k / 8
            cx, cz = x + 0.265 * math.cos(a), WHEEL_Z + 0.265 * math.sin(a)
            y0 = yc + s * 0.13
            p.cylinder((cx, y0, cz), (cx, y0 + s * 0.035, cz), 0.026, 6, "steel")
    return p.to_object(parent, bevel=0.0, smooth_angle=50.0, origin=(x, yc, WHEEL_Z))


# --------------------------------------------------------------------------- rear group


def build_rear_frame(mats, parent, lod=False, name="lhd_v2_rear_frame"):
    p = Part(name, mats)
    # hinge block between the front clevis plates, and the pin
    p.prism_xz([(-0.34, 0.58), (0.06, 0.58), (0.14, 0.66), (0.14, 0.94), (0.06, 1.00), (-0.34, 1.00)],
               -0.26, 0.26, "dark", bevel=not lod)
    # rear frame core
    p.box((-2.72, -0.64, 0.50), (-0.30, 0.64, DECK_Z - 0.08), "dark", bevel=not lod)
    # deck over the rear tyres
    p.box((-2.70, -1.31, DECK_Z - 0.08), (-0.92, 1.31, DECK_Z), "paint", bevel=not lod)
    # engine bay below the hood, chamfered under the counterweight
    p.prism_xz([(-2.64, 0.52), (-4.70, 0.52), (-4.90, 0.72), (-4.90, DECK_Z - 0.02), (-2.64, DECK_Z - 0.02)],
               -1.25, 1.25, "paint", bevel=not lod)
    # engine hood sloping down to the rear (visibility when reversing)
    p.prism_xz([(-1.76, DECK_Z - 0.02), (-1.76, 2.02), (-1.96, 2.12), (-4.22, 2.04), (-4.88, 1.86),
                (-4.88, DECK_Z - 0.02)], -1.17, 1.17, "paint", bevel=not lod)
    # counterweight
    p.prism_xz([(-4.86, 0.42), (-4.86, 1.84), (-5.02, 1.84), (-5.18, 1.60), (-5.18, 0.64), (-5.06, 0.42)],
               -1.26, 1.26, "dark", bevel=not lod)
    # hydraulic tank on the right beside the cab
    p.prism_xz([(-0.30, 0.54), (-0.30, 1.52), (-0.56, 1.86), (-1.74, 1.96), (-1.74, DECK_Z),
                (-0.94, DECK_Z), (-0.94, 0.54)], -1.29, -0.10, "paint", bevel=not lod)
    # rear fenders: arched plates in front of and behind the rear tyres
    for y0, y1 in sides_of(0.72, 1.32):
        p.strip_xz(arc(AXLE_R, WHEEL_Z, 0.95, 160, 128, 1 if lod else 3), 0.05, y0, y1, "paint", bevel=not lod)
        p.strip_xz(arc(AXLE_R, WHEEL_Z, 0.95, 52, 20, 1 if lod else 3), 0.05, y0, y1, "paint", bevel=not lod)
    if lod:
        for s in (1, -1):
            for yy in (0.72,):
                p.box((-5.20, s * yy - 0.10, 1.24), (-5.18, s * yy + 0.10, 1.40), "lens", bevel=False)
            p.box((-4.60, s * 1.25 - 0.01, 0.86), (-3.00, s * 1.25 + 0.01, 1.48), "dark", bevel=False)
            p.box((-0.52, s * 0.60 - 0.07, 0.77), (0.50, s * 0.60 + 0.07, 0.91), "paint", bevel=False)
        p.box((-4.10, -0.82, 2.02), (-2.90, 0.82, 2.09), "dark", bevel=False)
        p.cylinder((-2.10, -0.72, 2.0), (-2.10, -0.72, 2.34), 0.13, 8, "dark", caps=True)
        p.cylinder((-4.40, -0.80, 1.95), (-4.40, -0.80, 2.18), 0.13, 8, "steel", caps=True)
        p.cylinder((-4.40, -0.80, 2.18), (-4.40, -0.80, 2.32), 0.055, 6, "steel", caps=True)
        return p
    # steering cylinders across the joint
    for s in (1, -1):
        p.hydraulic((-0.52, s * 0.60, 0.84), (0.50, s * 0.60, 0.84), 0.075, 0.55, sides=10)
    # articulation pin with caps
    p.cylinder((0.0, 0.0, 0.40), (0.0, 0.0, 1.14), 0.085, 12, "steel")
    for z in (0.40, 1.12):
        p.cylinder((0.0, 0.0, z - 0.02), (0.0, 0.0, z + 0.05), 0.13, 12, "dark")
    # side grilles of the engine bay: recessed dark panel with steel slats
    for s in (1, -1):
        y_face = s * 1.25
        y0, y1 = sorted((y_face, y_face + s * 0.012))
        p.box((-4.62, y0, 0.84), (-2.98, y1, 1.50), "dark", bevel=False)
        for k in range(6):
            z = 0.88 + k * 0.105
            ya, yb = sorted((y_face, y_face + s * 0.035))
            p.box((-4.56, ya, z), (-3.04, yb, z + 0.045), "steel", bevel=False)
        # service door seams (thin dark strips)
        for xd in (-2.86, -4.74):
            p.box((xd, y0, 0.62), (xd + 0.03, y1, 1.62), "dark", bevel=False)
        # step + grab handle at the hood end
        ya, yb = sorted((s * 1.20, s * 1.36))
        p.box((-4.70, ya, 0.56), (-4.30, yb, 0.60), "steel", bevel=False)
    # top grille on the hood (radiator outlet) with slats
    p.box((-4.10, -0.82, 2.02), (-2.90, 0.82, 2.075), "dark", bevel=False)
    for k in range(7):
        x = -4.04 + k * 0.165
        p.box((x, -0.78, 2.07), (x + 0.07, 0.78, 2.10), "steel", bevel=False)
    # rear grille on the counterweight top
    p.box((-4.86, -0.90, 1.84), (-4.70, 0.90, 1.88), "dark", bevel=False)
    # air precleaner (front right of the hood)
    p.cylinder((-2.10, -0.72, 2.08), (-2.10, -0.72, 2.30), 0.12, 12, "dark")
    p.cylinder((-2.10, -0.72, 2.30), (-2.10, -0.72, 2.36), 0.16, 12, "dark", r1=0.10)
    # exhaust: purifier canister + stack (rear right)
    p.cylinder((-4.40, -0.80, 1.96), (-4.40, -0.80, 2.18), 0.13, 12, "steel")
    p.cylinder((-4.40, -0.80, 2.18), (-4.40, -0.80, 2.21), 0.145, 12, "dark")
    p.cylinder((-4.40, -0.80, 2.21), (-4.40, -0.80, 2.34), 0.055, 8, "steel")
    p.cylinder((-4.40, -0.80, 2.34), (-4.28, -0.80, 2.38), 0.055, 8, "steel")
    # lifting eyes on the hood
    for x, y in ((-2.30, 0.95), (-4.40, 0.95), (-4.40, -0.40)):
        p.box((x - 0.06, y - 0.02, 2.0), (x + 0.06, y + 0.02, 2.16), "dark", bevel=False)
    # rear lamps recessed in the counterweight, and a rubber bumper
    for s in (1, -1):
        p.lamp((-5.19, s * 0.80, 1.32), (-1, 0, 0), r=0.09, depth=0.10, bracket=False)
        p.lamp((-5.19, s * 0.80, 1.08), (-1, 0, 0), r=0.06, depth=0.08, bracket=False)
    p.box((-5.24, -1.05, 0.64), (-5.16, 1.05, 0.84), "rubber", bevel=False)
    # rear tyre fender stays
    for s in (1, -1):
        y0, y1 = sorted((s * 0.62, s * 0.78))
        p.box((AXLE_R + 0.70, y0, 1.10), (AXLE_R + 0.84, y1, DECK_Z), "dark")
    return p.to_object(parent, bevel=0.022)


def build_cab(mats, parent, lod=False, part=None, name="lhd_v2_cab"):
    """Side-mounted enclosed cab on the left (+Y); operator sits across the machine."""
    p = part or Part(name, mats)
    bev = not lod
    # lower tub ahead of the left rear tyre
    p.prism_xz([(-0.28, 0.55), (-0.28, 1.38), (-0.92, 1.38), (-0.92, 0.55)], 0.14, 1.30, "paint", bev)
    if lod:
        p.box((-1.66, 0.14, DECK_Z), (-0.28, 1.30, 1.86), "paint", bevel=False)
        p.box((-1.62, 0.18, 1.86), (-0.32, 1.26, 2.22), "glass", bevel=False)
        p.box((-0.92, 0.14, 1.38), (-0.28, 1.30, 1.74), "paint", bevel=False)
        p.box((-0.88, 0.18, 1.74), (-0.32, 1.26, 1.86), "glass", bevel=False)
        for x, y in ((-0.36, 0.14), (-0.36, 1.22), (-1.66, 0.14), (-1.66, 1.22), (-0.98, 1.22)):
            p.box((x, y, 1.38 if x > -0.95 else DECK_Z), (x + 0.08, y + 0.08, 2.22), "paint", bevel=False)
        p.box((-1.74, 0.08, 2.22), (-0.20, 1.36, 2.32), "paint", bevel=False)
        p.box((-0.20, 0.40, 2.12), (-0.18, 0.56, 2.20), "lens", bevel=False)
        return p
    # pillars
    for y in (0.14, 1.22):
        p.box((-0.36, y, 1.38), (-0.28, y + 0.08, 2.22), "paint")
        p.box((-1.66, y, DECK_Z), (-1.58, y + 0.08, 2.22), "paint")
    p.box((-0.98, 1.22, 1.38), (-0.90, 1.30, 2.22), "paint")
    # inner wall (towards the tank), rear wall, sill under the rear side window
    p.box((-1.66, 0.14, 1.38), (-0.28, 0.20, 2.22), "paint")
    p.box((-1.66, 0.14, DECK_Z), (-1.60, 1.30, 1.86), "paint")
    p.box((-1.58, 1.24, DECK_Z), (-0.98, 1.30, 1.86), "paint")
    # door: lower panel + handle
    p.box((-0.90, 1.25, 1.38), (-0.36, 1.30, 1.74), "paint")
    p.box((-0.84, 1.30, 1.62), (-0.74, 1.32, 1.65), "steel", bevel=False)
    # glazing (inset, opaque glossy)
    p.box((-0.33, 0.20, 1.40), (-0.30, 1.22, 2.18), "glass", bevel=False)              # front
    p.box((-0.90, 1.255, 1.74), (-0.36, 1.275, 2.18), "glass", bevel=False)            # door
    p.box((-1.58, 1.255, 1.86), (-0.98, 1.275, 2.18), "glass", bevel=False)            # rear side
    p.box((-1.63, 0.20, 1.88), (-1.61, 1.22, 2.16), "glass", bevel=False)              # rear
    # roof (ROPS/FOPS) with a front lip
    p.box((-1.74, 0.08, 2.22), (-0.20, 1.36, 2.32), "paint")
    p.box((-0.22, 0.08, 2.15), (-0.18, 1.36, 2.22), "paint")
    # roof lamps: two forward, one rearward
    for y in (0.40, 1.10):
        p.lamp((-0.10, y, 2.22), (1, 0, 0), r=0.06, depth=0.10, bracket=False)
    p.lamp((-1.84, 0.70, 2.22), (-1, 0, 0), r=0.06, depth=0.10, bracket=False)
    # beacon base on the roof (no colour: the scene owns the state colours)
    p.cylinder((-1.30, 1.10, 2.32), (-1.30, 1.10, 2.40), 0.07, 10, "dark")
    # mirror on an arm at the front outer corner
    p.cylinder((-0.30, 1.28, 2.05), (-0.10, 1.48, 2.08), 0.018, 6, "dark")
    p.box((-0.12, 1.44, 1.86), (-0.08, 1.58, 2.10), "dark", bevel=False)
    p.box((-0.135, 1.455, 1.88), (-0.12, 1.565, 2.08), "glass", bevel=False)
    # steps and a grab handle below the door
    for z in (0.62, 1.00):
        p.box((-0.84, 1.18, z), (-0.40, 1.36, z + 0.04), "steel", bevel=False)
    for x in (-0.86, -0.42):
        p.box((x, 1.32, 0.56), (x + 0.04, 1.36, 1.06), "steel", bevel=False)
    p.cylinder((-0.38, 1.33, 1.42), (-0.38, 1.33, 2.10), 0.022, 6, "steel")
    # seat back visible through the glass
    p.box((-0.82, 0.22, 1.40), (-0.46, 0.36, 1.96), "rubber")
    return p.to_object(parent, bevel=0.016)


# --------------------------------------------------------------------------- assembly


def empty(name, parent=None):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = "PLAIN_AXES"
    ob.empty_display_size = 0.5
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = parent
    return ob


WHEELS = (("fl", AXLE_F, "l"), ("fr", AXLE_F, "r"), ("rl", AXLE_R, "l"), ("rr", AXLE_R, "r"))


def build_full(mats):
    root = empty("lhd_v2")
    front = empty("lhd_v2_front", root)
    rear = empty("lhd_v2_rear", root)
    objs = [root, front, rear,
            build_front_frame(mats, front), build_boom(mats, front), build_bucket(mats, front),
            build_rear_frame(mats, rear), build_cab(mats, rear)]
    for tag, x, side in WHEELS:
        objs.append(build_wheel(mats, front if x > 0 else rear, f"lhd_v2_wheel_{tag}", x, side))
    return objs


def build_lod(mats):
    root = empty("lhd_v2_lod")
    front = empty("lhd_v2_lod_front", root)
    rear = empty("lhd_v2_lod_rear_group", root)
    objs = [root, front, rear,
            build_front_frame(mats, front, lod=True, name="lhd_v2_lod_front_frame"),
            build_bucket(mats, front, lod=True, name="lhd_v2_lod_bucket")]
    p = build_rear_frame(mats, rear, lod=True, name="lhd_v2_lod_rear")
    build_cab(mats, rear, lod=True, part=p)
    objs.append(p.to_object(rear, bevel=0.0, smooth_angle=30.0))
    for tag, x, side in WHEELS:
        objs.append(build_wheel(mats, front if x > 0 else rear, f"lhd_v2_lod_wheel_{tag}", x, side, lod=True))
    return objs


# --------------------------------------------------------------------------- export + checks


def export_glb(objs, path, note):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=path, export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
        export_texcoords=False, export_normals=True, export_tangents=False, export_materials="EXPORT",
        export_vertex_color="NONE", export_attributes=False, export_image_format="NONE",
        export_cameras=False, export_lights=False, export_extras=False, export_animations=False,
        export_skins=False, export_morph=False, export_draco_mesh_compression_enable=False,
        export_copyright=note)
    for o in objs:
        o.select_set(False)


def inspect_glb(path):
    """Count triangles and check the budget straight from the exported file."""
    with open(path, "rb") as fh:
        data = fh.read()
    magic, version, _ = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67 and version == 2, "not a glTF 2.0 binary"
    clen, ctype = struct.unpack_from("<II", data, 12)
    assert ctype == 0x4E4F534A
    gltf = json.loads(data[20:20 + clen])
    acc = gltf["accessors"]
    tris = 0
    per_mesh = {}
    for node in gltf.get("nodes", []):
        assert "rotation" not in node and "scale" not in node, "unexpected node rotation/scale"
        if "mesh" not in node:
            continue
        t = 0
        for prim in gltf["meshes"][node["mesh"]]["primitives"]:
            assert prim.get("mode", 4) == 4
            t += acc[prim["indices"]]["count"] // 3
        per_mesh[node["name"]] = t
        tris += t
    return {
        "bytes": len(data), "triangles": tris, "per_mesh": per_mesh,
        "draw_primitives": sum(len(m["primitives"]) for m in gltf["meshes"]),
        "materials": [m["name"] for m in gltf.get("materials", [])],
        "images": len(gltf.get("images", [])), "textures": len(gltf.get("textures", [])),
        "extensionsUsed": gltf.get("extensionsUsed", []),
    }


def world_bounds(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = -lo
    for ob in objs:
        if ob.type != "MESH":
            continue
        for v in ob.data.vertices:
            w = ob.matrix_world @ v.co
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


# --------------------------------------------------------------------------- previews


def setup_preview_rig():
    scene = bpy.context.scene
    world = bpy.data.worlds.new("graphite")
    if getattr(world, "node_tree", None) is None:
        world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = hex_rgba("#0E1012")
    scene.world = world
    desk_mat = principled("preview_desk", "#191B1E", 0.9)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=60.0)
    me = bpy.data.meshes.new("preview_desk")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(desk_mat)
    desk = bpy.data.objects.new("preview_desk", me)
    scene.collection.objects.link(desk)

    def area(name, color, energy, size, loc, target):
        ld = bpy.data.lights.new(name, "AREA")
        ld.color = hex_rgba(color)[:3]
        ld.energy = energy
        ld.size = size
        ob = bpy.data.objects.new(name, ld)
        ob.location = loc
        ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(ob)

    area("key_warm", "#FFD7A1", 1500, 7.0, (6.0, 7.5, 8.0), (0, 0, 0.8))
    area("fill_cool", "#B9C6D2", 900, 9.0, (5.0, -8.0, 4.0), (0, 0, 1.0))
    area("rim_verdigris", "#9FF5DF", 1100, 5.0, (-9.0, 4.0, 5.0), (0, 0, 1.0))
    area("top_soft", "#D9DDE2", 700, 10.0, (0.0, 0.0, 10.0), (0, 0, 0))


def make_camera(name, loc, target, ortho_scale=None, lens=50.0):
    cd = bpy.data.cameras.new(name)
    if ortho_scale:
        cd.type = "ORTHO"
        cd.ortho_scale = ortho_scale
    else:
        cd.lens = lens
    cd.clip_start = 0.1
    cd.clip_end = 200
    ob = bpy.data.objects.new(name, cd)
    ob.location = loc
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(ob)
    return ob


def configure_render(engine):
    scene = bpy.context.scene
    scene.render.engine = engine
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    if engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = SAMPLES
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.use_denoising = True
        scene.cycles.max_bounces = 6


def set_visible(objs, visible):
    for o in objs:
        o.hide_render = not visible
        o.hide_viewport = not visible


def render_previews(full, lod):
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    scene = bpy.context.scene
    cams = {
        "q": make_camera("cam_three_quarter", (9.6, 8.4, 4.4), (0.0, 0.0, 0.85), lens=42),
        "r": make_camera("cam_rear_quarter", (-9.4, -8.0, 4.6), (-0.4, 0.0, 0.9), lens=42),
        "s": make_camera("cam_side", (-0.1, 25.0, 1.2), (-0.1, 0.0, 1.2), ortho_scale=11.4),
        "t": make_camera("cam_top", (-0.1, 0.0, 25.0), (-0.1, 0.0, 0.0), ortho_scale=11.4),
        "m": make_camera("cam_mid", (14.0, 15.0, 13.0), (0.0, 0.0, 0.8), lens=50),
    }
    cams["t"].rotation_euler = (0.0, 0.0, 0.0)
    shots = [("lhd_v2_three_quarter", "q", 1200, 800, full), ("lhd_v2_rear_quarter", "r", 1200, 800, full),
             ("lhd_v2_side", "s", 1200, 800, full), ("lhd_v2_top", "t", 1200, 800, full),
             ("lhd_v2_mid_zoom_320", "m", 320, 214, full), ("lhd_v2_lod_three_quarter", "q", 1200, 800, lod),
             ("lhd_v2_lod_mid_zoom_320", "m", 320, 214, lod)]
    configure_render("CYCLES")
    for name, cam, w, h, show in shots:
        set_visible(full, show is full)
        set_visible(lod, show is lod)
        scene.camera = cams[cam]
        scene.render.resolution_x, scene.render.resolution_y = w, h
        scene.render.resolution_percentage = 100
        scene.render.filepath = os.path.join(PREVIEW_DIR, name + ".png")
        t = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        print(f"[lhd_v2] rendered {name}.png {w}x{h} in {time.perf_counter() - t:.1f} s")
    set_visible(full, True)
    set_visible(lod, False)
    scene.camera = cams["q"]


# --------------------------------------------------------------------------- run


def main():
    reset_scene()
    mats = make_materials()
    full = build_full(mats)
    lod = build_lod(mats)
    lo, hi = world_bounds(full)
    print(f"[lhd_v2] full bounds (Blender, m): min {tuple(round(c, 3) for c in lo)} max {tuple(round(c, 3) for c in hi)}")
    export_glb(full, GLB_PATH, "Team repository licence (MIT); authored by Claude, procedural Blender 5.1 script lhd_v2.py")
    export_glb(lod, GLB_LOD_PATH, "Team repository licence (MIT); authored by Claude, procedural Blender 5.1 script lhd_v2.py (LOD)")
    info = inspect_glb(GLB_PATH)
    info_lod = inspect_glb(GLB_LOD_PATH)
    print("[lhd_v2] glb", json.dumps(info, indent=1))
    print("[lhd_v2] lod glb", json.dumps(info_lod, indent=1))
    problems = []
    for i, cap, label in ((info, MAX_TRIANGLES, "full"), (info_lod, MAX_TRIANGLES_LOD, "lod")):
        if i["triangles"] > cap:
            problems.append(f"{label}: {i['triangles']} triangles > {cap}")
        if i["images"] or i["textures"]:
            problems.append(f"{label}: textures present")
        if i["extensionsUsed"]:
            problems.append(f"{label}: extensions {i['extensionsUsed']}")
    setup_preview_rig()
    set_visible(lod, False)
    if DO_RENDER:
        render_previews(full, lod)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH, compress=True)
    if os.path.exists(BLEND_PATH + "1"):
        os.remove(BLEND_PATH + "1")
    print(f"[lhd_v2] total {time.perf_counter() - T0:.1f} s; full {info['triangles']} tris {info['bytes']} B; "
          f"lod {info_lod['triangles']} tris {info_lod['bytes']} B")
    if problems:
        print("[lhd_v2] BUDGET FAILED: " + "; ".join(problems))
        if bpy.app.background:
            sys.exit(1)
        raise RuntimeError("; ".join(problems))
    print("[lhd_v2] budget ok")


main()
