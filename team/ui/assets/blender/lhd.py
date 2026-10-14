"""
lhd.py - procedural generator of an underground load-haul-dump machine (LHD, "ПДМ"),
10-tonne class, for the dispatcher UI of the team's fictional copper mine.

Provenance
    Authored by Claude (Anthropic) on 14 October 2026 as this Python script, run
    with the Blender 5.1 command line (headless). It was NOT made through
    Blender MCP. No external models, textures, HDRIs or add-ons are used: every
    vertex is produced by the code below. Licence: the repository's licence (MIT).

What it builds (static "parked" pose: bucket lowered and level, frames straight)
    - articulated chassis: front loader frame with a tower, rear power-unit frame,
      centre articulation joint (hinge plates, vertical pin, two steering cylinders)
    - wide bucket (worn steel) on two lift arms, two lift cylinders,
      a central tilt cylinder with a Z-bar bellcrank and link
    - rear engine hood sloping down to the rear, counterweight, louvres, exhaust,
      air precleaner, hydraulic tank on the right
    - low side-mounted ROPS canopy on the left with a transverse operator seat
      (the operator sits sideways), steps and grab handles
    - four 1.65 m tyres with staggered tread lugs made of geometry, painted rims
    - fenders, front / canopy / rear lamps (non-emissive lenses; the scene lights them)

Dimensions (metres, real-world scale)
    length 10.00 (bucket cutting edge +4.80 ... rear lamp lenses -5.20)
    width   2.60   height 2.30 at the canopy roof   wheelbase 3.50
    axles at x = +1.75 (front) and x = -1.75 (rear), tyre diameter 1.65
    origin: ground level (z = 0) under the centre of the articulation joint

Axes
    Blender: +X forward, +Y left, +Z up. The glTF exporter converts to Y-up,
    so the exported scene has forward = +X, up = +Y, left = -Z.

Budget (checked by this script after export; it exits with an error if exceeded)
    <= 8 000 triangles in the glb, <= 5 materials, no textures/images,
    no Draco, no glTF extensions; modifiers applied; flat object hierarchy under
    an empty "lhd".

Materials (Principled BSDF, no image textures)
    lhd_paint_graphite #3A4148, lhd_steel_worn #6E6A64, lhd_rubber #1C1D1F,
    lhd_lens (warm white, not emissive), lhd_copper #C8834F (only the two
    articulation pin caps: copper is the UI selection colour, so the model keeps it rare).
    Metallic is kept low on purpose: in three.js a fully metallic material with
    no environment map renders almost black.

Outputs (paths relative to this file)
    ./lhd.blend                         saved source scene (model + preview rig)
    ../../public/models/lhd.glb         optimised export for the browser
    ./previews/lhd_three_quarter.png    1200x800, three-quarter front
    ./previews/lhd_side.png             1200x800, left side (orthographic)
    ./previews/lhd_top.png              1200x800, top (orthographic)
    ./previews/lhd_small_300.png        300x200 silhouette check

Rebuild everything from the repository root (Windows example):
    "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" -b --factory-startup --python team/ui/assets/blender/lhd.py
Plain `blender -b --python team/ui/assets/blender/lhd.py` works too: the script
empties the current file itself and sets every export and render option explicitly.
Options after "--":
    --no-render     build, save and export only (skip the preview renders)
    --samples N     Cycles samples for previews (default 64)
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

# --------------------------------------------------------------------------- paths


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
BLEND_PATH = os.path.join(HERE, "lhd.blend")
GLB_PATH = os.path.join(UI_ROOT, "public", "models", "lhd.glb")
PREVIEW_DIR = os.path.join(HERE, "previews")

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
DO_RENDER = "--no-render" not in ARGS
SAMPLES = int(ARGS[ARGS.index("--samples") + 1]) if "--samples" in ARGS else 64

MAX_TRIANGLES = 8000
MAX_MATERIALS = 5

# --------------------------------------------------------------------------- main dimensions

AXLE_F = 1.75          # front axle x
AXLE_R = -1.75         # rear axle x
WHEEL_Z = 0.825        # axle height = tyre radius incl. lugs (0.775 + 0.05)
WHEEL_Y = 1.04         # tyre centre |y|; tyre width 0.52 -> outer face at 1.30
DECK_Z = 1.72          # top of the rear deck / fenders over the rear tyres

# --------------------------------------------------------------------------- scene reset


def reset_scene():
    """Empty the current file without touching user preferences."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                 bpy.data.cameras, bpy.data.worlds, bpy.data.images,
                 bpy.data.node_groups):
        for block in list(coll):
            coll.remove(block)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    scene = bpy.context.scene
    scene.name = "lhd"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


