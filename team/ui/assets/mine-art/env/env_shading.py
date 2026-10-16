"""Materials (procedural, rendered into the projected textures), world and lights.

The balance of the two art passes: the clean value structure of the isometric pass
(light gravel floor > mid tunnel walls > dark rock, calm palette) on the sculpted rock of
the faceted pass.

- Rock (cut faces and tops): every flat facet of the sculpted skin gets a painted value
  from its orientation to a soft key from the upper left (KEY), through a charcoal ramp
  of moderate contrast (ROCK_STOPS), +-10 % per facet; soft strata on the cut faces,
  large lighter/darker masses, local AO in creases, a few thin copper veins.
- Tunnel walls: beige-grey rock in small facets, lighter toward the key, light drips
  hanging from the visible top (UV v = metres below it), copper staining on the veins.
- Floors: light gravel (pebbles), quiet large variation; tyre tracks are a prop.
- Paint is seen by camera rays only (bounce rays see no paint, so painted surfaces never
  light each other), times AO. The warm lamps (2700 K) are real lights on top (diffuse
  only): pools on the floors, a wash up the walls.
"""

import math

import bpy
from mathutils import Vector

LAMP_RGB = (1.0, 0.62, 0.30)            # warm 2700 K (#FFC37A family)
LAMP_POWER = 6500.0                       # W, the spot lamps on the steel sets
KEY = Vector((-0.35, -0.45, 0.82)).normalized()   # toward the painted key light

ROCK_STOPS = [(0.30, "#1c1a19"), (0.50, "#211f1d"), (0.62, "#282524"), (0.72, "#302d2b"), (0.80, "#393533"),
              (0.88, "#45403d"), (0.95, "#534d48")]
VEIN_STOPS = [(0.30, "#2a1a12"), (0.55, "#43271a"), (0.70, "#653a22"), (0.82, "#8a532e"), (0.92, "#a8693b")]

_lamp_specs = []    # (location, direction, power, kind, radius, colour, angle) collected by props
ORE_POINTS = []     # Blender positions of the two zone faces: a little more vein around them


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
        m = self.n("ShaderNodeVectorMath", operation="SCALE")
        self._set(m.inputs[0], col)
        self._set(m.inputs["Scale"], f)
        return m.outputs[0]

    def noise(self, vec, scale, detail=2.0, rough=0.5, distortion=0.0, w=None):
        dims = "4D" if w is not None else "3D"
        t = self.n("ShaderNodeTexNoise", noise_dimensions=dims, in_Scale=scale, in_Detail=detail,
                   in_Roughness=rough, in_Distortion=distortion)
        if w is not None:
            t.inputs["W"].default_value = w
        try:
            t.normalize = True
        except AttributeError:
            pass
        self.link(vec, t.inputs["Vector"])
        return t.outputs["Fac"]

    def stretch(self, vec, sx, sy, sz):
        m = self.n("ShaderNodeMapping", vector_type="POINT")
        m.inputs["Scale"].default_value = (sx, sy, sz)
        self.link(vec, m.inputs["Vector"])
        return m.outputs[0]

    def ao(self, distance, strength, local=False):
        """1 in the open, (1 - strength) deep in a corner."""
        a = self.n("ShaderNodeAmbientOcclusion", samples=12, only_local=local)
        a.inputs["Distance"].default_value = distance
        return self.math("ADD", 1.0 - strength, self.math("MULTIPLY", a.outputs["AO"], strength))

    def out(self, albedo, paint):
        """Paint for camera rays only, plus a diffuse surface for the lamps."""
        lp = self.n("ShaderNodeLightPath")
        em = self.n("ShaderNodeEmission")
        em.inputs["Strength"].default_value = 1.0
        self._set(em.inputs["Color"], paint)
        bsdf = self.n("ShaderNodeBsdfDiffuse")
        bsdf.inputs["Roughness"].default_value = 1.0
        self._set(bsdf.inputs["Color"], albedo)
        hold = self.n("ShaderNodeEmission")
        hold.inputs["Strength"].default_value = 0.0
        mixp = self.n("ShaderNodeMixShader")
        self.link(lp.outputs["Is Camera Ray"], mixp.inputs[0])
        self.link(hold.outputs[0], mixp.inputs[1])
        self.link(em.outputs[0], mixp.inputs[2])
        add = self.n("ShaderNodeAddShader")
        self.link(bsdf.outputs[0], add.inputs[0])
        self.link(mixp.outputs[0], add.inputs[1])
        o = self.n("ShaderNodeOutputMaterial")
        self.link(add.outputs[0], o.inputs["Surface"])


