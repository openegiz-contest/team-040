"""Deterministic LHD cycle and people-first traffic on two existing workings.

_s is distance from the face along cycle_route, not a world coordinate.
The pure cycle step is shared by real machines, undisturbed shadows and
the attribute cycle-time calculation. Internal keys are never published.
"""
import copy

EPS = 1e-9


def initial_machine(attributes):
    return dict(state="working", hold_reason="none", activity="loading",
        at_working=attributes["load_point"]["working"],
        offset_m=attributes["load_point"]["offset_m"], toward_node="",
        loaded=False, location_hazard="normal", operator_aboard=True,
        loads_dumped=0, run_hauled_t=0.0, _s=0.0, _phase="loading",
        _elapsed=0, _held=None, _episodes=[])


def cycle_step(machine, parameters, distance, travel=None, stop=False):
    """One second; a phase transition consumes no part of the next phase.

    travel(direction, speed) returns distance actually travelled. Its caller
    handles geometry, yielding and closures. Omitting it gives the shadow.
    """
    m, p = machine, parameters
    phase = m["_phase"]
    if stop:
        if m["loaded"]:
            phase = "dumping" if m["_s"] >= distance - EPS else "hauling"
        else:
            phase = "idle" if m["_s"] >= distance - EPS else "tramming"
        if phase != m["_phase"]:
            m["_elapsed"] = 0
        m["_phase"] = phase
    m["activity"] = phase
    if phase == "idle":
        return
    if phase in ("loading", "dumping"):
        m["_elapsed"] += 1
        duration = p["lhd_load_s"] if phase == "loading" else p["lhd_dump_s"]
        if m["_elapsed"] >= duration:
            m["_elapsed"] = 0
            if phase == "loading":
                m["loaded"], m["_phase"] = True, "hauling"
            else:
                m["loaded"] = False
                m["loads_dumped"] += 1
                m["run_hauled_t"] += p["lhd_payload_t"]
                m["_phase"] = "idle" if stop else "returning"
        return
    direction = -1 if phase == "returning" else 1
    speed = p["lhd_speed_loaded_m_s"] if m["loaded"] else p["lhd_speed_empty_m_s"]
    remaining = m["_s"] if direction < 0 else distance - m["_s"]
    budget = min(speed, remaining)
    moved = budget if travel is None else travel(direction, speed)
    m["_s"] = min(distance, max(0.0, m["_s"] + direction * min(budget, moved)))
    if (direction > 0 and m["_s"] >= distance - EPS) or (direction < 0 and m["_s"] <= EPS):
        m["_elapsed"] = 0
        m["_phase"] = ("dumping" if m["loaded"] else "idle") if stop else (
            "dumping" if direction > 0 else "loading")


def cycle_seconds(parameters, distance):
    m = dict(_s=0.0, _phase="loading", _elapsed=0, loaded=False, loads_dumped=0, run_hauled_t=0.)
    seconds = 0
    # Each phase must advance. Validation rejects zero/negative parameters.
    while True:
        cycle_step(m, parameters, distance)
        seconds += 1
        if m["loads_dumped"] and m["_phase"] == "loading" and m["_s"] <= EPS:
            return seconds


def distance_of(attributes, machine_attributes):
    return machine_attributes["load_point"]["offset_m"] + (
        attributes[machine_attributes["bay"]["working"]]["length_m"] - machine_attributes["bay"]["offset_m"])


def locate(attributes, a, m, direction=None):
    """Publish the face→junction→dump path; choose the next edge at a junction."""
    length = a["load_point"]["offset_m"]
    if direction is None:
        direction = -1 if m["_phase"] == "returning" else 1
    on_face = m["_s"] < length - EPS or (abs(m["_s"]-length) <= EPS and direction < 0)
    edge = a["cycle_route"][0 if on_face else 1]
    offset = length - m["_s"] if on_face else attributes[edge]["length_m"] - (m["_s"] - length)
    m.update(at_working=edge, offset_m=max(0., offset),
             toward_node=attributes[edge]["from" if direction > 0 else "to"])


def segments(attributes, a, m, direction):
    """Remaining directed path, including the shared node with both edges."""
    face, corridor = a["cycle_route"]
    face_length = a["load_point"]["offset_m"]
    end = distance_of(attributes, a)
    spans = [(face, 0., face_length), (corridor, face_length, end)]
    if direction < 0:
        spans.reverse()
    result = []
    for edge, lo, hi in spans:
        start = max(lo, m["_s"]) if direction > 0 else min(hi, m["_s"])
        target = hi if direction > 0 else lo
        if direction * (target - start) < -EPS:
            continue
        result.append((edge, start, target))
    return result


def worker_distance(attributes, a, worker):
    edge = worker.get("at_working")
    if edge == a["cycle_route"][0]:
        return a["load_point"]["offset_m"] - worker["offset_m"]
    if edge == a["cycle_route"][1]:
        return a["load_point"]["offset_m"] + attributes[edge]["length_m"] - worker["offset_m"]
    return None


def crew_staffed(mine, zone):
    return sum(w["status"] == "working" and mine.attributes[k]["home_zone"] == zone
               and mine.attributes[k]["role"] == "crew"
               for k, w in mine.workers.items()) >= mine.attributes[zone]["required_workers"]


