"""
check_actors.py - verify the mine-art actor GLBs against SPEC section 6 (stdlib only).

    python team/ui/assets/mine-art/actors/check_actors.py [--json]

Parses team/ui/public/models/mine-art/actors/{worker,lhd,truck,drill}.glb and prints
triangles (as rendered: mesh instances counted per node), materials, textures (size),
nodes (LAMPS, WHEELS, WHEEL_*), animations (names, durations), extras and the bounding
box at the origin, then the budget checks. Exit code 1 if any check fails.
"""

import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ACTORS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "public", "models", "mine-art", "actors"))

BUDGET = {
    "worker": dict(tris=1500, materials=1, textures=1, tex_max=512, wheels=0),
    "lhd": dict(tris=6000, textures=1, tex_max=1024, wheels=4),
    "truck": dict(tris=6000, textures=1, tex_max=1024, wheels=6),
    "drill": dict(tris=7000, textures=1, tex_max=1024, wheels=4),
}

COMPONENTS = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}


def read_glb(path):
    with open(path, "rb") as f:
        data = f.read()
    magic, _version, length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError("not a GLB: " + path)
    off, js, binc = 12, None, b""
    while off < length:
        clen, ctype = struct.unpack_from("<I4s", data, off)
        chunk = data[off + 8: off + 8 + clen]
        if ctype == b"JSON":
            js = json.loads(chunk.decode("utf-8"))
        elif ctype == b"BIN\x00":
            binc = chunk
        off += 8 + clen
    return js, binc, len(data)


