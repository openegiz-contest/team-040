"""Tests of the contract fixtures and of the mock server (no browser).

Run from the repository root:
    python -m unittest discover -s team/ui/tests -t team/ui -p "test_mock_server.py" -v

The fixtures hold invented test data; these tests check that the data are
self-consistent and that the server replays them as fixtures/README.md says.
Nothing here measures the stand. Standard library only, no fixed port.
"""

import email.utils
import http.client
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
FIXTURES = UI_DIR / "fixtures"
GENERATOR = UI_DIR / "tools" / "build_fixtures.py"
SERVER = UI_DIR / "tools" / "mock_server.py"

sys.path.insert(0, str(UI_DIR / "tools"))
import mock_server  # noqa: E402  (FixtureFormatError, FIXTURE_FORMAT)

NS = "team040.mine"
THINGS = "/ditto/api/2/things"
SHIFT = f"{THINGS}/{NS}:shift?fields=thingId,features,_modified,_revision"
MINE = f"{THINGS}/{NS}:mine?fields=thingId,attributes"
COMMAND = f"{THINGS}/{NS}:shift/inbox/messages/command?timeout=0"
SPEED_M_S = 1.25
STEP_M = 12.5

SCENARIOS = [
    "normal", "detour", "no_path", "sensor_lost_after_danger", "danger_zone",
    "paused_heartbeat", "frozen_seq", "frozen_seq_old", "invalid_missing_id", "invalid_duplicate_id",
    "invalid_mixed_tick", "invalid_missing_field", "invalid_contract_version",
    "invalid_no_metadata", "topology_mismatch", "topology_change", "commands",
    "reset", "withdrawal_incomplete", "no_forecast", "partial_forecast",
    "route_segments", "unknown_enum", "empty",
]
# scenario -> the one violation its "violated" state carries
INVALID = {
    "invalid_missing_id": "missing_id", "invalid_duplicate_id": "duplicate_id",
    "invalid_mixed_tick": "mixed_tick", "invalid_missing_field": "missing_field",
    "invalid_contract_version": "contract_version", "invalid_no_metadata": "no_metadata",
}


def tid(local):
    return f"{NS}:{local}"


def val(features, name, default=None):
    feature = features.get(name)
    return default if feature is None else feature["properties"]["value"]


def load_fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def scene_of(features):
    return val(features, "scene", [])


def element(features, local):
    for el in scene_of(features):
        if el["thingId"] == tid(local):
            return el["features"]
    raise AssertionError(f"{local} is not in the scene")


# ---------------------------------------------------------------------------
# Reference validator: the snapshot validity rules of the UI spec, section 4
# ---------------------------------------------------------------------------

REQUIRED_SHIFT = [
    "contract_version", "publication_seq", "tick", "sim_time_s", "idSimulationRun",
    "run_state", "pause_reason", "speedup", "seed", "topology_version", "conditions",
    "workers_total", "workers_out", "workers_in_danger", "workers_no_route",
    "workers_unknown", "commands", "runs", "scene"]
REQUIRED_BY_KIND = {
    "working": ["passability", "hazard_state", "data_quality"],
    "zone": ["work_state", "withdrawal_state", "hazard_state", "data_quality"],
    "sensor": ["quality", "link_state", "measured_at_tick"],
    "worker": ["status", "egress_status"],
    "exit": ["state"], "incident": ["state"], "option": ["state"],
    "journal": ["last_seq", "events"],
}


def parse_date(header):
    try:
        return email.utils.parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None


def violations(mine_attributes, kinds, shift_thing, date_header="Tue, 13 Oct 2026 08:00:00 GMT"):
    """Returns the set of violated rules; an empty set means a full snapshot."""
    found = set()
    if parse_date(date_header) is None:
        found.add("no_date")
    if "_modified" not in shift_thing or "_revision" not in shift_thing:
        found.add("no_metadata")
    features = shift_thing["features"]
    if any(name not in features for name in REQUIRED_SHIFT):
        found.add("missing_field")
        return found
    if val(features, "contract_version") != 1:
        found.add("contract_version")
    if val(features, "topology_version") != mine_attributes["topology_version"]:
        found.add("topology_mismatch")
    ids = [el["thingId"] for el in scene_of(features)]
    expected = set(mine_attributes["dynamic_ids"])
    if len(ids) != len(set(ids)):
        found.add("duplicate_id")
    if expected - set(ids):
        found.add("missing_id")
    if set(ids) - expected:
        found.add("extra_id")
    for el in scene_of(features):
        f = el["features"]
        if any(val(f, k) != val(features, k) for k in ("tick", "sim_time_s", "idSimulationRun")):
            found.add("mixed_tick")
        kind = kinds.get(el["thingId"])
        required = list(REQUIRED_BY_KIND.get(kind, []))
        if kind == "worker" and val(f, "status") not in ("out", "unknown"):
            required += ["at_working", "offset_m"]
        if any(name not in f for name in required):
            found.add("missing_field")
    return found


def kinds_of(things):
    return {t["thingId"]: t["attributes"]["kind"] for t in things}


# ---------------------------------------------------------------------------
# Server process and HTTP helpers
# ---------------------------------------------------------------------------

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Response:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    def json(self):
        return json.loads(self.body.decode("utf-8"))


class Mock:
    """mock_server.py as a child process on a free port."""

    def __init__(self, scenario="normal", publication_ms=None, public_dir=None, flags=0):
        args = [sys.executable, str(SERVER), "--port", "0", "--scenario", scenario]
        if publication_ms:
            args += ["--publication-ms", str(publication_ms)]
        if public_dir:
            args += ["--public-dir", str(public_dir)]
        self.interval = (publication_ms or 1000) / 1000
        self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8", creationflags=flags)
        line = []
        reader = threading.Thread(target=lambda: line.append(self.process.stdout.readline()),
                                  daemon=True)
        reader.start()
        reader.join(20)
        first = line[0].strip() if line else ""
        if not first.startswith("LISTENING http://127.0.0.1:"):
            self.stop()
            raise RuntimeError(f"mock server did not start: {first!r}")
        self.first_line = first
        self.base = first.split(" ", 1)[1]
        self.port = int(self.base.rsplit(":", 1)[1])
        self._ids = 0

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(10)
        for pipe in (self.process.stdout, self.process.stderr):
            pipe.close()

    def request(self, method, path, data=None, headers=None, timeout=5.0):
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers=headers or {})
        try:
            with OPENER.open(req, timeout=timeout) as r:
                return Response(r.status, r.headers, r.read())
        except urllib.error.HTTPError as e:
            return Response(e.code, e.headers, e.read())

    def get(self, path, timeout=5.0):
        return self.request("GET", path, timeout=timeout)

    def post_json(self, path, body, timeout=5.0):
        return self.request("POST", path, json.dumps(body).encode("utf-8"),
                            {"Content-Type": "application/json"}, timeout)

    def scenario(self, name):
        r = self.post_json("/__mock__/scenario", {"name": name})
        assert r.status == 200, r.body
        return self

    def fault(self, mode):
        r = self.post_json("/__mock__/fault", {"mode": mode})
        assert r.status == 200, r.body

    def state(self):
        return self.get("/__mock__/state").json()

    def log(self):
        return self.get("/__mock__/log").json()["entries"]

    def shift(self):
        r = self.get(SHIFT)
        assert r.status == 200, (r.status, r.body[:200])
        return r.json()

    def features(self):
        return self.shift()["features"]

    def mine(self):
        return self.get(MINE).json()["attributes"]

    def attributes(self, ids):
        """Attributes of the given things, read in batches of 20 like the UI does."""
        things = []
        for i in range(0, len(ids), 20):
            r = self.get(f"{THINGS}?ids={','.join(ids[i:i + 20])}&fields=thingId,attributes")
            assert r.status == 200, r.body
            things += r.json()
        return things

    def new_id(self):
        self._ids += 1
        return "c-" + f"{os.getpid():08x}{id(self) & 0xffffffff:08x}{self._ids:016x}"

    def command(self, ctype, target, run="run-0005", command_id=None, timeout=5.0, **extra):
        body = {"command_id": command_id or self.new_id(), "type": ctype, "target": target,
                "run": run, **extra}
        return self.post_json(COMMAND, body, timeout), body

    def ack(self, command_id, features=None):
        """Acknowledgement records with this id in shift.commands."""
        commands = val(features or self.features(), "commands")
        return [c for c in commands if c["id"] == command_id]

    def wait(self, predicate, publications=20, what="condition"):
        """Polls until predicate() is truthy; the limit is counted in publications."""
        deadline = time.monotonic() + publications * self.interval + 3.0
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(min(0.03, self.interval / 3))
        raise AssertionError(f"timed out waiting for {what}; state: {self.state()}")

    def wait_ack(self, command_id, publications=20):
        return self.wait(lambda: self.ack(command_id), publications, f"ack of {command_id}")[0]

    def wait_state(self, name, publications=20):
        return self.wait(lambda: self.state()["state"] == name, publications, f"state {name}")


SERVERS = {}


def setUpModule():
    # real: the contract's one publication per second; fast/story: shortened for tests
    SERVERS["real"] = Mock()
    SERVERS["fast"] = Mock(publication_ms=100)
    SERVERS["story"] = Mock(publication_ms=50)


def tearDownModule():
    for server in SERVERS.values():
        server.stop()


# ---------------------------------------------------------------------------
# Fixture files
# ---------------------------------------------------------------------------

