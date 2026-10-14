"""The pure modules of the interface, run in headless Chrome.

Node.js is not installed, so the only JavaScript runtime is the browser. Each
test opens a page of the mock server's origin that does not run the
application (the control page) and imports the module under test with a
dynamic `import()`. Where real data are needed they are fetched from the mock.

    python -m unittest discover -s team/ui/tests -t team/ui -p "test_logic.py" -v
"""

from __future__ import annotations

import json

from browser_support import BrowserTestCase, MockServer

NBSP = " "

# Shared by the tests that need the attributes and a shift response of the current scenario.
LOAD = r"""
  const {createApi} = await import('/js/api.js');
  const V = await import('/js/validate.js');
  const M = await import('/js/model.js');
  const api = createApi();
  async function loadAttributes() {
    const mine = await api.readMine();
    const checked = V.validateMine(mine.body);
    if (!checked.ok) throw new Error('mine rejected: ' + checked.detail);
    const rest = await api.readAttributes(checked.manifest);
    if (!rest.ok) throw new Error('attributes not read: ' + JSON.stringify(rest));
    return V.buildAttributes(checked, rest.body).attributes;
  }
  const clone = (value) => JSON.parse(JSON.stringify(value));
"""


def plain(text):
    """Texts use no-break spaces between a number and its unit; tests compare with ordinary ones."""
    return text.replace(NBSP, " ") if isinstance(text, str) else text


class LogicTestCase(BrowserTestCase):
    scenario = "normal"
    mock_args = ()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock = MockServer(cls.scenario, extra_args=cls.mock_args).start()
        cls.addClassCleanup(cls.mock.stop)

    def setUp(self):
        super().setUp()
        # A page of the same origin that does not start the application.
        self.page.goto(self.mock.url + "/__mock__/")

    def js(self, body, timeout=20.0):
        """Run statements inside an async function of the page and return its result."""
        return self.page.evaluate("(async () => {" + body + "})()", timeout=timeout)


class ValidateTest(LogicTestCase):
    mock_args = ("--publication-ms", "100")

    def test_fixture_snapshot_is_accepted_and_normalized(self):
        self.mock.scenario("normal")
        result = self.js(LOAD + r"""
          const attributes = await loadAttributes();
          const response = await api.readShift();
          const checked = V.validateShift(response, attributes);
          if (!checked.ok) return {ok: false, detail: checked.detail};
          const s = checked.snapshot;
          return {
            ok: true, run: s.run, tick: s.tick, simTimeS: s.simTimeS, seq: s.seq, runState: s.runState,
            pauseReason: s.pauseReason, topologyVersion: s.topologyVersion,
            modifiedIsText: typeof s.modified === 'string', modifiedMs: s.modifiedMs, dateMs: s.dateMs,
            revision: s.revision, sceneIds: Object.keys(s.scene).length,
            sceneKeysMatch: JSON.stringify(Object.keys(s.scene)) === JSON.stringify(attributes.dynamicIds),
            shiftHasScene: 'scene' in s.shift.values, total: s.shift.values.workers_total,
            worker: s.scene['team040.mine:worker-01'], info: checked.info,
            manifest: attributes.manifest.length, dynamic: attributes.dynamicIds.length,
          };
        """)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["run"], "run-0005")
        self.assertEqual(result["runState"], "running")
        self.assertEqual(result["pauseReason"], "none")
        self.assertEqual(result["topologyVersion"], "t1")
        self.assertEqual((result["manifest"], result["dynamic"], result["sceneIds"]), (77, 72, 72))
        self.assertTrue(result["sceneKeysMatch"])
        self.assertFalse(result["shiftHasScene"], "the scene must not be kept twice")
        self.assertEqual(result["total"], 14)
        self.assertTrue(result["modifiedIsText"])
        self.assertIsInstance(result["modifiedMs"], (int, float))
        self.assertIsInstance(result["dateMs"], (int, float))
        self.assertIsInstance(result["revision"], int)
        self.assertEqual(result["info"]["seq"], result["seq"])
        self.assertEqual(result["info"]["run"], "run-0005")
        worker = result["worker"]
        self.assertEqual(worker["values"]["status"], "working")
        self.assertEqual(worker["values"]["route"], ["w-33", "w-34", "w-31"])
        self.assertEqual(worker["units"]["offset_m"], "m")
        self.assertNotIn("status", worker["units"])

    def test_every_violation_is_rejected_with_its_code(self):
        self.mock.scenario("normal")
        cases = self.js(LOAD + r"""
          const attributes = await loadAttributes();
          const good = await api.readShift();
          const NS = 'team040.mine:';
          const scene = (r) => r.body.features.scene.properties.value;
          const element = (r, name) => scene(r).find((item) => item.thingId === NS + name);
          const mutations = {
            no_date: (r) => { r.dateMs = null; },
            no_modified: (r) => { delete r.body._modified; },
            bad_modified: (r) => { r.body._modified = 'yesterday'; },
            no_revision: (r) => { delete r.body._revision; },
            contract_version: (r) => { r.body.features.contract_version.properties.value = 2; },
            no_contract_version: (r) => { delete r.body.features.contract_version; },
            topology: (r) => { r.body.features.topology_version.properties.value = 't9'; },
            missing_id: (r) => { scene(r).splice(scene(r).findIndex((item) => item.thingId === NS + 'worker-14'), 1); },
            extra_id: (r) => { scene(r).push({thingId: NS + 'w-99', features: clone(element(r, 'w-01').features)}); },
            duplicate_id: (r) => { scene(r).push(clone(element(r, 'worker-14'))); },
            mixed_tick: (r) => { element(r, 'sens-geo-02').features.tick.properties.value -= 10; },
            mixed_sim_time: (r) => { element(r, 'zone-a').features.sim_time_s.properties.value -= 10; },
            mixed_run: (r) => { element(r, 'exit-ramp').features.idSimulationRun.properties.value = 'run-0004'; },
            shift_field: (r) => { delete r.body.features.workers_total; },
            shift_scene: (r) => { delete r.body.features.scene; },
            worker_egress: (r) => { delete element(r, 'worker-05').features.egress_status; },
            worker_offset: (r) => { delete element(r, 'worker-05').features.offset_m; },
            working_passability: (r) => { delete element(r, 'w-12').features.passability; },
            working_quality: (r) => { delete element(r, 'w-12').features.data_quality; },
            zone_work_state: (r) => { delete element(r, 'zone-b').features.work_state; },
            zone_withdrawal: (r) => { delete element(r, 'zone-b').features.withdrawal_state; },
            sensor_measured: (r) => { delete element(r, 'sens-ext-05').features.measured_at_tick; },
            sensor_link: (r) => { delete element(r, 'sens-ext-05').features.link_state; },
            exit_state: (r) => { delete element(r, 'exit-shaft').features.state; },
            incident_state: (r) => { delete element(r, 'incident').features.state; },
            option_state: (r) => { delete element(r, 'option-observe').features.state; },
            journal_events: (r) => { delete element(r, 'journal').features.events; },
            element_tick: (r) => { delete element(r, 'w-01').features.tick; },
            null_value: (r) => { element(r, 'w-01').features.hazard_state.properties.value = null; },
            wrong_type: (r) => { r.body.features.tick.properties.value = '12'; },
            scene_not_array: (r) => { r.body.features.scene.properties.value = {}; },
            element_shape: (r) => { delete element(r, 'w-01').features; },
            no_features: (r) => { r.body.features = null; },
            not_an_object: (r) => { r.body = [1, 2]; },
          };
          const out = {};
          for (const [name, mutate] of Object.entries(mutations)) {
            const response = clone(good);
            mutate(response);
            const checked = V.validateShift(response, attributes);
            out[name] = checked.ok ? {ok: true} : {code: checked.code, params: checked.params, detail: checked.detail};
          }
          // Still full snapshots: optional features absent, a worker who is out has no position.
          const optional = clone(good);
          for (const name of ['danger_exposure_person_s', 'unknown_exposure_person_s', 'all_out', 'downtime_s']) {
            delete optional.body.features[name];
          }
          const outWorker = element(optional, 'worker-05').features;
          outWorker.status.properties.value = 'out';
          delete outWorker.at_working; delete outWorker.offset_m;
          out.optional_absent = {ok: V.validateShift(optional, attributes).ok};
          const reordered = clone(good);
          scene(reordered).reverse();
          out.reordered = {ok: V.validateShift(reordered, attributes).ok};
          out.good = {ok: V.validateShift(clone(good), attributes).ok};
          return out;
        """)
        for name in ("good", "optional_absent", "reordered"):
            self.assertEqual(cases[name], {"ok": True}, name)
        expected = {
            "no_date": ("no_metadata", {"field": "Date"}),
            "no_modified": ("no_metadata", {"field": "_modified"}),
            "bad_modified": ("no_metadata", {"field": "_modified"}),
            "no_revision": ("no_metadata", {"field": "_revision"}),
            "contract_version": ("contract_version", {"expected": 1, "actual": 2}),
            "no_contract_version": ("missing_field", {"thing": "shift", "field": "contract_version"}),
            "topology": ("topology_mismatch", {"attributes": "t1", "shift": "t9"}),
            "missing_id": ("scene_missing_id", {"ids": ["team040.mine:worker-14"]}),
            "extra_id": ("scene_extra_id", {"ids": ["team040.mine:w-99"]}),
            "duplicate_id": ("scene_duplicate_id", {"ids": ["team040.mine:worker-14"]}),
            "mixed_tick": ("scene_mixed_tick", {"thing": "sens-geo-02", "field": "tick"}),
            "mixed_sim_time": ("scene_mixed_tick", {"thing": "zone-a", "field": "sim_time_s"}),
            "mixed_run": ("scene_mixed_run", {"thing": "exit-ramp", "actual": "run-0004", "expected": "run-0005"}),
            "shift_field": ("missing_field", {"thing": "shift", "field": "workers_total"}),
            "shift_scene": ("missing_field", {"thing": "shift", "field": "scene"}),
            "worker_egress": ("missing_field", {"thing": "worker-05", "field": "egress_status"}),
            "worker_offset": ("missing_field", {"thing": "worker-05", "field": "offset_m"}),
            "working_passability": ("missing_field", {"thing": "w-12", "field": "passability"}),
            "working_quality": ("missing_field", {"thing": "w-12", "field": "data_quality"}),
            "zone_work_state": ("missing_field", {"thing": "zone-b", "field": "work_state"}),
            "zone_withdrawal": ("missing_field", {"thing": "zone-b", "field": "withdrawal_state"}),
            "sensor_measured": ("missing_field", {"thing": "sens-ext-05", "field": "measured_at_tick"}),
            "sensor_link": ("missing_field", {"thing": "sens-ext-05", "field": "link_state"}),
            "exit_state": ("missing_field", {"thing": "exit-shaft", "field": "state"}),
            "incident_state": ("missing_field", {"thing": "incident", "field": "state"}),
            "option_state": ("missing_field", {"thing": "option-observe", "field": "state"}),
            "journal_events": ("missing_field", {"thing": "journal", "field": "events"}),
            "element_tick": ("missing_field", {"thing": "w-01", "field": "tick"}),
            "null_value": ("malformed", {"thing": "w-01", "field": "hazard_state"}),
            "wrong_type": ("malformed", {"thing": "shift", "field": "tick"}),
            "scene_not_array": ("malformed", {"thing": "shift", "field": "scene"}),
            "element_shape": ("malformed", {"thing": "shift", "field": "scene"}),
            "no_features": ("malformed", {}),
            "not_an_object": ("malformed", {}),
        }
        self.assertEqual(set(cases) - {"good", "optional_absent", "reordered"}, set(expected))
        for name, (code, params) in expected.items():
            with self.subTest(violation=name):
                got = cases[name]
                self.assertEqual(got.get("code"), code, got)
                for key, value in params.items():
                    self.assertEqual(got["params"].get(key), value, got)
                self.assertTrue(got["detail"], "a rejection explains itself")

    def test_invalid_scenarios_of_the_mock_are_rejected(self):
        expected = {
            "invalid_missing_id": ("scene_missing_id", {"ids": ["team040.mine:worker-14"]}),
            "invalid_duplicate_id": ("scene_duplicate_id", {"ids": ["team040.mine:worker-14"]}),
            "invalid_mixed_tick": ("scene_mixed_tick", {"thing": "sens-geo-02", "field": "tick"}),
            "invalid_missing_field": ("missing_field", {"thing": "worker-05", "field": "egress_status"}),
            "invalid_contract_version": ("contract_version", {"actual": 2, "expected": 1}),
            "invalid_no_metadata": ("no_metadata", {"field": "_modified"}),
            "topology_mismatch": ("topology_mismatch", {"attributes": "t1", "shift": "t2"}),
        }
        for scenario, (code, params) in expected.items():
            with self.subTest(scenario=scenario):
                self.mock.scenario(scenario)
                got = self.js(LOAD + r"""
                  const attributes = await loadAttributes();
                  const started = performance.now();
                  let accepted = 0;
                  while (performance.now() - started < 5000) {
                    const checked = V.validateShift(await api.readShift(), attributes);
                    if (!checked.ok) return {code: checked.code, params: checked.params, accepted, seq: checked.info.seq};
                    accepted += 1;
                    await new Promise((resolve) => setTimeout(resolve, 40));
                  }
                  return {code: null, accepted};
                """)
                self.assertEqual(got["code"], code, got)
                for key, value in params.items():
                    self.assertEqual(got["params"].get(key), value, got)
                self.assertIsInstance(got["seq"], int, "the heartbeat stays readable in a rejected answer")
                if scenario != "topology_mismatch":
                    self.assertGreaterEqual(got["accepted"], 1, "the first publications of the scenario are full")

    def test_mine_attributes_are_checked(self):
        self.mock.scenario("normal")
        got = self.js(LOAD + r"""
          const mine = (await api.readMine()).body;
          const check = (mutate) => {
            const thing = clone(mine);
            mutate(thing);
            const checked = V.validateMine(thing);
            return checked.ok ? 'ok' : [checked.code, checked.params.field || null];
          };
          const checked = V.validateMine(mine);
          const things = (await api.readAttributes(checked.manifest)).body;
          const incomplete = V.buildAttributes(checked, things.filter((thing) => thing.thingId !== 'team040.mine:w-07'));
          const whole = V.buildAttributes(checked, [...things].reverse());
          return {
            good: check(() => {}),
            version: check((t) => { t.attributes.contract_version = 3; }),
            noVersion: check((t) => { delete t.attributes.contract_version; }),
            noManifest: check((t) => { delete t.attributes.manifest; }),
            badManifest: check((t) => { t.attributes.manifest = 'a,b'; }),
            duplicateManifest: check((t) => { t.attributes.manifest.push(t.attributes.manifest[3]); }),
            unsafeId: check((t) => { t.attributes.manifest[5] = 'team040.mine:w 01&x=1'; }),
            noDynamic: check((t) => { delete t.attributes.dynamic_ids; }),
            outside: check((t) => { t.attributes.dynamic_ids.push('team040.mine:w-99'); }),
            noTopology: check((t) => { delete t.attributes.topology_version; }),
            noNodes: check((t) => { delete t.attributes.nodes; }),
            noAttributes: check((t) => { delete t.attributes; }),
            incomplete: [incomplete.code, incomplete.params.ids, incomplete.params.total],
            wholeOk: whole.ok,
            order: JSON.stringify(Object.keys(whole.attributes.things)) === JSON.stringify(checked.manifest),
            kind: whole.attributes.things['team040.mine:w-07'].kind,
          };
        """)
        self.assertEqual(got["good"], "ok")
        self.assertEqual(got["version"], ["contract_version", None])
        self.assertEqual(got["noVersion"], ["missing_field", "contract_version"])
        self.assertEqual(got["noManifest"], ["missing_field", "manifest"])
        self.assertEqual(got["badManifest"], ["malformed", "manifest"])
        self.assertEqual(got["duplicateManifest"], ["malformed", "manifest"])
        self.assertEqual(got["unsafeId"], ["malformed", "manifest"])
        self.assertEqual(got["noDynamic"], ["missing_field", "dynamic_ids"])
        self.assertEqual(got["outside"], ["malformed", "dynamic_ids"])
        self.assertEqual(got["noTopology"], ["missing_field", "topology_version"])
        self.assertEqual(got["noNodes"], ["missing_field", "nodes"])
        self.assertEqual(got["noAttributes"], ["malformed", "attributes"])
        self.assertEqual(got["incomplete"], ["manifest_incomplete", ["team040.mine:w-07"], 77])
        self.assertTrue(got["wholeOk"])
        self.assertTrue(got["order"], "attributes are indexed in manifest order whatever the answer order")
        self.assertEqual(got["kind"], "working")


