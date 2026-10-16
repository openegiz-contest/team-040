"""Materials (procedural, rendered into the projected textures), world and lights.

Painted light: every surface carries a painted key light in its emission, a value set
by the orientation of its flat facet to a soft key from the upper left (KEY), so the
rock reads in 3-4 values per orientation like the references (upper planes light,
undersides dark), independent of shadows. The warm lamps (2700 K) are real lights on
top of that (diffuse only): pools on floors and walls, facets warming up near them.
No sun; emissive surfaces are not sampled as lights (emission_sampling NONE).
"""

import math

import bpy
from mathutils import Vector

LAMP_RGB = (1.0, 0.546, 0.195)          # #FFC37A in linear
LAMP_POWER = 11000.0                      # W, spot lights of drift lamps
KEY = Vector((-0.35, -0.45, 0.82)).normalized()   # toward the painted key light

_lamp_specs = []    # (location, direction, power, kind) collected by props


def srgb(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c) + (1.0,)


class NB:
    """Tiny node-tree builder."""

    def __init__(self, mat):
        mat.use_nodes = True
        try:
            mat.emission_sampling = "NONE"
        except AttributeError:
            pass
        self.nt = mat.node_tree
        self.nt.nodes.clear()
        self.x = 0

    def n(self, kind, **props):
        node = self.nt.nodes.new(kind)
        node.location = (self.x, 0)
        self.x += 180
        for k, v in props.items():
            if not k.startswith("in_"):
                setattr(node, k, v)
        for k, v in props.items():
            if k.startswith("in_"):
                key = k[3:]
                key = int(key) if key.isdigit() else key.replace("__", " ")
                node.inputs[key].default_value = v
        return node

    def link(self, a, b):
        self.nt.links.new(a, b)

    def _set(self, sock, v):
        if isinstance(v, (int, float)):
            sock.default_value = v
        elif isinstance(v, tuple):
            sock.default_value = tuple(v) + (1.0,) * (4 - len(v)) if len(sock.default_value) == 4 else v[:3]
        else:
            self.link(v, sock)

    def math(self, op, a, b=None, clamp=False):
        m = self.n("ShaderNodeMath", operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b)):
            if v is not None:
                self._set(m.inputs[i], v)
        return m.outputs[0]

    def mix(self, fac, a, b, blend="MIX"):
        m = self.n("ShaderNodeMix", data_type="RGBA", blend_type=blend)
        for sock, v in ((m.inputs[0], fac), (m.inputs[6], a), (m.inputs[7], b)):
            self._set(sock, v)
        return m.outputs[2]

    def ramp(self, fac, stops, interp="LINEAR"):
        r = self.n("ShaderNodeValToRGB")
        cr = r.color_ramp
        cr.interpolation = interp
        while len(cr.elements) < len(stops):
            cr.elements.new(0.5)
        for el, (pos, col) in zip(cr.elements, stops):
            el.position = pos
            el.color = col
        self.link(fac, r.inputs[0])
        return r.outputs[0]

    def scale(self, col, f):
        """Colour times a scalar socket or number."""
        m = self.n("ShaderNodeVectorMath", operation="SCALE")
        self._set(m.inputs[0], col)
        self._set(m.inputs["Scale"], f)
        return m.outputs[0]

    def out(self, albedo, emission):
        """Diffuse (lamps only, no gloss) plus the painted emission."""
        bsdf = self.n("ShaderNodeBsdfDiffuse")
        bsdf.inputs["Roughness"].default_value = 1.0
        self._set(bsdf.inputs["Color"], albedo)
        em = self.n("ShaderNodeEmission")
        em.inputs["Strength"].default_value = 1.0
        self._set(em.inputs["Color"], emission)
        add = self.n("ShaderNodeAddShader")
        self.link(bsdf.outputs[0], add.inputs[0])
        self.link(em.outputs[0], add.inputs[1])
        o = self.n("ShaderNodeOutputMaterial")
        self.link(add.outputs[0], o.inputs["Surface"])


def _coords(nb, kind="Object"):
    return nb.n("ShaderNodeTexCoord").outputs[kind]


def key_t(nb):
    """0.5 + 0.5 * (flat facet normal . KEY): the painted key light of a facet."""
    geo = nb.n("ShaderNodeNewGeometry")
    dot = nb.n("ShaderNodeVectorMath", operation="DOT_PRODUCT")
    nb.link(geo.outputs["True Normal"], dot.inputs[0])
    dot.inputs[1].default_value = tuple(KEY)
    return nb.math("ADD", nb.math("MULTIPLY", dot.outputs["Value"], 0.5), 0.5)


