"""Camera-projected textures (combined bake), outlines, GLB assembly and previews."""

import math
import os
import time

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

import mine_map
import env_export as X
from env_export import log

TEX_SIZE = X.TEX_SIZE


# ------------------------------------------------------------ projected textures

def win_rect(win):
    cx, cy, side = win
    return cx - side / 2.0, cy - side / 2.0, side


def _aux_material(kind):
    name = "AUX_" + kind
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    if kind == "depth":
        cd = nt.nodes.new("ShaderNodeCameraData")
        comb = nt.nodes.new("ShaderNodeCombineXYZ")
        for i in range(3):
            nt.links.new(cd.outputs["View Z Depth"], comb.inputs[i])
        nt.links.new(comb.outputs[0], em.inputs["Color"])
    else:
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        nt.links.new(geo.outputs["Normal"], em.inputs["Color"])
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


def render_projected(name, win, cam, samples):
    """Beauty render of one projection window plus depth and normal passes."""
    sc = bpy.context.scene
    vl = sc.view_layers[0]
    l, b, side = win_rect(win)
    old = (cam.data.ortho_scale, cam.location.copy())
    X.set_view(cam, side=side, centre=(win[0], win[1]))
    res = (TEX_SIZE, TEX_SIZE)
    X.setup_cycles(samples, res)
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.color_depth = "16"
    beauty = os.path.join(X.BUILD, f"{name}_beauty.png")
    sc.render.filepath = beauty
    t = time.time()
    bpy.ops.render.render(write_still=True)
    log("projected beauty", name, f"{time.time() - t:.1f}s")
    bg = sc.world.node_tree.nodes["Background"].inputs["Strength"]
    world_strength = bg.default_value
    bg.default_value = 0.0
    hidden = []
    for ob in bpy.data.objects:
        if ob.name == "TRACKS" and not ob.hide_render:
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


def outlined(beauty, depth, normal, texel):
    """Thin selective dark lines baked into the texture: silhouettes and convex edges
    from the depth Laplacian, hard creases from the normals. Returns sRGB (h, w, 3)."""
    import numpy as np
    img = _load_pixels(beauty)[..., :3]
    D = _load_pixels(depth, noncolor=False)[..., 0]
    N = _load_pixels(normal, noncolor=False)[..., :3]
    t = max(0.45, 2.4 * texel)
    L = np.zeros_like(D)
    Lx = D[:, 2:] + D[:, :-2] - 2.0 * D[:, 1:-1]
    Ly = D[2:, :] + D[:-2, :] - 2.0 * D[1:-1, :]
    L[:, 1:-1] = np.maximum(L[:, 1:-1], Lx)
    L[1:-1, :] = np.maximum(L[1:-1, :], Ly)
    sil = (L > t).astype(np.float32)
    Nn = N / np.maximum(np.linalg.norm(N, axis=2, keepdims=True), 1e-6)
    cr = np.zeros_like(D)
    dx = (Nn[:, 1:] * Nn[:, :-1]).sum(axis=2)
    dy = (Nn[1:, :] * Nn[:-1, :]).sum(axis=2)
    cos_t = math.cos(math.radians(38.0))
    flat = Nn[..., 2] > 0.8            # ground and floors: no crease lines inside them
    fx = flat[:, 1:] & flat[:, :-1]
    fy = flat[1:, :] & flat[:-1, :]
    cr[:, 1:] = np.maximum(cr[:, 1:], ((dx < cos_t) & ~fx).astype(np.float32))
    cr[1:, :] = np.maximum(cr[1:, :], ((dy < cos_t) & ~fy).astype(np.float32))
    mask = np.clip(sil * 0.62 + cr * 0.38, 0.0, 0.62)
    soft = mask.copy()
    soft[1:, :] += 0.18 * mask[:-1, :]
    soft[:-1, :] += 0.18 * mask[1:, :]
    soft[:, 1:] += 0.18 * mask[:, :-1]
    soft[:, :-1] += 0.18 * mask[:, 1:]
    soft = np.clip(soft, 0.0, 0.66)[..., None]
    ink = np.array([0.055, 0.047, 0.043], np.float32)
    log("outline: silhouettes", int(sil.sum()), "creases", int(cr.sum()))
    return img * (1.0 - soft) + ink * soft