class ApiTest(LogicTestCase):
    def test_batches_are_small_complete_and_restored_to_request_order(self):
        got = self.js(LOAD + r"""
          const mine = V.validateMine((await api.readMine()).body);
          const read = await api.readAttributes(mine.manifest);
          const unknown = await api.readAttributes(['team040.mine:w-01', 'team040.mine:nothing-here']);
          const unsafe = await api.readAttributes(['team040.mine:w-01&x=1']);
          const runs = await api.readRuns(['run-0002', 'run-0001']);
          const badRun = await api.readRuns(['run 1']);
          return {
            ok: read.ok,
            order: JSON.stringify(read.body.map((thing) => thing.thingId)) === JSON.stringify(mine.manifest),
            unknown: [unknown.ok, unknown.kind, unknown.missing],
            unsafe: [unsafe.ok, unsafe.kind],
            runs: runs.body.map((thing) => thing.thingId),
            runHasFeatures: 'features' in runs.body[0] && 'attributes' in runs.body[0],
            badRun: [badRun.ok, badRun.kind],
          };
        """)
        self.assertTrue(got["ok"])
        self.assertTrue(got["order"])
        self.assertEqual(got["unknown"], [False, "incomplete", ["team040.mine:nothing-here"]])
        self.assertEqual(got["unsafe"], [False, "incomplete"])
        self.assertEqual(got["runs"], ["team040.mine:run-0002", "team040.mine:run-0001"])
        self.assertTrue(got["runHasFeatures"])
        self.assertEqual(got["badRun"], [False, "incomplete"])
        batches = [entry["url"] for entry in self.page.requests if "/ditto/api/2/things?ids=" in entry["url"]]
        attribute_batches = [url for url in batches if url.endswith("&fields=thingId,attributes")]
        sizes = [len(url.split("ids=")[1].split("&")[0].split(",")) for url in attribute_batches]
        self.assertEqual(sizes[:4], [20, 20, 20, 17], "77 manifest ids go out as four batches of at most 20")
        self.assertTrue(all(size <= 20 for size in sizes))
        self.assertFalse([url for url in batches if "nothing-here" not in url and "x=1" in url],
                         "an id that is not a safe thingId never reaches a URL")

    def test_failures_are_told_apart(self):
        got = {}
        self.mock.scenario("empty")
        got["not_found"] = self.js(LOAD + r"""
          const mine = await api.readMine();
          return [mine.ok, mine.kind, mine.status];
        """)
        self.mock.scenario("normal")
        self.mock.fault("http_502")
        got["http"] = self.js(LOAD + "const r = await api.readShift(); return [r.ok, r.kind, r.status];")
        self.mock.fault("drop")
        got["network"] = self.js(LOAD + "const r = await api.readShift(); return [r.ok, r.kind, r.status];")
        self.mock.fault("hang")
        got["timeout"] = self.js(LOAD + r"""
          const started = performance.now();
          const r = await api.readShift();
          return [r.ok, r.kind, r.status, Math.round(performance.now() - started)];
        """)
        self.mock.fault("none")
        got["ok"] = self.js(LOAD + r"""
          const r = await api.readShift();
          return [r.ok, r.status, typeof r.dateMs, Math.abs(r.dateMs - Date.parse(r.body._modified)) < 5000];
        """)
        self.assertEqual(got["not_found"], [False, "http", 404])
        self.assertEqual(got["http"], [False, "http", 502])
        self.assertEqual(got["network"], [False, "network", None])
        self.assertEqual(got["timeout"][:3], [False, "timeout", None])
        self.assertTrue(2800 <= got["timeout"][3] <= 3600, f"the request timeout is 3 s, measured {got['timeout'][3]} ms")
        self.assertEqual(got["ok"], [True, 200, "number", True])


class LinkTest(LogicTestCase):
    PRELUDE = r"""
      const L = await import('/js/link.js');
      let state = L.initialLink();
      const send = (event) => { state = L.reduceLink(state, event); };
      const at = (now) => L.deriveLink(state, now);
      const full = (time, seq, extra = {}) => send({type: 'poll_ok', at: time, seq, dateMs: 1000, modifiedMs: 1000,
        full: true, runState: 'running', ...extra});
      const pick = (status) => [status.link, status.publications, status.snapshot, status.blockReason];
    """

    def test_failures_degrade_then_stale_then_unavailable_and_recover(self):
        got = self.js(self.PRELUDE + r"""
          const out = {};
          out.initial = pick(at(0));
          send({type: 'polling_started', at: 0});
          out.waiting = pick(at(1999));
          out.neverRead = pick(at(2000));
          full(100, 5);
          out.ok = [...pick(at(100)), at(100).blocked, at(100).dataAgeS, at(100).failure];
          send({type: 'poll_failed', at: 1100, kind: 'http', status: 502});
          out.firstFailure = [...pick(at(1100)), at(1100).blocked, at(1100).failure];
          out.beforeStale = pick(at(2099));
          out.stale = [...pick(at(2100)), at(2100).blocked];
          send({type: 'poll_failed', at: 2100, kind: 'http', status: 502});
          out.second = pick(at(2100));
          send({type: 'poll_failed', at: 3100, kind: 'timeout', status: null});
          out.third = [...pick(at(3100)), at(3100).failure, at(3100).dataAgeS];
          full(4100, 6);
          out.recovered = [...pick(at(4100)), at(4100).blocked, at(4100).failure, at(4100).dataAgeS];
          return out;
        """)
        self.assertEqual(got["initial"], ["ok", "unknown", "none", "no_snapshot"])
        self.assertEqual(got["waiting"][0], "ok")
        self.assertEqual(got["neverRead"][0], "stale", "two seconds of polling without a snapshot is stale as well")
        self.assertEqual(got["ok"], ["ok", "alive", "ok", None, False, 0, None])
        self.assertEqual(got["firstFailure"],
                         ["degraded", "unknown", "ok", None, False, {"kind": "http", "status": 502}])
        self.assertEqual(got["beforeStale"][0], "degraded")
        self.assertEqual(got["stale"], ["stale", "unknown", "ok", "stale", True])
        self.assertEqual(got["second"][0], "stale")
        self.assertEqual(got["third"], ["unavailable", "unknown", "ok", "platform_unavailable",
                                        {"kind": "timeout", "status": None}, 3])
        self.assertEqual(got["recovered"], ["ok", "alive", "ok", None, False, None, 0])

    def test_stale_fires_during_a_pending_fetch(self):
        got = self.js(self.PRELUDE + r"""
          send({type: 'polling_started', at: 0});
          full(100, 5);
          // No event at all after the snapshot: the next fetch hangs.
          return {
            at1900: pick(at(2099)), at2100: [...pick(at(2100)), at(2100).blocked],
            stillKnown: at(4100).publications, unknownLater: at(4101).publications,
          };
        """)
        self.assertEqual(got["at1900"], ["ok", "alive", "ok", None])
        self.assertEqual(got["at2100"], ["stale", "alive", "ok", "stale", True])
        self.assertEqual(got["stillKnown"], "alive")
        self.assertEqual(got["unknownLater"], "unknown", "without answers nothing is claimed about publications")

    def test_frozen_sequence_stops_publications_also_when_paused(self):
        got = self.js(self.PRELUDE + r"""
          const out = {};
          for (const runState of ['running', 'paused']) {
            state = L.initialLink();
            send({type: 'polling_started', at: 0});
            for (let time = 0; time <= 4000; time += 1000) full(time, 7, {runState});
            out[runState] = {before: pick(at(4999))};
            full(5000, 7, {runState});
            out[runState].after = [...pick(at(5000)), at(5000).blocked, at(5000).dataAgeS];
            full(6000, 8, {runState});
            out[runState].moved = [...pick(at(6000)), at(6000).blocked];
          }
          // A paused model with a live heartbeat is a normal state.
          state = L.initialLink();
          send({type: 'polling_started', at: 0});
          for (let time = 0; time <= 9000; time += 1000) full(time, 100 + time / 1000, {runState: 'paused'});
          out.heartbeat = [...pick(at(9500)), at(9500).blocked];
          return out;
        """)
        for run_state in ("running", "paused"):
            with self.subTest(run_state=run_state):
                self.assertEqual(got[run_state]["before"], ["ok", "alive", "ok", None])
                self.assertEqual(got[run_state]["after"], ["ok", "stopped", "ok", "publications_stopped", True, 5])
                self.assertEqual(got[run_state]["moved"], ["ok", "alive", "ok", None, False])
        self.assertEqual(got["heartbeat"], ["ok", "alive", "ok", None, False])

    def test_initial_age_comes_from_date_minus_modified(self):
        got = self.js(self.PRELUDE + r"""
          const out = {
            ages: [L.initialAgeMs(31000, 0), L.initialAgeMs(1500, 0), L.initialAgeMs(700, 0), L.initialAgeMs(0, 900),
              L.initialAgeMs(null, 0)],
          };
          send({type: 'polling_started', at: 0});
          full(50, 9, {dateMs: 1031000, modifiedMs: 1000000});
          out.old = [...pick(at(50)), at(50).dataAgeS];
          // The same publication read again is aged by the monotonic clock, not by the headers of the later answer.
          full(1050, 9, {dateMs: 2000000, modifiedMs: 1000000});
          out.oldLater = at(1050).dataAgeS;
          full(2050, 10, {dateMs: 2000500, modifiedMs: 2000000});
          out.newPublication = [...pick(at(2050)), at(2050).dataAgeS];

          state = L.initialLink();
          send({type: 'polling_started', at: 0});
          full(0, 9, {dateMs: 1001500, modifiedMs: 1000000});
          out.young = [at(0).publications];
          for (let time = 1000; time <= 3000; time += 1000) full(time, 9, {dateMs: 1001500 + time, modifiedMs: 1000000});
          out.young.push(at(3499).publications, at(3500).publications);
          return out;
        """)
        # The header is cut to the whole second, so the difference is already a lower bound: nothing more is taken off.
        self.assertEqual(got["ages"], [31000, 1500, 700, 0, 0])
        self.assertEqual(got["old"], ["ok", "stopped", "ok", "publications_stopped", 31])
        self.assertEqual(got["oldLater"], 32)
        self.assertEqual(got["newPublication"], ["ok", "alive", "ok", None, 0])
        self.assertEqual(got["young"], ["alive", "alive", "stopped"])

    def test_new_sequence_after_a_gap_takes_its_age_from_the_platform_clocks(self):
        """M2: a number that is new to the page is as old as `Date - _modified` says, also after the first load."""
        got = self.js(self.PRELUDE + r"""
          const out = {};
          const T0 = 1700000000000;
          send({type: 'polling_started', at: 0});
          // Steady state: one publication a second, Date - _modified between 0 and 1 s. Nothing ever looks stopped.
          const steady = [];
          let seq = 100;
          for (let time = 0; time <= 20000; time += 1000) {
            const lag = [0, 400, 999, 1000][(time / 1000) % 4];
            full(time, seq += 1, {dateMs: T0 + time + lag, modifiedMs: T0 + time});
            steady.push(at(time), at(time + 999));
          }
          out.steady = [...new Set(steady.map((status) => [status.link, status.publications, status.blocked].join()))];
          out.steadyMaxAge = Math.max(...steady.map((status) => status.dataAgeS));

          // An outage, then the platform returns a state it kept: a new number, a minute old by its own clocks.
          for (let time = 21000; time <= 23000; time += 1000) send({type: 'poll_failed', at: time, kind: 'http', status: 502});
          out.outage = pick(at(23000));
          full(24000, 500, {dateMs: T0 + 90000, modifiedMs: T0 + 30000});
          const back = at(24000);
          out.back = [...pick(back), back.blocked, back.dataAgeS, L.showsOldData(back)];
          full(25000, 500, {dateMs: T0 + 91000, modifiedMs: T0 + 30000});
          out.backLater = [at(25000).publications, at(25000).dataAgeS];
          // A publication that is really new ends it.
          full(26000, 501, {dateMs: T0 + 92000, modifiedMs: T0 + 91800});
          out.fresh = [...pick(at(26000)), at(26000).blocked, at(26000).dataAgeS];
          // A number that goes back (the service restarted from an older state) is judged the same way.
          full(27000, 7, {dateMs: T0 + 93000, modifiedMs: T0 + 80000});
          out.older = [at(27000).publications, at(27000).blocked, at(27000).dataAgeS];
          return out;
        """)
        self.assertEqual(got["steady"], ["ok,alive,false"], "differences of 0-1 s never look like a stop")
        self.assertLessEqual(got["steadyMaxAge"], 1)
        self.assertEqual(got["outage"], ["unavailable", "unknown", "ok", "platform_unavailable"])
        self.assertEqual(got["back"], ["ok", "stopped", "ok", "publications_stopped", True, 60, True],
                         "a kept state is not shown as 0 s old and commands are blocked at once")
        self.assertEqual(got["backLater"], ["stopped", 61])
        self.assertEqual(got["fresh"], ["ok", "alive", "ok", None, False, 0])
        self.assertEqual(got["older"], ["stopped", True, 13])

    def test_failed_poll_does_not_erase_a_known_stop_of_publications(self):
        """M3: once the last answered read showed the number frozen for 5 s, failed reads keep «stopped» and the block."""
        got = self.js(self.PRELUDE + r"""
          const out = {};
          const view = (now) => { const status = at(now); return [...pick(status), status.blocked, L.showsOldData(status)]; };
          send({type: 'polling_started', at: 0});
          for (let time = 0; time <= 6000; time += 1000) full(time, 7);
          out.frozen = view(6000);
          // One fast failure a second later.
          send({type: 'poll_failed', at: 7000, kind: 'http', status: 502});
          out.oneFailure = view(7000);
          out.beforeStale = view(7999);
          out.stale = view(8000);
          send({type: 'poll_failed', at: 8000, kind: 'http', status: 502});
          send({type: 'poll_failed', at: 9000, kind: 'http', status: 502});
          out.unavailable = view(9000);
          // The platform answers again with the same number: still stopped; with a new one: alive.
          full(10000, 7);
          out.sameNumber = view(10000);
          full(11000, 8);
          out.newNumber = view(11000);

          // A stop that was not established before the failure is not claimed: unknown, as before.
          state = L.initialLink();
          send({type: 'polling_started', at: 0});
          for (let time = 0; time <= 4000; time += 1000) full(time, 7);
          send({type: 'poll_failed', at: 5000, kind: 'timeout', status: null});
          out.notEstablished = view(5000);
          out.notEstablishedLater = view(5999);

          // A read that hangs after the stop was shown: still stopped while the answer is awaited.
          state = L.initialLink();
          send({type: 'polling_started', at: 0});
          for (let time = 0; time <= 6000; time += 1000) full(time, 7);
          out.hanging = [view(7900), view(12000)];

          // The whole sequence, step by step: commands are never enabled between the stop and the new number.
          state = L.initialLink();
          send({type: 'polling_started', at: 0});
          for (let time = 0; time <= 6000; time += 1000) full(time, 7);
          const open = [];
          const probe = (from, to) => { for (let now = from; now <= to; now += 50) if (!at(now).blocked || !L.showsOldData(at(now))) open.push(now); };
          probe(6000, 6999);
          send({type: 'poll_failed', at: 7000, kind: 'network', status: null});
          probe(7000, 7999);
          full(8000, 7);
          probe(8000, 8999);
          send({type: 'poll_failed', at: 9000, kind: 'http', status: 503});
          probe(9000, 9999);
          out.open = open;
          return out;
        """)
        self.assertEqual(got["frozen"], ["ok", "stopped", "ok", "publications_stopped", True, True])
        self.assertEqual(got["oneFailure"], ["degraded", "stopped", "ok", "publications_stopped", True, True],
                         "one failed poll keeps the stop, the block and the mark of old data")
        self.assertEqual(got["beforeStale"], ["degraded", "stopped", "ok", "publications_stopped", True, True])
        self.assertEqual(got["stale"], ["stale", "stopped", "ok", "stale", True, True])
        self.assertEqual(got["unavailable"], ["unavailable", "stopped", "ok", "platform_unavailable", True, True])
        self.assertEqual(got["sameNumber"], ["ok", "stopped", "ok", "publications_stopped", True, True])
        self.assertEqual(got["newNumber"], ["ok", "alive", "ok", None, False, False])
        self.assertEqual(got["notEstablished"], ["degraded", "unknown", "ok", None, False, False])
        self.assertEqual(got["notEstablishedLater"], ["degraded", "unknown", "ok", None, False, False])
        self.assertEqual(got["hanging"], [["ok", "stopped", "ok", "publications_stopped", True, True],
                                          ["stale", "stopped", "ok", "stale", True, True]])
        self.assertEqual(got["open"], [], "commands stay blocked through the whole sequence")

    def test_invalid_snapshot_blocks_at_once_and_keeps_the_age_of_the_last_full_one(self):
        got = self.js(self.PRELUDE + r"""
          const out = {};
          send({type: 'polling_started', at: 0});
          full(0, 1);
          const rejection = {code: 'missing_field', params: {thing: 'worker-05', field: 'egress_status'}, detail: 'x'};
          send({type: 'poll_ok', at: 1000, seq: 2, dateMs: 1, modifiedMs: 1, full: false, rejection});
          out.rejected = [...pick(at(1000)), at(1000).invalid.code, at(1000).dataAgeS];
          send({type: 'poll_ok', at: 2000, seq: 3, dateMs: 1, modifiedMs: 1, full: false, rejection});
          out.later = [...pick(at(2000)), at(2000).dataAgeS];
          out.old = L.showsOldData(at(1000));
          full(3000, 4);
          out.recovered = [...pick(at(3000)), at(3000).invalid];
          full(4000, 5, {runState: 'resetting'});
          out.resetting = [...pick(at(4000)), at(4000).blocked];
          out.same = [L.sameLinkStatus(at(4000), at(4100)), L.sameLinkStatus(at(4000), at(5000))];
          out.shows = [L.showsOldData(at(4000)), L.showsOldData(at(6000))];
          return out;
        """)
        self.assertEqual(got["rejected"], ["ok", "alive", "invalid", "snapshot_invalid", "missing_field", 1])
        self.assertEqual(got["later"], ["stale", "alive", "invalid", "snapshot_invalid", 2])
        self.assertTrue(got["old"])
        self.assertEqual(got["recovered"], ["ok", "alive", "ok", None, None])
        self.assertEqual(got["resetting"], ["ok", "alive", "ok", "resetting", True])
        self.assertEqual(got["same"], [True, False])
        self.assertEqual(got["shows"], [False, True])


