"""Mine -> scene mapping shared by the Blender build and the checks (stdlib only).

Mine frame: x east, y north, z up (metres). Scene (three.js, Y up):
    X = x - cx,  Y = (z - zTop) * k,  Z = cy - y        (SPEC section 3)
Blender works Z-up and its glTF exporter writes (bx, by, bz) -> (bx, bz, -by), so in
Blender the same transform is
    bx = x - cx,  by = y - cy,  bz = (z - zTop) * k
"""

import hashlib
import json
import math
import os

K = 1.35
ZTOP = 0.0

# Main view (SPEC section 4): orthographic isometric-like view from the south-east:
# azimuth from south toward the east, elevation above the horizon. Chosen by comparing
# overviews at azimuth 22, 24, 30 and 40 (the reference reads at 40-45; 24 fills the 16:9
# frame with the mine and shows the lit back walls). Allowed: azimuth 20-50, elevation 26-34.

CAM_AZ_DEG = 24.0
CAM_EL_DEG = 28.0
CAM_AZ_RANGE = (20.0, 50.0)
CAM_EL_RANGE = (26.0, 34.0)

HERE = os.path.dirname(os.path.abspath(__file__))
TOPOLOGY_JSON = os.path.join(HERE, "build", "topology.json")


def load(path=TOPOLOGY_JSON):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def full_polyline(nodes, working):
    """Polyline of a working in mine metres: from-node, bends (`points`), to-node."""
    a, b = nodes[working["from"]], nodes[working["to"]]
    pts = [[a["x"], a["y"], a["z"]]]
    pts += [list(p) for p in working.get("points", [])]
    pts.append([b["x"], b["y"], b["z"]])
    return [[float(c) for c in p] for p in pts]


def plan_centre(nodes, workings):
    xs, ys = [], []
    for n in nodes.values():
        xs.append(n["x"]); ys.append(n["y"])
    for w in workings.values():
        for p in full_polyline(nodes, w):
            xs.append(p[0]); ys.append(p[1])
    return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0


def signature(nodes, workings):
    """sha1 hex of the canonical working list.

    Canonical form (the browser must build the same string):
      JSON.stringify(list) with no spaces, list sorted by working id, each item
      [id, from, to, [[x, y, z], ...]] where the points are the full polyline
      (from-node, bends, to-node) in mine metres, each coordinate Math.round()-ed.
    """
    items = []
    for wid in sorted(workings):
        w = workings[wid]
        pts = [[int(round(c)) for c in p] for p in full_polyline(nodes, w)]
        items.append([wid, w["from"], w["to"], pts])
    text = json.dumps(items, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(text.encode("utf-8")).hexdigest(), text


def to_blender(p, cx, cy):
    return (p[0] - cx, p[1] - cy, (p[2] - ZTOP) * K)


def cam_basis(az_deg=CAM_AZ_DEG, el_deg=CAM_EL_DEG):
    """(towards_camera, right, up) unit vectors in Blender world coordinates."""
    az, el = math.radians(az_deg), math.radians(el_deg)
    back = (math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el))
    right = (math.cos(az), math.sin(az), 0.0)
    d = (-back[0], -back[1], -back[2])
    up = (right[1] * d[2] - right[2] * d[1],
          right[2] * d[0] - right[0] * d[2],
          right[0] * d[1] - right[1] * d[0])
    return back, right, up


def to_screen(p, az_deg=CAM_AZ_DEG, el_deg=CAM_EL_DEG):
    """Orthographic screen coordinates (metres) of a Blender point, origin at world 0."""
    _, r, u = cam_basis(az_deg, el_deg)
    return (p[0] * r[0] + p[1] * r[1] + p[2] * r[2],
            p[0] * u[0] + p[1] * u[1] + p[2] * u[2])