def sync_operator(mine, key):
    m, a = mine.machines[key], mine.attributes[key]
    w = mine.workers[a["operator"]]
    m["operator_aboard"] = w.get("aboard") == key
    if not m["operator_aboard"]:
        return
    w.update(at_working=m["at_working"], offset_m=m["offset_m"])
    w.pop("at_exit", None)
    withdrawing = mine.zones[a["zone"]]["withdrawal_state"] != "none"
    w["status"] = "moving_to_exit" if withdrawing else "working"
    if withdrawing and m["_s"] >= distance_of(mine.attributes, a)-EPS and not m["loaded"]:
        w.pop("aboard", None)
        m["operator_aboard"] = False


def refresh(mine):
    for key, m in sorted(mine.machines.items()):
        a = mine.attributes[key]
        z = mine.zones[a["zone"]]
        locate(mine.attributes, a, m)
        if mine.workings[m["at_working"]]["passability"] == "closed":
            m["_held"] = "path_closed"
        stopped = z["work_state"] == "stopped"
        if not stopped and m["_held"] is None:
            outside = mine.attributes[m["at_working"]].get("zone") != a["zone"]
            if outside and m["_phase"] == "returning" and z["routing_restriction"] != "allowed":
                m["_held"] = "entry_blocked"
            elif (not mine.workers[a["operator"]].get("aboard") or
                  (m["_phase"] in ("loading", "dumping", "idle") and not crew_staffed(mine, a["zone"]))):
                m["_held"] = "crew_absent"
        reason = "path_closed" if m["_held"] == "path_closed" else (
            "zone_stopped" if stopped else m["_held"] or "none")
        m.update(state="stopped" if stopped else ("parked" if reason != "none" else "working"),
                 hold_reason=reason)
        if reason not in ("none", "zone_stopped") or m["_phase"] == "idle":
            m["activity"] = "idle"
            m.pop("yielding_to", None)
        zone = mine.attributes[m["at_working"]].get("zone")
        m["location_hazard"] = mine.zones[zone]["hazard_state"] if zone else "unknown"
        sync_operator(mine, key)


def reset_window(mine):
    mine.shadow = {}
    for key, machine in mine.machines.items():
        shadow = copy.deepcopy(machine)
        # A stopped/parked empty machine at a station resumes a productive cycle.
        if shadow["_phase"] in ("idle", "tramming"):
            shadow["_phase"] = "returning" if shadow["_s"] > EPS else "loading"
            shadow["_elapsed"] = 0
        shadow["run_hauled_t"] = 0.
        shadow["loads_dumped"] = 0
        shadow["_held"] = None
        shadow["_episodes"] = []
        mine.shadow[key] = shadow
    mine.hauled_t = mine.planned_t = 0.
    mine.conflicts = mine.conflict_yield_s = 0


def step(mine):
    for key, m in sorted(mine.machines.items()):
        a = mine.attributes[key]
        length = distance_of(mine.attributes, a)
        m.pop("yielding_to", None)
        episodes = []
        stopped = mine.zones[a["zone"]]["work_state"] == "stopped"
        blocked = m["hold_reason"] not in ("none", "zone_stopped")
        old_tonnes = m["run_hauled_t"]

        def travel(direction, speed):
            spans = segments(mine.attributes, a, m, direction)
            available = min(speed, m["_s"] if direction < 0 else length-m["_s"])
            # Closure at the current/next edge latches until explicit resume.
            for edge, start, end in spans:
                if mine.workings[edge]["passability"] == "closed":
                    gap = abs(start - m["_s"])
                    if gap < available + EPS:
                        available = max(0., gap)
                        m["_held"] = "path_closed"
                    break
            if m["_held"] == "path_closed":
                m["activity"] = "idle"
                return 0.  # No part of a step crosses into a closed working.
            ahead = []
            for worker_id, w in sorted(mine.workers.items()):
                if w["status"] not in ("moving_to_exit", "waiting") or w.get("aboard"):
                    continue
                s = worker_distance(mine.attributes, a, w)
                if s is None or s < -EPS or s > length+EPS:
                    continue
                gap = direction * (s - m["_s"])
                if gap < -EPS:
                    continue
                if gap <= mine.parameters["lhd_clearance_m"] + speed:
                    episodes.append(worker_id)
                    if worker_id not in m["_episodes"]:
                        mine.conflicts += 1
                        mine._event("equipment.conflict", key,
                            f"{a['label']} уступает дорогу {mine.attributes[worker_id]['label']}, {gap:.1f} м",
                            details=dict(worker=worker_id, working=w["at_working"], gap_m=gap,
                                machine_offset_m=m["offset_m"], worker_offset_m=w["offset_m"],
                                causes=mine._causes()))
                ahead.append((gap, worker_id))
            if ahead:
                gap, worker_id = min(ahead)
                limited = max(0., gap - mine.parameters["lhd_clearance_m"])
                if limited < available - EPS:
                    m.update(activity="yielding", yielding_to=worker_id)
                    mine.conflict_yield_s += 1
                    available = limited
            return available

        if not blocked and m["operator_aboard"]:
            cycle_step(m, mine.parameters, length, travel, stop=stopped)
        else:
            m["activity"] = "idle"
        m["_episodes"] = episodes
        mine.hauled_t += m["run_hauled_t"] - old_tonnes
        locate(mine.attributes, a, m)
        sync_operator(mine, key)
        shadow = mine.shadow[key]
        before = shadow["run_hauled_t"]
        cycle_step(shadow, mine.parameters, length)
        mine.planned_t += shadow["run_hauled_t"] - before


def resume(mine, zone):
    for key in mine.attributes[zone]["equipment"]:
        m = mine.machines[key]
        m["_held"] = None
        if m["_phase"] in ("idle", "tramming"):
            m["_phase"] = "hauling" if m["loaded"] else (
                "loading" if m["_s"] <= EPS else "returning")
            m["_elapsed"] = 0