class CommandsTest(LogicTestCase):
    PRELUDE = r"""
      const C = await import('/js/commands.js');
      const {ACK_TIMEOUT_MS, APPLIED_LINGER_MS} = await import('/js/config.js');
      let pending = [];
      const send = (event) => { pending = C.reducePending(pending, event); return pending; };
      const entry = (id, type = 'condition.close_working', target = 'w-12') => ({
        id, type, target, run: 'run-0005',
        bodyText: JSON.stringify(C.buildBody({id, type, target, run: 'run-0005'})),
      });
      const view = () => pending.map((item) => [item.id, item.phase, item.attempts]);
      const ack = (id, status, reason = 'none') => ({id, type: 't', target: 'x', run: 'run-0005', status, tick: 1, sim_time_s: 1, reason});
    """

    def test_identifier_and_body(self):
        got = self.js(self.PRELUDE + r"""
          const ids = [C.newCommandId(), C.newCommandId()];
          const fixed = C.newCommandId((bytes) => bytes.fill(171));
          return {
            ids, fixed,
            plain: JSON.stringify(C.buildBody({id: 'c-1', type: 'condition.close_working', target: 'w-12', run: 'run-0003', decisionId: 'd-1'})),
            option: JSON.stringify(C.buildBody({id: 'c-1', type: 'action.execute_option', target: 'option-observe', run: 'run-0003', decisionId: 'd-0005-01'})),
            types: C.COMMAND_TYPES, resetTarget: C.RESET_TARGET,
            post: [
              C.phaseAfterPost({ok: true, status: 202}), C.phaseAfterPost({ok: false, kind: 'http', status: 400}),
              C.phaseAfterPost({ok: false, kind: 'http', status: 404}), C.phaseAfterPost({ok: false, kind: 'http', status: 413}),
              C.phaseAfterPost({ok: false, kind: 'http', status: 500}), C.phaseAfterPost({ok: false, kind: 'http', status: 503}),
              C.phaseAfterPost({ok: false, kind: 'http', status: 504}), C.phaseAfterPost({ok: false, kind: 'timeout', status: null}),
              C.phaseAfterPost({ok: false, kind: 'network', status: null}),
            ],
          };
        """)
        for command_id in got["ids"]:
            self.assertRegex(command_id, r"^c-[0-9a-f]{32}$")
        self.assertNotEqual(got["ids"][0], got["ids"][1])
        self.assertEqual(got["fixed"], "c-" + "ab" * 16)
        self.assertEqual(json.loads(got["plain"]),
                         {"command_id": "c-1", "type": "condition.close_working", "target": "w-12", "run": "run-0003"})
        self.assertEqual(json.loads(got["option"]),
                         {"command_id": "c-1", "type": "action.execute_option", "target": "option-observe",
                          "run": "run-0003", "decision_id": "d-0005-01"})
        self.assertEqual(len(got["types"]), 12)
        self.assertIn("run.start_preset", got["types"])
        self.assertEqual(got["resetTarget"], "run")
        self.assertEqual(got["post"], ["sent", "not_sent", "not_sent", "not_sent", "delivery_unknown",
                                       "delivery_unknown", "delivery_unknown", "delivery_unknown", "delivery_unknown"])

    def test_every_phase_path(self):
        got = self.js(self.PRELUDE + r"""
          const out = {};
          // sending -> sent -> no_ack -> retry -> sent -> applied -> leaves on its own
          send({type: 'created', entry: entry('c-a'), at: 0});
          out.created = view();
          const body = pending[0].bodyText;
          send({type: 'posted', id: 'c-a', result: {ok: true, status: 202}, at: 100});
          out.sent = view();
          out.unresolved = [C.isUnresolved('sent'), !!C.findUnresolved(pending, 'condition.close_working', 'w-12'),
            !!C.findUnresolved(pending, 'condition.close_working', 'w-07'), C.unresolvedFor(pending, 'w-12').length];
          send({type: 'tick', at: 100 + ACK_TIMEOUT_MS - 1});
          out.waiting = view();
          send({type: 'tick', at: 100 + ACK_TIMEOUT_MS});
          out.noAck = view();
          out.noAckOffers = [C.canRetry('no_ack'), C.isUnresolved('no_ack')];
          send({type: 'tick', at: 100000});
          out.noAckStays = view();
          send({type: 'retry', id: 'c-a', at: 100100});
          out.retried = view();
          out.sameBody = pending[0].bodyText === body && pending[0].id === 'c-a';
          send({type: 'posted', id: 'c-a', result: {ok: true, status: 202}, at: 100200});
          send({type: 'acks', acks: {'c-a': ack('c-a', 'applied')}, at: 101000});
          out.applied = [...view()[0], pending[0].ack.status];
          const appliedAt = pending[0].phaseAt;
          send({type: 'acks', acks: {'c-a': ack('c-a', 'applied')}, at: 102000});
          out.ackRepeatedKeepsTime = pending[0].phaseAt === appliedAt;
          send({type: 'tick', at: 101000 + APPLIED_LINGER_MS - 1});
          out.lingers = pending.length;
          send({type: 'tick', at: 101000 + APPLIED_LINGER_MS});
          out.left = pending.length;

          // rejected stays until dismissed
          send({type: 'created', entry: entry('c-b', 'condition.close_working', 'w-07'), at: 0});
          send({type: 'posted', id: 'c-b', result: {ok: true, status: 202}, at: 10});
          send({type: 'acks', acks: {'c-b': ack('c-b', 'rejected', 'not_allowed_in_state')}, at: 1000});
          send({type: 'tick', at: 900000});
          out.rejected = [...view()[0], pending[0].ack.reason, C.isUnresolved(pending[0].phase)];
          send({type: 'dismiss', id: 'c-b'});
          out.dismissed = pending.length;

          // timeout -> delivery_unknown -> retry; the acknowledgement arrives before the second answer
          send({type: 'created', entry: entry('c-c', 'condition.sensor_lost', 'sens-ext-05'), at: 0});
          send({type: 'posted', id: 'c-c', result: {ok: false, kind: 'timeout', status: null}, at: 3000});
          out.unknown = [...view()[0], pending[0].failure];
          send({type: 'tick', at: 900000});
          out.unknownStays = view()[0][1];
          send({type: 'retry', id: 'c-c', at: 900100});
          send({type: 'acks', acks: {'c-c': ack('c-c', 'applied')}, at: 900200});
          send({type: 'posted', id: 'c-c', result: {ok: false, kind: 'http', status: 504}, at: 900300});
          out.ackWins = view()[0];
          send({type: 'dismiss', id: 'c-c'});

          // 5xx is unknown as well; 4xx is certainly not sent and can be sent again
          send({type: 'created', entry: entry('c-d', 'action.stop_zone', 'zone-b'), at: 0});
          send({type: 'posted', id: 'c-d', result: {ok: false, kind: 'http', status: 503}, at: 20});
          out.fiveXx = [view()[0][1], pending[0].failure];
          send({type: 'dismiss', id: 'c-d'});
          send({type: 'created', entry: entry('c-e', 'action.stop_zone', 'zone-b'), at: 0});
          send({type: 'posted', id: 'c-e', result: {ok: false, kind: 'http', status: 400}, at: 20});
          out.fourXx = [view()[0][1], pending[0].failure, C.isUnresolved(pending[0].phase), C.canRetry(pending[0].phase)];
          send({type: 'tick', at: 900000});
          out.fourXxStays = view()[0][1];
          send({type: 'retry', id: 'c-e', at: 900001});
          out.fourXxRetried = view()[0];
          send({type: 'dismiss', id: 'c-e'});

          // blocked: an entry that was never posted
          send({type: 'blocked', entry: {...entry('c-f'), failure: {kind: 'blocked', status: null, reason: 'stale'}}, at: 5});
          out.blocked = [...view()[0], pending[0].failure.reason];
          // a new command for the same type and target replaces the finished message
          send({type: 'created', entry: entry('c-g'), at: 6});
          out.replaced = view();
          // ... but never an unresolved one, and other targets are untouched
          send({type: 'created', entry: entry('c-h', 'condition.close_working', 'w-07'), at: 7});
          out.both = view().map((item) => item[0]);
          send({type: 'retry', id: 'c-g', at: 8});
          out.retryWhileSending = view()[0];

          // applied without change keeps its reason
          send({type: 'acks', acks: {'c-g': ack('c-g', 'applied', 'already_in_state')}, at: 9});
          out.alreadyInState = [pending[0].phase, pending[0].ack.reason];
          // a later conflict over the same id does not take the outcome back (see the next test)
          send({type: 'acks', acks: {'c-g': ack('c-g', 'rejected', 'command_id_conflict')}, at: 10});
          out.conflict = [pending[0].phase, pending[0].ack.reason];
          out.unknownEvent = C.reducePending(pending, {type: 'nonsense'}) === pending;
          out.noChangeKeepsIdentity = C.reducePending(pending, {type: 'tick', at: 11}) === pending;
          return out;
        """)
        self.assertEqual(got["created"], [["c-a", "sending", 1]])
        self.assertEqual(got["sent"], [["c-a", "sent", 1]])
        self.assertEqual(got["unresolved"], [True, True, False, 1])
        self.assertEqual(got["waiting"], [["c-a", "sent", 1]])
        self.assertEqual(got["noAck"], [["c-a", "no_ack", 1]])
        self.assertEqual(got["noAckOffers"], [True, True])
        self.assertEqual(got["noAckStays"], [["c-a", "no_ack", 1]])
        self.assertEqual(got["retried"], [["c-a", "sending", 2]])
        self.assertTrue(got["sameBody"], "a retry keeps the identifier and the body")
        self.assertEqual(got["applied"], ["c-a", "applied", 2, "applied"])
        self.assertTrue(got["ackRepeatedKeepsTime"])
        self.assertEqual((got["lingers"], got["left"]), (1, 0))
        self.assertEqual(got["rejected"], ["c-b", "rejected", 1, "not_allowed_in_state", False])
        self.assertEqual(got["dismissed"], 0)
        self.assertEqual(got["unknown"], ["c-c", "delivery_unknown", 1, {"kind": "timeout", "status": None}])
        self.assertEqual(got["unknownStays"], "delivery_unknown")
        self.assertEqual(got["ackWins"], ["c-c", "applied", 2])
        self.assertEqual(got["fiveXx"], ["delivery_unknown", {"kind": "http", "status": 503}])
        self.assertEqual(got["fourXx"], ["not_sent", {"kind": "http", "status": 400}, False, True])
        self.assertEqual(got["fourXxStays"], "not_sent")
        self.assertEqual(got["fourXxRetried"], ["c-e", "sending", 2])
        self.assertEqual(got["blocked"], ["c-f", "not_sent", 0, "stale"])
        self.assertEqual(got["replaced"], [["c-g", "sending", 1]])
        self.assertEqual(got["both"], ["c-g", "c-h"])
        self.assertEqual(got["retryWhileSending"], ["c-g", "sending", 1])
        self.assertEqual(got["alreadyInState"], ["applied", "already_in_state"])
        self.assertEqual(got["conflict"], ["applied", "already_in_state"])
        self.assertTrue(got["unknownEvent"])
        self.assertTrue(got["noChangeKeepsIdentity"])

    def test_conflict_and_unknown_status_records_do_not_settle_a_command(self):
        """S7: a conflict over the id never replaces an outcome; a status outside the contract resolves nothing."""
        got = self.js(self.PRELUDE + r"""
          const M = await import('/js/model.js');
          const T = await import('/js/text.js');
          const out = {};
          const record = (id, status, reason = 'none', extra = {}) => ({...ack(id, status, reason), ...extra});
          const acks = (records) => Object.fromEntries(Object.entries(M.latestAcks(records)).map(([id, item]) => [id, [item.status, item.reason]]));
          out.latest = {
            appliedThenConflict: acks([record('c-1', 'applied'), record('c-1', 'rejected', 'command_id_conflict')]),
            rejectedThenConflict: acks([record('c-1', 'rejected', 'malformed'), record('c-1', 'rejected', 'command_id_conflict')]),
            conflictAlone: acks([record('c-1', 'rejected', 'command_id_conflict')]),
            conflictThenApplied: acks([record('c-1', 'rejected', 'command_id_conflict'), record('c-1', 'applied')]),
            appliedThenOdd: acks([record('c-1', 'applied'), record('c-1', 'queued')]),
            oddThenApplied: acks([record('c-1', 'queued'), record('c-1', 'applied')]),
            oddAlone: acks([record('c-1', 'queued')]),
            noStatus: acks([{id: 'c-1'}]),
            // Not a conflict and a real outcome: the later record still wins.
            appliedThenRejected: acks([record('c-1', 'applied'), record('c-1', 'rejected', 'not_allowed_in_state')]),
            otherIdsUntouched: acks([record('c-1', 'applied'), record('c-2', 'rejected', 'command_id_conflict')]),
            junk: acks([null, 7, 'x', [], {status: 'applied'}, {id: 5, status: 'applied'}]),
          };

          // The reducer: an applied command stays applied when the conflict record arrives in a later snapshot.
          send({type: 'created', entry: entry('c-a'), at: 0});
          send({type: 'posted', id: 'c-a', result: {ok: true, status: 202}, at: 10});
          send({type: 'acks', acks: {'c-a': record('c-a', 'applied')}, at: 1000});
          const applied = pending[0];
          send({type: 'acks', acks: {'c-a': record('c-a', 'rejected', 'command_id_conflict')}, at: 2000});
          out.conflictAfterApplied = [pending[0].phase, pending[0].ack.status, pending[0].ack.reason, pending[0] === applied];
          send({type: 'acks', acks: {'c-a': record('c-a', 'queued')}, at: 2500});
          out.oddAfterApplied = [pending[0].phase, pending[0].oddAck, pending[0] === applied];
          send({type: 'dismiss', id: 'c-a'});
          // The same for a rejected one.
          send({type: 'created', entry: entry('c-b'), at: 0});
          send({type: 'posted', id: 'c-b', result: {ok: true, status: 202}, at: 10});
          send({type: 'acks', acks: {'c-b': record('c-b', 'rejected', 'not_allowed_in_state')}, at: 1000});
          send({type: 'acks', acks: {'c-b': record('c-b', 'rejected', 'command_id_conflict')}, at: 2000});
          out.conflictAfterRejected = [pending[0].phase, pending[0].ack.reason];
          send({type: 'dismiss', id: 'c-b'});

          // A record with a status that is neither applied nor rejected: the command goes on waiting.
          send({type: 'created', entry: entry('c-c'), at: 0});
          send({type: 'posted', id: 'c-c', result: {ok: true, status: 202}, at: 100});
          send({type: 'acks', acks: {'c-c': record('c-c', 'queued')}, at: 1000});
          out.odd = [pending[0].phase, pending[0].ack, pending[0].oddAck.status, C.isUnresolved(pending[0].phase)];
          out.oddText = T.pendingText(pending[0], 1);
          const withOdd = pending[0];
          send({type: 'acks', acks: {'c-c': record('c-c', 'queued')}, at: 2000});
          out.oddRepeatedKeepsIdentity = pending[0] === withOdd;
          send({type: 'tick', at: 100 + ACK_TIMEOUT_MS - 1});
          out.oddStillSent = pending[0].phase;
          send({type: 'tick', at: 100 + ACK_TIMEOUT_MS});
          out.oddNoAck = [pending[0].phase, C.canRetry(pending[0].phase), pending[0].oddAck.status];
          out.oddNoAckText = T.pendingText(pending[0]);
          // The real outcome arrives later and settles it; the odd record is forgotten.
          send({type: 'acks', acks: {'c-c': record('c-c', 'applied')}, at: 9000});
          out.settled = [pending[0].phase, pending[0].ack.status, pending[0].oddAck];
          out.settledText = T.pendingText(pending[0]);
          send({type: 'dismiss', id: 'c-c'});

          // A record without any status is odd as well.
          send({type: 'created', entry: entry('c-d'), at: 0});
          send({type: 'posted', id: 'c-d', result: {ok: true, status: 202}, at: 100});
          send({type: 'acks', acks: {'c-d': {id: 'c-d'}}, at: 1000});
          out.noStatus = [pending[0].phase, T.pendingText(pending[0], 0)];
          return out;
        """)
        got = json.loads(plain(json.dumps(got, ensure_ascii=False)))
        latest = got["latest"]
        self.assertEqual(latest["appliedThenConflict"], {"c-1": ["applied", "none"]})
        self.assertEqual(latest["rejectedThenConflict"], {"c-1": ["rejected", "malformed"]})
        self.assertEqual(latest["conflictAlone"], {"c-1": ["rejected", "command_id_conflict"]})
        self.assertEqual(latest["conflictThenApplied"], {"c-1": ["applied", "none"]})
        self.assertEqual(latest["appliedThenOdd"], {"c-1": ["applied", "none"]})
        self.assertEqual(latest["oddThenApplied"], {"c-1": ["applied", "none"]})
        self.assertEqual(latest["oddAlone"], {"c-1": ["queued", "none"]})
        self.assertEqual(latest["noStatus"], {"c-1": [None, None]})
        self.assertEqual(latest["appliedThenRejected"], {"c-1": ["rejected", "not_allowed_in_state"]})
        self.assertEqual(latest["otherIdsUntouched"], {"c-1": ["applied", "none"], "c-2": ["rejected", "command_id_conflict"]})
        self.assertEqual(latest["junk"], {})
        self.assertEqual(got["conflictAfterApplied"], ["applied", "applied", "none", True])
        self.assertEqual(got["oddAfterApplied"], ["applied", None, True])
        self.assertEqual(got["conflictAfterRejected"], ["rejected", "not_allowed_in_state"])
        self.assertEqual(got["odd"], ["sent", None, "queued", True], "the command is not resolved")
        self.assertEqual(got["oddText"], "Команда отправлена, не подтверждена (1 с). Запись модели: неизвестный результат (queued)")
        self.assertTrue(got["oddRepeatedKeepsIdentity"])
        self.assertEqual(got["oddStillSent"], "sent")
        self.assertEqual(got["oddNoAck"], ["no_ack", True, "queued"], "it reaches «no acknowledgement» like any unanswered command")
        self.assertEqual(got["oddNoAckText"],
                         "Нет подтверждения 5 с. Команда могла не дойти. Запись модели: неизвестный результат (queued)")
        self.assertEqual(got["settled"], ["applied", "applied", None])
        self.assertEqual(got["settledText"], "Команда применена")
        self.assertEqual(got["noStatus"], ["sent", "Команда отправлена, не подтверждена (0 с). Запись модели: результат не указан"])

    def test_refused_retry_after_unknown_delivery_stays_unknown(self):
        """S8: HTTP 4xx settles «not sent» only when no earlier POST of the command may have arrived."""
        got = self.js(self.PRELUDE + r"""
          const T = await import('/js/text.js');
          const out = {};
          const state = () => [pending[0].phase, pending[0].attempts, pending[0].failure, pending[0].maybeDelivered];
          // First attempt 4xx: certainly not sent.
          send({type: 'created', entry: entry('c-a'), at: 0});
          send({type: 'posted', id: 'c-a', result: {ok: false, kind: 'http', status: 400}, at: 10});
          out.first4xx = state();
          out.first4xxText = T.pendingText(pending[0]);
          // ... and again 4xx on its retry: still certainly not sent.
          send({type: 'retry', id: 'c-a', at: 20});
          send({type: 'posted', id: 'c-a', result: {ok: false, kind: 'http', status: 413}, at: 30});
          out.second4xx = state();
          send({type: 'dismiss', id: 'c-a'});

          // Timeout, then 4xx on the retry: the first attempt may have arrived.
          send({type: 'created', entry: entry('c-b'), at: 0});
          send({type: 'posted', id: 'c-b', result: {ok: false, kind: 'timeout', status: null}, at: 3000});
          out.timeout = state();
          send({type: 'retry', id: 'c-b', at: 4000});
          send({type: 'posted', id: 'c-b', result: {ok: false, kind: 'http', status: 400}, at: 4010});
          out.retry4xx = state();
          out.retry4xxText = T.pendingText(pending[0]);
          out.retry4xxOffers = [C.isUnresolved(pending[0].phase), C.canRetry(pending[0].phase),
            !!C.findUnresolved(pending, 'condition.close_working', 'w-12')];
          send({type: 'tick', at: 900000});
          out.retry4xxStays = pending[0].phase;
          // The acknowledgement of the first attempt can still arrive and settles it.
          send({type: 'acks', acks: {'c-b': ack('c-b', 'applied')}, at: 900100});
          out.ackAfterRefusal = [pending[0].phase, pending[0].failure];
          send({type: 'dismiss', id: 'c-b'});

          // 5xx, then 4xx on the retry: the same.
          send({type: 'created', entry: entry('c-c'), at: 0});
          send({type: 'posted', id: 'c-c', result: {ok: false, kind: 'http', status: 503}, at: 10});
          send({type: 'retry', id: 'c-c', at: 20});
          send({type: 'posted', id: 'c-c', result: {ok: false, kind: 'http', status: 404}, at: 30});
          out.after5xx = state();
          send({type: 'dismiss', id: 'c-c'});

          // Accepted (202), no acknowledgement, 4xx on the retry: the accepted attempt may have arrived.
          send({type: 'created', entry: entry('c-d'), at: 0});
          send({type: 'posted', id: 'c-d', result: {ok: true, status: 202}, at: 10});
          send({type: 'tick', at: 10 + ACK_TIMEOUT_MS});
          send({type: 'retry', id: 'c-d', at: 6000});
          send({type: 'posted', id: 'c-d', result: {ok: false, kind: 'http', status: 400}, at: 6010});
          out.afterAccepted = state();
          send({type: 'dismiss', id: 'c-d'});

          // 4xx first, then a timeout, then 4xx: unknown from the timeout on.
          send({type: 'created', entry: entry('c-e'), at: 0});
          send({type: 'posted', id: 'c-e', result: {ok: false, kind: 'http', status: 400}, at: 10});
          send({type: 'retry', id: 'c-e', at: 20});
          send({type: 'posted', id: 'c-e', result: {ok: false, kind: 'network', status: null}, at: 30});
          send({type: 'retry', id: 'c-e', at: 40});
          send({type: 'posted', id: 'c-e', result: {ok: false, kind: 'http', status: 400}, at: 50});
          out.mixed = state();
          out.phases = [C.phaseAfterPost({ok: false, kind: 'http', status: 400}), C.phaseAfterPost({ok: false, kind: 'http', status: 400}, true),
            C.phaseAfterPost({ok: true, status: 202}, true), C.phaseAfterPost({ok: false, kind: 'http', status: 502}, false)];
          return out;
        """)
        got = json.loads(plain(json.dumps(got, ensure_ascii=False)))
        refused = {"kind": "http", "status": 400}
        self.assertEqual(got["first4xx"], ["not_sent", 1, refused, False])
        self.assertEqual(got["first4xxText"], "Команда не отправлена: HTTP 400")
        self.assertEqual(got["second4xx"], ["not_sent", 2, {"kind": "http", "status": 413}, False])
        self.assertEqual(got["timeout"], ["delivery_unknown", 1, {"kind": "timeout", "status": None}, True])
        self.assertEqual(got["retry4xx"], ["delivery_unknown", 2, refused, True],
                         "a refused retry does not prove that the first attempt never arrived")
        self.assertEqual(got["retry4xxText"], "Результат доставки неизвестен: повтор не принят (HTTP 400), "
                                              "но предыдущая отправка могла дойти до модели")
        self.assertEqual(got["retry4xxOffers"], [True, True, True], "unresolved, can be retried, bars a second command")
        self.assertEqual(got["retry4xxStays"], "delivery_unknown")
        self.assertEqual(got["ackAfterRefusal"], ["applied", None])
        self.assertEqual(got["after5xx"], ["delivery_unknown", 2, {"kind": "http", "status": 404}, True])
        self.assertEqual(got["afterAccepted"], ["delivery_unknown", 2, refused, True])
        self.assertEqual(got["mixed"], ["delivery_unknown", 3, refused, True])
        self.assertEqual(got["phases"], ["not_sent", "delivery_unknown", "sent", "delivery_unknown"])

    def test_block_derivation(self):
        got = self.js(self.PRELUDE + r"""
          const {initialState} = await import('/js/store.js');
          const base = initialState();
          const open = {...base.link, blocked: false, blockReason: null};
          const reset = (phase) => [{...entry('c-r', 'run.reset', 'run'), phase}];
          const block = (state) => { const d = C.deriveBlock(state); return [d.commandsBlocked, d.blockReason]; };
          return {
            loading: block(base),
            ready: block({...base, boot: 'ready', link: open}),
            link: block({...base, boot: 'ready', link: {...open, blocked: true, blockReason: 'stale'}}),
            ownReset: block({...base, boot: 'ready', link: open, pending: reset('sent')}),
            ownResetSending: block({...base, boot: 'ready', link: open, pending: reset('sending')}),
            ownResetNoAck: block({...base, boot: 'ready', link: open, pending: reset('no_ack')}),
            preset: C.hasOwnResetPending([{...entry('c-p', 'run.start_preset', 'p-detour'), phase: 'sent'}]),
            other: C.hasOwnResetPending([{...entry('c-o'), phase: 'sent'}]),
          };
        """)
        self.assertEqual(got["loading"], [True, "not_ready"])
        self.assertEqual(got["ready"], [False, None])
        self.assertEqual(got["link"], [True, "stale"])
        self.assertEqual(got["ownReset"], [True, "own_reset_pending"])
        self.assertEqual(got["ownResetSending"], [True, "own_reset_pending"])
        self.assertEqual(got["ownResetNoAck"], [False, None])
        self.assertTrue(got["preset"])
        self.assertFalse(got["other"])