def save_jpeg(arr, path, quality=88):
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


def cull_hidden(tris, back, far_rect):
    """Drop triangles outside the far window and triangles hidden from MainView."""
    l, b, side = far_rect
    keep = []
    for t in tris:
        ss = [mine_map.to_screen(p) for p in t]
        if all(s[0] < l - 20 for s in ss) or all(s[0] > l + side + 20 for s in ss) \
                or all(s[1] < b - 20 for s in ss) or all(s[1] > b + side + 20 for s in ss):
            continue
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
        samples = [cen, a.lerp(cen, 0.12), b_.lerp(cen, 0.12), c.lerp(cen, 0.12),
                   ((a + b_) / 2).lerp(cen, 0.1), ((b_ + c) / 2).lerp(cen, 0.1), ((c + a) / 2).lerp(cen, 0.1)]
        for p in samples:
            if bvh.ray_cast(p + back * 0.05, back)[0] is None:
                out.append(t)
                break
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


def anchors(mine):
    """Decor places for the browser (machines are decoration, SPEC section 6).
    Yaw is about the up axis; the actor faces +X locally."""
    out = {}
    for wid, zone in (("w-07", "zone-a"), ("w-12", "zone-b")):
        face = mine.workings[wid]["pts"][-1]
        loc = Vector((face.x - 16.0, face.y + 14.0, face.z))
        out[f"ANCHOR_lhd_{zone}"] = (loc, -90.0, {
            "kind": "lhd", "zone": zone, "working": wid, "footprintM": [16.5, 4.5],
            "facing": "+X local", "clearFromWalkingLineM": 13.7})
    H = mine.nodes["b"].z
    out["ANCHOR_truck"] = (Vector((87.0, mine.back_y + 7.0, H)), 180.0, {
        "kind": "truck", "working": "w-04", "footprintM": [18.0, 5.2], "facing": "+X local",
        "place": "bay behind drift w-04", "clearFromWalkingLineM": 14.4})
    He = mine.nodes["f"].z
    out["ANCHOR_drill"] = (Vector((-76.0, mine.back_y + 6.5, He)), 180.0, {
        "kind": "drill", "working": "w-10", "footprintM": [18.0, 3.75], "facing": "+X local",
        "place": "bay behind drift w-10", "clearFromWalkingLineM": 14.6})
    return out