# --------------------------------------------------------------------------- materials


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_rgba(h):
    h = h.lstrip("#")
    return tuple(srgb_to_linear(int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4)) + (1.0,)


def principled(name, hex_color, roughness, metallic=0.0):
    mat = bpy.data.materials.new(name)
    if getattr(mat, "node_tree", None) is None:
        mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    rgba = hex_rgba(hex_color)
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    mat.diffuse_color = rgba          # viewport / workbench colour
    mat.roughness = roughness
    mat.metallic = metallic
    return mat


def make_materials():
    return {
        "paint": principled("lhd_paint_graphite", "#3A4148", 0.55, 0.15),
        "steel": principled("lhd_steel_worn", "#6E6A64", 0.62, 0.35),
        "rubber": principled("lhd_rubber", "#1C1D1F", 0.92, 0.0),
        "lens": principled("lhd_lens", "#EFE6D6", 0.18, 0.0),
        "copper": principled("lhd_copper", "#C8834F", 0.42, 0.45),
    }


# --------------------------------------------------------------------------- mesh builder


class Part:
    """A bmesh plus its material slots; becomes one Blender object."""

    def __init__(self, name, mats, slots):
        self.name = name
        self.bm = bmesh.new()
        # vertices of round or tiny parts are flagged so the bevel skips them
        self.nobevel = self.bm.verts.layers.int.new("nobevel")
        self.slots = list(slots)
        self.mats = mats

    def _idx(self, slot):
        return self.slots.index(slot)

    def _flag(self, verts, bevel):
        if not bevel:
            for v in verts:
                v[self.nobevel] = 1

    # -- primitives ---------------------------------------------------------

    def box(self, mn, mx, slot="paint", bevel=True):
        (x0, y0, z0), (x1, y1, z1) = mn, mx
        bm = self.bm
        v = [bm.verts.new(p) for p in (
            (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))]
        self._flag(v, bevel)
        faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        for f in faces:
            bm.faces.new([v[i] for i in f]).material_index = self._idx(slot)

    def prism_xz(self, pts, y0, y1, slot="paint", bevel=True):
        """Polygon in the XZ plane (side profile), extruded from y0 to y1."""
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

    def strip_xz(self, line, thick, y0, y1, slot="paint", bevel=True):
        """A plate of thickness `thick` following a polyline in XZ, extruded in Y."""
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

    def cylinder(self, p0, p1, r, sides=10, slot="paint", caps=True):
        p0, p1 = Vector(p0), Vector(p1)
        d = (p1 - p0).normalized()
        u = d.orthogonal().normalized()
        w = d.cross(u).normalized()
        bm = self.bm
        m = self._idx(slot)
        ring0, ring1 = [], []
        for k in range(sides):
            a = 2 * math.pi * (k + 0.5) / sides
            off = (u * math.cos(a) + w * math.sin(a)) * r
            ring0.append(bm.verts.new(p0 + off))
            ring1.append(bm.verts.new(p1 + off))
        self._flag(ring0 + ring1, False)       # cylinders are never bevelled
        for k in range(sides):
            j = (k + 1) % sides
            bm.faces.new((ring0[k], ring0[j], ring1[j], ring1[k])).material_index = m
        if caps:
            bm.faces.new(list(reversed(ring0))).material_index = m
            bm.faces.new(ring1).material_index = m

    def hydraulic(self, base, tip, r_barrel, frac=0.62, sides=10):
        """Barrel (paint) from base, chrome-ish rod (steel) to tip, eye ends."""
        base, tip = Vector(base), Vector(tip)
        mid = base.lerp(tip, frac)
        self.cylinder(base, mid, r_barrel, sides, "paint")
        self.cylinder(mid, tip, r_barrel * 0.5, 8, "steel")

    # -- finishing ----------------------------------------------------------

    def to_object(self, parent, bevel=0.0, smooth_angle=40.0):
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts, dist=1e-5)
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces)
        if bevel > 0:
            # mark only the hard edges of flat-sided parts for the chamfer
            bw = self.bm.edges.layers.float.new("bevel_weight_edge")
            limit = math.radians(35)
            for e in self.bm.edges:
                if (e.is_manifold and not (e.verts[0][self.nobevel] or e.verts[1][self.nobevel])
                        and e.calc_face_angle(0.0) > limit):
                    e[bw] = 1.0
        self.bm.verts.layers.int.remove(self.nobevel)
        me = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(me)
        self.bm.free()
        ob = bpy.data.objects.new(self.name, me)
        bpy.context.scene.collection.objects.link(ob)
        for s in self.slots:
            me.materials.append(self.mats[s])
        ob.parent = parent
        finish_object(ob, bevel, smooth_angle)
        return ob


