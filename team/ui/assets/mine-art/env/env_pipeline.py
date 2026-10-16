"""Camera-projected textures (combined bake), outlines, GLB assembly and previews."""

import math
import os
import time

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

import mine_map
import env_export as X
import env_shading as SH
from env_export import log

TEX_SIZE = X.TEX_SIZE


# ------------------------------------------------------------ projected textures

def near_rect():
    cx, cy, side = X.NEAR_WIN
    return (cx - side / 2.0, cy - side / 2.0, side, side)


def _aux_material(kind):
    """Override materials of the outline passes: depth (R) + material kind `mk` (G), or
    the world normal."""
    name = "AUX_" + kind
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    if kind == "depth":
        cd = nt.nodes.new("ShaderNodeCameraData")
        at = nt.nodes.new("ShaderNodeAttribute")
        at.attribute_type = "GEOMETRY"
        at.attribute_name = "mk"
        comb = nt.nodes.new("ShaderNodeCombineXYZ")
        nt.links.new(cd.outputs["View Z Depth"], comb.inputs[0])
        nt.links.new(at.outputs["Fac"], comb.inputs[1])
        nt.links.new(comb.outputs[0], em.inputs["Color"])
    else:
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        nt.links.new(geo.outputs["True Normal"], em.inputs["Color"])
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return mat


def _load_pixels(path, noncolor=True):
    import numpy as np
    img = bpy.data.images.load(path, check_existing=False)
    if noncolor:
        img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    bpy.data.images.remove(img)
    return a.reshape(h, w, 4)


def render_projected(name, rect, res, cam, samples):
    """Beauty render of one screen rectangle (left, bottom, width, height) at res
    (square pixels), plus the depth/kind and normal passes for the outlines."""
    sc = bpy.context.scene
    vl = sc.view_layers[0]
    l, b, w, h = rect
    old = (cam.data.ortho_scale, cam.location.copy())
    X.set_view(cam, side=max(w, h), centre=(l + w / 2.0, b + h / 2.0))
    X.setup_cycles(samples, res)
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.color_depth = "16"
    beauty = os.path.join(X.BUILD, f"{name}_beauty.png")
    sc.render.filepath = beauty
    t = time.time()
    bpy.ops.render.render(write_still=True)
    log("projected beauty", name, res, f"{time.time() - t:.1f}s")
    bg = sc.world.node_tree.nodes["Background"].inputs["Strength"]
    world_strength = bg.default_value
    bg.default_value = 0.0
    hidden = []
    for ob in bpy.data.objects:
        if ob.name in ("TRACKS", "P_cone") and not ob.hide_render:
            ob.hide_render = True
            hidden.append(ob)
    out = {}
    for kind in ("depth", "normal"):
        X.setup_cycles(1, res, denoise=False)
        sc.cycles.pixel_filter_type = "BOX"
        sc.cycles.filter_width = 0.01
        sc.cycles.use_adaptive_sampling = False
        sc.cycles.max_bounces = 0
        vl.material_override = _aux_material(kind)
        sc.render.image_settings.file_format = "OPEN_EXR"
        sc.render.image_settings.color_depth = "32"
        sc.render.image_settings.color_mode = "RGB"
        path = os.path.join(X.BUILD, f"{name}_{kind}.exr")
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        out[kind] = path
    vl.material_override = None
    for ob in hidden:
        ob.hide_render = False
    bg.default_value = world_strength
    cam.data.ortho_scale, cam.location = old
    return beauty, out["depth"], out["normal"]


ROCKY = (3, 4)     # mk of the rock: top and cut faces (env_geom.facet_attributes: slot + 1)