class ModelTest(LogicTestCase):
    def test_route_forms_normalize_to_the_same_segments(self):
        got = self.js(r"""
          const M = await import('/js/model.js');
          const ends = {'w-14': {from: 'n-14', to: 'n-15'}, 'w-15': {from: 'n-16', to: 'n-15'}, 'w-18': {from: 'n-16', to: 'n-17'}};
          const endsOf = (name) => ends[name] || null;
          return {
            names: M.normalizeRoute(['w-14', 'w-15', 'w-18'], 'n-15', endsOf),
            reversedFirst: M.normalizeRoute(['w-14'], 'n-14', endsOf),
            objects: M.normalizeRoute([{working: 'w-14', from: 'n-14', to: 'n-15'}, {working: 'w-15', from: 'n-15', to: 'n-16'}], 'n-15', endsOf),
            noNextNode: M.normalizeRoute(['w-14', 'w-15'], null, endsOf),
            unknownWorking: M.normalizeRoute(['w-14', 'w-77', 'w-18'], 'n-15', endsOf),
            junk: M.normalizeRoute([42, null, {working: 7}, 'w-14'], 'n-15', endsOf),
            absent: [M.normalizeRoute(undefined, 'n-1', endsOf), M.normalizeRoute('w-14,w-15', 'n-1', endsOf)],
          };
        """)
        self.assertEqual(got["names"], [
            {"working": "w-14", "from": "n-14", "to": "n-15"},
            {"working": "w-15", "from": "n-15", "to": "n-16"},
            {"working": "w-18", "from": "n-16", "to": "n-17"},
        ])
        self.assertEqual(got["reversedFirst"], [{"working": "w-14", "from": "n-15", "to": "n-14"}])
        self.assertEqual(got["objects"], got["names"][:2])
        self.assertEqual(got["noNextNode"], [{"working": "w-14", "from": None, "to": None},
                                             {"working": "w-15", "from": None, "to": None}])
        self.assertEqual(got["unknownWorking"], [
            {"working": "w-14", "from": "n-14", "to": "n-15"},
            {"working": "w-77", "from": None, "to": None},
            {"working": "w-18", "from": None, "to": None},
        ], "a direction is never guessed past a working the attributes do not describe")
        self.assertEqual(got["junk"], [{"working": "w-14", "from": "n-14", "to": "n-15"}])
        self.assertEqual(got["absent"], [[], []])

    def test_both_route_forms_of_the_fixtures_give_one_route(self):
        routes = {}
        for scenario in ("paused_heartbeat", "route_segments"):
            self.mock.scenario(scenario)
            routes[scenario] = self.js(LOAD + r"""
              const attributes = await loadAttributes();
              const checked = V.validateShift(await api.readShift(), attributes);
              if (!checked.ok) throw new Error(checked.detail);
              const model = M.buildModel(attributes, checked.snapshot);
              const worker = M.thingByName(model, 'worker-03');
              return {raw: worker.values.route, route: M.routeOf(model, worker)};
            """)
        self.assertIsInstance(routes["paused_heartbeat"]["raw"][0], str)
        self.assertIsInstance(routes["route_segments"]["raw"][0], dict)
        self.assertEqual(routes["paused_heartbeat"]["route"], routes["route_segments"]["route"])
        self.assertEqual(routes["route_segments"]["route"], [
            {"working": "w-14", "from": "n-14", "to": "n-15"},
            {"working": "w-15", "from": "n-15", "to": "n-16"},
            {"working": "w-18", "from": "n-16", "to": "n-17"},
            {"working": "w-03", "from": "n-17", "to": "n-06"},
        ])

    def test_conditions_acknowledgements_and_the_defensive_hazard_rule(self):
        got = self.js(r"""
          const M = await import('/js/model.js');
          const hazard = (hazard_state, data_quality) => M.displayedHazard({hazard_state, data_quality});
          return {
            conditions: ['working_closed:w-07', 'sensor_lost:sens-ext-05', 'instability:zone-b', 'flood:w-01',
              'working_closed', 'working_closed:'].map(M.parseCondition),
            // The object form gives the same condition; anything else is an entry of an unknown form, as JSON text.
            objects: [{kind: 'working_closed', target: 'w-07'}, {type: 'sensor_lost', target: 'sens-ext-05'},
              {kind: 'instability', type: 'ignored', target: 'zone-b'}, {kind: 'flood', target: 'w-01'}].map(M.parseCondition),
            unknownForms: [{kind: 'working_closed'}, {target: 'w-07'}, {kind: 7, target: 'w-07'}, {kind: 'working_closed', target: 7},
              {}, [], ['working_closed', 'w-07'], null, 42, true, undefined].map(M.parseCondition),
            deduplicated: M.parseConditions(['working_closed:w-07', 'working_closed:w-07', {kind: 'working_closed', target: 'w-07'},
              {type: 'sensor_lost', target: 'sens-ext-05'}, {a: 1}, {a: 1}, {a: 2}, 'sensor_lost:sens-ext-05', null, null])
              .map((condition) => condition.raw),
            noConditions: [M.parseConditions(undefined), M.parseConditions('working_closed:w-07'), M.parseConditions({})],
            causes: [M.causesOf({causes: [null, 'x', 7, [], {trigger: 'hazard'}, undefined, {}]}), M.causesOf({causes: 'hazard'}), M.causesOf({})],
            acks: M.latestAcks([
              {id: 'c-1', status: 'applied', reason: 'none'}, {id: 'c-2', status: 'rejected', reason: 'malformed'},
              {id: 'c-1', status: 'rejected', reason: 'command_id_conflict'}, null, {status: 'applied'},
              {id: 'c-3', status: 'applied', reason: 'none'}, {id: 'c-3', status: 'applied', reason: 'already_in_state'},
            ]),
            noAcks: M.latestAcks(undefined),
            hazards: {
              normalFresh: hazard('normal', 'fresh'), normalStale: hazard('normal', 'stale'),
              normalLost: hazard('normal', 'lost'), normalNone: hazard('normal', 'none'),
              normalNoQuality: hazard('normal', undefined), attentionStale: hazard('attention', 'stale'),
              dangerLost: hazard('danger', 'lost'), unknownNone: hazard('unknown', 'none'),
              elevated: hazard('elevated', 'fresh'), absent: hazard(undefined, 'fresh'),
            },
            location: [M.knownHazard('danger'), M.knownHazard('elevated'), M.knownHazard(undefined)],
            ids: [M.fullId('w-12'), M.localName('team040.mine:w-12'), M.localName('w-12')],
            commands: M.CONDITION_COMMANDS,
          };
        """)
        self.assertEqual(got["conditions"], [
            {"raw": "working_closed:w-07", "kind": "working_closed", "target": "w-07", "undoType": "condition.open_working"},
            {"raw": "sensor_lost:sens-ext-05", "kind": "sensor_lost", "target": "sens-ext-05",
             "undoType": "condition.sensor_restored"},
            {"raw": "instability:zone-b", "kind": "instability", "target": "zone-b", "undoType": "condition.instability_off"},
            {"raw": "flood:w-01", "kind": "flood", "target": "w-01", "undoType": None},
            {"raw": "working_closed", "kind": "working_closed", "target": "", "undoType": None},
            {"raw": "working_closed:", "kind": "working_closed", "target": "", "undoType": None},
        ])
        self.assertEqual(got["objects"], [
            {"raw": "working_closed:w-07", "kind": "working_closed", "target": "w-07", "undoType": "condition.open_working"},
            {"raw": "sensor_lost:sens-ext-05", "kind": "sensor_lost", "target": "sens-ext-05",
             "undoType": "condition.sensor_restored"},
            {"raw": "instability:zone-b", "kind": "instability", "target": "zone-b", "undoType": "condition.instability_off"},
            {"raw": "flood:w-01", "kind": "flood", "target": "w-01", "undoType": None},
        ])
        self.assertEqual([item["raw"] for item in got["unknownForms"]], [
            '{"kind":"working_closed"}', '{"target":"w-07"}', '{"kind":7,"target":"w-07"}', '{"kind":"working_closed","target":7}',
            "{}", "[]", '["working_closed","w-07"]', "null", "42", "true", "undefined"])
        for item in got["unknownForms"]:
            self.assertEqual((item["kind"], item["target"], item["undoType"]), ("", "", None), item)
        self.assertEqual(got["deduplicated"], ["working_closed:w-07", "sensor_lost:sens-ext-05", '{"a":1}', '{"a":2}', "null"],
                         "one entry per condition, whatever form and however often it was published")
        self.assertEqual(got["noConditions"], [[], [], []])
        self.assertEqual(got["causes"], [[{"trigger": "hazard"}, {}], [], []])
        self.assertEqual(got["acks"], {
            "c-1": {"id": "c-1", "status": "applied", "reason": "none"},
            "c-2": {"id": "c-2", "status": "rejected", "reason": "malformed"},
            "c-3": {"id": "c-3", "status": "applied", "reason": "already_in_state"},
        }, "the latest record of an id wins, except a conflict over an id that already has its outcome")
        self.assertEqual(got["noAcks"], {})
        hazards = got["hazards"]
        self.assertEqual(hazards["normalFresh"], {"state": "normal", "raw": "normal", "known": True, "defensive": False})
        for name in ("normalStale", "normalLost", "normalNone", "normalNoQuality"):
            self.assertEqual(hazards[name], {"state": "unknown", "raw": "normal", "known": True, "defensive": True}, name)
        self.assertEqual(hazards["attentionStale"]["state"], "attention", "only `normal` is doubted by the interface")
        self.assertEqual(hazards["dangerLost"]["state"], "danger")
        self.assertEqual(hazards["unknownNone"], {"state": "unknown", "raw": "unknown", "known": True, "defensive": False})
        self.assertEqual(hazards["elevated"], {"state": "unknown", "raw": "elevated", "known": False, "defensive": False})
        self.assertEqual(hazards["absent"]["state"], "unknown")
        self.assertEqual(got["location"], ["danger", "unknown", "unknown"])
        self.assertEqual(got["ids"], ["team040.mine:w-12", "w-12", "w-12"])
        self.assertEqual(got["commands"]["sensor_lost"],
                         {"set": "condition.sensor_lost", "undo": "condition.sensor_restored", "targetKind": "sensor"})

    def test_model_of_a_real_snapshot(self):
        self.mock.scenario("sensor_lost_after_danger")
        got = self.js(LOAD + r"""
          const T = await import('/js/text.js');
          const attributes = await loadAttributes();
          const checked = V.validateShift(await api.readShift(), attributes);
          if (!checked.ok) throw new Error(checked.detail);
          const model = M.buildModel(attributes, checked.snapshot);
          const bare = M.buildModel(attributes, null);
          const names = (things) => things.map((thing) => thing.name);
          const zone = M.thingByName(model, 'zone-c');
          const worker = M.thingByName(model, 'worker-07');
          const place = M.placeOf(model, worker);
          const sensorPlace = M.placeOf(model, M.thingByName(model, 'sens-ext-05'));
          const exitPlace = M.placeOf(model, M.thingByName(model, 'exit-shaft'));
          return {
            kinds: Object.fromEntries(Object.entries(model.byKind).map(([kind, things]) => [kind, things.length])),
            hasSnapshot: [model.hasSnapshot, bare.hasSnapshot],
            label: [zone.label, zone.kind, zone.name, zone.thingId, zone.hasState],
            zoneHazard: zone.hazard, zoneAttrs: M.stateAttributes(zone),
            lastKnown: T.lastKnownText(zone.values),
            sensorAttrs: M.stateAttributes(M.thingByName(model, 'sens-ext-05')),
            workerAttrs: M.stateAttributes(worker, true),
            exitAttrs: M.stateAttributes(M.thingByName(model, 'exit-shaft')),
            workingAttrs: M.stateAttributes(M.thingByName(model, 'w-21')),
            bareWorking: [M.thingByName(bare, 'w-21').hasState, M.stateAttributes(M.thingByName(bare, 'w-21'))],
            zoneOfWorking: [M.zoneOfWorking(model, 'w-21').name, M.zoneOfWorking(model, 'w-01')],
            workingsOfZone: names(M.workingsOfZone(model, 'zone-c')),
            sensorsOfZone: names(M.sensorsOfZone(model, 'zone-b')),
            sensorsOfWorking: names(M.sensorsOfWorking(model, 'w-21')),
            workersAtWorking: names(M.workersAtWorking(model, 'w-21')),
            workersInZone: names(M.workersInZone(model, 'zone-c')),
            workersAtExit: names(M.workersAtExit(model, 'exit-shaft')),
            exitAtNode: M.exitAtNode(model, 'n-01').name,
            incident: M.incidentOf(model).values.state,
            place: [place.working.name, place.offsetM, place.fromNode, place.zone.name, place.level.name, place.exit],
            placeText: T.placeText(place),
            sensorPlace: T.placeText(sensorPlace), exitPlace: T.placeText(exitPlace),
            unknownName: [M.thingByName(model, 'nothing'), M.thingByName(model, 'constructor'), M.labelOf(model, 'nothing'),
              M.labelOf(model, 'w-21')],
            conditions: model.conditions.map((condition) => condition.raw),
            shift: model.shift.values.workers_unknown,
          };
        """)
        self.assertEqual(got["kinds"], {"mine": 1, "shift": 1, "level": 3, "working": 36, "zone": 4, "sensor": 10,
                                        "worker": 14, "exit": 3, "incident": 1, "option": 3, "journal": 1})
        self.assertEqual(got["hasSnapshot"], [True, False])
        self.assertEqual(got["label"], ["Участок В", "zone", "zone-c", "team040.mine:zone-c", True])
        self.assertEqual(got["zoneHazard"], {"state": "unknown", "raw": "unknown", "known": True, "defensive": False})
        self.assertEqual(got["zoneAttrs"], {
            "data-thing-id": "team040.mine:zone-c", "data-kind": "zone", "data-pending": None,
            "data-hazard": "unknown", "data-quality": "lost", "data-last-known-hazard": "danger",
            "data-work-state": "working", "data-withdrawal": "none",
        })
        self.assertEqual(plain(got["lastKnown"]), "последнее известное: опасно (тик 810)")
        self.assertEqual(got["sensorAttrs"]["data-quality"], "lost")
        self.assertEqual(got["sensorAttrs"]["data-link"], "offline")
        self.assertEqual(got["workerAttrs"], {
            "data-thing-id": "team040.mine:worker-07", "data-kind": "worker", "data-pending": True,
            "data-status": "working", "data-egress": "ok", "data-location-hazard": "unknown", "data-pos-quality": "fresh",
        })
        self.assertEqual(got["exitAttrs"]["data-state"], "available")
        self.assertEqual(got["workingAttrs"]["data-restriction"], "blocked")
        self.assertEqual(got["workingAttrs"]["data-passability"], "open")
        self.assertEqual(got["workingAttrs"]["data-last-known-hazard"], "danger")
        self.assertEqual(got["bareWorking"][0], False)
        self.assertEqual(got["bareWorking"][1]["data-hazard"], "unknown", "without a state nothing is drawn as normal")
        self.assertIsNone(got["bareWorking"][1]["data-passability"])
        self.assertEqual(got["zoneOfWorking"], ["zone-c", None])
        self.assertEqual(got["workingsOfZone"], ["w-20", "w-21"])
        self.assertEqual(got["sensorsOfZone"], ["sens-ext-02", "sens-ext-03", "sens-conv-02", "sens-geo-02"])
        self.assertEqual(got["sensorsOfWorking"], ["sens-ext-05"])
        self.assertEqual(got["workersAtWorking"], ["worker-07"])
        self.assertEqual(got["workersInZone"], ["worker-07", "worker-08"])
        self.assertEqual(got["workersAtExit"], [])
        self.assertEqual(got["exitAtNode"], "exit-shaft")
        self.assertEqual(got["incident"], "executing")
        self.assertEqual(got["place"], ["w-21", 35, "n-26", "zone-c", "level-380", None])
        self.assertEqual(plain(got["placeText"]), "В-21, 35 м от узла n-26 · Участок В")
        self.assertEqual(plain(got["sensorPlace"]), "В-21, 18 м от узла n-26 · Участок В")
        self.assertIn("узел n-01", got["exitPlace"])
        self.assertEqual(got["unknownName"], [None, None, "nothing", "В-21"])
        self.assertEqual(got["shift"], 2)


    def test_a_worker_who_is_out_is_nowhere_under_ground(self):
        """S2: `status = out` with a working and an offset still published is not a position under ground."""
        self.mock.scenario("normal")
        got = self.js(LOAD + r"""
          const attributes = await loadAttributes();
          const response = await api.readShift();
          const features = response.body.features.scene.properties.value
            .find((item) => item.thingId === 'team040.mine:worker-05').features;
          const working = features.at_working.properties.value;
          const names = (things) => things.map((thing) => thing.name);
          const look = () => {
            const checked = V.validateShift(response, attributes);
            if (!checked.ok) throw new Error(checked.detail);
            const model = M.buildModel(attributes, checked.snapshot);
            const worker = M.thingByName(model, 'worker-05');
            const zone = M.zoneOfWorking(model, working);
            const place = M.placeOf(model, worker);
            return {
              published: [worker.values.at_working === working, typeof worker.values.offset_m],
              underground: M.isUnderground(worker),
              atWorking: names(M.workersAtWorking(model, working)).includes('worker-05'),
              inZone: names(M.workersInZone(model, zone.name)).includes('worker-05'),
              others: M.workersInZone(model, zone.name).length,
              place: [place.working && place.working.name, place.zone && place.zone.name, place.exit && place.exit.name, place.offsetM],
            };
          };
          const out = {working, before: look()};
          features.status.properties.value = 'out';
          out.out = look();
          features.at_exit = {properties: {value: 'exit-shaft'}};
          out.outWithExit = look();
          return out;
        """)
        working = got["working"]
        self.assertEqual(got["before"]["published"], [True, "number"])
        self.assertEqual((got["before"]["underground"], got["before"]["atWorking"], got["before"]["inZone"]), (True, True, True))
        self.assertEqual(got["before"]["place"][0], working)
        out = got["out"]
        self.assertEqual(out["published"], [True, "number"], "the fixture of the test: the old position is still published")
        self.assertEqual((out["underground"], out["atWorking"], out["inZone"]), (False, False, False))
        self.assertEqual(out["others"], got["before"]["others"] - 1, "the other workers of the zone stay")
        self.assertEqual(out["place"], [None, None, None, None], "no place under ground is claimed")
        self.assertEqual(got["outWithExit"]["place"], [None, None, "exit-shaft", None])