def facet_rand(nb):
    """Per-facet random colour (face attribute `fr`, see env_geom.facet_attributes)."""
    a = nb.n("ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name="fr")
    sep = nb.n("ShaderNodeSeparateColor")
    nb.link(a.outputs["Color"], sep.inputs[0])
    return sep.outputs[0], sep.outputs[1], sep.outputs[2]


def facet_jitter(nb, col, r, g, amount=0.12, hue=0.07):
    """Slight value and hue shift per facet."""
    v = nb.math("ADD", 1.0 - amount, nb.math("MULTIPLY", r, 2.0 * amount))
    col = nb.scale(col, v)
    warm = nb.mix(g, (1.0 - hue, 1.0, 1.0 + hue), (1.0 + hue, 1.0, 1.0 - hue * 1.3))
    m = nb.n("ShaderNodeVectorMath", operation="MULTIPLY")
    nb.link(col, m.inputs[0])
    nb.link(warm, m.inputs[1])
    return m.outputs[0]


ORE_POINTS = []      # Blender positions of the two zone faces: ore-rich rock around them


def _ore_mask(nb, co, radius=80.0):
    m = None
    for p in ORE_POINTS:
        vd = nb.n("ShaderNodeVectorMath", operation="DISTANCE")
        nb.link(co, vd.inputs[0])
        vd.inputs[1].default_value = tuple(p)
        f = nb.math("SUBTRACT", 1.0, nb.math("DIVIDE", vd.outputs["Value"], radius), clamp=True)
        m = f if m is None else nb.math("MAXIMUM", m, f)
    return m


def _noise(nb, co, scale, w=0.0, detail=0.0):
    nz = nb.n("ShaderNodeTexNoise", noise_dimensions="4D", in_Scale=scale, in_Detail=detail,
              in_Roughness=0.5, in_W=w)
    nb.link(co, nz.inputs["Vector"])
    return nz.outputs["Fac"]


def vein_bands(nb, co, amount=1.0):
    """Copper veins: continuous diagonal bands (rising to the east) that run across many
    facets. Each family is a set of parallel planes warped by a smooth noise; a band is
    present only on stretches of 60-200 m and tapers at both ends; its width swells
    (0.5-3 m); thin broken streaks run beside it. Returns (core, rim) masks."""
    ore = _ore_mask(nb, co) if ORE_POINTS else None
    cores, rims = [], []
    for ang, period, w0, wv, thr, wseed, tilt in ((28.0, 92.0, 0.5, 2.4, 0.53, 1.3, 0.30),
                                                  (-14.0, 150.0, 0.4, 1.8, 0.58, 4.1, -0.22),
                                                  (58.0, 210.0, 0.4, 1.4, 0.60, 7.7, 0.15)):
        a = math.radians(ang)
        n = Vector((-math.sin(a), tilt, math.cos(a))).normalized()
        dot = nb.n("ShaderNodeVectorMath", operation="DOT_PRODUCT")
        nb.link(co, dot.inputs[0])
        dot.inputs[1].default_value = tuple(n)
        warp = nb.math("MULTIPLY", nb.math("SUBTRACT", _noise(nb, co, 0.0055, wseed), 0.5), 85.0)
        wob = nb.math("MULTIPLY", nb.math("SUBTRACT", _noise(nb, co, 0.045, wseed + 3.0), 0.5), 3.0)
        s_ = nb.math("ADD", nb.math("ADD", dot.outputs["Value"], warp), wob)
        f = nb.math("FRACT", nb.math("DIVIDE", s_, period))
        d = nb.math("MULTIPLY", nb.math("ABSOLUTE", nb.math("SUBTRACT", f, 0.5)), period)
        pres = _noise(nb, co, 0.010, wseed + 5.0, 1.0)
        t = thr / max(amount, 1e-3) if amount < 1.0 else thr
        if ore is not None:
            pres = nb.math("ADD", pres, nb.math("MULTIPLY", ore, 0.5))
        taper = nb.math("DIVIDE", nb.math("SUBTRACT", pres, t), 0.07, clamp=True)
        width = nb.math("ADD", w0, nb.math("MULTIPLY", _noise(nb, co, 0.025, wseed + 2.0), wv))
        if ore is not None:
            width = nb.math("MULTIPLY", width, nb.math("ADD", 1.0, nb.math("MULTIPLY", ore, 0.8)))
        width = nb.math("MULTIPLY", width, taper)
        core = nb.math("LESS_THAN", d, width)
        # thin broken streaks beside the band
        zone = nb.math("LESS_THAN", d, nb.math("ADD", nb.math("MULTIPLY", width, 2.4), 1.2))
        sub = nb.math("LESS_THAN", nb.math("ABSOLUTE", nb.math("SUBTRACT", nb.math("FRACT", nb.math("DIVIDE", s_, 2.9)), 0.5)), 0.11)
        dash = nb.math("GREATER_THAN", _noise(nb, co, 0.06, wseed + 8.0), 0.60)
        sat = nb.math("MULTIPLY", nb.math("MULTIPLY", zone, sub), nb.math("MULTIPLY", dash, nb.math("GREATER_THAN", taper, 0.3)))
        core = nb.math("MAXIMUM", core, sat)
        rim = nb.math("LESS_THAN", d, nb.math("MULTIPLY", nb.math("ADD", width, 0.7), nb.math("GREATER_THAN", taper, 0.0)))
        cores.append(core)
        rims.append(rim)
    core = cores[0]
    rim = rims[0]
    for c, r in zip(cores[1:], rims[1:]):
        core = nb.math("MAXIMUM", core, c)
        rim = nb.math("MAXIMUM", rim, r)
    return core, rim


ROCK_STOPS = [(0.30, "#0e0d0d"), (0.50, "#141312"), (0.60, "#1b1919"), (0.68, "#232120"), (0.75, "#2c2928"),
              (0.82, "#393433"), (0.88, "#4a4441"), (0.95, "#625a55")]
VEIN_STOPS = [(0.30, "#2a1a12"), (0.55, "#47281a"), (0.70, "#6e3d22"), (0.82, "#96582f"), (0.92, "#b8743f")]


def rock_shader(mat, stops=ROCK_STOPS, tint=(1.0, 1.0, 1.0), vein_amt=1.0, albedo="#3b3836"):
    """Faceted rock: painted key value per facet (orientation), slight per-facet hue
    shift, darkened in crevices (local AO), copper vein bands that take the facet value."""
    nb = NB(mat)
    co = _coords(nb)
    t = key_t(nb)
    r, g, b = facet_rand(nb)
    col = nb.ramp(t, [(p, srgb(h)) for p, h in stops])
    col = facet_jitter(nb, col, r, g)
    col = nb.mix(1.0, col, tint, blend="MULTIPLY")
    ao = nb.n("ShaderNodeAmbientOcclusion", samples=8, only_local=True, in_Distance=7.0)
    aof = nb.math("ADD", 0.30, nb.math("MULTIPLY", nb.math("POWER", ao.outputs["AO"], 1.6), 0.70))
    alb = facet_jitter(nb, srgb(albedo)[:3], r, g)
    if vein_amt > 0:
        core, rim = vein_bands(nb, co, vein_amt)
        vt = nb.math("ADD", t, nb.math("MULTIPLY", nb.math("SUBTRACT", b, 0.5), 0.10))
        vcol = nb.ramp(vt, [(p, srgb(h)) for p, h in VEIN_STOPS])
        col = nb.mix(nb.math("MULTIPLY", nb.math("SUBTRACT", rim, core), 0.40, clamp=True), col, srgb("#100c0b"))
        vcol = nb.scale(vcol, nb.math("ADD", 0.78, nb.math("MULTIPLY", _noise(nb, co, 0.12, 3.3), 0.44)))
        col = nb.mix(core, col, vcol)
        alb = nb.mix(core, alb, srgb("#b0602e"))
    # crevices (point attribute `crev` of the massif front) sink into darkness
    cv = nb.n("ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name="crev")
    aof = nb.math("MULTIPLY", aof, nb.math("SUBTRACT", 1.0, nb.math("MULTIPLY", nb.math("POWER", cv.outputs["Fac"], 0.7), 0.72)))
    # large painted masses: some regions of the massif a little lighter and browner,
    # others darker and cooler (~250 m)
    lv = _noise(nb, co, 0.004, 6.6, 1.0)
    aof = nb.math("MULTIPLY", aof, nb.math("ADD", 0.80, nb.math("MULTIPLY", lv, 0.40)))
    col = nb.mix(nb.math("MULTIPLY", lv, 0.6), col, nb.mix(1.0, col, (1.10, 0.98, 0.88), blend="MULTIPLY"))
    # the rock right under the surface is weathered darker, so the pit walls and the top
    # band sink under the dark ground instead of standing up from it
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.link(co, sep.inputs[0])
    top = nb.math("DIVIDE", nb.math("ADD", sep.outputs["Z"], 75.0), 75.0, clamp=True)
    aof = nb.math("MULTIPLY", aof, nb.math("SUBTRACT", 1.0, nb.math("MULTIPLY", top, 0.38)))
    col = nb.scale(col, aof)
    alb = nb.scale(alb, aof)
    nb.out(alb, col)


def wall_shader(mat):
    """Walls of the workings: lighter beige-grey rock in small flat facets (the render
    skin), lit by the lamps; bolting mesh up to wall height, copper staining along the
    vein bands."""
    nb = NB(mat)
    co = _coords(nb)
    uv = nb.n("ShaderNodeUVMap", uv_map="UVMap")
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.link(uv.outputs[0], sep.inputs[0])
    u, v = sep.outputs[0], sep.outputs[1]
    t = key_t(nb)
    r, g, b = facet_rand(nb)
    alb = nb.ramp(b, [(0.0, srgb("#6e665b")), (0.5, srgb("#7e7568")), (1.0, srgb("#8f8576"))])
    alb = facet_jitter(nb, alb, r, g, amount=0.16, hue=0.05)
    # facets turned toward the key are lighter, turned away darker (painted, +-22 %)
    k = nb.math("ADD", 1.0, nb.math("MULTIPLY", nb.math("SUBTRACT", t, 0.72), 1.6))
    alb = nb.scale(alb, nb.math("MINIMUM", nb.math("MAXIMUM", k, 0.78), 1.25))
    core, rim = vein_bands(nb, co, 0.8)
    alb = nb.mix(nb.math("MULTIPLY", core, 0.75), alb, srgb("#8c4a26"))
    # bolting mesh: diamond lattice in (u, v) metres, in panels, up to 11 m
    p = 1.05
    a_ = nb.math("FRACT", nb.math("DIVIDE", nb.math("ADD", u, v), p))
    b_ = nb.math("FRACT", nb.math("DIVIDE", nb.math("SUBTRACT", u, v), p))
    la = nb.math("LESS_THAN", nb.math("ABSOLUTE", nb.math("SUBTRACT", a_, 0.5)), 0.05)
    lb = nb.math("LESS_THAN", nb.math("ABSOLUTE", nb.math("SUBTRACT", b_, 0.5)), 0.05)
    lat = nb.math("MAXIMUM", la, lb)
    band = nb.math("MULTIPLY", nb.math("GREATER_THAN", v, 0.9), nb.math("LESS_THAN", v, 11.2))
    panel = nb.math("GREATER_THAN", nb.math("FRACT", nb.math("DIVIDE", u, 23.0)), 0.18)
    mesh = nb.math("MULTIPLY", nb.math("MULTIPLY", lat, band), panel)
    alb = nb.mix(nb.math("MULTIPLY", mesh, 0.55), alb, srgb("#2a2c2e"))
    bu = nb.math("LESS_THAN", nb.math("ABSOLUTE", nb.math("SUBTRACT", nb.math("FRACT", nb.math("DIVIDE", u, 2.1)), 0.5)), 0.07)
    bv = nb.math("LESS_THAN", nb.math("ABSOLUTE", nb.math("SUBTRACT", nb.math("FRACT", nb.math("DIVIDE", v, 1.9)), 0.5)), 0.08)
    alb = nb.mix(nb.math("MULTIPLY", nb.math("MULTIPLY", bu, bv), band), alb, srgb("#8d8f8c"))
    # painted ambient: a dim version of the albedo by facet orientation (lamps do the rest)
    amb = nb.ramp(t, [(0.30, (0.10,) * 3 + (1.0,)), (0.62, (0.17,) * 3 + (1.0,)), (0.75, (0.24,) * 3 + (1.0,)),
                      (0.90, (0.32,) * 3 + (1.0,))])
    em = nb.mix(1.0, alb, amb, blend="MULTIPLY")
    ao = nb.n("ShaderNodeAmbientOcclusion", samples=8, only_local=True, in_Distance=3.0)
    aof = nb.math("ADD", 0.55, nb.math("MULTIPLY", ao.outputs["AO"], 0.45))
    nb.out(nb.scale(alb, aof), nb.scale(em, aof))


def floor_shader(mat):
    nb = NB(mat)
    co = _coords(nb)
    peb = nb.n("ShaderNodeTexVoronoi", feature="F1", in_Scale=2.2)
    nb.link(co, peb.inputs["Vector"])
    sc = nb.n("ShaderNodeSeparateColor")
    nb.link(peb.outputs["Color"], sc.inputs[0])
    col = nb.ramp(sc.outputs[0], [(0.0, srgb("#6f665a")), (0.5, srgb("#8a7f70")), (0.93, srgb("#9a8e7c")),
                                  (0.97, srgb("#4a443d"))])
    ed = nb.n("ShaderNodeTexVoronoi", feature="DISTANCE_TO_EDGE", in_Scale=2.2)
    nb.link(co, ed.inputs["Vector"])
    col = nb.mix(nb.math("MULTIPLY", nb.math("LESS_THAN", ed.outputs["Distance"], 0.05), 0.35), col, srgb("#4d463e"))
    ln = _noise(nb, co, 0.05, 0.0, 3.0)
    col = nb.scale(col, nb.math("ADD", 0.80, nb.math("MULTIPLY", ln, 0.40)))
    nb.out(col, nb.scale(col, 0.30))


def ground_shader(mat):
    """The surface: dark, quiet ground (no patches), a hint of large-scale variation."""
    nb = NB(mat)
    co = _coords(nb)
    t = key_t(nb)
    ln = _noise(nb, co, 0.004, 2.0, 1.0)
    col = nb.ramp(ln, [(0.3, srgb("#24221f")), (0.7, srgb("#2c2925"))])
    lit = nb.math("ADD", 0.86, nb.math("MULTIPLY", nb.math("SUBTRACT", t, 0.905), 2.8))
    lit = nb.math("MINIMUM", nb.math("MAXIMUM", lit, 0.72), 0.96)
    em = nb.scale(col, lit)
    nb.out(nb.scale(col, 1.4), em)


def _flat_shader(mat, hexcol, emission=None, strength=1.0):
    nb = NB(mat)
    t = key_t(nb)
    base = srgb(hexcol)
    amb = nb.ramp(t, [(0.25, (0.16,) * 3 + (1.0,)), (0.60, (0.30,) * 3 + (1.0,)), (0.92, (0.62,) * 3 + (1.0,))])
    em = nb.mix(1.0, base, amb, blend="MULTIPLY")
    if emission:
        glow = nb.scale(srgb(emission)[:3], strength)
        add = nb.n("ShaderNodeVectorMath", operation="ADD")
        nb.link(em, add.inputs[0])
        nb.link(glow, add.inputs[1])
        em = add.outputs[0]
    nb.out(base, em)


def flat_material(name, hexcol, emission=None, strength=1.0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    _flat_shader(mat, hexcol, emission, strength)
    return mat


def emissive_material(name, hexcol, strength):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = srgb(hexcol)
    em.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return mat


def rock_materials(ore_points=()):
    """Slots: floor, wall, rock (massif front), ground (surface), rockcut (cut faces)."""
    ORE_POINTS[:] = [tuple(p) for p in ore_points]
    floor = bpy.data.materials.new("floor")
    floor_shader(floor)
    wall = bpy.data.materials.new("wall")
    wall_shader(wall)
    rock = bpy.data.materials.new("rock")
    rock_shader(rock)
    ground = bpy.data.materials.new("ground")
    ground_shader(ground)
    cut = bpy.data.materials.new("rockcut")
    rock_shader(cut, tint=(1.0, 0.97, 0.94), vein_amt=0.9)
    return [floor, wall, rock, ground, cut]


def add_lamp_light(loc, direction, power=None, kind="spot", radius=0.7, color=LAMP_RGB, angle=150.0):
    _lamp_specs.append((Vector(loc), Vector(direction), power or LAMP_POWER, kind, radius, color, angle))


def world_and_lights(mine):
    sc = bpy.context.scene
    world = bpy.data.worlds.new("mine_world")
    sc.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.006, 0.008, 0.012, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    coll = bpy.data.collections.new("LIGHTS")
    sc.collection.children.link(coll)
    for i, (loc, direction, power, kind, radius, color, angle) in enumerate(_lamp_specs):
        if kind == "point":
            li = bpy.data.lights.new(f"LAMP_{i:03d}", "POINT")
        else:
            li = bpy.data.lights.new(f"LAMP_{i:03d}", "SPOT")
            li.spot_size = math.radians(angle)
            li.spot_blend = 0.85
        li.energy = power
        li.color = color
        li.shadow_soft_size = radius
        ob = bpy.data.objects.new(f"LAMP_{i:03d}", li)
        ob.location = loc
        if kind != "point":
            ob.rotation_euler = direction.normalized().to_track_quat("-Z", "Y").to_euler()
        coll.objects.link(ob)
    print("[env] lights:", len(_lamp_specs))
