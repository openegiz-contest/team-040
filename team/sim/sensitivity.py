"""Offline one-factor sensitivity; does not claim uncertainty bounds or field validation."""

import json

from .model import Mine, SCOPE_POLICY_VERSION
from .topology import MODEL_VERSION


def experiment():
    rows = []
    for speed in (0.5, 0.75, 1.0, 1.25):
        mine = Mine({"walking_speed_m_s": speed})
        mine.command(dict(command_id="c-" + "1" * 32, type="run.start_preset",
                          target="p-instability", run=mine.run))
        mine.advance(60)
        predictions = mine.forecasts.copy()
        mine.command(dict(command_id="c-" + "2" * 32, type="action.execute_option",
            target="option-withdraw_all", run=mine.run, decision_id=mine.incident["decision_id"]))
        mine.advance(mine.parameters["forecast_horizon_s"])
        actual = mine.metrics()
        predicted = predictions["withdraw_all"]
        assert all(predicted["forecast_" + key] == value for key, value in actual.items())
        rows.append(dict(walking_speed_m_s=speed, comparison_key=mine.comparison_key,
                         forecast_horizon_s=mine.parameters["forecast_horizon_s"],
                         forecasts=predictions, actual_withdraw_all=actual))
    return dict(synthetic=True, platform_verified=False, model_version=MODEL_VERSION,
                scope_policy_version=SCOPE_POLICY_VERSION,
                scenario="p-instability", one_factor="walking_speed_m_s", results=rows)


if __name__ == "__main__":
    print(json.dumps(experiment(), ensure_ascii=False, indent=2, allow_nan=False))