def finish_object(ob, bevel, smooth_angle):
    """Bevel (chamfer) the hard edges, mark sharp by angle, weighted normals, apply."""
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


# --------------------------------------------------------------------------- the machine


def build_front_frame(mats, root):
    p = Part("lhd_body_front", mats, ["paint", "steel"])
    # main box frame between the front tyres (tyre inner faces at |y| = 0.78)
    p.box((0.30, -0.50, 0.42), (2.95, 0.50, 1.10))
    # nose / bumper ahead of the tyres
    p.prism_xz([(2.60, 0.45), (3.05, 0.45), (3.05, 0.95), (2.90, 1.12), (2.60, 1.12)],
               -0.52, 0.52)
    # tower carrying the lift-arm and tilt-cylinder pivots
    p.prism_xz([(0.30, 1.05), (1.35, 1.05), (1.20, 1.70), (1.00, 1.95),
                (0.55, 1.97), (0.30, 1.70)], -0.53, 0.53)
    # front fenders: thin plates arching over the tyres
    for s in (1, -1):
        y0, y1 = sorted((s * 0.74, s * 1.30))
        p.strip_xz([(AXLE_F - 1.02, 1.18), (AXLE_F - 0.80, 1.70),
                    (AXLE_F + 0.80, 1.70), (AXLE_F + 1.00, 1.18)], 0.05, y0, y1)
        # fender stays down to the frame
        y0, y1 = sorted((s * 0.50, s * 0.76))
        p.box((AXLE_F - 0.95, y0, 0.95), (AXLE_F - 0.80, y1, 1.62))
        p.box((AXLE_F + 0.80, y0, 0.95), (AXLE_F + 0.95, y1, 1.62))
        # lift-cylinder base brackets
        y0, y1 = sorted((s * 0.48, s * 0.74))
        p.box((1.05, y0, 0.62), (1.42, y1, 0.98))
    # skid / belly plate (steel)
    p.box((0.45, -0.46, 0.36), (2.85, 0.46, 0.43), "steel")
    return p.to_object(root, bevel=0.025)


def build_rear_body(mats, root):
    p = Part("lhd_body_rear", mats, ["paint", "steel", "rubber"])
    # central frame between the rear tyres
    p.box((-2.70, -0.70, 0.45), (-0.30, 0.70, DECK_Z - 0.08))
    # deck over the rear tyres (fender line), full width
    p.box((-2.62, -1.30, DECK_Z - 0.08), (-0.95, 1.30, DECK_Z))
    # fender skirts in front of / behind the rear tyres
    for s in (1, -1):
        y0, y1 = sorted((s * 0.72, s * 1.30))
        p.strip_xz([(AXLE_R + 0.98, 1.20), (AXLE_R + 0.80, DECK_Z - 0.04)], 0.05, y0, y1)
    # lower rear body behind the rear tyres (transmission, engine bay)
    p.box((-4.87, -1.25, 0.50), (-2.62, 1.25, DECK_Z))
    # engine hood, sloping down to the rear for visibility when reversing
    p.prism_xz([(-1.68, DECK_Z), (-1.68, 1.98), (-1.88, 2.08), (-4.15, 2.00),
                (-4.87, 1.80), (-4.87, DECK_Z)], -1.18, 1.18)
    # hydraulic tank on the right, beside the canopy, merging into the hood
    p.prism_xz([(-0.30, 0.52), (-0.30, 1.50), (-0.55, 1.84), (-1.70, 1.94),
                (-1.70, DECK_Z), (-0.95, DECK_Z), (-0.95, 0.52)], -1.28, 0.10)
    # counterweight with chamfered top and bottom
    p.prism_xz([(-4.85, 0.42), (-4.85, 1.80), (-5.00, 1.80), (-5.17, 1.55),
                (-5.17, 0.62), (-5.05, 0.42)], -1.24, 1.24)
    # air precleaner and its cap on the hood (right front)
    p.cylinder((-2.05, -0.72, 2.0), (-2.05, -0.72, 2.20), 0.13, 12)
    # exhaust (steel) at the hood rear right
    p.cylinder((-4.35, -0.82, 1.88), (-4.35, -0.82, 2.16), 0.065, 8, "steel")
    p.cylinder((-4.35, -0.82, 2.16), (-4.22, -0.82, 2.20), 0.065, 8, "steel")
    # louvres on the sides of the engine bay
    for s in (1, -1):
        y0, y1 = sorted((s * 1.25, s * 1.29))
        for k in range(4):
            z = 0.98 + k * 0.15
            p.box((-4.60, y0, z), (-3.00, y1, z + 0.06), "steel", bevel=False)
    # rear bumper strip (rubber)
    p.box((-5.19, -1.0, 0.62), (-5.13, 1.0, 0.82), "rubber", bevel=False)
    return p.to_object(root, bevel=0.025)