class ArchiveTest(LogicTestCase):
    def test_run_names_in_both_forms_read_the_same_archive(self):
        """S1: `shift.runs` may hold local names or full thingIds; both give the same reads and the same groups."""
        self.mock.scenario("normal")
        got = self.js(LOAD + r"""
          const R = await import('/js/view/runs.js');
          const published = (await api.readShift()).body.features.runs.properties.value;
          const full = published.map((name) => 'team040.mine:' + name);
          const mixed = [full[0], published[0], published[1], 7, null, {}, ...full.slice(1)];
          const out = {
            published,
            names: [V.runNames(published), V.runNames(full), V.runNames(mixed)],
            odd: [V.runNames(undefined), V.runNames('run-0001'), V.runNames([{}, 5, null])],
          };
          const read = await api.readRuns(V.runNames(full));
          out.read = read.ok ? read.body.map((thing) => thing.thingId) : read;
          // What the poller did before: full ids passed on as they came are refused before any request.
          const raw = await api.readRuns(full);
          out.rawRefused = [raw.ok, raw.kind];
          const runs = read.body.map(V.plainRun);
          const shape = (groups) => groups.map((group) => [group.key, group.comparable, group.runs.map((item) => item.run.name)]);
          out.groups = [shape(R.groupRuns(runs, published)), shape(R.groupRuns(runs, full)), shape(R.groupRuns(runs, mixed))];
          return out;
        """)
        names = ["run-0001", "run-0002", "run-0003", "run-0004"]
        self.assertEqual(got["published"], names, "the fixture publishes local names")
        self.assertEqual(got["names"], [names, names, names])
        self.assertEqual(got["odd"], [[], [], []])
        self.assertEqual(got["read"], ["team040.mine:" + name for name in names])
        self.assertEqual(got["rawRefused"], [False, "incomplete"])
        expected = [["ck-7b107a5ea7bd", 0, ["run-0004"]], ["ck-cd9c9d8910d8", 2, ["run-0001", "run-0002", "run-0003"]]]
        self.assertEqual(got["groups"], [expected, expected, expected])

    def test_only_a_classified_finished_run_takes_part_in_a_comparison(self):
        """S3: finished, a known completed ending and not marked incomparable; everything else is told apart."""
        got = self.js(r"""
          const R = await import('/js/view/runs.js');
          const T = await import('/js/text.js');
          const D = await import('/js/view/decision.js');
          const run = (name, values) => ({thingId: 'team040.mine:' + name, name, label: name, units: {},
            values: {comparison_key: 'ck-1', state: 'finished', comparable: true, all_out: false, ...values}});
          const runs = [
            run('r-01', {completion_reason: 'withdrawal_done'}),
            run('r-02', {completion_reason: 'horizon_reached'}),
            run('r-03', {completion_reason: 'reset'}),
            run('r-04', {}),                                                    // no ending published
            run('r-05', {completion_reason: 'evacuated'}),                      // an ending this interface does not know
            run('r-06', {completion_reason: 'withdrawal_done', comparable: false, incomparable_reason: 'condition_changed_after_decision'}),
            run('r-07', {completion_reason: 'withdrawal_done', state: 'running'}),
            run('r-08', {completion_reason: 'withdrawal_done', state: undefined}),
            run('r-09', {completion_reason: 'withdrawal_done', comparable: undefined}),
            run('r-10', {completion_reason: 'withdrawal_done', comparison_key: undefined}),
            run('r-11', {completion_reason: 7}),
            run('r-12', {completion_reason: 'reset', state: 'running'}),
          ];
          const groups = R.groupRuns(runs, runs.map((item) => item.name));
          const flags = {};
          for (const group of groups) {
            for (const item of group.runs) flags[item.run.name] = [item.interrupted, item.unclassified, item.takesPart];
          }
          return {
            flags,
            groups: groups.map((group) => [group.key, group.comparable, group.runs.length]),
            completed: R.COMPLETED_REASONS,
            known: R.COMPLETED_REASONS.every((code) => T.isKnown('completionReason', code)),
            words: [T.UI.runs.unclassified, T.UI.runs.interrupted],
            // The cells of a run without a classified ending follow the rule of an interrupted one.
            cells: [D.metricCell(T, runs[3], '', 'last_out_s', true).text, D.metricCell(T, runs[3], '', 'last_out_s', false).text,
              D.metricCell(T, runs[3], '', 'out', true).text],
          };
        """)
        self.assertEqual(got["flags"], {
            "r-01": [False, False, True], "r-02": [False, False, True],
            "r-03": [True, False, False],
            "r-04": [False, True, False], "r-05": [False, True, False],
            "r-06": [False, False, False],
            "r-07": [False, True, False], "r-08": [False, True, False],
            "r-09": [False, False, True], "r-10": [False, False, False],
            "r-11": [False, True, False], "r-12": [True, False, False],
        })
        self.assertEqual(got["groups"], [["ck-1", 3, 11], [None, 0, 1]])
        self.assertEqual(got["completed"], ["withdrawal_done", "horizon_reached"])
        self.assertTrue(got["known"], "every completed ending has its words in text.js")
        self.assertEqual(got["words"], ["итог не классифицирован, в сравнение не входит", "итог неполный, в сравнение не входит"])
        self.assertEqual(got["cells"], ["—", "нет: не все вышли", "—"])


