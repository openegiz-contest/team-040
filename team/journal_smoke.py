"""Real Ditto journal proof. Changes only synthetic team runs; leaves a decision ready."""

import json
import time

from .smoke import get, values, wait, send


def events():
    shift = values(get("shift"))
    journal = next(t for t in shift["scene"] if t["thingId"].endswith(":journal"))
    return [e for e in values(journal)["events"] if e["run"] == shift["idSimulationRun"]]


def main():
    registry = get("mine")["attributes"]["parameter_registry"]
    assert registry["calibrated"] is False
    assert registry["entries"]["walking_speed_m_s"]["value"] == 1.25
    send("run.start_preset", "p-trapped")
    wait(lambda: values(get("shift"))["pause_reason"] == "decision", 25)
    lost = [e for e in events() if e["code"] == "route.changed"]
    assert len(lost) == 3 and all(e["details"]["after"]["egress_status"] == "none" for e in lost)
    body, _ = send("condition.open_working", "w-07")
    restored = wait(lambda: [e for e in events() if e["code"] == "route.changed" and e["command_id"] == body["command_id"]])
    assert len(restored) == 3 and all(e["details"]["after"]["egress_status"] == "ok" for e in restored)
    seq = events()[-1]["seq"]
    send("condition.open_working", "w-07", body=body)
    assert events()[-1]["seq"] == seq, "duplicate command repeated events"

    send("run.start_preset", "p-instability")
    wait(lambda: values(get("shift"))["pause_reason"] == "decision", 25)
    hazard = next(e for e in events() if e["code"] == "hazard.transition")
    assert hazard["details"]["reason_value"] == 2.6 and hazard["details"]["reason_threshold"] == 2
    assert not any(e["code"] == "worker.exited" for e in events()), "forecast leaked into actual journal"
    incident = values(get("incident"))
    send("action.execute_option", "option-observe", decision_id=incident["decision_id"])
    send("condition.sensor_lost", "sens-ext-a")
    wait(lambda: any(e["code"] == "hazard.transition" and e["details"].get("reason_code") == "sensor_lost" for e in events()))
    evidence = next(e for e in reversed(events()) if e["code"] == "hazard.transition")
    assert evidence["details"]["after"]["routing_restriction"] == "blocked"
    assert evidence["details"]["last_known_hazard_state"] == "danger"
    send("run.start_preset", "p-instability")
    wait(lambda: values(get("shift"))["pause_reason"] == "decision", 25)
    before = events()
    time.sleep(2)
    assert events() == before, "paused heartbeat created journal entries"
    print(json.dumps(dict(result="PASS", real_ditto=True, registry=True, closure_and_recovery=True,
        command_dedup=True, last_danger_evidence=True, forecast_isolation=True, paused_journal_stable=True)))


if __name__ == "__main__":
    main()
