"""
actors_style.py - shared style, mesh builder, light bake, export and preview helpers
for the mine-art actors (worker, LHD, truck, drill) of the dispatcher UI.

Imported by worker.py, lhd.py, truck.py and drill.py, which run in Blender 5.1 in
background mode only:

    "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" --background
        --factory-startup --python team/ui/assets/mine-art/actors/<asset>.py [-- options]

The look (team/ui/assets/mine-art/SPEC.md, sections 6 and 7)
    Every surface is shaded once, in Blender, by a "paint" shader and baked into one
    texture per asset; the browser shows that texture with KHR_materials_unlit. The
    paint shader is a fixed light rig written as shader math, not lamps:
      * ambient from above (cool) + one soft key from above-front (warm), mirrored
        left/right so a machine looks the same whichever side faces the camera;
      * rounded-edge normals (Bevel node) so top edges catch a light rim and lower
        edges fall into a dark rim, like painted highlights;
      * ambient occlusion for contact shadows in creases;
      * a thin dark line only on sharp edges (selective outline, no screen pass);
      * dust: the lower part of the machine takes on the floor colour.
    No random noise, no gloss. Lamp lenses are not baked: they stay a separate
    emissive (unlit, flat colour) node named LAMPS that the browser can switch.

Units: scene metres (SPEC section 3): machines are built at real size and scaled
by MACHINE_SCALE = 1.5 when a part becomes a mesh; the worker is 5 m tall.
Axes (Blender): +X forward, +Y left, +Z up; glTF: forward +X, up +Y, left -Z.
"""

import json
import math
import os
import struct
import sys
import time

import bmesh
import bpy
from mathutils import Matrix, Vector

# --------------------------------------------------------------------------- paths, options

HERE = os.path.dirname(os.path.abspath(__file__))
UI_ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
OUT_DIR = os.path.join(UI_ROOT, "public", "models", "mine-art", "actors")
PREVIEW_DIR = os.path.join(HERE, "previews")
BLENDER_EXE = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
DO_RENDER = "--no-render" not in ARGS
BAKE_SAMPLES = int(ARGS[ARGS.index("--samples") + 1]) if "--samples" in ARGS else 128

MACHINE_SCALE = 1.5
T0 = time.perf_counter()


def log(*a):
    print(f"[{time.perf_counter() - T0:7.1f}s]", *a, flush=True)


# --------------------------------------------------------------------------- main view (SPEC 4)

VIEW_AZIMUTH = 12.0      # degrees from south toward east
VIEW_ELEVATION = 28.0    # degrees above the horizon


def view_dir():
    """Unit vector from the target toward the camera (Blender axes, -Y = south)."""
    az, el = math.radians(VIEW_AZIMUTH), math.radians(VIEW_ELEVATION)
    return Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))


# Two zoom levels for the previews, in screen pixels per scene metre:
# overview (1x): the LHD (~15.6 m) is ~120 px long and a worker (5 m) ~40 px tall;
# close (about 3.4x): the LHD is ~400 px long.
PPM_OVERVIEW = 7.7
PPM_CLOSE = 25.6
PPM_WORKER_CLOSE = 30.0

FLOOR_HEX = "#857B6E"     # mid tone of the lit gravel floor in the references

# --------------------------------------------------------------------------- palette (sRGB)

PALETTE = {
    # machines
    "yellow": "#E8B22A",       # machine paint (SPEC 7)
    "yellow_dk": "#C98F1C",    # second paint tone: guards, inner panels
    "chassis": "#3B3632",      # frame, counterweight, grille frames
    "steel": "#9A9A96",        # rods, pins, cutting edge, rims
    "steel_dk": "#64666A",     # feeds, booms' steel parts
    "rubber": "#262423",       # tyres
    "rim": "#A48D5C",          # painted wheel rims (khaki)
    "hose": "#24221F",         # hoses, cables
    "glass": "#2F3E48",        # cab glazing (opaque)
    "housing": "#34312E",      # lamp housings
    "seam": "#4A3818",         # painted panel lines on yellow
    "plate": "#E9DDB8",        # small light plates (numbers, labels)
    "rock": "#6E6760",         # rocks in the truck box
    "rock_dk": "#57514C",
    "ore": "#9C6740",          # copper-stained rock
    # worker
    "orange": "#F26A1B",       # coveralls (SPEC 7)
    "orange_dk": "#D2531A",    # shoulder yoke, pockets
    "reflect": "#DCDFD8",      # reflective stripes
    "helmet": "#F3D768",       # yellow-white helmet
    "skin": "#C98E68",
    "boot": "#2F2925",
    "glove": "#3D3833",
    "gear": "#38332F",         # belt, battery, lamp housing
    "lens_paint": "#FFF3D2",   # cap-lamp lens painted into the worker texture
    # lamps (LAMPS node, not baked)
    "lens": "#FFE7B8",
}
LAMP_ON_HEX = "#FFE7B8"
LAMP_OFF_HEX = "#5B544B"


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_lin(h):
    h = h.lstrip("#")
    return tuple(srgb_to_linear(int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4))


# Per-material bake parameters. Keys not listed use DEFAULT_SHADE.
DEFAULT_SHADE = dict(dust=1.0, hi=0.38, lo=0.42, line=0.85, ao=0.75, sym=True, wheel=False,
                     glass=False, flat=False, sky=1.0, key=1.0)
SHADE = {
    "yellow": dict(hi=0.5),
    "yellow_dk": dict(hi=0.5),
    "chassis": dict(hi=0.7),
    "steel": dict(hi=0.55, dust=0.7),
    "steel_dk": dict(hi=0.6, dust=0.7),
    "rubber": dict(hi=0.9, dust=0.3, wheel=True, line=0.6),
    "rim": dict(hi=0.6, dust=0.4, wheel=True),
    "hose": dict(hi=0.9, dust=0.4, line=0.4),
    "glass": dict(glass=True, dust=0.0, hi=0.2, lo=0.2, line=0.9),
    "housing": dict(hi=0.8, dust=0.3),
    "seam": dict(dust=0.6, hi=0.0, lo=0.0, line=0.0),
    "plate": dict(dust=0.3),
    "rock": dict(dust=0.0, hi=0.6),
    "rock_dk": dict(dust=0.0, hi=0.6),
    "ore": dict(dust=0.0, hi=0.6),
    "orange": dict(dust=0.25),
    "orange_dk": dict(dust=0.25),
    "reflect": dict(dust=0.15),
    "helmet": dict(dust=0.0, hi=0.5),
    "skin": dict(dust=0.0),
    "boot": dict(dust=0.3, hi=0.8),
    "glove": dict(dust=0.0, hi=0.7),
    "gear": dict(dust=0.0, hi=0.7),
    "lens_paint": dict(flat=True, dust=0.0, line=0.0),
}

# Light rig of the paint shader (directions in object space, Blender axes).
STYLE = dict(
    key_dir=(0.30, 0.50, 0.81),       # above, a little front, toward the viewer (mirrored in Y)
    key_rgb=(1.00, 0.95, 0.86),
    key_str=0.70,
    key_ramp=(0.0, 0.75),
    amb_rgb=(0.96, 0.80, 0.70),
    amb_base=0.36,
    amb_sky=0.26,
    ao_dist=0.9,
    cavity_dist=0.14,
    cavity_str=0.75,
    bevel_wide=0.09,
    bevel_thin=0.05,
    line_ramp=(0.025, 0.09),
    line_rgb=(0.035, 0.026, 0.020),
    dust_rgb=hex_lin("#6E5F4D"),
    dust_height=1.1,
)

# --------------------------------------------------------------------------- scene


def reset_scene(name):
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras,
                 bpy.data.images, bpy.data.node_groups, bpy.data.armatures, bpy.data.actions,
                 bpy.data.curves):
        for block in list(coll):
            coll.remove(block)
    bpy.context.preferences.filepaths.save_version = 0      # no .blend1 backups
    scene = bpy.context.scene
    scene.name = name
    scene.unit_settings.system = "METRIC"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("world")
    return scene


def setup_cycles(samples=64):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for kind in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = kind
                prefs.get_devices()
                gpus = [d for d in prefs.devices if d.type == kind]
                if gpus:
                    for d in prefs.devices:
                        d.use = d.type == kind
                    scene.cycles.device = "GPU"
                    break
            except Exception:
                continue
    except Exception as exc:  # CPU fallback
        log("GPU setup failed, CPU", exc)
    scene.cycles.samples = samples
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.use_denoising = False
    scene.cycles.max_bounces = 0
    scene.cycles.diffuse_bounces = 0
    scene.cycles.glossy_bounces = 0
    scene.cycles.transmission_bounces = 0
    scene.cycles.transparent_max_bounces = 8
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.display_settings.display_device = "sRGB"
    scene.render.film_transparent = False
    scene.render.filter_size = 1.0
    scene.cycles.pixel_filter_type = "BLACKMAN_HARRIS"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.resolution_percentage = 100


