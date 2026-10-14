"""Reproducible 4 x 3 offline comparison from shared decision checkpoints."""

import argparse
import copy
import json
from pathlib import Path

from .model import Mine, fingerprint
from .topology import MODEL_VERSION, TOPOLOGY_VERSION

OPTIONS = ("observe", "stop_withdraw_zone", "withdraw_all")
LABELS = {"observe": "Наблюдать", "stop_withdraw_zone": "Вывести затронутые участки",
          "withdraw_all": "Вывести всех"}
SCENARIOS = {"p-instability": "Нестабильность", "p-detour": "Закрыт основной проход",
             "p-trapped": "Закрыт выход с участка", "p-sensor": "Потерян датчик"}


def apply(mine, kind, target, number, **extra):
    ack = mine.command(dict(command_id=f"c-{number:032x}", type=kind, target=target,
                            run=mine.run, **extra))
    if ack["status"] != "applied":
        raise AssertionError(ack)


def experiment():
    scenarios = []
    for preset, label in SCENARIOS.items():
        checkpoint = Mine()
        initial_routes = {k: {f: copy.deepcopy(w.get(f)) for f in
                          ("route", "egress_exit", "egress_length_m")} for k, w in checkpoint.workers.items()}
        apply(checkpoint, "run.start_preset", preset, 1)
        checkpoint.advance(1000)
        if checkpoint.pause_reason != "decision":
            raise AssertionError("No decision checkpoint: " + preset)
        unchanged = fingerprint(checkpoint.__dict__)
        horizon = checkpoint.parameters["forecast_horizon_s"]
        rows = []
        for number, option in enumerate(OPTIONS, 2):
            trial = copy.deepcopy(checkpoint)
            target_zones = [] if option == "observe" else (sorted(trial.zones)
                           if option == "withdraw_all" else trial.incident["scope"][:])
            targeted = [k for k in trial.cohort if trial.attributes[k]["home_zone"] in target_zones]
            baseline = trial.metrics()
            peak = {key: baseline[key] for key in ("in_danger", "unknown", "no_route")}
            target_out_s = None
            apply(trial, "action.execute_option", "option-" + option, number,
                  decision_id=trial.incident["decision_id"])
            for elapsed in range(1, horizon + 1):
                trial.advance(1)
                metrics = trial.metrics()
                for key in peak:
                    peak[key] = max(peak[key], metrics[key])
                if targeted and target_out_s is None and all(trial.workers[k]["status"] == "out" for k in targeted):
                    target_out_s = elapsed
            actual = trial.metrics()
            prediction = checkpoint.forecasts[option]
            predicted_metrics = {k.removeprefix("forecast_"): v for k, v in prediction.items()
                                 if k.removeprefix("forecast_") in set(actual) | {"last_out_s"}}
            if predicted_metrics != actual:
                raise AssertionError((preset, option, predicted_metrics, actual))
            if not trial.comparable or trial.comparison_key != checkpoint.comparison_key:
                raise AssertionError("Comparison inputs changed")
            if not trial.archived_current or trial.archive[-1]["completion_reason"] != "horizon":
                raise AssertionError("Incomplete execution")
            rows.append(dict(option=option, label=LABELS[option], target_zones=target_zones,
                targeted_workers=len(targeted), target_out_s=target_out_s,
                actual=actual, peak=peak, downtime_since_decision_zone_s=actual["downtime_s"] - baseline["downtime_s"],
                forecast=prediction, forecast_matches_actual=True,
                comparison_key=trial.comparison_key, finished_at_sim_s=trial.tick,
                zones={k: {f: z[f] for f in ("work_state", "withdrawal_state", "production_rate", "downtime_s")}
                       for k, z in trial.zones.items()},
                workers={k: {f: w[f] for f in ("status", "at_exit", "at_working", "offset_m", "egress_status", "egress_reason") if f in w}
                         for k, w in trial.workers.items()}))
        if fingerprint(checkpoint.__dict__) != unchanged:
            raise AssertionError("Trial mutated shared checkpoint")
        scenarios.append(dict(preset=preset, label=label, decision_tick=checkpoint.tick,
            event_tick=next(p["at_s"] for p in checkpoint.attributes["mine"]["presets"] if p["id"] == preset),
            scope=checkpoint.incident["scope"], causes=checkpoint.incident["causes"],
            cohort=checkpoint.cohort, checkpoint_hash=unchanged, comparison_key=checkpoint.comparison_key,
            initial_routes=initial_routes,
            decision_routes={k: {f: copy.deepcopy(w.get(f)) for f in
                ("route", "egress_exit", "egress_length_m", "egress_status", "egress_reason")} for k, w in checkpoint.workers.items()},
            horizon_s=horizon, rows=rows))
    return dict(schema_version=1, synthetic=True, platform_verified=False,
                model_version=MODEL_VERSION, topology_version=TOPOLOGY_VERSION,
                parameters=checkpoint.parameters, scenarios=scenarios)


def table(report):
    lines = ["| Сценарий | Действие | Вышло / 6 | Выход всех, с | Без пути в конце | Опасность, чел·с | Неопределённость, чел·с | Простой, участок·с |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for scenario in report["scenarios"]:
        for row in scenario["rows"]:
            m = row["actual"]
            lines.append(f"| {scenario['label']} | {row['label']} | {m['out']} | {m.get('last_out_s', '—')} | "
                         f"{m['no_route']} | {m['danger_exposure_person_s']} | {m['unknown_exposure_person_s']} | "
                         f"{row['downtime_since_decision_zone_s']} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Save complete JSON evidence")
    parser.add_argument("--check", type=Path, help="Repeat and compare with saved JSON evidence")
    args = parser.parse_args()
    report = experiment()
    if args.check and json.loads(args.check.read_text(encoding="utf-8")) != report:
        raise SystemExit("FAIL: saved experiment differs from current model")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(table(report))
    print("\nPASS: 12 executions match forecasts; shared checkpoints were not modified. Offline synthetic experiment.")


if __name__ == "__main__":
    main()