def build_canopy(mats, root):
    """Low side-mounted operator compartment on the left (+Y), ROPS canopy."""
    p = Part("lhd_canopy", mats, ["paint", "steel", "rubber"])
    # cab tub ahead of the left rear tyre
    p.prism_xz([(-0.30, 0.55), (-0.30, 1.30), (-0.95, 1.30), (-0.95, 0.55)], 0.14, 1.30)
    # ROPS posts: front pair on the tub, rear pair on the deck
    for y in (0.20, 1.24):
        p.box((-0.38, y - 0.06, 1.30), (-0.26, y + 0.06, 2.20))
        p.box((-1.66, y - 0.06, DECK_Z), (-1.54, y + 0.06, 2.20))
    # diagonal brace on the inner side (between canopy and hood)
    p.strip_xz([(-0.32, 1.40), (-1.60, 2.12)], 0.08, 0.15, 0.25)
    # roof plate with a slight front lip
    p.box((-1.70, 0.12, 2.20), (-0.24, 1.30, 2.30))
    p.box((-0.30, 0.12, 2.12), (-0.24, 1.30, 2.20))
    # low side guard rail on the open outer side
    p.box((-1.60, 1.22, 1.62), (-0.32, 1.30, 1.70))
    # operator seat, transverse: back to the machine centre, facing outward (+Y)
    p.box((-0.88, 0.40, 1.02), (-0.40, 0.92, 1.18), "rubber")        # cushion
    p.box((-0.88, 0.28, 1.12), (-0.40, 0.42, 1.78), "rubber")        # backrest
    p.box((-0.84, 0.50, 0.75), (-0.44, 0.84, 1.02), "paint", bevel=False)  # seat base
    # control console with two levers
    p.box((-0.95, 0.40, 1.15), (-0.88, 1.10, 1.38), "paint", bevel=False)
    for y in (0.62, 0.86):
        p.cylinder((-0.92, y, 1.38), (-0.90, y, 1.55), 0.02, 6, "steel")
    # steps on the outer side below the tub (steel)
    p.box((-0.85, 1.12, 0.48), (-0.40, 1.30, 0.52), "steel", bevel=False)
    p.box((-0.82, 1.27, 0.52), (-0.78, 1.30, 0.75), "steel", bevel=False)
    p.box((-0.47, 1.27, 0.52), (-0.43, 1.30, 0.75), "steel", bevel=False)
    # grab handles (steel: copper is the UI selection colour, so it stays rare on the model)
    p.cylinder((-0.45, 1.24, 1.36), (-0.45, 1.24, 2.02), 0.022, 6, "steel")
    p.cylinder((-0.38, 1.24, 1.36), (-0.45, 1.24, 1.36), 0.018, 6, "steel")
    p.cylinder((-0.38, 1.24, 2.02), (-0.45, 1.24, 2.02), 0.018, 6, "steel")
    return p.to_object(root, bevel=0.018)


def build_joint(mats, root):
    p = Part("lhd_joint", mats, ["paint", "steel", "copper"])
    # front clevis plates (upper and lower) reaching back across the joint
    p.prism_xz([(0.32, 0.98), (0.32, 1.10), (-0.10, 1.10), (-0.18, 1.04), (-0.10, 0.98)],
               -0.30, 0.30)
    p.prism_xz([(0.32, 0.42), (0.32, 0.54), (-0.10, 0.54), (-0.18, 0.48), (-0.10, 0.42)],
               -0.30, 0.30)
    # rear hinge block between the plates
    p.prism_xz([(-0.32, 0.58), (0.06, 0.58), (0.12, 0.66), (0.12, 0.90),
                (0.06, 0.96), (-0.32, 0.96)], -0.24, 0.24)
    # vertical articulation pin with copper caps
    p.cylinder((0.0, 0.0, 0.38), (0.0, 0.0, 1.13), 0.085, 10, "steel")
    p.cylinder((0.0, 0.0, 1.10), (0.0, 0.0, 1.15), 0.12, 10, "copper")
    p.cylinder((0.0, 0.0, 0.36), (0.0, 0.0, 0.41), 0.12, 10, "copper")
    # steering cylinders across the joint, one on each side
    for s in (1, -1):
        p.hydraulic((-0.32, s * 0.60, 0.84), (0.62, s * 0.58, 0.84), 0.075, 0.55)
        y0, y1 = sorted((s * 0.50, s * 0.68))
        p.box((0.55, y0, 0.74), (0.75, y1, 0.94))
    return p.to_object(root, bevel=0.015)