class PollerTest(LogicTestCase):
    """The poller with a scripted clock and a scripted platform: real answers of the mock, handed out by the test."""

    PRELUDE = LOAD + r"""
      const P = await import('/js/poller.js');
      const S = await import('/js/store.js');
      const mine = await api.readMine();
      const rest = await api.readAttributes(V.validateMine(mine.body).manifest);
      const shift = await api.readShift();
      let t = 0;
      let seq = 1000;
      /** The fixture's state as publication `seq` of `run`, published at the moment it is read. */
      const publication = (run) => {
        const response = clone(shift);
        const features = response.body.features;
        features.publication_seq.properties.value = (seq += 1);
        if (run) {
          features.idSimulationRun.properties.value = run;
          for (const item of features.scene.properties.value) item.features.idSimulationRun.properties.value = run;
        }
        response.dateMs = Date.parse(response.body._modified);
        return response;
      };
      const calls = {mine: 0, attributes: 0, runs: []};
      let mineTakesMs = 0;
      let runsAnswer = {ok: true, status: 200, body: [], dateMs: 0};
      let pendingShift = null;
      const platform = {
        readMine: async () => { calls.mine += 1; t += mineTakesMs; return mine; },
        readAttributes: async () => { calls.attributes += 1; return rest; },
        readShift: () => new Promise((resolve) => { pendingShift = resolve; }),
        readRuns: async (names) => { calls.runs.push([t, names.length]); return runsAnswer; },
      };
      const store = S.createStore(S.initialState());
      const poller = P.createPoller({store, api: platform, now: () => t});
      const until = async (test) => {
        for (let i = 0; i < 1000; i += 1) {
          if (test()) return;
          await new Promise((resolve) => setTimeout(resolve, 2));
        }
        throw new Error('the poller did not get there');
      };
      /** Answer the read of shift that is waiting, one scripted second after it began; return when the next one waits. */
      const answer = async (response) => {
        await until(() => pendingShift !== null);
        const resolve = pendingShift;
        pendingShift = null;
        t += 1000;
        resolve(response);
        await until(() => pendingShift !== null);
      };
      const stop = () => { poller.stop(); if (pendingShift) pendingShift({ok: false, kind: 'network', status: null}); };
      poller.start();
    """

    def test_a_state_read_before_a_slow_re_read_of_attributes_keeps_its_age(self):
        """S4: the snapshot is stamped with the moment `shift` was read, not the moment the attributes came back."""
        self.mock.scenario("normal")
        got = self.js(self.PRELUDE + r"""
          const out = {};
          const link = () => { const status = store.getState().link; return [status.link, status.dataAgeS, status.blocked, status.blockReason]; };
          await answer(publication(null));                     // read at t = 1000
          out.first = [store.getState().snapshot.run, ...link(), calls.mine, calls.attributes];
          // The run changes: attributes are re-read, and that read takes 2.5 s.
          mineTakesMs = 2500;
          await answer(publication('run-0777'));               // read at t = 2000, committed at t = 4500
          mineTakesMs = 0;
          const state = store.getState();
          out.committedAt = t;
          out.second = [state.snapshot.run, ...link(), calls.mine];
          out.oneGeneration = [state.snapshot.run, Object.values(state.snapshot.scene).every((item) => item.values.idSimulationRun === 'run-0777'),
            state.model.things['team040.mine:worker-01'].values.idSimulationRun];
          // The next ordinary read is current again.
          await answer(publication('run-0777'));
          out.third = link();
          stop();
          return out;
        """)
        self.assertEqual(got["first"], ["run-0005", "ok", 0, False, None, 1, 1])
        self.assertEqual(got["committedAt"], 4500)
        self.assertEqual(got["second"], ["run-0777", "stale", 2, True, "stale", 2],
                         "2.5 s passed since the state was read: it is 2 s old and stale, not «0 s ago»")
        self.assertEqual(got["oneGeneration"], ["run-0777", True, "run-0777"])
        self.assertEqual(got["third"], ["ok", 0, False, None])

    def test_a_failed_archive_read_is_retried_every_five_seconds_not_every_poll(self):
        """S9: the status does not flip between reading and failed with every poll."""
        self.mock.scenario("normal")
        got = self.js(self.PRELUDE + r"""
          const out = {statuses: []};
          const runs = await api.readRuns(V.runNames(shift.body.features.runs.properties.value));
          runsAnswer = {ok: false, kind: 'http', status: 502};
          const seen = [];
          store.subscribe((state, previous) => { if (state.archive !== previous.archive) seen.push(state.archive.status); });
          for (let poll = 1; poll <= 12; poll += 1) {
            await answer(publication(null));
            out.statuses.push(store.getState().archive.status);
          }
          out.failedCalls = calls.runs.map((call) => call[0]);
          out.failure = store.getState().archive.failure;
          out.transitions = [...seen];
          // The platform answers again: the next due retry reads the archive, and then it is left alone.
          runsAnswer = runs;
          for (let poll = 13; poll <= 20; poll += 1) await answer(publication(null));
          const archive = store.getState().archive;
          out.recovered = [archive.status, archive.runs.length, archive.failure, archive.ids];
          out.allCalls = calls.runs.map((call) => call[0]);
          out.batch = calls.runs[0][1];
          stop();
          return out;
        """)
        self.assertEqual(got["failedCalls"], [1000, 6000, 11000], "one try per 5 s while the archive cannot be read")
        self.assertEqual(got["statuses"], ["error"] * 12)
        self.assertEqual(got["transitions"], ["loading", "error", "error", "error"],
                         "«reading» is shown once; a retry does not take the failure off the screen")
        self.assertEqual(got["failure"], {"kind": "http", "status": 502})
        self.assertEqual(got["allCalls"], [1000, 6000, 11000, 16000])
        self.assertEqual(got["recovered"], ["ready", 4, None, ["run-0001", "run-0002", "run-0003", "run-0004"]])
        self.assertEqual(got["batch"], 4)