class FixtureFilesTest(unittest.TestCase):
    """The committed JSON files: reproducible, well-formed, self-consistent."""

    @classmethod
    def setUpClass(cls):
        cls.fixtures = {name: load_fixture(name) for name in SCENARIOS}

    def frames(self, with_violations=False):
        """Yields (label, fixture, state, attributes by local name, shift features)."""
        for name, fx in self.fixtures.items():
            for state_name, state in fx["states"].items():
                if not with_violations and (
                        (name in INVALID and state_name == "violated")
                        or name == "topology_mismatch"):
                    continue
                set_name = state.get("attributes", next(iter(fx["attribute_sets"])))
                attributes = {t["thingId"].split(":")[1]: t["attributes"]
                              for t in fx["attribute_sets"][set_name]}
                for i, frame in enumerate(state["frames"]):
                    yield f"{name}/{state_name}[{i}]", fx, state, attributes, frame

    def test_generator_reproduces_committed_files(self):
        self.assertEqual(sorted(p.stem for p in FIXTURES.glob("*.json")), sorted(SCENARIOS))
        with tempfile.TemporaryDirectory() as tmp:
            # another process with another hash seed must write the same bytes
            env = dict(os.environ, PYTHONHASHSEED="12345")
            done = subprocess.run([sys.executable, str(GENERATOR), "--out", tmp],
                                  capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(done.returncode, 0, done.stderr)
            for name in SCENARIOS:
                fresh = (Path(tmp) / f"{name}.json").read_bytes()
                # a checkout with core.autocrlf may have turned LF into CRLF
                committed = (FIXTURES / f"{name}.json").read_bytes().replace(b"\r\n", b"\n")
                self.assertNotIn(b"\r", fresh)
                self.assertEqual(fresh, committed, f"{name}.json differs from a fresh build")

    def test_header_marks_every_file_as_invented_test_data(self):
        for name, fx in self.fixtures.items():
            head = fx["_fixture"]
            self.assertEqual(head["scenario"], name)
            self.assertEqual(head["contract_version"], 1)
            self.assertIn("Числа придуманы для тестов и не являются измерениями стенда",
                          head["notice"])
            self.assertTrue(head["description"].strip())
            raw = (FIXTURES / f"{name}.json").read_bytes().lstrip()
            self.assertTrue(raw.startswith(b'{\n "_fixture":'), f"{name}: _fixture is not first")

    def test_no_null_and_features_have_ditto_shape(self):
        def walk(node, path):
            self.assertIsNotNone(node, f"null at {path}")
            if isinstance(node, dict):
                for key, child in node.items():
                    if key == "features":
                        for feature_name, feature in child.items():
                            self.assertEqual(list(feature), ["properties"], f"{path}/{feature_name}")
                            self.assertIn("value", feature["properties"])
                            self.assertLessEqual(set(feature["properties"]), {"value", "unit"})
                    walk(child, f"{path}/{key}")
            elif isinstance(node, list):
                for i, child in enumerate(node):
                    walk(child, f"{path}[{i}]")

        for name, fx in self.fixtures.items():
            walk(fx, name)
            for state_name, state in fx["states"].items():
                for frame in state["frames"]:
                    for feature_name, feature in frame.items():
                        self.assertEqual(list(feature), ["properties"],
                                         f"{name}/{state_name}/{feature_name}")

    def test_manifest_and_base_mine(self):
        for name, fx in self.fixtures.items():
            for set_name, things in fx["attribute_sets"].items():
                mine = things[0]["attributes"]
                ids = [t["thingId"] for t in things]
                self.assertEqual(mine["manifest"], ids)
                self.assertLessEqual(len(ids), 80)
                self.assertEqual(len(ids), len(set(ids)))
                kinds = kinds_of(things)
                self.assertTrue(set(mine["dynamic_ids"]) < set(ids))
                self.assertFalse({kinds[i] for i in mine["dynamic_ids"]} & {"mine", "shift", "level"})
                self.assertNotIn("run", kinds.values())
                self.assertEqual(mine["contract_version"], 1)
                self.assertTrue(mine["synthetic"])
                self.assertEqual(mine["topology_version"], set_name)
                self.assertEqual({p["id"] for p in mine["presets"]}, {"p-detour", "p-no-path"})
                for preset in mine["presets"]:
                    self.assertTrue({"id", "label", "expect", "schedule"} <= set(preset))
                    for item in preset["schedule"]:
                        self.assertEqual(set(item), {"at_sim_s", "type", "target"})
                counts = {}
                for kind in kinds.values():
                    counts[kind] = counts.get(kind, 0) + 1
                self.assertEqual(mine["counts"], counts)
                for t in things:
                    self.assertTrue(t["thingId"].startswith(NS + ":"))
                    self.assertTrue(t["attributes"]["label"])
        mine = self.fixtures["normal"]["attribute_sets"]["t1"]
        counts = self.fixtures["normal"]["attribute_sets"]["t1"][0]["attributes"]["counts"]
        self.assertEqual(counts, {"mine": 1, "shift": 1, "level": 3, "working": 36, "zone": 4,
                                  "sensor": 10, "worker": 14, "exit": 3, "incident": 1,
                                  "option": 3, "journal": 1})
        by_id = {t["thingId"].split(":")[1]: t["attributes"] for t in mine}
        self.assertEqual([by_id[f"level-{d}"]["elevation_m"] for d in (260, 320, 380)],
                         [-260, -320, -380])
        self.assertEqual([by_id[z]["label"] for z in ("zone-a", "zone-b", "zone-c", "zone-d")],
                         ["Участок А", "Участок Б", "Участок В", "Участок Г"])
        self.assertEqual(by_id["sens-ext-05"]["label"], "Э-05")
        self.assertEqual((by_id["sens-ext-05"]["working"], by_id["sens-ext-05"]["zone"]),
                         ("w-21", "zone-c"))
        self.assertEqual(by_id["zone-c"]["sensors"], ["sens-ext-05"])
        self.assertEqual({by_id[f"worker-{i:02d}"]["label"] for i in range(1, 15)},
                         {f"Р-{i:02d}" for i in range(1, 15)})
        self.assertEqual({by_id[e]["exit_kind"] for e in ("exit-shaft", "exit-ramp", "exit-raise")},
                         {"shaft", "ramp", "raise"})
        self.assertTrue(any("zone" not in a for a in by_id.values() if a["kind"] == "working"))

    def test_working_length_equals_polyline_length(self):
        for name, fx in self.fixtures.items():
            for set_name, things in fx["attribute_sets"].items():
                nodes = things[0]["attributes"]["nodes"]
                levels = {t["thingId"].split(":")[1]: t["attributes"]["elevation_m"]
                          for t in things if t["attributes"]["kind"] == "level"}
                for node_id, node in nodes.items():
                    self.assertEqual(node["z"], levels[node["level"]], node_id)
                    self.assertIn(node["node_kind"], ("junction", "dead_end", "exit"))
                for t in things:
                    a = t["attributes"]
                    if a["kind"] != "working":
                        continue
                    points = ([[nodes[a["from"]][k] for k in "xyz"]] + a["points"]
                              + [[nodes[a["to"]][k] for k in "xyz"]])
                    length = sum(math.dist(p, q) for p, q in zip(points, points[1:]))
                    self.assertLessEqual(abs(length - a["length_m"]), 1.0,
                                         f"{name}/{set_name}/{t['thingId']}")
                # the plan is not a single line and has the size of a small level
                for level in levels:
                    xs = [n["x"] for n in nodes.values() if n["level"] == level]
                    ys = [n["y"] for n in nodes.values() if n["level"] == level]
                    self.assertGreaterEqual(max(xs) - min(xs), 450)
                    self.assertGreaterEqual(max(ys) - min(ys), 150)

    def check_worker_route(self, label, attributes, features, f):
        status, egress = val(f, "status"), val(f, "egress_status")
        route_features = ("route", "route_next_node", "egress_exit", "egress_length_m",
                          "egress_eta_s", "egress_detour_m", "egress_detour_s")
        if status == "out":
            self.assertIn(val(f, "at_exit"), attributes, label)
            self.assertFalse({"at_working", "offset_m"} & set(f), label)
        if egress is None:
            return      # invalid_missing_field removes egress_status on purpose
        if status == "out" or egress != "ok":
            self.assertFalse(set(route_features) & set(f), f"{label}: route without egress")
            if egress == "none":
                self.assertIn(val(f, "egress_reason"), ("no_open_path", "current_working_closed"))
            return
        route = val(f, "route")
        names = [seg["working"] if isinstance(seg, dict) else seg for seg in route]
        at, offset = val(f, "at_working"), val(f, "offset_m")
        self.assertEqual(names[0], at, label)
        first = attributes[at]
        self.assertTrue(0 <= offset <= first["length_m"], label)
        node = val(f, "route_next_node")
        self.assertIn(node, (first["from"], first["to"]), label)
        remaining = offset if node == first["from"] else first["length_m"] - offset
        if isinstance(route[0], dict):
            self.assertEqual(route[0]["to"], node, label)
        for i, working in enumerate(names):
            self.assertEqual(val(element(features, working), "passability"), "open",
                             f"{label}: the route uses closed {working}")
            if i == 0:
                continue
            w = attributes[working]
            self.assertIn(node, (w["from"], w["to"]), f"{label}: {working} does not continue")
            following = w["to"] if node == w["from"] else w["from"]
            if isinstance(route[i], dict):
                self.assertEqual((route[i]["from"], route[i]["to"]), (node, following), label)
            node, remaining = following, remaining + w["length_m"]
        self.assertEqual(node, attributes[val(f, "egress_exit")]["node"], label)
        length = val(f, "egress_length_m")
        self.assertLessEqual(abs(length - remaining), 1.0, f"{label}: {length} vs {remaining}")
        self.assertEqual(val(f, "egress_eta_s"), int(length / SPEED_M_S + 0.5), label)
        self.assertEqual(f["egress_length_m"]["properties"].get("unit"), "m")
        self.assertEqual(f["egress_eta_s"]["properties"].get("unit"), "s")

    def test_routes_are_consistent_in_every_frame(self):
        checked = 0
        for label, fx, state, attributes, frame in self.frames(with_violations=True):
            for el in scene_of(frame):
                local = el["thingId"].split(":")[1]
                if attributes.get(local, {}).get("kind") == "worker":
                    self.check_worker_route(f"{label} {local}", attributes, frame, el["features"])
                    checked += 1
        self.assertGreater(checked, 3000)

    def test_frames_are_full_snapshots_with_consistent_counters(self):
        for label, fx, state, attributes, frame in self.frames():
            set_name = state.get("attributes", next(iter(fx["attribute_sets"])))
            things = fx["attribute_sets"][set_name]
            thing = {"features": frame, "_modified": "x", "_revision": 1}
            self.assertEqual(violations(things[0]["attributes"], kinds_of(things), thing), set(),
                             label)
            workers = [el["features"] for el in scene_of(frame)
                       if attributes[el["thingId"].split(":")[1]]["kind"] == "worker"]
            out = [w for w in workers if val(w, "status") == "out"]
            self.assertEqual(val(frame, "workers_total"), len(workers), label)
            self.assertEqual(val(frame, "workers_out"), len(out), label)
            self.assertEqual(val(frame, "workers_no_route"),
                             sum(1 for w in workers if val(w, "egress_status") == "none"), label)
            self.assertEqual(val(frame, "all_out"), len(out) == len(workers), label)
            exits = sum(val(el["features"], "workers_out") for el in scene_of(frame)
                        if attributes[el["thingId"].split(":")[1]]["kind"] == "exit")
            self.assertEqual(exits, len(out), label)
            self.assertIn(val(frame, "run_state"), ("running", "paused", "resetting"))
            self.assertIn(val(frame, "pause_reason"), ("none", "decision"))
            self.assertLessEqual(len(val(frame, "commands")), 32)
            self.assertLessEqual(len(val(element(frame, "journal"), "events")), 50)
            if state["clock"] == "hold" and val(frame, "run_state") == "running":
                self.fail(f"{label}: a running model with a held clock")

    def test_intended_violations_and_nothing_else(self):
        for name, code in INVALID.items():
            fx = self.fixtures[name]
            things = fx["attribute_sets"]["t1"]
            state = fx["states"]["violated"]
            thing = {"features": state["frames"][0]}
            if state.get("metadata", True):
                thing.update(_modified="x", _revision=1)
            self.assertEqual(violations(things[0]["attributes"], kinds_of(things), thing), {code},
                             name)
            self.assertEqual((fx["states"]["initial"]["publications"],
                              fx["states"]["initial"]["next"]), (3, "violated"))
        fx = self.fixtures["topology_mismatch"]
        things = fx["attribute_sets"]["t1"]
        thing = {"features": fx["states"]["initial"]["frames"][0], "_modified": "x", "_revision": 1}
        self.assertEqual(violations(things[0]["attributes"], kinds_of(things), thing),
                         {"topology_mismatch"})
        fx = self.fixtures["topology_change"]
        t1 = {t["thingId"]: t["attributes"] for t in fx["attribute_sets"]["t1"]}
        t2 = {t["thingId"]: t["attributes"] for t in fx["attribute_sets"]["t2"]}
        self.assertEqual(set(t2) - set(t1), {tid("w-37")})
        self.assertNotEqual(t1[tid("w-19")]["length_m"], t2[tid("w-19")]["length_m"])
        self.assertIn(tid("w-37"), t2[tid("mine")]["dynamic_ids"])
        self.assertEqual(fx["states"]["t2"]["attributes"], "t2")
        self.assertEqual(self.fixtures["empty"]["states"], {})

    def test_states_and_rules_refer_to_each_other_correctly(self):
        for name, fx in self.fixtures.items():
            states = fx["states"]
            if not states:
                continue
            rules = [r for st in states.values() for r in st.get("rules", [])]
            targets = {r["goto"] for r in rules if "goto" in r}
            targets |= {st["next"] for st in states.values() if "next" in st}
            self.assertLessEqual(targets, set(states), name)
            self.assertEqual(set(states) - targets, {fx["start"]}, f"{name}: unreachable state")
            raw = (FIXTURES / f"{name}.json").read_text(encoding="utf-8")
            placeholders = {part.split('"')[0] for part in raw.split('"@')[1:]}
            self.assertLessEqual(placeholders, {r["bind"] for r in rules if "bind" in r}, name)
            for state_name, st in states.items():
                self.assertIn(st["clock"], ("run", "hold"))
                ticks = [val(f, "tick") for f in st["frames"]]
                step = 10 if st["clock"] == "run" else 0
                self.assertEqual(ticks, [ticks[0] + step * i for i in range(len(ticks))],
                                 f"{name}/{state_name}")
                self.assertEqual(len({val(f, "idSimulationRun") for f in st["frames"]}), 1)
                for r in st.get("rules", []):
                    self.assertTrue(("ack" in r) != bool(r.get("no_ack")), f"{name}/{state_name}")
                    self.assertLessEqual(set(r), {"when", "ack", "no_ack", "ack_delay", "goto",
                                                  "bind", "transport", "key"})

    def test_story_numbers_of_the_passage_closure(self):
        normal = self.fixtures["normal"]["states"]["initial"]["frames"][0]
        w3 = element(normal, "worker-03")
        self.assertEqual((val(w3, "egress_length_m"), val(w3, "egress_eta_s"),
                          val(w3, "egress_exit")), (412, 330, "exit-shaft"))
        self.assertIn("w-12", val(w3, "route"))
        self.assertEqual(val(normal, "conditions"), [])
        self.assertEqual(val(element(normal, "incident"), "state"), "none")
        hazards = [val(element(normal, z), "hazard_state")
                   for z in ("zone-a", "zone-b", "zone-c", "zone-d")]
        self.assertEqual(sorted(hazards), ["attention", "normal", "normal", "normal"])
        for option in ("option-observe", "option-stop-withdraw", "option-withdraw-all"):
            self.assertEqual(val(element(normal, option), "state"), "inactive")
        for i in range(1, 15):
            self.assertEqual(val(element(normal, f"worker-{i:02d}"), "egress_status"), "ok")
        self.assertEqual(val(element(normal, "w-12"), "data_quality"), "none")

        detour = self.fixtures["detour"]["states"]
        decision = detour["decision"]["frames"][0]
        w3 = element(decision, "worker-03")
        self.assertEqual((val(w3, "egress_length_m"), val(w3, "egress_detour_m"),
                          val(w3, "egress_eta_s"), val(w3, "egress_exit")),
                         (655, 243, 524, "exit-ramp"))
        self.assertNotIn("w-12", val(w3, "route"))
        self.assertEqual((val(element(decision, "w-12"), "passability"),
                          val(element(decision, "w-12"), "closed_by")), ("closed", "scenario"))
        self.assertEqual((val(decision, "run_state"), val(decision, "pause_reason")),
                         ("paused", "decision"))
        incident = element(decision, "incident")
        self.assertEqual((val(incident, "state"), val(incident, "trigger")),
                         ("active", "passage_closed"))
        options = [element(decision, o) for o in
                   ("option-observe", "option-stop-withdraw", "option-withdraw-all")]
        self.assertEqual({val(o, "state") for o in options}, {"offered"})
        self.assertEqual(len({val(o, "decision_id") for o in options}), 1)
        self.assertEqual(len({val(o, "comparison_key") for o in options}), 1)
        for o in options:
            for suffix in ("in_danger", "danger_exposure_person_s", "unknown_exposure_person_s",
                           "no_route", "out", "all_out", "downtime_s"):
                self.assertIn("forecast_" + suffix, o)
            self.assertEqual(val(o, "forecast_quality"), "full")
            self.assertEqual("forecast_last_out_s" in o, val(o, "forecast_all_out"))
        # every moving worker advances 12.5 m per publication, and time by 10 s
        for name in ("sw_exec", "wa_exec"):
            frames = detour[name]["frames"]
            for before, after in zip(frames, frames[1:]):
                self.assertEqual(val(after, "tick") - val(before, "tick"), 10)
                for i in range(1, 15):
                    a = element(before, f"worker-{i:02d}")
                    b = element(after, f"worker-{i:02d}")
                    if val(a, "status") == "moving_to_exit" and val(b, "status") != "out":
                        self.assertEqual(val(a, "egress_length_m") - val(b, "egress_length_m"),
                                         STEP_M)
                    if val(b, "status") == "out" and val(a, "status") != "out":
                        self.assertLessEqual(val(a, "egress_length_m"), STEP_M)
        self.assertEqual(len(detour["sw_exec"]["frames"]), 53)   # 655 m at 12.5 m per publication

    def test_archive_runs(self):
        archive = {t["thingId"].split(":")[1]: {k: v["properties"]["value"]
                                                 for k, v in t["features"].items()}
                   for t in self.fixtures["normal"]["archive"]}
        frame = self.fixtures["normal"]["states"]["initial"]["frames"][0]
        self.assertEqual(val(frame, "runs"), ["run-0001", "run-0002", "run-0003", "run-0004"])
        self.assertEqual(list(archive), val(frame, "runs"))
        r1, r2, r3, r4 = (archive[f"run-000{i}"] for i in range(1, 5))
        self.assertEqual(r1["comparison_key"], r2["comparison_key"])
        self.assertNotEqual(r1["executed_option"], r2["executed_option"])
        self.assertEqual({r1["state"], r2["state"], r4["state"]}, {"finished"})
        by_all_out = {r["all_out"]: r for r in (r1, r2)}
        self.assertIn("last_out_s", by_all_out[True])
        self.assertNotIn("last_out_s", by_all_out[False])
        self.assertEqual(r3["completion_reason"], "reset")
        self.assertNotIn("last_out_s", r3)
        self.assertNotEqual(r4["comparison_key"], r1["comparison_key"])
        self.assertIs(r4["comparable"], False)
        self.assertTrue(r4["incomparable_reason"])
        for run in archive.values():
            self.assertEqual("last_out_s" in run, run["all_out"])
            self.assertEqual("forecast_last_out_s" in run, run["forecast_all_out"])

    def test_journal_seq_is_monotonic_with_one_scenario_having_a_gap(self):
        with_gap = set()
        codes = set()
        for label, fx, state, attributes, frame in self.frames(with_violations=True):
            journal = element(frame, "journal")
            seqs = [e["seq"] for e in val(journal, "events")]
            codes.update(e["code"] for e in val(journal, "events"))
            self.assertEqual(seqs, sorted(set(seqs)), label)
            self.assertEqual(val(journal, "last_seq"), seqs[-1], label)
            if any(b - a != 1 for a, b in zip(seqs, seqs[1:])):
                with_gap.add(label.split("/")[0])
        self.assertEqual(with_gap, {"sensor_lost_after_danger"})
        self.assertTrue({"condition.set", "condition.cancelled", "command.applied",
                         "command.rejected", "hazard.changed", "worker.out",
                         "ventilation.changed"} <= codes)

    def test_static_scenarios_show_their_condition(self):
        f = self.fixtures["sensor_lost_after_danger"]["states"]["initial"]["frames"][0]
        zone, sensor = element(f, "zone-c"), element(f, "sens-ext-05")
        self.assertEqual(
            [val(zone, k) for k in ("hazard_state", "data_quality", "last_known_hazard_state",
                                    "routing_restriction")],
            ["unknown", "lost", "danger", "blocked"])
        self.assertLess(val(zone, "last_known_hazard_tick"), val(f, "tick"))
        self.assertEqual((val(sensor, "quality"), val(sensor, "link_state")), ("lost", "offline"))
        self.assertGreaterEqual(val(f, "tick") - val(sensor, "measured_at_tick"), 300)
        incident = element(f, "incident")
        self.assertNotEqual(val(incident, "state"), "none")
        self.assertEqual({c["trigger"] for c in val(incident, "causes")}, {"hazard", "data_lost"})
        for w in ("worker-07", "worker-08"):
            self.assertEqual(val(element(f, w), "location_hazard"), "unknown")
        self.assertEqual(val(f, "workers_unknown"), 2)
        self.assertEqual(val(f, "workers_in_danger"), 0)

        f = self.fixtures["withdrawal_incomplete"]["states"]["initial"]["frames"][0]
        self.assertIs(val(f, "all_out"), False)
        self.assertEqual(val(element(f, "zone-c"), "withdrawal_state"), "incomplete")
        done = [element(f, o) for o in ("option-observe", "option-stop-withdraw",
                                        "option-withdraw-all")]
        done = [o for o in done if val(o, "state") == "done"]
        self.assertEqual(len(done), 1)
        self.assertIs(val(done[0], "actual_all_out"), False)
        self.assertNotIn("actual_last_out_s", done[0])
        self.assertNotIn("forecast_last_out_s", done[0])
        self.assertEqual((val(done[0], "actual_out"), val(done[0], "actual_no_route")), (12, 2))

        f = self.fixtures["no_forecast"]["states"]["initial"]["frames"][0]
        self.assertEqual((val(f, "run_state"), val(element(f, "incident"), "state")),
                         ("paused", "active"))
        for o in ("option-observe", "option-stop-withdraw", "option-withdraw-all"):
            option = element(f, o)
            self.assertEqual(val(option, "state"), "offered")
            self.assertFalse([k for k in option if k.startswith("forecast_")])
            self.assertTrue(val(option, "decision_id"))
        f = self.fixtures["partial_forecast"]["states"]["initial"]["frames"][0]
        for o in ("option-observe", "option-stop-withdraw", "option-withdraw-all"):
            self.assertEqual(val(element(f, o), "forecast_quality"), "partial")
            self.assertIn("forecast_out", element(f, o))

        f = self.fixtures["route_segments"]["states"]["initial"]["frames"][0]
        route = val(element(f, "worker-03"), "route")
        self.assertEqual(route[0], {"working": "w-14", "from": "n-14", "to": "n-15"})
        self.assertEqual(val(element(f, "worker-03"), "egress_length_m"), 655)

        fx = self.fixtures["unknown_enum"]
        f = fx["states"]["initial"]["frames"][0]
        self.assertEqual(val(element(f, "zone-a"), "hazard_state"), "elevated")
        self.assertEqual(val(element(f, "worker-09"), "status"), "resting")
        kinds = {t["thingId"]: t["attributes"].get("option_kind")
                 for t in fx["attribute_sets"]["t1"]}
        self.assertEqual(kinds[tid("option-observe")], "shelter")

        f = self.fixtures["paused_heartbeat"]["states"]["initial"]
        self.assertEqual(f["clock"], "hold")
        self.assertEqual((val(f["frames"][0], "run_state"), val(f["frames"][0], "pause_reason")),
                         ("paused", "decision"))

    # --- danger_zone: a zone in danger on fresh data, a stale sensor elsewhere ---

    OPTION_IDS = ("option-observe", "option-stop-withdraw", "option-withdraw-all")

    def danger_zone(self):
        fx = self.fixtures["danger_zone"]
        attributes = {t["thingId"].split(":")[1]: t["attributes"]
                      for t in fx["attribute_sets"]["t1"]}
        return fx, fx["states"], attributes

    def test_danger_zone_is_covered_by_the_per_frame_checks(self):
        # the generic route / counter / snapshot checks iterate over every frame of every
        # scenario; make sure the new scenario's frames are among them and pass the route check
        fx, states, _ = self.danger_zone()
        labels = []
        checked = 0
        for label, fx, state, attributes, frame in self.frames():
            if not label.startswith("danger_zone/"):
                continue
            labels.append(label)
            for el in scene_of(frame):
                local = el["thingId"].split(":")[1]
                if attributes[local]["kind"] == "worker":
                    self.check_worker_route(f"{label} {local}", attributes, frame, el["features"])
                    checked += 1
        self.assertEqual(len(labels), sum(len(s["frames"]) for s in states.values()))
        self.assertGreaterEqual(len(labels), 100)
        for state in ("initial", "decision", "observe_exec", "sw_exec", "wa_exec", "sw_done"):
            self.assertTrue(any(l.startswith(f"danger_zone/{state}[") for l in labels), state)
        self.assertEqual(checked, 14 * len(labels))

    def test_danger_zone_prelude_climbs_from_attention_to_the_decision_point(self):
        fx, states, attributes = self.danger_zone()
        thresholds = attributes["mine"]["thresholds"]
        initial, decision = states["initial"], states["decision"]
        self.assertEqual((initial["clock"], initial["publications"], initial["next"]),
                         ("run", 6, "decision"))
        self.assertEqual(decision["clock"], "hold")
        frames = initial["frames"]
        self.assertEqual(len(frames), 6)
        self.assertEqual([val(f, "tick") for f in frames], list(range(1200, 1260, 10)))
        rates, indexes = [], []
        for f in frames:
            self.assertEqual((val(f, "run_state"), val(f, "workers_in_danger"),
                              val(element(f, "incident"), "state")), ("running", 0, "none"))
            zone = element(f, "zone-d")
            self.assertEqual((val(zone, "hazard_state"), val(zone, "data_quality"),
                              val(zone, "routing_restriction")), ("attention", "fresh", "allowed"))
            rate = val(element(f, "sens-ext-04"), "rate")
            self.assertEqual(val(zone, "reason_value"), rate)
            self.assertGreaterEqual(rate, thresholds["rate"]["attention"])
            self.assertLess(rate, thresholds["rate"]["danger"])
            self.assertLess(val(zone, "instability_index"), thresholds["index"]["danger"])
            rates.append(rate)
            indexes.append(val(zone, "instability_index"))
            # the sensor that will go stale is already silent, but not yet too old
            quiet = element(f, "sens-ext-05")
            self.assertEqual((val(quiet, "quality"), val(quiet, "link_state")),
                             ("fresh", "online"))
            self.assertLessEqual(val(f, "tick") - val(quiet, "measured_at_tick"),
                                 attributes["sens-ext-05"]["stale_after_s"])
            self.assertEqual(val(element(f, "zone-c"), "hazard_state"), "normal")
        self.assertEqual(rates, sorted(set(rates)))        # strictly climbing
        self.assertEqual(indexes, sorted(set(indexes)))
        last = decision["frames"][0]
        self.assertEqual(val(last, "tick"), val(frames[-1], "tick") + 10)
        self.assertGreater(val(element(last, "sens-ext-04"), "rate"), rates[-1])

    def test_danger_zone_hazard_numbers_follow_the_thresholds(self):
        fx, states, attributes = self.danger_zone()
        thresholds = attributes["mine"]["thresholds"]
        f = states["decision"]["frames"][0]
        things = fx["attribute_sets"]["t1"]
        self.assertEqual(violations(things[0]["attributes"], kinds_of(things),
                                    {"features": f, "_modified": "x", "_revision": 1}), set())
        zone = element(f, "zone-d")
        self.assertEqual([val(zone, k) for k in ("hazard_state", "data_quality", "reason_code",
                                                  "routing_restriction", "reason_sensor")],
                         ["danger", "fresh", "rate_above_danger", "blocked", "sens-ext-04"])
        self.assertEqual(val(zone, "index_at_tick"), val(f, "tick"))
        # the reason names the sensor, its rate and the danger threshold of the mine
        sensor = element(f, val(zone, "reason_sensor"))
        self.assertEqual(attributes[val(zone, "reason_sensor")]["zone"], "zone-d")
        self.assertEqual(val(zone, "reason_value"), val(sensor, "rate"))
        self.assertEqual((val(zone, "reason_threshold"), val(zone, "reason_unit")),
                         (thresholds["rate"]["danger"], thresholds["rate"]["unit"]))
        self.assertGreater(val(zone, "reason_value"), val(zone, "reason_threshold"))
        self.assertGreater(val(zone, "instability_index"), thresholds["index"]["danger"])
        self.assertEqual(zone["instability_index"]["properties"]["unit"], "1")
        # every sensor of the zone reads above the danger threshold and is fresh
        sensors = attributes["zone-d"]["sensors"]
        self.assertEqual(sorted(sensors), ["sens-conv-03", "sens-ext-04"])
        for sid in sensors:
            s = element(f, sid)
            self.assertGreater(val(s, "rate"), thresholds["rate"]["danger"], sid)
            self.assertEqual((val(s, "quality"), val(s, "link_state"), val(s, "measured_at_tick")),
                             ("fresh", "online", val(f, "tick")), sid)
        self.assertNotIn("last_known_hazard_state", zone)
        # the zone's workings carry the zone's state
        for wid in attributes["zone-d"]["workings"]:
            w = element(f, wid)
            self.assertEqual((val(w, "hazard_state"), val(w, "data_quality"),
                              val(w, "routing_restriction")), ("danger", "fresh", "blocked"), wid)
        # the model stopped to ask: the incident has the hazard cause at the transition
        self.assertEqual((val(f, "run_state"), val(f, "pause_reason")), ("paused", "decision"))
        incident = element(f, "incident")
        self.assertEqual([val(incident, k) for k in ("state", "trigger", "zone", "opened_at_tick")],
                         ["active", "hazard", "zone-d", val(f, "tick")])
        self.assertIn({"trigger": "hazard", "subject": "zone-d", "tick": val(f, "tick")},
                      val(incident, "causes"))
        events = [(e["code"], e["subject"], e.get("arg"), e["tick"])
                  for e in val(element(f, "journal"), "events")]
        self.assertIn(("hazard.changed", "zone-d", "danger", val(f, "tick")), events)
        # the zone was in attention from the start and the journal says so
        self.assertIn(("hazard.changed", "zone-d", "attention", 0), events)

    def test_danger_zone_workers_inside_are_in_danger(self):
        fx, states, attributes = self.danger_zone()
        f = states["decision"]["frames"][0]
        inside = set(attributes["zone-d"]["workings"])
        in_zone = [i for i in range(1, 15)
                   if val(element(f, f"worker-{i:02d}"), "at_working") in inside]
        self.assertEqual(in_zone, [11, 12, 13])
        for i in range(1, 15):
            w = element(f, f"worker-{i:02d}")
            if i in in_zone:
                self.assertEqual(val(w, "location_hazard"), "danger", f"worker-{i:02d}")
            else:
                self.assertNotEqual(val(w, "location_hazard"), "danger", f"worker-{i:02d}")
        self.assertEqual(val(f, "workers_in_danger"), len(in_zone))
        self.assertEqual(val(element(f, "zone-d"), "workers_count"), len(in_zone))
        self.assertEqual(sum(1 for i in range(1, 15)
                             if val(element(f, f"worker-{i:02d}"), "location_hazard") == "danger"),
                         val(f, "workers_in_danger"))
        # leaving the zone is a published route that crosses it; entry is what is forbidden
        for i in in_zone:
            w = element(f, f"worker-{i:02d}")
            self.assertEqual((val(w, "egress_status"), val(w, "egress_crosses"),
                              val(w, "status")), ("ok", "danger", "working"))
        # worker-14 belongs to zone D but stands in an unmonitored passage
        w14 = element(f, "worker-14")
        self.assertEqual(attributes["worker-14"]["home_zone"], "zone-d")
        self.assertEqual((val(w14, "location_hazard"),
                          val(element(f, val(w14, "at_working")), "data_quality")),
                         ("unknown", "none"))
        self.assertEqual(val(f, "workers_no_route"), 0)

    def test_danger_zone_has_a_stale_sensor_and_an_unknown_zone(self):
        fx, states, attributes = self.danger_zone()
        f = states["decision"]["frames"][0]
        before = states["initial"]["frames"][-1]
        sensor = element(f, "sens-ext-05")
        self.assertEqual((val(sensor, "quality"), val(sensor, "link_state")), ("stale", "online"))
        age = val(f, "tick") - val(sensor, "measured_at_tick")
        self.assertGreater(age, attributes["sens-ext-05"]["stale_after_s"])
        self.assertLess(age, attributes["sens-ext-05"]["lost_after_s"])
        self.assertEqual(val(sensor, "measured_at_sim_s"), val(sensor, "measured_at_tick"))
        # another zone than the one in danger, and the only sensor of its zone
        self.assertEqual(attributes["sens-ext-05"]["zone"], "zone-c")
        self.assertEqual(attributes["zone-c"]["sensors"], ["sens-ext-05"])
        zone = element(f, "zone-c")
        self.assertEqual([val(zone, k) for k in ("hazard_state", "data_quality", "reason_code",
                                                  "reason_sensor", "last_known_hazard_state")],
                         ["unknown", "stale", "sensor_stale", "sens-ext-05", "normal"])
        # the last known value is the previous fresh one, not an invention
        fresh = element(before, "zone-c")
        self.assertEqual((val(fresh, "hazard_state"), val(fresh, "data_quality")),
                         ("normal", "fresh"))
        self.assertEqual(val(zone, "last_known_hazard_tick"), val(before, "tick"))
        self.assertLess(val(zone, "last_known_hazard_tick"), val(f, "tick"))
        self.assertEqual(val(zone, "routing_restriction"), "blocked")
        self.assertNotIn("reason_value", zone)
        for wid in attributes["zone-c"]["workings"]:
            self.assertEqual(val(element(f, wid), "hazard_state"), "unknown", wid)
        # people there are unknown, not in danger and not fine
        for w in ("worker-07", "worker-08"):
            self.assertEqual(val(element(f, w), "location_hazard"), "unknown")
        self.assertEqual(val(f, "workers_unknown"), 2)
        self.assertEqual(val(f, "workers_in_danger"), 3)
        incident = element(f, "incident")
        self.assertEqual({c["trigger"] for c in val(incident, "causes")}, {"hazard", "data_lost"})
        self.assertEqual(val(incident, "trigger"), "hazard")
        events = [(e["code"], e["subject"], e.get("arg"))
                  for e in val(element(f, "journal"), "events") if e["tick"] == val(f, "tick")]
        self.assertIn(("quality.changed", "sens-ext-05", "stale"), events)
        self.assertIn(("hazard.changed", "zone-c", "unknown"), events)

    def test_danger_zone_forecasts_are_consistent_and_differ(self):
        fx, states, attributes = self.danger_zone()
        f = states["decision"]["frames"][0]
        options = {o: element(f, o) for o in self.OPTION_IDS}
        self.assertEqual({val(o, "state") for o in options.values()}, {"offered"})
        self.assertEqual(len({val(o, "decision_id") for o in options.values()}), 1)
        self.assertEqual(len({val(o, "comparison_key") for o in options.values()}), 1)
        self.assertTrue(val(options["option-observe"], "decision_id"))
        for o in options.values():
            self.assertEqual((val(o, "forecast_tick"), val(o, "forecast_horizon_s"),
                              val(o, "forecast_quality")), (val(f, "tick"), 900, "full"))
            for suffix in ("in_danger", "danger_exposure_person_s", "unknown_exposure_person_s",
                           "no_route", "out", "all_out", "downtime_s"):
                self.assertIn("forecast_" + suffix, o)
            self.assertEqual("forecast_last_out_s" in o, val(o, "forecast_all_out"))
        observe, sw, wa = (options[o] for o in self.OPTION_IDS)
        group = [f"worker-{i:02d}" for i in range(1, 15)]
        # publications a worker needs: route length at 12.5 m per publication, rounded up
        walk = {w: math.ceil(val(element(f, w), "egress_length_m") / STEP_M) for w in group}
        in_danger = [w for w in group if val(element(f, w), "location_hazard") == "danger"]
        self.assertEqual(len(in_danger), 3)
        # observe: nobody moves, everybody who is in danger stays for the whole horizon
        self.assertEqual(val(observe, "scope"), [])
        self.assertEqual((val(observe, "forecast_in_danger"), val(observe, "forecast_out"),
                          val(observe, "forecast_all_out")), (len(in_danger), 0, False))
        self.assertNotIn("forecast_last_out_s", observe)
        self.assertEqual(val(observe, "forecast_danger_exposure_person_s"), len(in_danger) * 900)
        self.assertEqual(val(observe, "forecast_unknown_exposure_person_s"), 2 * 900)
        self.assertEqual(val(observe, "forecast_downtime_s"), 0)
        # stop and withdraw the zone: its home workers walk out, the others of the group do not
        home = [w for w in group if attributes[w]["home_zone"] == "zone-d"]
        self.assertEqual(val(sw, "scope"), ["zone-d"])
        self.assertEqual((val(sw, "forecast_in_danger"), val(sw, "forecast_out"),
                          val(sw, "forecast_no_route"), val(sw, "forecast_all_out")),
                         (0, len(home), 0, False))
        self.assertNotIn("forecast_last_out_s", sw)
        sw_steps = max(walk[w] for w in home)
        self.assertEqual(val(sw, "forecast_downtime_s"), 10 * sw_steps)    # one zone stopped
        # exposure from the geometry: a worker stays in danger while his walk is inside the zone
        inside = set(attributes["zone-d"]["workings"])
        steps_in_danger = 0
        for w in in_danger:
            e = element(f, w)
            route = val(e, "route")
            first = attributes[route[0]]
            offset = val(e, "offset_m")
            distance = offset if val(e, "route_next_node") == first["from"] \
                else first["length_m"] - offset
            for working in route[1:]:
                if working not in inside:
                    break
                distance += attributes[working]["length_m"]
            steps_in_danger += math.ceil(distance / STEP_M) - 1
        self.assertEqual(val(sw, "forecast_danger_exposure_person_s"), 10 * steps_in_danger)
        self.assertEqual(val(wa, "forecast_danger_exposure_person_s"), 10 * steps_in_danger)
        self.assertGreater(val(observe, "forecast_danger_exposure_person_s"),
                           val(sw, "forecast_danger_exposure_person_s"))
        # withdraw all: the whole common group is out, the time is the longest walk
        self.assertEqual(val(wa, "scope"), ["zone-a", "zone-b", "zone-c", "zone-d"])
        self.assertEqual((val(wa, "forecast_out"), val(wa, "forecast_all_out"),
                          val(wa, "forecast_in_danger"), val(wa, "forecast_no_route")),
                         (14, True, 0, 0))
        self.assertEqual(val(wa, "forecast_last_out_s"), 10 * max(walk.values()))
        self.assertLessEqual(val(wa, "forecast_last_out_s"), 900)
        self.assertGreater(val(wa, "forecast_last_out_s"), 10 * sw_steps)
        self.assertEqual(wa["forecast_last_out_s"]["properties"]["unit"], "s")
        self.assertGreater(val(wa, "forecast_downtime_s"), val(sw, "forecast_downtime_s"))
        for suffix in ("danger_exposure_person_s", "unknown_exposure_person_s"):
            self.assertEqual(wa["forecast_" + suffix]["properties"]["unit"], "person*s")

    def test_danger_zone_walk_out_frames(self):
        fx, states, attributes = self.danger_zone()
        decision = states["decision"]["frames"][0]
        # the three option states are reached from the decision point only
        rules = states["decision"]["rules"]
        decision_id = val(element(decision, "option-observe"), "decision_id")
        goto = {r["when"]["target"]: r["goto"] for r in rules if "goto" in r}
        self.assertEqual(goto, {"option-observe": "observe_exec",
                                "option-stop-withdraw": "sw_exec",
                                "option-withdraw-all": "wa_exec"})
        for r in rules:
            if "goto" in r:
                self.assertEqual((r["when"]["type"], r["when"]["decision_id"], r["ack"]["status"]),
                                 ("action.execute_option", decision_id, "applied"))
            else:
                self.assertEqual((r["when"]["type"], r["ack"]["reason"]),
                                 ("action.execute_option", "stale_decision"))
        for name in ("sw_exec", "wa_exec"):
            frames = states[name]["frames"]
            self.assertEqual(val(frames[0], "tick"), val(decision, "tick"))
            self.assertEqual((val(frames[0], "run_state"), val(frames[0], "pause_reason")),
                             ("running", "none"))
            for before, after in zip(frames, frames[1:]):
                self.assertEqual(val(after, "tick") - val(before, "tick"), 10)
                for i in range(1, 15):
                    a = element(before, f"worker-{i:02d}")
                    b = element(after, f"worker-{i:02d}")
                    label = f"{name} worker-{i:02d} tick {val(after, 'tick')}"
                    if val(a, "status") != "moving_to_exit":
                        self.assertEqual(val(b, "status"), val(a, "status"), label)
                        continue
                    if val(b, "status") == "out":
                        self.assertLessEqual(val(a, "egress_length_m"), STEP_M, label)
                        self.assertEqual(val(b, "at_exit"), val(a, "egress_exit"), label)
                        continue
                    # one step of 12.5 m along the route published a publication earlier
                    self.assertEqual(val(a, "egress_length_m") - val(b, "egress_length_m"),
                                     STEP_M, label)
                    old, new = val(a, "route"), val(b, "route")
                    self.assertEqual(old[len(old) - len(new):], new, label)
                    self.assertEqual(val(a, "egress_exit"), val(b, "egress_exit"), label)
        # stop and withdraw the zone: the zone's workers go, nobody else
        frames = states["sw_exec"]["frames"]
        start = frames[0]
        zone = element(start, "zone-d")
        self.assertEqual((val(zone, "work_state"), val(zone, "withdrawal_state"),
                          val(zone, "production_rate")), ("stopped", "in_progress", 0))
        home = [f"worker-{i:02d}" for i in range(1, 15)
                if attributes[f"worker-{i:02d}"]["home_zone"] == "zone-d"]
        for i in range(1, 15):
            w = f"worker-{i:02d}"
            expected = "moving_to_exit" if w in home else val(element(decision, w), "status")
            self.assertEqual(val(element(start, w), "status"), expected, w)
        self.assertEqual(val(start, "workers_in_danger"), 3)
        self.assertEqual(val(element(frames[-1], "zone-d"), "workers_count"), 0)
        self.assertEqual(len(frames), 33)       # 405 m for the last one at 12.5 m per publication
        danger_counts = [val(fr, "workers_in_danger") for fr in frames]
        self.assertEqual(danger_counts, sorted(danger_counts, reverse=True))
        self.assertEqual((danger_counts[0], danger_counts[-1]), (3, 0))
        done = states["sw_done"]["frames"][0]
        self.assertEqual(val(done, "tick"), val(decision, "tick") + 330)
        zone = element(done, "zone-d")
        self.assertEqual((val(zone, "work_state"), val(zone, "withdrawal_state"),
                          val(zone, "workers_count")), ("stopped", "done", 0))
        self.assertEqual((val(done, "workers_out"), val(done, "workers_in_danger"),
                          val(done, "workers_no_route"), val(done, "run_state")),
                         (4, 0, 0, "running"))
        self.assertIs(val(done, "all_out"), False)
        self.assertEqual(val(element(done, "exit-raise"), "workers_out"), 4)
        self.assertEqual(val(element(done, "zone-a"), "work_state"), "working")
        self.assertEqual(val(element(done, "zone-c"), "hazard_state"), "unknown")   # unchanged
        self.assertEqual(val(element(done, "incident"), "state"), "done")
        self.assertEqual(val(element(done, "incident"), "selected_option"), "option-stop-withdraw")
        option = element(done, "option-stop-withdraw")
        self.assertEqual(val(option, "state"), "done")
        self.assertEqual({val(element(done, o), "state") for o in
                          ("option-observe", "option-withdraw-all")}, {"unavailable"})
        for suffix in ("in_danger", "danger_exposure_person_s", "unknown_exposure_person_s",
                       "no_route", "out", "all_out", "downtime_s"):
            self.assertEqual(val(option, "actual_" + suffix), val(option, "forecast_" + suffix),
                             suffix)
        self.assertIs(val(option, "actual_all_out"), False)
        self.assertNotIn("actual_last_out_s", option)
        self.assertEqual(val(option, "actual_out"), 4)
        events = val(element(done, "journal"), "events")
        outs = [e for e in events if e["code"] == "worker.out"]
        self.assertEqual(sorted(e["subject"] for e in outs), home)
        self.assertEqual(max(e["tick"] for e in outs) - val(decision, "tick"), 330)
        self.assertEqual([e["code"] for e in events[-8:]],
                         ["command.applied", "zone.stopped", "withdrawal.started",
                          "worker.out", "worker.out", "worker.out", "worker.out",
                          "withdrawal.finished"])
        # withdraw all ends with everyone out and the published last_out_s
        done = states["wa_done"]["frames"][0]
        self.assertEqual((val(done, "workers_out"), val(done, "workers_total")), (14, 14))
        self.assertIs(val(done, "all_out"), True)
        option = element(done, "option-withdraw-all")
        self.assertEqual(val(option, "actual_last_out_s"), val(option, "forecast_last_out_s"))
        self.assertEqual(len(states["wa_exec"]["frames"]), 58)
        # observe: the frame stays, three people stay in danger to the horizon
        wait = states["observe_exec"]
        self.assertEqual((len(wait["frames"]), wait["publications"]), (1, 90))
        done = states["observe_done"]["frames"][0]
        self.assertEqual((val(done, "workers_out"), val(done, "workers_in_danger")), (0, 3))
        self.assertEqual(val(element(done, "option-observe"), "actual_in_danger"), 3)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

class FixtureFormatTest(unittest.TestCase):
    """The server reads one file format and refuses any other."""

    def test_unknown_format_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            for version in (0, mock_server.FIXTURE_FORMAT + 1, "1", None):
                fx = {"_fixture": {"description": "x"}, "states": {}}
                if version is not None:
                    fx["format"] = version
                (Path(tmp) / "old.json").write_text(json.dumps(fx), encoding="utf-8")
                app = mock_server.App(Path(tmp), UI_DIR / "public", 1000)
                with self.assertRaisesRegex(mock_server.FixtureFormatError, "format"):
                    app.load("old")
            fx["format"] = mock_server.FIXTURE_FORMAT
            (Path(tmp) / "old.json").write_text(json.dumps(fx), encoding="utf-8")
            mock_server.App(Path(tmp), UI_DIR / "public", 1000).load("old")

    def test_files_carry_the_known_format(self):
        for name in SCENARIOS:
            self.assertEqual(load_fixture(name)["format"], mock_server.FIXTURE_FORMAT, name)


class ReadsTest(unittest.TestCase):
    def test_first_response_of_every_scenario(self):
        real = SERVERS["real"]
        for name in SCENARIOS:
            with self.subTest(scenario=name):
                real.scenario(name)
                mine = real.get(MINE)
                self.assertIsNotNone(parse_date(mine.headers["Date"]))
                if name == "empty":
                    for path in (MINE, SHIFT):
                        r = real.get(path)
                        self.assertEqual(r.status, 404)
                        self.assertEqual(r.json()["error"], "things:thing.notfound")
                        self.assertEqual(r.json()["status"], 404)
                        self.assertIn("message", r.json())
                    continue
                self.assertEqual(mine.status, 200)
                attributes = mine.json()["attributes"]
                kinds = kinds_of(real.attributes(attributes["manifest"]))
                self.assertEqual(set(kinds), set(attributes["manifest"]))
                r = real.get(SHIFT)
                self.assertEqual(r.status, 200)
                self.assertTrue(r.headers["Content-Type"].startswith("application/json"))
                thing = r.json()
                self.assertEqual(set(thing), {"thingId", "features", "_modified", "_revision"})
                self.assertIsInstance(thing["_revision"], int)
                datetime.strptime(thing["_modified"], "%Y-%m-%dT%H:%M:%S.%fZ")
                expected = {"topology_mismatch"} if name == "topology_mismatch" else set()
                self.assertEqual(violations(attributes, kinds, thing, r.headers["Date"]), expected)
        real.scenario("normal")

    def test_batch_order_fields_limit_and_unknown_ids(self):
        fast = SERVERS["fast"].scenario("normal")
        manifest = fast.mine()["manifest"]
        self.assertGreater(len(manifest), 60)                 # several batches of 20
        self.assertEqual(len(fast.attributes(manifest)), len(manifest))
        ids = manifest[:20]
        for _ in range(5):
            r = fast.get(f"{THINGS}?ids={','.join(ids)}&fields=thingId,attributes")
            self.assertEqual(r.status, 200)
            got = [t["thingId"] for t in r.json()]
            self.assertEqual(sorted(got), sorted(ids))
            self.assertNotEqual(got, ids, "the batch came back in request order")
            for t in r.json():
                self.assertEqual(set(t), {"thingId", "attributes"})
        r = fast.get(f"{THINGS}?ids={','.join(manifest[:21])}&fields=thingId,attributes")
        self.assertEqual(r.status, 400)
        self.assertEqual(r.json()["status"], 400)
        r = fast.get(f"{THINGS}?ids={tid('w-01')},{tid('nope')},{tid('w-02')}&fields=thingId")
        self.assertEqual(sorted(t["thingId"] for t in r.json()), [tid("w-01"), tid("w-02")])
        self.assertEqual(fast.get(f"{THINGS}?fields=thingId").status, 400)
        self.assertEqual(fast.get(f"{THINGS}?ids=other.ns:thing-1").status, 400)
        r = fast.get(f"{THINGS}?ids={tid('shift')},{tid('w-12')}"
                     "&fields=thingId,features,_modified,_revision")
        for t in r.json():
            self.assertEqual(set(t), {"thingId", "features", "_modified", "_revision"})

    def test_single_thing_is_a_mirror_of_the_scene(self):
        fast = SERVERS["fast"].scenario("paused_heartbeat")
        r = fast.get(f"{THINGS}/{tid('worker-03')}")
        self.assertEqual(set(r.json()), {"thingId", "policyId", "attributes", "features"})
        self.assertEqual(r.json()["attributes"]["label"], "Р-03")
        mirror = {k: v for k, v in r.json()["features"].items()}
        self.assertEqual(mirror, element(fast.features(), "worker-03"))
        r = fast.get(f"{THINGS}/{tid('nobody')}?fields=thingId")
        self.assertEqual((r.status, r.json()["error"]), (404, "things:thing.notfound"))
        r = fast.get(f"{THINGS}/{tid('level-320')}?fields=thingId,attributes/elevation_m")
        self.assertEqual(r.json(), {"thingId": tid("level-320"), "attributes": {"elevation_m": -320}})

    def test_archive_is_read_by_the_ids_in_runs(self):
        fast = SERVERS["fast"].scenario("normal")
        runs = val(fast.features(), "runs")
        ids = ",".join(tid(r) for r in runs)
        things = fast.get(f"{THINGS}?ids={ids}&fields=thingId,attributes,features").json()
        self.assertEqual(sorted(t["thingId"] for t in things), sorted(tid(r) for r in runs))
        for t in things:
            self.assertEqual(t["attributes"]["kind"], "run")
            self.assertEqual(val(t["features"], "state"), "finished")
        # the current run is not an archive thing until a reset finishes it
        self.assertEqual(fast.get(f"{THINGS}/{tid('run-0005')}").status, 404)
        self.assertNotIn(tid("run-0001"), fast.mine()["manifest"])


# ---------------------------------------------------------------------------
# Publications and time
# ---------------------------------------------------------------------------

class PublicationsTest(unittest.TestCase):
    def test_publication_seq_grows_by_wall_time(self):
        real = SERVERS["real"].scenario("normal")
        started = time.monotonic()
        first = real.shift()
        time.sleep(2.4)
        second = real.shift()
        elapsed = time.monotonic() - started
        grown = val(second["features"], "publication_seq") - val(first["features"], "publication_seq")
        self.assertIn(grown, (int(elapsed), int(elapsed) + 1, int(elapsed) - 1))
        self.assertGreaterEqual(grown, 2)
        self.assertEqual(second["_revision"] - first["_revision"], grown)
        self.assertGreater(second["_modified"], first["_modified"])
        self.assertEqual(val(second["features"], "tick") - val(first["features"], "tick"), 10 * grown)
        for el in scene_of(second["features"]):
            self.assertEqual(val(el["features"], "tick"), val(second["features"], "tick"))
            self.assertEqual(val(el["features"], "sim_time_s"), val(second["features"], "tick"))
        # a fresh sensor keeps measuring: its time follows the model time
        self.assertEqual(val(element(second["features"], "sens-ext-01"), "measured_at_tick"),
                         val(second["features"], "tick"))
        # the header and the metadata agree within the precision of the header
        date = email.utils.parsedate_to_datetime(real.get(SHIFT).headers["Date"])
        modified = datetime.strptime(real.shift()["_modified"], "%Y-%m-%dT%H:%M:%S.%fZ")
        self.assertLess(abs((date - modified.replace(tzinfo=timezone.utc)).total_seconds()), 3)

    def test_frozen_seq_stops_after_the_third_publication(self):
        fast = SERVERS["fast"].scenario("frozen_seq")
        first_seq = load_fixture("frozen_seq")["publication"]["first_seq"]
        self.assertLessEqual(val(fast.features(), "publication_seq"), first_seq + 2)
        fast.wait(lambda: fast.state()["frozen"], 10, "freeze")
        frozen = fast.shift()
        self.assertEqual(fast.state()["publication"], 3)
        self.assertEqual(val(frozen["features"], "publication_seq"), first_seq + 2)
        r, body = fast.command("condition.close_working", "w-12")
        self.assertEqual(r.status, 202)
        time.sleep(0.6)
        later = fast.get(SHIFT)
        self.assertEqual(later.status, 200)
        self.assertEqual(later.json(), frozen)
        self.assertEqual(fast.ack(body["command_id"]), [])

    def test_frozen_seq_old_is_stale_from_the_first_response(self):
        fast = SERVERS["fast"].scenario("frozen_seq_old")
        r = fast.get(SHIFT)
        date = email.utils.parsedate_to_datetime(r.headers["Date"])
        modified = datetime.strptime(r.json()["_modified"], "%Y-%m-%dT%H:%M:%S.%fZ")
        age = (date - modified.replace(tzinfo=timezone.utc)).total_seconds()
        self.assertTrue(29 <= age <= 32, age)
        time.sleep(0.5)
        self.assertEqual(fast.get(SHIFT).json(), r.json())
        self.assertEqual(fast.state()["publication"], 1)

    def test_paused_heartbeat_keeps_tick_and_grows_seq(self):
        fast = SERVERS["fast"].scenario("paused_heartbeat")
        first = fast.features()
        fast.wait(lambda: fast.state()["publication"] >= 6, 10, "five more publications")
        second = fast.shift()
        self.assertGreaterEqual(val(second["features"], "publication_seq")
                                - val(first, "publication_seq"), 4)
        self.assertEqual(val(second["features"], "tick"), val(first, "tick"))
        self.assertEqual(val(second["features"], "sim_time_s"), val(first, "sim_time_s"))
        self.assertEqual((val(first, "run_state"), val(first, "pause_reason")),
                         ("paused", "decision"))
        self.assertEqual(scene_of(second["features"]), scene_of(first))

    def test_invalid_scenarios_break_after_three_publications(self):
        fast = SERVERS["fast"]
        for name, code in INVALID.items():
            with self.subTest(scenario=name):
                fast.scenario(name)
                attributes = fast.mine()
                kinds = kinds_of(fast.attributes(attributes["manifest"]))
                fast.wait_state("violated", 10)
                self.assertEqual(fast.state()["publication"] >= 4, True)
                r = fast.get(SHIFT)
                thing = r.json()
                self.assertEqual(violations(attributes, kinds, thing, r.headers["Date"]), {code})
                seq = val(thing["features"], "publication_seq")
                later = fast.wait(lambda: (lambda t: t if val(t["features"], "publication_seq")
                                           >= seq + 3 else None)(fast.shift()), 10, "growth")
                self.assertEqual(violations(attributes, kinds, later, r.headers["Date"]), {code})
                if code == "mixed_tick":
                    lag = val(later["features"], "tick") - val(
                        element(later["features"], "sens-geo-02"), "tick")
                    self.assertEqual(lag, 10)
                if code == "no_metadata":
                    self.assertEqual(set(later), {"thingId", "features"})

    def test_topology_mismatch_and_change(self):
        fast = SERVERS["fast"].scenario("topology_mismatch")
        self.assertEqual(fast.mine()["topology_version"], "t1")
        fast.wait(lambda: fast.state()["publication"] >= 5, 10, "publications")
        self.assertEqual(val(fast.features(), "topology_version"), "t2")
        self.assertEqual(fast.mine()["topology_version"], "t1")

        fast.scenario("topology_change")
        old = fast.mine()
        old_things = fast.attributes(old["manifest"])
        self.assertEqual((old["topology_version"], val(fast.features(), "topology_version")),
                         ("t1", "t1"))
        fast.wait_state("t2", 10)
        thing = fast.shift()
        self.assertEqual(val(thing["features"], "topology_version"), "t2")
        self.assertEqual(violations(old, kinds_of(old_things), thing),
                         {"topology_mismatch", "extra_id"})
        new = fast.mine()
        new_things = fast.attributes(new["manifest"])
        self.assertEqual(new["topology_version"], "t2")
        self.assertEqual(set(new["manifest"]) - set(old["manifest"]), {tid("w-37")})
        self.assertEqual(set(new["dynamic_ids"]) - set(old["dynamic_ids"]), {tid("w-37")})
        self.assertEqual(violations(new, kinds_of(new_things), thing), set())
        lengths = [{t["thingId"]: t["attributes"] for t in things}[tid("w-19")]["length_m"]
                   for things in (old_things, new_things)]
        self.assertNotEqual(lengths[0], lengths[1])
        self.assertNotEqual(old["nodes"]["n-19"], new["nodes"]["n-19"])


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

class CommandsTest(unittest.TestCase):
    def setUp(self):
        self.mock = SERVERS["fast"].scenario("commands")

    def effect(self, command_id):
        entries = [e for e in self.mock.log() if e.get("body", {}).get("command_id") == command_id]
        self.assertTrue(entries, "the command is not in the log")
        return entries

    def test_accepted_but_never_acknowledged(self):
        r, body = self.mock.command("condition.close_working", "w-12")
        self.assertEqual((r.status, r.body), (202, b""))
        seq = val(self.mock.features(), "publication_seq")
        self.mock.wait(lambda: val(self.mock.features(), "publication_seq") >= seq + 8, 12, "time")
        features = self.mock.features()
        self.assertEqual(self.mock.ack(body["command_id"], features), [])
        self.assertEqual(val(element(features, "w-12"), "passability"), "open")
        self.assertIs(self.effect(body["command_id"])[0]["effect_applied"], False)

    def test_rejected_by_the_model(self):
        r, body = self.mock.command("condition.close_working", "w-07")
        self.assertEqual(r.status, 202)
        ack = self.mock.wait_ack(body["command_id"])
        self.assertEqual(set(ack), {"id", "type", "target", "run", "status", "tick",
                                    "sim_time_s", "reason"})
        self.assertEqual((ack["status"], ack["reason"], ack["type"], ack["target"], ack["run"]),
                         ("rejected", "not_allowed_in_state", "condition.close_working", "w-07",
                          "run-0005"))
        self.assertEqual(val(element(self.mock.features(), "w-07"), "passability"), "open")
        r, body = self.mock.command("action.resume_zone", "zone-a")
        ack = self.mock.wait_ack(body["command_id"])
        self.assertEqual((ack["status"], ack["reason"]), ("rejected", "insufficient_workers"))
        self.assertEqual(val(element(self.mock.features(), "zone-a"), "work_state"), "stopped")

    def test_acknowledgement_arrives_one_publication_later_with_its_tick(self):
        before = self.mock.shift()["features"]
        r, body = self.mock.command("action.stop_zone", "zone-a")
        ack = self.mock.wait_ack(body["command_id"])
        after = self.mock.features()
        self.assertEqual((ack["status"], ack["reason"]), ("applied", "already_in_state"))
        self.assertGreater(ack["tick"], val(before, "tick"))
        self.assertLessEqual(ack["tick"], val(after, "tick"))
        self.assertEqual(ack["tick"], ack["sim_time_s"])
        self.assertEqual(element(after, "zone-a")["work_state"], element(before, "zone-a")["work_state"])
        self.assertIs(self.effect(body["command_id"])[0]["effect_applied"], False)

    def test_http_503_then_repeat_with_the_same_id_applies_once(self):
        r, body = self.mock.command("action.stop_zone", "zone-b")
        self.assertEqual(r.status, 503)
        seq = val(self.mock.features(), "publication_seq")
        self.mock.wait(lambda: val(self.mock.features(), "publication_seq") >= seq + 4, 8, "time")
        features = self.mock.features()
        self.assertEqual(self.mock.ack(body["command_id"], features), [])
        self.assertEqual(val(element(features, "zone-b"), "work_state"), "working")
        r, _ = self.mock.command("action.stop_zone", "zone-b", command_id=body["command_id"])
        self.assertEqual(r.status, 202)
        ack = self.mock.wait_ack(body["command_id"])
        self.assertEqual((ack["status"], ack["reason"]), ("applied", "none"))
        features = self.mock.features()
        zone = element(features, "zone-b")
        self.assertEqual((val(zone, "work_state"), val(zone, "production_rate")), ("stopped", 0))
        events = [e for e in val(element(features, "journal"), "events")
                  if e.get("command_id") == body["command_id"]]
        self.assertEqual([e["code"] for e in events], ["command.applied"])
        self.assertEqual(events[0]["tick"], ack["tick"])
        log = self.effect(body["command_id"])
        self.assertEqual([(e["status"], e["delivered"], e["effect_applied"]) for e in log],
                         [(503, False, False), (202, True, True)])
        # the same command with a new id: applied without a change
        r, again = self.mock.command("action.stop_zone", "zone-b")
        ack = self.mock.wait_ack(again["command_id"])
        self.assertEqual((ack["status"], ack["reason"]), ("applied", "already_in_state"))

    def test_hanging_post_is_delivered_and_a_repeat_does_not_apply_twice(self):
        hang_s = 10 * self.mock.interval
        started = time.monotonic()
        with self.assertRaises(OSError):         # the client gives up: delivery unknown
            self.mock.command("condition.sensor_lost", "sens-ext-05",
                              command_id="c-" + "5" * 32, timeout=hang_s / 4)
        self.assertLess(time.monotonic() - started, hang_s)
        command_id = "c-" + "5" * 32
        ack = self.mock.wait_ack(command_id)       # applied although the POST never answered
        self.assertEqual((ack["status"], ack["reason"]), ("applied", "none"))
        r, _ = self.mock.command("condition.sensor_lost", "sens-ext-05", command_id=command_id)
        self.assertEqual(r.status, 202)
        seq = val(self.mock.features(), "publication_seq")
        self.mock.wait(lambda: val(self.mock.features(), "publication_seq") >= seq + 4, 8, "time")
        features = self.mock.features()
        self.assertEqual(len(self.mock.ack(command_id, features)), 1)
        self.assertEqual(val(features, "conditions"), ["sensor_lost:sens-ext-05"])
        sensor = element(features, "sens-ext-05")
        self.assertEqual(val(sensor, "link_state"), "offline")
        self.assertLess(val(sensor, "measured_at_tick"), ack["tick"])
        self.assertGreaterEqual(val(sensor, "measured_at_tick"), ack["tick"] - 10)
        events = [e for e in val(element(features, "journal"), "events")
                  if e.get("command_id") == command_id]
        self.assertEqual([e["code"] for e in events], ["condition.set"])
        log = self.effect(command_id)
        self.assertEqual([(e["delivered"], e["effect_applied"], e["duplicate"]) for e in log],
                         [(True, True, False), (True, False, True)])

    def test_hanging_post_ends_with_504(self):
        hang_s = 10 * self.mock.interval
        started = time.monotonic()
        r, body = self.mock.command("condition.sensor_lost", "sens-ext-05", timeout=hang_s + 5)
        self.assertEqual(r.status, 504)
        self.assertGreaterEqual(time.monotonic() - started, hang_s * 0.9)
        self.assertEqual(self.mock.wait_ack(body["command_id"])["status"], "applied")
        self.assertEqual(self.effect(body["command_id"])[0]["hang_ms"], int(hang_s * 1000))

    def test_same_id_same_body_applies_once_and_another_body_conflicts(self):
        self.mock.scenario("detour")
        r, body = self.mock.command("condition.close_working", "w-12")
        for _ in range(2):
            r, _ = self.mock.command("condition.close_working", "w-12",
                                     command_id=body["command_id"])
            self.assertEqual(r.status, 202)
        ack = self.mock.wait_ack(body["command_id"])
        self.assertEqual(ack["status"], "applied")
        self.mock.wait_state("decision")
        r, _ = self.mock.command("condition.open_working", "w-12", command_id=body["command_id"])
        self.assertEqual(r.status, 202)
        records = self.mock.wait(lambda: (lambda a: a if len(a) == 2 else None)(
            self.mock.ack(body["command_id"])), 10, "the conflict record")
        self.assertEqual([(a["status"], a["reason"], a["type"]) for a in records],
                         [("applied", "none", "condition.close_working"),
                          ("rejected", "command_id_conflict", "condition.open_working")])
        features = self.mock.features()
        self.assertEqual(val(features, "conditions"), ["working_closed:w-12"])
        self.assertEqual(val(element(features, "w-12"), "passability"), "closed")
        sets = [e for e in val(element(features, "journal"), "events")
                if e["code"] == "condition.set"]
        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0]["command_id"], body["command_id"])
        log = self.effect(body["command_id"])
        self.assertEqual([e["effect_applied"] for e in log], [True, False, False, False])
        self.assertEqual([e.get("duplicate") for e in log], [False, True, True, False])
        self.assertIs(log[3]["conflict"], True)

    def test_model_side_rejections(self):
        cases = [
            (("condition.close_working", "w-12"), {"run": "run-0001"}, "invalid_run"),
            (("condition.teleport", "w-12"), {}, "unknown_type"),
            (("condition.close_working", "w-99"), {}, "unknown_target"),
            (("action.stop_zone", "w-12"), {}, "unknown_target"),
            (("run.start_preset", "p-unknown"), {}, "unknown_target"),
            (("action.execute_option", "option-observe"), {}, "malformed"),
            (("condition.instability_on", "zone-b"), {}, "not_scripted"),
        ]
        for (ctype, target), extra, reason in cases:
            with self.subTest(reason=reason, type=ctype):
                r, body = self.mock.command(ctype, target, **extra)
                self.assertEqual(r.status, 202)
                ack = self.mock.wait_ack(body["command_id"])
                self.assertEqual((ack["status"], ack["reason"]), ("rejected", reason))
                self.assertEqual(ack["run"], body["run"])

    def test_http_validation_of_the_post(self):
        good = {"command_id": "c-" + "a" * 32, "type": "action.stop_zone", "target": "zone-a",
                "run": "run-0005"}
        json_type = {"Content-Type": "application/json"}
        raw = json.dumps(good).encode()
        no_timeout = COMMAND.split("?")[0]
        cases = [
            ("no timeout", no_timeout, raw, json_type, 400),
            ("timeout=5", no_timeout + "?timeout=5", raw, json_type, 400),
            ("content type", COMMAND, raw, {"Content-Type": "text/plain"}, 400),
            ("not json", COMMAND, b"{not json", json_type, 400),
            ("array", COMMAND, b"[1]", json_type, 400),
            ("no run", COMMAND, json.dumps({k: v for k, v in good.items() if k != "run"}).encode(),
             json_type, 400),
            ("short id", COMMAND, json.dumps(dict(good, command_id="c-123")).encode(), json_type,
             400),
            ("upper id", COMMAND, json.dumps(dict(good, command_id="c-" + "A" * 32)).encode(),
             json_type, 400),
            ("too large", COMMAND, json.dumps(dict(good, note="x" * 5000)).encode(), json_type,
             413),
        ]
        for label, path, data, headers, status in cases:
            with self.subTest(case=label):
                r = self.mock.request("POST", path, data, headers)
                self.assertEqual(r.status, status)
                self.assertEqual(r.json()["status"], status)
        seq = val(self.mock.features(), "publication_seq")
        self.mock.wait(lambda: val(self.mock.features(), "publication_seq") >= seq + 3, 8, "time")
        commands = val(self.mock.features(), "commands")
        self.assertEqual(len(commands), 2)       # only the two records written in the fixture
        refused = [e for e in self.mock.log() if e["kind"] == "command"]
        self.assertEqual(len(refused), len(cases))
        self.assertFalse(any(e.get("effect_applied") for e in refused))
        r = self.mock.request("POST", COMMAND, raw + b" ", dict(json_type))
        self.assertEqual(r.status, 202)

    def test_commands_window_shows_the_last_32(self):
        ids = []
        for _ in range(36):
            r, body = self.mock.command("condition.instability_on", "zone-b")
            self.assertEqual(r.status, 202)
            ids.append(body["command_id"])
        self.mock.wait_ack(ids[-1])
        commands = val(self.mock.features(), "commands")
        self.assertEqual([c["id"] for c in commands], ids[-32:])