def build_lift_arms(mats, root):
    p = Part("lhd_lift_arms", mats, ["paint", "steel"])
    pivot = (0.98, 1.64)
    knee1 = (2.40, 1.46)
    knee2 = (2.88, 1.06)
    bucket_pin = (3.29, 0.52)
    for s in (1, -1):
        y0, y1 = sorted((s * 0.54, s * 0.72))
        p.strip_xz([pivot, knee1, knee2, bucket_pin], 0.30, y0, y1)
        # pin bosses
        p.cylinder((pivot[0], s * 0.50, pivot[1]), (pivot[0], s * 0.76, pivot[1]), 0.16, 10)
        p.cylinder((bucket_pin[0], s * 0.50, bucket_pin[1]),
                   (bucket_pin[0], s * 0.76, bucket_pin[1]), 0.13, 10)
        # lug under the arm for the lift cylinder
        p.box((2.05, y0, 1.20), (2.31, y1, 1.40))
    # cross tube between the arms carrying the bellcrank
    p.cylinder((2.45, -0.72, 1.42), (2.45, 0.72, 1.42), 0.10, 10)
    # Z-bar bellcrank (pair of plates) and the link to the bucket
    for y in (0.08, -0.08):
        y0, y1 = sorted((y, y + (0.06 if y > 0 else -0.06)))
        p.strip_xz([(2.30, 1.98), (2.45, 1.42), (2.60, 1.00)], 0.22, y0, y1)
    p.strip_xz([(2.60, 1.00), (3.27, 0.96)], 0.14, -0.07, 0.07)
    return p.to_object(root, bevel=0.015)


def build_hydraulics(mats, root):
    p = Part("lhd_hydraulics", mats, ["paint", "steel"])
    for s in (1, -1):
        # lift cylinders: bracket on the frame -> lug under the arm
        p.hydraulic((1.24, s * 0.63, 0.82), (2.18, s * 0.63, 1.30), 0.085, 0.6)
    # central tilt cylinder: tower top -> bellcrank top
    p.hydraulic((0.80, 0.0, 1.90), (2.30, 0.0, 1.98), 0.11, 0.58)
    return p.to_object(root, bevel=0.0, smooth_angle=40.0)


def build_bucket(mats, root):
    """4.5 m3-class bucket, 2.58 m wide, lowered and level; all worn steel."""
    p = Part("lhd_bucket", mats, ["steel"])
    lip_x = 4.76
    # shell: floor, curved back, top plate (spill guard)
    p.strip_xz([(lip_x, 0.065), (3.60, 0.065), (3.43, 0.16), (3.35, 0.40),
                (3.35, 0.84), (3.43, 1.08), (3.98, 1.15)], 0.06, -1.22, 1.22, "steel")
    # side plates with the sloped front edge typical of LHD buckets
    side = [(lip_x + 0.02, 0.03), (lip_x - 0.02, 0.28), (4.00, 1.18), (3.41, 1.12),
            (3.31, 0.86), (3.31, 0.38), (3.41, 0.12), (3.61, 0.03)]
    for s in (1, -1):
        y0, y1 = sorted((s * 1.21, s * 1.29))
        p.prism_xz(side, y0, y1, "steel")
    # cutting edge (thick wear plate) at the lip
    p.prism_xz([(4.37, 0.035), (4.80, 0.035), (4.80, 0.07), (4.69, 0.12), (4.37, 0.12)],
               -1.22, 1.22, "steel")
    # wear strips under the floor
    for y in (-0.85, -0.28, 0.28, 0.85):
        p.box((3.67, y - 0.07, 0.0), (4.50, y + 0.07, 0.04), "steel")
    # top reinforcement bar along the spill guard
    p.box((3.39, -1.22, 1.12), (3.55, 1.22, 1.22), "steel")
    # pin lugs on the back: two for the arms, one for the tilt link
    for s in (1, -1):
        y0, y1 = sorted((s * 0.50, s * 0.76))
        p.prism_xz([(3.13, 0.42), (3.21, 0.34), (3.37, 0.30), (3.37, 0.74), (3.21, 0.70)],
                   y0, y1, "steel")
    p.prism_xz([(3.17, 0.90), (3.25, 0.84), (3.37, 0.82), (3.37, 1.10), (3.25, 1.06)],
               -0.16, 0.16, "steel")
    return p.to_object(root, bevel=0.012)


