"""Minimal glTF 2.0 binary writer (stdlib only) for the environment GLB.

Blender (x, y, z) -> glTF (x, z, -y). Images are external files (uri) next to the GLB.
"""

import json
import math
import struct
from array import array


def b2g(p):
    return (p[0], p[2], -p[1])


def quat_from_matrix(m):
    """m: 3x3 rows (column vectors are the local axes in world). Returns (x, y, z, w)."""
    m00, m01, m02 = m[0]
    m10, m11, m12 = m[1]
    m20, m21, m22 = m[2]
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w, x, y, z = 0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        w, x, y, z = (m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        w, x, y, z = (m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2
        w, x, y, z = (m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s
    n = math.sqrt(x * x + y * y + z * z + w * w)
    return [x / n, y / n, z / n, w / n]


class GLB:
    def __init__(self):
        self.j = {"asset": {"version": "2.0", "generator": "mine-art env build (glb_writer.py)"},
                  "scene": 0, "scenes": [{"name": "Scene", "nodes": []}], "nodes": [],
                  "meshes": [], "materials": [], "accessors": [], "bufferViews": [],
                  "buffers": [{"byteLength": 0}]}
        self.bin = bytearray()
        self.used_ext = set()

    def _view(self, data, target=None):
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        self.bin.extend(data)
        bv = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target:
            bv["target"] = target
        self.j["bufferViews"].append(bv)
        return len(self.j["bufferViews"]) - 1

    def _accessor(self, data_bytes, ctype, count, atype, target, mn=None, mx=None):
        v = self._view(data_bytes, target)
        acc = {"bufferView": v, "componentType": ctype, "count": count, "type": atype}
        if mn is not None:
            acc["min"], acc["max"] = mn, mx
        self.j["accessors"].append(acc)
        return len(self.j["accessors"]) - 1

    def add_material(self, mat):
        self.j["materials"].append(mat)
        for e in mat.get("extensions", {}):
            self.used_ext.add(e)
        return len(self.j["materials"]) - 1

    def add_texture(self, uri, sampler=None):
        self.j.setdefault("images", []).append({"uri": uri})
        self.j.setdefault("samplers", [])
        if not self.j["samplers"]:
            self.j["samplers"].append(sampler or {"magFilter": 9729, "minFilter": 9987,
                                                  "wrapS": 33071, "wrapT": 33071})
        self.j.setdefault("textures", []).append({"sampler": 0, "source": len(self.j["images"]) - 1})
        return len(self.j["textures"]) - 1

    def add_mesh(self, name, prims):
        """prims: list of dict(positions=[(x,y,z) glTF], uvs=[(u,v)] or None, indices=[...],
        material=index)."""
        out = []
        for p in prims:
            pos = p["positions"]
            flat = array("f", [c for v in pos for c in v])
            mn = [min(v[i] for v in pos) for i in range(3)]
            mx = [max(v[i] for v in pos) for i in range(3)]
            attrs = {"POSITION": self._accessor(flat.tobytes(), 5126, len(pos), "VEC3", 34962, mn, mx)}
            if p.get("uvs"):
                uv = array("f", [c for v in p["uvs"] for c in v])
                attrs["TEXCOORD_0"] = self._accessor(uv.tobytes(), 5126, len(p["uvs"]), "VEC2", 34962)
            idx = p["indices"]
            if len(pos) < 65536:
                ib = array("H", idx).tobytes()
                ct = 5123
            else:
                ib = array("I", idx).tobytes()
                ct = 5125
            ia = self._accessor(ib, ct, len(idx), "SCALAR", 34963)
            out.append({"attributes": attrs, "indices": ia, "material": p["material"], "mode": 4})
        self.j["meshes"].append({"name": name, "primitives": out})
        return len(self.j["meshes"]) - 1

    def add_node(self, node, root=True):
        self.j["nodes"].append(node)
        i = len(self.j["nodes"]) - 1
        if root:
            self.j["scenes"][0]["nodes"].append(i)
        return i

    def add_camera(self, cam):
        self.j.setdefault("cameras", []).append(cam)
        return len(self.j["cameras"]) - 1

    def write(self, path):
        if self.used_ext:
            self.j["extensionsUsed"] = sorted(self.used_ext)
        while len(self.bin) % 4:
            self.bin.append(0)
        self.j["buffers"][0]["byteLength"] = len(self.bin)
        js = json.dumps(self.j, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        while len(js) % 4:
            js += b" "
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        with open(path, "wb") as fh:
            fh.write(struct.pack("<III", 0x46546C67, 2, total))
            fh.write(struct.pack("<II", len(js), 0x4E4F534A))
            fh.write(js)
            fh.write(struct.pack("<II", len(self.bin), 0x004E4942))
            fh.write(self.bin)
        return total