# ---------------------------------------------------------------------------
# Stories with scripted frames
# ---------------------------------------------------------------------------

class StoriesTest(unittest.TestCase):
    OPTIONS = ("option-observe", "option-stop-withdraw", "option-withdraw-all")

    def to_decision(self, scenario, working):
        mock = SERVERS["story"].scenario(scenario)
        initial = mock.features()
        self.assertEqual(val(initial, "run_state"), "running")
        r, close = mock.command("condition.close_working", working)
        self.assertEqual(r.status, 202)
        ack = mock.wait_ack(close["command_id"])
        self.assertEqual((ack["status"], ack["reason"]), ("applied", "none"))
        features = mock.features()
        self.assertEqual((val(features, "run_state"), val(features, "pause_reason")),
                         ("paused", "decision"))
        self.assertEqual(val(features, "tick"), ack["tick"])
        self.assertEqual(val(features, "conditions"), [f"working_closed:{working}"])
        self.assertEqual(val(element(features, working), "passability"), "closed")
        incident = element(features, "incident")
        self.assertEqual((val(incident, "state"), val(incident, "trigger"),
                          val(incident, "opened_at_tick")),
                         ("active", "passage_closed", ack["tick"]))
        journal = [e for e in val(element(features, "journal"), "events")
                   if e.get("command_id") == close["command_id"]]
        self.assertEqual([(e["code"], e["tick"]) for e in journal],
                         [("condition.set", ack["tick"])])
        return mock, features

    def execute(self, mock, features, option):
        decision_id = val(element(features, option), "decision_id")
        r, wrong = mock.command("action.execute_option", option, decision_id="d-0000-00")
        self.assertEqual(r.status, 202)
        ack = mock.wait_ack(wrong["command_id"])
        self.assertEqual((ack["status"], ack["reason"]), ("rejected", "stale_decision"))
        self.assertEqual(val(mock.features(), "run_state"), "paused")
        r, body = mock.command("action.execute_option", option, decision_id=decision_id)
        ack = mock.wait_ack(body["command_id"])
        self.assertEqual((ack["status"], ack["reason"]), ("applied", "none"))
        return ack

    def follow_movement(self, mock, worker, done_state, publications):
        """Reads frames until the end state; checks the pace of one worker."""
        seen = []
        while mock.state()["state"] != done_state:
            features = mock.features()
            w = element(features, worker)
            if val(w, "status") == "moving_to_exit":
                seen.append((val(features, "tick"), val(w, "egress_length_m")))
            self.assertLess(len(seen), publications * 40, "the story does not end")
            time.sleep(0.02)
        ticks = dict(seen)
        self.assertGreater(len(ticks), 10)
        pairs = sorted(ticks.items())
        for (t0, l0), (t1, l1) in zip(pairs, pairs[1:]):
            self.assertEqual(l0 - l1, STEP_M * (t1 - t0) / 10, f"tick {t0}->{t1}")
        return pairs

    def test_detour_stop_withdraw_then_open_the_passage(self):
        mock, features = self.to_decision("detour", "w-12")
        w3 = element(features, "worker-03")
        self.assertEqual((val(w3, "egress_length_m"), val(w3, "egress_detour_m"),
                          val(w3, "egress_exit")), (655, 243, "exit-ramp"))
        for i in (3, 4, 5, 6):
            self.assertIn("w-03", val(element(features, f"worker-{i:02d}"), "route"))
        options = [element(features, o) for o in self.OPTIONS]
        self.assertEqual({val(o, "state") for o in options}, {"offered"})
        self.assertEqual(len({val(o, "decision_id") for o in options}), 1)
        self.assertEqual(len({val(o, "comparison_key") for o in options}), 1)
        self.assertEqual({val(o, "forecast_tick") for o in options}, {val(features, "tick")})

        ack = self.execute(mock, features, "option-stop-withdraw")
        started = mock.features()
        self.assertEqual(val(started, "run_state"), "running")
        zone = element(started, "zone-b")
        self.assertEqual((val(zone, "work_state"), val(zone, "withdrawal_state")),
                         ("stopped", "in_progress"))
        pairs = self.follow_movement(mock, "worker-03", "sw_done", 60)
        self.assertEqual(pairs[0][0] - ack["tick"] <= 60, True)
        end = mock.features()
        self.assertEqual(val(end, "workers_out"), 4)
        self.assertIs(val(end, "all_out"), False)
        self.assertEqual(val(element(end, "zone-b"), "withdrawal_state"), "done")
        self.assertEqual(val(element(end, "zone-b"), "workers_count"), 0)
        self.assertEqual(val(element(end, "zone-a"), "work_state"), "working")
        self.assertEqual(val(element(end, "exit-ramp"), "workers_out"), 4)
        option = element(end, "option-stop-withdraw")
        self.assertEqual(val(option, "state"), "done")
        self.assertIs(val(option, "actual_all_out"), False)
        self.assertNotIn("actual_last_out_s", option)
        self.assertEqual(val(option, "actual_out"), 4)
        self.assertEqual(val(element(end, "incident"), "state"), "done")
        self.assertEqual(val(element(end, "worker-03"), "status"), "out")
        outs = [e for e in val(element(end, "journal"), "events") if e["code"] == "worker.out"]
        self.assertEqual(len(outs), 4)
        # 655 m at 12.5 m per publication: the last one is out 530 model seconds after the decision
        self.assertEqual(max(e["tick"] for e in outs) - ack["tick"], 530)

        r, body = mock.command("condition.open_working", "w-12")
        opened = mock.wait_ack(body["command_id"])
        self.assertEqual((opened["status"], opened["reason"]), ("applied", "none"))
        after = mock.features()
        self.assertEqual(val(after, "conditions"), [])
        self.assertEqual((val(element(after, "w-12"), "passability"),
                          val(element(after, "w-12"), "closed_by")), ("open", "none"))
        self.assertEqual(val(after, "workers_out"), 4)                 # nobody moves back
        self.assertEqual(val(element(after, "worker-03"), "status"), "out")
        self.assertEqual(val(element(after, "zone-b"), "work_state"), "stopped")
        events = val(element(after, "journal"), "events")
        codes = [e["code"] for e in events]
        self.assertEqual((codes.count("condition.set"), codes.count("condition.cancelled")), (1, 1))
        # times of the whole story lie on one model clock, whenever the commands arrived
        ticks = [e["tick"] for e in events]
        self.assertEqual(ticks, sorted(ticks))
        self.assertEqual(ticks[-1], opened["tick"])
        self.assertEqual(events[-1]["command_id"], body["command_id"])
        self.assertLessEqual(opened["tick"], val(after, "tick"))

    def test_detour_withdraw_all_ends_with_everyone_out(self):
        mock, features = self.to_decision("detour", "w-12")
        forecast = element(features, "option-withdraw-all")
        ack = self.execute(mock, features, "option-withdraw-all")
        self.follow_movement(mock, "worker-07", "wa_done", 65)
        end = mock.features()
        self.assertEqual((val(end, "workers_out"), val(end, "workers_total")), (14, 14))
        self.assertIs(val(end, "all_out"), True)
        option = element(end, "option-withdraw-all")
        self.assertIs(val(option, "actual_all_out"), True)
        self.assertEqual(val(option, "actual_last_out_s"), 580)
        for suffix in ("in_danger", "danger_exposure_person_s", "unknown_exposure_person_s",
                       "no_route", "out", "all_out", "last_out_s", "downtime_s"):
            self.assertEqual(val(option, "actual_" + suffix), val(forecast, "forecast_" + suffix))
        outs = [e for e in val(element(end, "journal"), "events") if e["code"] == "worker.out"]
        self.assertEqual(max(e["tick"] for e in outs) - ack["tick"], 580)
        self.assertEqual({val(element(end, z), "withdrawal_state")
                          for z in ("zone-a", "zone-b", "zone-c", "zone-d")}, {"done"})
        others = [val(element(end, o), "state") for o in self.OPTIONS[:2]]
        self.assertEqual(others, ["unavailable", "unavailable"])

    def test_detour_observe_runs_to_the_horizon_and_reopening_restores_routes(self):
        mock, features = self.to_decision("detour", "w-12")
        ack = self.execute(mock, features, "option-observe")
        running = mock.wait(lambda: (lambda f: f if val(f, "tick") >= ack["tick"] + 50 else None)(
            mock.features()), 20, "model time to run")
        self.assertEqual((val(running, "run_state"), mock.state()["state"]),
                         ("running", "observe_exec"))
        self.assertEqual(val(element(running, "option-observe"), "state"), "executing")
        self.assertEqual(val(element(running, "worker-03"), "status"), "working")
        self.assertEqual(val(element(running, "worker-03"), "egress_length_m"), 655)
        self.assertEqual(val(element(running, "sens-ext-02"), "measured_at_tick"),
                         val(running, "tick"))
        mock.wait_state("observe_done", 100)
        end = mock.features()
        self.assertGreaterEqual(val(end, "tick"), ack["tick"] + 900)     # the forecast horizon
        option = element(end, "option-observe")
        self.assertEqual(val(option, "state"), "done")
        self.assertIs(val(option, "actual_all_out"), False)
        self.assertNotIn("actual_last_out_s", option)
        self.assertEqual((val(end, "workers_out"), val(element(end, "zone-b"), "work_state")),
                         (0, "working"))
        r, body = mock.command("condition.open_working", "w-12")
        self.assertEqual(mock.wait_ack(body["command_id"])["status"], "applied")
        after = mock.features()
        w3 = element(after, "worker-03")
        self.assertEqual((val(w3, "egress_length_m"), val(w3, "egress_detour_m"),
                          val(w3, "egress_exit")), (412, 0, "exit-shaft"))
        self.assertEqual(val(after, "conditions"), [])

    def test_detour_open_at_the_decision_point_issues_a_new_decision(self):
        mock, features = self.to_decision("detour", "w-12")
        old = val(element(features, "option-observe"), "decision_id")
        r, body = mock.command("condition.open_working", "w-12")
        mock.wait_ack(body["command_id"])
        after = mock.features()
        self.assertEqual(val(after, "run_state"), "paused")
        self.assertEqual(val(element(after, "worker-03"), "egress_length_m"), 412)
        self.assertEqual(val(element(after, "worker-03"), "egress_detour_m"), 0)
        self.assertNotEqual(val(element(after, "option-observe"), "decision_id"), old)
        r, body = mock.command("action.execute_option", "option-observe", decision_id=old)
        ack = mock.wait_ack(body["command_id"])
        self.assertEqual((ack["status"], ack["reason"]), ("rejected", "stale_decision"))

    def test_detour_preset_starts_a_new_run_at_the_same_decision_point(self):
        mock = SERVERS["story"].scenario("detour")
        archive_key = val(mock.get(f"{THINGS}/{tid('run-0001')}").json()["features"],
                          "comparison_key")
        r, body = mock.command("run.start_preset", "p-detour")
        self.assertEqual(r.status, 202)
        mock.wait_state("preset_decision", 20)
        features = mock.features()
        ack = mock.ack(body["command_id"], features)[0]
        self.assertEqual((ack["status"], ack["run"], ack["new_run"]),
                         ("applied", "run-0005", "run-0006"))
        self.assertEqual((val(features, "idSimulationRun"), val(features, "tick")),
                         ("run-0006", 60))
        self.assertEqual((val(features, "run_state"), val(features, "pause_reason")),
                         ("paused", "decision"))
        self.assertEqual(val(features, "conditions"), ["working_closed:w-12"])
        self.assertEqual(val(element(features, "worker-03"), "egress_length_m"), 655)
        self.assertEqual({val(element(features, o), "comparison_key") for o in self.OPTIONS},
                         {archive_key})
        self.assertEqual(val(features, "runs")[-1], "run-0005")
        old = mock.get(f"{THINGS}/{tid('run-0005')}").json()["features"]
        self.assertEqual(val(old, "completion_reason"), "reset")
        for el in scene_of(features):
            self.assertEqual(val(el["features"], "idSimulationRun"), "run-0006")

    def test_no_path_leaves_two_workers_without_a_route(self):
        mock, features = self.to_decision("no_path", "w-07")
        self.assertEqual(val(features, "workers_no_route"), 2)
        for worker in ("worker-07", "worker-08"):
            w = element(features, worker)
            self.assertEqual((val(w, "egress_status"), val(w, "egress_reason"), val(w, "status")),
                             ("none", "no_open_path", "working"))
            self.assertFalse({"route", "route_next_node", "egress_length_m", "egress_eta_s",
                              "egress_exit"} & set(w))
        for o in self.OPTIONS:
            option = element(features, o)
            self.assertEqual(val(option, "forecast_no_route"), 2)
            self.assertIs(val(option, "forecast_all_out"), False)
            self.assertNotIn("forecast_last_out_s", option)
        self.execute(mock, features, "option-stop-withdraw")
        mock.wait_state("sw_done", 10)
        end = mock.features()
        self.assertEqual(val(element(end, "zone-c"), "withdrawal_state"), "incomplete")
        option = element(end, "option-stop-withdraw")
        self.assertEqual(val(option, "state"), "done")
        self.assertIs(val(option, "actual_all_out"), False)
        self.assertNotIn("actual_last_out_s", option)
        self.assertEqual(val(option, "actual_no_route"), 2)
        self.assertEqual(val(end, "workers_no_route"), 2)
        self.assertIs(val(end, "all_out"), False)
        for worker in ("worker-07", "worker-08"):
            w = element(end, worker)
            self.assertEqual((val(w, "status"), val(w, "at_working")),
                             ("waiting", val(element(features, worker), "at_working")))

    def test_danger_zone_runs_into_the_decision_and_the_zone_is_withdrawn(self):
        mock = SERVERS["story"].scenario("danger_zone")
        first = mock.features()
        self.assertEqual((val(first, "run_state"), val(first, "workers_in_danger")),
                         ("running", 0))
        # the running prelude: the rate of the zone climbs, then the model stops for a decision
        rates = {}
        mock.wait(lambda: rates.setdefault(val(mock.features(), "tick"),
                                           val(element(mock.features(), "sens-ext-04"), "rate"))
                  and mock.state()["state"] == "decision", 40, "the decision point")
        self.assertEqual(sorted(rates), sorted(set(rates)))
        self.assertGreaterEqual(len(rates), 3)
        features = mock.features()
        self.assertEqual((val(features, "run_state"), val(features, "pause_reason"),
                          val(features, "tick")), ("paused", "decision", 1260))
        zone = element(features, "zone-d")
        self.assertEqual([val(zone, k) for k in ("hazard_state", "data_quality",
                                                  "routing_restriction")],
                         ["danger", "fresh", "blocked"])
        incident = element(features, "incident")
        self.assertEqual((val(incident, "state"), val(incident, "trigger"),
                          val(incident, "opened_at_tick")), ("active", "hazard", 1260))
        self.assertEqual(val(features, "workers_in_danger"), 3)
        self.assertEqual(val(element(features, "zone-c"), "last_known_hazard_state"), "normal")
        # the model stays on the decision point: the same tick, the sequence grows
        later = mock.features()
        self.assertEqual(val(later, "tick"), 1260)
        # a command that the fixture does not script
        r, body = mock.command("action.stop_zone", "zone-d")
        ack = mock.wait_ack(body["command_id"])
        self.assertEqual((ack["status"], ack["reason"]), ("rejected", "not_scripted"))

        ack = self.execute(mock, features, "option-stop-withdraw")
        started = mock.features()
        self.assertEqual(val(started, "run_state"), "running")
        zone = element(started, "zone-d")
        self.assertEqual((val(zone, "work_state"), val(zone, "withdrawal_state")),
                         ("stopped", "in_progress"))
        self.follow_movement(mock, "worker-14", "sw_done", 40)
        end = mock.features()
        self.assertEqual((val(end, "workers_out"), val(end, "workers_in_danger")), (4, 0))
        self.assertEqual(val(element(end, "zone-d"), "withdrawal_state"), "done")
        option = element(end, "option-stop-withdraw")
        self.assertEqual(val(option, "state"), "done")
        self.assertEqual(val(option, "actual_out"), 4)
        self.assertIs(val(option, "actual_all_out"), False)
        self.assertNotIn("actual_last_out_s", option)
        self.assertEqual(val(option, "actual_in_danger"), 0)
        for suffix in ("danger_exposure_person_s", "unknown_exposure_person_s", "downtime_s"):
            self.assertEqual(val(option, "actual_" + suffix), val(option, "forecast_" + suffix))
        self.assertEqual(val(element(end, "incident"), "state"), "done")
        events = val(element(end, "journal"), "events")
        outs = [e for e in events if e["code"] == "worker.out"]
        self.assertEqual(sorted(e["subject"] for e in outs),
                         ["worker-11", "worker-12", "worker-13", "worker-14"])
        self.assertEqual(max(e["tick"] for e in outs) - ack["tick"], 330)
        applied = [e for e in events if e["code"] == "command.applied"]
        self.assertEqual(applied[-1]["command_id"], ack["id"])
        self.assertEqual(applied[-1]["tick"], ack["tick"])
        # the sensor elsewhere is still stale, the model does not pretend otherwise
        self.assertEqual(val(element(end, "sens-ext-05"), "quality"), "stale")
        self.assertEqual(val(element(end, "zone-c"), "hazard_state"), "unknown")


    def test_reset_goes_through_resetting_to_a_new_run(self):
        mock = SERVERS["real"].scenario("reset")   # real pace: no publication can be missed
        self.addCleanup(mock.scenario, "normal")
        before = mock.features()
        self.assertEqual((val(before, "idSimulationRun"), val(before, "run_state")),
                         ("run-0005", "paused"))
        self.assertNotEqual(val(before, "conditions"), [])
        r, body = mock.command("run.reset", "run")
        self.assertEqual(r.status, 202)
        seen = {}
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            features = mock.features()
            seen.setdefault(val(features, "publication_seq"), features)
            if sum(1 for f in seen.values() if val(f, "idSimulationRun") == "run-0006") >= 2:
                break
            time.sleep(0.1)
        frames = [seen[k] for k in sorted(seen)]
        self.assertEqual(sorted(seen), list(range(min(seen), max(seen) + 1)), "a publication was missed")
        resetting = [f for f in frames if val(f, "run_state") == "resetting"]
        self.assertEqual(len(resetting), 2)
        for f in resetting:
            self.assertEqual(val(f, "idSimulationRun"), "run-0005")
            self.assertEqual(mock.ack(body["command_id"], f), [])
        new = [f for f in frames if val(f, "idSimulationRun") == "run-0006"]
        first = new[0]
        self.assertEqual((val(first, "tick"), val(first, "sim_time_s"), val(first, "run_state")),
                         (0, 0, "running"))
        self.assertEqual(val(first, "conditions"), [])
        self.assertEqual(val(element(first, "w-12"), "passability"), "open")
        self.assertEqual(val(element(first, "incident"), "state"), "none")
        self.assertEqual(val(element(first, "worker-03"), "egress_length_m"), 412)
        ack = mock.ack(body["command_id"], first)
        self.assertEqual(len(ack), 1)
        self.assertEqual({k: ack[0][k] for k in ("type", "run", "new_run", "status")},
                         {"type": "run.reset", "run": "run-0005", "new_run": "run-0006",
                          "status": "applied"})
        self.assertEqual(ack[0]["tick"], val(before, "tick"))    # a tick of the old run
        self.assertEqual(val(first, "runs"), val(before, "runs") + ["run-0005"])
        self.assertGreater(val(first, "publication_seq"), val(before, "publication_seq"))
        self.assertGreater(val(element(first, "journal"), "last_seq"),
                           val(element(before, "journal"), "last_seq"))
        self.assertEqual(val(new[1], "tick"), 10)
        # the journal keeps the old run's records unchanged and continues the numbering
        old_events = val(element(before, "journal"), "events")
        new_events = val(element(first, "journal"), "events")
        self.assertEqual(new_events[:len(old_events)], old_events)
        self.assertEqual([(e["code"], e["run"]) for e in new_events[len(old_events):]],
                         [("run.reset", "run-0005"), ("run.started", "run-0006"),
                          ("hazard.changed", "run-0006")])
        self.assertEqual(new_events[len(old_events)]["command_id"], body["command_id"])
        old = mock.get(f"{THINGS}?ids={tid('run-0005')}&fields=thingId,attributes,features").json()
        self.assertEqual(val(old[0]["features"], "completion_reason"), "reset")
        self.assertNotIn("last_out_s", old[0]["features"])
        # a repeat of the same reset does not start another run
        r, _ = mock.command("run.reset", "run", command_id=body["command_id"])
        self.assertEqual(r.status, 202)
        time.sleep(2.2)
        later = mock.features()
        self.assertEqual(val(later, "idSimulationRun"), "run-0006")
        self.assertEqual(val(later, "runs"), val(first, "runs"))
        self.assertEqual(len(mock.ack(body["command_id"], later)), 1)