def build_tyre(mats, root, name, x, side, segments=22):
    """Tyre with staggered tread lugs plus a painted rim, revolved around Y."""
    p = Part(name, mats, ["rubber", "paint"])
    bm = p.bm
    s = 1 if side == "l" else -1
    yc = s * WHEEL_Y
    # profile (radius, lateral offset outward positive) from inner to outer bead
    prof = [(0.34, -0.21), (0.69, -0.258), (0.765, -0.225),
            (0.775, -0.04), (0.775, 0.04), (0.765, 0.225), (0.71, 0.258),
            (0.56, 0.255), (0.34, 0.21)]
    # outer rim dish (paint) continuing from the outer bead to the hub
    rim = [(0.34, 0.21), (0.31, 0.13), (0.16, 0.13), (0.0, 0.16)]
    inner_rim = [(0.0, -0.16), (0.34, -0.21)]

    def ring(r, yl, a):
        return (x + r * math.cos(a), yc + s * yl, WHEEL_Z + r * math.sin(a))

    full = inner_rim[:-1] + prof + rim[1:]
    first_rubber = len(inner_rim) - 1          # index of prof[0] within `full`
    last_rubber = first_rubber + len(prof) - 2   # last edge that lies on the tyre
    mat_of_edge = [0 if first_rubber <= i <= last_rubber else 1 for i in range(len(full) - 1)]
    angles = [2 * math.pi * k / segments for k in range(segments)]
    grid = []
    for a in angles:
        col = []
        for r, yl in full:
            col.append(bm.verts.new(ring(r, yl, a)) if r > 0 else None)
        grid.append(col)
    centres = [bm.verts.new((x, yc + s * full[0][1], WHEEL_Z)),
               bm.verts.new((x, yc + s * full[-1][1], WHEEL_Z))]
    tread_faces = {}
    for k in range(segments):
        k2 = (k + 1) % segments
        for i in range(len(full) - 1):
            a0, a1 = grid[k][i], grid[k][i + 1]
            b0, b1 = grid[k2][i], grid[k2][i + 1]
            if a0 is None:            # fan to the inner centre
                f = bm.faces.new((centres[0], b1, a1))
            elif a1 is None:          # fan to the hub centre
                f = bm.faces.new((a0, b0, centres[1]))
            else:
                f = bm.faces.new((a0, b0, b1, a1))
            f.material_index = mat_of_edge[i]
            tread_faces[(k, i)] = f
    # staggered lugs: left shoulder band on even segments, right on odd
    left_band, right_band = first_rubber + 2, first_rubber + 4
    for k in range(segments):
        f = tread_faces[(k, left_band if k % 2 == 0 else right_band)]
        ret = bmesh.ops.extrude_face_region(bm, geom=[f])
        verts = [v for v in ret["geom"] if isinstance(v, bmesh.types.BMVert)]
        for v in verts:
            radial = Vector((v.co.x - x, 0.0, v.co.z - WHEEL_Z)).normalized()
            v.co += radial * 0.05
    return p.to_object(root, bevel=0.0, smooth_angle=50.0)


def build_lamps(mats, root):
    p = Part("lhd_lamps", mats, ["paint", "lens"])
    # front working lamps on the front fenders, facing +X
    for s in (1, -1):
        yc = s * 1.02
        p.box((2.48, yc - 0.11, 1.72), (2.68, yc + 0.11, 1.90))
        p.box((2.68, yc - 0.085, 1.745), (2.70, yc + 0.085, 1.875), "lens")
    # canopy lamps: two forward, one rearward
    for yc in (0.48, 1.02):
        p.box((-0.24, yc - 0.09, 2.10), (-0.12, yc + 0.09, 2.20))
        p.box((-0.12, yc - 0.07, 2.115), (-0.105, yc + 0.07, 2.185), "lens")
    p.box((-1.82, 0.62, 2.10), (-1.70, 0.80, 2.20))
    p.box((-1.835, 0.64, 2.115), (-1.82, 0.78, 2.185), "lens")
    # rear lamps recessed in the counterweight, facing -X
    for s in (1, -1):
        yc = s * 0.86
        p.box((-5.19, yc - 0.13, 1.22), (-5.15, yc + 0.13, 1.42))
        p.box((-5.20, yc - 0.10, 1.245), (-5.19, yc + 0.10, 1.395), "lens")
    return p.to_object(root, bevel=0.0, smooth_angle=30.0)