def outlined(beauty, depth, normal, texel):
    """Thin selective lines painted into the texture (arrays bottom-up, sRGB, (h, w, 3)):
    - silhouettes and convex steps from the depth Laplacian, dark;
    - hard creases (> 38 deg) on props and workings, dark;
    - every facet edge of the rock (> 8 deg) and of the working walls: a dark line on the
      side that is darker under the painted key, and on convex edges a light rim on the
      side that faces the key (the lit upper edge of a facet), as in the references;
    - the plateau edge gets the same rim, so the dark ground ends in a subtle light lip."""
    import numpy as np
    back, right, up = (np.array(v, np.float32) for v in mine_map.cam_basis())
    key = np.array(tuple(SH.KEY), np.float32)
    img = _load_pixels(beauty)[..., :3]
    DD = _load_pixels(depth, noncolor=False)
    D, MK = DD[..., 0], np.rint(DD[..., 1]).astype(np.int32)
    N = _load_pixels(normal, noncolor=False)[..., :3]
    N = N / np.maximum(np.linalg.norm(N, axis=2, keepdims=True), 1e-6)
    h, w = D.shape
    # silhouettes (as before)
    t = max(0.45, 2.4 * texel)
    L = np.zeros_like(D)
    L[:, 1:-1] = np.maximum(L[:, 1:-1], D[:, 2:] + D[:, :-2] - 2.0 * D[:, 1:-1])
    L[1:-1, :] = np.maximum(L[1:-1, :], D[2:, :] + D[:-2, :] - 2.0 * D[1:-1, :])
    sil = (L > t).astype(np.float32)
    V = (N * key).sum(axis=2)                        # painted key value of the pixel's facet
    rocky = np.isin(MK, ROCKY)
    wall = MK == 2
    ground = MK == -1     # (no separate ground kind any more)
    ink = np.zeros_like(D)                           # dark line alpha
    rim = np.zeros_like(D)                           # light rim alpha
    cos_hard, cos_rock, cos_wall = math.cos(math.radians(38.0)), math.cos(math.radians(24.0)), \
        math.cos(math.radians(22.0))
    flat = N[..., 2] > 0.8
    for axis in (1, 0):
        # pairs (p, q): q is the right neighbour (axis 1) or the one above (axis 0)
        sl_p = (slice(None), slice(0, -1)) if axis == 1 else (slice(0, -1), slice(None))
        sl_q = (slice(None), slice(1, None)) if axis == 1 else (slice(1, None), slice(None))
        Np, Nq = N[sl_p], N[sl_q]
        c = (Np * Nq).sum(axis=2)
        rp, rq = rocky[sl_p], rocky[sl_q]
        wp, wq = wall[sl_p], wall[sl_q]
        gp, gq = ground[sl_p], ground[sl_q]
        fp, fq = flat[sl_p], flat[sl_q]
        same_rock = rp & rq
        same_wall = wp & wq
        hard = (c < cos_hard) & ~(fp & fq) & ~same_rock & ~same_wall
        facet = ((same_rock & (c < cos_rock)) | (same_wall & (c < cos_wall)) |
                 ((gp | gq) & (rp | rq) & (c < cos_hard)))
        # convexity: (Nq - Np) . (Pq - Pp) > 0, P in world metres from screen and depth
        step = right if axis == 1 else up
        dD = D[sl_q] - D[sl_p]
        dP = step[None, None, :] * texel - back[None, None, :] * dD[..., None]
        convex = ((Nq - Np) * dP).sum(axis=2) > 0.0
        Vp, Vq = V[sl_p], V[sl_q]
        p_lit = Vp >= Vq
        # dark line on the darker side of a convex edge, on both sides of a concave one
        # (a crease); walls only get their concave creases, faintly
        a_ink = np.where(same_wall, np.where(convex, 0.0, 0.10), np.where(convex, 0.18, 0.30))
        ink[sl_p] = np.maximum(ink[sl_p], np.where(facet & (~p_lit | ~convex), a_ink, 0.0))
        ink[sl_q] = np.maximum(ink[sl_q], np.where(facet & (p_lit | ~convex), a_ink, 0.0))
        # light rim on the lit side of convex edges
        a_rim = np.where(same_wall, 0.0, 0.24)
        rim[sl_p] = np.maximum(rim[sl_p], np.where(facet & convex & p_lit, a_rim, 0.0))
        rim[sl_q] = np.maximum(rim[sl_q], np.where(facet & convex & ~p_lit, a_rim, 0.0))
        hq = hard.astype(np.float32) * 0.38
        ink[sl_q] = np.maximum(ink[sl_q], hq)
    rim = np.where(ink > 0.0, 0.0, rim)
    mask = np.clip(sil * 0.62, 0.0, 0.62)
    soft = mask.copy()
    soft[1:, :] += 0.18 * mask[:-1, :]
    soft[:-1, :] += 0.18 * mask[1:, :]
    soft[:, 1:] += 0.18 * mask[:, :-1]
    soft[:, :-1] += 0.18 * mask[:, 1:]
    dark = np.clip(np.maximum(soft, ink), 0.0, 0.66)[..., None]
    inkc = np.array([0.055, 0.047, 0.043], np.float32)
    out = img * (1.0 - dark) + inkc * dark
    # the rim lightens toward a warm light grey, more on dark facets than on lit ones
    rimc = np.array([0.62, 0.58, 0.54], np.float32)
    r = rim[..., None]
    out = out * (1.0 - r) + np.maximum(out, rimc * (0.55 + 0.45 * out.max(axis=2, keepdims=True))) * r
    log("outline: silhouettes", int(sil.sum()), "facet ink", int((ink > 0).sum()), "rims", int((rim > 0).sum()))
    return out


