"""One source of geometry for routing and Ditto attributes.

Every number here is a demonstration assumption, not a surveyed mine or a
geotechnical safety limit. See README.md before interpreting model outputs.
"""

from collections import Counter
from math import dist

NAMESPACE = "team040.mine"
MODEL_VERSION = "0.1"
TOPOLOGY_VERSION = "t1"
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


def build_attributes():
    nodes = {
        "surface-a": (0, 0, 0, "surface", "exit"),
        "surface-b": (420, 180, 0, "surface", "exit"),
        "a": (0, 0, -120, "level-120", "junction"),
        "b": (150, 0, -120, "level-120", "junction"),
        "c": (300, 0, -120, "level-120", "junction"),
        "d": (150, 160, -120, "level-120", "junction"),
        "face-a": (150, -80, -120, "level-120", "dead_end"),
        "e": (0, 0, -240, "level-240", "junction"),
        "f": (150, 0, -240, "level-240", "junction"),
        "g": (300, 0, -240, "level-240", "junction"),
        "face-b": (150, -80, -240, "level-240", "dead_end"),
    }
    attributes = {}

    def add(key, kind, label, parent="mine", **fields):
        attributes[key] = dict(kind=kind, label=label, synthetic=True,
                               _parents=f"{NAMESPACE}:{parent}", **fields)

    for level, elevation, order in [("surface", 0, 0), ("level-120", -120, 1),
                                     ("level-240", -240, 2)]:
        add(level, "level", f"Горизонт {elevation} м", elevation_m=elevation, order=order)
    # No shaft transport is modelled: both surface connections are walkable ramps.
    edges = [
        ("w-01", "a", "surface-a", "ramp", None),
        ("w-02", "c", "surface-b", "ramp", None),
        ("w-03", "a", "b", "drift", None),
        ("w-04", "b", "c", "drift", None),
        ("w-05", "a", "d", "crosscut", None),
        ("w-06", "d", "c", "crosscut", None),
        ("w-07", "b", "face-a", "drift", "zone-a"),
        ("w-08", "a", "e", "ramp", None),
        ("w-09", "c", "g", "ramp", None),
        ("w-10", "e", "f", "drift", None),
        ("w-11", "f", "g", "drift", None),
        ("w-12", "f", "face-b", "drift", "zone-b"),
    ]
    # Ramp polylines add horizontal travel; edge lengths equal polyline lengths.
    bends = {
        "w-01": [[-240, 0, -60]], "w-02": [[540, 0, -60]],
        "w-08": [[-180, 0, -180]], "w-09": [[480, 0, -180]],
    }
    for key, start, end, kind, zone in edges:
        points = bends.get(key, [])
        polyline = [nodes[start][:3], *points, nodes[end][:3]]
        length = sum(dist(p, q) for p, q in zip(polyline, polyline[1:]))
        add(key, "working", "В-" + key[2:], parent=nodes[start][3],
            **{"from": start, "to": end}, length_m=length, working_kind=kind,
            points=points, level=nodes[start][3], **({"zone": zone} if zone else {}))
    for suffix, level, edge in [("a", "level-120", "w-07"), ("b", "level-240", "w-12")]:
        zone, sensor = f"zone-{suffix}", f"sens-ext-{suffix}"
        add(zone, "zone", f"Участок {suffix.upper()}", parent=level,
            level=level, workings=[edge], sensors=[sensor], nominal_production_t_h=30,
            required_workers=3)
        add(sensor, "sensor", f"Э-{suffix.upper()}", parent=zone, zone=zone,
            sensor_kind="extensometer", working=edge, offset_m=40,
            stale_after_s=PARAMETERS["stale_after_s"], lost_after_s=PARAMETERS["lost_after_s"])
        for number in range(1, 4):
            key = f"worker-{suffix}{number}"
            add(key, "worker", f"Р-{suffix.upper()}{number}", parent=zone,
                home_zone=zone, initial_working=edge, initial_offset_m=20 * number)
    for suffix in "ab":
        add(f"exit-{suffix}", "exit", f"Выход {suffix.upper()}",
            exit_kind="ramp", node=f"surface-{suffix}")
    add("shift", "shift", "Смена", tick_wall_ms=1000, contract_version=1)
    add("incident", "incident", "Инцидент")
    add("journal", "journal", "Журнал")
    for kind in ("observe", "stop_withdraw_zone", "withdraw_all"):
        add("option-" + kind, "option", kind, option_kind=kind)
    attributes["mine"] = dict(
        kind="mine", label="Условный подземный рудник", synthetic=True,
        crs="local", units="m", contract_version=1, topology_version=TOPOLOGY_VERSION,
        nodes={key: dict(zip(("x", "y", "z", "level", "node_kind"), row))
               for key, row in nodes.items()},
        thresholds={"attention_rate": {"value": 1.0, "unit": "mm/h"},
                    "danger_rate": {"value": 2.0, "unit": "mm/h"}},
        presets=[
            dict(id="p-instability", label="Рост нестабильности", at_s=60,
                 type="condition.instability_on", target="zone-a"),
            dict(id="p-detour", label="Перекрытие основного прохода", at_s=60,
                 type="condition.close_working", target="w-04"),
            dict(id="p-trapped", label="Перекрытие выхода с участка", at_s=60,
                 type="condition.close_working", target="w-07"),
            dict(id="p-sensor", label="Потеря датчика", at_s=60,
                 type="condition.sensor_lost", target="sens-ext-a"),
        ],
    )
    attributes["mine"]["counts"] = dict(Counter(a["kind"] for a in attributes.values()))
    attributes["mine"]["manifest"] = [f"{NAMESPACE}:{key}" for key in attributes]
    attributes["mine"]["dynamic_ids"] = [f"{NAMESPACE}:{key}" for key, a in attributes.items()
                                            if a["kind"] not in ("mine", "level", "shift")]
    return attributes