def build_machine(mats):
    root = bpy.data.objects.new("lhd", None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.5
    bpy.context.scene.collection.objects.link(root)
    objs = [root]
    objs.append(build_front_frame(mats, root))
    objs.append(build_rear_body(mats, root))
    objs.append(build_canopy(mats, root))
    objs.append(build_joint(mats, root))
    objs.append(build_lift_arms(mats, root))
    objs.append(build_hydraulics(mats, root))
    objs.append(build_bucket(mats, root))
    objs.append(build_lamps(mats, root))
    for name, x, side in (("lhd_tyre_fl", AXLE_F, "l"), ("lhd_tyre_fr", AXLE_F, "r"),
                          ("lhd_tyre_rl", AXLE_R, "l"), ("lhd_tyre_rr", AXLE_R, "r")):
        objs.append(build_tyre(mats, root, name, x, side))
    return objs


# --------------------------------------------------------------------------- export + checks


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


def export_glb(objs):
    os.makedirs(os.path.dirname(GLB_PATH), exist_ok=True)
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=GLB_PATH,
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
        export_texcoords=False,
        export_normals=True,
        export_tangents=False,
        export_materials="EXPORT",
        export_vertex_color="NONE",
        export_attributes=False,
        export_image_format="NONE",
        export_cameras=False,
        export_lights=False,
        export_extras=False,
        export_animations=False,
        export_skins=False,
        export_morph=False,
        export_draco_mesh_compression_enable=False,
        export_copyright="Team repository licence (MIT); authored by Claude via Blender 5.1 command line script",
    )
    for o in objs:
        o.select_set(False)


def inspect_glb(path):
    """Count triangles and check the budget straight from the exported data."""
    with open(path, "rb") as fh:
        data = fh.read()
    magic, version, length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67 and version == 2, "not a glTF 2.0 binary"
    clen, ctype = struct.unpack_from("<II", data, 12)
    assert ctype == 0x4E4F534A
    gltf = json.loads(data[20:20 + clen])
    acc = gltf["accessors"]
    tris = verts = 0
    per_mesh = {}
    for node in gltf.get("nodes", []):
        if "mesh" not in node:
            continue
        mesh = gltf["meshes"][node["mesh"]]
        t = 0
        for prim in mesh["primitives"]:
            mode = prim.get("mode", 4)
            assert mode == 4, "only TRIANGLES expected"
            n = acc[prim["indices"]]["count"] if "indices" in prim else acc[prim["attributes"]["POSITION"]]["count"]
            t += n // 3
            verts += acc[prim["attributes"]["POSITION"]]["count"]
        per_mesh[node.get("name", "?")] = t
        tris += t
    lo = [1e9] * 3
    hi = [-1e9] * 3
    for node in gltf.get("nodes", []):
        assert "rotation" not in node and "scale" not in node, "unexpected node transform"
        if "mesh" in node:
            for prim in gltf["meshes"][node["mesh"]]["primitives"]:
                a = acc[prim["attributes"]["POSITION"]]
                lo = [min(l, m) for l, m in zip(lo, a["min"])]
                hi = [max(h, m) for h, m in zip(hi, a["max"])]
    return {
        "bytes": len(data),
        "triangles": tris,
        "vertices": verts,
        "per_mesh": per_mesh,
        "materials": [m["name"] for m in gltf.get("materials", [])],
        "images": len(gltf.get("images", [])),
        "textures": len(gltf.get("textures", [])),
        "extensionsUsed": gltf.get("extensionsUsed", []),
        "bounds_min": lo,
        "bounds_max": hi,
    }


# --------------------------------------------------------------------------- preview rig


def setup_preview_rig():
    scene = bpy.context.scene
    world = bpy.data.worlds.new("graphite")
    if getattr(world, "node_tree", None) is None:
        world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = hex_rgba("#111316")
    bg.inputs["Strength"].default_value = 1.0
    scene.world = world

    ground_mat = principled("preview_desk", "#1A1D21", 0.9, 0.0)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=60.0)
    me = bpy.data.meshes.new("preview_desk")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(ground_mat)
    desk = bpy.data.objects.new("preview_desk", me)
    scene.collection.objects.link(desk)

    def area(name, color, energy, size, loc, target):
        ld = bpy.data.lights.new(name, "AREA")
        ld.color = hex_rgba(color)[:3]
        ld.energy = energy
        ld.size = size
        ob = bpy.data.objects.new(name, ld)
        ob.location = loc
        direction = Vector(target) - Vector(loc)
        ob.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(ob)
        return ob

    rig = [desk]
    rig.append(area("key_warm", "#FFD7A1", 1200, 7.0, (6.0, 7.5, 8.0), (0.0, 0, 0.8)))
    rig.append(area("fill_neutral", "#C9D0D8", 1200, 9.0, (5.0, -8.0, 4.0), (0, 0, 1.0)))
    rig.append(area("rim", "#E8E3DA", 900, 5.0, (-9.0, 4.0, 6.0), (0, 0, 1.0)))
    rig.append(area("top_soft", "#D9DDE2", 900, 10.0, (0.0, 0.0, 10.0), (0, 0, 0)))
    return rig


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
    direction = Vector(target) - Vector(loc)
    ob.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(ob)
    return ob