def build_glb(mine, topo, cam, far_name="env_far.jpg", near_name="env_near.jpg"):
    from glb_writer import GLB, b2g, quat_from_matrix
    back, right, up = (Vector(v) for v in mine_map.cam_basis())
    objs = [o for o in bpy.data.objects if o.type == "MESH" and
            (o.name.startswith("PROXY_") or any(c.name == "PROPS_GLB" for c in o.users_collection))]
    tris = export_triangles(objs, back)
    n0 = len(tris)
    far_rect, near_rect = win_rect(X.FAR_WIN), win_rect(X.NEAR_WIN)
    tris = cull_hidden(tris, back, far_rect)
    log("export triangles", n0, "->", len(tris), "after culling")
    visibility_report(mine, tris, back)
    render_rock = [o for o in bpy.data.objects if o.name in ("MASSIF", "PILLAR", "SPUR_w-07", "SPUR_w-12")]
    visibility_report(mine, export_triangles(render_rock, back), back, name="visibility_render.json")
    g = GLB()
    tex_far = g.add_texture(far_name)
    tex_near = g.add_texture(near_name)

    def env_mat(name, tex, rect):
        return {"name": name, "pbrMetallicRoughness": {"baseColorTexture": {"index": tex},
                "metallicFactor": 0.0, "roughnessFactor": 1.0},
                "extensions": {"KHR_materials_unlit": {}},
                "extras": {"bake": "combined", "projection": "MainView",
                           "windowScreenM": [round(rect[0], 3), round(rect[1], 3), rect[2]],
                           "note": "UV0 is the orthographic projection of MainView into this "
                                   "window; valid for pan and zoom, not for orbit"}}
    m_far = g.add_material(env_mat("env_far", tex_far, far_rect))
    m_near = g.add_material(env_mat("env_near", tex_near, near_rect))
    m_pick = g.add_material({"name": "pick", "alphaMode": "BLEND",
                             "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 0],
                                                      "metallicFactor": 0.0, "roughnessFactor": 1.0},
                             "extensions": {"KHR_materials_unlit": {}}})

    def inside(s, rect, m=0.5):
        return rect[0] + m <= s[0] <= rect[0] + rect[2] - m and rect[1] + m <= s[1] <= rect[1] + rect[2] - m

    prims = {m_far: ({}, [], [], []), m_near: ({}, [], [], [])}
    for t in tris:
        ss = [mine_map.to_screen(p) for p in t]
        if all(inside(s, near_rect) for s in ss):
            mi, rect = m_near, near_rect
        else:
            mi, rect = m_far, far_rect
        lut, pos, uvs, idx = prims[mi]
        for p, s in zip(t, ss):
            key = (round(p.x, 3), round(p.y, 3), round(p.z, 3))
            k = lut.get(key)
            if k is None:
                k = len(pos)
                lut[key] = k
                pos.append(b2g(p))
                uvs.append(((s[0] - rect[0]) / rect[2], (rect[1] + rect[2] - s[1]) / rect[2]))
            idx.append(k)
    plist, stats = [], {}
    for mi, (lut, pos, uvs, idx) in prims.items():
        if idx:
            plist.append({"positions": pos, "uvs": uvs, "indices": idx, "material": mi})
            stats["near" if mi == m_near else "far"] = (len(pos), len(idx) // 3)
    env_mesh = g.add_mesh("ENV", plist)
    g.add_node({"name": "ENV", "mesh": env_mesh, "extras": {"role": "static_environment"}})
    log("env primitives (verts, tris)", stats)
    for wid in sorted(mine.workings):
        w = mine.workings[wid]
        pos, idx = [], []
        for a, b in zip(w["pts"], w["pts"][1:]):
            d = Vector((b.x - a.x, b.y - a.y, 0.0))
            if d.length < 1e-6:
                continue
            nrm = Vector((-d.y, d.x, 0.0)).normalized()
            if abs(a.y - mine.face_y) < 0.01 and abs(b.y - mine.face_y) < 0.01:
                # the drawn gallery floor: from the open front edge to the back wall
                import env_geom
                lo_y, hi_y = env_geom.FRONT - 2.0, mine.back_y
                offs = sorted(((lo_y - a.y) / nrm.y, (hi_y - a.y) / nrm.y))
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
    fcx, fcy = cam["frame_centre"]
    loc = right * fcx + up * fcy + back * 2500.0
    r_g, u_g, b_g = (Vector(b2g(v)) for v in (right, up, back))
    rot = [[r_g.x, u_g.x, b_g.x], [r_g.y, u_g.y, b_g.y], [r_g.z, u_g.z, b_g.z]]
    ci = g.add_camera({"name": "MainView", "type": "orthographic",
                       "orthographic": {"xmag": X.FRAME_W / 2.0, "ymag": X.FRAME_W / 2.0 / X.ASPECT,
                                        "znear": 10.0, "zfar": 6000.0}})
    g.add_node({"name": "MainView", "camera": ci, "translation": list(b2g(loc)),
                "rotation": quat_from_matrix(rot),
                "extras": {"azimuthDeg": mine_map.CAM_AZ_DEG, "elevationDeg": mine_map.CAM_EL_DEG,
                           "aspect": "16:9", "zoomRange": [1, 4], "interaction": "pan and zoom only"}})
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


def full_pipeline(mine, topo, cam, samples, do_textures=True, do_previews=True):
    os.makedirs(X.OUT_DIR, exist_ok=True)
    if do_textures:
        for name, win, fname in (("far", X.FAR_WIN, "env_far.jpg"), ("near", X.NEAR_WIN, "env_near.jpg")):
            beauty, depth, normal = render_projected(name, win, cam, samples)
            arr = outlined(beauty, depth, normal, win[2] / TEX_SIZE)
            save_jpeg(arr, os.path.join(X.OUT_DIR, fname), quality=88)
            for f in (beauty, depth, normal):      # large intermediates
                os.remove(f)
    build_glb(mine, topo, cam)
    if do_previews:
        previews(mine, cam, max(128, samples // 3))
