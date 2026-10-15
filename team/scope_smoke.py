"""Live closure scope/command check; leaves a local-detour decision ready."""

import json

from .smoke import get, values, wait, send


def scene():
    shift = values(get("shift"))
    return shift, {t["thingId"].split(":", 1)[1]: values(t) for t in shift["scene"]}


def decision(preset):
    send("run.start_preset", preset)
    wait(lambda: values(get("shift"))["pause_reason"] == "decision", 25)
    shift, state = scene()
    assert state["incident"]["scope"] == ["zone-a"]
    assert state["incident"]["scope_policy_version"] == 2
    assert set(state["incident"]["scope_reasons"]) == {"zone-a"}
    assert state["option-stop_withdraw_zone"]["scope"] == ["zone-a"]
    assert state["option-withdraw_all"]["scope"] == ["zone-a", "zone-b"]
    return shift, state


def main():
    _, state = decision("p-detour")
    assert state["option-stop_withdraw_zone"]["forecast_out"] == 3
    assert state["option-stop_withdraw_zone"]["forecast_downtime_s"] == 900
    initial_b = {k: (w["at_working"], w["offset_m"]) for k, w in state.items() if k.startswith("worker-b")}
    send("action.execute_option", "option-stop_withdraw_zone", decision_id=state["incident"]["decision_id"])
    wait(lambda: values(get("shift"))["workers_out"] == 3, 80)
    _, state = scene()
    assert state["zone-a"]["withdrawal_state"] == "done"
    assert state["zone-b"]["work_state"] == "working" and state["zone-b"]["production_rate"] == 30
    for k, position in initial_b.items():
        assert state[k]["status"] == "working"
        assert (state[k]["at_working"], state[k]["offset_m"]) == position

    _, state = decision("p-trapped")
    assert state["option-stop_withdraw_zone"]["forecast_out"] == 0
    assert state["option-withdraw_all"]["forecast_out"] == 3
    send("action.execute_option", "option-stop_withdraw_zone", decision_id=state["incident"]["decision_id"])
    wait(lambda: values(get("shift"))["tick"] >= 90)
    shift, state = scene()
    assert shift["workers_out"] == 0 and shift["workers_no_route"] == 3
    assert state["zone-a"]["work_state"] == "stopped"
    assert state["zone-b"]["work_state"] == "working" and state["zone-b"]["production_rate"] == 30
    for number in range(1, 4):
        worker = state[f"worker-a{number}"]
        assert worker["status"] == "waiting" and worker["offset_m"] == 20 * number
    decision("p-detour")
    print(json.dumps(dict(result="PASS", real_ditto=True, local_detour_out=3,
        local_trapped_out=0, unaffected_zone_kept_working=True, scope_reasons=True)))


if __name__ == "__main__":
    main()
