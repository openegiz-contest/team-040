#!/usr/bin/env python3
"""Generator of the contract fixtures for the dispatcher UI tests.

ALL NUMBERS HERE ARE INVENTED FOR TESTS. The mine below does not exist, its
geometry, sensor readings, speeds, forecasts and timings are test data and are
NOT measurements of the stand and NOT output of the team's simulation service.

One base test mine is defined once (class ``Mine``). Every scenario is derived
from it by explicit modifications scripted in this file. To keep the frames
self-consistent (route lengths, counters, forecasts equal to the scripted
outcome) the generator contains a small scripted stepper (class ``Sim``); it
exists only to write fixtures and is not the contract's model. The mock server
replays the frames written here and contains no mine logic at all.

Usage:
    python team/ui/tools/build_fixtures.py            # rewrite team/ui/fixtures/*.json
    python team/ui/tools/build_fixtures.py --out DIR  # write somewhere else
    python team/ui/tools/build_fixtures.py --check    # exit 1 if committed files differ

The output is deterministic: no clock, no randomness, sorted keys, LF endings.
Standard library only.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import heapq
import json
import math
import sys
from pathlib import Path

NS = "team040.mine"
CONTRACT_VERSION = 1
NOTICE = ("Контрактная фикстура для тестов UI. Числа придуманы для тестов "
          "и не являются измерениями стенда.")

SPEED_M_S = 1.25      # invented walking speed of the test stepper
TICK_STEP = 10        # model seconds (= ticks) per publication at speed x10
STEP_M = SPEED_M_S * TICK_STEP
HORIZON_S = 900       # forecast horizon, demonstration parameter
SEED = 42
BASE_TICK = 1200      # nominal tick of the first frame of a running fixture
PRESET_AT_S = 60      # model second at which a preset applies its condition
FIRST_SEQ = 48211     # nominal publication_seq of the first publication
FIRST_REVISION = 52140

SCENARIOS = [
    "normal", "detour", "no_path", "sensor_lost_after_danger", "paused_heartbeat",
    "frozen_seq", "frozen_seq_old", "invalid_missing_id", "invalid_duplicate_id",
    "invalid_mixed_tick", "invalid_missing_field", "invalid_contract_version",
    "invalid_no_metadata", "topology_mismatch", "topology_change", "commands",
    "reset", "withdrawal_incomplete", "no_forecast", "partial_forecast",
    "route_segments", "unknown_enum", "empty",
]

OPTIONS = {
    "option-observe": "observe",
    "option-stop-withdraw": "stop_withdraw_zone",
    "option-withdraw-all": "withdraw_all",
}
OPTION_SHORT = {"option-observe": "observe", "option-stop-withdraw": "sw",
                "option-withdraw-all": "wa"}

# How the mock server re-times a frame (see fixtures/README.md, "Время").
CLOCK = {
    "tick_step": TICK_STEP,
    "follow_fields": ["index_at_tick", "measured_at_sim_s", "measured_at_tick"],
    "event_fields": ["forecast_tick", "last_known_hazard_tick", "opened_at_tick"],
    "record_lists": {"causes": ["tick"], "commands": ["sim_time_s", "tick"],
                     "events": ["sim_time_s", "tick"]},
}


def tid(local: str) -> str:
    return f"{NS}:{local}"


def F(value, unit: str | None = None) -> dict:
    """A Ditto feature: {"properties": {"value": ..., "unit": ...}}."""
    props = {"value": value}
    if unit is not None:
        props["unit"] = unit
    return {"properties": props}


def num(x: float):
    """Integers stay integers, other numbers keep one decimal."""
    r = round(float(x), 1)
    return int(r) if r == int(r) else r


def eta_s(length_m: float) -> int:
    return int(length_m / SPEED_M_S + 0.5)


def cid(label: str) -> str:
    """A literal command id for history that was 'sent' before the fixture starts."""
    return "c-" + hashlib.sha1(("command:" + label).encode()).hexdigest()[:32]


def ckey(label: str) -> str:
    return "ck-" + hashlib.sha1(("comparison:" + label).encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# The base test mine (invented)
# ---------------------------------------------------------------------------

class Mine:
    """Static description: levels, nodes, workings, zones, sensors, workers, exits."""

    LEVELS = [("level-260", -260, 1), ("level-320", -320, 2), ("level-380", -380, 3)]

    def __init__(self, topology: str = "t1"):
        self.topology = topology
        elev = {name: z for name, z, _ in self.LEVELS}
        self.nodes: dict[str, dict] = {}
        self.workings: dict[str, dict] = {}

        def node(i, level, x, y, kind="junction"):
            self.nodes[f"n-{i:02d}"] = {"x": x, "y": y, "z": elev[level],
                                        "level": level, "node_kind": kind}

        def working(i, a, b, kind, zone=None, points=None):
            a, b = f"n-{a:02d}", f"n-{b:02d}"
            # an inter-level working is filed under the level of its lower end
            lower = min((a, b), key=lambda n: self.nodes[n]["z"])
            self.workings[f"w-{i:02d}"] = {
                "from": a, "to": b, "working_kind": kind, "zone": zone,
                "level": self.nodes[lower]["level"], "points": points or []}

        # level -260: the three exits and zone A
        node(1, "level-260", 80, 120, "exit")      # shaft station
        node(2, "level-260", 200, 120)
        node(3, "level-260", 200, 220, "exit")     # top of the escape raise
        node(4, "level-260", 320, 120)
        node(5, "level-260", 460, 120)
        node(6, "level-260", 584, 120, "exit")     # ramp portal
        node(7, "level-260", 320, 20)
        node(8, "level-260", 460, 20)
        node(9, "level-260", 220, 20, "dead_end")
        node(10, "level-260", 560, 20, "dead_end")
        # level -320: zone B between the shaft (west, through w-12) and the ramp (east)
        node(11, "level-320", 80, 120)
        node(12, "level-320", 180, 120)
        node(13, "level-320", 300, 120)
        node(14, "level-320", 300, 220)
        node(15, "level-320", 440, 220)
        node(16, "level-320", 440, 120)
        node(17, "level-320", 584, 120)
        node(18, "level-320", 540, 220, "dead_end")
        node(19, "level-320", 180, 10 if topology == "t2" else 30, "dead_end")
        # level -380: zone D on the north side, dead-end zone C behind w-07
        node(20, "level-380", 80, 120)
        node(21, "level-380", 200, 120)
        node(22, "level-380", 340, 120)
        node(23, "level-380", 460, 120)
        node(24, "level-380", 584, 120)
        node(25, "level-380", 460, 30)
        node(26, "level-380", 340, 30)
        node(27, "level-380", 250, 30, "dead_end")
        node(28, "level-380", 200, 220)            # bottom of the escape raise
        node(29, "level-380", 340, 220)
        node(30, "level-380", 440, 220, "dead_end")
        node(31, "level-380", 80, 220, "dead_end")
        if topology == "t2":
            node(32, "level-320", 440, 30, "dead_end")

        # between levels
        working(1, 11, 1, "shaft")
        working(2, 20, 11, "shaft")
        working(3, 17, 6, "ramp", points=self._helix(584, 120, -320, -260))
        working(4, 24, 17, "ramp", points=self._helix(584, 120, -380, -320))
        working(5, 28, 3, "raise")
        # level -380
        working(6, 20, 21, "drift")
        working(7, 23, 25, "crosscut")
        working(8, 21, 22, "drift")
        working(9, 22, 23, "drift")
        working(10, 23, 24, "drift")
        # level -320
        working(11, 11, 12, "drift")
        working(12, 12, 13, "drift")
        working(13, 13, 14, "crosscut", "zone-b")
        working(14, 14, 15, "drift", "zone-b")
        working(15, 15, 16, "crosscut", "zone-b")
        working(16, 13, 16, "drift", "zone-b", points=[[370, 100, -320]])
        working(17, 15, 18, "drift", "zone-b")
        working(18, 16, 17, "drift")
        working(19, 12, 19, "crosscut")
        # level -380 again: zone C and zone D
        working(20, 25, 26, "drift", "zone-c")
        working(21, 26, 27, "drift", "zone-c")
        working(22, 21, 28, "crosscut")
        working(23, 28, 29, "drift", "zone-d", points=[[270, 240, -380]])
        working(24, 22, 29, "crosscut", "zone-d")
        working(25, 29, 30, "drift", "zone-d")
        working(26, 20, 31, "crosscut")
        # level -260
        working(27, 1, 2, "drift")
        working(28, 2, 3, "crosscut")
        working(29, 2, 4, "drift")
        working(30, 4, 5, "drift")
        working(31, 5, 6, "drift")
        working(32, 4, 7, "crosscut", "zone-a")
        working(33, 7, 8, "drift", "zone-a")
        working(34, 8, 5, "crosscut", "zone-a")
        working(35, 7, 9, "drift", "zone-a")
        working(36, 8, 10, "drift", "zone-a")
        if topology == "t2":
            working(37, 16, 32, "crosscut")

        for w in self.workings.values():
            w["length_m"] = int(round(self.polyline_length(w)))

        self.zones = {
            "zone-a": {"label": "Участок А", "level": "level-260", "rate": 42.0, "index": 0.12},
            "zone-b": {"label": "Участок Б", "level": "level-320", "rate": 55.0, "index": 0.18},
            "zone-c": {"label": "Участок В", "level": "level-380", "rate": 38.0, "index": 0.21},
            "zone-d": {"label": "Участок Г", "level": "level-380", "rate": 47.5, "index": 0.46},
        }
        # id: (kind, working, offset_m, zone, value_mm, rate_mm_h, events)
        self.sensors = {
            "sens-ext-01": ("extensometer", "w-33", 40.0, "zone-a", 2.1, 0.2, None),
            "sens-ext-02": ("extensometer", "w-14", 70.0, "zone-b", 3.4, 0.4, None),
            "sens-ext-03": ("extensometer", "w-16", 60.0, "zone-b", 2.8, 0.3, None),
            "sens-ext-04": ("extensometer", "w-23", 80.0, "zone-d", 6.7, 1.3, None),
            "sens-ext-05": ("extensometer", "w-21", 18.0, "zone-c", 4.2, 0.3, None),
            "sens-conv-01": ("convergence", "w-32", 50.0, "zone-a", 5.5, 0.1, None),
            "sens-conv-02": ("convergence", "w-15", 40.0, "zone-b", 7.2, 0.2, None),
            "sens-conv-03": ("convergence", "w-25", 30.0, "zone-d", 4.9, 0.4, None),
            "sens-geo-01": ("geophone", "w-36", 20.0, "zone-a", None, None, 2),
            "sens-geo-02": ("geophone", "w-17", 55.0, "zone-b", None, None, 3),
        }
        # id: (home zone, working, offset from the working's "from" node)
        self.workers = {
            "worker-01": ("zone-a", "w-33", 40.0),
            "worker-02": ("zone-a", "w-35", 60.0),
            "worker-03": ("zone-b", "w-14", 32.0),
            "worker-04": ("zone-b", "w-13", 40.0),
            "worker-05": ("zone-b", "w-16", 100.0),
            "worker-06": ("zone-b", "w-17", 40.0),
            "worker-07": ("zone-c", "w-21", 35.0),
            "worker-08": ("zone-c", "w-20", 60.0),
            "worker-09": ("zone-a", "w-34", 30.0),
            "worker-10": ("zone-a", "w-36", 50.0),
            "worker-11": ("zone-d", "w-23", 50.0),
            "worker-12": ("zone-d", "w-25", 70.0),
            "worker-13": ("zone-d", "w-24", 30.0),
            "worker-14": ("zone-d", "w-09", 45.0),
        }
        # id: (kind, node, label)
        self.exits = {
            "exit-shaft": ("shaft", "n-01", "Ствол"),
            "exit-ramp": ("ramp", "n-06", "Съезд"),
            "exit-raise": ("raise", "n-03", "Восстающий"),
        }
        self.exit_nodes = {node_id: ex for ex, (_, node_id, _) in self.exits.items()}
        self._route_cache: dict[frozenset, tuple[dict, dict]] = {}

    @staticmethod
    def _helix(x, y, z0, z1, dx=60.0, dy=88.5):
        """One rectangular turn of a spiral ramp; z grows linearly with the plan distance."""
        corners = [(x + dx, y), (x + dx, y + dy), (x, y + dy)]
        total = 2 * (dx + dy)
        points, run, prev = [], 0.0, (x, y)
        for cx, cy in corners:
            run += math.hypot(cx - prev[0], cy - prev[1])
            prev = (cx, cy)
            points.append([num(cx), num(cy), round(z0 + (z1 - z0) * run / total, 2)])
        return points

    def polyline(self, w: dict) -> list[list[float]]:
        a, b = self.nodes[w["from"]], self.nodes[w["to"]]
        return [[a["x"], a["y"], a["z"]]] + [list(p) for p in w["points"]] + [[b["x"], b["y"], b["z"]]]

    def polyline_length(self, w: dict) -> float:
        pts = self.polyline(w)
        return sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))

    def zone_workings(self, zone: str) -> list[str]:
        return [wid for wid, w in self.workings.items() if w["zone"] == zone]

    def zone_sensors(self, zone: str) -> list[str]:
        return [sid for sid, s in self.sensors.items() if s[3] == zone]

    # --- shortest route to an exit over open workings (fixture consistency only) ---

    def _field(self, closed: frozenset):
        if closed not in self._route_cache:
            adj: dict[str, list] = {n: [] for n in self.nodes}
            for wid in sorted(self.workings):
                if wid in closed:
                    continue
                w = self.workings[wid]
                adj[w["from"]].append((wid, w["to"], w["length_m"]))
                adj[w["to"]].append((wid, w["from"], w["length_m"]))
            dist = {n: 0.0 for n in self.exit_nodes}
            nxt: dict[str, tuple[str, str]] = {}
            heap = [(0.0, n) for n in sorted(self.exit_nodes)]
            heapq.heapify(heap)
            while heap:
                d, n = heapq.heappop(heap)
                if d > dist.get(n, math.inf):
                    continue
                for wid, other, length in adj[n]:
                    if other in self.exit_nodes:
                        continue
                    nd = d + length
                    if nd < dist.get(other, math.inf):
                        dist[other] = nd
                        nxt[other] = (wid, n)
                        heapq.heappush(heap, (nd, other))
            self._route_cache[closed] = (dist, nxt)
        return self._route_cache[closed]

    def route(self, at: str, offset: float, closed=()):
        """Returns (route, reason). route = {"segments": [(working, from, to)], "length", "exit"}."""
        closed = frozenset(closed)
        if at in closed:
            return None, "current_working_closed"
        dist, nxt = self._field(closed)
        w = self.workings[at]
        candidates = []
        for rank, (cost, node, other) in enumerate(
                ((offset, w["from"], w["to"]), (w["length_m"] - offset, w["to"], w["from"]))):
            if node in dist:
                candidates.append((cost + dist[node], rank, node, other))
        if not candidates:
            return None, "no_open_path"
        total, _, node, other = min(candidates)
        segments = [(at, other, node)]
        while node not in self.exit_nodes:
            wid, following = nxt[node]
            segments.append((wid, node, following))
            node = following
        return {"segments": segments, "length": total, "exit": self.exit_nodes[node]}, "none"

    # --- attributes -------------------------------------------------------------

    def things(self) -> list[dict]:
        """All static/actual things with attributes, in manifest order."""
        out: list[dict] = []

        def add(local, **attrs):
            out.append({"thingId": tid(local), "attributes": attrs})

        add("mine")
        add("shift", kind="shift", label="Смена", _parents=tid("mine"),
            tick_wall_ms=1000, contract_version=CONTRACT_VERSION)
        for name, z, order in self.LEVELS:
            add(name, kind="level", label=f"Гор. −{-z} м", _parents=tid("mine"),
                elevation_m=z, order=order)
        for wid, w in self.workings.items():
            attrs = {"kind": "working", "label": "В-" + wid[2:], "_parents": tid(w["level"]),
                     "from": w["from"], "to": w["to"], "length_m": w["length_m"],
                     "working_kind": w["working_kind"], "points": w["points"], "level": w["level"]}
            if w["zone"]:
                attrs["zone"] = w["zone"]
            add(wid, **attrs)
        for zid, z in self.zones.items():
            add(zid, kind="zone", label=z["label"], _parents=tid(z["level"]), level=z["level"],
                workings=self.zone_workings(zid), sensors=self.zone_sensors(zid))
        letters = {"extensometer": "Э", "convergence": "К", "geophone": "Г"}
        for sid, (kind, wid, off, zone, _, _, events) in self.sensors.items():
            attrs = {"kind": "sensor", "label": f"{letters[kind]}-{sid[-2:]}", "_parents": tid(zone),
                     "sensor_kind": kind, "working": wid, "offset_m": off, "zone": zone,
                     "stale_after_s": 60, "lost_after_s": 300}
            if events is not None:
                attrs["window_s"] = 600
            add(sid, **attrs)
        for wid, (zone, _, _) in self.workers.items():
            add(wid, kind="worker", label="Р-" + wid[-2:], _parents=tid("mine"), home_zone=zone)
        for eid, (kind, node_id, label) in self.exits.items():
            add(eid, kind="exit", label=label, _parents=tid("level-260"), exit_kind=kind, node=node_id)
        add("incident", kind="incident", label="Инцидент", _parents=tid("shift"))
        for i, (oid, kind) in enumerate(OPTIONS.items(), 1):
            add(oid, kind="option", label=f"Вариант {i}", _parents=tid("incident"), option_kind=kind)
        add("journal", kind="journal", label="Журнал", _parents=tid("shift"))

        manifest = [t["thingId"] for t in out]
        static_kinds = {"mine", "shift", "level"}
        dynamic = [t["thingId"] for t in out[2:] if t["attributes"]["kind"] not in static_kinds]
        counts: dict[str, int] = {"mine": 1}
        for t in out[1:]:
            counts[t["attributes"]["kind"]] = counts.get(t["attributes"]["kind"], 0) + 1
        out[0]["attributes"] = {
            "kind": "mine", "label": "Рудник (условный)", "synthetic": True,
            "crs": "local", "units": "m", "contract_version": CONTRACT_VERSION,
            "topology_version": self.topology, "manifest": manifest, "dynamic_ids": dynamic,
            "nodes": self.nodes, "counts": counts,
            "thresholds": {
                "rate": {"attention": 1.0, "danger": 2.0, "unit": "mm/h"},
                "index": {"attention": 0.4, "danger": 0.7, "unit": "1"},
                "events": {"danger": 12, "unit": "1"},
            },
            "presets": [
                {"id": "p-detour", "label": "Закрыть В-12 на 60-й секунде", "expect": "detour",
                 "schedule": [{"at_sim_s": PRESET_AT_S, "type": "condition.close_working",
                               "target": "w-12"}]},
                {"id": "p-no-path", "label": "Закрыть В-07 на 60-й секунде", "expect": "no_path",
                 "schedule": [{"at_sim_s": PRESET_AT_S, "type": "condition.close_working",
                               "target": "w-07"}]},
            ],
        }
        return out


# ---------------------------------------------------------------------------
# Scripted stepper: writes consistent frames, nothing more
# ---------------------------------------------------------------------------

HAZARD_RANK = {"normal": 0, "attention": 1, "unknown": 2, "danger": 3}
ARCHIVE_BASE = ["run-0001", "run-0002", "run-0003", "run-0004"]


class Sim:
    def __init__(self, mine: Mine, run="run-0005", tick=BASE_TICK, runs=None,
                 events=None, last_seq=211):
        self.mine = mine
        self.run = run
        self.tick = tick
        self.runs = list(ARCHIVE_BASE if runs is None else runs)
        self.run_state, self.pause_reason = "running", "none"
        self.topology_version = mine.topology
        self.route_form = "names"
        self.closed: dict[str, str] = {}
        self.conditions: list[str] = []
        self.commands: list[dict] = []
        self.zones = {}
        for zid, z in mine.zones.items():
            self.zones[zid] = {
                "work_state": "working", "withdrawal_state": "none", "downtime_s": 0,
                "production_rate": z["rate"],
                "hazard": {"hazard_state": "normal", "data_quality": "fresh",
                           "instability_index": z["index"], "reason_code": "none",
                           "routing_restriction": "allowed"}}
        self.zones["zone-d"]["hazard"].update(
            hazard_state="attention", reason_code="rate_above_attention",
            reason_sensor="sens-ext-04", reason_value=1.3, reason_threshold=1.0,
            reason_unit="mm/h")
        self.sensors = {}
        for sid, (_, _, _, _, value, rate, events_count) in mine.sensors.items():
            s = {"link_state": "online", "quality": "fresh"}
            if value is not None:
                s["value"], s["rate"] = value, rate
            if events_count is not None:
                s["events_count"] = events_count
            self.sensors[sid] = s
        self.workers = {wid: {"status": "working", "at": at, "offset": off}
                        for wid, (_, at, off) in mine.workers.items()}
        self.exits = {eid: {"state": "available", "workers_out": 0} for eid in mine.exits}
        self.incident: dict = {"state": "none"}
        self.option_state = {oid: "inactive" for oid in OPTIONS}
        self.decision: dict | None = None
        self.decision_n = 0
        self.actual: dict[str, dict] = {}
        self.executing: str | None = None
        self.danger_exposure = 0
        self.unknown_exposure = 0
        self.last_out_tick: int | None = None
        self.forecast_quality = "full"
        self.publish_forecast = True
        self.last_seq = last_seq
        if events is None:
            self.events: list[dict] = []
            self.ev("run.started", run, tick=0)
            self.ev("hazard.changed", "zone-d", "attention", tick=0)
        else:
            self.events = [dict(e) for e in events]

    def clone(self) -> "Sim":
        c = Sim.__new__(Sim)
        for key, value in self.__dict__.items():
            c.__dict__[key] = value if key == "mine" else copy.deepcopy(value)
        return c

    def successor(self, run: str, command_id: str | None, preset: str | None = None) -> "Sim":
        """A clean new run that keeps the journal and archives the current run."""
        self.ev("run.reset", self.run, command_id=command_id)
        new = Sim(self.mine, run=run, tick=0, runs=self.runs + [self.run],
                  events=self.events, last_seq=self.last_seq)
        new.ev("run.started", run, arg=("preset:" + preset) if preset else None, tick=0)
        new.ev("hazard.changed", "zone-d", "attention", tick=0)
        return new

    # --- journal ----------------------------------------------------------------

    def ev(self, code, subject, arg=None, command_id=None, tick=None):
        self.last_seq += 1
        t = self.tick if tick is None else tick
        e = {"seq": self.last_seq, "run": self.run, "tick": t, "sim_time_s": t,
             "code": code, "subject": subject}
        if arg is not None:
            e["arg"] = arg
        if command_id is not None:
            e["command_id"] = command_id
        self.events.append(e)

    # --- queries ----------------------------------------------------------------

    def underground(self) -> list[str]:
        return [w for w, st in self.workers.items() if st["status"] != "out"]

    def route_of(self, wid: str, closed=None):
        st = self.workers[wid]
        return self.mine.route(st["at"], st["offset"], self.closed if closed is None else closed)

    def working_hazard(self, working: str) -> dict:
        zone = self.mine.workings[working]["zone"]
        if zone is None:
            # passage without sensors: not assessed, passable by a documented assumption
            return {"hazard_state": "unknown", "data_quality": "none",
                    "reason_code": "no_sensor", "routing_restriction": "allowed"}
        return self.zones[zone]["hazard"]

    def zone_of_worker(self, wid: str) -> str | None:
        return self.mine.workings[self.workers[wid]["at"]]["zone"]

    def metrics(self) -> dict:
        d = self.decision
        group = d["group"]
        out = [w for w in group if self.workers[w]["status"] == "out"]
        left = [w for w in group if self.workers[w]["status"] != "out"]
        m = {
            "in_danger": self.count_in_danger(),
            "danger_exposure_person_s": self.danger_exposure - d["base_danger"],
            "unknown_exposure_person_s": self.unknown_exposure - d["base_unknown"],
            "no_route": sum(1 for w in left if self.route_of(w)[0] is None),
            "out": len(out),
            "all_out": len(out) == len(group),
            "downtime_s": self.total_downtime() - d["base_downtime"],
        }
        if m["all_out"]:
            m["last_out_s"] = self.last_out_tick - d["tick"]
        return m

    def total_downtime(self) -> int:
        return sum(z["downtime_s"] for z in self.zones.values())

    def count_in_danger(self) -> int:
        n = 0
        for w in self.underground():
            zone = self.zone_of_worker(w)
            if zone and self.zones[zone]["hazard"]["hazard_state"] == "danger":
                n += 1
        return n

    def count_unknown(self) -> int:
        n = 0
        for w in self.underground():
            zone = self.zone_of_worker(w)
            if zone and self.zones[zone]["hazard"]["hazard_state"] == "unknown":
                n += 1
        return n

    # --- scripted modifications ---------------------------------------------------

    def _route_events(self, before: dict):
        for w in self.underground():
            old, (new, _) = before[w], self.route_of(w)
            if new is None:
                if old is not None:
                    self.ev("worker.no_route", w)
            elif old is None or [s[0] for s in old["segments"]] != [s[0] for s in new["segments"]]:
                self.ev("worker.route_changed", w, new["exit"])

    def close(self, working, command_id, zone, arg="working_closed"):
        before = {w: self.route_of(w)[0] for w in self.underground()}
        self.closed[working] = "scenario"
        self.conditions.append(f"working_closed:{working}")
        self.ev("condition.set", working, arg, command_id)
        self._route_events(before)
        self.open_incident("passage_closed", zone, working)

    def open(self, working, command_id):
        before = {w: self.route_of(w)[0] for w in self.underground()}
        del self.closed[working]
        self.conditions.remove(f"working_closed:{working}")
        self.ev("condition.cancelled", working, "working_closed", command_id)
        self._route_events(before)
        if self.incident["state"] == "active":
            self.make_decision()      # a condition changed during the pause: new decision_id

    def open_incident(self, trigger, zone, subject):
        cause = {"trigger": trigger, "subject": subject, "tick": self.tick}
        if self.incident["state"] == "none":
            self.incident = {"state": "active", "trigger": trigger, "zone": zone,
                             "opened_at_tick": self.tick, "causes": [cause]}
            self.run_state, self.pause_reason = "paused", "decision"
            self.make_decision()
        else:
            self.incident["causes"].append(cause)

    def make_decision(self):
        self.decision_n += 1
        zone = self.incident["zone"]
        self.decision = {
            "id": f"d-{self.run[4:]}-{self.decision_n:02d}",
            "key": ckey(f"{self.mine.topology}|seed{SEED}|tick{self.tick}|"
                        f"{sorted(self.closed)}|{sorted(self.conditions)}|h{HORIZON_S}"),
            "tick": self.tick, "group": self.underground(),
            "scope": {"option-observe": [], "option-stop-withdraw": [zone],
                      "option-withdraw-all": list(self.zones)},
            "base_danger": self.danger_exposure, "base_unknown": self.unknown_exposure,
            "base_downtime": self.total_downtime(), "forecast": {},
        }
        for oid in OPTIONS:
            self.option_state[oid] = "offered"
        for oid in OPTIONS:
            # the forecast is the outcome of a copy of this state run by the same code
            c = self.clone()
            c.execute(oid, None)
            while c.executing:
                c.step()
            self.decision["forecast"][oid] = c.actual[oid]

    def stop_zone(self, zone):
        z = self.zones[zone]
        z["work_state"], z["production_rate"] = "stopped", 0
        for w in self.underground():
            if self.mine.workers[w][0] == zone and self.workers[w]["status"] == "working":
                self.workers[w]["status"] = "waiting"
        self.ev("zone.stopped", zone)

    def withdraw_zone(self, zone):
        self.zones[zone]["withdrawal_state"] = "in_progress"
        for w in self.underground():
            if self.mine.workers[w][0] == zone:
                has_route = self.route_of(w)[0] is not None
                self.workers[w]["status"] = "moving_to_exit" if has_route else "waiting"
                self.workers[w]["ordered"] = True
        self.ev("withdrawal.started", zone)

    def execute(self, oid, command_id):
        self.incident["state"], self.incident["selected_option"] = "executing", oid
        for other in OPTIONS:
            self.option_state[other] = "executing" if other == oid else "unavailable"
        self.run_state, self.pause_reason = "running", "none"
        self.executing = oid
        self.ev("command.applied", oid, "action.execute_option", command_id)
        for zone in self.decision["scope"][oid]:
            self.stop_zone(zone)
            self.withdraw_zone(zone)

    def sensor_lost(self, sensor, command_id):
        # the last measurement is the model step before the link was cut
        self.sensors[sensor].update(link_state="offline", measured_at=self.tick - 1)
        self.conditions.append(f"sensor_lost:{sensor}")
        self.ev("condition.set", sensor, "sensor_lost", command_id)

    # --- one publication of model time ----------------------------------------------

    def step(self):
        self.tick += TICK_STEP
        for w in self.underground():
            if self.workers[w]["status"] == "moving_to_exit":
                self._advance(w)
        for z in self.zones.values():
            if z["work_state"] == "stopped":
                z["downtime_s"] += TICK_STEP
        self.danger_exposure += TICK_STEP * self.count_in_danger()
        self.unknown_exposure += TICK_STEP * self.count_unknown()
        for zid, z in self.zones.items():
            if z["withdrawal_state"] != "in_progress":
                continue
            left = [w for w in self.underground()
                    if self.mine.workers[w][0] == zid and self.workers[w].get("ordered")]
            if not left:
                z["withdrawal_state"] = "done"
                self.ev("withdrawal.finished", zid, "done")
            elif all(self.route_of(w)[0] is None for w in left):
                z["withdrawal_state"] = "incomplete"
                self.ev("withdrawal.finished", zid, "incomplete")
        if self.executing:
            oid = self.executing
            scope = self.decision["scope"][oid]
            if scope:
                finished = all(self.zones[z]["withdrawal_state"] in ("done", "incomplete")
                               for z in scope)
            else:
                finished = self.tick - self.decision["tick"] >= HORIZON_S
            if finished:
                self.actual[oid] = self.metrics()
                self.option_state[oid] = "done"
                self.incident["state"] = "done"
                self.executing = None

    def _advance(self, wid):
        st = self.workers[wid]
        route, _ = self.route_of(wid)
        if route is None:
            st["status"] = "waiting"
            return
        left = STEP_M
        for working, _, to in route["segments"]:
            w = self.mine.workings[working]
            if working == st["at"]:
                off = st["offset"]
            else:
                off = float(w["length_m"]) if to == w["from"] else 0.0
            remain = off if to == w["from"] else w["length_m"] - off
            if left < remain:
                st["at"], st["offset"] = working, (off - left if to == w["from"] else off + left)
                return
            left -= remain
        st["status"], st["at_exit"] = "out", route["exit"]
        del st["at"], st["offset"]
        self.exits[route["exit"]]["workers_out"] += 1
        self.last_out_tick = self.tick
        self.ev("worker.out", wid, route["exit"])

    # --- the frame: features of shift with the whole scene -----------------------------

    def common(self) -> dict:
        return {"tick": F(self.tick), "sim_time_s": F(self.tick, "s"),
                "idSimulationRun": F(self.run)}

    @staticmethod
    def hazard_features(hz: dict, tick: int, with_index: bool) -> dict:
        f = {k: F(hz[k]) for k in ("hazard_state", "data_quality", "reason_code",
                                   "routing_restriction")}
        if with_index:
            f["instability_index"] = F(hz["instability_index"], "1")
            f["index_at_tick"] = F(hz.get("index_at", tick))
        for k in ("reason_sensor", "reason_value", "reason_threshold", "reason_unit",
                  "last_known_hazard_state", "last_known_hazard_tick"):
            if k in hz:
                f[k] = F(hz[k])
        return f

    def worker_features(self, wid) -> dict:
        st = self.workers[wid]
        f = self.common()
        f["status"] = F(st["status"])
        f["pos_quality"] = F("fresh")
        if st["status"] == "out":
            f["at_exit"] = F(st["at_exit"])
            f["egress_status"], f["egress_reason"] = F("ok"), F("none")
            return f
        f["at_working"], f["offset_m"] = F(st["at"]), F(num(st["offset"]), "m")
        f["location_hazard"] = F(self.working_hazard(st["at"])["hazard_state"])
        route, reason = self.route_of(wid)
        if route is None:
            f["egress_status"], f["egress_reason"] = F("none"), F(reason)
            return f
        base, _ = self.route_of(wid, closed=())
        if self.route_form == "segments":
            f["route"] = F([{"working": w, "from": a, "to": b} for w, a, b in route["segments"]])
        else:
            f["route"] = F([w for w, _, _ in route["segments"]])
        f["route_next_node"] = F(route["segments"][0][2])
        f["egress_status"], f["egress_reason"] = F("ok"), F("none")
        f["egress_exit"] = F(route["exit"])
        f["egress_length_m"] = F(num(route["length"]), "m")
        f["egress_eta_s"] = F(eta_s(route["length"]), "s")
        f["egress_detour_m"] = F(num(route["length"] - base["length"]), "m")
        f["egress_detour_s"] = F(eta_s(route["length"]) - eta_s(base["length"]), "s")
        controlled = [self.working_hazard(w)["hazard_state"] for w, _, _ in route["segments"]
                      if self.mine.workings[w]["zone"]]
        if controlled:
            f["egress_crosses"] = F(max(controlled, key=HAZARD_RANK.__getitem__))
        return f

    def option_features(self, oid) -> dict:
        f = self.common()
        state = self.option_state[oid]
        f["state"] = F(state)
        if state == "inactive":
            return f
        d = self.decision
        f["scope"] = F(d["scope"][oid])
        f["decision_id"], f["comparison_key"] = F(d["id"]), F(d["key"])
        units = {"danger_exposure_person_s": "person*s", "unknown_exposure_person_s": "person*s",
                 "last_out_s": "s", "downtime_s": "zone*s"}
        if self.publish_forecast:
            f["forecast_tick"] = F(d["tick"])
            f["forecast_horizon_s"] = F(HORIZON_S, "s")
            f["forecast_quality"] = F(self.forecast_quality)
            for k, v in d["forecast"][oid].items():
                f["forecast_" + k] = F(v, units.get(k))
        for k, v in self.actual.get(oid, {}).items():
            f["actual_" + k] = F(v, units.get(k))
        return f

    def scene(self) -> list[dict]:
        scene = []

        def add(local, features):
            scene.append({"thingId": tid(local), "features": {**self.common(), **features}})

        for wid in self.mine.workings:
            f = {"passability": F("closed" if wid in self.closed else "open"),
                 "closed_by": F(self.closed.get(wid, "none"))}
            f.update(self.hazard_features(self.working_hazard(wid), self.tick, False))
            add(wid, f)
        for zid, z in self.zones.items():
            workings = set(self.mine.zone_workings(zid))
            f = {"work_state": F(z["work_state"]), "withdrawal_state": F(z["withdrawal_state"]),
                 "workers_count": F(sum(1 for w in self.underground()
                                        if self.workers[w]["at"] in workings)),
                 "production_rate": F(z["production_rate"], "t/h"),
                 "downtime_s": F(z["downtime_s"], "s")}
            f.update(self.hazard_features(z["hazard"], self.tick, True))
            add(zid, f)
        for sid, s in self.sensors.items():
            measured = s.get("measured_at", self.tick)
            f = {"measured_at_tick": F(measured), "measured_at_sim_s": F(measured, "s"),
                 "link_state": F(s["link_state"]), "quality": F(s["quality"])}
            if "value" in s:
                f["value"], f["rate"] = F(s["value"], "mm"), F(s["rate"], "mm/h")
            if "events_count" in s:
                f["events_count"] = F(s["events_count"])
            add(sid, f)
        for wid in self.mine.workers:
            scene.append({"thingId": tid(wid), "features": self.worker_features(wid)})
        for eid, e in self.exits.items():
            add(eid, {"state": F(e["state"]), "workers_out": F(e["workers_out"])})
        add("incident", {k: F(v) for k, v in self.incident.items()})
        for oid in OPTIONS:
            scene.append({"thingId": tid(oid), "features": self.option_features(oid)})
        add("journal", {"last_seq": F(self.last_seq), "events": F(self.events[-50:])})
        return scene

    def frame(self) -> dict:
        under = self.underground()
        f = self.common()
        f.update({
            "contract_version": F(CONTRACT_VERSION),
            "publication_seq": F(FIRST_SEQ),
            "run_state": F(self.run_state), "pause_reason": F(self.pause_reason),
            "speedup": F(10), "seed": F(SEED),
            "topology_version": F(self.topology_version),
            "conditions": F(list(self.conditions)),
            "workers_total": F(len(self.workers)),
            "workers_out": F(len(self.workers) - len(under)),
            "workers_in_danger": F(self.count_in_danger()),
            "workers_no_route": F(sum(1 for w in under if self.route_of(w)[0] is None)),
            "workers_unknown": F(self.count_unknown()),
            "danger_exposure_person_s": F(self.danger_exposure, "person*s"),
            "unknown_exposure_person_s": F(self.unknown_exposure, "person*s"),
            "all_out": F(not under),
            "downtime_s": F(self.total_downtime(), "zone*s"),
            "commands": F([dict(c) for c in self.commands]),
            "runs": F(list(self.runs)),
            "scene": F(self.scene()),
        })
        return f


# ---------------------------------------------------------------------------
# Fixture file helpers
# ---------------------------------------------------------------------------

def state(frames, clock, **extra) -> dict:
    """A named frame sequence. clock: "run" (model time advances) or "hold"."""
    s = {"clock": clock, "frames": frames}
    s.update({k: v for k, v in extra.items() if v is not None})
    return s


def rule(ctype, target=None, *, decision_id=None, status="applied", reason="none",
         goto=None, bind=None, new_run=None, ack_delay=None, no_ack=False,
         transport=None, key=None) -> dict:
    when = {"type": ctype}
    if target is not None:
        when["target"] = target
    if decision_id is not None:
        when["decision_id"] = decision_id
    r: dict = {"when": when}
    if no_ack:
        r["no_ack"] = True
    else:
        r["ack"] = {"status": status, "reason": reason}
        if new_run:
            r["ack"]["new_run"] = new_run
    for k, v in (("goto", goto), ("bind", bind), ("ack_delay", ack_delay),
                 ("transport", transport), ("key", key)):
        if v is not None:
            r[k] = v
    return r


def fixture(name, description, states, start="initial", attribute_sets=None,
            archive=None, publication=None) -> dict:
    fx = {
        "_fixture": {"notice": NOTICE, "contract_version": CONTRACT_VERSION,
                     "scenario": name, "description": description},
        "format": FORMAT,
        "namespace": NS,
        "clock": CLOCK,
        "publication": {"first_seq": FIRST_SEQ, "first_revision": FIRST_REVISION,
                        **(publication or {})},
        "attribute_sets": attribute_sets if attribute_sets is not None else {"t1": MINE.things()},
        "archive": archive if archive is not None else base_archive(),
        "states": states,
    }
    if states:
        fx["start"] = start
    return fx


def element(frame: dict, local: str) -> dict:
    """Features of one scene element of a frame."""
    for el in frame["scene"]["properties"]["value"]:
        if el["thingId"] == tid(local):
            return el["features"]
    raise KeyError(local)


def run_thing(run_id, tick, **values) -> dict:
    units = {"danger_exposure_person_s": "person*s", "unknown_exposure_person_s": "person*s",
             "last_out_s": "s", "downtime_s": "zone*s", "finished_at_sim_s": "s",
             "forecast_horizon_s": "s"}
    units.update({"forecast_" + k: v for k, v in list(units.items())})
    features = {"tick": F(tick), "sim_time_s": F(tick, "s"), "idSimulationRun": F(run_id)}
    for k, v in values.items():
        features[k] = F(v, units.get(k))
    return {"thingId": tid(run_id),
            "attributes": {"kind": "run", "label": run_id, "_parents": tid("mine")},
            "features": features}


def preset_run(run_id, working, zone, oid, stop_after=None) -> Sim:
    """A run started by a preset: the condition at model second 60, then one option."""
    s = Sim(MINE, run=run_id, tick=0, runs=[])
    for _ in range(PRESET_AT_S // TICK_STEP):
        s.step()
    s.close(working, None, zone, arg="preset")
    s.execute(oid, None)
    steps = 0
    while s.executing and (stop_after is None or steps < stop_after):
        s.step()
        steps += 1
    return s


def finished_run(s: Sim, oid, reason, comparable=True, **override) -> dict:
    d = s.decision
    m = s.actual.get(oid) or s.metrics()
    values = {"state": "finished", "seed": SEED, "comparison_key": d["key"],
              "conditions": list(s.conditions), "executed_option": oid,
              "completion_reason": reason, "comparable": comparable,
              "finished_at_sim_s": s.tick}
    values.update(m)
    values.update({"forecast_tick": d["tick"], "forecast_horizon_s": HORIZON_S,
                   "forecast_quality": "full"})
    values.update({"forecast_" + k: v for k, v in d["forecast"][oid].items()})
    values.update(override)
    return run_thing(s.run, s.tick, **values)


def base_archive() -> list[dict]:
    r1 = preset_run("run-0001", "w-12", "zone-b", "option-stop-withdraw")
    r2 = preset_run("run-0002", "w-12", "zone-b", "option-withdraw-all")
    r3 = preset_run("run-0003", "w-12", "zone-b", "option-withdraw-all", stop_after=25)
    r4 = preset_run("run-0004", "w-12", "zone-b", "option-observe")
    return [
        finished_run(r1, "option-stop-withdraw", "withdrawal_done"),
        finished_run(r2, "option-withdraw-all", "withdrawal_done"),
        finished_run(r3, "option-withdraw-all", "reset"),
        finished_run(r4, "option-observe", "horizon_reached", comparable=False,
                     incomparable_reason="condition_changed_after_decision",
                     comparison_key=ckey("run-0004 after a manual change"), conditions=[]),
    ]


def interrupted_run(s: Sim) -> dict:
    """The archive record of a current run interrupted by reset or by a preset start."""
    values = {"state": "finished", "seed": SEED, "conditions": list(s.conditions),
              "completion_reason": "reset", "finished_at_sim_s": s.tick}
    if s.decision:
        values["comparison_key"] = s.decision["key"]
        values["comparable"] = True
        values.update(s.metrics())
    return run_thing(s.run, s.tick, **values)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

MINE = Mine("t1")


def closure_story(working, zone, preset, literal=False):
    """States of 'close a passage -> decision -> execute an option -> open it again'."""
    def c(name):
        return cid(f"{working}:{name}") if literal else "@" + name

    base = Sim(MINE)
    states = {}
    states["initial"] = state([base.frame()], "run", rules=[
        rule("condition.close_working", working, goto="decision", bind="close"),
        rule("run.start_preset", preset, goto="preset_resetting", bind="preset",
             new_run="run-0006", ack_delay=2)])

    d = base.clone()
    d.step()
    d.close(working, c("close"), zone)
    stale = rule("action.execute_option", status="rejected", reason="stale_decision")
    states["decision"] = state([d.frame()], "hold", rules=[
        *[rule("action.execute_option", oid, decision_id=d.decision["id"],
               goto=OPTION_SHORT[oid] + "_exec", bind="exec") for oid in OPTIONS],
        stale,
        rule("condition.open_working", working, goto="decision_open", bind="open")])

    reopened = d.clone()
    reopened.open(working, c("open"))
    states["decision_open"] = state([reopened.frame()], "hold", rules=[
        rule("action.execute_option", decision_id=reopened.decision["id"],
             status="rejected", reason="not_scripted"),
        stale])

    sims = {"initial": base, "decision": d, "decision_open": reopened}
    for oid, kind in OPTIONS.items():
        short = OPTION_SHORT[oid]
        s = d.clone()
        s.execute(oid, c("exec"))
        frames = [s.frame()]
        publications = None
        if kind == "observe":
            # nothing changes until the horizon: one frame repeated, model time running
            while s.executing:
                s.step()
            publications = HORIZON_S // TICK_STEP
        else:
            while True:
                s.step()
                if not s.executing:
                    break
                frames.append(s.frame())
        states[short + "_exec"] = state(frames, "run", publications=publications,
                                        next=short + "_done")
        states[short + "_done"] = state([s.frame()], "run", rules=[
            rule("condition.open_working", working, goto=short + "_done_open", bind="open")])
        after = s.clone()
        after.step()
        after.open(working, c("open"))
        states[short + "_done_open"] = state([after.frame()], "run")
        sims[short + "_done"] = s

    old = base.clone()
    old.step()
    old.run_state = "resetting"
    states["preset_resetting"] = state([old.frame()], "hold", publications=2, next="preset_run")
    new = old.successor("run-0006", c("preset"), preset)
    states["preset_run"] = state([new.frame()], "run", new_run=True,
                                 publications=PRESET_AT_S // TICK_STEP, next="preset_decision")
    for _ in range(PRESET_AT_S // TICK_STEP):
        new.step()
    new.close(working, None, zone, arg="preset:" + preset)
    states["preset_decision"] = state([new.frame()], "hold")
    archive = base_archive() + [interrupted_run(old)]
    return states, sims, archive


def static(sim_or_frame, clock="run", **extra) -> dict:
    frame = sim_or_frame.frame() if isinstance(sim_or_frame, Sim) else sim_or_frame
    return {"initial": state([frame], clock, **extra)}


def then_violated(mutate) -> dict:
    """Three valid publications, then a violation that persists."""
    good = Sim(MINE)
    bad = good.clone()
    for _ in range(3):
        bad.step()
    frame = bad.frame()
    extra = mutate(frame) or {}
    return {"initial": state([good.frame()], "run", publications=3, next="violated"),
            "violated": state([frame], "run", **extra)}


def build_all() -> dict[str, dict]:
    out: dict[str, dict] = {}

    def put(name, description, states, **kw):
        out[name] = fixture(name, description, states, **kw)

    # --- normal and its link variants ---
    normal = Sim(MINE)
    put("normal", "Обычный кадр: модель идёт, условий и инцидента нет, у всех работников "
        "есть расчётный маршрут, участок Г в состоянии «внимание».", static(normal))
    put("frozen_seq", "Сервер отвечает 200, но после третьей публикации publication_seq, "
        "_modified и _revision перестают меняться.", static(normal),
        publication={"freeze_at": 3})
    put("frozen_seq_old", "Сервер отвечает 200, состояние застыло с первого ответа, "
        "_modified на 30 с старше заголовка Date.", static(normal),
        publication={"freeze_at": 1, "modified_age_s": 30})

    # --- passage closure stories ---
    states, sims, archive = closure_story("w-12", "zone-b", "p-detour")
    put("detour", "Закрытие В-12: обход участка Б по съезду (655 м для Р-03), пауза для "
        "выбора, исполнение варианта с движением людей, открытие прохода, пресет p-detour.",
        states, archive=archive)
    detour_decision = sims["decision"]

    states, sims, archive = closure_story("w-07", "zone-c", "p-no-path")
    put("no_path", "Закрытие В-07: у Р-07 и Р-08 нет открытого пути, прогноз каждого "
        "варианта содержит двоих без маршрута, вывод участка В остаётся неполным.",
        states, archive=archive)

    lit_states, lit_sims, _ = closure_story("w-07", "zone-c", "p-no-path", literal=True)
    put("withdrawal_incomplete", "Конечное состояние исполненного варианта «вывести всех» "
        "при закрытой В-07: двенадцать человек вышли, двое без маршрута, вывод участка В "
        "неполный, времени выхода всех нет.", static(lit_sims["wa_done"]))

    lit_states, lit_sims, _ = closure_story("w-12", "zone-b", "p-detour", literal=True)
    decision = lit_sims["decision"]
    put("paused_heartbeat", "Модель на паузе для выбора действия: tick стоит, "
        "publication_seq растёт каждую секунду.", static(decision, "hold"))

    no_forecast = decision.clone()
    no_forecast.publish_forecast = False
    put("no_forecast", "Инцидент открыт, модель на паузе, варианты предложены, но признаков "
        "forecast_* нет: прогноз не опубликован.", static(no_forecast, "hold"))

    partial = decision.clone()
    partial.forecast_quality = "partial"
    put("partial_forecast", "Точка решения с прогнозом по неполным данным: "
        "forecast_quality = partial. Причина неполноты в фикстуре не разыгрывается.",
        static(partial, "hold"))

    segments = decision.clone()
    segments.route_form = "segments"
    put("route_segments", "Точка решения сценария detour, но route состоит из "
        "ориентированных сегментов {working, from, to}.", static(segments, "hold"))

    # --- reset from the decision point ---
    resetting = decision.clone()
    resetting.run_state, resetting.pause_reason = "resetting", "none"
    fresh = decision.clone().successor("run-0006", "@reset")
    put("reset", "Полный сброс из точки решения: две публикации resetting, затем новый "
        "прогон run-0006 с тика 0, подтверждение сброса видно уже в новом прогоне.", {
            "initial": state([decision.frame()], "hold", rules=[
                rule("run.reset", goto="resetting", bind="reset", new_run="run-0006",
                     ack_delay=2)]),
            "resetting": state([resetting.frame()], "hold", publications=2, next="fresh"),
            "fresh": state([fresh.frame()], "run", new_run=True),
        }, archive=base_archive() + [interrupted_run(decision)])

    # --- sensor lost after danger ---
    s = Sim(MINE, tick=700)
    s.zones["zone-c"]["hazard"].update(
        hazard_state="danger", routing_restriction="blocked", instability_index=0.78,
        reason_code="rate_above_danger", reason_sensor="sens-ext-05", reason_value=2.6,
        reason_threshold=2.0, reason_unit="mm/h")
    s.sensors["sens-ext-05"].update(value=9.8, rate=2.6)
    s.ev("hazard.changed", "zone-c", "danger")
    s.open_incident("hazard", "zone-c", "zone-c")
    s.execute("option-observe", cid("lost:observe"))
    for _ in range(6):
        s.step()
    s.sensor_lost("sens-ext-05", cid("lost:sensor"))        # tick 760
    for _ in range(6):
        s.step()
    s.sensors["sens-ext-05"]["quality"] = "stale"           # tick 820
    s.ev("quality.changed", "sens-ext-05", "stale")
    s.last_seq += 2                                         # two events fell out: a gap in seq
    s.zones["zone-c"]["hazard"].update(
        hazard_state="unknown", data_quality="stale", reason_code="sensor_stale",
        index_at=s.tick - TICK_STEP, last_known_hazard_state="danger",
        last_known_hazard_tick=s.tick - TICK_STEP)
    for k in ("reason_value", "reason_threshold", "reason_unit"):
        del s.zones["zone-c"]["hazard"][k]
    s.ev("hazard.changed", "zone-c", "unknown")
    s.open_incident("data_lost", "zone-c", "sens-ext-05")
    for _ in range(24):
        s.step()
    s.sensors["sens-ext-05"]["quality"] = "lost"            # tick 1060
    s.zones["zone-c"]["hazard"].update(data_quality="lost", reason_code="sensor_lost")
    s.ev("quality.changed", "sens-ext-05", "lost")
    while s.tick < BASE_TICK:
        s.step()
    put("sensor_lost_after_danger", "Участок В был в состоянии «опасно», затем потерял "
        "единственный датчик: состояние неизвестно, последнее известное — «опасно», "
        "ограничение маршрутов сохранено. В журнале пропуск номеров seq.", static(s))

    # --- invalid snapshots ---
    def missing_id(frame):
        scene = frame["scene"]["properties"]["value"]
        scene[:] = [el for el in scene if el["thingId"] != tid("worker-14")]

    def duplicate_id(frame):
        scene = frame["scene"]["properties"]["value"]
        scene.append(copy.deepcopy(next(el for el in scene if el["thingId"] == tid("worker-14"))))

    def mixed_tick(frame):
        f = element(frame, "sens-geo-02")
        for k in ("tick", "sim_time_s", "measured_at_tick", "measured_at_sim_s"):
            f[k]["properties"]["value"] -= TICK_STEP

    def missing_field(frame):
        del element(frame, "worker-05")["egress_status"]

    def contract_version(frame):
        frame["contract_version"] = F(2)

    put("invalid_missing_id", "Три полных публикации, затем в scene нет worker-14 "
        "(есть в dynamic_ids).", then_violated(missing_id))
    put("invalid_duplicate_id", "Три полных публикации, затем worker-14 входит в scene "
        "дважды.", then_violated(duplicate_id))
    put("invalid_mixed_tick", "Три полных публикации, затем sens-geo-02 несёт tick "
        "предыдущей публикации.", then_violated(mixed_tick))
    put("invalid_missing_field", "Три полных публикации, затем у worker-05 нет "
        "обязательного egress_status.", then_violated(missing_field))
    put("invalid_contract_version", "Три полных публикации, затем shift сообщает "
        "contract_version = 2.", then_violated(contract_version))
    put("invalid_no_metadata", "Три полных публикации, затем ответ shift приходит без "
        "_modified и _revision.", then_violated(lambda frame: {"metadata": False}))

    # --- topology ---
    mismatch = Sim(MINE)
    mismatch.topology_version = "t2"
    put("topology_mismatch", "shift постоянно сообщает topology_version = t2, а атрибуты "
        "рудника — t1.", static(mismatch))
    mine2 = Mine("t2")
    second = Sim(mine2)
    for _ in range(3):
        second.step()
    put("topology_change", "После трёх публикаций shift переходит на топологию t2; с этого "
        "момента атрибуты отдаются набором t2: у В-19 другая геометрия, добавлена В-37.", {
            "initial": state([Sim(MINE).frame()], "run", publications=3, next="t2"),
            "t2": state([second.frame()], "run", attributes="t2"),
        }, attribute_sets={"t1": MINE.things(), "t2": mine2.things()})

    # --- scripted command outcomes ---
    c0 = Sim(MINE, tick=380)
    rejected = cid("commands:resume")
    c0.ev("command.rejected", "zone-a", "not_allowed_in_state", rejected)
    c0.commands.append({"id": rejected, "type": "action.resume_zone", "target": "zone-a",
                        "run": c0.run, "status": "rejected", "tick": c0.tick,
                        "sim_time_s": c0.tick, "reason": "not_allowed_in_state"})
    for _ in range(2):
        c0.step()
    withdrawn = cid("commands:withdraw")                     # tick 400
    c0.ev("command.applied", "zone-a", "action.withdraw_zone", withdrawn)
    c0.commands.append({"id": withdrawn, "type": "action.withdraw_zone", "target": "zone-a",
                        "run": c0.run, "status": "applied", "tick": c0.tick,
                        "sim_time_s": c0.tick, "reason": "none"})
    c0.stop_zone("zone-a")
    c0.withdraw_zone("zone-a")
    while c0.tick < BASE_TICK:
        c0.step()

    def after(sim, action):
        nxt = sim.clone()
        nxt.step()
        action(nxt)
        return nxt

    def stop_b(sim):
        sim.ev("command.applied", "zone-b", "action.stop_zone", "@stop")
        sim.stop_zone("zone-b")

    def lose(sim):
        sim.sensor_lost("sens-ext-05", "@lost")

    variants = {"initial": c0, "zb": after(c0, stop_b), "sl": after(c0, lose)}
    variants["zb_sl"] = after(variants["zb"], lose)
    variants["sl_zb"] = after(variants["sl"], stop_b)
    hang = [{"hang_ms": 10000, "status": 504, "delivered": True}]
    refuse = [{"status": 503, "delivered": False}]
    goto_stop = {"initial": "zb", "sl": "sl_zb"}
    goto_lost = {"initial": "sl", "zb": "zb_sl"}
    states = {}
    for name, sim in variants.items():
        rules = [
            rule("condition.close_working", "w-12", no_ack=True),
            rule("condition.close_working", "w-07", status="rejected",
                 reason="not_allowed_in_state"),
            rule("action.stop_zone", "zone-a", reason="already_in_state"),
            rule("action.resume_zone", "zone-a", status="rejected",
                 reason="insufficient_workers"),
        ]
        if name in goto_lost:
            rules.append(rule("condition.sensor_lost", "sens-ext-05", goto=goto_lost[name],
                              bind="lost", transport=hang, key="sensor-lost"))
        else:
            rules.append(rule("condition.sensor_lost", "sens-ext-05", reason="already_in_state",
                              transport=hang, key="sensor-lost"))
        if name in goto_stop:
            rules.append(rule("action.stop_zone", "zone-b", goto=goto_stop[name], bind="stop",
                              transport=refuse, key="stop-zone-b"))
        else:
            rules.append(rule("action.stop_zone", "zone-b", reason="already_in_state",
                              transport=refuse, key="stop-zone-b"))
        states[name] = state([sim.frame()], "run", rules=rules)
    put("commands", "Неподвижное идущее состояние с заданными исходами команд: без "
        "подтверждения, отказ, зависший POST с повтором, HTTP 503 с повтором, "
        "already_in_state, insufficient_workers. Участок А уже остановлен и выведен.", states)

    # --- unknown enum values ---
    frame = Sim(MINE).frame()
    element(frame, "zone-a")["hazard_state"] = F("elevated")
    element(frame, "worker-09")["status"] = F("resting")
    journal = element(frame, "journal")
    seq = journal["last_seq"]["properties"]["value"] + 1
    journal["last_seq"] = F(seq)
    journal["events"]["properties"]["value"].append(
        {"seq": seq, "run": "run-0005", "tick": 900, "sim_time_s": 900,
         "code": "ventilation.changed", "subject": "zone-a", "arg": "reduced"})
    things = MINE.things()
    next(t for t in things if t["thingId"] == tid("option-observe"))["attributes"][
        "option_kind"] = "shelter"
    put("unknown_enum", "Неизвестные значения перечислений: участок А hazard_state = "
        "elevated, Р-09 status = resting, вариант option_kind = shelter, событие журнала "
        "с кодом ventilation.changed.", static(frame), attribute_sets={"t1": things})

    put("empty", "Пустой стенд: двойник рудника и все остальные двойники не найдены, "
        "GET возвращает 404 с телом ошибки в стиле Ditto.", {},
        attribute_sets={}, archive=[])

    assert list(out) != [] and sorted(out) == sorted(SCENARIOS), sorted(set(SCENARIOS) ^ set(out))
    return {name: out[name] for name in SCENARIOS}


# ---------------------------------------------------------------------------
# Deterministic JSON layout: one thing per line, short values on one line
# ---------------------------------------------------------------------------

def _compact(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


FORMAT = 1


def render(obj, indent=0) -> str:
    text = _compact(obj)
    if not isinstance(obj, (dict, list)) or not obj:
        return text
    limit = 2500 if isinstance(obj, dict) and "thingId" in obj else 160
    if len(text) <= limit:
        return text
    pad = " " * (indent + 1)
    if isinstance(obj, dict):
        items = [f"{pad}{json.dumps(k, ensure_ascii=False)}:{render(obj[k], indent + 1)}"
                 for k in sorted(obj)]
        return "{\n" + ",\n".join(items) + "\n" + " " * indent + "}"
    items = [pad + render(v, indent + 1) for v in obj]
    return "[\n" + ",\n".join(items) + "\n" + " " * indent + "]"


def write_all(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, fx in build_all().items():
        path = out_dir / f"{name}.json"
        path.write_bytes((render(fx) + "\n").encode("utf-8"))
        written.append(path)
    return written


def main(argv=None) -> int:
    default_dir = Path(__file__).resolve().parent.parent / "fixtures"
    parser = argparse.ArgumentParser(description="Build the contract fixtures (invented test data).")
    parser.add_argument("--out", type=Path, default=default_dir, help="output directory")
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if the files in --out differ from a fresh build")
    args = parser.parse_args(argv)
    if args.check:
        differing = []
        for name, fx in build_all().items():
            path = args.out / f"{name}.json"
            fresh = (render(fx) + "\n").encode("utf-8")
            # a checkout with core.autocrlf may have turned LF into CRLF
            if not path.exists() or path.read_bytes().replace(b"\r\n", b"\n") != fresh:
                differing.append(path.name)
        extra = sorted(p.name for p in args.out.glob("*.json")
                       if p.stem not in SCENARIOS)
        if differing or extra:
            print("fixtures differ:", ", ".join(differing + ["unexpected " + e for e in extra]))
            return 1
        print(f"{len(SCENARIOS)} fixtures are up to date")
        return 0
    written = write_all(args.out)
    total = sum(p.stat().st_size for p in written)
    print(f"wrote {len(written)} fixtures, {total / 1e6:.1f} MB, to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