def save_jpeg(arr, path, quality=88):
    """arr: (h, w, 3) sRGB, rows bottom-up (Blender order)."""
    import numpy as np
    h, w, _ = arr.shape
    srgb = np.clip(arr, 0.0, 1.0)
    lin = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    rgba = np.concatenate([lin, np.ones((h, w, 1), np.float32)], axis=2).astype(np.float32)
    img = bpy.data.images.new("save_tmp", w, h, float_buffer=True)
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw = path
    img.file_format = "JPEG"
    img.save(filepath=path, quality=quality)
    bpy.data.images.remove(img)
    log("wrote", path, os.path.getsize(path), "bytes")


def _bake(name, rect, res, cam, samples):
    beauty, depth, normal = render_projected(name, rect, res, cam, samples)
    texel = max(rect[2] / res[0], rect[3] / res[1])
    arr = outlined(beauty, depth, normal, texel)
    for f in (beauty, depth, normal):      # large intermediates
        os.remove(f)
    return arr[::-1]                        # top-down


def bake_far(cam, samples, path):
    """The far atlas: main block on top, the two rotated wings below it (env_export)."""
    import numpy as np
    S = TEX_SIZE
    atlas = np.zeros((S, S, 3), np.float32)       # top-down rows
    main = _bake("far_main", X.FAR_MAIN, (S, X.MAIN_ROWS), cam, samples)
    atlas[:X.MAIN_ROWS] = main
    wing_px = int(round(X.WING_W / (X.WING_H / S)))   # square-pixel render width
    for k, (rect, r0) in enumerate(zip(X.FAR_WINGS, X.WING_ROW0)):
        img = _bake(f"far_wing{k}", rect, (wing_px, S), cam, max(64, samples // 2))   # (S rows, wing_px cols)
        # area-resample the columns (screen x) to WING_ROWS
        src = np.linspace(0.0, wing_px, X.WING_ROWS + 1)
        cs = np.concatenate([np.zeros((S, 1, 3), np.float32), np.cumsum(img, axis=1)], axis=1)
        idx = np.arange(wing_px + 1)

        def at(xp):
            out = np.empty((S, len(xp), 3), np.float32)
            for ch in range(3):
                out[..., ch] = np.array([np.interp(xp, idx, cs[i, :, ch]) for i in range(S)])
            return out
        acc = at(src)
        small = (acc[:, 1:] - acc[:, :-1]) / (src[1:] - src[:-1])[None, :, None]   # (S, WING_ROWS, 3)
        block = small[::-1, :, :].transpose(1, 0, 2)     # rows: screen x, cols: screen y (bottom->top)
        atlas[r0:r0 + X.WING_ROWS] = block
    # gutters: repeat the neighbouring edge rows
    g0 = X.MAIN_ROWS
    atlas[g0:g0 + 2] = atlas[g0 - 1]
    atlas[g0 + 2:X.WING_ROW0[0]] = atlas[X.WING_ROW0[0]]
    g1 = X.WING_ROW0[0] + X.WING_ROWS
    atlas[g1:g1 + 2] = atlas[g1 - 1]
    atlas[g1 + 2:X.WING_ROW0[1]] = atlas[X.WING_ROW0[1]]
    save_jpeg(atlas[::-1].copy(), path, quality=88)


def bake_near(cam, samples, path):
    arr = _bake("near", near_rect(), (TEX_SIZE, TEX_SIZE), cam, samples)
    save_jpeg(arr[::-1].copy(), path, quality=88)


# --------------------------------------------------------------------- export

def export_triangles(objs, back):
    tris = []
    for ob in objs:
        me = ob.data
        me.calc_loop_triangles()
        mw = ob.matrix_world
        vs = [mw @ v.co for v in me.vertices]
        for lt in me.loop_triangles:
            a, b, c = (vs[i] for i in lt.vertices)
            n = (b - a).cross(c - a)
            if n.length < 1e-9:
                continue
            if n.normalized().dot(back) < -0.01:
                continue
            tris.append((a.copy(), b.copy(), c.copy()))
    return tris


def _regions():
    return [tuple(X.FAR_MAIN)] + [tuple(r) for r in X.FAR_WINGS] + [near_rect()]


def cull_hidden(tris, back):
    """Drop triangles outside every texture window and triangles hidden from MainView."""
    regs = _regions()
    keep = []
    for t in tris:
        ss = [mine_map.to_screen(p) for p in t]
        vis = False
        for (l, b, w, h) in regs:
            if not (all(s[0] < l - 20 for s in ss) or all(s[0] > l + w + 20 for s in ss)
                    or all(s[1] < b - 20 for s in ss) or all(s[1] > b + h + 20 for s in ss)):
                vis = True
                break
        if vis:
            keep.append(t)
    verts, polys = [], []
    for t in keep:
        i = len(verts)
        verts.extend(t)
        polys.append((i, i + 1, i + 2))
    bvh = BVHTree.FromPolygons(verts, polys, all_triangles=True, epsilon=0.0)
    out = []
    for t in keep:
        a, b_, c = t
        cen = (a + b_ + c) / 3.0
        # a barycentric grid, denser on big triangles (a long sliver along an edge may peek out
        # only in part); keep the triangle if any sample sees the camera
        size = max((b_ - a).length, (c - b_).length, (a - c).length)
        n = max(2, min(24, int(size / 6.0) + 2))
        samples = []
        for i in range(n + 1):
            for j in range(n + 1 - i):
                k = n - i - j
                p = (a * (i + 0.15) + b_ * (j + 0.15) + c * (k + 0.15)) / (n + 0.45)
                samples.append(p)
        for p in samples:
            if bvh.ray_cast(p + back * 0.05, back)[0] is None:
                out.append(t)
                break
    return out


def clip_poly(poly, right, c, keep_greater):
    """Clip a convex 3D polygon by the plane p.right = c (a vertical line of the screen)."""
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        da, db = a.dot(right) - c, b.dot(right) - c
        ina = da >= 0 if keep_greater else da <= 0
        inb = db >= 0 if keep_greater else db <= 0
        if ina:
            out.append(a)
        if ina != inb:
            t = da / (da - db)
            out.append(a.lerp(b, t))
    return out


def visibility_report(mine, tris, back, step=2.0, name="visibility.json"):
    """How much of each walking line is hidden from MainView by the exported geometry:
    a person's mid-body (2.5 m) and feet (0.3 m) sampled every `step` metres."""
    import json
    verts, polys = [], []
    for t in tris:
        i = len(verts)
        verts.extend(t)
        polys.append((i, i + 1, i + 2))
    bvh = BVHTree.FromPolygons(verts, polys, all_triangles=True, epsilon=0.0)
    rep = {}
    for wid in sorted(mine.workings):
        pts = mine.workings[wid]["pts"]
        samples, offs, acc = [], [], 0.0
        wlen = mine.workings[wid]["length_m"]
        scale_len = sum((b - a).length for a, b in zip(pts, pts[1:]))
        for a, b in zip(pts, pts[1:]):
            L = (b - a).length
            n = max(1, int(L // step))
            samples += [a.lerp(b, k / n) for k in range(n)]
            offs += [(acc + L * k / n) * wlen / scale_len for k in range(n)]
            acc += L
        samples.append(pts[-1])
        offs.append(wlen)
        ranges = []
        hidden_body = hidden_feet = 0
        run = best = 0
        for p, o in zip(samples, offs):
            hb = bvh.ray_cast(p + Vector((0, 0, 2.5)) + back * 0.05, back)[0] is not None
            hf = bvh.ray_cast(p + Vector((0, 0, 0.3)) + back * 0.05, back)[0] is not None
            hidden_body += hb
            hidden_feet += hf
            if hb:
                if ranges and o - ranges[-1][1] <= step * wlen / scale_len * 1.5:
                    ranges[-1][1] = o
                else:
                    ranges.append([o, o])
            run = run + 1 if hb else 0
            best = max(best, run)
        rep[wid] = {"samples": len(samples), "bodyHiddenPct": round(100.0 * hidden_body / len(samples), 1),
                    "feetHiddenPct": round(100.0 * hidden_feet / len(samples), 1),
                    "longestBodyHiddenM": best * step,
                    "hiddenOffsetRangesM": [[round(a, 1), round(b, 1)] for a, b in ranges]}
    with open(os.path.join(X.BUILD, name), "w") as fh:
        json.dump(rep, fh, indent=1)
    for wid, r in rep.items():
        if r["hiddenOffsetRangesM"]:
            log(name, wid, r["bodyHiddenPct"], r["hiddenOffsetRangesM"])
    return rep


def _clearance(mine, loc, yaw, footprint):
    """Plan distance (m) from an actor footprint to the nearest walking line on its level."""
    d = Vector((math.cos(math.radians(yaw)), math.sin(math.radians(yaw))))
    n = Vector((-d.y, d.x))
    hl, hw = footprint[0] / 2.0, footprint[1] / 2.0
    c = loc.xy
    rect = [c + d * hl + n * hw, c - d * hl + n * hw, c - d * hl - n * hw, c + d * hl - n * hw]
    border = []
    for i in range(4):
        a, b = rect[i], rect[(i + 1) % 4]
        k = max(2, int((b - a).length / 0.25))
        border += [a.lerp(b, j / k) for j in range(k)]
    best = 1e9
    for w in mine.workings.values():
        pts = w["pts"]
        for a, b in zip(pts, pts[1:]):
            L = (b - a).length
            k = max(2, int(L / 0.5))
            for j in range(k + 1):
                p = a.lerp(b, j / k)
                if abs(p.z - loc.z) > 8.0:
                    continue
                for q in border:
                    dd = (q - p.xy).length
                    if dd < best:
                        best = dd
    return round(best, 1)


# machines are drawn 2.2x real (SPEC section 6 actors): footprints length x width, metres
FOOT_LHD = (34.0, 11.0)
FOOT_TRUCK = (34.0, 11.0)
FOOT_DRILL = (47.0, 11.0)


def anchors(mine):
    """Decor places for the browser (machines are decoration, SPEC section 6).
    Yaw is about the up axis; the actor faces +X locally. The clearance from the walking
    lines is measured from the footprint, not assumed."""
    out = {}
    for wid, zone in (("w-07", "zone-a"), ("w-12", "zone-b")):
        face = mine.workings[wid]["pts"][-1]
        loc = Vector((face.x - 24.0, face.y + 7.0, face.z))
        out[f"ANCHOR_lhd_{zone}"] = (loc, 180.0, {
            "kind": "lhd", "zone": zone, "working": wid, "footprintM": list(FOOT_LHD), "facing": "+X local",
            "place": "face chamber west of the zone drift"})
    out["ANCHOR_truck"] = (Vector((87.0, mine.back_y + 7.5, mine.nodes["b"].z)), 180.0, {
        "kind": "truck", "working": "w-04", "footprintM": list(FOOT_TRUCK), "facing": "+X local",
        "place": "pocket behind drift w-04"})
    out["ANCHOR_drill"] = (Vector((-100.0, mine.face_y - 29.0, mine.nodes["f"].z)), 180.0, {
        "kind": "drill", "working": "w-10", "footprintM": list(FOOT_DRILL), "facing": "+X local",
        "place": "terrace in front of drift w-10"})
    for name, (loc, yaw, ex) in out.items():
        ex["clearFromWalkingLineM"] = _clearance(mine, loc, yaw, ex["footprintM"])
        log("anchor", name, "clearance", ex["clearFromWalkingLineM"], "m")
    return out


def build_glb(mine, topo, cam, slope, far_name="env_far.jpg", near_name="env_near.jpg"):
    from glb_writer import GLB, b2g, quat_from_matrix
    back, right, up = (Vector(v) for v in mine_map.cam_basis())
    objs = [o for o in bpy.data.objects if o.type == "MESH" and
            (o.name.startswith("PROXY_") or any(c.name == "PROPS_GLB" for c in o.users_collection))]
    tris = export_triangles(objs, back)
    n0 = len(tris)
    tris = cull_hidden(tris, back)
    log("export triangles", n0, "->", len(tris), "after culling")
    visibility_report(mine, tris, back)
    g = GLB()
    tex_far = g.add_texture(far_name)
    tex_near = g.add_texture(near_name)
    S = float(TEX_SIZE)
    fcx = X.FAR_MAIN[0] + X.FAR_MAIN[2] / 2.0
    nr = near_rect()

    def r3(v):
        return [round(c, 3) for c in v]
    atlas = [{"block": "main", "screenM": r3(X.FAR_MAIN), "texels": [0, 0, TEX_SIZE, X.MAIN_ROWS],
              "rotated": False}]
    for k, (rect, r0) in enumerate(zip(X.FAR_WINGS, X.WING_ROW0)):
        atlas.append({"block": ("west", "east")[k], "screenM": r3(rect), "texels": [0, r0, TEX_SIZE, X.WING_ROWS],
                      "rotated": True})

    def env_mat(name, tex, extras):
        ex = {"bake": "combined", "projection": "MainView",
              "note": "UV0 is the orthographic projection of MainView into this texture; valid for "
                      "pan and zoom, not for orbit"}
        ex.update(extras)
        return {"name": name, "pbrMetallicRoughness": {"baseColorTexture": {"index": tex},
                "metallicFactor": 0.0, "roughnessFactor": 1.0},
                "extensions": {"KHR_materials_unlit": {}}, "extras": ex}
    m_far = g.add_material(env_mat("env_far", tex_far, {"atlas": atlas}))
    m_near = g.add_material(env_mat("env_near", tex_near, {"windowScreenM": [round(nr[0], 3), round(nr[1], 3), nr[2]]}))
    m_pick = g.add_material({"name": "pick", "alphaMode": "BLEND",
                             "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 0],
                                                      "metallicFactor": 0.0, "roughnessFactor": 1.0},
                             "extensions": {"KHR_materials_unlit": {}}})

    def inside(s, rect, m=0.5):
        return rect[0] + m <= s[0] <= rect[0] + rect[2] - m and rect[1] + m <= s[1] <= rect[1] + rect[3] - m

    def uv_near(s):
        return ((s[0] - nr[0]) / nr[2], (nr[1] + nr[3] - s[1]) / nr[3])

    ml, mb, mw, mh = X.FAR_MAIN
    tm = mw / S

    def uv_main(s):
        return ((s[0] - ml) / tm / S, ((mb + mh) - s[1]) / tm / S)

    def uv_wing(k):
        wl, wb, ww, wh = X.FAR_WINGS[k]
        r0 = X.WING_ROW0[k]

        def f(s):
            row = r0 + (s[0] - wl) / ww * X.WING_ROWS
            col = (s[1] - wb) / wh * S
            return (col / S, row / S)
        return f

    prims = {m_far: ({}, [], [], []), m_near: ({}, [], [], [])}

    def emit(mi, poly, uvf):
        lut, pos, uvs, idx = prims[mi]
        keys = []
        for p in poly:
            key = (round(p.x, 3), round(p.y, 3), round(p.z, 3), mi, id(uvf) if mi == m_far else 0)
            k = lut.get(key)
            if k is None:
                k = len(pos)
                lut[key] = k
                pos.append(b2g(p))
                uvs.append(uvf(mine_map.to_screen(p)))
            keys.append(k)
        for i in range(1, len(keys) - 1):
            idx += [keys[0], keys[i], keys[i + 1]]

    split_w, split_e = fcx - X.WING_SPLIT, fcx + X.WING_SPLIT
    uv_w, uv_e = uv_wing(0), uv_wing(1)
    n_split = 0
    for t in tris:
        ss = [mine_map.to_screen(p) for p in t]
        if all(inside(s, nr) for s in ss):
            emit(m_near, list(t), uv_near)
            continue
        xs = [s[0] for s in ss]
        if min(xs) >= split_w and max(xs) <= split_e:
            emit(m_far, list(t), uv_main)
            continue
        n_split += 1
        poly = list(t)
        west = clip_poly(poly, right, split_w, keep_greater=False)
        rest = clip_poly(poly, right, split_w, keep_greater=True)
        mid = clip_poly(rest, right, split_e, keep_greater=False) if len(rest) >= 3 else []
        east = clip_poly(rest, right, split_e, keep_greater=True) if len(rest) >= 3 else []
        for piece, f in ((west, uv_w), (mid, uv_main), (east, uv_e)):
            if len(piece) >= 3:
                emit(m_far, piece, f)
    log("triangles split at the wing borders:", n_split)
    plist, stats = [], {}
    for mi, (lut, pos, uvs, idx) in prims.items():
        if idx:
            plist.append({"positions": pos, "uvs": uvs, "indices": idx, "material": mi})
            stats["near" if mi == m_near else "far"] = (len(pos), len(idx) // 3)
    env_mesh = g.add_mesh("ENV", plist)
    g.add_node({"name": "ENV", "mesh": env_mesh, "extras": {"role": "static_environment"}})
    log("env primitives (verts, tris)", stats)
    import env_geom
    for wid in sorted(mine.workings):
        w = mine.workings[wid]
        pos, idx = [], []
        for si, (a, b) in enumerate(zip(w["pts"], w["pts"][1:])):
            d = Vector((b.x - a.x, b.y - a.y, 0.0))
            if d.length < 1e-6:
                continue
            nrm = Vector((-d.y, d.x, 0.0)).normalized()
            if abs(a.y - mine.face_y) < 0.01 and abs(b.y - mine.face_y) < 0.01:
                # the drawn gallery floor: from its front edge to the back wall
                seg = next(s_ for s_ in mine.segments if s_["wid"] == wid and s_["idx"] == si)
                fmax = 0.0
                for k in range(21):
                    x = a.x + (b.x - a.x) * k / 20.0
                    fmax = max(fmax, env_geom.Stack(mine, slope, x).of(seg)[1]["Feff"])
                lo_y, hi_y = mine.face_y - fmax - 1.0, mine.back_y
                offs = sorted(((lo_y - a.y) / nrm.y, (hi_y - a.y) / nrm.y))
            elif wid == "w-05":
                # the a-d slot: open floor toward the island (south-east), back wall north-west
                offs = (-(env_geom.CC_FRONT + env_geom.CC_OPEN), env_geom.B_BACK)
            else:
                offs = (-7.5, 7.5)
            base = len(pos)
            for p in (a, b):
                for o in offs:
                    for dz in (-1.0, 7.0):
                        pos.append(b2g(p + nrm * o + Vector((0, 0, dz))))
            quads = [(0, 4, 5, 1), (2, 3, 7, 6), (1, 5, 7, 3), (0, 2, 6, 4), (0, 1, 3, 2), (4, 6, 7, 5)]
            for q in quads:
                idx += [base + q[0], base + q[1], base + q[2], base + q[0], base + q[2], base + q[3]]
        mesh = g.add_mesh("PICK_" + wid, [{"positions": pos, "uvs": None, "indices": idx, "material": m_pick}])
        g.add_node({"name": "PICK_" + wid, "mesh": mesh,
                    "extras": {"thingId": f"team040.mine:{wid}", "pick": True, "working": wid}})
    for name, (loc, yaw, extras) in anchors(mine).items():
        h = math.radians(yaw) / 2.0
        g.add_node({"name": name, "translation": list(b2g(loc)), "rotation": [0.0, math.sin(h), 0.0, math.cos(h)],
                    "extras": extras})
    fcx_, fcy_ = cam["frame_centre"]
    loc = right * fcx_ + up * fcy_ + back * 2500.0
    r_g, u_g, b_g = (Vector(b2g(v)) for v in (right, up, back))
    rot = [[r_g.x, u_g.x, b_g.x], [r_g.y, u_g.y, b_g.y], [r_g.z, u_g.z, b_g.z]]
    ci = g.add_camera({"name": "MainView", "type": "orthographic",
                       "orthographic": {"xmag": X.FRAME_W / 2.0, "ymag": X.FRAME_W / 2.0 / X.ASPECT,
                                        "znear": 10.0, "zfar": 6000.0}})
    g.add_node({"name": "MainView", "camera": ci, "translation": list(b2g(loc)),
                "rotation": quat_from_matrix(rot),
                "extras": {"azimuthDeg": mine_map.CAM_AZ_DEG, "elevationDeg": mine_map.CAM_EL_DEG,
                           "aspect": "16:9", "zoomRange": [1, 4], "interaction": "pan and zoom only",
                           "stageAspects": "4:3 to 21:9 at 1x: the art covers the MainView rectangle "
                                           "widened to 21:9 or heightened to 4:3"}})
    g.j["scenes"][0]["extras"] = {
        "mineArt": 1, "k": mine_map.K, "cx": topo["cx"], "cy": topo["cy"], "zTop": mine_map.ZTOP,
        "topology": topo["topology"], "workings": sorted(mine.workings), "camera": "MainView"}
    os.makedirs(X.OUT_DIR, exist_ok=True)
    path = os.path.join(X.OUT_DIR, "env.glb")
    size = g.write(path)
    log("wrote", path, size, "bytes")
    return path


# ------------------------------------------------------------------- pipeline

def zone_focus(mine, wid):
    w = mine.workings[wid]
    return w["pts"][0].lerp(w["pts"][-1], 0.6)


def previews(mine, cam, samples):
    X.render_view(os.path.join(X.PREVIEWS, "overview.png"), cam, 1.0, None, samples)
    X.render_view(os.path.join(X.PREVIEWS, "zone_a_3x.png"), cam, 3.0, zone_focus(mine, "w-07"), samples)
    X.render_view(os.path.join(X.PREVIEWS, "zone_b_3x.png"), cam, 3.0, zone_focus(mine, "w-12"), samples)


def full_pipeline(mine, topo, cam, slope, samples, do_textures=True, do_previews=True):
    os.makedirs(X.OUT_DIR, exist_ok=True)
    if do_textures:
        bake_far(cam, samples, os.path.join(X.OUT_DIR, "env_far.jpg"))
        bake_near(cam, samples, os.path.join(X.OUT_DIR, "env_near.jpg"))
    build_glb(mine, topo, cam, slope)
    if do_previews:
        previews(mine, cam, max(128, samples // 3))
