"""Provenance for demonstration settings, never industrial safety setpoints."""

import math

PARAMETERS = {
    "walking_speed_m_s": 1.25,
    "attention_rate_mm_h": 1.0,
    "danger_rate_mm_h": 2.0,
    "baseline_rate_mm_h": 0.2,
    "unstable_rate_mm_h": 2.6,
    "stale_after_s": 15,
    "lost_after_s": 30,
    "forecast_horizon_s": 900,
    "speedup": 10,
}

SOURCES = {
    "escape1983": dict(url="https://stacks.cdc.gov/view/cdc/206706",
        location="Description, average escape speeds", year=1983,
        scope="Underground coal mine experiment, not calibration of a copper mine",
        published_ft_min=[96, 264], converted_m_s=[0.48768, 1.34112]),
    "monitoring2024": dict(url="https://stacks.cdc.gov/view/cdc/155321/cdc_155321_DS1.pdf",
        location="PDF pages 3–4, Roof-to-floor / Multipoint Roof / Borehole Extensometers",
        year=2024, scope="Supports displacement measurement; does not validate our alarm setpoints"),
}


def validate(parameters):
    if set(parameters) != set(PARAMETERS):
        raise ValueError("unknown or missing model parameter")
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in parameters.values()):
        raise ValueError("parameters must be positive finite numbers")
    if not parameters["baseline_rate_mm_h"] < parameters["attention_rate_mm_h"] < parameters["danger_rate_mm_h"] < parameters["unstable_rate_mm_h"]:
        raise ValueError("expected baseline < attention < danger < unstable")
    if parameters["stale_after_s"] >= parameters["lost_after_s"]:
        raise ValueError("stale timeout must precede lost timeout")
    for key in ("stale_after_s", "lost_after_s", "forecast_horizon_s", "speedup"):
        if type(parameters[key]) is not int:
            raise ValueError(key + " must be an integer number of seconds")


def registry(parameters):
    units = dict(walking_speed_m_s="m/s", attention_rate_mm_h="mm/h", danger_rate_mm_h="mm/h",
        baseline_rate_mm_h="mm/h", unstable_rate_mm_h="mm/h", stale_after_s="s",
        lost_after_s="s", forecast_horizon_s="s", speedup="model s/wall s")
    reasons = {
        "walking_speed_m_s": "Uniform free walking; no slope, fatigue or congestion correction",
        "attention_rate_mm_h": "Synthetic warning boundary, not a rock failure criterion",
        "danger_rate_mm_h": "Synthetic blocking boundary, not a rock failure criterion",
        "baseline_rate_mm_h": "Synthetic stable signal below warning boundary",
        "unstable_rate_mm_h": "Synthetic event signal above blocking boundary",
        "stale_after_s": "Demo freshness timeout in model time, not a sensor specification",
        "lost_after_s": "Demo loss timeout in model time, last measurement is retained",
        "forecast_horizon_s": "Comparison window; incomplete exit is not successful evacuation",
        "speedup": "Presentation acceleration, does not change movement per model second",
    }
    entries = {key: dict(value=value, unit=units[key], status="scenario_assumption",
                        rationale=reasons[key], source_ids=[]) for key, value in parameters.items()}
    entries["walking_speed_m_s"].update(status="engineering_assumption",
        source_ids=["escape1983"], sensitivity_values=[0.5, 0.75, 1.0, 1.25],
        transfer="Historical coal-mine results are context only, not a validated range for this mine")
    for key in ("attention_rate_mm_h", "danger_rate_mm_h", "baseline_rate_mm_h", "unstable_rate_mm_h"):
        entries[key]["source_ids"] = ["monitoring2024"]
        entries[key]["transfer"] = "Measurement type only; numerical value chosen by team"
    return dict(version=1, calibrated=False, sources=SOURCES, entries=entries)
