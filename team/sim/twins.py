"""Projection to the agreed native Ditto feature and MQTT envelope formats."""

import copy

from .topology import NAMESPACE, TOPOLOGY_VERSION

UNITS = {
    "sim_time_s": "s", "measured_at_sim_s": "s", "finished_at_sim_s": "s",
    "value": "mm", "rate": "mm/h", "instability_index": "1", "offset_m": "m",
    "egress_length_m": "m", "egress_eta_s": "s", "egress_detour_m": "m", "egress_detour_s": "s",
    "production_rate": "t/h", "last_out_s": "s", "downtime_s": "zone*s",
    "danger_exposure_person_s": "person*s", "unknown_exposure_person_s": "person*s",
    "forecast_horizon_s": "s",
}


def features(values):
    result = {}
    for key, value in values.items():
        if value is None:
            continue
        plain = key.removeprefix("forecast_").removeprefix("actual_")
        unit = UNITS.get(key, UNITS.get(plain))
        result[key] = {"properties": {"value": copy.deepcopy(value)}}
        if unit:
            result[key]["properties"]["unit"] = unit
    return result


def snapshot(mine):
    """One heartbeat, including while paused. Caller persists before publishing."""
    mine.publication_seq += 1
    common = dict(tick=mine.tick, sim_time_s=mine.tick, idSimulationRun=mine.run)
    twins = {key: {"thingId": f"{NAMESPACE}:{key}", "policyId": "default:basic_policy",
                    "attributes": copy.deepcopy(a)} for key, a in mine.attributes.items()}
    dynamic = {}
    for collection in (mine.workings, mine.zones, mine.sensors, mine.workers, mine.exits):
        dynamic.update(copy.deepcopy(collection))
    for key, state in mine.workings.items():
        zone = mine.attributes[key].get("zone")
        hazard = mine.zones[zone] if zone else dict(hazard_state="unknown", data_quality="none",
                                                   reason_code="no_sensor", routing_restriction="allowed")
        for field, value in hazard.items():
            if field not in ("work_state", "withdrawal_state", "workers_count", "production_rate", "downtime_s"):
                dynamic[key][field] = value
    for key, worker in mine.workers.items():
        # Directed segments are explicit; the browser does not solve the graph.
        if "route_segments" in worker:
            segments = dynamic[key].pop("route_segments")
            dynamic[key]["route"] = [dict(working=s["working"], to=s["to_node"],
                **{"from": mine.attributes[s["working"]]["from"] if s["to_node"] ==
                   mine.attributes[s["working"]]["to"] else mine.attributes[s["working"]]["to"]},
                from_offset_m=s["from_offset_m"], to_offset_m=s["to_offset_m"]) for s in segments]
    dynamic["incident"] = copy.deepcopy(mine.incident)
    if mine.selected_option:
        dynamic["incident"]["selected_option"] = "option-" + mine.selected_option
    dynamic["journal"] = dict(last_seq=mine.journal_seq, events=mine.events)
    for kind in ("observe", "stop_withdraw_zone", "withdraw_all"):
        state = "offered" if mine.incident["state"] == "active" else "inactive"
        if mine.selected_option == kind:
            state = "done" if mine.incident["state"] == "done" else "executing"
        dynamic["option-" + kind] = dict(state=state, scope=list(mine.zones) if kind == "withdraw_all"
                                        else mine.incident.get("scope", []), **mine.forecasts.get(kind, {}))
        if state == "done":
            dynamic["option-" + kind].update({"actual_" + k: v for k, v in mine.metrics().items()})
    for key, values in dynamic.items():
        twins[key]["features"] = features({**values, **common})
    m = mine.metrics()
    shift = dict(**common, contract_version=1, publication_seq=mine.publication_seq,
        topology_version=TOPOLOGY_VERSION, run_state=mine.run_state, pause_reason=mine.pause_reason,
        speedup=mine.parameters["speedup"], seed=mine.seed, conditions=mine.conditions,
        workers_total=len(mine.workers), workers_out=sum(w["status"] == "out" for w in mine.workers.values()),
        workers_in_danger=m["in_danger"], workers_no_route=m["no_route"], workers_unknown=m["unknown"],
        commands=mine.commands, runs=[f"{NAMESPACE}:{r['id']}" for r in mine.archive],
        scene=[dict(thingId=twins[key]["thingId"], features=twins[key]["features"]) for key in dynamic])
    twins["shift"]["features"] = features(shift)
    for run in mine.archive:
        twins[run["id"]] = dict(thingId=f"{NAMESPACE}:{run['id']}", policyId="default:basic_policy",
                                attributes=dict(kind="run", label=run["id"], synthetic=True,
                                                _parents=f"{NAMESPACE}:mine"),
                                features=features({k: v for k, v in run.items() if k != "id"}))
    return twins


def mqtt_messages(twins):
    """Native Ditto Protocol. This only builds envelopes; it does not send them."""
    for key in [k for k in twins if k != "shift"] + ["shift"]:
        twin = twins[key]
        if "features" not in twin:
            continue
        yield f"telemetry/{NAMESPACE}/{key}", dict(
            topic=f"{NAMESPACE}/{key}/things/twin/commands/modify", path="/features",
            headers={"response-required": False, "content-type": "application/json"},
            value=twin["features"])
