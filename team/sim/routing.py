"""Shortest walkable path from an edge position; no teleports at closures."""

import heapq
from itertools import count


def route(attributes, workings, zones, exits, worker):
    if worker["status"] == "out":
        return {"egress_status": "ok", "egress_reason": "none", "route": []}
    current = worker["at_working"]
    edge = attributes[current]
    if workings[current]["passability"] == "closed":
        return {"egress_status": "none", "egress_reason": "current_working_closed", "route": []}
    def permitted(key):
        zone = attributes[key].get("zone")
        return workings[key]["passability"] == "open" and (
            not zone or zones[zone]["routing_restriction"] == "allowed")

    adjacency = {}
    for key in sorted(workings):
        if key == current or not permitted(key):
            continue
        a = attributes[key]
        for start, end in [(a["from"], a["to"]), (a["to"], a["from"])]:
            adjacency.setdefault(start, []).append((end, key, a["length_m"]))
    targets = {attributes[key]["node"]: key for key in sorted(exits)
               if exits[key]["state"] == "available"}
    queue, serial, best = [], count(), {}
    # A worker already on a restricted edge can leave it in either direction.
    # It is never available for entry/re-entry as an intermediate graph edge.
    for node, offset in [(edge["from"], 0.0), (edge["to"], edge["length_m"])]:
        segment = {"working": current, "from_offset_m": worker["offset_m"],
                   "to_offset_m": offset, "to_node": node}
        heapq.heappush(queue, (abs(offset - worker["offset_m"]), next(serial), node, [segment]))
    while queue:
        distance, _, node, segments = heapq.heappop(queue)
        if distance >= best.get(node, float("inf")):
            continue
        best[node] = distance
        if node in targets:
            hazards = [zones[attributes[s["working"]]["zone"]]["hazard_state"]
                       if attributes[s["working"]].get("zone") else "unknown" for s in segments]
            worst = max(hazards, key={"normal": 0, "attention": 1, "unknown": 2, "danger": 3}.get)
            return dict(egress_status="ok", egress_reason="none", egress_exit=targets[node],
                        egress_length_m=distance, route=[s["working"] for s in segments],
                        route_next_node=segments[0]["to_node"], route_segments=segments,
                        egress_crosses=worst)
        for end, key, length in adjacency.get(node, []):
            a = attributes[key]
            forward = a["from"] == node
            segment = dict(working=key, from_offset_m=0.0 if forward else length,
                           to_offset_m=length if forward else 0.0, to_node=end)
            heapq.heappush(queue, (distance + length, next(serial), end, segments + [segment]))
    return {"egress_status": "none", "egress_reason": "no_open_path", "route": []}
