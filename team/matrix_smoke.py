"""Run all twelve scenarios through Ditto on an explicitly selected disposable stand.

python -m team.matrix_smoke --url http://127.0.0.1:18088 --allow-reset --output report.json
This changes the selected stand's synthetic run. It never defaults to the live UI.
"""
import argparse
import json
import os
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--allow-reset", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ["TEAM_UI_URL"] = args.url
    from team.smoke import get, send, values, wait

    reference = json.loads(Path(__file__).with_name("research").joinpath("comparison.json").read_text(encoding="utf-8"))
    report = {"model_version": reference["model_version"], "synthetic": True,
              "transport": "HTTP proxy -> Ditto live -> MQTT -> simulator -> MQTT -> Ditto -> HTTP",
              "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rows": []}

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def shift():
        return values(get("shift"))

    manifest = get("mine")["attributes"]
    assert manifest["counts"]["worker"] == 8
    for scenario in reference["scenarios"]:
        for expected in scenario["rows"]:
            started = time.monotonic()
            preset, option = scenario["preset"], expected["option"]
            print(f"START {preset} {option}", flush=True)
            body, ack = send("run.start_preset", preset)
            run = ack["new_run"]
            send("run.start_preset", preset, body=body)
            wait(lambda: shift()["idSimulationRun"] == run and shift()["pause_reason"] == "decision", 60)
            checkpoint = shift()
            assert checkpoint["tick"] == scenario["decision_tick"]
            assert len(checkpoint["scene"]) == 33
            for twin in checkpoint["scene"]:
                state = values(twin)
                assert (state["idSimulationRun"], state["tick"]) == (run, checkpoint["tick"])
            forecast = values(next(t for t in checkpoint["scene"] if t["thingId"].endswith(":option-" + option)))
            time.sleep(2)
            fresh = shift()
            assert fresh["tick"] == checkpoint["tick"] and fresh["publication_seq"] > checkpoint["publication_seq"]
            send("action.execute_option", "option-" + option, decision_id=forecast["decision_id"])
            wait(lambda: shift()["idSimulationRun"] == run and shift()["tick"] >= expected["finished_at_sim_s"]
                 and shift()["run_state"] == "paused", 240)
            actual = values(get(run))
            assert actual["completion_reason"] == "horizon"
            for key, value in expected["actual"].items():
                assert actual.get(key) == value, (preset, option, key, actual.get(key), value)
                if "forecast_" + key in forecast:
                    assert forecast["forecast_" + key] == value, (preset, option, key, "forecast mismatch")
            if "last_out_s" not in expected["actual"]:
                assert "last_out_s" not in actual and "forecast_last_out_s" not in forecast
            report["rows"].append({"preset": preset, "option": option, "run": run,
                                   "actual": {k: actual[k] for k in expected["actual"]},
                                   "forecast_matches_actual": True, "matches_offline": True,
                                   "elapsed_wall_s": round(time.monotonic() - started, 2)})
            save()
            print(f"PASS {preset} {option} ({len(report['rows'])}/12)", flush=True)
    before = shift()["idSimulationRun"]
    body, ack = send("run.reset", "run")
    send("run.reset", "run", body=body)
    assert shift()["idSimulationRun"] == ack["new_run"] != before
    report["ui_reset_and_replay"] = True
    report["result"] = "PASS"
    save()
    print("PASS: all 12 live executions and UI reset/replay", flush=True)


if __name__ == "__main__":
    main()
