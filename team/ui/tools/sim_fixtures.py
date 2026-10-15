#!/usr/bin/env python3
"""Mock fixtures recorded from the real mine simulation (team/sim), for the dispatcher UI.

Unlike build_fixtures.py (invented topology, scripted stepper), this tool drives the
team's own simulation offline: team.sim.model.Mine advanced publication by publication,
team.sim.twins.snapshot as the service takes it, without Ditto, MQTT or storage. The
frames written are the published shift features, the `scene` array included. The mock
server replays them as before; it still contains no mine logic.

One scenario per preset of the mine twin:

    sim_instability   p-instability   zone A reaches "danger" (fresh data)
    sim_detour        p-detour        the main drift w-04 closes, routes get longer
    sim_trapped       p-trapped       w-07, the only way out of zone A, closes
    sim_sensor        p-sensor        the extensometer of zone A goes silent

States of a scenario (see fixtures/SIM.md):

    initial        run-0001 at rest; the preset button (run.start_preset) starts run-0002
    preset_run     run-0002 from its start to the second before the decision
    decision       paused, three options offered with their forecasts
    <o>_exec       the option executes, one real publication per frame (o: observe, sw, wa)
    <o>_done       the horizon is reached: incident done, run paused, run archived

Usage:
    python team/ui/tools/sim_fixtures.py            # rewrite team/ui/fixtures/sim_*.json.gz
    python team/ui/tools/sim_fixtures.py --out DIR
    python team/ui/tools/sim_fixtures.py --check    # exit 1 if the files differ from a fresh run

Deterministic: no clock, no randomness, sorted keys, LF endings. Standard library and
team.sim only.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
UI_DIR = TOOLS_DIR.parent
REPO_ROOT = UI_DIR.parent.parent
for path in (str(REPO_ROOT), str(TOOLS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from team.sim.model import Mine                      # noqa: E402
from team.sim.topology import NAMESPACE              # noqa: E402
from team.sim.twins import snapshot                  # noqa: E402
from build_fixtures import CLOCK as INVENTED_CLOCK, render   # noqa: E402  (layout and re-timing rules)

FIRST_SEQ = 1000          # the mock overwrites publication_seq; only the first value is a choice
FIRST_REVISION = 2000
REST_PUBLICATIONS = 6     # frames of run-0001 before anything is pressed (ticks 0..50)
SPEEDUP = 10              # model seconds per publication (parameters["speedup"])
NOTICE = ("Фикстура записана из симуляции команды (team/sim) без платформы: кадры - опубликованные "
          "признаки смены, как их отдаёт twins.snapshot. Данные условной модели, не измерения стенда.")

# The sim publishes last_known_hazard_tick always (the tick of the last fresh evaluation), not only
# when the data are stale: while it equals the element's own tick it follows the mock's clock.
CLOCK = {**INVENTED_CLOCK,
         "follow_fields": sorted({*INVENTED_CLOCK["follow_fields"], "last_known_hazard_tick"}),
         "event_fields": [f for f in INVENTED_CLOCK["event_fields"] if f != "last_known_hazard_tick"]}

PRESET_CID = "c-" + "1" * 32      # ids of the commands the recording sends; the mock binds the real ones
EXEC_CID = "c-" + "2" * 32

SCENARIOS = {
    "sim_instability": ("p-instability", "рост нестабильности на участке A: опасно по свежим данным"),
    "sim_detour": ("p-detour", "перекрыт основной проход w-04: маршруты работников удлиняются"),
    "sim_trapped": ("p-trapped", "перекрыта w-07, единственный выход с участка A: у троих нет маршрута"),
    "sim_sensor": ("p-sensor", "потерян датчик Э-A: состояние участка A неизвестно"),
}
OPTIONS = {"observe": "observe", "stop_withdraw_zone": "sw", "withdraw_all": "wa"}


# ---------------------------------------------------------------------------
# Driving the simulation
# ---------------------------------------------------------------------------

def value_of(frame: dict, name: str):
    return frame[name]["properties"]["value"]


def take(mine: Mine) -> tuple[dict, dict]:
    """One publication: (shift features, all twins by local name). Like service.py after advance()."""
    twins = snapshot(mine)
    return copy.deepcopy(twins["shift"]["features"]), twins


def command(mine: Mine, cid: str, ctype: str, target: str, **extra) -> dict:
    ack = mine.command(dict(command_id=cid, type=ctype, target=target, run=mine.run, **extra))
    if ack["status"] != "applied":
        raise RuntimeError(f"the simulation refused {ctype} {target}: {ack['reason']}")
    return ack


def record(preset_id: str) -> dict:
    """Runs one preset to its decision and all three options from there to the horizon."""
    mine = Mine()
    initial = []
    for number in range(REST_PUBLICATIONS):
        if number:
            mine.advance(SPEEDUP)
        initial.append(take(mine)[0])

    command(mine, PRESET_CID, "run.start_preset", preset_id)
    preset_run = []
    while True:
        mine.advance(SPEEDUP)
        frame, twins = take(mine)
        if mine.incident["state"] == "active":
            decision = frame
            break
        preset_run.append(frame)
        if mine.tick > 600:
            raise RuntimeError(f"{preset_id} did not reach a decision")
    forecasts = copy.deepcopy(mine.forecasts)
    decision_id = mine.incident["decision_id"]

    options = {}
    for kind in OPTIONS:
        trial = copy.deepcopy(mine)
        command(trial, EXEC_CID, "action.execute_option", "option-" + kind, decision_id=decision_id)
        # The model state the moment the option is launched: tick unchanged, run goes on.
        frames = [take(trial)[0]]
        while trial.incident["state"] != "done":
            trial.advance(SPEEDUP)
            frame, twins = take(trial)
            frames.append(frame)
        options[kind] = dict(frames=frames, archive=[twins[name] for name in sorted(twins) if name.startswith("run-")])
    return dict(initial=initial, preset_run=preset_run, decision=decision, decision_id=decision_id,
                forecasts=forecasts, options=options, attributes=snapshot(mine))


# ---------------------------------------------------------------------------
# From published frames to mock fixtures
# ---------------------------------------------------------------------------

def bind_commands(value, bindings: dict[str, str]):
    """Journal events carry the id of the command that caused them; the mock binds the real id."""
    if isinstance(value, dict):
        return {k: bind_commands(v, bindings) for k, v in value.items()}
    if isinstance(value, list):
        return [bind_commands(v, bindings) for v in value]
    return "@" + bindings[value] if isinstance(value, str) and value in bindings else value


def clean(frame: dict) -> dict:
    """The recorded acknowledgements are dropped: the mock server writes its own into `commands`."""
    frame = bind_commands(frame, {PRESET_CID: "preset", EXEC_CID: "exec"})
    frame["commands"]["properties"]["value"] = []
    for element in frame["scene"]["properties"]["value"]:
        if "commands" in element["features"]:
            raise RuntimeError("a scene element carries commands")
    leftover = json.dumps(frame)
    if PRESET_CID in leftover or EXEC_CID in leftover:
        raise RuntimeError("a recorded command id is left in a frame")
    return frame


def state(frames, clock, **extra) -> dict:
    out = {"clock": clock, "frames": [clean(f) for f in frames]}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def rule(ctype, target=None, *, decision_id=None, status="applied", reason="none", goto=None,
         bind=None, new_run=None) -> dict:
    when = {"type": ctype}
    if target is not None:
        when["target"] = target
    if decision_id is not None:
        when["decision_id"] = decision_id
    r = {"when": when, "ack": {"status": status, "reason": reason}}
    if new_run:
        r["ack"]["new_run"] = new_run
    for key, value in (("goto", goto), ("bind", bind)):
        if value is not None:
            r[key] = value
    return r


def fixture_for(name: str) -> dict:
    preset_id, description = SCENARIOS[name]
    rec = record(preset_id)
    twins = rec["attributes"]
    mine_twin = twins["mine"]
    attribute_sets = {"t1": [{"thingId": thing_id, "attributes": twins[thing_id.split(":", 1)[1]]["attributes"]}
                             for thing_id in mine_twin["attributes"]["manifest"]]}
    new_run = value_of(rec["decision"], "idSimulationRun")

    states = {}
    states["initial"] = state(rec["initial"], "run", rules=[
        rule("run.start_preset", preset_id, goto="preset_run", bind="preset", new_run=new_run)])
    states["preset_run"] = state(rec["preset_run"], "run", new_run=True,
                                 publications=len(rec["preset_run"]), next="decision")
    states["decision"] = state([rec["decision"]], "hold", rules=[
        *[rule("action.execute_option", "option-" + kind, decision_id=rec["decision_id"],
               goto=short + "_exec", bind="exec") for kind, short in OPTIONS.items()],
        rule("action.execute_option", status="rejected", reason="stale_decision")])

    archive = {}
    for kind, short in OPTIONS.items():
        option = rec["options"][kind]
        states[short + "_exec"] = state(option["frames"][:-1], "run", next=short + "_done")
        done_archive = [{"thingId": t["thingId"], "attributes": t["attributes"], "features": t["features"]}
                        for t in option["archive"]]
        states[short + "_done"] = state(option["frames"][-1:], "hold", archive=done_archive)
        for twin in done_archive:
            archive.setdefault(twin["thingId"], twin)
    # The run archived by the preset start is the same in every story and is served from the file's
    # archive; the finished run differs per option and lives in the done state that lists it.
    base = [t for t in archive.values() if t["thingId"].endswith(":run-0001")]
    return {
        "_fixture": {"notice": NOTICE, "contract_version": 1, "scenario": name,
                     "description": f"Симуляция team/sim, пресет {preset_id}: {description}. "
                                    "Кнопка пресета, решение, три варианта до горизонта."},
        "format": 1,
        "namespace": NAMESPACE,
        "clock": CLOCK,
        "publication": {"first_seq": FIRST_SEQ, "first_revision": FIRST_REVISION},
        "attribute_sets": attribute_sets,
        "archive": base,
        "start": "initial",
        "states": states,
    }


def build_all() -> dict[str, dict]:
    return {name: fixture_for(name) for name in SCENARIOS}


def pack(fx) -> bytes:
    """The fixture as gzipped JSON (about 70 times smaller), byte for byte the same on every run (mtime 0)."""
    return gzip.compress((render(fx) + "\n").encode("utf-8"), 9, mtime=0)


def write_all(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, fx in build_all().items():
        path = out_dir / f"{name}.json.gz"
        path.write_bytes(pack(fx))
        written.append(path)
    return written


def main(argv=None) -> int:
    default_dir = UI_DIR / "fixtures"
    parser = argparse.ArgumentParser(description="Record mock fixtures from the team's simulation.")
    parser.add_argument("--out", type=Path, default=default_dir, help="output directory")
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if the files in --out differ from a fresh run")
    args = parser.parse_args(argv)
    if args.check:
        differing = []
        for name, fx in build_all().items():
            path = args.out / f"{name}.json.gz"
            if not path.exists() or path.read_bytes() != pack(fx):
                differing.append(path.name)
        if differing:
            print("fixtures differ:", ", ".join(differing))
            return 1
        print(f"{len(SCENARIOS)} sim fixtures are up to date")
        return 0
    written = write_all(args.out)
    total = sum(p.stat().st_size for p in written)
    print(f"wrote {len(written)} fixtures, {total / 1e6:.1f} MB, to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