def image_size(blob):
    """(format, width, height) from PNG or JPEG bytes."""
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", blob[16:24])
        return "png", w, h
    if blob[:2] == b"\xff\xd8":
        i = 2
        while i < len(blob):
            if blob[i] != 0xFF:
                i += 1
                continue
            marker = blob[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                h, w = struct.unpack(">HH", blob[i + 5:i + 9])
                return "jpeg", w, h
            seglen = struct.unpack(">H", blob[i + 2:i + 4])[0]
            i += 2 + seglen
    return "?", 0, 0


# --- small matrix helpers (column-major 4x4 as nested lists, row-major access m[r][c])

def mat_identity():
    return [[1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]


def mat_mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def node_matrix(node):
    if "matrix" in node:
        m = node["matrix"]
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    tx, ty, tz = node.get("translation", (0, 0, 0))
    qx, qy, qz, qw = node.get("rotation", (0, 0, 0, 1))
    sx, sy, sz = node.get("scale", (1, 1, 1))
    r = [[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
         [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
         [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]]
    m = [[r[i][0] * sx, r[i][1] * sy, r[i][2] * sz, (tx, ty, tz)[i]] for i in range(3)]
    m.append([0.0, 0.0, 0.0, 1.0])
    return m


def transform(m, p):
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3))


def inspect(name):
    path = os.path.join(ACTORS, name + ".glb")
    js, binc, nbytes = read_glb(path)
    acc = js.get("accessors", [])
    nodes = js.get("nodes", [])
    meshes = js.get("meshes", [])
    rep = {"file": path, "bytes": nbytes}

    # walk the scene graph: triangles per instance, bbox of positions
    tris = 0
    tris_by_node = {}
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    scene = js["scenes"][js.get("scene", 0)]

    def visit(i, parent_m):
        nonlocal tris
        nd = nodes[i]
        m = mat_mul(parent_m, node_matrix(nd))
        if "mesh" in nd:
            t = 0
            for prim in meshes[nd["mesh"]]["primitives"]:
                if prim.get("mode", 4) != 4:
                    continue
                if "indices" in prim:
                    t += acc[prim["indices"]]["count"] // 3
                else:
                    t += acc[prim["attributes"]["POSITION"]]["count"] // 3
                pa = acc[prim["attributes"]["POSITION"]]
                if "skin" in nd:
                    corners = [(x, y, z) for x in (pa["min"][0], pa["max"][0])
                               for y in (pa["min"][1], pa["max"][1]) for z in (pa["min"][2], pa["max"][2])]
                    pts = corners
                else:
                    pts = [transform(m, (x, y, z)) for x in (pa["min"][0], pa["max"][0])
                           for y in (pa["min"][1], pa["max"][1]) for z in (pa["min"][2], pa["max"][2])]
                if nd.get("name") != "SHADOW":
                    for p in pts:
                        for k in range(3):
                            lo[k], hi[k] = min(lo[k], p[k]), max(hi[k], p[k])
            tris += t
            tris_by_node[nd.get("name", str(i))] = tris_by_node.get(nd.get("name", str(i)), 0) + t
        for c in nd.get("children", []):
            visit(c, m)

    for r in scene["nodes"]:
        visit(r, mat_identity())
    rep["triangles"] = tris
    rep["triangles_by_node"] = tris_by_node
    rep["bbox_min"] = [round(v, 3) for v in lo]
    rep["bbox_max"] = [round(v, 3) for v in hi]

    # materials and textures
    mats = []
    for m in js.get("materials", []):
        pbr = m.get("pbrMetallicRoughness", {})
        mats.append({
            "name": m.get("name"),
            "unlit": "KHR_materials_unlit" in m.get("extensions", {}),
            "alphaMode": m.get("alphaMode", "OPAQUE"),
            "doubleSided": m.get("doubleSided", False),
            "texture": pbr.get("baseColorTexture", {}).get("index"),
            "baseColorFactor": [round(c, 4) for c in pbr.get("baseColorFactor", [1, 1, 1, 1])],
            "extras": m.get("extras"),
        })
    rep["materials"] = mats
    texs = []
    for i, img in enumerate(js.get("images", [])):
        if "bufferView" in img:
            bv = js["bufferViews"][img["bufferView"]]
            blob = binc[bv.get("byteOffset", 0): bv.get("byteOffset", 0) + bv["byteLength"]]
        else:
            blob = open(os.path.join(ACTORS, img["uri"]), "rb").read()
        fmt, w, h = image_size(blob)
        texs.append({"image": i, "name": img.get("name"), "format": fmt, "width": w, "height": h,
                     "bytes": len(blob)})
    rep["textures"] = texs

    names = [n.get("name", "") for n in nodes]
    rep["nodes"] = names
    rep["root_nodes"] = [nodes[i].get("name") for i in scene["nodes"]]
    rep["lamps"] = [n for n in names if n == "LAMPS"]
    rep["wheels"] = sorted(n for n in names if n.startswith("WHEEL_"))
    rep["wheels_group"] = "WHEELS" in names
    root = nodes[scene["nodes"][0]]
    rep["root_extras"] = root.get("extras", {})
    rep["scene_extras"] = scene.get("extras", {})
    wheel_nodes = {n.get("name"): n for n in nodes if n.get("name", "").startswith("WHEEL_")}
    rep["wheel_centres"] = {k: [round(v, 3) for v in n.get("translation", (0, 0, 0))]
                            for k, n in sorted(wheel_nodes.items())}

    anims = []
    for a in js.get("animations", []):
        dur = 0.0
        for s in a["samplers"]:
            dur = max(dur, acc[s["input"]].get("max", [0])[0])
        anims.append({"name": a.get("name"), "duration_s": round(dur, 4), "channels": len(a["channels"]),
                      "extras": a.get("extras")})
    rep["animations"] = anims
    rep["skins"] = len(js.get("skins", []))
    rep["extensionsUsed"] = js.get("extensionsUsed", [])
    return rep


def checks(name, rep):
    b = BUDGET[name]
    out = []

    def ok(label, cond, detail=""):
        out.append((label, bool(cond), detail))

    ok("triangles <= %d" % b["tris"], rep["triangles"] <= b["tris"], rep["triangles"])
    ok("all materials unlit", all(m["unlit"] for m in rep["materials"]),
       [m["name"] for m in rep["materials"] if not m["unlit"]])
    ok("single-sided materials", all(not m["doubleSided"] for m in rep["materials"]))
    ok("textures == %d" % b["textures"], len(rep["textures"]) == b["textures"], len(rep["textures"]))
    ok("texture <= %d^2" % b["tex_max"],
       all(t["width"] <= b["tex_max"] and t["height"] <= b["tex_max"] for t in rep["textures"]),
       ["%dx%d" % (t["width"], t["height"]) for t in rep["textures"]])
    if "materials" in b:
        ok("materials == %d" % b["materials"], len(rep["materials"]) == b["materials"], len(rep["materials"]))
    lo, hi = rep["bbox_min"], rep["bbox_max"]
    ok("origin on the ground (min up ~ 0)", abs(lo[1]) < 0.05, lo[1])
    ok("origin centred in plan", abs((lo[0] + hi[0]) / 2) < 0.15 * (hi[0] - lo[0]) and abs((lo[2] + hi[2]) / 2) < 0.15 * (hi[2] - lo[2]),
       ((lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2))
    if name == "worker":
        an = {a["name"]: a for a in rep["animations"]}
        ok("clips walk + idle", "walk" in an and "idle" in an, sorted(an))
        stride = rep["root_extras"].get("strideM") or rep["scene_extras"].get("strideM")
        ok("extras.strideM", isinstance(stride, (int, float)) and stride > 0, stride)
        h = hi[1] - lo[1]
        ok("height ~ 5 m", 4.8 <= h <= 5.2, round(h, 3))
        ok("facing +X (longer forward than back: nose, toes)", hi[0] > -lo[0], (lo[0], hi[0]))
        ok("skinned", rep["skins"] == 1, rep["skins"])
    else:
        ok("LAMPS node", rep["lamps"] == ["LAMPS"], rep["lamps"])
        ok("WHEELS group + %d WHEEL_*" % b["wheels"], rep["wheels_group"] and len(rep["wheels"]) == b["wheels"],
           rep["wheels"])
        ok("no animations", not rep["animations"])
        ok("facing +X (longest along X)", (hi[0] - lo[0]) > (hi[2] - lo[2]), (hi[0] - lo[0], hi[2] - lo[2]))
    return out


def main():
    as_json = "--json" in sys.argv
    allok = True
    reports = {}
    for name in ("worker", "lhd", "truck", "drill"):
        path = os.path.join(ACTORS, name + ".glb")
        if not os.path.exists(path):
            print(f"== {name}: MISSING {path}")
            allok = False
            continue
        rep = inspect(name)
        res = checks(name, rep)
        reports[name] = {"report": rep, "checks": [(l, o, str(d)) for l, o, d in res]}
        if as_json:
            continue
        print(f"== {name}.glb  {rep['bytes'] / 1024:.0f} KiB")
        print(f"   triangles  {rep['triangles']}  by node: " +
              ", ".join(f"{k} {v}" for k, v in rep["triangles_by_node"].items()))
        for m in rep["materials"]:
            print(f"   material   {m['name']}: unlit={m['unlit']} alpha={m['alphaMode']} "
                  f"texture={m['texture']} factor={m['baseColorFactor']}" + (f" extras={m['extras']}" if m["extras"] else ""))
        for t in rep["textures"]:
            print(f"   texture    #{t['image']} {t['name']}: {t['format']} {t['width']}x{t['height']} "
                  f"{t['bytes'] / 1024:.0f} KiB")
        print(f"   nodes      {len(rep['nodes'])}: {', '.join(rep['nodes'])}")
        if rep["wheels"]:
            print(f"   wheels     {rep['wheel_centres']}")
        for a in rep["animations"]:
            print(f"   animation  {a['name']}: {a['duration_s']} s, {a['channels']} channels"
                  + (f", extras={a['extras']}" if a["extras"] else ""))
        print(f"   bbox       min {rep['bbox_min']} max {rep['bbox_max']}  (glTF: x fwd, y up, z right)")
        print(f"   root       {rep['root_nodes']} extras {json.dumps(rep['root_extras'])}")
        print(f"   scene      extras {json.dumps(rep['scene_extras'])}")
        for label, good, detail in res:
            allok &= good
            print(f"   [{'PASS' if good else 'FAIL'}] {label}" + (f"  ({detail})" if detail not in ("", None) else ""))
    if as_json:
        print(json.dumps(reports, indent=1, default=str))
    else:
        total = sum(os.path.getsize(os.path.join(ACTORS, n + ".glb")) for n in reports)
        print(f"== total {total / 1024:.0f} KiB in {ACTORS}")
        print("ALL PASS" if allok else "SOME CHECKS FAILED")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
