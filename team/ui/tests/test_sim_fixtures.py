"""The mock fixtures recorded from the team's simulation (tools/sim_fixtures.py).

Three layers, each against the real thing:

* the files: they load, they are what a fresh recording writes, every story has its states;
* the mock server's own replay (no browser, no HTTP): a launched command is answered with the
  frames of that option, through to the end;
* the page, in headless Chrome: every recorded frame passes the interface's own snapshot validation
  (public/js/validate.js), and each scenario is opened, started by its preset, decided by each of the
  three options through the real controls, and followed to the end, with no console error.

    python -m unittest discover -s team/ui/tests -t team/ui -p "test_sim_fixtures.py" -v
"""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from browser_support import BrowserTestCase, MockServer, wait_until

import mock_server

UI_DIR = Path(__file__).resolve().parent.parent
FIXTURES = UI_DIR / "fixtures"
GENERATOR = UI_DIR / "tools" / "sim_fixtures.py"

NS = "team040.mine"
# scenario -> (preset, the options of the mine, short names of the option states)
SCENARIOS = {
    "sim_instability": "p-instability",
    "sim_detour": "p-detour",
    "sim_trapped": "p-trapped",
    "sim_sensor": "p-sensor",
}
OPTIONS = {"observe": "observe", "stop_withdraw_zone": "sw", "withdraw_all": "wa"}
STATES = {"initial", "preset_run", "decision", *(f"{short}_{part}" for short in OPTIONS.values()
                                                 for part in ("exec", "done"))}
SWIFTSHADER = ("--use-angle=swiftshader", "--enable-unsafe-swiftshader")
PUBLICATION_MS = "100"


def load(name):
    return json.loads(gzip.decompress((FIXTURES / f"{name}.json.gz").read_bytes()).decode("utf-8"))


def value_of(frame, name, default=None):
    return mock_server.value_of(frame, name, default)


def element(frame, local):
    for item in value_of(frame, "scene", []):
        if item["thingId"] == f"{NS}:{local}":
            return item["features"]
    raise KeyError(local)


def command(ctype, target, run, **extra):
    return {"command_id": "c-" + os.urandom(16).hex(), "type": ctype, "target": target, "run": run, **extra}


# ---------------------------------------------------------------------------
# The files
# ---------------------------------------------------------------------------

class SimFixtureFilesTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.fixtures = {name: load(name) for name in SCENARIOS}

    def test_the_files_load_in_the_format_the_mock_reads(self):
        for name, fx in self.fixtures.items():
            with self.subTest(name):
                mock_server.check_format(fx)
                self.assertEqual(fx["namespace"], NS)
                self.assertEqual(fx["_fixture"]["scenario"], name)
                self.assertTrue(fx["_fixture"]["description"])
                self.assertEqual(fx["start"], "initial")
                self.assertEqual(set(fx["states"]), STATES)

    def test_the_mock_lists_the_scenarios(self):
        app = mock_server.App(FIXTURES, UI_DIR / "public", 1000)
        listed = {item["name"]: item["description"] for item in app.scenarios()}
        for name in SCENARIOS:
            self.assertTrue(listed.get(name), name)

    def test_the_topology_is_the_simulations(self):
        for name, fx in self.fixtures.items():
            with self.subTest(name):
                things = {t["thingId"].split(":")[1]: t["attributes"] for t in fx["attribute_sets"]["t1"]}
                mine = things["mine"]
                self.assertEqual(len(mine["manifest"]), 34)
                self.assertEqual(len(mine["dynamic_ids"]), 29)
                self.assertEqual(sorted(k for k, a in things.items() if a["kind"] == "level"),
                                 ["level-120", "level-240", "surface"])
                self.assertEqual(sorted(k for k, a in things.items() if a["kind"] == "working"),
                                 [f"w-{n:02d}" for n in range(1, 13)])
                self.assertEqual([p["id"] for p in mine["presets"]],
                                 ["p-instability", "p-detour", "p-trapped", "p-sensor"])
                self.assertEqual(things["w-01"]["points"], [[-240, 0, -60]])
                # the manifest, in the twin's own order, is what the attribute set lists
                self.assertEqual([t["thingId"] for t in fx["attribute_sets"]["t1"]], mine["manifest"])

    def test_every_frame_is_a_published_snapshot_of_one_run(self):
        for name, fx in self.fixtures.items():
            mine = next(t for t in fx["attribute_sets"]["t1"] if t["thingId"] == f"{NS}:mine")["attributes"]
            dynamic = mine["dynamic_ids"]
            for state_name, state in fx["states"].items():
                runs = {value_of(f, "idSimulationRun") for f in state["frames"]}
                self.assertEqual(len(runs), 1, f"{name}/{state_name}: one run per state")
                for i, frame in enumerate(state["frames"]):
                    where = f"{name}/{state_name}[{i}]"
                    scene = value_of(frame, "scene")
                    # the scene lists the twins by kind, dynamic_ids by creation: the same set, each once
                    self.assertEqual(sorted(e["thingId"] for e in scene), sorted(dynamic), where)
                    for e in scene:
                        self.assertEqual(value_of(e["features"], "tick"), value_of(frame, "tick"), where)
                    self.assertEqual(value_of(frame, "commands"), [], f"{where}: the mock writes acknowledgements")

    def test_the_story_runs_in_order_and_ticks_are_the_models(self):
        for name, fx in self.fixtures.items():
            states = fx["states"]
            with self.subTest(name):
                first = states["initial"]["frames"][0]
                self.assertEqual(value_of(first, "idSimulationRun"), "run-0001")
                self.assertEqual(value_of(first, "tick"), 0)
                run = {value_of(f, "idSimulationRun") for f in states["decision"]["frames"]}
                self.assertEqual(run, {"run-0002"})
                self.assertEqual(states["preset_run"]["next"], "decision")
                decision = states["decision"]["frames"][0]
                self.assertEqual(value_of(decision, "run_state"), "paused")
                self.assertEqual(value_of(decision, "pause_reason"), "decision")
                self.assertEqual(value_of(element(decision, "incident"), "state"), "active")
                decision_id = value_of(element(decision, "incident"), "decision_id")
                self.assertEqual(decision_id, "run-0002-d1")
                ticks = [value_of(f, "tick") for f in states["preset_run"]["frames"]]
                self.assertEqual(ticks, list(range(10, 10 * (len(ticks) + 1), 10)))
                for kind, short in OPTIONS.items():
                    option = f"option-{kind}"
                    rules = [r for r in states["decision"]["rules"]
                             if r["when"].get("target") == option]
                    self.assertEqual(len(rules), 1, option)
                    self.assertEqual(rules[0]["when"]["decision_id"], decision_id)
                    self.assertEqual(rules[0]["goto"], f"{short}_exec")
                    execing = states[f"{short}_exec"]
                    self.assertEqual(execing["next"], f"{short}_done")
                    frames = execing["frames"]
                    ticks = [value_of(f, "tick") for f in frames]
                    # the state of the launch (the tick of the decision), then one publication every 10 s
                    self.assertEqual(ticks[0], value_of(decision, "tick"))
                    self.assertEqual(ticks, [ticks[0] + 10 * i for i in range(len(frames))])
                    for f in frames:
                        self.assertEqual(value_of(f, "run_state"), "running")
                        self.assertEqual(value_of(element(f, "incident"), "state"), "executing")
                        self.assertEqual(value_of(element(f, option), "state"), "executing")
                        others = [o for o in OPTIONS if o != kind]
                        self.assertEqual({value_of(element(f, f"option-{o}"), "state") for o in others}, {"inactive"})
                    done = states[f"{short}_done"]
                    self.assertEqual(done["clock"], "hold")
                    end = done["frames"][0]
                    self.assertEqual(value_of(end, "tick"), ticks[-1] + 10)
                    self.assertEqual(value_of(end, "tick") - value_of(decision, "tick"), 900,
                                     "the horizon of the model")
                    self.assertEqual(value_of(end, "run_state"), "paused")
                    self.assertEqual(value_of(element(end, "incident"), "state"), "done")
                    self.assertEqual(value_of(element(end, option), "state"), "done")
                    self.assertIn("actual_all_out", element(end, option))
                    self.assertEqual(value_of(end, "runs"), [f"{NS}:run-0001", f"{NS}:run-0002"])
                    archived = {t["thingId"]: t for t in done["archive"]}
                    self.assertEqual(sorted(archived), [f"{NS}:run-0001", f"{NS}:run-0002"])
                    self.assertEqual(value_of(archived[f"{NS}:run-0002"]["features"], "executed_option"), option)

    def test_the_forecast_is_what_the_model_then_did(self):
        """The simulation's own promise, seen through the recording: each option's forecast at the decision
        equals its actual result at the horizon."""
        fields = ["out", "all_out", "in_danger", "no_route", "unknown", "danger_exposure_person_s",
                  "unknown_exposure_person_s", "downtime_s", "last_out_s"]
        for name, fx in self.fixtures.items():
            decision = fx["states"]["decision"]["frames"][0]
            for kind, short in OPTIONS.items():
                end = fx["states"][f"{short}_done"]["frames"][0]
                forecast, actual = element(decision, f"option-{kind}"), element(end, f"option-{kind}")
                for field in fields:
                    self.assertEqual(value_of(forecast, "forecast_" + field), value_of(actual, "actual_" + field),
                                     f"{name} {kind} {field}")

    def test_generator_reproduces_committed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            # another process with another hash seed must write the same bytes
            env = dict(os.environ, PYTHONHASHSEED="12345")
            done = subprocess.run([sys.executable, str(GENERATOR), "--out", tmp],
                                  capture_output=True, text=True, env=env, timeout=600)
            self.assertEqual(done.returncode, 0, done.stderr)
            for name in SCENARIOS:
                fresh = (Path(tmp) / f"{name}.json.gz").read_bytes()
                committed = (FIXTURES / f"{name}.json.gz").read_bytes()
                self.assertNotIn(b"\r", gzip.decompress(fresh))
                self.assertEqual(fresh, committed, f"{name}.json.gz differs from a fresh recording")