class TextTest(LogicTestCase):
    def test_formatters(self):
        got = self.js(r"""
          const T = await import('/js/text.js');
          return {
            modelTime: [T.modelTime(8120), T.modelTime(0), T.modelTime(59.9), T.modelTime(360000), T.modelTime(-1), T.modelTime(undefined)],
            duration: [T.duration(524), T.duration(330), T.duration(44), T.duration(600), T.duration(3725), T.duration(0),
              T.duration(3600), T.duration(null)],
            num: [T.num(2.6), T.num(42.0), T.num(-260), T.num(0.125), T.num(0.12), T.num(1000000), T.num(-0.001),
              T.num(9.6, 0), T.num('7'), T.num(NaN)],
            units: ['m', 'mm', 'mm/h', 't/h', 's', 'person*s', 'zone*s', '1', 'kPa', undefined].map(T.unit),
            quantity: [T.quantity(2.6, 'mm/h'), T.quantity(655, 'm'), T.quantity(0.21, '1'), T.quantity(38, 't/h'),
              T.quantity(120, 'person*s'), T.quantity(530, 'zone*s'), T.quantity(14, undefined), T.quantity(undefined, 'm'),
              T.quantity(5, 'kPa')],
            utc: [T.utcTime('2026-10-18T09:02:11.184Z'), T.utcTime(Date.UTC(2026, 9, 18, 23, 5, 9)), T.utcTime('2026-10-18T12:02:11+03:00'),
              T.utcTime(null), T.utcTime('yesterday')],
            tickTime: [T.tickTime(8120, 812), T.tickTime(undefined, undefined)],
            plural: [1, 2, 5, 11, 12, 21, 22, 25, 101, 111].map((n) => T.counted(n, T.FORMS.worker)),
            yesNo: [T.yesNo(true), T.yesNo(false), T.yesNo(undefined)],
            age: [T.ageText(1), T.ageText(75), T.ageText(null)],
          };
        """)
        got = json.loads(plain(json.dumps(got, ensure_ascii=False)))
        self.assertEqual(got["modelTime"], ["02:15:20", "00:00:00", "00:00:59", "100:00:00", "—", "—"])
        self.assertEqual(got["duration"], ["8 мин 44 с", "5 мин 30 с", "44 с", "10 мин", "1 ч 2 мин 5 с", "0 с", "1 ч", "—"])
        self.assertEqual(got["num"], ["2,6", "42", "−260", "0,13", "0,12", "1000000", "0", "10", "—", "—"])
        self.assertEqual(got["units"], ["м", "мм", "мм/ч", "т/ч", "с", "чел.·с", "уч.·с", "", "kPa", ""])
        self.assertEqual(got["quantity"], ["2,6 мм/ч", "655 м", "0,21", "38 т/ч", "120 чел.·с", "530 уч.·с", "14", "—", "5 kPa"])
        self.assertEqual(got["utc"], ["09:02:11 UTC", "23:05:09 UTC", "09:02:11 UTC", "—", "—"])
        self.assertEqual(got["tickTime"], ["02:15:20 · тик 812", "—"])
        self.assertEqual(got["plural"], ["1 работник", "2 работника", "5 работников", "11 работников", "12 работников",
                                         "21 работник", "22 работника", "25 работников", "101 работник", "111 работников"])
        self.assertEqual(got["yesNo"], ["да", "нет", "—"])
        self.assertEqual(got["age"], ["данные 1 с назад", "данные 1 мин 15 с назад", "данных нет"])

    def test_vocabularies_and_unknown_codes(self):
        got = self.js(r"""
          const T = await import('/js/text.js');
          const required = {
            hazard: ['normal', 'attention', 'danger', 'unknown'], quality: ['fresh', 'stale', 'lost', 'none'],
            posQuality: ['fresh', 'stale', 'lost'], linkState: ['online', 'offline'], passability: ['open', 'closed'],
            closedBy: ['none', 'scenario', 'dispatcher'], restriction: ['blocked', 'allowed', 'unknown'],
            workState: ['working', 'stopped'], withdrawal: ['none', 'in_progress', 'done', 'incomplete'],
            workerStatus: ['working', 'moving_to_exit', 'waiting', 'out', 'unknown'], egress: ['ok', 'none', 'unknown'],
            egressReason: ['none', 'no_open_path', 'position_unknown', 'not_computed', 'current_working_closed'],
            exitState: ['available', 'unavailable', 'unknown'], exitKind: ['shaft', 'ramp', 'raise'],
            sensorKind: ['extensometer', 'convergence', 'geophone'],
            workingKind: ['drift', 'crosscut', 'ramp', 'shaft', 'raise'],
            reasonCode: ['none', 'rate_above_attention', 'rate_above_danger', 'events_above_danger', 'index_above_attention',
              'index_above_danger', 'sensor_stale', 'sensor_lost', 'no_sensor'],
            runState: ['running', 'paused', 'resetting'], pauseReason: ['none', 'decision'],
            incidentState: ['none', 'active', 'executing', 'done'], incidentTrigger: ['hazard', 'passage_closed', 'data_lost'],
            optionKind: ['observe', 'stop_withdraw_zone', 'withdraw_all'],
            optionState: ['inactive', 'offered', 'executing', 'done', 'unavailable'], forecastQuality: ['full', 'partial'],
            archiveRunState: ['running', 'finished'], completionReason: ['withdrawal_done', 'horizon_reached', 'reset'],
            conditionKind: ['working_closed', 'sensor_lost', 'instability'],
            commandType: (await import('/js/commands.js')).COMMAND_TYPES,
            ackReason: ['none', 'already_in_state', 'not_allowed_in_state', 'malformed', 'unknown_type', 'unknown_target',
              'invalid_run', 'command_id_conflict', 'stale_decision', 'insufficient_workers'],
            journalCode: ['run.started', 'run.reset', 'condition.set', 'condition.cancelled', 'hazard.changed',
              'quality.changed', 'command.applied', 'command.rejected', 'zone.stopped', 'zone.resumed',
              'withdrawal.started', 'withdrawal.finished', 'worker.route_changed', 'worker.no_route', 'worker.out'],
            kind: ['mine', 'level', 'working', 'zone', 'sensor', 'worker', 'exit', 'shift', 'incident', 'option', 'run', 'journal'],
            linkStatus: ['ok', 'degraded', 'stale', 'unavailable'], publications: ['alive', 'stopped', 'unknown'],
            blockReason: ['not_ready', 'platform_unavailable', 'stale', 'no_snapshot', 'snapshot_invalid',
              'publications_stopped', 'resetting', 'own_reset_pending'],
            pendingPhase: ['sending', 'sent', 'applied', 'rejected', 'no_ack', 'delivery_unknown', 'not_sent'],
          };
          const missing = [];
          for (const [vocab, codes] of Object.entries(required)) {
            for (const code of codes) if (!T.isKnown(vocab, code)) missing.push(vocab + ':' + code);
          }
          const source = await (await fetch('/js/text.js')).text();
          return {
            missing,
            texts: {
              normal: T.label('hazard', 'normal'), none: T.label('quality', 'none'), noRoute: T.label('egress', 'none'),
              route: T.label('egress', 'ok'), reset: T.label('completionReason', 'reset'),
              closed: T.label('egressReason', 'current_working_closed'),
            },
            unknown: [T.label('hazard', 'elevated'), T.label('workerStatus', 'resting'), T.label('hazard', undefined),
              T.label('hazard', 'constructor'), T.isKnown('hazard', 'toString')],
            asIs: [T.codeLabel('optionKind', 'shelter'), T.codeLabel('journalCode', 'ventilation.changed'),
              T.codeLabel('journalCode', 'worker.out'), T.codeLabel('optionKind', undefined)],
            hazardText: [
              T.hazardText({state: 'unknown', raw: 'elevated', known: false, defensive: false}),
              T.hazardText({state: 'unknown', raw: 'normal', known: true, defensive: true}),
              T.hazardText({state: 'danger', raw: 'danger', known: true, defensive: false}),
            ],
            fields: [T.fieldLabel('instability_index'), T.fieldLabel('forecast_no_route'), T.fieldLabel('actual_last_out_s'),
              T.fieldLabel('downtime_s', 'zone'), T.fieldLabel('downtime_s', 'option'), T.fieldLabel('made_up_field'),
              T.metricLabel('downtime_s'), T.metricLabel('nope')],
            metrics: T.METRICS,
            notice: T.NOTICE,
            forbidden: ['безопасн', 'вероятност', 'риск обрушения'].filter((word) => source.toLowerCase().includes(word)),
            ack: [
              T.ackText({status: 'applied', reason: 'none'}), T.ackText({status: 'applied', reason: 'already_in_state'}),
              T.ackText({status: 'rejected', reason: 'insufficient_workers'}), T.ackText({status: 'rejected', reason: 'not_scripted'}),
              T.ackText({status: 'lost'}),
            ],
            pending: [
              T.pendingText({phase: 'sent'}, 2), T.pendingText({phase: 'no_ack'}),
              T.pendingText({phase: 'delivery_unknown', failure: {kind: 'timeout', status: null}}),
              T.pendingText({phase: 'delivery_unknown', failure: {kind: 'http', status: 503}}),
              T.pendingText({phase: 'not_sent', failure: {kind: 'http', status: 400}}),
              T.pendingText({phase: 'not_sent', failure: {kind: 'blocked', status: null, reason: 'stale'}}),
              T.pendingText({phase: 'rejected', ack: {status: 'rejected', reason: 'stale_decision'}}),
              T.pendingText({phase: 'applied', ack: {status: 'applied', reason: 'already_in_state'}}),
            ],
            buttons: [T.UI.pending.retry, T.UI.pending.dismiss],
            command: [T.commandText('condition.close_working', 'w-12', () => 'В-12'), T.commandText('run.reset', 'run'),
              T.commandText('custom.type', 'x')],
          };
        """)
        got = json.loads(plain(json.dumps(got, ensure_ascii=False)))
        self.assertEqual(got["missing"], [])
        self.assertEqual(got["texts"], {
            "normal": "норма", "none": "без датчиков, состояние не оценивается", "noRoute": "нет расчётного маршрута",
            "route": "расчётный маршрут (модель)", "reset": "прерван сбросом",
            "closed": "закрыта выработка, в которой находится работник",
        })
        self.assertEqual(got["unknown"], ["неизвестно (elevated)", "неизвестно (resting)", "—", "неизвестно (constructor)", False])
        self.assertEqual(got["asIs"], ["shelter", "ventilation.changed", "работник вышел", "—"])
        self.assertEqual(got["hazardText"], ["состояние неизвестно (код elevated)", "состояние неизвестно", "опасно"])
        self.assertEqual(got["fields"], ["синтетический индекс нестабильности", "прогноз: без расчётного маршрута",
                                         "факт: время выхода всех", "простой участка", "суммарный простой участков",
                                         "made_up_field", "суммарный простой участков", "nope"])
        self.assertEqual(got["metrics"], ["in_danger", "danger_exposure_person_s", "unknown_exposure_person_s", "no_route",
                                          "out", "all_out", "last_out_s", "downtime_s"])
        self.assertEqual(got["notice"], "Синтетические данные. Расчёт модели, не сведения о реальной шахте")
        self.assertEqual(got["forbidden"], [], "wording rules of DESIGN.md 2.2")
        self.assertEqual(got["ack"], [
            "применена", "применена без изменения: состояние уже такое",
            "отклонена: на участке недостаточно персонала (insufficient_workers)",
            "отклонена: неизвестная причина (not_scripted)", "неизвестный результат (lost)",
        ])
        self.assertEqual(got["pending"], [
            "Команда отправлена, не подтверждена (2 с)",
            "Нет подтверждения 5 с. Команда могла не дойти",
            "Результат доставки неизвестен (нет ответа за 3 с). Команда могла дойти до модели",
            "Результат доставки неизвестен (HTTP 503). Команда могла дойти до модели",
            "Команда не отправлена: HTTP 400",
            "Команда не отправлена: команды заблокированы: данные устарели",
            "Команда отклонена: решение устарело: условия изменились (stale_decision)",
            "Команда применена без изменения: состояние уже такое",
        ])
        self.assertEqual(got["buttons"], ["Повторить с тем же идентификатором", "Снять ожидание"])
        self.assertEqual(got["command"], ["Закрыть выработку: В-12", "Полный сброс прогона", "custom.type: x"])

    def test_option_state_and_withdrawal_words(self):
        """S6: an option the model no longer offers is «недоступен»; a finished withdrawal without a known outcome is not «завершён»."""
        got = self.js(r"""
          const T = await import('/js/text.js');
          const J = await import('/js/view/journal.js');
          const state = {model: {byName: {'zone-a': {label: 'Участок А'}}}, attributes: null};
          const event = (arg) => J.eventText(T, state, {code: 'withdrawal.finished', subject: 'zone-a', arg});
          return {
            option: T.label('optionState', 'unavailable'),
            code: T.codeLabel('journalCode', 'withdrawal.finished'),
            events: [event('done'), event('incomplete'), event(undefined), event('aborted'), event(7)],
          };
        """)
        self.assertEqual(got["option"], "недоступен")
        self.assertEqual(got["code"], "вывод персонала окончен")
        self.assertEqual(got["events"], [
            "Участок А: вывод персонала завершён", "Участок А: вывод не завершён",
            "Участок А: вывод персонала окончен", "Участок А: вывод персонала окончен — aborted",
            "Участок А: вывод персонала окончен — 7",
        ])

    def test_state_sentences_and_banners(self):
        got = self.js(r"""
          const T = await import('/js/text.js');
          const {initialState} = await import('/js/store.js');
          const names = {'exit-ramp': 'Съезд', 'exit-shaft': 'Ствол', 'sens-ext-03': 'Э-03', 'w-07': 'В-07',
            'sens-ext-05': 'Э-05', 'zone-b': 'Участок Б', 'worker-05': 'Р-05', 'worker-14': 'Р-14'};
          const labelOf = (name) => names[name] || name;
          const snapshot = {modifiedMs: Date.UTC(2026, 9, 18, 9, 2, 11), tick: 812, run: 'run-0003'};
          const state = (link, extra = {}) => ({...initialState(), boot: 'ready', snapshot,
            link: {...initialState().link, ...link}, ...extra});
          const banner = (code, st) => { const b = T.bannerText(code, st, labelOf); return b.title + ' ' + b.text; };
          const invalid = (code, params) => ({snapshot: 'invalid', invalid: {code, params, detail: 'd'}});
          return {
            egress: [
              T.egressText({egress_status: 'ok', egress_length_m: 655, egress_detour_m: 243, egress_eta_s: 524, egress_exit: 'exit-ramp'}, labelOf),
              T.egressText({egress_status: 'ok', egress_length_m: 412, egress_detour_m: 0, egress_eta_s: 330, egress_exit: 'exit-shaft'}, labelOf),
              T.egressText({egress_status: 'none', egress_reason: 'no_open_path'}, labelOf),
              T.egressText({egress_status: 'none', egress_reason: 'current_working_closed'}, labelOf),
              T.egressText({egress_status: 'unknown', egress_reason: 'not_computed'}, labelOf),
              T.egressText({egress_status: 'teleport'}, labelOf),
              T.egressText({status: 'out', at_exit: 'exit-shaft', egress_status: 'ok'}, labelOf),
            ],
            crosses: [T.crossesText({egress_crosses: 'danger'}), T.crossesText({egress_crosses: 'normal'}), T.crossesText({})],
            reason: T.reasonText({reason_code: 'rate_above_danger', reason_sensor: 'sens-ext-03', reason_value: 2.6,
              reason_threshold: 2.0, reason_unit: 'mm/h'}, labelOf),
            noReason: T.reasonText({reason_code: 'none'}, labelOf),
            passability: [T.passabilityText({passability: 'closed', closed_by: 'scenario'}), T.passabilityText({passability: 'open', closed_by: 'none'})],
            conditions: [
              T.conditionText({raw: 'working_closed:w-07', kind: 'working_closed', target: 'w-07'}, labelOf),
              T.conditionText({raw: 'sensor_lost:sens-ext-05', kind: 'sensor_lost', target: 'sens-ext-05'}, labelOf),
              T.conditionText({raw: 'instability:zone-b', kind: 'instability', target: 'zone-b'}, labelOf),
              T.conditionText({raw: 'flood:w-07', kind: 'flood', target: 'w-07'}, labelOf),
            ],
            failures: [T.failureText({kind: 'http', status: 502}), T.failureText({kind: 'timeout', status: null}),
              T.failureText({kind: 'network', status: null}), T.failureText(null)],
            banners: {
              unavailable: banner('platform_unavailable', state({link: 'unavailable', failure: {kind: 'http', status: 502}})),
              unavailableNoData: banner('platform_unavailable', state({link: 'unavailable', failure: {kind: 'timeout', status: null}}, {snapshot: null})),
              stopped: banner('publications_stopped', state({publications: 'stopped'})),
              paused: banner('paused_decision', state({})),
              resetting: banner('resetting', state({})),
              empty: banner('empty_stand', state({}, {boot: 'empty', snapshot: null})),
              topology: banner('topology_mismatch', state(invalid('topology_mismatch', {attributes: 't1', shift: 't2'}))),
              field: banner('snapshot_invalid', state(invalid('missing_field', {thing: 'worker-05', field: 'egress_status'}))),
              missingId: banner('snapshot_invalid', state(invalid('scene_missing_id', {ids: ['team040.mine:worker-14']}))),
              version: banner('snapshot_invalid', state(invalid('contract_version', {expected: 1, actual: 2}))),
              bootVersion: banner('contract_version', state({}, {boot: 'error', snapshot: null,
                bootError: {code: 'contract_version', params: {expected: 1, actual: 7}, detail: 'd'}})),
              manifest: banner('manifest_incomplete', state({}, {boot: 'error', snapshot: null,
                bootError: {code: 'manifest_incomplete', params: {ids: ['team040.mine:w-07'], total: 77}, detail: 'd'}})),
              degraded: banner('link_degraded', state({link: 'degraded', failure: {kind: 'http', status: 503}})),
              stale: banner('stale', state({link: 'stale', failure: {kind: 'timeout', status: null}})),
            },
            order: T.BANNER_ORDER,
            severities: T.BANNER_ORDER.filter((code) => !T.BANNER_SEVERITY[code]),
          };
        """)
        got = json.loads(plain(json.dumps(got, ensure_ascii=False)))
        self.assertEqual(got["egress"], [
            "расчётный маршрут (модель): 655 м (длиннее на 243 м), около 8 мин 44 с, выход Съезд",
            "расчётный маршрут (модель): 412 м, около 5 мин 30 с, выход Ствол",
            "нет расчётного маршрута: в графе модели нет открытого пути до выхода",
            "нет расчётного маршрута: закрыта выработка, в которой находится работник",
            "маршрут не рассчитан: расчёт не выполнен",
            "неизвестно (teleport)",
            "вышел через Ствол",
        ])
        self.assertEqual(got["crosses"], ["маршрут проходит через участок «опасно»", "", ""])
        self.assertEqual(got["reason"], "скорость изменения выше порога «опасно»: датчик Э-03, значение 2,6 мм/ч, порог 2 мм/ч")
        self.assertEqual(got["noReason"], "")
        self.assertEqual(got["passability"], ["проход закрыт (условие стенда)", "проход открыт"])
        self.assertEqual(got["conditions"], ["В-07 закрыта", "Э-05 без связи", "Участок Б рост нестабильности",
                                             "flood:w-07 (неизвестное условие)"])
        self.assertEqual(got["failures"], ["HTTP 502", "нет ответа за 3 с", "ошибка сети", ""])
        banners = got["banners"]
        self.assertEqual(banners["unavailable"],
                         "Платформа недоступна (HTTP 502). Показаны данные на 09:02:11 UTC, тик 812. Текущее состояние неизвестно")
        self.assertEqual(banners["unavailableNoData"],
                         "Платформа недоступна (нет ответа за 3 с). Данные ещё не получены. Текущее состояние неизвестно")
        self.assertTrue(banners["stopped"].startswith("Публикации модели остановились. "), banners["stopped"])
        self.assertIn("тик 812", banners["stopped"])
        self.assertTrue(banners["paused"].startswith("Модель на паузе для выбора действия."))
        self.assertTrue(banners["resetting"].startswith("Выполняется сброс. Новый прогон ещё не начался"))
        self.assertEqual(banners["empty"],
                         "Двойники рудника не найдены в платформе. Платформа отвечает, объектов в team040.mine нет")
        self.assertTrue(banners["topology"].startswith(
            "Схема не показана: версия топологии в двойниках (t1) не совпадает с версией модели (t2)."), banners["topology"])
        self.assertTrue(banners["field"].startswith(
            "Состояние не принято: у объекта Р-05 (worker-05) нет обязательного поля egress_status."), banners["field"])
        self.assertIn("Показан последний полный снимок: 09:02:11 UTC, тик 812", banners["field"])
        self.assertIn("Команды заблокированы", banners["field"])
        self.assertIn("в состоянии нет 1 объект: Р-14 (worker-14)", banners["missingId"])
        self.assertIn("версия контракта данных 2, интерфейс работает с версией 1", banners["version"])
        self.assertIn("Версия контракта данных 7, интерфейс работает с версией 1", banners["bootVersion"])
        self.assertIn("не вернула атрибуты 1 из 77 объектов: В-07 (w-07)", banners["manifest"])
        self.assertTrue(banners["degraded"].startswith("Связь с платформой ухудшилась (HTTP 503)."))
        self.assertTrue(banners["stale"].startswith("Данные устарели: полного снимка нет дольше 2 с (нет ответа за 3 с)."))
        self.assertEqual(got["order"][0], "platform_unavailable")
        self.assertEqual(got["order"][-1], "paused_decision")
        self.assertEqual(len(got["order"]), 11)
        self.assertEqual(got["severities"], [])


