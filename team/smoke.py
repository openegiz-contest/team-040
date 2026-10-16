"""Live integration test. Resets only this team's synthetic run via the public UI API."""

import json
import os
import time
import urllib.request
import uuid

BASE = os.environ.get("TEAM_UI_URL", "http://127.0.0.1:8088").rstrip("/") + "/ditto/api/2/things"


def get(name):
    with urllib.request.urlopen(BASE + "/team040.mine:" + name +
            "?fields=thingId,attributes,features,_modified,_revision", timeout=5) as response:
        data = json.load(response)
        assert response.headers.get("Date"), "platform Date missing"
    return data


def values(twin):
    return {k: v["properties"]["value"] for k, v in twin["features"].items()}


def wait(predicate, seconds=15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = predicate()
        if result:
            return result
        time.sleep(0.5)
    raise AssertionError("Timed out waiting for platform state")


def send(kind, target, *, body=None, **extra):
    if body is None:
        body = dict(command_id="c-" + uuid.uuid4().hex, type=kind, target=target,
                    run=values(get("shift"))["idSimulationRun"], **extra)
    started = time.monotonic()
    request = urllib.request.Request(BASE + "/team040.mine:shift/inbox/messages/command?timeout=0",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 202, response.status

    def acknowledged():
        return next((c for c in values(get("shift"))["commands"] if c["id"] == body["command_id"]), None)

    ack = wait(acknowledged)
    assert ack["status"] == "applied", ack
    print(json.dumps(dict(command=kind, ack_s=round(time.monotonic() - started, 3), reason=ack["reason"])), flush=True)
    return body, ack


def main():
    mine = get("mine")
    assert mine["attributes"]["synthetic"] is True
    body, ack = send("run.start_preset", "p-instability")
    run = ack["new_run"]
    send("run.start_preset", "p-instability", body=body)
    assert values(get("shift"))["idSimulationRun"] == run, "duplicate reset created another run"
    wait(lambda: values(get("shift"))["pause_reason"] == "decision", 20)
    first = values(get("shift"))
    time.sleep(2)
    second_twin = get("shift")
    second = values(second_twin)
    assert second["tick"] == first["tick"] == 60
    assert second["publication_seq"] > first["publication_seq"], "paused heartbeat stopped"
    assert "_modified" in second_twin and "_revision" in second_twin
    assert {t["thingId"] for t in second["scene"]} == set(mine["attributes"]["dynamic_ids"])
    for twin in second["scene"]:
        state = values(twin)
        assert (state["tick"], state["sim_time_s"], state["idSimulationRun"]) == (60, 60, run)
    selected = next(t for t in second["scene"] if t["thingId"].endswith(":option-withdraw_all"))
    prediction = values(selected)
    assert prediction["forecast_all_out"] is True
    send("action.execute_option", "option-withdraw_all", decision_id=prediction["decision_id"])
    wait(lambda: values(get("shift"))["workers_out"] == mine["attributes"]["counts"]["worker"], 110)
    wait(lambda: values(get("shift"))["run_state"] == "paused", 20)
    archive = values(get(run))
    assert archive["completion_reason"] == "horizon"
    assert archive["all_out"] is True
    assert archive["last_out_s"] == prediction["forecast_last_out_s"]
    assert archive["danger_exposure_person_s"] == prediction["forecast_danger_exposure_person_s"]
    for key in ("hauled_t", "planned_t", "production_lost_t", "machines_in_danger", "machines_unknown",
                "machines_stuck", "conflicts", "conflict_yield_s"):
        assert archive[key] == prediction["forecast_"+key], key
    assert len(second["scene"]) == 33
    equipment = get("lhd-a")
    assert equipment["attributes"]["kind"] == "equipment"
    assert values(equipment)["idSimulationRun"] == run
    print(json.dumps(dict(result="PASS", run=run, last_out_s=archive["last_out_s"],
                          danger_exposure_person_s=archive["danger_exposure_person_s"],
                          production_lost_t=archive["production_lost_t"], conflicts=archive["conflicts"])), flush=True)


if __name__ == "__main__":
    main()
