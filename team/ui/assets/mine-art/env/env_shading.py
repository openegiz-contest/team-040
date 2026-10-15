"""Materials (procedural, rendered into the projected textures), world and lights."""

import math

import bpy
from mathutils import Vector

LAMP_RGB = (1.0, 0.546, 0.195)          # #FFC37A in linear
LAMP_POWER = 11000.0                      # W, spot lights of drift lamps
FILL_RGB = (0.62, 0.72, 0.95)
FILL_STRENGTH = 4.0

_lamp_specs = []    # (location, direction, power, kind) collected by props


def srgb(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c) + (1.0,)


class NB:
    """Tiny node-tree builder."""

    def __init__(self, mat):
        mat.use_nodes = True
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

    def math(self, op, a, b=None, clamp=False):
        m = self.n("ShaderNodeMath", operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = v
            else:
                self.link(v, m.inputs[i])
        return m.outputs[0]

    def mix(self, fac, a, b, blend="MIX"):
        m = self.n("ShaderNodeMix", data_type="RGBA", blend_type=blend)
        for sock, v in ((m.inputs[0], fac), (m.inputs[6], a), (m.inputs[7], b)):
            if isinstance(v, (int, float)):
                sock.default_value = v
            elif isinstance(v, tuple):
                sock.default_value = tuple(v) + (1.0,) * (4 - len(v))
            else:
                self.link(v, sock)
        return m.outputs[2]

    def ramp(self, fac, stops):
        r = self.n("ShaderNodeValToRGB")
        cr = r.color_ramp
        while len(cr.elements) < len(stops):
            cr.elements.new(0.5)
        for el, (pos, col) in zip(cr.elements, stops):
            el.position = pos
            el.color = col
        self.link(fac, r.inputs[0])
        return r.outputs[0]

    def out_diffuse(self, color, emission=None, strength=1.0, normal=None):
        bsdf = self.n("ShaderNodeBsdfDiffuse")
        bsdf.inputs["Roughness"].default_value = 1.0
        self.link(color, bsdf.inputs["Color"])
        if normal is not None:
            self.link(normal, bsdf.inputs["Normal"])
        shader = bsdf.outputs[0]
        if emission is not None:
            em = self.n("ShaderNodeEmission")
            em.inputs["Strength"].default_value = strength
            self.link(emission, em.inputs["Color"])
            add = self.n("ShaderNodeAddShader")
            self.link(shader, add.inputs[0])
            self.link(em.outputs[0], add.inputs[1])
            shader = add.outputs[0]
        out = self.n("ShaderNodeOutputMaterial")
        self.link(shader, out.inputs["Surface"])


def _coords(nb, kind="Object"):
    tc = nb.n("ShaderNodeTexCoord")
    return tc.outputs[kind]


def facet_normal(nb, co, scale, strength, scale2=None, strength2=0.0):
    """Normal tilted per Voronoi cell: flat crystalline facets that catch the light."""
    geo = nb.n("ShaderNodeNewGeometry")
    vor = nb.n("ShaderNodeTexVoronoi", feature="F1", in_Scale=scale, in_Randomness=1.0)
    nb.link(co, vor.inputs["Vector"])
    off = nb.n("ShaderNodeVectorMath", operation="MULTIPLY_ADD")
    nb.link(vor.outputs["Color"], off.inputs[0])
    off.inputs[1].default_value = (2 * strength, 2 * strength, 2 * strength)
    off.inputs[2].default_value = (-strength, -strength, -strength)
    add = nb.n("ShaderNodeVectorMath", operation="ADD")
    nb.link(geo.outputs["Normal"], add.inputs[0])
    nb.link(off.outputs[0], add.inputs[1])
    last = add.outputs[0]
    if scale2:
        vor2 = nb.n("ShaderNodeTexVoronoi", feature="F1", in_Scale=scale2, in_Randomness=1.0)
        nb.link(co, vor2.inputs["Vector"])
        off2 = nb.n("ShaderNodeVectorMath", operation="MULTIPLY_ADD")
        nb.link(vor2.outputs["Color"], off2.inputs[0])
        off2.inputs[1].default_value = (2 * strength2,) * 3
        off2.inputs[2].default_value = (-strength2,) * 3
        add2 = nb.n("ShaderNodeVectorMath", operation="ADD")
        nb.link(last, add2.inputs[0])
        nb.link(off2.outputs[0], add2.inputs[1])
        last = add2.outputs[0]
    nrm = nb.n("ShaderNodeVectorMath", operation="NORMALIZE")
    nb.link(last, nrm.inputs[0])
    return nrm.outputs[0], vor


ORE_POINTS = []      # Blender positions of the two zone faces: ore-rich rock around them


def _ore_mask(nb, co, radius=75.0):
    m = None
    for p in ORE_POINTS:
        vd = nb.n("ShaderNodeVectorMath", operation="DISTANCE")
        nb.link(co, vd.inputs[0])
        vd.inputs[1].default_value = tuple(p)
        f = nb.math("SUBTRACT", 1.0, nb.math("DIVIDE", vd.outputs["Value"], radius), clamp=True)
        m = f if m is None else nb.math("MAXIMUM", m, f)
    return m


def rock_shader(mat, base_lo, base_hi, vein=True, facet=0.6, tint=(1, 1, 1, 1), vein_amt=1.0):
    nb = NB(mat)
    co = _coords(nb)
    normal, vor = facet_normal(nb, co, 0.085, facet, 0.24, facet * 0.35)
    cell = nb.n("ShaderNodeSeparateColor")
    nb.link(vor.outputs["Color"], cell.inputs[0])
    fine = nb.n("ShaderNodeTexVoronoi", feature="F1", in_Scale=0.34)
    nb.link(co, fine.inputs["Vector"])
    fc = nb.n("ShaderNodeSeparateColor")
    nb.link(fine.outputs["Color"], fc.inputs[0])
    tone = nb.math("ADD", nb.math("MULTIPLY", cell.outputs[0], 0.8), nb.math("MULTIPLY", fc.outputs[1], 0.2))
    col = nb.ramp(tone, [(0.0, base_lo), (1.0, base_hi)])
    ore = _ore_mask(nb, co) if ORE_POINTS else None
    if vein:
        # copper veins: isolines of two smooth noises, only inside vein-rich zones,
        # broken into chips
        vmask = None
        for sc_, off_ in ((0.0065, 0.0), (0.0048, 3.7)):
            nz = nb.n("ShaderNodeTexNoise", noise_dimensions="4D", in_Scale=sc_, in_Detail=1.5,
                      in_Roughness=0.4, in_W=off_)
            nb.link(co, nz.inputs["Vector"])
            thr = 0.012 * vein_amt
            if ore is not None:
                thr = nb.math("MULTIPLY", nb.math("ADD", 1.0, nb.math("MULTIPLY", ore, 2.6)), thr)
            iso = nb.math("LESS_THAN", nb.math("ABSOLUTE", nb.math("SUBTRACT", nz.outputs["Fac"], 0.5)), thr)
            vmask = iso if vmask is None else nb.math("MAXIMUM", vmask, iso)
        zone = nb.n("ShaderNodeTexNoise", in_Scale=0.0035, in_Detail=1.0)
        nb.link(co, zone.inputs["Vector"])
        zm = nb.math("GREATER_THAN", zone.outputs["Fac"], 0.55)
        if ore is not None:
            zm = nb.math("MAXIMUM", zm, nb.math("GREATER_THAN", ore, 0.05))
        vmask = nb.math("MULTIPLY", vmask, zm)
        vmask = nb.math("MULTIPLY", vmask, nb.math("GREATER_THAN", fc.outputs[2], 0.45))
        vcol = nb.ramp(fc.outputs[0], [(0.0, srgb("#5e2e16")), (0.5, srgb("#94501f")), (1.0, srgb("#c8783a"))])
        col = nb.mix(vmask, col, vcol)
    ln = nb.n("ShaderNodeTexNoise", in_Scale=0.006, in_Detail=1.0)
    nb.link(co, ln.inputs["Vector"])
    f = nb.math("ADD", 0.80, nb.math("MULTIPLY", ln.outputs["Fac"], 0.40))
    col = _mul_scalar(nb, col, f)
    col = nb.mix(1.0, col, tint, blend="MULTIPLY")
    nb.out_diffuse(col, normal=normal)


def _mul_scalar(nb, col, f):
    cm = nb.n("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
    cm.inputs[0].default_value = 1.0
    nb.link(col, cm.inputs[6])
    comb = nb.n("ShaderNodeCombineColor")
    for i in range(3):
        nb.link(f, comb.inputs[i])
    nb.link(comb.outputs[0], cm.inputs[7])
    return cm.outputs[2]


def wall_shader(mat):
    """Back walls of workings: lighter faceted rock with bolting mesh up to wall height."""
    nb = NB(mat)
    co = _coords(nb)
    uv = nb.n("ShaderNodeUVMap", uv_map="UVMap")
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.link(uv.outputs[0], sep.inputs[0])
    u, v = sep.outputs[0], sep.outputs[1]
    chips = nb.n("ShaderNodeTexVoronoi", feature="F1", in_Scale=0.42)
    nb.link(co, chips.inputs["Vector"])
    edges = nb.n("ShaderNodeTexVoronoi", feature="DISTANCE_TO_EDGE", in_Scale=0.42)
    nb.link(co, edges.inputs["Vector"])
    sc = nb.n("ShaderNodeSeparateColor")
    nb.link(chips.outputs["Color"], sc.inputs[0])
    col = nb.ramp(sc.outputs[0], [(0.0, srgb("#5a564e")), (0.5, srgb("#716b61")), (1.0, srgb("#877f72"))])
    crack = nb.math("GREATER_THAN", edges.outputs["Distance"], 0.03)
    col = nb.mix(nb.math("MULTIPLY", nb.math("SUBTRACT", 1.0, crack), 0.3), col, srgb("#26241f"))
    # copper staining on a few chips
    stain = nb.math("GREATER_THAN", sc.outputs[2], 0.965)
    col = nb.mix(nb.math("MULTIPLY", stain, 0.4), col, srgb("#7a4528"))
    # bolting mesh: diamond lattice in (u, v) metres
    p = 1.05
    a = nb.math("FRACT", nb.math("DIVIDE", nb.math("ADD", u, v), p))
    b = nb.math("FRACT", nb.math("DIVIDE", nb.math("SUBTRACT", u, v), p))
    la = nb.math("LESS_THAN", nb.math("ABSOLUTE", nb.math("SUBTRACT", a, 0.5)), 0.05)
    lb = nb.math("LESS_THAN", nb.math("ABSOLUTE", nb.math("SUBTRACT", b, 0.5)), 0.05)
    lat = nb.math("MAXIMUM", la, lb)
    band = nb.math("MULTIPLY", nb.math("GREATER_THAN", v, 0.9), nb.math("LESS_THAN", v, 11.2))
    panel = nb.math("GREATER_THAN", nb.math("FRACT", nb.math("DIVIDE", u, 23.0)), 0.18)
    mesh = nb.math("MULTIPLY", nb.math("MULTIPLY", lat, band), panel)
    col = nb.mix(nb.math("MULTIPLY", mesh, 0.8), col, srgb("#2a2c2e"))
    # bolt plates
    bu = nb.math("LESS_THAN", nb.math("ABSOLUTE", nb.math("SUBTRACT", nb.math("FRACT", nb.math("DIVIDE", u, 2.1)), 0.5)), 0.07)
    bv = nb.math("LESS_THAN", nb.math("ABSOLUTE", nb.math("SUBTRACT", nb.math("FRACT", nb.math("DIVIDE", v, 1.9)), 0.5)), 0.08)
    bolt = nb.math("MULTIPLY", nb.math("MULTIPLY", bu, bv), band)
    col = nb.mix(bolt, col, srgb("#8d8f8c"))
    # above the mesh band: the tall gallery wall, light grey-beige faceted rock
    upper = nb.ramp(sc.outputs[1], [(0.0, srgb("#6a6257")), (0.5, srgb("#857b6d")), (1.0, srgb("#9c9180"))])
    upper = nb.mix(nb.math("MULTIPLY", nb.math("SUBTRACT", 1.0, crack), 0.28), upper, srgb("#3a352f"))
    upper = nb.mix(nb.math("MULTIPLY", stain, 0.35), upper, srgb("#8a4a26"))
    above = nb.math("GREATER_THAN", v, 11.6)
    col = nb.mix(above, col, upper)
    nb.out_diffuse(col, normal=facet_normal(nb, co, 0.3, 0.32)[0])


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
    ln = nb.n("ShaderNodeTexNoise", in_Scale=0.05, in_Detail=3.0)
    nb.link(co, ln.inputs["Vector"])
    f = nb.math("ADD", 0.80, nb.math("MULTIPLY", ln.outputs["Fac"], 0.40))
    col = _mul_scalar(nb, col, f)
    nb.out_diffuse(col)


def ground_shader(mat):
    nb = NB(mat)
    co = _coords(nb)
    peb = nb.n("ShaderNodeTexVoronoi", feature="F1", in_Scale=0.9)
    nb.link(co, peb.inputs["Vector"])
    sc = nb.n("ShaderNodeSeparateColor")
    nb.link(peb.outputs["Color"], sc.inputs[0])
    col = nb.ramp(sc.outputs[0], [(0.0, srgb("#24221f")), (0.6, srgb("#2c2925")), (1.0, srgb("#36322c"))])
    ln = nb.n("ShaderNodeTexNoise", in_Scale=0.02, in_Detail=4.0)
    nb.link(co, ln.inputs["Vector"])
    patch = nb.math("GREATER_THAN", ln.outputs["Fac"], 0.58)
    col = nb.mix(nb.math("MULTIPLY", patch, 0.5), col, srgb("#2e2b27"))
    f = nb.math("ADD", 0.82, nb.math("MULTIPLY", ln.outputs["Fac"], 0.36))
    col = _mul_scalar(nb, col, f)
    nb.out_diffuse(col)


def flat_material(name, hexcol, emission=None, strength=1.0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    nb = NB(mat)
    rgb = nb.n("ShaderNodeRGB")
    rgb.outputs[0].default_value = srgb(hexcol)
    if emission:
        em = nb.n("ShaderNodeRGB")
        em.outputs[0].default_value = srgb(emission)
        nb.out_diffuse(rgb.outputs[0], em.outputs[0], strength)
    else:
        nb.out_diffuse(rgb.outputs[0])
    return mat


def emissive_material(name, hexcol, strength):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    nb = NB(mat)
    em = nb.n("ShaderNodeEmission")
    em.inputs["Color"].default_value = srgb(hexcol)
    em.inputs["Strength"].default_value = strength
    out = nb.n("ShaderNodeOutputMaterial")
    nb.link(em.outputs[0], out.inputs["Surface"])
    return mat


def rock_materials(ore_points=()):
    """Slots: floor, wall, rock (massif front), ground (surface), rockcut (cut faces)."""
    ORE_POINTS[:] = [tuple(p) for p in ore_points]
    floor = bpy.data.materials.new("floor")
    floor_shader(floor)
    wall = bpy.data.materials.new("wall")
    wall_shader(wall)
    rock = bpy.data.materials.new("rock")
    rock_shader(rock, srgb("#252326"), srgb("#5e585d"))
    ground = bpy.data.materials.new("ground")
    ground_shader(ground)
    cut = bpy.data.materials.new("rockcut")
    rock_shader(cut, srgb("#262427"), srgb("#635c62"), tint=(1.0, 0.97, 0.94, 1.0), vein_amt=0.9)
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
    # cool fill: a soft sun from the upper left, in front
    sun = bpy.data.lights.new("FILL_SUN", "SUN")
    sun.energy = FILL_STRENGTH
    sun.color = FILL_RGB
    sun.angle = math.radians(12.0)
    ob = bpy.data.objects.new("FILL_SUN", sun)
    d = Vector((0.62, 0.40, -0.68)).normalized()      # light travel direction
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    coll.objects.link(ob)
    # second, weaker fill from the right to keep the east faces readable
    sun2 = bpy.data.lights.new("FILL_SUN2", "SUN")
    sun2.energy = FILL_STRENGTH * 0.3
    sun2.color = (0.70, 0.74, 0.86)
    sun2.angle = math.radians(20.0)
    ob2 = bpy.data.objects.new("FILL_SUN2", sun2)
    d2 = Vector((-0.62, 0.48, -0.62)).normalized()
    ob2.rotation_euler = d2.to_track_quat("-Z", "Y").to_euler()
    coll.objects.link(ob2)
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
