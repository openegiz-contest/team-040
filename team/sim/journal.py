"""State transitions only; normal progress along a route is not rerouting."""

import copy


def capture(mine):
    result = {}
    for key, sensor in mine.sensors.items():
        result[key] = {k: sensor[k] for k in ("link_state", "quality")}
    for key, zone in mine.zones.items():
        result[key] = {k: zone[k] for k in ("hazard_state", "data_quality", "routing_restriction",
                                            "work_state", "withdrawal_state")}
    for key, worker in mine.workers.items():
        result[key] = dict(status=worker["status"], egress_status=worker["egress_status"],
            egress_reason=worker["egress_reason"], exit=worker.get("egress_exit"),
            path=[[s["working"], s["to_node"]] for s in worker.get("route_segments", [])])
    return result


def observe(mine):
    if getattr(mine, "_forecast_only", False):
        return
    current = capture(mine)
    previous = getattr(mine, "_journal_state", None)
    mine._journal_state = current
    if previous is None:
        return  # Initialisation / first observation of an old checkpoint.

    def emit(code, subject, message, before, after, **evidence):
        mine._event(code, subject, message, details=dict(before=before, after=after,
            causes=mine._causes(), **evidence))

    for key, sensor in mine.sensors.items():
        old, new = previous[key], current[key]
        if old != new:
            emit("sensor.state_changed", key,
                 f"Связь {old['link_state']} → {new['link_state']}; данные {old['quality']} → {new['quality']}",
                 old, new, measured_at_sim_s=sensor["measured_at_sim_s"],
                 age_s=mine.tick - sensor["measured_at_sim_s"])
    for key, zone in mine.zones.items():
        old, new = previous[key], current[key]
        fields = ("hazard_state", "data_quality", "routing_restriction")
        if any(old[k] != new[k] for k in fields):
            reason = zone["reason_code"]
            explanation = (f"{zone['reason_value']:g} {zone['reason_unit']} ≥ "
                           f"{zone['reason_threshold']:g} (условный порог)") if "reason_value" in zone else reason
            emit("hazard.transition", key,
                 f"{old['hazard_state']} → {new['hazard_state']}: {explanation}; вход {new['routing_restriction']}",
                 {k: old[k] for k in fields}, {k: new[k] for k in fields},
                 **{k: copy.deepcopy(v) for k, v in zone.items()
                    if k.startswith("reason_") or k.startswith("last_known_")})
        for field, code, label in (("work_state", "work.changed", "Работа"),
                                    ("withdrawal_state", "withdrawal.changed", "Вывод")):
            if old[field] != new[field]:
                emit(code, key, f"{label}: {old[field]} → {new[field]}", old[field], new[field])
    for key in mine.workers:
        old, new = previous[key], current[key]
        if new["status"] == "out" and old["status"] != "out":
            emit("worker.exited", key, "Вышел через " + mine.workers[key]["at_exit"], old, new)
        elif new["status"] != "out":
            # Consuming a directed prefix is normal movement, including junctions.
            path = new["path"]
            continuation = bool(path) and len(path) <= len(old["path"]) and old["path"][-len(path):] == path
            changed = any(old[k] != new[k] for k in ("egress_status", "egress_reason", "exit"))
            if changed or (old["path"] != path and not continuation):
                emit("route.changed", key,
                     ("Нет расчётного маршрута: " + new["egress_reason"]) if new["egress_status"] != "ok"
                     else "Расчётный маршрут к " + str(new["exit"]) + ": " + " → ".join(p[0] for p in path),
                     old, new)
        if old["status"] != new["status"] and new["status"] != "out":
            emit("worker.state_changed", key, f"{old['status']} → {new['status']}", old["status"], new["status"])