# ---------------------------------------------------------------------------
# The mock's replay, without a browser
# ---------------------------------------------------------------------------

class SimReplayTest(unittest.TestCase):
    """mock_server.Timeline driven by hand: a launched command is answered with that option's frames."""

    def publish(self, timeline, count=1):
        for _ in range(count):
            timeline._step()

    def send(self, timeline, body):
        rule = timeline.find_rule(body)
        return timeline.submit(body, rule)

    def test_each_option_is_answered_with_its_own_frames_to_the_end(self):
        for name, preset in SCENARIOS.items():
            fx = load(name)
            for kind, short in OPTIONS.items():
                with self.subTest(name=name, option=kind):
                    timeline = mock_server.Timeline(fx, 1000)
                    shift = timeline.shift_features()
                    self.assertEqual(value_of(shift, "idSimulationRun"), "run-0001")
                    self.assertEqual(value_of(shift, "run_state"), "running")

                    started = self.send(timeline, command("run.start_preset", preset, "run-0001"))
                    self.assertEqual((started["ack"]["status"], started["ack"]["new_run"]), ("applied", "run-0002"))
                    self.publish(timeline)
                    self.assertEqual(timeline.state, "preset_run")
                    self.publish(timeline, len(fx["states"]["preset_run"]["frames"]))
                    self.assertEqual(timeline.state, "decision")
                    shift = timeline.shift_features()
                    self.assertEqual(value_of(shift, "run_state"), "paused")
                    decision_id = value_of(element_of(shift, "incident"), "decision_id")
                    decision_tick = value_of(shift, "tick")

                    # another decision id is refused, the right one launches the option
                    stale = self.send(timeline, command("action.execute_option", f"option-{kind}", "run-0002",
                                                        decision_id="run-0002-d9"))
                    self.assertEqual((stale["ack"]["status"], stale["ack"]["reason"]), ("rejected", "stale_decision"))
                    sent = self.send(timeline, command("action.execute_option", f"option-{kind}", "run-0002",
                                                       decision_id=decision_id))
                    self.assertEqual((sent["ack"]["status"], sent["goto"]), ("applied", f"{short}_exec"))
                    self.publish(timeline)
                    self.assertEqual(timeline.state, f"{short}_exec")
                    shift = timeline.shift_features()
                    self.assertEqual(value_of(shift, "tick"), decision_tick)
                    self.assertEqual(value_of(element_of(shift, f"option-{kind}"), "state"), "executing")

                    frames = len(fx["states"][f"{short}_exec"]["frames"])
                    self.publish(timeline, frames)
                    self.assertEqual(timeline.state, f"{short}_done")
                    shift = timeline.shift_features()
                    self.assertEqual(value_of(shift, "tick"), decision_tick + 900)
                    self.assertEqual(value_of(element_of(shift, "incident"), "state"), "done")
                    self.assertEqual(value_of(element_of(shift, f"option-{kind}"), "state"), "done")
                    # the model time stands while the run is paused; the heartbeat goes on
                    seq = value_of(shift, "publication_seq")
                    self.publish(timeline, 3)
                    again = timeline.shift_features()
                    self.assertEqual(value_of(again, "tick"), decision_tick + 900)
                    self.assertEqual(value_of(again, "publication_seq"), seq + 3)
                    # the run twins of the archive are served, the finished one is this option's
                    run = timeline.thing(f"{NS}:run-0002")
                    self.assertIsNotNone(run)
                    self.assertEqual(value_of(run["features"], "executed_option"), f"option-{kind}")
                    self.assertIsNotNone(timeline.thing(f"{NS}:run-0001"))

    def test_the_run_twins_are_not_there_before_they_are_listed(self):
        fx = load("sim_instability")
        timeline = mock_server.Timeline(fx, 1000)
        self.assertIsNone(timeline.thing(f"{NS}:run-0001"))
        self.assertIsNone(timeline.thing(f"{NS}:run-0002"))

    def test_a_command_outside_the_story_is_not_scripted(self):
        timeline = mock_server.Timeline(load("sim_instability"), 1000)
        other = self.send(timeline, command("run.start_preset", "p-sensor", "run-0001"))
        self.assertEqual((other["ack"]["status"], other["ack"]["reason"]), ("rejected", "not_scripted"))


