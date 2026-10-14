"""Live no-route and stale-danger checks; leaves an instability decision ready to inspect."""

import json
from team.smoke import get, send, values, wait


def scene():
    return {t["thingId"].split(":", 1)[1]: values(t) for t in values(get("shift"))["scene"]}


def preset(name):
    _, ack = send("run.start_preset", name)
    wait(lambda: values(get("shift"))["idSimulationRun"] == ack["new_run"] and
         values(get("shift"))["pause_reason"] == "decision", 20)


def main():
    preset("p-trapped")
    state = scene()
    assert values(get("shift"))["workers_no_route"] == 3
    assert state["worker-a1"]["egress_reason"] == "current_working_closed"
    forecast = state["option-withdraw_all"]
    assert forecast["forecast_all_out"] is False
    assert "forecast_last_out_s" not in forecast
    original_offset = state["worker-a1"]["offset_m"]
    send("action.execute_option", "option-withdraw_all", decision_id=forecast["decision_id"])
    wait(lambda: values(get("shift"))["tick"] >= 90)
    assert scene()["worker-a1"]["offset_m"] == original_offset

    preset("p-instability")
    send("condition.sensor_lost", "sens-ext-a")
    state = scene()
    measured = state["sens-ext-a"]["measured_at_sim_s"]
    send("action.execute_option", "option-observe", decision_id=state["option-observe"]["decision_id"])
    wait(lambda: scene()["sens-ext-a"]["quality"] == "lost", 15)
    state = scene()
    assert state["zone-a"]["hazard_state"] == "unknown"
    assert state["zone-a"]["last_known_hazard_state"] == "danger"
    assert state["zone-a"]["routing_restriction"] == "blocked"
    assert state["sens-ext-a"]["measured_at_sim_s"] == measured
    preset("p-instability")
    print(json.dumps(dict(result="PASS", trapped_worker_did_not_move=True,
                          no_false_all_out=True, lost_sensor_kept_last_danger=True,
                          final_state="paused instability decision")), flush=True)


if __name__ == "__main__":
    main()
