"""Offline reproducible experiment. Does not substitute for platform integration."""

import argparse
import json
from pathlib import Path

from .model import Mine
from .twins import mqtt_messages, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=("p-instability", "p-detour", "p-trapped", "p-sensor"),
                        default="p-instability")
    parser.add_argument("--option", choices=("observe", "stop_withdraw_zone", "withdraw_all"),
                        default="withdraw_all")
    parser.add_argument("--export", type=Path, help="Write Ditto bodies and MQTT envelopes, without sending them")
    args = parser.parse_args()
    mine = Mine()
    mine.command(dict(command_id="c-" + "1" * 32, type="run.start_preset", target=args.preset, run=mine.run))
    mine.advance(1000)
    if mine.incident["state"] != "active":
        raise RuntimeError("preset did not reach a decision checkpoint")
    predictions = mine.forecasts.copy()
    mine.command(dict(command_id="c-" + "2" * 32, type="action.execute_option", target="option-" + args.option,
                      run=mine.run, decision_id=mine.incident["decision_id"]))
    mine.advance(mine.parameters["forecast_horizon_s"])
    report = dict(synthetic=True, platform_verified=False, preset=args.preset, selected=args.option,
                  comparison_key=mine.comparison_key, forecasts=predictions, actual=mine.metrics())
    print(json.dumps(report, indent=2, allow_nan=False))
    if args.export:
        twins = snapshot(mine)
        args.export.parent.mkdir(parents=True, exist_ok=True)
        args.export.write_text(json.dumps(dict(report=report, twins=list(twins.values()),
            mqtt=[dict(topic=t, payload=p) for t, p in mqtt_messages(twins)]),
            ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