def select_only(objs, active=None):
    for o in list(bpy.context.view_layer.objects):
        if o is not None:
            o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or (objs[0] if objs else None)


def empty(name, parent=None, loc=(0, 0, 0)):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = "PLAIN_AXES"
    ob.empty_display_size = 0.5
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = parent
    ob.location = loc
    return ob


# --------------------------------------------------------------------------- node helpers


class NodeBuilder:
    """Tiny expression builder over a shader node tree (scalars and vectors)."""

    def __init__(self, tree):
        self.tree, self.nodes, self.links = tree, tree.nodes, tree.links
        self.x = 0

    def node(self, kind, **props):
        n = self.nodes.new(kind)
        n.location = (self.x, 0)
        self.x += 30
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def feed(self, sock, val):
        if isinstance(val, bpy.types.NodeSocket):
            self.links.new(val, sock)
        elif val is not None:
            sock.default_value = val

    def math(self, op, a, b=None, clamp=False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.feed(n.inputs[0], a)
        if b is not None:
            self.feed(n.inputs[1], b)
        return n.outputs[0]

    def vmath(self, op, a, b=None, scale=None):
        n = self.node("ShaderNodeVectorMath", operation=op)
        self.feed(n.inputs[0], a)
        if b is not None:
            self.feed(n.inputs[1], b)
        if scale is not None:
            self.feed(n.inputs["Scale"], scale)
        out = n.outputs["Value"] if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else n.outputs["Vector"]
        return out

    def vec(self, x, y, z):
        n = self.node("ShaderNodeCombineXYZ")
        for i, v in enumerate((x, y, z)):
            self.feed(n.inputs[i], v)
        return n.outputs[0]

    def sep(self, v):
        n = self.node("ShaderNodeSeparateXYZ")
        self.feed(n.inputs[0], v)
        return n.outputs[0], n.outputs[1], n.outputs[2]

    def smooth(self, v, e0, e1):
        n = self.node("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP", clamp=True)
        self.feed(n.inputs["Value"], v)
        n.inputs["From Min"].default_value = e0
        n.inputs["From Max"].default_value = e1
        n.inputs["To Min"].default_value = 0.0
        n.inputs["To Max"].default_value = 1.0
        return n.outputs["Result"]

    def scale(self, v, s):
        return self.vmath("SCALE", v, scale=s)

    def lerp(self, a, b, t):
        """a + (b - a) * t for vectors (t scalar socket or float)."""
        return self.vmath("ADD", a, self.scale(self.vmath("SUBTRACT", b, a), t))

    def lerpf(self, a, b, t):
        return self.math("ADD", a, self.math("MULTIPLY", self.math("SUBTRACT", b, a), t))


def paint_material(key, style=None):
    """Bake-source material for palette entry `key`: shading as emission (see module doc)."""
    st = dict(STYLE)
    st.update(style or {})
    prm = dict(DEFAULT_SHADE)
    prm.update(SHADE.get(key, {}))
    name = f"paint_{key}"
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True if getattr(mat, "node_tree", None) is None else mat.use_nodes
    tree = mat.node_tree
    tree.nodes.clear()
    nb = NodeBuilder(tree)
    out = nb.node("ShaderNodeOutputMaterial")
    emit = nb.node("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = 1.0
    nb.links.new(emit.outputs[0], out.inputs["Surface"])
    albedo = hex_lin(PALETTE[key])
    mat.diffuse_color = albedo + (1.0,)
    mat["palette"] = key

    if prm["flat"]:
        emit.inputs["Color"].default_value = albedo + (1.0,)
        return mat

    geo = nb.node("ShaderNodeNewGeometry")
    ns = geo.outputs["Normal"]
    pos = geo.outputs["Position"]
    bw = nb.node("ShaderNodeBevel", samples=16)
    bw.inputs["Radius"].default_value = st["bevel_wide"]
    bt = nb.node("ShaderNodeBevel", samples=16)
    bt.inputs["Radius"].default_value = st["bevel_thin"]
    nw, nt = bw.outputs["Normal"], bt.outputs["Normal"]
    ao = nb.node("ShaderNodeAmbientOcclusion", samples=16, only_local=bool(st.get("ao_local", False)))
    ao.inputs["Distance"].default_value = st["ao_dist"]
    aof = ao.outputs["AO"]
    cav = nb.node("ShaderNodeAmbientOcclusion", samples=8, only_local=bool(st.get("ao_local", False)))
    cav.inputs["Distance"].default_value = st["cavity_dist"]
    cavf = cav.outputs["AO"]

    lx, ly, lz = st["key_dir"]
    ll = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / ll, ly / ll, lz / ll

    def mirrored(n):
        x, y, z = nb.sep(n)
        return nb.vec(x, nb.math("ABSOLUTE", y), z)

    if prm["wheel"]:
        # rotation-invariant light for parts that spin: sidewalls lit, tread in ambient
        def lambert(n):
            x, y, z = nb.sep(n)
            return nb.math("MULTIPLY", nb.math("ABSOLUTE", y), 0.85)
        sky = 0.5
        key_l = lambert(nw)
        diff_line = nb.math("SUBTRACT", lambert(nw), lambert(ns))
    else:
        L = (lx, ly, lz)
        nwm = mirrored(nw) if prm["sym"] else nw
        nsm = mirrored(ns) if prm["sym"] else ns
        key_l = nb.vmath("DOT_PRODUCT", nwm, L)
        _, _, nz = nb.sep(nw)
        sky = nb.math("ADD", nb.math("MULTIPLY", nz, 0.5), 0.5)
        diff_line = nb.math("SUBTRACT", nb.vmath("DOT_PRODUCT", nwm, L), nb.vmath("DOT_PRODUCT", nsm, L))

    key = nb.smooth(key_l, *st["key_ramp"])
    amb = nb.math("ADD", st["amb_base"], nb.math("MULTIPLY", sky, st["amb_sky"] * prm["sky"]))
    light = nb.vmath("ADD", nb.scale(st["amb_rgb"], amb),
                     nb.scale(st["key_rgb"], nb.math("MULTIPLY", key, st["key_str"] * prm["key"])))
    # ambient occlusion: 1 - ao_strength * (1 - ao)
    aoterm = nb.math("SUBTRACT", 1.0, nb.math("MULTIPLY", nb.math("SUBTRACT", 1.0, aof), prm["ao"]))
    light = nb.scale(light, aoterm)
    # cavity: short-range occlusion draws crisp contact lines where parts meet
    cavterm = nb.math("SUBTRACT", 1.0, nb.math("MULTIPLY", nb.math("SUBTRACT", 1.0, cavf),
                                                 st["cavity_str"] * prm["ao"]))
    light = nb.scale(light, cavterm)
    # rounded-edge rim: lit rim where the rounded normal turns to the key, dark rim where it turns away
    hi = nb.smooth(diff_line, 0.02, 0.16)
    lo = nb.smooth(nb.math("MULTIPLY", diff_line, -1.0), 0.02, 0.16)
    rim = nb.math("MULTIPLY", nb.math("ADD", 1.0, nb.math("MULTIPLY", hi, prm["hi"])),
                  nb.math("SUBTRACT", 1.0, nb.math("MULTIPLY", lo, prm["lo"])))
    light = nb.scale(light, rim)

    # albedo with dust toward the floor
    base = nb.vec(*albedo)
    if prm["glass"]:
        # painted reflection: two soft diagonal bands across the panes
        d = nb.vmath("DOT_PRODUCT", pos, (0.55, 0.55, 1.0))
        f = nb.math("FRACT", nb.math("MULTIPLY", d, 0.55))
        band = nb.math("SUBTRACT", nb.smooth(f, 0.10, 0.16), nb.smooth(f, 0.30, 0.36))
        band2 = nb.math("SUBTRACT", nb.smooth(f, 0.42, 0.45), nb.smooth(f, 0.50, 0.53))
        bands = nb.math("ADD", band, nb.math("MULTIPLY", band2, 0.6))
        base = nb.lerp(base, hex_lin("#8FA6B2"), nb.math("MULTIPLY", bands, 0.55))
    if prm["dust"] > 0:
        if prm["wheel"]:
            dust = 0.35
        else:
            _, _, pz = nb.sep(pos)
            dust = nb.math("SUBTRACT", 1.0, nb.smooth(pz, 0.0, st["dust_height"]))
        base = nb.lerp(base, st["dust_rgb"], nb.math("MULTIPLY", dust, 0.55 * prm["dust"]))
    col = nb.vmath("MULTIPLY", base, light)

    # selective outline: dark line on sharp edges (thin rounded normal vs shading normal)
    edge = nb.math("SUBTRACT", 1.0, nb.vmath("DOT_PRODUCT", nt, ns))
    line = nb.math("MULTIPLY", nb.smooth(edge, *st["line_ramp"]), prm["line"])
    col = nb.lerp(col, st["line_rgb"], line)
    nb.links.new(col, emit.inputs["Color"])
    return mat


class Palette(dict):
    """Lazily created bake materials keyed by palette name."""

    def __init__(self, style=None):
        super().__init__()
        self.style = style

    def __missing__(self, key):
        mat = paint_material(key, self.style)
        self[key] = mat
        return mat


# --------------------------------------------------------------------------- mesh builder


class Part:
    """A bmesh plus palette slots; becomes one Blender object (real-size coordinates)."""

    def __init__(self, name, mats, lens=None):
        self.name = name
        self.bm = bmesh.new()
        self.slots = []
        self.mats = mats
        self.lens = lens          # Part receiving lamp lenses (the LAMPS node)
        self.loose = set()        # single faces (decals): keep their winding

    def _idx(self, slot):
        if slot not in self.slots:
            self.slots.append(slot)
        return self.slots.index(slot)

    def face(self, verts, slot, loose=False):
        f = self.bm.faces.new(verts)
        f.material_index = self._idx(slot)
        if loose:
            self.loose.add(f)
        return f

    def hexa(self, pts, slot="yellow"):
        """Eight corners: bottom face 0-3, top face 4-7 (same winding)."""
        v = [self.bm.verts.new(p) for p in pts]
        for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            self.face([v[i] for i in f], slot)

    def box(self, mn, mx, slot="yellow"):
        (x0, y0, z0), (x1, y1, z1) = mn, mx
        self.hexa([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                   (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], slot)

    def boxc(self, c, size, slot="yellow"):
        (cx, cy, cz), (sx, sy, sz) = c, size
        self.box((cx - sx / 2, cy - sy / 2, cz - sz / 2), (cx + sx / 2, cy + sy / 2, cz + sz / 2), slot)

    def prism_xz(self, pts, y0, y1, slot="yellow"):
        a = [self.bm.verts.new((x, y0, z)) for x, z in pts]
        b = [self.bm.verts.new((x, y1, z)) for x, z in pts]
        self.face(a, slot)
        self.face(list(reversed(b)), slot)
        n = len(pts)
        for i in range(n):
            j = (i + 1) % n
            self.face((a[i], a[j], b[j], b[i]), slot)

    def prism_yz(self, pts, x0, x1, slot="yellow"):
        """Polygon in the YZ plane (cross-section), extruded along X."""
        a = [self.bm.verts.new((x0, y, z)) for y, z in pts]
        b = [self.bm.verts.new((x1, y, z)) for y, z in pts]
        self.face(a, slot)
        self.face(list(reversed(b)), slot)
        n = len(pts)
        for i in range(n):
            j = (i + 1) % n
            self.face((a[i], a[j], b[j], b[i]), slot)

    def prism_xy(self, pts, z0, z1, slot="yellow"):
        a = [self.bm.verts.new((x, y, z0)) for x, y in pts]
        b = [self.bm.verts.new((x, y, z1)) for x, y in pts]
        self.face(a, slot)
        self.face(list(reversed(b)), slot)
        n = len(pts)
        for i in range(n):
            j = (i + 1) % n
            self.face((a[i], a[j], b[j], b[i]), slot)

    def strip_xz(self, line, thick, y0, y1, slot="yellow"):
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
        self.prism_xz(left + list(reversed(right)), y0, y1, slot)

    def cylinder(self, p0, p1, r, sides=8, slot="yellow", caps=True, r1=None, phase=0.5):
        p0, p1 = Vector(p0), Vector(p1)
        d = (p1 - p0).normalized()
        if abs(d.z) > 0.9:
            u = Vector((1, 0, 0))
        else:
            u = Vector((0, 0, 1)).cross(d).cross(d).normalized()
        w = d.cross(u).normalized()
        r1 = r if r1 is None else r1
        ring0, ring1 = [], []
        for k in range(sides):
            a = 2 * math.pi * (k + phase) / sides
            off = u * math.cos(a) + w * math.sin(a)
            ring0.append(self.bm.verts.new(p0 + off * r))
            ring1.append(self.bm.verts.new(p1 + off * r1))
        for k in range(sides):
            j = (k + 1) % sides
            self.face((ring0[k], ring0[j], ring1[j], ring1[k]), slot)
        if caps:
            self.face(list(reversed(ring0)), slot)
            self.face(ring1, slot)
        return ring0, ring1

    def hydraulic(self, base, tip, r_barrel, frac=0.6, sides=8, slot="yellow"):
        """Barrel (paint) with a gland ring, chrome rod (steel), dark eye bosses."""
        base, tip = Vector(base), Vector(tip)
        d = (tip - base).normalized()
        mid = base.lerp(tip, frac)
        self.cylinder(base + d * r_barrel * 0.5, mid, r_barrel, sides, slot)
        self.cylinder(mid - d * 0.05, mid + d * 0.02, r_barrel * 1.14, sides, "chassis")
        self.cylinder(mid, tip - d * r_barrel * 0.3, r_barrel * 0.5, 6, "steel", caps=False)
        side = d.cross(Vector((0, 0, 1)))
        if side.length < 1e-3:
            side = Vector((0, 1, 0))
        side.normalize()
        for c, r in ((base, r_barrel * 0.9), (tip, r_barrel * 0.65)):
            self.cylinder(c - side * r_barrel * 0.75, c + side * r_barrel * 0.75, r, 6, "chassis")

    def tube(self, points, radius, sides=5, segments=8, slot="hose"):
        """A hose along a quadratic Bezier through three control points."""
        p0, p1, p2 = (Vector(p) for p in points)
        path = [(1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2
                for t in (i / segments for i in range(segments + 1))]
        loops = []
        for i, p in enumerate(path):
            tangent = (path[min(i + 1, segments)] - path[max(i - 1, 0)]).normalized()
            side = tangent.cross(Vector((0.0, 1.0, 0.0)))
            if side.length < 1e-4:
                side = tangent.cross(Vector((0, 0, 1)))
            side.normalize()
            up = side.cross(tangent).normalized()
            loops.append([self.bm.verts.new(p + radius * (math.cos(2 * math.pi * s / sides) * side
                                                          + math.sin(2 * math.pi * s / sides) * up))
                          for s in range(sides)])
        for a, b in zip(loops, loops[1:]):
            for s in range(sides):
                t = (s + 1) % sides
                self.face((a[s], a[t], b[t], b[s]), slot)
        self.face(list(reversed(loops[0])), slot)
        self.face(loops[-1], slot)

    def lamp(self, centre, direction, r=0.09, depth=0.12, sides=8, square=False):
        """Work lamp: dark housing in this part, lens disc in the LAMPS part."""
        c, d = Vector(centre), Vector(direction).normalized()
        if square:
            # rectangular housing facing along +/-X or +/-Y
            ax = Vector((abs(d.x), abs(d.y), abs(d.z)))
            half = Vector((r, r, r * 0.75))
            for i in range(3):
                if ax[i] > 0.5:
                    half[i] = depth / 2
            self.box(tuple(c - d * depth / 2 - half), tuple(c - d * depth / 2 + half), "housing")
            if self.lens is not None:
                lh = Vector((r * 0.8, r * 0.8, r * 0.58))
                for i in range(3):
                    if ax[i] > 0.5:
                        lh[i] = 0.012
                self.lens.box(tuple(c - lh), tuple(c + lh), "lens")
            return
        self.cylinder(c - d * depth, c, r, sides, "housing", r1=r * 1.06)
        if self.lens is not None:
            self.lens.cylinder(c - d * 0.004, c + d * 0.016, r * 0.84, sides, "lens")

    def decal(self, centre, axis, su, sv, slot="seam", off=0.004):
        """A flat quad lying on a face that points along axis ('+x','-x','+y','-y','+z')."""
        cx, cy, cz = centre
        sgn = 1 if axis[0] == "+" else -1
        a = axis[1]
        hu, hv = su / 2, sv / 2
        if a == "x":
            x = cx + sgn * off
            pts = [(x, cy - hu, cz - hv), (x, cy + hu, cz - hv), (x, cy + hu, cz + hv), (x, cy - hu, cz + hv)]
        elif a == "y":
            y = cy + sgn * off
            pts = [(cx - hu, y, cz - hv), (cx + hu, y, cz - hv), (cx + hu, y, cz + hv), (cx - hu, y, cz + hv)]
        else:
            z = cz + sgn * off
            pts = [(cx - hu, cy - hv, z), (cx + hu, cy - hv, z), (cx + hu, cy + hv, z), (cx - hu, cy + hv, z)]
        v = [self.bm.verts.new(p) for p in pts]
        f = self.face(v, slot, loose=True)
        f.normal_update()
        want = Vector((sgn if a == "x" else 0, sgn if a == "y" else 0, sgn if a == "z" else 0))
        if f.normal.dot(want) < 0:
            f.normal_flip()
        return f

    def rock(self, c, size, seed, slot="rock", squash=0.7):
        """A faceted rock: a jittered octahedron-ish blob (8-12 faces), deterministic."""
        cx, cy, cz = c
        rnd = _Rand(seed)
        ico = bmesh.ops.create_icosphere(self.bm, subdivisions=1, radius=1.0)
        verts = ico["verts"]
        m = self._idx(slot)
        for v in verts:
            k = 0.78 + 0.34 * rnd.next()
            v.co = Vector((cx + v.co.x * size * k, cy + v.co.y * size * k * (0.8 + 0.3 * rnd.next()),
                           cz + v.co.z * size * k * squash))
        faces = {f for v in verts for f in v.link_faces}
        for f in faces:
            f.material_index = m

    def to_object(self, parent=None, scale=1.0, origin=None, cull_down=False, smooth_angle=35.0):
        bm = self.bm
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        closed = [f for f in bm.faces if f not in self.loose and f.is_valid]
        bmesh.ops.recalc_face_normals(bm, faces=closed)
        if cull_down:
            # faces pointing straight down are never seen from the main view (elevation 28 deg)
            bm.normal_update()
            down = [f for f in bm.faces if f.normal.z < -0.9]
            bmesh.ops.delete(bm, geom=down, context="FACES")
        if scale != 1.0:
            bmesh.ops.scale(bm, vec=(scale, scale, scale), verts=bm.verts)
        o = Vector(origin) * scale if origin is not None else None
        if o is not None:
            bmesh.ops.translate(bm, vec=-o, verts=bm.verts)
        me = bpy.data.meshes.new(self.name)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(self.name, me)
        bpy.context.scene.collection.objects.link(ob)
        for s in self.slots:
            me.materials.append(self.mats[s])
        ob.parent = parent
        if o is not None:
            ob.location = o
        select_only([ob])
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(smooth_angle))
        ob.select_set(False)
        return ob


class _Rand:
    """Deterministic LCG so rebuilds are identical."""

    def __init__(self, seed):
        self.s = (seed * 2654435761 + 12345) & 0xFFFFFFFF

    def next(self):
        self.s = (1103515245 * self.s + 12345) & 0x7FFFFFFF
        return self.s / 0x7FFFFFFF


def arc(cx, cz, r, a0, a1, n):
    """Points on a circle in XZ from angle a0 to a1 (degrees), n+1 points."""
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cz + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def sides_of(y_in, y_out):
    """Both mirrored y-intervals [in, out] for s = +1 (left) and -1 (right)."""
    return [tuple(sorted((s * y_in, s * y_out))) for s in (1, -1)]


def join(objs, name):
    select_only(objs, objs[0])
    bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = name
    ob.data.name = name
    return ob


def tri_count(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


# --------------------------------------------------------------------------- wheels


def build_wheel(mats, name, radius, width, rim_r, segments=16, lug=0.10):
    """Tyre about the Y axis, origin at the axle, outer face +Y; real-size coords.
    Chunky lugs on every other segment, alternating tread halves, so the silhouette
    shows the tread blocks. Rim painted (khaki) with a dark hub cap."""
    p = Part(name, mats)
    bm = p.bm
    hw = width / 2
    prof = [(rim_r * 0.95, -hw * 0.84), (radius * 0.90, -hw), (radius, -hw * 0.50),
            (radius, hw * 0.05), (radius, hw * 0.55), (radius * 0.95, hw * 0.92),
            (radius * 0.82, hw), (rim_r * 1.03, hw * 0.90)]
    rim = [(rim_r * 0.96, hw * 0.76), (rim_r * 0.58, hw * 0.64), (rim_r * 0.40, hw * 0.82)]
    slots = ["rubber"] * (len(prof) - 1) + ["rim"] * len(rim)
    full = prof + rim
    grid = []
    for k in range(segments):
        ang = 2 * math.pi * (k + 0.5) / segments
        grid.append([bm.verts.new((r * math.cos(ang), y, r * math.sin(ang))) for r, y in full])
    hub_c = bm.verts.new((0, full[-1][1], 0))
    in_c = bm.verts.new((0, full[0][1], 0))
    faces = {}
    for k in range(segments):
        k2 = (k + 1) % segments
        for i in range(len(full) - 1):
            faces[(k, i)] = p.face((grid[k][i], grid[k2][i], grid[k2][i + 1], grid[k][i + 1]), slots[i])
        p.face((grid[k][-1], grid[k2][-1], hub_c), "rim")
        p.face((grid[k2][0], grid[k][0], in_c), "chassis")
    for k in range(0, segments, 2):
        idx = (1, 2) if (k // 2) % 2 == 0 else (3, 4)
        ret = bmesh.ops.extrude_face_region(bm, geom=[faces[(k, i)] for i in idx])
        for v in [g for g in ret["geom"] if isinstance(g, bmesh.types.BMVert)]:
            radial = Vector((v.co.x, 0.0, v.co.z)).normalized()
            v.co += radial * radius * lug
    p.cylinder((0, full[-1][1] - 0.01, 0), (0, full[-1][1] + 0.06, 0), rim_r * 0.30, 6, "chassis")
    return p


def mirror_mesh_y(src, name):
    """A copy of mesh `src` mirrored in Y (normals kept outward, UVs kept)."""
    me = src.copy()
    me.name = name
    bm = bmesh.new()
    bm.from_mesh(me)
    for v in bm.verts:
        v.co.y = -v.co.y
    bmesh.ops.reverse_faces(bm, faces=bm.faces, flip_multires=False)
    bm.to_mesh(me)
    bm.free()
    return me


# --------------------------------------------------------------------------- hidden faces


def cull_hidden(target, occluders=(), elevations=(20.0, 28.0, 36.0), step_deg=15.0):
    """Delete faces of `target` that no main-view ray can see, for any heading of the
    machine (the camera is fixed; the machine turns about Z) and elevations 20-36 deg.
    A face stays if any of 5 sample points has a free ray toward the camera."""
    from mathutils.bvhtree import BVHTree
    bm_all = bmesh.new()
    for ob in [target] + list(occluders):
        tmp = bmesh.new()
        tmp.from_mesh(ob.data)
        tmp.transform(ob.matrix_world)
        me = bpy.data.meshes.new("_occ")
        tmp.to_mesh(me)
        tmp.free()
        bm_all.from_mesh(me)
        bpy.data.meshes.remove(me)
    tree = BVHTree.FromBMesh(bm_all)
    bm_all.free()
    dirs = []
    for el in elevations:
        e = math.radians(el)
        a = 0.0
        while a < 360.0 - 1e-6:
            r = math.radians(a)
            dirs.append(Vector((math.sin(r) * math.cos(e), -math.cos(r) * math.cos(e), math.sin(e))))
            a += step_deg
    bm = bmesh.new()
    bm.from_mesh(target.data)
    mw = target.matrix_world
    nm = mw.to_3x3().inverted().transposed()
    dead = []
    for f in bm.faces:
        n = (nm @ f.normal).normalized()
        c = mw @ f.calc_center_median()
        pts = [c] + [c.lerp(mw @ v.co, 0.75) for v in f.verts]
        seen = False
        for d in dirs:
            if n.dot(d) <= 0.02:
                continue
            for p in pts:
                hit = tree.ray_cast(p + n * 0.003 + d * 0.003, d, 500.0)
                if hit[0] is None:
                    seen = True
                    break
            if seen:
                break
        if not seen:
            dead.append(f)
    before = len(bm.faces)
    bmesh.ops.delete(bm, geom=dead, context="FACES")
    bm.to_mesh(target.data)
    bm.free()
    target.data.update()
    log(f"cull_hidden {target.name}: {before} -> {before - len(dead)} faces")
    return len(dead)


def pushpull_fill(img):
    """Fill pixels the bake left empty (alpha 0) from a coarser average (push-pull), so
    mipmaps never mix black gaps into the islands. Keeps baked pixels as they are."""
    import numpy as np
    w, h = img.size
    arr = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(arr)
    arr = arr.reshape(h, w, 4)
    a = (arr[..., 3] > 0.5).astype(np.float32)
    rgb = arr[..., :3]
    levels = []
    c, wt = rgb * a[..., None], a
    while min(c.shape[:2]) > 1:
        levels.append((c, wt))
        hh, ww = c.shape[0] // 2, c.shape[1] // 2
        c = c[:hh * 2, :ww * 2].reshape(hh, 2, ww, 2, 3).sum(axis=(1, 3))
        wt = wt[:hh * 2, :ww * 2].reshape(hh, 2, ww, 2).sum(axis=(1, 3))
    col = c / np.maximum(wt, 1e-8)[..., None]
    for cl, wl in reversed(levels):
        up = col.repeat(2, axis=0).repeat(2, axis=1)[:cl.shape[0], :cl.shape[1]]
        own = cl / np.maximum(wl, 1e-8)[..., None]
        col = np.where(wl[..., None] > 0, own, up)
    out = np.concatenate([col, np.ones((h, w, 1), dtype=np.float32)], axis=2)
    out[a > 0.5, :3] = rgb[a > 0.5]
    img.pixels.foreach_set(out.ravel())
    img.update()
    return a


# --------------------------------------------------------------------------- UV + bake


def unwrap(objs, margin=0.005, angle=60.0, weights=None):
    """One shared UV atlas over several objects (smart project + pack)."""
    for ob in objs:
        if not ob.data.uv_layers:
            ob.data.uv_layers.new(name="UVMap")
    select_only(objs, objs[0])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(angle), island_margin=margin * 0.5,
                             area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    if weights:
        # enlarge or shrink some objects' islands before packing (texel priority)
        for ob in objs:
            w = weights.get(ob.name, 1.0)
            if w != 1.0:
                uv = ob.data.uv_layers.active.data
                for l in uv:
                    l.uv = l.uv * w
    select_only(objs, objs[0])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.pack_islands(udim_source="CLOSEST_UDIM", rotate=True, rotate_method="AXIS_ALIGNED",
                            scale=True, margin_method="FRACTION", margin=margin, shape_method="CONCAVE")
    bpy.ops.object.mode_set(mode="OBJECT")


BAKE_MASKS = {}


def bake_emit(objs, image_name, size, samples=None, margin=3):
    """Bake the emission of the paint materials of objs into one new image."""
    img = bpy.data.images.new(image_name, size, size, alpha=True, float_buffer=False)
    img.colorspace_settings.name = "sRGB"
    img.generated_color = (0.0, 0.0, 0.0, 0.0)
    mats = {m for ob in objs for m in ob.data.materials if m}
    for m in mats:
        tex = m.node_tree.nodes.new("ShaderNodeTexImage")
        tex.name = "BAKE_TARGET"
        tex.image = img
        for n in m.node_tree.nodes:
            n.select = False
        tex.select = True
        m.node_tree.nodes.active = tex
    scene = bpy.context.scene
    scene.cycles.samples = samples or BAKE_SAMPLES
    scene.render.bake.margin = margin
    scene.render.bake.margin_type = "EXTEND"
    scene.render.bake.use_clear = True
    scene.render.bake.target = "IMAGE_TEXTURES"
    select_only(objs, objs[0])
    t = time.perf_counter()
    bpy.ops.object.bake(type="EMIT", use_clear=True, margin=margin)
    mask = pushpull_fill(img)
    img["cover"] = float(mask.mean())
    BAKE_MASKS[img.name] = mask
    log(f"baked {image_name} {size}px in {time.perf_counter() - t:.1f}s, islands+margin cover {mask.mean():.0%}")
    for m in mats:
        n = m.node_tree.nodes.get("BAKE_TARGET")
        if n:
            m.node_tree.nodes.remove(n)
    return img


def save_image(img, path, fmt="PNG", quality=92):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    scene = bpy.context.scene
    s = scene.render.image_settings
    old = (s.file_format, s.color_mode, getattr(s, "quality", 90))
    s.file_format = fmt
    s.color_mode = "RGB"
    if fmt == "JPEG":
        s.quality = quality
    img.save_render(path, scene=scene)
    s.file_format, s.color_mode = old[0], old[1]
    return path


# --------------------------------------------------------------------------- outlines (inverted hull)

OUTLINE_HEX = "#2A2018"
OUTLINE_T = 0.05          # scene metres: ~1.3 px at the close zoom, ~0.4 px at the overview


def paint_outline_block(img, block=12, guard=6):
    """Find an empty square in the atlas (no island, no margin), paint it in the outline
    colour, return its centre in UV. The hull faces sample only this block."""
    import numpy as np
    mask = BAKE_MASKS[img.name]
    h, w = mask.shape
    need = block + 2 * guard
    occ = mask > 0
    sat = np.pad(occ.astype(np.int64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    best = None
    for y in range(0, h - need, 4):
        for x in range(0, w - need, 4):
            n = sat[y + need, x + need] - sat[y, x + need] - sat[y + need, x] + sat[y, x]
            if n == 0:
                best = (x, y)
                break
        if best:
            break
    if best is None:
        raise RuntimeError("no free block in the atlas for the outline colour")
    x0, y0 = best[0] + guard, best[1] + guard
    arr = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(arr)
    arr = arr.reshape(h, w, 4)
    col = [int(OUTLINE_HEX[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    arr[y0:y0 + block, x0:x0 + block, :3] = col
    img.pixels.foreach_set(arr.ravel())
    img.update()
    return ((x0 + block / 2) / w, (y0 + block / 2) / h)


def _offset_shell(bm, t):
    """Push all verts of bm out by t (even thickness) and flip the faces inward."""
    bm.normal_update()
    moves = {}
    for v in bm.verts:
        fn = [f.normal for f in v.link_faces]
        if not fn:
            continue
        n = sum(fn, Vector()).normalized()
        k = min(max(n.dot(x), 0.5) for x in fn)
        moves[v] = n * (t / k)
    for v, d in moves.items():
        v.co += d
    bmesh.ops.reverse_faces(bm, faces=bm.faces)


def add_body_hull(target, source_mesh, uv_point, t=OUTLINE_T, min_diag=0.9, min_faces=6, skip=()):
    """Append an inverted hull (outline) of the big connected parts of source_mesh to
    target (same material, UVs on the outline block)."""
    src = bmesh.new()
    src.from_mesh(source_mesh)
    seen, comps = set(), []
    for f in src.faces:
        if f in seen:
            continue
        stack, comp = [f], []
        seen.add(f)
        while stack:
            g = stack.pop()
            comp.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h not in seen:
                        seen.add(h)
                        stack.append(h)
        comps.append(comp)
    hull = bmesh.new()
    kept = 0
    skip_idx = {i for i, m in enumerate(source_mesh.materials) if m and m.get("palette") in skip}
    for comp in comps:
        if len(comp) < min_faces:
            continue
        if any(f.material_index in skip_idx for f in comp):
            continue
        pts = [v.co for f in comp for v in f.verts]
        lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
        hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
        if (hi - lo).length < min_diag:
            continue
        kept += 1
        tmp = bmesh.new()
        idx = {}
        for f in comp:
            vs = []
            for v in f.verts:
                if v not in idx:
                    idx[v] = tmp.verts.new(v.co)
                vs.append(idx[v])
            try:
                tmp.faces.new(vs)
            except ValueError:
                pass
        _offset_shell(tmp, t)
        me = bpy.data.meshes.new("_hull")
        tmp.to_mesh(me)
        tmp.free()
        hull.from_mesh(me)
        bpy.data.meshes.remove(me)
    src.free()
    n = _append_with_uv(target.data, hull, uv_point)
    log(f"outline hull on {target.name}: {kept} parts, {n} triangles")
    return n


def add_wheel_hull(mesh, radius, half_w, uv_point, t=OUTLINE_T, sides=12):
    """Inverted cylinder around a tyre (axle along Y) as its outline."""
    bm = bmesh.new()
    r, hw = (radius + t * 0.6) / math.cos(math.pi / sides), half_w + t
    a = [bm.verts.new((r * math.cos(2 * math.pi * (k + 0.5) / sides), -hw,
                       r * math.sin(2 * math.pi * (k + 0.5) / sides))) for k in range(sides)]
    b = [bm.verts.new((v.co.x, hw, v.co.z)) for v in a]
    for k in range(sides):
        j = (k + 1) % sides
        bm.faces.new((a[k], b[k], b[j], a[j]))
    bm.faces.new(a)
    bm.faces.new(list(reversed(b)))
    bm.normal_update()
    for f in bm.faces:
        if f.calc_center_median().dot(f.normal) > 0:
            f.normal_flip()
    return _append_with_uv(mesh, bm, uv_point)


def _append_with_uv(mesh, add_bm, uv_point):
    """Append geometry of add_bm to mesh; new loops get UV = uv_point, material 0."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    uvl = bm.loops.layers.uv.active or bm.loops.layers.uv.new("UVMap")
    vmap = {v: bm.verts.new(v.co) for v in add_bm.verts}
    count = 0
    for f in add_bm.faces:
        try:
            nf = bm.faces.new([vmap[v] for v in f.verts])
        except ValueError:
            continue
        nf.material_index = 0
        nf.smooth = False
        for lp in nf.loops:
            lp[uvl].uv = uv_point
        count += len(f.verts) - 2
    add_bm.free()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return count


# --------------------------------------------------------------------------- final materials


def unlit_texture_material(name, img):
    """Exported as KHR_materials_unlit with a base colour texture (lightpath trick)."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True if getattr(mat, "node_tree", None) is None else mat.use_nodes
    t = mat.node_tree
    t.nodes.clear()
    out = t.nodes.new("ShaderNodeOutputMaterial")
    tex = t.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Linear"
    emit = t.nodes.new("ShaderNodeEmission")
    lp = t.nodes.new("ShaderNodeLightPath")
    mix = t.nodes.new("ShaderNodeMixShader")
    tr = t.nodes.new("ShaderNodeBsdfTransparent")
    t.links.new(tex.outputs["Color"], emit.inputs["Color"])
    t.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    t.links.new(tr.outputs[0], mix.inputs[1])
    t.links.new(emit.outputs[0], mix.inputs[2])
    t.links.new(mix.outputs[0], out.inputs["Surface"])
    mat.use_backface_culling = True
    mat.diffuse_color = (0.8, 0.6, 0.1, 1.0)
    return mat


def unlit_color_material(name, hex_color):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True if getattr(mat, "node_tree", None) is None else mat.use_nodes
    t = mat.node_tree
    t.nodes.clear()
    out = t.nodes.new("ShaderNodeOutputMaterial")
    emit = t.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = hex_lin(hex_color) + (1.0,)
    lp = t.nodes.new("ShaderNodeLightPath")
    mix = t.nodes.new("ShaderNodeMixShader")
    tr = t.nodes.new("ShaderNodeBsdfTransparent")
    t.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    t.links.new(tr.outputs[0], mix.inputs[1])
    t.links.new(emit.outputs[0], mix.inputs[2])
    t.links.new(mix.outputs[0], out.inputs["Surface"])
    mat.use_backface_culling = True
    mat.diffuse_color = hex_lin(hex_color) + (1.0,)
    return mat


def shadow_material(name):
    """Soft contact shadow: dark colour, alpha from the vertex colour (BLEND, unlit)."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True if getattr(mat, "node_tree", None) is None else mat.use_nodes
    t = mat.node_tree
    t.nodes.clear()
    out = t.nodes.new("ShaderNodeOutputMaterial")
    va = t.nodes.new("ShaderNodeVertexColor")
    va.layer_name = "Col"
    emit = t.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = hex_lin("#17120E") + (1.0,)
    mix = t.nodes.new("ShaderNodeMixShader")
    tr = t.nodes.new("ShaderNodeBsdfTransparent")
    t.links.new(va.outputs["Alpha"], mix.inputs[0])
    t.links.new(tr.outputs[0], mix.inputs[1])
    t.links.new(emit.outputs[0], mix.inputs[2])
    t.links.new(mix.outputs[0], out.inputs["Surface"])
    mat.use_backface_culling = True
    mat.surface_render_method = "BLENDED"
    return mat


def build_shadow(name, parent, half_x, half_y, cx=0.0, alpha=0.55, z=0.03, n=28):
    """Superellipse blob under a machine: centre and inner ring dark, outer ring clear."""
    bm = bmesh.new()
    col = bm.loops.layers.color.new("Col")
    rings = []
    for scale, a in ((0.0, alpha), (0.82, alpha * 0.85), (1.18, 0.0)):
        if scale == 0.0:
            rings.append(([bm.verts.new((cx, 0.0, z))], a))
            continue
        ring = []
        for k in range(n):
            t = 2 * math.pi * k / n
            c, s = math.cos(t), math.sin(t)
            e = 2.0 / 4.0
            x = cx + half_x * scale * math.copysign(abs(c) ** e, c)
            y = half_y * scale * math.copysign(abs(s) ** e, s)
            ring.append(bm.verts.new((x, y, z)))
        rings.append((ring, a))
    centre = rings[0][0][0]
    faces = []
    r1 = rings[1][0]
    for k in range(n):
        faces.append(bm.faces.new((centre, r1[k], r1[(k + 1) % n])))
    for (ra, _), (rb, _) in zip(rings[1:], rings[2:]):
        for k in range(n):
            j = (k + 1) % n
            faces.append(bm.faces.new((ra[k], rb[k], rb[j], ra[j])))
    alpha_of = {}
    for ring, a in rings:
        for v in ring:
            alpha_of[v] = a
    for f in faces:
        if f.normal.z < 0:
            f.normal_flip()
        for l in f.loops:
            l[col] = (0.09, 0.07, 0.055, alpha_of[l.vert])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = parent
    me.materials.append(shadow_material(name.lower() + "_blob"))
    return ob


# --------------------------------------------------------------------------- export


def export_glb(root, path, animations=False):
    """Export root and its hierarchy; then patch the GLB (unlit check, blend shadow)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    objs = [root] + list(root.children_recursive)
    select_only(objs, root)
    kwargs = dict(filepath=path, export_format="GLB", use_selection=True, export_extras=True,
                  export_yup=True, export_apply=False, export_texcoords=True, export_normals=False,
                  export_tangents=False, export_materials="EXPORT", export_image_format="JPEG",
                  export_jpeg_quality=92, export_image_quality=92, export_cameras=False,
                  export_lights=False, export_vertex_color="MATERIAL",
                  export_animations=animations, export_skins=True, export_morph=False)
    if animations:
        kwargs.update(export_animation_mode="NLA_TRACKS", export_force_sampling=True,
                      export_frame_step=1, export_optimize_animation_size=False,
                      export_anim_slide_to_zero=False, export_reset_pose_bones=True,
                      export_def_bones=False, export_leaf_bone=False)
    bpy.ops.export_scene.gltf(**kwargs)
    return path


def read_glb(path):
    with open(path, "rb") as f:
        data = f.read()
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF", path
    off = 12
    js, binc = None, b""
    while off < length:
        clen, ctype = struct.unpack_from("<I4s", data, off)
        chunk = data[off + 8: off + 8 + clen]
        if ctype == b"JSON":
            js = json.loads(chunk.decode("utf-8"))
        elif ctype == b"BIN\x00":
            binc = chunk
        off += 8 + clen
    return js, binc


def write_glb(path, js, binc):
    jb = json.dumps(js, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((4 - len(jb) % 4) % 4)
    bb = binc + b"\x00" * ((4 - len(binc) % 4) % 4)
    total = 12 + 8 + len(jb) + (8 + len(bb) if bb else 0)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<I4s", len(jb), b"JSON"))
        f.write(jb)
        if bb:
            f.write(struct.pack("<I4s", len(bb), b"BIN\x00"))
            f.write(bb)


def patch_glb(path, scene_extras=None, blend_materials=(), lamp_materials=(), anim_extras=None):
    """Make every material unlit, mark shadow materials BLEND, add scene extras."""
    js, binc = read_glb(path)
    used = set(js.get("extensionsUsed", []))
    for m in js.get("materials", []):
        ext = m.setdefault("extensions", {})
        ext.setdefault("KHR_materials_unlit", {})
        m.pop("emissiveTexture", None)
        pbr = m.setdefault("pbrMetallicRoughness", {})
        pbr["metallicFactor"] = 0.0
        pbr["roughnessFactor"] = 1.0
        m["doubleSided"] = False
        if m.get("name") in blend_materials:
            m["alphaMode"] = "BLEND"
            pbr["baseColorFactor"] = [0.0075, 0.0060, 0.0045, 1.0]
        if m.get("name") in lamp_materials:
            lin = hex_lin(LAMP_ON_HEX)
            pbr["baseColorFactor"] = [lin[0], lin[1], lin[2], 1.0]
            m["emissiveFactor"] = [lin[0], lin[1], lin[2]]
            m["extras"] = {"lampOn": LAMP_ON_HEX, "lampOff": LAMP_OFF_HEX}
        if "emissiveFactor" in m and m.get("name") not in lamp_materials:
            m.pop("emissiveFactor")
    # the exporter writes an all-white COLOR_0 and our blob alpha as COLOR_1: keep ours
    for mesh in js.get("meshes", []):
        for prim in mesh.get("primitives", []):
            at = prim.get("attributes", {})
            if "COLOR_1" in at:
                at["COLOR_0"] = at.pop("COLOR_1")
    used.add("KHR_materials_unlit")
    js["extensionsUsed"] = sorted(used)
    if scene_extras:
        for sc in js.get("scenes", []):
            sc.setdefault("extras", {}).update(scene_extras)
    if anim_extras:
        for a in js.get("animations", []):
            if a.get("name") in anim_extras:
                a.setdefault("extras", {}).update(anim_extras[a["name"]])
    js.setdefault("asset", {})["copyright"] = "Team mine-art actors, built procedurally in Blender (MIT)"
    write_glb(path, js, binc)


# --------------------------------------------------------------------------- previews


def make_world(hex_color):
    w = bpy.context.scene.world
    w.use_nodes = True if getattr(w, "node_tree", None) is None else w.use_nodes
    bg = next((n for n in w.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg is None:
        bg = w.node_tree.nodes.new("ShaderNodeBackground")
        out = next(n for n in w.node_tree.nodes if n.type == "OUTPUT_WORLD")
        w.node_tree.links.new(bg.outputs[0], out.inputs[0])
    bg.inputs["Color"].default_value = hex_lin(hex_color) + (1.0,)
    bg.inputs["Strength"].default_value = 1.0


def ensure_camera():
    cam = bpy.data.objects.get("PREVIEW_CAM")
    if cam is None:
        cd = bpy.data.cameras.new("PREVIEW_CAM")
        cd.type = "ORTHO"
        cam = bpy.data.objects.new("PREVIEW_CAM", cd)
        bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    return cam


def world_bbox(objs):
    pts = []
    dg = bpy.context.evaluated_depsgraph_get()
    for ob in objs:
        if ob.type != "MESH" or ob.hide_render:
            continue
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        mw = ev.matrix_world
        pts += [mw @ v.co for v in me.vertices]
        ev.to_mesh_clear()
    return pts


def render_tile(objs, ppm, path, pad=10, min_w=0, min_h=0, centre=None, size=None):
    """Orthographic render of objs from the main view at ppm pixels per metre."""
    scene = bpy.context.scene
    cam = ensure_camera()
    d = view_dir()
    fwd = -d
    right = fwd.cross(Vector((0, 0, 1))).normalized()
    up = right.cross(fwd).normalized()
    if size is None or centre is None:
        pts = world_bbox(objs)
        us = [p.dot(right) for p in pts]
        vs = [p.dot(up) for p in pts]
        ws = [p.dot(d) for p in pts]
        cu, cv = (min(us) + max(us)) / 2, (min(vs) + max(vs)) / 2
        cw = (min(ws) + max(ws)) / 2
        centre = right * cu + up * cv + d * cw
        wpx = int(math.ceil((max(us) - min(us)) * ppm)) + 2 * pad
        hpx = int(math.ceil((max(vs) - min(vs)) * ppm)) + 2 * pad
    else:
        wpx, hpx = size
    wpx, hpx = max(wpx, min_w), max(hpx, min_h)
    wpx += wpx % 2
    hpx += hpx % 2
    scene.render.resolution_x = wpx
    scene.render.resolution_y = hpx
    cam.data.ortho_scale = max(wpx, hpx) / ppm
    cam.data.clip_start = 0.1
    cam.data.clip_end = 400.0
    cam.location = centre + d * 150.0
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path, (wpx, hpx), centre


def load_rgba(path):
    import numpy as np
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    arr = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(arr)
    bpy.data.images.remove(img)
    return arr.reshape(h, w, 4)[::-1]          # top row first


def save_rgba(arr, path):
    import numpy as np
    h, w, _ = arr.shape
    img = bpy.data.images.new(os.path.basename(path), w, h, alpha=True)
    img.colorspace_settings.name = "sRGB"
    img.pixels.foreach_set(np.ascontiguousarray(arr[::-1]).astype(np.float32).ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def compose_row(paths, out, gap=6, bg=(0.10, 0.10, 0.10), labels=None, upscale=1):
    """Lay tiles side by side, bottom-aligned, on a dark strip; optional nearest upscale."""
    import numpy as np
    tiles = [load_rgba(p) for p in paths]
    h = max(t.shape[0] for t in tiles)
    w = sum(t.shape[1] for t in tiles) + gap * (len(tiles) + 1)
    canvas = np.zeros((h + 2 * gap, w, 4), dtype=np.float32)
    canvas[..., 0], canvas[..., 1], canvas[..., 2], canvas[..., 3] = bg[0], bg[1], bg[2], 1.0
    x = gap
    for t in tiles:
        th, tw = t.shape[:2]
        y = gap + (h - th)
        canvas[y:y + th, x:x + tw] = t
        x += tw + gap
    if upscale > 1:
        canvas = canvas.repeat(upscale, axis=0).repeat(upscale, axis=1)
    save_rgba(canvas, out)
    return out


def compose_grid(rows, out, gap=6, bg=(0.10, 0.10, 0.10)):
    """rows: list of lists of image paths; rows stacked vertically, left-aligned."""
    import numpy as np
    loaded = [[load_rgba(p) for p in r] for r in rows]
    row_h = [max(t.shape[0] for t in r) for r in loaded]
    row_w = [sum(t.shape[1] for t in r) + gap * (len(r) + 1) for r in loaded]
    W, H = max(row_w), sum(row_h) + gap * (len(rows) + 1)
    canvas = np.zeros((H, W, 4), dtype=np.float32)
    canvas[..., 0], canvas[..., 1], canvas[..., 2], canvas[..., 3] = bg[0], bg[1], bg[2], 1.0
    y = gap
    for r, rh in zip(loaded, row_h):
        x = gap
        for t in r:
            th, tw = t.shape[:2]
            canvas[y + rh - th:y + rh, x:x + tw] = t
            x += tw + gap
        y += rh + gap
    save_rgba(canvas, out)
    return out


HEADINGS = (("E", 0.0), ("SE", -45.0), ("S", -90.0), ("W", 180.0))


def render_headings(root, objs, ppm, tag, prefix, headings=HEADINGS, upscale=1):
    """One tile per heading (machine turned about Z), composed into one row image."""
    tiles = []
    tmp = os.path.join(PREVIEW_DIR, "_tiles")
    os.makedirs(tmp, exist_ok=True)
    root.rotation_mode = "XYZ"
    rot0 = root.rotation_euler.copy()
    for hname, deg in headings:
        root.rotation_euler = (0.0, 0.0, math.radians(deg))
        bpy.context.view_layer.update()
        p = os.path.join(tmp, f"{prefix}_{tag}_{hname}.png")
        render_tile(objs, ppm, p, pad=8)
        tiles.append(p)
    root.rotation_euler = rot0
    out = os.path.join(PREVIEW_DIR, f"{prefix}_{tag}.png")
    compose_row(tiles, out, upscale=upscale)
    return out


# --------------------------------------------------------------------------- GLB re-import (what three.js shows)


def reimport_unlit(path):
    """Import a GLB into the (cleared) scene with emission-only materials, as three.js
    shows KHR_materials_unlit: colour = baseColorTexture x baseColorFactor x COLOR_0."""
    reset_scene("check")
    bpy.ops.import_scene.gltf(filepath=path)
    js, _ = read_glb(path)
    gm = {m.get("name"): m for m in js.get("materials", [])}
    for mat in bpy.data.materials:
        g = gm.get(mat.name)
        if g is None or getattr(mat, "node_tree", None) is None:
            continue
        t = mat.node_tree
        img = next((n.image for n in t.nodes if n.type == "TEX_IMAGE" and n.image), None)
        pbr = g.get("pbrMetallicRoughness", {})
        fac = pbr.get("baseColorFactor", [1, 1, 1, 1])
        blend = g.get("alphaMode") == "BLEND"
        t.nodes.clear()
        out = t.nodes.new("ShaderNodeOutputMaterial")
        emit = t.nodes.new("ShaderNodeEmission")
        colour = None
        if img is not None:
            tex = t.nodes.new("ShaderNodeTexImage")
            tex.image = img
            colour = tex.outputs["Color"]
        mulf = t.nodes.new("ShaderNodeVectorMath")
        mulf.operation = "MULTIPLY"
        mulf.inputs[1].default_value = fac[:3]
        if colour is not None:
            t.links.new(colour, mulf.inputs[0])
        else:
            mulf.inputs[0].default_value = (1, 1, 1)
        t.links.new(mulf.outputs[0], emit.inputs["Color"])
        if blend:
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
    setup_cycles(32)
    enable_backface_culling_cycles()
    roots = [o for o in bpy.data.objects if o.parent is None]
    return roots, js


def enable_backface_culling_cycles():
    """Cycles ignores material backface culling; emulate it with a Backfacing mix."""
    for mat in bpy.data.materials:
        t = getattr(mat, "node_tree", None)
        if t is None or not mat.use_backface_culling:
            continue
        out = next((n for n in t.nodes if n.type == "OUTPUT_MATERIAL"), None)
        if out is None or not out.inputs["Surface"].links:
            continue
        src = out.inputs["Surface"].links[0].from_socket
        geo = t.nodes.new("ShaderNodeNewGeometry")
        mix = t.nodes.new("ShaderNodeMixShader")
        tr = t.nodes.new("ShaderNodeBsdfTransparent")
        t.links.new(geo.outputs["Backfacing"], mix.inputs[0])
        t.links.new(src, mix.inputs[1])
        t.links.new(tr.outputs[0], mix.inputs[2])
        t.links.new(mix.outputs[0], out.inputs["Surface"])


# --------------------------------------------------------------------------- machine assembly


def build_machine(name, kind, body, lamps, wheel_part, wheels, wheel_z, wheel_half_w, tex_size=1024,
                  shadow_pad=(1.08, 1.12), extra=None, hull_min_diag=0.9, hull_skip=()):
    """Common pipeline of lhd.py, truck.py, drill.py.

    body, lamps: Parts in real metres (origin anywhere; recentred here).
    wheel_part: Part of the LEFT wheel, built around its axle (outer face +Y).
    wheels: [(tag, x, y)] axle centres in real metres (same frame as body), y > 0 left.
    wheel_z: axle height (real metres) = tyre radius at the lugs.
    """
    sc = MACHINE_SCALE
    xs = [v.co.x for v in body.bm.verts]
    ys = [v.co.y for v in body.bm.verts]
    xs += [x for _, x, _ in wheels]
    ys += [y + math.copysign(0.4, y) for _, _, y in wheels]
    # x: middle of the length; y: the vehicle centreline (wheel tracks are symmetric)
    cx, cy = (min(xs) + max(xs)) / 2, 0.0
    length_real, width_real = max(xs) - min(xs), max(ys) - min(ys)
    shift = Vector((-cx, -cy, 0.0))
    for part in (body, lamps):
        bmesh.ops.translate(part.bm, vec=shift, verts=part.bm.verts)
    height_real = max(v.co.z for v in body.bm.verts)
    height_real = max(height_real, max((v.co.z for v in lamps.bm.verts), default=0.0))

    root = empty(name)
    body_ob = body.to_object(root, scale=sc, cull_down=True)
    body_ob.name = f"{name}_body"
    lamps_ob = lamps.to_object(root, scale=sc)
    lamps_ob.name = "LAMPS"
    wheels_e = empty("WHEELS", root)
    proto = wheel_part.to_object(None, scale=sc, smooth_angle=50)
    proto.name = f"{name}_wheel_bake"
    wheel_obs = []
    for tag, x, y in wheels:
        ob = bpy.data.objects.new(f"WHEEL_{tag}", proto.data)
        bpy.context.scene.collection.objects.link(ob)
        ob.parent = wheels_e
        ob.location = ((x + shift.x) * sc, (y + shift.y) * sc, wheel_z * sc)
        if y < 0:
            ob.rotation_euler = (0.0, 0.0, math.pi)     # temporary, for culling only
        wheel_obs.append(ob)
    bpy.context.view_layer.update()
    hull_src = body_ob.data.copy()
    cull_hidden(body_ob, occluders=wheel_obs + [lamps_ob])
    unwrap([body_ob, proto])
    me_l = proto.data
    me_l.name = f"{name}_wheel_L"
    for ob in wheel_obs:
        ob.rotation_euler = (0.0, 0.0, 0.0)
    proto.location = (120.0, 0.0, 30.0)
    bpy.context.view_layer.update()
    img = bake_emit([body_ob, proto], f"{name}_paint", tex_size)
    uv_dark = paint_outline_block(img)
    save_image(img, os.path.join(HERE, "textures", f"{name}_paint.png"))

    lamp_mat = unlit_color_material(f"{name}_lamps", LAMP_ON_HEX)
    lamps_ob.data.materials.clear()
    lamps_ob.data.materials.append(lamp_mat)
    shadow = build_shadow("SHADOW", root, length_real * sc / 2 * shadow_pad[0],
                          width_real * sc / 2 * shadow_pad[1])
    objs = [body_ob, lamps_ob] + wheel_obs
    if DO_RENDER:
        make_world(FLOOR_HEX)
        setup_cycles(48)
        for tag, ppm in (("overview", PPM_OVERVIEW), ("close", PPM_CLOSE)):
            render_headings(root, objs + [shadow], ppm, tag, f"{name}_source")
    bpy.data.objects.remove(proto, do_unlink=True)

    # outlines: inverted hulls of the big parts and the tyres, coloured by the dark block
    add_body_hull(body_ob, hull_src, uv_dark, min_diag=hull_min_diag, skip=hull_skip)
    bpy.data.meshes.remove(hull_src)
    add_wheel_hull(me_l, wheel_z * sc, wheel_half_w * sc, uv_dark)
    me_r = mirror_mesh_y(me_l, f"{name}_wheel_R")
    for ob, (tag, x, y) in zip(wheel_obs, wheels):
        if y < 0:
            ob.data = me_r

    paint = unlit_texture_material(f"{name}_paint", img)
    for me in (body_ob.data, me_l, me_r):
        me.materials.clear()
        me.materials.append(paint)
    tris = {o.name: tri_count(o) for o in objs + [shadow]}
    log("triangles", sum(tris.values()), tris)

    root["actor"] = name
    root["kind"] = kind
    root["scaleToReal"] = sc
    root["lengthM"] = round(length_real * sc, 3)
    root["widthM"] = round(width_real * sc, 3)
    root["heightM"] = round(height_real * sc, 3)
    root["facing"] = "+X"
    root["origin"] = "ground, centre of the footprint"
    root["wheelRadiusM"] = round(wheel_z * sc, 3)
    root["wheelSpinAxis"] = [0, 0, -1]
    root["wheelSpin"] = "forward motion: rotate each WHEEL_* about its local wheelSpinAxis by distance / wheelRadiusM (rad)"
    root["lampsNode"] = "LAMPS"
    root["lampOn"] = LAMP_ON_HEX
    root["lampOff"] = LAMP_OFF_HEX
    root["shadowNode"] = "SHADOW"
    for k, v in (extra or {}).items():
        root[k] = v

    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, f"{name}.blend"), compress=True)
    glb = os.path.join(OUT_DIR, f"{name}.glb")
    export_glb(root, glb)
    patch_glb(glb, scene_extras={"mineArtActor": name}, blend_materials=("shadow_blob",),
              lamp_materials=(f"{name}_lamps",))
    log("exported", glb, os.path.getsize(glb))
    if DO_RENDER:
        render_glb_check(glb, name)
    return glb


def render_glb_check(glb, name):
    roots, _ = reimport_unlit(glb)
    make_world(FLOOR_HEX)
    r = next(o for o in roots if o.name == name)
    meshes = [o for o in r.children_recursive if o.type == "MESH"]
    out = []
    for tag, ppm in (("overview", PPM_OVERVIEW), ("close", PPM_CLOSE)):
        out.append(render_headings(r, meshes, ppm, tag, f"{name}_glb_unlit"))
    return out