def element_of(shift, local):
    return element(shift, local)


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

class SimValidationTest(BrowserTestCase):
    """Every recorded frame through the interface's own validation (validate.js), against the recorded attributes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock = MockServer("sim_instability").start()
        cls.addClassCleanup(cls.mock.stop)

    def test_every_frame_of_every_scenario_is_a_valid_snapshot(self):
        self.page.goto(self.mock.url + "/__mock__/")
        total = 0
        for name in SCENARIOS:
            fx = load(name)
            things = fx["attribute_sets"]["t1"]
            attributes = self.page.evaluate("(async () => {"
                                            "const V = await import('/js/validate.js');"
                                            f"const things = {json.dumps(things)};"
                                            "const mine = V.validateMine(things.find((t) => t.thingId === 'team040.mine:mine'));"
                                            "if (!mine.ok) return {error: mine.detail};"
                                            "const built = V.buildAttributes(mine, things);"
                                            "if (!built.ok) return {error: built.detail};"
                                            "window.__attributes = built.attributes; return {ok: true}; })()")
            self.assertEqual(attributes, {"ok": True}, f"{name}: the attributes")
            for state_name, state in fx["states"].items():
                frames = state["frames"]
                for start in range(0, len(frames), 12):
                    chunk = frames[start:start + 12]
                    problems = self.page.evaluate(
                        "(async () => {"
                        "const V = await import('/js/validate.js');"
                        f"const frames = {json.dumps(chunk)};"
                        "const bad = [];"
                        "frames.forEach((features, i) => {"
                        "  const r = V.validateShift({body: {features, _modified: new Date().toISOString(), _revision: 1},"
                        "    dateMs: Date.now()}, window.__attributes);"
                        "  if (!r.ok) bad.push(i + ': ' + r.code + ' ' + r.detail);"
                        "  else {"
                        "    const incident = r.snapshot.scene['team040.mine:incident'].values;"
                        "    const causes = incident.causes || [];"
                        "    if (!causes.every((c) => c && typeof c === 'object' && typeof c.trigger === 'string')) bad.push(i + ': a cause is not read');"
                        "  }"
                        "});"
                        "return bad; })()", timeout=60.0)
                    self.assertEqual(problems, [], f"{name}/{state_name} from frame {start}")
                    total += len(chunk)
        self.assertGreater(total, 1000)


class SimReadersTest(BrowserTestCase):
    """The readers accept the forms the simulation publishes (SIM.md), next to the forms of the contract draft."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock = MockServer("sim_instability").start()
        cls.addClassCleanup(cls.mock.stop)

    def setUp(self):
        super().setUp()
        self.page.goto(self.mock.url + "/__mock__/")

    def js(self, body):
        return self.page.evaluate("(async () => {" + body + "})()")

    def test_a_cause_is_read_as_text_or_as_record(self):
        got = self.js("""
          const V = await import('/js/validate.js');
          const M = await import('/js/model.js');
          return {
            text: V.normalizeCause('passage_closed:w-04'), bare: V.normalizeCause('hazard'),
            record: V.normalizeCause({trigger: 'hazard', subject: 'zone-a', tick: 60}), other: V.normalizeCause(7),
            causes: M.causesOf({causes: ['hazard:zone-a', 'data_lost:zone-a', {trigger: 'passage_closed', subject: 'w-04', tick: 60}, 7]}),
          };""")
        self.assertEqual(got["text"], {"trigger": "passage_closed", "subject": "w-04"})
        self.assertEqual(got["bare"], "hazard", "a text without a colon is no cause the readers can use")
        self.assertEqual(got["record"], {"trigger": "hazard", "subject": "zone-a", "tick": 60})
        self.assertEqual(got["other"], 7)
        self.assertEqual([(c["trigger"], c.get("subject")) for c in got["causes"]],
                         [("hazard", "zone-a"), ("data_lost", "zone-a"), ("passage_closed", "w-04")])

    def test_the_last_known_state_is_said_only_for_data_that_are_not_fresh(self):
        got = self.js("""
          const T = await import('/js/text.js');
          const known = {last_known_hazard_state: 'danger', last_known_hazard_tick: 810};
          return {
            fresh: T.lastKnownText({...known, data_quality: 'fresh'}, 820),
            stale: T.lastKnownText({...known, data_quality: 'stale'}, 820),
            lost: T.lastKnownText({...known, data_quality: 'lost'}, 820),
            noQuality: T.lastKnownText(known, 820),
          };""")
        self.assertEqual(got["fresh"], "")
        self.assertTrue(got["stale"].startswith("последнее известное: опасно"), got)
        self.assertEqual(got["stale"], got["lost"])
        self.assertEqual(got["stale"], got["noQuality"])

    def test_a_route_over_workings_without_sensors_is_not_called_a_zone(self):
        got = self.js("""
          const T = await import('/js/text.js');
          return [T.crossesText({egress_crosses: 'unknown'}), T.crossesText({egress_crosses: 'danger'}),
                  T.crossesText({egress_crosses: 'normal'}), T.crossesText({})];""")
        self.assertEqual(got, ["маршрут проходит через места с неизвестным состоянием",
                               "маршрут проходит через участок «опасно»", "", ""])

    def test_the_codes_of_the_simulation_have_words(self):
        got = self.js("""
          const T = await import('/js/text.js');
          const R = await import('/js/view/runs.js');
          const codes = ['run.started', 'run.finished', 'decision.opened', 'decision.selected', 'command.applied',
            'sensor.state_changed', 'hazard.transition', 'work.changed', 'withdrawal.changed', 'worker.exited',
            'route.changed', 'worker.state_changed', 'condition.set'];
          const run = (reason) => ({name: reason, values: {state: 'finished', completion_reason: reason, comparison_key: 'k', comparable: true}});
          const groups = R.groupRuns([run('horizon'), run('horizon_reached'), run('reset')], ['horizon', 'horizon_reached', 'reset']);
          return {
            unknown: codes.filter((code) => !T.VOCAB.journalCode[code]),
            ending: T.codeLabel('completionReason', 'horizon'),
            flags: groups.flatMap((g) => g.runs.map((item) => [item.run.name, item.interrupted, item.unclassified, item.takesPart])),
          };""")
        self.assertEqual(got["unknown"], [])
        self.assertEqual(got["ending"], "достигнут горизонт расчёта")
        self.assertEqual(sorted(got["flags"]), [["horizon", False, False, True], ["horizon_reached", False, False, True],
                                                ["reset", True, False, False]])

    def test_a_preset_of_the_simulation_has_its_step(self):
        got = self.js("""
          const P = await import('/js/view/pending.js');
          const state = {attributes: {mine: {presets: [
            {id: 'p-a', label: 'A', at_s: 60, type: 'condition.close_working', target: 'w-04'},
            {id: 'p-b', label: 'B', expect: 'detour', schedule: [{at_sim_s: 30, type: 'condition.close_working', target: 'w-12'}]},
            {id: 'p-c'}]}}};
          return P.presetsOf(state).map((p) => [p.id, p.schedule]);""")
        self.assertEqual(got, [["p-a", [{"at_sim_s": 60, "type": "condition.close_working", "target": "w-04"}]],
                               ["p-b", [{"at_sim_s": 30, "type": "condition.close_working", "target": "w-12"}]],
                               ["p-c", []]])