def _co(nb):
    return nb.n("ShaderNodeTexCoord").outputs["Object"]


def _uv(nb):
    uvn = nb.n("ShaderNodeUVMap", uv_map="UVMap")
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.link(uvn.outputs[0], sep.inputs[0])
    return sep.outputs[0], sep.outputs[1]


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


def facet_jitter(nb, col, r, g, amount=0.10, hue=0.05):
    v = nb.math("ADD", 1.0 - amount, nb.math("MULTIPLY", r, 2.0 * amount))
    col = nb.scale(col, v)
    warm = nb.mix(g, (1.0 - hue, 1.0, 1.0 + hue), (1.0 + hue, 1.0, 1.0 - hue * 1.3))
    m = nb.n("ShaderNodeVectorMath", operation="MULTIPLY")
    nb.link(col, m.inputs[0])
    nb.link(warm, m.inputs[1])
    return m.outputs[0]


def _ore_mask(nb, co, radius=80.0):
    m = None
    for p in ORE_POINTS:
        vd = nb.n("ShaderNodeVectorMath", operation="DISTANCE")
        nb.link(co, vd.inputs[0])
        vd.inputs[1].default_value = tuple(p)
        f = nb.math("SUBTRACT", 1.0, nb.math("DIVIDE", vd.outputs["Value"], radius), clamp=True)
        m = f if m is None else nb.math("MAXIMUM", m, f)
    return m


def vein_bands(nb, co):
    """A few thin copper veins: warped parallel bands present on 60-200 m stretches,
    tapered at both ends, 0.3-1.3 m wide (a little wider near the two zone faces)."""
    ore = _ore_mask(nb, co) if ORE_POINTS else None
    cores, rims = [], []
    for ang, period, w0, wv, thr, wseed, tilt in ((28.0, 120.0, 0.3, 1.0, 0.60, 1.3, 0.30),
                                                  (-14.0, 190.0, 0.25, 0.8, 0.64, 4.1, -0.22)):
        a = math.radians(ang)
        n = Vector((-math.sin(a), tilt, math.cos(a))).normalized()
        dot = nb.n("ShaderNodeVectorMath", operation="DOT_PRODUCT")
        nb.link(co, dot.inputs[0])
        dot.inputs[1].default_value = tuple(n)
        warp = nb.math("MULTIPLY", nb.math("SUBTRACT", nb.noise(co, 0.0055, 0.0, w=wseed), 0.5), 85.0)
        wob = nb.math("MULTIPLY", nb.math("SUBTRACT", nb.noise(co, 0.045, 0.0, w=wseed + 3.0), 0.5), 3.0)
        s_ = nb.math("ADD", nb.math("ADD", dot.outputs["Value"], warp), wob)
        f = nb.math("FRACT", nb.math("DIVIDE", s_, period))
        d = nb.math("MULTIPLY", nb.math("ABSOLUTE", nb.math("SUBTRACT", f, 0.5)), period)
        pres = nb.noise(co, 0.010, 1.0, w=wseed + 5.0)
        if ore is not None:
            pres = nb.math("ADD", pres, nb.math("MULTIPLY", ore, 0.35))
        taper = nb.math("DIVIDE", nb.math("SUBTRACT", pres, thr), 0.07, clamp=True)
        width = nb.math("ADD", w0, nb.math("MULTIPLY", nb.noise(co, 0.025, 0.0, w=wseed + 2.0), wv))
        width = nb.math("MULTIPLY", width, taper)
        core = nb.math("LESS_THAN", d, width)
        rim = nb.math("LESS_THAN", d, nb.math("MULTIPLY", nb.math("ADD", width, 0.5), nb.math("GREATER_THAN", taper, 0.0)))
        cores.append(core)
        rims.append(rim)
    core, rim = cores[0], rims[0]
    for c, r in zip(cores[1:], rims[1:]):
        core = nb.math("MAXIMUM", core, c)
        rim = nb.math("MAXIMUM", rim, r)
    return core, rim