class RouterStoreDomTest(LogicTestCase):
    def test_hash_routes_both_ways(self):
        got = self.js(r"""
          const R = await import('/js/router.js');
          const {initialState} = await import('/js/store.js');
          const base = initialState().ui;
          const parse = (hash, current = base) => R.parseHash(hash, current);
          const hashes = ['#/scheme', '#/scheme?sel=team040.mine:w-12', '#/scheme?sel=team040.mine:worker-03&view=plan&level=level-320',
            '#/scheme?view=plan', '#/list', '#/list?type=worker', '#/list?type=sensor&sel=team040.mine:sens-ext-05', '#/runs',
            '#/scheme?mode=scheme', '#/scheme?sel=team040.mine:w-12&view=plan&mode=3d'];
          return {
            parsed: {
              empty: parse(''), scheme: parse('#/scheme?sel=team040.mine:w-12&view=plan&level=level-320'),
              list: parse('#/list?type=worker&sel=team040.mine:worker-03'), runs: parse('#/runs'),
              garbage: parse('#/nowhere?sel=<img src=x>&view=3d&level=../etc'),
              encoded: parse('#/scheme?sel=team040.mine%3Aw-12'),
              badType: parse('#/list?type=dragon'),
              keepsOtherFields: parse('#/list?type=zone', {...base, projection: 'plan', level: 'level-320'}),
              command: parse('#/scheme?type=run.reset&command=run.reset&target=run'),
              mode3d: parse('#/scheme?mode=3d'), modeScheme: parse('#/scheme?sel=team040.mine:w-12&mode=scheme'),
              badMode: parse('#/scheme?mode=vr'),
              // The stage mode is kept by a route that does not carry it, in every view, and written only in the scheme view.
              modeKept: parse('#/list?type=zone', {...base, stageMode: 'scheme'}),
              listHash: R.formatHash({...base, view: 'list', stageMode: 'scheme'}),
            },
            roundTrip: hashes.filter((hash) => R.formatHash(parse(hash)) !== hash),
            types: R.LIST_TYPES,
          };
        """)
        parsed = got["parsed"]
        # The route fields, plus the fields of the stage (redesign): stageMode from the hash (`mode`), quality and
        # explode only from the stage's own controls, all three unset by default.
        default = {"view": "scheme", "projection": "axo", "level": None, "selected": None, "listType": "all",
                   "stageMode": None, "quality": None, "explode": None}
        stage = {"stageMode": None, "quality": None, "explode": None}
        self.assertEqual(parsed["empty"], default)
        self.assertEqual(parsed["scheme"], {"view": "scheme", "projection": "plan", "level": "level-320",
                                            "selected": "team040.mine:w-12", "listType": "all", **stage})
        self.assertEqual(parsed["list"], {"view": "list", "projection": "axo", "level": None,
                                          "selected": "team040.mine:worker-03", "listType": "worker", **stage})
        self.assertEqual(parsed["runs"]["view"], "runs")
        self.assertEqual(parsed["garbage"], default)
        self.assertEqual(parsed["encoded"]["selected"], "team040.mine:w-12")
        self.assertEqual(parsed["badType"]["listType"], "all")
        self.assertEqual(parsed["keepsOtherFields"], {"view": "list", "projection": "plan", "level": "level-320",
                                                      "selected": None, "listType": "zone", **stage})
        self.assertEqual(parsed["command"], default, "a route carries a view and a selection, nothing else")
        self.assertEqual(parsed["mode3d"], {**default, "stageMode": "3d"})
        self.assertEqual(parsed["modeScheme"], {**default, "selected": "team040.mine:w-12", "stageMode": "scheme"})
        self.assertEqual(parsed["badMode"], default, "an unknown mode leaves the stage to its own choice")
        self.assertEqual(parsed["modeKept"]["stageMode"], "scheme", "a route without `mode` keeps the chosen stage")
        self.assertEqual(parsed["listHash"], "#/list", "the mode is written only in the scheme view")
        self.assertEqual(got["roundTrip"], [])
        self.assertEqual(got["types"][0], "all")

    def test_store_notifies_only_on_change(self):
        got = self.js(r"""
          const S = await import('/js/store.js');
          const store = S.createStore(S.initialState(), (state) => ({commandsBlocked: state.boot !== 'ready'}));
          const log = [];
          store.subscribe((state, previous) => log.push(['all', previous.boot, state.boot]));
          const stop = store.watch((state) => state.ui.view, (view) => log.push(['view', view]));
          store.watch((state) => [state.boot, state.ui.selected], ([boot, selected]) => log.push(['pair', boot, selected]));
          store.update({boot: 'loading'});                       // nothing changed
          store.update(() => null);                              // nothing to change
          store.update({boot: 'ready'});
          const derived = store.getState().commandsBlocked;
          store.update((state) => ({ui: {...state.ui, selected: 'team040.mine:w-01'}}));
          store.update((state) => ({ui: {...state.ui, view: 'list'}}));
          stop();
          store.update((state) => ({ui: {...state.ui, view: 'runs'}}));
          // An update from inside a listener is delivered after the current round, in order.
          const order = [];
          const nested = S.createStore({...S.initialState()});
          nested.subscribe((state) => { order.push('a:' + state.boot); if (state.boot === 'ready') nested.update({boot: 'error'}); });
          nested.subscribe((state) => order.push('b:' + state.boot));
          nested.update({boot: 'ready'});
          return {log, derived, order, same: [S.sameSelection([1, 'a'], [1, 'a']), S.sameSelection([1], [2]), S.sameSelection(1, 1)]};
        """)
        self.assertEqual(got["log"], [
            ["view", "scheme"], ["pair", "loading", None],
            ["all", "loading", "ready"], ["pair", "ready", None],
            ["all", "ready", "ready"], ["pair", "ready", "team040.mine:w-01"],
            ["all", "ready", "ready"], ["view", "list"],
            ["all", "ready", "ready"],
        ])
        self.assertFalse(got["derived"])
        self.assertEqual(got["order"], ["a:ready", "b:ready", "a:error", "b:error"])
        self.assertEqual(got["same"], [True, False, True])

    def test_a_throwing_listener_does_not_starve_the_later_ones(self):
        """M1: one view that fails on a state must not keep that state, or any later one, from the other views."""
        got = self.js(r"""
          const S = await import('/js/store.js');
          const logged = [];
          const realError = console.error;
          console.error = (...args) => { logged.push(args.map((item) => (item && item.message) || String(item)).join(' ')); };
          try {
            const store = S.createStore(S.initialState());
            const seen = {before: [], after: [], watcher: [], nested: []};
            store.subscribe((state) => seen.before.push(state.boot));
            store.subscribe((state) => { if (state.boot !== 'loading') throw new Error('view failed on ' + state.boot); });
            store.watch((state) => state.boot, (boot) => { if (boot === 'ready') throw new Error('watcher failed'); seen.watcher.push(boot); });
            store.subscribe((state) => seen.after.push(state.boot));
            // A listener that updates the store while another one throws: the queued round is delivered too.
            store.subscribe((state) => { seen.nested.push(state.boot); if (state.boot === 'ready') store.update({boot: 'error'}); });
            let thrown = null;
            try {
              store.update({boot: 'ready'});
              store.update({boot: 'empty'});
            } catch (error) {
              thrown = error.message;
            }
            // The store itself goes on working after the failures.
            store.update({boot: 'ready'});
            return {seen, thrown, logged, state: store.getState().boot};
          } finally {
            console.error = realError;
          }
        """)
        self.assertIsNone(got["thrown"], "an update does not throw into the code that made it")
        rounds = ["ready", "error", "empty", "ready", "error"]
        self.assertEqual(got["seen"]["before"], rounds)
        self.assertEqual(got["seen"]["after"], rounds, "listeners after the failing ones got every state")
        self.assertEqual(got["seen"]["nested"], rounds)
        self.assertEqual(got["seen"]["watcher"], ["loading", "error", "empty", "error"])
        self.assertEqual(got["state"], "error")
        self.assertEqual([entry for entry in got["logged"] if "watcher failed" in entry], ["watcher failed", "watcher failed"])
        self.assertEqual(len([entry for entry in got["logged"] if "view failed on" in entry]), 5, "every failure is logged")

    def test_reconcile_keeps_nodes_and_focus(self):
        got = self.js(r"""
          const D = await import('/js/dom.js');
          const list = D.h('ul');
          document.body.append(list);
          let created = 0;
          const render = (items) => D.reconcile(list, items, (item) => item.id,
            (item) => { created += 1; return D.h('li', null, D.h('button', {type: 'button', id: 'b-' + item.id})); },
            (node, item) => D.setAttrs(node, {'data-value': item.value, class: ['row', item.on && 'is-on'], hidden: item.hidden}));
          render([{id: 'a', value: 1}, {id: 'b', value: 2}, {id: 'c', value: 3}]);
          const nodeC = list.children[2];
          document.getElementById('b-c').focus();
          render([{id: 'b', value: 20, on: true}, {id: 'c', value: 30}]);          // the first item is gone
          const out = {
            order: [...list.children].map((node) => node.firstChild.id),
            sameNode: list.children[1] === nodeC, focus: document.activeElement.id, created,
            attrs: [list.children[0].getAttribute('data-value'), list.children[0].className, list.children[1].className],
          };
          render([{id: 'd', value: 4}, {id: 'c', value: 31, hidden: true}, {id: 'b', value: 21}]);   // added and reordered
          out.reordered = [...list.children].map((node) => node.firstChild.id);
          out.hidden = list.children[1].hidden;
          out.createdAfter = created;
          let duplicate = null;
          try { render([{id: 'x'}, {id: 'x'}]); } catch (error) { duplicate = error.message; }
          out.duplicate = duplicate;
          // Attributes: null and false remove, true sets an empty attribute, text is not parsed as markup.
          const node = D.h('p', {title: 'x', 'data-a': '1', hidden: true, text: '<b>bold</b>'});
          D.setAttrs(node, {title: null, 'data-a': false, dataset: {kind: 'zone', gone: null}});
          out.node = [node.hasAttribute('title'), node.hasAttribute('data-a'), node.getAttribute('hidden'), node.dataset.kind,
            node.children.length, node.textContent];
          const svg = D.s('svg', {viewBox: '0 0 1 1'}, D.s('path', {d: 'M0 0'}));
          out.svg = [svg.namespaceURI, svg.firstChild.namespaceURI, D.glyph('danger').getAttribute('data-glyph'),
            D.glyph('nonsense').getAttribute('data-glyph')];
          const holder = D.h('span');
          D.setGlyph(holder, 'ok'); const first = holder.firstChild;
          D.setGlyph(holder, 'ok'); const kept = holder.firstChild === first;
          D.setGlyph(holder, 'danger');
          out.glyph = [kept, holder.children.length, holder.firstChild.getAttribute('data-glyph')];
          let activated = 0;
          const row = D.h('div', {tabindex: 0});
          D.onActivate(row, () => { activated += 1; });
          row.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter'}));
          row.dispatchEvent(new KeyboardEvent('keydown', {key: ' '}));
          row.dispatchEvent(new KeyboardEvent('keydown', {key: 'a'}));
          row.click();
          out.activated = activated;
          list.remove();
          return out;
        """)
        self.assertEqual(got["order"], ["b-b", "b-c"])
        self.assertTrue(got["sameNode"])
        self.assertEqual(got["focus"], "b-c", "removing a sibling must not take the focus away")
        self.assertEqual(got["created"], 3)
        self.assertEqual(got["attrs"], ["20", "row is-on", "row"])
        self.assertEqual(got["reordered"], ["b-d", "b-c", "b-b"])
        self.assertTrue(got["hidden"])
        self.assertEqual(got["createdAfter"], 4)
        self.assertIn("duplicate key", got["duplicate"])
        self.assertEqual(got["node"], [False, False, "", "zone", 0, "<b>bold</b>"])
        self.assertEqual(got["svg"], ["http://www.w3.org/2000/svg", "http://www.w3.org/2000/svg", "danger", "unknown"])
        self.assertEqual(got["glyph"], [True, 1, "danger"])
        self.assertEqual(got["activated"], 3)