class SimScenarioTest(BrowserTestCase):
    """Each scenario by its real controls: the preset, each of the three options, to the end."""

    viewport = (1920, 1080)
    chrome_args = SWIFTSHADER

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock = MockServer("sim_instability", extra_args=("--publication-ms", PUBLICATION_MS)).start()
        cls.addClassCleanup(cls.mock.stop)

    # ---- helpers ----------------------------------------------------------------------------

    def open(self, scenario, mode="scheme"):
        self.mock.scenario(scenario)
        self.page.goto("about:blank")
        self.page.goto(self.mock.url + f"/#/scheme?mode={mode}")
        self.page.wait_for("document.body.dataset.boot === 'ready' && document.body.dataset.snapshot === 'ok'", timeout=30)
        if mode == "3d":
            # the 3D stage has drawn the three levels (the surface included) and the twelve workings
            self.page.wait_for("(() => { const s = document.querySelector('#stage').dataset;"
                               " return s.stageMode === '3d' && Number(s.frames) > 0 && s.rendering === 'idle'"
                               " && s.levels === '3' && s.workings === '12'; })()", timeout=60,
                               message="the 3D stage draws the simulation's mine")
        else:
            self.page.wait_for("document.querySelector('[data-testid=\"scheme-svg\"]')?.dataset.drawn === 'true'"
                               " && document.querySelectorAll('#scheme .worker').length === 6", timeout=30)
        self.assertEqual(self.page.evaluate("document.body.dataset.situation"), "norm")

    def start_preset(self, preset):
        page = self.page
        page.click('[data-testid="stand-toggle"]')
        page.wait_for("document.body.dataset.stand === 'open'", timeout=5)
        time.sleep(0.6)
        page.click(f'[data-preset="{preset}"] button', timeout=5)
        page.wait_for("!!document.querySelector('[data-testid=dialog-confirm]')", timeout=5)
        page.click('[data-testid="dialog-confirm"]')
        page.wait_for("document.body.dataset.situation === 'decision'", timeout=30, message="the decision point")
        page.click('[data-testid="stand-toggle"]')
        page.wait_for("document.body.dataset.stand === 'closed'", timeout=5)
        page.wait_for("document.querySelector('#panel')?.dataset.panelMode === 'decision'", timeout=10)

    def cards(self):
        return self.page.evaluate("""[...document.querySelectorAll('#panel .dp-card')].map((card) => ({
            kind: card.dataset.optionKind, state: card.dataset.state,
            unpublished: card.classList.contains('is-unpublished'), unavailable: card.classList.contains('is-unavailable')}))""")

    def launch(self, kind):
        page = self.page
        page.click(f"#panel .dp-card[data-option-kind={kind}]")
        page.wait_for(f"document.querySelector('#panel .dp-card[data-option-kind={kind}]').getAttribute('aria-checked') === 'true'")
        page.click('[data-testid=btn-execute]')
        page.wait_for("!!document.querySelector('[data-testid=dialog-confirm]')", timeout=5)
        page.click('[data-testid="dialog-confirm"]')

    def commands(self, type_):
        return [e for e in self.mock.log()["entries"]
                if e.get("kind") == "command" and (e.get("body") or {}).get("type") == type_]

    def run_story(self, scenario, kind, mode):
        preset = SCENARIOS[scenario]
        self.open(scenario, mode)
        page = self.page
        self.start_preset(preset)
        started = self.commands("run.start_preset")
        self.assertEqual(len(started), 1)
        self.assertEqual((started[0]["body"]["target"], started[0]["ack"]["status"], started[0]["ack"]["new_run"]),
                         (preset, "applied", "run-0002"))
        self.assertEqual(page.evaluate("document.body.dataset.runState"), "paused")

        # the decision: three options offered, each with the forecast the simulation computed
        cards = self.cards()
        self.assertEqual([c["kind"] for c in cards], ["observe", "stop_withdraw_zone", "withdraw_all"])
        self.assertEqual({c["state"] for c in cards}, {"offered"}, cards)
        self.assertFalse(any(c["unpublished"] or c["unavailable"] for c in cards), cards)

        self.launch(kind)
        page.wait_for("document.body.dataset.situation === 'executing'", timeout=15, message="the option executes")
        page.wait_for("document.querySelector('#panel')?.dataset.panelMode === 'executing'", timeout=10)
        executed = self.commands("action.execute_option")
        self.assertEqual(len(executed), 1)
        body = executed[0]["body"]
        self.assertEqual((body["target"], body["decision_id"]), (f"option-{kind}", "run-0002-d1"))
        self.assertEqual((executed[0]["ack"]["status"], executed[0]["ack"]["reason"]), ("applied", "none"))
        self.assertEqual(page.evaluate("document.body.dataset.runState"), "running")

        page.wait_for("document.body.dataset.situation === 'done'", timeout=60, message="the end of the incident")
        page.wait_for("document.querySelector('#panel')?.dataset.panelMode === 'done'", timeout=10)
        self.assertEqual(page.evaluate("document.body.dataset.runState"), "paused")
        wait_until(lambda: page.evaluate("document.querySelector('#panel .dp__title')?.textContent.startsWith('Итог')"),
                   timeout=5, message="the result is on the panel")

        # the archive: the run just finished is the option's, the first one was cut short by the preset
        archive = self.mock.request("GET", f"/ditto/api/2/things/{NS}:run-0002?fields=features")
        self.assertEqual(archive["features"]["executed_option"]["properties"]["value"], f"option-{kind}")
        page.evaluate("location.hash = '#/runs'")
        page.wait_for("document.querySelectorAll('[data-testid=\"runs-table\"] tr[data-series=\"actual\"]').length >= 2",
                      timeout=15, message="both archived runs are listed")
        listed = page.evaluate("[...document.querySelectorAll('[data-testid=\"runs-table\"] tr[data-series=\"actual\"]')]"
                               ".map((row) => row.dataset.run)")
        self.assertEqual(sorted(listed), ["run-0001", "run-0002"])

    # ---- tests ------------------------------------------------------------------------------

    def test_every_option_of_every_scenario_by_the_real_controls(self):
        for scenario in SCENARIOS:
            for kind in OPTIONS:
                with self.subTest(scenario=scenario, option=kind):
                    self.run_story(scenario, kind, "scheme")

    def test_the_3d_stage_follows_each_scenario(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                self.run_story(scenario, "stop_withdraw_zone", "3d")

    def test_the_incident_is_said_with_its_causes(self):
        """The simulation names a cause as a text ("passage_closed:w-04"); the panel says what it is and where."""
        expected = {
            "sim_instability": "Участок A — опасно",
            "sim_detour": "Участок A — закрыт проход В-04",
            "sim_trapped": "Участок A — закрыт проход В-07",
            "sim_sensor": "Участок A — потеряны данные",
        }
        for scenario, line in expected.items():
            with self.subTest(scenario=scenario):
                self.open(scenario)
                self.start_preset(SCENARIOS[scenario])
                said = self.page.evaluate("document.querySelector('[data-testid=decide-what] .dp-what__line')?.textContent")
                self.assertEqual(said.replace(" ", " "), line)

    def test_the_stand_lists_the_presets_with_their_step(self):
        self.open("sim_detour")
        page = self.page
        page.click('[data-testid="stand-toggle"]')
        page.wait_for("document.body.dataset.stand === 'open'", timeout=5)
        time.sleep(0.6)
        notes = page.evaluate("Object.fromEntries([...document.querySelectorAll('[data-preset]')]"
                              ".map((li) => [li.dataset.preset, li.querySelector('.note').textContent]))")
        self.assertEqual(sorted(notes), sorted(SCENARIOS.values()))
        self.assertIn("Закрыть выработку: В-04", notes["p-detour"])
        self.assertIn("в 00:01:00 модельного времени", notes["p-detour"])
        self.assertIn("Потерять связь с датчиком: Э-A", notes["p-sensor"])


if __name__ == "__main__":
    unittest.main()
