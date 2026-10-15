"""Dump the real mine topology (team.sim.topology.build_attributes) to build/topology.json.

Run with the system Python from anywhere:  python dump_topology.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from team.sim.topology import build_attributes  # noqa: E402
import mine_map  # noqa: E402


def main():
    attrs = build_attributes()
    nodes = attrs["mine"]["nodes"]
    workings = {}
    for key, a in attrs.items():
        if a.get("kind") != "working":
            continue
        workings[key] = {
            "from": a["from"], "to": a["to"], "kind": a["working_kind"],
            "zone": a.get("zone"), "length_m": a["length_m"], "level": a["level"],
            "points": a["points"],
        }
    for w in workings.values():
        w["polyline"] = mine_map.full_polyline(nodes, w)
    cx, cy = mine_map.plan_centre(nodes, workings)
    sig, canon = mine_map.signature(nodes, workings)
    out = {
        "source": "team.sim.topology.build_attributes()",
        "k": mine_map.K, "zTop": mine_map.ZTOP, "cx": cx, "cy": cy,
        "topology": sig, "canonical": canon,
        "nodes": nodes, "workings": workings,
    }
    os.makedirs(os.path.dirname(mine_map.TOPOLOGY_JSON), exist_ok=True)
    with open(mine_map.TOPOLOGY_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("workings", len(workings), "cx", cx, "cy", cy, "topology", sig)


if __name__ == "__main__":
    main()