# ---------------------------------------------------------------------------
# What the server refuses, faults, static files, process
# ---------------------------------------------------------------------------

class ServerSurfaceTest(unittest.TestCase):
    def test_other_paths_and_methods_are_refused_and_logged(self):
        fast = SERVERS["fast"].scenario("normal")
        body = json.dumps({"x": 1}).encode()
        headers = {"Content-Type": "application/json"}
        cases = [
            ("GET", "/ditto/api/2/search/things?namespaces=team040.mine", None, 404),
            ("GET", f"{THINGS}/{tid('w-12')}/features/passability", None, 404),
            ("GET", "/ditto/api/2/policies/default:basic_policy", None, 404),
            ("GET", "/ditto/status", None, 404),
            ("PUT", f"{THINGS}/{tid('w-12')}", body, 405),
            ("PATCH", f"{THINGS}/{tid('w-12')}", body, 405),
            ("DELETE", f"{THINGS}/{tid('w-12')}", None, 405),
            ("POST", THINGS, body, 405),
            ("POST", f"{THINGS}/{tid('w-12')}/inbox/messages/command?timeout=0", body, 404),
            ("POST", f"{THINGS}/{tid('shift')}/inbox/messages/other?timeout=0", body, 404),
            ("GET", f"{THINGS}/{tid('shift')}/inbox/messages/command?timeout=0", None, 405),
        ]
        for method, path, data, status in cases:
            with self.subTest(method=method, path=path):
                r = fast.request(method, path, data, headers if data else None)
                self.assertEqual(r.status, status)
                self.assertEqual(r.json()["status"], status)
        refused = [e for e in fast.log() if e["kind"] == "ditto" and e["allowed"] is False]
        self.assertEqual([(e["method"], e["path"], e["status"]) for e in refused],
                         [(m, p, s) for m, p, _, s in cases])
        self.assertEqual(val(element(fast.features(), "w-12"), "passability"), "open")
        allowed = [e for e in fast.log() if e["kind"] == "ditto" and e["allowed"]]
        self.assertTrue(allowed and all(e["status"] == 200 for e in allowed))

    def test_faults_affect_only_ditto(self):
        fast = SERVERS["fast"].scenario("normal")
        self.addCleanup(fast.fault, "none")
        for mode, status in (("http_502", 502), ("http_503", 503)):
            fast.fault(mode)
            self.assertEqual(fast.get(SHIFT).status, status)
            self.assertEqual(fast.get(MINE).status, status)
            r, _ = fast.command("action.stop_zone", "zone-a")
            self.assertEqual(r.status, status)
            self.assertEqual(fast.get("/").status, 200)
            self.assertEqual(fast.state()["fault"], mode)
        fast.fault("drop")
        with self.assertRaises(OSError):
            fast.get(SHIFT, timeout=3)
        fast.fault("hang")
        started = time.monotonic()
        with self.assertRaises(OSError):
            fast.get(SHIFT, timeout=0.7)
        self.assertGreaterEqual(time.monotonic() - started, 0.6)
        self.assertEqual(fast.get("/__mock__/state").status, 200)
        fast.fault("none")
        self.assertEqual(fast.get(SHIFT).status, 200)
        faults = [e.get("fault") for e in fast.log() if e["kind"] == "ditto" and "fault" in e]
        self.assertEqual(faults, ["http_502"] * 3 + ["http_503"] * 3 + ["drop", "hang"])
        self.assertFalse([e for e in fast.log() if e["kind"] == "command"])
        self.assertEqual(fast.post_json("/__mock__/fault", {"mode": "explode"}).status, 400)
        # a new scenario starts without a fault
        fast.fault("http_502")
        fast.scenario("normal")
        self.assertEqual(fast.get(SHIFT).status, 200)

    def test_control_api_and_page(self):
        fast = SERVERS["fast"].scenario("detour")
        listing = fast.get("/__mock__/scenarios").json()
        self.assertEqual(sorted(s["name"] for s in listing["scenarios"]), sorted(SCENARIOS))
        self.assertTrue(all(s["description"] for s in listing["scenarios"]))
        self.assertEqual(listing["current"], "detour")
        state = fast.state()
        self.assertEqual((state["scenario"], state["state"], state["run"], state["interval_ms"]),
                         ("detour", "initial", "run-0005", 100))
        self.assertEqual(fast.post_json("/__mock__/scenario", {"name": "nope"}).status, 404)
        self.assertEqual(fast.post_json("/__mock__/scenario", {"name": "../x"}).status, 404)
        page = fast.get("/__mock__/")
        self.assertTrue(page.headers["Content-Type"].startswith("text/html"))
        html = page.body.decode("utf-8")
        self.assertIn("Тестовый инструмент", html)
        self.assertIn("придуманы для тестов", html)
        self.assertIn('href="/"', html)
        for name in SCENARIOS:
            self.assertIn(f'data-scenario="{name}"', html)
        for mode in ("none", "http_502", "http_503", "hang", "drop"):
            self.assertIn(f'data-fault="{mode}"', html)
        # restarting the scenario starts again from the first frame with an empty log
        fast.command("condition.close_working", "w-12")
        fast.wait_state("decision")
        fast.scenario("detour")
        self.assertEqual(fast.state()["state"], "initial")
        self.assertEqual([e for e in fast.log() if e["kind"] == "command"], [])

    def test_static_files_and_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "public"
            (root / "js").mkdir(parents=True)
            (root / "index.html").write_bytes(b"<!doctype html><title>t</title>")
            (root / "js" / "main.js").write_bytes(b"export const x = 1;\n")
            (root / "base.css").write_bytes(b"body{}\n")
            (root / "icon.svg").write_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'/>")
            (root / "data.json").write_bytes(b"{}")
            (Path(tmp) / "secret.txt").write_bytes(b"secret")
            mock = Mock(public_dir=root)
            self.addCleanup(mock.stop)
            expected = {"/": "text/html", "/index.html": "text/html",
                        "/js/main.js": "text/javascript", "/base.css": "text/css",
                        "/icon.svg": "image/svg+xml", "/data.json": "application/json"}
            for path, mime in expected.items():
                r = mock.get(path)
                self.assertEqual(r.status, 200, path)
                self.assertTrue(r.headers["Content-Type"].startswith(mime), path)
                self.assertEqual(r.headers["Cache-Control"], "no-store")
                self.assertIsNotNone(parse_date(r.headers["Date"]))
            self.assertEqual(mock.get("/js/main.js").body, b"export const x = 1;\n")
            for path in ("/js", "/js/", "/missing.js"):
                r = mock.get(path)
                self.assertEqual(r.status, 404, path)          # no directory listing
                self.assertNotIn(b"main.js", r.body)
            for path in ("/../secret.txt", "/js/../../secret.txt", "/%2e%2e/secret.txt",
                         "/..%2fsecret.txt", "/js/..%5c..%5csecret.txt", "/./index.html"):
                connection = http.client.HTTPConnection("127.0.0.1", mock.port, timeout=5)
                connection.request("GET", path)       # http.client sends the path as written
                r = connection.getresponse()
                body = r.read()
                connection.close()
                self.assertIn(r.status, (403, 404), path)
                self.assertNotIn(b"secret", body, path)
            self.assertEqual(mock.request("POST", "/index.html", b"x").status, 405)
            # the default directory is team/ui/public
        r = SERVERS["fast"].get("/")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.headers["Content-Type"].startswith("text/html"))
        self.assertEqual(r.body, (UI_DIR / "public" / "index.html").read_bytes())

    def test_listening_line_and_exit_on_terminate(self):
        mock = Mock(scenario="paused_heartbeat")
        self.addCleanup(mock.stop)
        self.assertRegex(mock.first_line, r"^LISTENING http://127\.0\.0\.1:\d+$")
        self.assertEqual(mock.state()["scenario"], "paused_heartbeat")
        # an open hanging request must not keep the process alive
        mock.fault("hang")
        hanging = threading.Thread(target=lambda: self.assertRaises(OSError, mock.get, SHIFT, 8),
                                   daemon=True)
        hanging.start()
        time.sleep(0.3)
        mock.process.terminate()
        self.assertIsNotNone(mock.process.wait(10))
        hanging.join(10)
        with self.assertRaises(OSError):
            mock.get("/__mock__/state", timeout=2)
        bad = subprocess.run([sys.executable, str(SERVER), "--port", "0", "--scenario", "nope"],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(bad.returncode, 2)
        self.assertNotIn("LISTENING", bad.stdout)

    def test_interrupt_signal_shuts_down_cleanly(self):
        windows = sys.platform == "win32"
        mock = Mock(flags=subprocess.CREATE_NEW_PROCESS_GROUP if windows else 0)
        self.addCleanup(mock.stop)
        try:
            mock.process.send_signal(signal.CTRL_BREAK_EVENT if windows else signal.SIGINT)
        except OSError as error:
            self.skipTest(f"cannot send an interrupt to the child process here: {error}")
        try:
            code = mock.process.wait(10)
        except subprocess.TimeoutExpired:
            if windows:
                self.skipTest("no console to deliver CTRL_BREAK_EVENT to the child process")
            raise
        self.assertEqual(code, 0)
        self.assertEqual(mock.process.stderr.read(), "")


if __name__ == "__main__":
    unittest.main()