def rock_shader(mat, tint=1.0, strata=True, veins=True):
    """Sculpted rock: painted key value per facet through a charcoal ramp of moderate
    contrast, per-facet jitter, soft strata, large masses, AO in creases, thin veins."""
    nb = NB(mat)
    co = _co(nb)
    t = key_t(nb)
    r, g, b = facet_rand(nb)
    col = nb.ramp(t, [(p, srgb(h)) for p, h in ROCK_STOPS])
    col = facet_jitter(nb, col, r, g, amount=0.045, hue=0.025)
    f = nb.math("MULTIPLY", 1.0, tint)
    if strata:
        # soft strata: gently warped bands, a few metres thick, dipping slightly to the east
        sep = nb.n("ShaderNodeSeparateXYZ")
        nb.link(co, sep.inputs[0])
        warp = nb.math("MULTIPLY", nb.math("SUBTRACT", nb.noise(co, 0.006, 1.0, w=9.1), 0.5), 40.0)
        zz = nb.math("ADD", nb.math("ADD", sep.outputs["Z"], nb.math("MULTIPLY", sep.outputs["X"], 0.06)), warp)
        band = nb.math("SINE", nb.math("DIVIDE", zz, 4.6))
        band2 = nb.math("SINE", nb.math("DIVIDE", zz, 13.0))
        st = nb.math("ADD", nb.math("MULTIPLY", band, 0.035), nb.math("MULTIPLY", band2, 0.05))
        geo = nb.n("ShaderNodeNewGeometry")
        sepn = nb.n("ShaderNodeSeparateXYZ")
        nb.link(geo.outputs["Normal"], sepn.inputs[0])
        vert = nb.math("SUBTRACT", 1.0, nb.math("ABSOLUTE", sepn.outputs["Z"]), clamp=True)
        f = nb.math("MULTIPLY", f, nb.math("ADD", 1.0, nb.math("MULTIPLY", st, vert)))
    lv = nb.noise(co, 0.004, 1.0, w=6.6)
    f = nb.math("MULTIPLY", f, nb.math("ADD", 0.84, nb.math("MULTIPLY", lv, 0.32)))
    col = nb.mix(nb.math("MULTIPLY", lv, 0.5), col, nb.mix(1.0, col, (1.08, 0.99, 0.90), blend="MULTIPLY"))
    alb = facet_jitter(nb, srgb("#3b3836")[:3], r, g)
    if veins:
        core, rim = vein_bands(nb, co)
        vt = nb.math("ADD", t, nb.math("MULTIPLY", nb.math("SUBTRACT", b, 0.5), 0.10))
        vcol = nb.ramp(vt, [(p, srgb(h)) for p, h in VEIN_STOPS])
        col = nb.mix(nb.math("MULTIPLY", nb.math("SUBTRACT", rim, core), 0.30, clamp=True), col, srgb("#120e0c"))
        col = nb.mix(nb.math("MULTIPLY", core, 0.85), col, vcol)
        alb = nb.mix(core, alb, srgb("#a05a2c"))
    ao = nb.ao(7.0, 0.55, local=True)
    f = nb.math("MULTIPLY", f, ao)
    nb.out(nb.scale(alb, f), nb.scale(col, f))


