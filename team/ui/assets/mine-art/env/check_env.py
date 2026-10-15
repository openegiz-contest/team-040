"""Check team/ui/public/models/mine-art/env.glb against SPEC sections 5 and 8 (stdlib only).

    python check_env.py            prints the numbers, exits 1 if a budget or contract fails
"""

import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", ".."))
ART = os.path.join(ROOT, "team", "ui", "public", "models", "mine-art")
GLB = os.path.join(ART, "env.glb")
TOPO = os.path.join(HERE, "build", "topology.json")

BUDGET_TRIS = 100_000
AIM_TRIS = 60_000
BUDGET_DRAWS = 80
BUDGET_FOLDER = 8 * 1024 * 1024
MAX_TEX = 2048


def read_glb(path):
    with open(path, "rb") as fh:
        data = fh.read()
    magic, version, length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67 and version == 2 and length == len(data), "not a glTF 2 binary"
    jlen, jtype = struct.unpack_from("<II", data, 12)
    assert jtype == 0x4E4F534A
    j = json.loads(data[20:20 + jlen].decode("utf-8"))
    return j, len(data)


def image_size(path):
    with open(path, "rb") as fh:
        d = fh.read()
    if d[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", d[16:24])
    if d[:2] == b"\xff\xd8":
        i = 2
        while i < len(d):
            if d[i] != 0xFF:
                i += 1
                continue
            marker = d[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", d[i + 5:i + 9])
                return w, h
            seg = struct.unpack(">H", d[i + 2:i + 4])[0]
            i += 2 + seg
    raise ValueError("unknown image " + path)


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("  ok   " if cond else "  FAIL ") + msg)
        ok = ok and cond

    j, glb_bytes = read_glb(GLB)
    nodes = j["nodes"]
    print("env.glb:", GLB, glb_bytes, "bytes")
    extras = j["scenes"][j.get("scene", 0)].get("extras", {})
    print("scene extras:", json.dumps(extras, ensure_ascii=False))
    topo = json.load(open(TOPO, encoding="utf-8")) if os.path.exists(TOPO) else None
    check(extras.get("mineArt") == 1, "extras.mineArt == 1")
    check(abs(extras.get("k", 0) - 1.6) < 1e-9, "extras.k == 1.6")
    check(extras.get("zTop") == 0, "extras.zTop == 0")
    check(extras.get("camera") == "MainView", "extras.camera == MainView")
    if topo:
        check(extras.get("topology") == topo["topology"], "extras.topology == sha1 of build/topology.json")
        check((extras.get("cx"), extras.get("cy")) == (topo["cx"], topo["cy"]), "extras.cx/cy match the topology")
        check(extras.get("workings") == sorted(topo["workings"]), "extras.workings = 12 working ids")
    # camera
    cams = j.get("cameras", [])
    cam_nodes = [n for n in nodes if "camera" in n]
    check(len(cams) == 1 and len(cam_nodes) == 1 and cam_nodes[0]["name"] == "MainView",
          "exactly one camera, node MainView")
    if cams:
        c = cams[0]
        print("camera:", c["type"], json.dumps(c.get("orthographic")),
              "translation", [round(v, 2) for v in cam_nodes[0]["translation"]],
              "rotation", [round(v, 5) for v in cam_nodes[0]["rotation"]],
              "extras", json.dumps(cam_nodes[0].get("extras", {})))
        check(c["type"] == "orthographic", "MainView is orthographic")
        o = c["orthographic"]
        check(abs(o["xmag"] / o["ymag"] - 16 / 9) < 1e-6, "MainView aspect 16:9")
    check("lights" not in json.dumps(j.get("extensions", {})) and "KHR_lights_punctual" not in j.get("extensionsUsed", []),
          "no lights")
    check(not j.get("animations"), "no animations")
    # triangles and draw calls
    acc = j["accessors"]
    tris_env = tris_pick = 0
    prims_env = prims_pick = 0
    for n in nodes:
        if "mesh" not in n:
            continue
        for p in j["meshes"][n["mesh"]]["primitives"]:
            t = acc[p["indices"]]["count"] // 3
            if n["name"].startswith("PICK_"):
                tris_pick += t
                prims_pick += 1
            else:
                tris_env += t
                prims_env += 1
    print(f"triangles: visible {tris_env}, pick (invisible) {tris_pick}")
    check(tris_env <= BUDGET_TRIS, f"visible triangles {tris_env} <= {BUDGET_TRIS} (aim {AIM_TRIS})")
    print(f"draw calls: visible primitives {prims_env}, pick primitives {prims_pick} (hidden in the browser)")
    check(prims_env + prims_pick <= BUDGET_DRAWS, f"primitives {prims_env + prims_pick} <= {BUDGET_DRAWS}")
    mats = j.get("materials", [])
    print("materials:", len(mats), [m["name"] for m in mats])
    check(all("KHR_materials_unlit" in m.get("extensions", {}) for m in mats), "all materials KHR_materials_unlit")
    # textures
    tex_bytes = 0
    for im in j.get("images", []):
        path = os.path.join(ART, im["uri"])
        w, h = image_size(path)
        size = os.path.getsize(path)
        tex_bytes += size
        print(f"texture: {im['uri']} {w}x{h} {size} bytes")
        check(w <= MAX_TEX and h <= MAX_TEX, f"{im['uri']} <= {MAX_TEX}^2 (light-map class, max 2)")
    check(len(j.get("images", [])) <= 2, "at most 2 baked textures")
    env_total = glb_bytes + tex_bytes
    folder = 0
    for dp, _, fs in os.walk(ART):
        for f in fs:
            folder += os.path.getsize(os.path.join(dp, f))
    print(f"bytes: env.glb + textures {env_total} ({env_total / 1048576:.2f} MiB); "
          f"whole models/mine-art/ {folder} ({folder / 1048576:.2f} MiB)")
    check(folder <= BUDGET_FOLDER, "models/mine-art/ <= 8 MiB")
    # picks and anchors
    picks = sorted(n["name"] for n in nodes if n["name"].startswith("PICK_"))
    print("PICK_:", picks)
    if topo:
        want = sorted("PICK_" + w for w in topo["workings"])
        check(picks == want, "PICK_ nodes match the 12 workings")
    for n in nodes:
        if n["name"].startswith("PICK_"):
            wid = n["name"][5:]
            if n.get("extras", {}).get("thingId") != f"team040.mine:{wid}":
                check(False, f"{n['name']} extras.thingId")
    check(all(n.get("extras", {}).get("thingId") == "team040.mine:" + n["name"][5:]
              for n in nodes if n["name"].startswith("PICK_")), "PICK_ extras.thingId = team040.mine:<working>")
    anchors = [n for n in nodes if n["name"].startswith("ANCHOR_")]
    for a in anchors:
        print("ANCHOR:", a["name"], [round(v, 2) for v in a["translation"]],
              "rot", [round(v, 4) for v in a["rotation"]], json.dumps(a.get("extras", {})))
    names = {a["name"] for a in anchors}
    for need in ("ANCHOR_lhd_zone-a", "ANCHOR_lhd_zone-b", "ANCHOR_truck", "ANCHOR_drill"):
        check(need in names, need)
    check(all("mesh" not in a for a in anchors), "anchors are empties")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