def configure_render(engine):
    scene = bpy.context.scene
    scene.render.engine = engine
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    if engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = SAMPLES
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.use_denoising = True
        scene.cycles.max_bounces = 6
    elif engine == "BLENDER_WORKBENCH":
        sh = scene.display.shading
        sh.light = "STUDIO"
        sh.color_type = "MATERIAL"
        sh.show_shadows = True
        sh.show_cavity = True


def render_previews():
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    scene = bpy.context.scene
    cams = {
        "lhd_three_quarter": make_camera("cam_three_quarter", (9.1, 8.6, 4.6), (-0.15, 0.0, 0.75), lens=42),
        "lhd_side": make_camera("cam_side", (-0.2, 25.0, 1.15), (-0.2, 0.0, 1.15), ortho_scale=11.4),
        "lhd_top": make_camera("cam_top", (-0.2, 0.0, 25.0), (-0.2, 0.0, 0.0), ortho_scale=11.4),
    }
    # the top camera must keep +X to the right of the frame
    cams["lhd_top"].rotation_euler = (0.0, 0.0, 0.0)
    shots = [("lhd_three_quarter", 1200, 800), ("lhd_side", 1200, 800),
             ("lhd_top", 1200, 800), ("lhd_small_300", 300, 200)]
    engine_used = None
    for engine in ("CYCLES", "BLENDER_WORKBENCH"):
        try:
            configure_render(engine)
            for name, w, h in shots:
                cam = cams.get(name, cams["lhd_three_quarter"])
                scene.camera = cam
                scene.render.resolution_x = w
                scene.render.resolution_y = h
                scene.render.resolution_percentage = 100
                scene.render.filepath = os.path.join(PREVIEW_DIR, name + ".png")
                t = time.perf_counter()
                bpy.ops.render.render(write_still=True)
                print(f"[lhd] rendered {name}.png {w}x{h} with {engine} in {time.perf_counter() - t:.1f} s")
            engine_used = engine
            break
        except Exception as exc:  # fall back to Workbench if Cycles is unavailable
            print(f"[lhd] renderer {engine} failed: {exc}")
    scene.camera = cams["lhd_three_quarter"]
    return engine_used


# --------------------------------------------------------------------------- run


def main():
    reset_scene()
    mats = make_materials()
    objs = build_machine(mats)
    t_build = time.perf_counter() - T0

    lo, hi = world_bounds(objs)
    print(f"[lhd] bounds (Blender, m): min {tuple(round(c, 3) for c in lo)} max {tuple(round(c, 3) for c in hi)}")
    print(f"[lhd] length {hi.x - lo.x:.3f} m, width {hi.y - lo.y:.3f} m, height {hi.z - lo.z:.3f} m")

    t = time.perf_counter()
    export_glb(objs)
    t_export = time.perf_counter() - t
    info = inspect_glb(GLB_PATH)
    print("[lhd] glb", json.dumps(info, indent=1))
    problems = []
    if info["triangles"] > MAX_TRIANGLES:
        problems.append(f"{info['triangles']} triangles > {MAX_TRIANGLES}")
    if len(info["materials"]) > MAX_MATERIALS:
        problems.append(f"{len(info['materials'])} materials > {MAX_MATERIALS}")
    if info["images"] or info["textures"]:
        problems.append("textures present")
    if info["extensionsUsed"]:
        problems.append(f"extensions used: {info['extensionsUsed']}")

    rig = setup_preview_rig()
    engine = None
    t = time.perf_counter()
    if DO_RENDER:
        engine = render_previews()
    t_render = time.perf_counter() - t

    bpy.context.scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH, compress=True)
    if os.path.exists(BLEND_PATH + "1"):
        os.remove(BLEND_PATH + "1")      # no backup file next to the source

    print(f"[lhd] build {t_build:.1f} s, export {t_export:.1f} s, previews {t_render:.1f} s "
          f"({engine or 'skipped'}), total {time.perf_counter() - T0:.1f} s")
    print(f"[lhd] wrote {BLEND_PATH}\n[lhd] wrote {GLB_PATH} ({info['bytes']} bytes)")
    if problems:
        print("[lhd] BUDGET FAILED: " + "; ".join(problems))
        sys.exit(1)
    print(f"[lhd] budget ok: {info['triangles']} triangles, {len(info['materials'])} materials, no textures, no extensions")


main()