def wall_shader(mat):
    """Tunnel walls: beige-grey rock in small facets, lighter toward the key; light drips
    hanging from the visible top (UV v = metres below it); copper staining on the veins."""
    nb = NB(mat)
    co = _co(nb)
    u, v = _uv(nb)
    t = key_t(nb)
    r, g, b = facet_rand(nb)
    base = nb.ramp(b, [(0.0, srgb("#625c54")), (0.5, srgb("#6f685f")), (1.0, srgb("#7c746a"))])
    base = facet_jitter(nb, base, r, g, amount=0.13, hue=0.04)
    k = nb.math("ADD", 1.0, nb.math("MULTIPLY", nb.math("SUBTRACT", t, 0.68), 1.3))
    base = nb.scale(base, nb.math("MINIMUM", nb.math("MAXIMUM", k, 0.74), 1.22))

    def drips(width, lmin, lspan, seed):
        q = nb.math("DIVIDE", u, width)
        cell = nb.math("FLOOR", q)
        wn = nb.n("ShaderNodeTexWhiteNoise", noise_dimensions="2D")
        comb = nb.n("ShaderNodeCombineXYZ")
        nb.link(cell, comb.inputs[0])
        comb.inputs[1].default_value = seed
        nb.link(comb.outputs[0], wn.inputs["Vector"])
        rr = wn.outputs["Value"]
        length = nb.math("ADD", lmin, nb.math("MULTIPLY", nb.math("MULTIPLY", rr, rr), lspan))
        tri = nb.math("ABSOLUTE", nb.math("MULTIPLY", nb.math("SUBTRACT", nb.math("FRACT", q), 0.5), 2.0))
        shape = nb.math("SUBTRACT", nb.math("SUBTRACT", 1.0, tri), nb.math("DIVIDE", v, length))
        return nb.math("GREATER_THAN", shape, 0.0)
    d1 = drips(3.1, 1.2, 8.0, 3.0)
    d2 = drips(1.7, 0.5, 3.5, 7.0)
    dr = nb.math("MAXIMUM", nb.math("MULTIPLY", d1, 0.85), nb.math("MULTIPLY", d2, 0.6))
    col = nb.mix(dr, base, nb.scale(base, 1.32))
    # under the drip line: a soft darker band (the rock above shades the wall top)
    top = nb.math("SUBTRACT", 1.0, nb.math("DIVIDE", v, 3.0), clamp=True)
    col = nb.scale(col, nb.math("SUBTRACT", 1.0, nb.math("MULTIPLY", top, 0.18)))
    core, rim = vein_bands(nb, co)
    col = nb.mix(nb.math("MULTIPLY", core, 0.6), col, srgb("#7c4626"))
    ao = nb.ao(4.0, 0.42, local=True)
    nb.out(nb.scale(col, nb.math("MULTIPLY", ao, 0.65)), nb.scale(col, ao))


def floor_shader(mat):
    """Light gravel: pebbles in two tones with dark gaps, quiet large-scale variation."""
    nb = NB(mat)
    co = _co(nb)
    peb = nb.n("ShaderNodeTexVoronoi", feature="F1", in_Scale=1.6)
    nb.link(co, peb.inputs["Vector"])
    sc = nb.n("ShaderNodeSeparateColor")
    nb.link(peb.outputs["Color"], sc.inputs[0])
    col = nb.ramp(sc.outputs[0], [(0.0, srgb("#857d71")), (0.5, srgb("#958c7f")), (0.92, srgb("#a29888")),
                                  (0.97, srgb("#6c645a"))])
    ed = nb.n("ShaderNodeTexVoronoi", feature="DISTANCE_TO_EDGE", in_Scale=1.6)
    nb.link(co, ed.inputs["Vector"])
    col = nb.mix(nb.math("MULTIPLY", nb.math("LESS_THAN", ed.outputs["Distance"], 0.05), 0.28), col, srgb("#5e574e"))
    ln = nb.noise(co, 0.03, 2.0)
    col = nb.scale(col, nb.math("ADD", 0.88, nb.math("MULTIPLY", ln, 0.24)))
    ao = nb.ao(5.0, 0.42)
    nb.out(nb.scale(col, 0.55), nb.scale(col, nb.math("MULTIPLY", ao, 0.92)))


def ceil_shader(mat):
    nb = NB(mat)
    ao = nb.ao(4.0, 0.4)
    nb.out(nb.scale(srgb("#4a4642")[:3], 0.5), nb.scale(srgb("#3e3a37")[:3], ao))


def rock_materials(ore_points=()):
    """Slots: floor, wall, top, cut, ceiling (env_geom.SLOT_NAMES)."""
    ORE_POINTS[:] = [tuple(p) for p in ore_points]
    floor = bpy.data.materials.new("floor")
    floor_shader(floor)
    wall = bpy.data.materials.new("wall")
    wall_shader(wall)
    top = bpy.data.materials.new("top")
    rock_shader(top, tint=0.6, strata=False)
    cut = bpy.data.materials.new("cut")
    rock_shader(cut)
    ceil = bpy.data.materials.new("ceiling")
    ceil_shader(ceil)
    return [floor, wall, top, cut, ceil]


def flat_material(name, hexcol, light=0.62, mid=0.30, dark=0.18, smooth=False):
    """Props: a flat colour in three values by facing (the painted key), no texture."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    nb = NB(mat)
    geo = nb.n("ShaderNodeNewGeometry")
    dot = nb.n("ShaderNodeVectorMath", operation="DOT_PRODUCT")
    nb.link(geo.outputs["Normal" if smooth else "True Normal"], dot.inputs[0])
    dot.inputs[1].default_value = tuple(KEY)
    t = nb.math("ADD", nb.math("MULTIPLY", dot.outputs["Value"], 0.5), 0.5)
    v = nb.ramp(t, [(0.30, (dark,) * 3 + (1.0,)), (0.62, (mid,) * 3 + (1.0,)), (0.86, (light,) * 3 + (1.0,))])
    base = srgb(hexcol)
    paint = nb.mix(1.0, base, v, blend="MULTIPLY")
    paint = nb.scale(paint, 1.0 / max(mid, 1e-3) * 0.62)
    ao = nb.ao(2.0, 0.35)
    nb.out(nb.scale(base[:3], 0.6), nb.scale(paint, ao))
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
    try:
        mat.emission_sampling = "NONE"
    except AttributeError:
        pass
    return mat


def glow_material(name, hexcol, strength):
    """A soft additive glow (light cone below a lamp), camera rays only."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    try:
        mat.emission_sampling = "NONE"
    except AttributeError:
        pass
    nt = mat.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = srgb(hexcol)
    em.inputs["Strength"].default_value = strength
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(tr.outputs[0], add.inputs[0])
    nt.links.new(em.outputs[0], add.inputs[1])
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    tr2 = nt.nodes.new("ShaderNodeBsdfTransparent")
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    nt.links.new(tr2.outputs[0], mix.inputs[1])
    nt.links.new(add.outputs[0], mix.inputs[2])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return mat


def track_material():
    """Tyre tracks on the gravel: two darker strips with a tread, partly transparent."""
    mat = bpy.data.materials.new("tyre_track")
    nb = NB(mat)
    u, v = _uv(nb)
    tread = nb.math("LESS_THAN", nb.math("FRACT", nb.math("DIVIDE", nb.math("ADD", u, nb.math("MULTIPLY", v, 0.35)), 0.55)), 0.45)
    edge = nb.math("MULTIPLY", nb.math("GREATER_THAN", v, 0.12), nb.math("LESS_THAN", v, 0.88))
    alpha = nb.math("MULTIPLY", edge, nb.math("ADD", 0.16, nb.math("MULTIPLY", tread, 0.22)))
    em = nb.n("ShaderNodeEmission")
    em.inputs["Color"].default_value = srgb("#4b443b")
    tr = nb.n("ShaderNodeBsdfTransparent")
    mix = nb.n("ShaderNodeMixShader")
    nb.link(alpha, mix.inputs[0])
    nb.link(tr.outputs[0], mix.inputs[1])
    nb.link(em.outputs[0], mix.inputs[2])
    lp = nb.n("ShaderNodeLightPath")
    tr2 = nb.n("ShaderNodeBsdfTransparent")
    mix2 = nb.n("ShaderNodeMixShader")
    nb.link(lp.outputs["Is Camera Ray"], mix2.inputs[0])
    nb.link(tr2.outputs[0], mix2.inputs[1])
    nb.link(mix.outputs[0], mix2.inputs[2])
    out = nb.n("ShaderNodeOutputMaterial")
    nb.link(mix2.outputs[0], out.inputs["Surface"])
    return mat


def add_lamp_light(loc, direction, power=None, kind="spot", radius=0.7, color=LAMP_RGB, angle=135.0):
    _lamp_specs.append((Vector(loc), Vector(direction), power or LAMP_POWER, kind, radius, color, angle))


def world_and_lights(mine):
    sc = bpy.context.scene
    world = bpy.data.worlds.new("mine_world")
    sc.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    bg.inputs["Strength"].default_value = 0.0
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
        try:
            li.use_specular = False
        except AttributeError:
            pass
        ob = bpy.data.objects.new(f"LAMP_{i:03d}", li)
        ob.location = loc
        if kind != "point":
            ob.rotation_euler = direction.normalized().to_track_quat("-Z", "Y").to_euler()
        coll.objects.link(ob)
    print("[env] lights:", len(_lamp_specs))
