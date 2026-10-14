"""The core of the interface against the mock server: boot, polling, link states,
snapshot validity, commands, routes and the shell.

The page under test is the production static served by the mock; nothing in it
is switched for the test. State is read from the DOM contract (`<body>` data
attributes, `data-testid` elements, row attributes) and, where the views of the
other agents are still stubs, from the store of the running application.

    python -m unittest discover -s team/ui/tests -t team/ui -p "test_core.py" -v
"""

from __future__ import annotations

import os
import re
import time

from browser_support import OUTPUT_DIR, BrowserTestCase, MockServer, wait_until

NS = "team040.mine"
NBSP = "\u00a0"
SHIFT_PATH = f"/ditto/api/2/things/{NS}:shift?fields=thingId,features,_modified,_revision"
MINE_PATH = f"/ditto/api/2/things/{NS}:mine?fields=thingId,attributes"
COMMAND_PATH = f"/ditto/api/2/things/{NS}:shift/inbox/messages/command?timeout=0"

# The running application, reached the way a view module reaches it.
APP = "const {app} = await import('/js/main.js'); const state = app.store.getState();"

HAZARDS = ("normal", "attention", "danger", "unknown")


def plain(text):
    return text.replace(NBSP, " ") if isinstance(text, str) else text


def expected_row_attributes(kind, features):
    """The state attributes of a drawn twin (implementation spec, section 5) from raw Ditto features."""
    def value(name):
        feature = features.get(name)
        return feature["properties"]["value"] if feature else None

    expected = {}
    if kind in ("working", "zone"):
        hazard = value("hazard_state")
        if hazard not in HAZARDS or (hazard == "normal" and value("data_quality") != "fresh"):
            hazard = "unknown"
        expected.update(hazard=hazard, quality=value("data_quality"), lastKnownHazard=value("last_known_hazard_state"))
    if kind == "working":
        expected.update(passability=value("passability"), restriction=value("routing_restriction"))
    elif kind == "zone":
        expected.update(workState=value("work_state"), withdrawal=value("withdrawal_state"))
    elif kind == "sensor":
        expected.update(quality=value("quality"), link=value("link_state"))
    elif kind == "worker":
        expected.update(status=value("status"), egress=value("egress_status"),
                        locationHazard=value("location_hazard"), posQuality=value("pos_quality"))
    elif kind == "exit":
        expected.update(state=value("state"))
    return expected


class CoreTestCase(BrowserTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock = MockServer("normal").start()
        cls.addClassCleanup(cls.mock.stop)

    # ---- helpers ---------------------------------------------------------

    def open(self, scenario, route=""):
        """Restart the scenario from its first frame and load the page as a new document."""
        self.mock.scenario(scenario)
        # Navigating to the URL the tab already shows (or to another fragment of it) would keep the running page.
        self.page.goto("about:blank")
        self.page.goto(self.mock.url + "/" + route)

    def js(self, body, timeout=20.0):
        return self.page.evaluate("(async () => {" + body + "})()", timeout=timeout)

    def body(self):
        return self.page.evaluate("Object.assign({}, document.body.dataset)")

    def wait_body(self, timeout=10.0, **expected):
        """Wait until every given `<body>` data attribute has its value (camelCase names of `dataset`)."""
        condition = " && ".join(f"document.body.dataset.{name} === {value!r}" for name, value in expected.items())
        try:
            self.page.wait_for(condition, timeout=timeout)
        except AssertionError as error:
            raise AssertionError(f"{error}\nbody: {self.body()}\nbanners: {self.banners()}") from None
        return self.body()

    def wait_ready(self, timeout=10.0):
        return self.wait_body(timeout, boot="ready", snapshot="ok", link="ok")

    def banners(self):
        return self.page.evaluate("""[...document.querySelectorAll('[data-testid="overlay-banner"]')].map((node) => ({
          code: node.dataset.code, severity: node.dataset.severity, reason: node.dataset.reason || null,
          text: node.textContent.replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim(),
        }))""")

    def banner_codes(self):
        return [banner["code"] for banner in self.banners()]

    def wait_banner(self, code, timeout=10.0):
        self.page.wait_for(f"document.querySelector('[data-testid=\"overlay-banner\"][data-code=\"{code}\"]')",
                           timeout=timeout, message=f"banner {code}")
        return next(banner for banner in self.banners() if banner["code"] == code)

    def text_of(self, test_id):
        return plain(self.page.evaluate(
            f"document.querySelector('[data-testid=\"{test_id}\"]').textContent.replace(/\\s+/g, ' ').trim()"))

    def rows(self):
        return self.page.evaluate("""[...document.querySelectorAll('[data-testid="list"] tbody tr')].map((row) => ({
          ...row.dataset, text: row.textContent.replace(/\\u00a0/g, ' '), selected: row.getAttribute('aria-selected'),
        }))""")

    def platform_log(self):
        """Requests of the page to the platform paths, as the mock recorded them."""
        return [entry for entry in self.mock.log()["entries"] if entry["kind"] in ("ditto", "command")]

    def commands_logged(self, command_id=None):
        return [entry for entry in self.platform_log() if entry["kind"] == "command"
                and (command_id is None or (entry.get("body") or {}).get("command_id") == command_id)]

    def assert_only_platform_calls_of_the_contract(self):
        entries = self.platform_log()
        self.assertTrue(entries, "the page read the platform")
        for entry in entries:
            self.assertTrue(entry["allowed"], f"a request outside the contract: {entry['method']} {entry['path']}")
            if entry["kind"] == "command":
                self.assertEqual((entry["method"], entry["path"]), ("POST", COMMAND_PATH))
                continue
            self.assertEqual(entry["method"], "GET")
            path = entry["path"]
            if path in (MINE_PATH, SHIFT_PATH):
                continue
            match = re.fullmatch(r"/ditto/api/2/things\?ids=([^&]+)&fields=(thingId,attributes(?:,features)?)", path)
            self.assertIsNotNone(match, f"unexpected platform read: {path}")
            ids = match.group(1).split(",")
            self.assertLessEqual(len(ids), 20, "a batch holds at most 20 ids")
            self.assertTrue(all(thing_id.startswith(NS + ":") for thing_id in ids))
        origin = self.mock.url + "/"
        for request in list(self.page.requests):
            # A data: URL is an image the page drew itself, not a request to any server.
            if request["url"].startswith("data:"):
                continue
            self.assertTrue(request["url"].startswith(origin), f"request outside the origin: {request['url']}")
            self.assertNotIn("/__mock__/", request["url"], "production code never calls the control API")

    def phase(self, command_id):
        return self.js(APP + f"const entry = state.pending.find((item) => item.id === {command_id!r});"
                             "return entry ? entry.phase : null;")

    def wait_phase(self, command_id, phase, timeout=8.0):
        try:
            self.page.wait_for(
                "(async () => { const {app} = await import('/js/main.js');"
                f" const entry = app.store.getState().pending.find((item) => item.id === {command_id!r});"
                f" return !!entry && entry.phase === {phase!r}; }})()",
                timeout=timeout, message=f"command {command_id} in phase {phase}")
        except AssertionError as error:
            raise AssertionError(f"{error}\nphase now: {self.phase(command_id)}\nbody: {self.body()}") from None

    def record_phases(self):
        """Keep the phase history of every pending command in `window.__phases`."""
        self.js(APP + """
          window.__phases = {};
          app.store.watch((s) => s.pending, (pending) => {
            for (const entry of pending) {
              const history = window.__phases[entry.id] = window.__phases[entry.id] || [];
              if (history[history.length - 1] !== entry.phase) history.push(entry.phase);
            }
          });
        """)


class BootAndListTest(CoreTestCase):
    def test_normal_boots_polls_and_calls_only_the_contract(self):
        self.page.add_init_script("""
          window.__raf = 0;
          const raf = window.requestAnimationFrame;
          window.requestAnimationFrame = function (callback) { window.__raf += 1; return raf.call(window, callback); };
          window.__canvas = 0;
          const getContext = HTMLCanvasElement.prototype.getContext;
          HTMLCanvasElement.prototype.getContext = function (...args) { window.__canvas += 1; return getContext.apply(this, args); };
        """)
        # The SVG scheme mode of the stage: the 3D stage draws its boot frames and creates its WebGL contexts by
        # design, and its own idle rule (no frame while nothing changes) is checked in test_scene3d.py.
        self.open("normal", "#/scheme?mode=scheme")
        first = self.wait_ready()
        self.assertEqual(first["run"], "run-0005")
        self.assertEqual(first["runState"], "running")
        self.assertEqual(first["commands"], "enabled")
        self.assertEqual(first["view"], "scheme")
        self.assertRegex(first["tick"], r"^\d+$")
        self.assertRegex(first["seq"], r"^\d+$")
        self.wait_body(publications="alive")
        self.page.wait_for(f"Number(document.body.dataset.seq) >= {int(first['seq']) + 3}", timeout=8.0)
        later = self.body()
        self.assertEqual(int(later["tick"]) - int(first["tick"]), 10 * (int(later["seq"]) - int(first["seq"])),
                         "tick and publication_seq advance together, as published")
        self.assertEqual(self.banner_codes(), [])
        self.assertTrue(self.page.evaluate("document.getElementById('old-data').hidden"))

        self.assertEqual(self.text_of("status-notice"), "Синтетические данные. Расчёт модели, не сведения о реальной шахте")
        self.assertEqual(self.text_of("status-link"), "Платформа: связь есть")
        self.assertRegex(self.text_of("status-age"), r"^данные [01] с назад$")
        # Time, not ticks (clarity pass, A8); the tick and the seed are in the titles (A7).
        self.assertRegex(self.text_of("status-model-time"), r"^Модель \d\d:\d\d:\d\d · ×10 · модель идёт$")
        self.assertRegex(self.page.evaluate("document.querySelector('[data-testid=\"status-model-time\"]').title"), r"^Время модели; тик\s\d+$")
        self.assertEqual(self.text_of("status-run"), "Прогон run-0005")
        self.assertEqual(self.page.evaluate("document.querySelector('[data-testid=\"status-run\"]').title"), "Прогон run-0005; seed 42")
        self.assertEqual(self.text_of("status-conditions"), "Условия стенда: нет")
        self.assertTrue(self.page.evaluate("document.querySelector('[data-testid=\"status-commands\"]').hidden"))
        strip = self.page.evaluate("Object.assign({}, document.querySelector('[data-testid=\"incident-strip\"]').dataset)")
        self.assertEqual(strip["incidentState"], "none")
        self.assertIn("Инцидентов нет", self.text_of("incident-strip"))
        self.assertEqual([self.text_of(f"incident-{name}") for name in ("in-danger", "no-route", "unknown", "total")],
                         ["0", "0", "0", "14"])

        # Mount points of the other views exist and are empty or filled by their owners; the shell is complete.
        for test_id in ("scheme", "legend", "list", "card", "conditions-panel", "actions-panel", "decision-panel",
                        "journal", "tab-scheme", "tab-list", "tab-runs"):
            self.assertEqual(self.page.evaluate(f"document.querySelectorAll('[data-testid=\"{test_id}\"]').length"), 1, test_id)

        self.assertEqual(self.page.evaluate("document.querySelector('#stage').dataset.stageMode"), "scheme")
        self.assertEqual(self.page.evaluate("[window.__raf, window.__canvas]"), [0, 0],
                         "in the scheme mode: no animation loop and no canvas while data only tick")

        self.assert_only_platform_calls_of_the_contract()
        entries = self.platform_log()
        self.assertEqual(entries[0]["path"], MINE_PATH, "the mine is read first")
        batches = [entry["path"] for entry in entries if entry["path"].endswith("&fields=thingId,attributes")]
        sizes = [len(path.split("ids=")[1].split("&")[0].split(",")) for path in batches]
        self.assertEqual(sizes, [20, 20, 20, 17], "the manifest of 77 twins is read once, in four batches")
        archive = [entry["path"] for entry in entries if entry["path"].endswith("&fields=thingId,attributes,features")]
        self.assertEqual(archive, [f"/ditto/api/2/things?ids={','.join(f'{NS}:run-000{n}' for n in (1, 2, 3, 4))}"
                                   "&fields=thingId,attributes,features"])
        polls = [entry["t_ms"] for entry in entries if entry["path"] == SHIFT_PATH]
        self.assertGreaterEqual(len(polls), 4)
        gaps = [later_ms - earlier_ms for earlier_ms, later_ms in zip(polls, polls[1:])]
        self.assertGreaterEqual(min(gaps), 900, f"one poll per second, never faster: {gaps}")
        self.assertFalse([entry for entry in entries if entry["kind"] == "command"], "nothing is sent without the user")

        archive_state = self.js(APP + "return [state.archive.status, state.archive.ids, state.archive.runs.map((run) => "
                                      "[run.name, run.values.completion_reason, run.values.comparable, run.units.downtime_s])];")
        self.assertEqual(archive_state[0], "ready")
        self.assertEqual(archive_state[1], ["run-0001", "run-0002", "run-0003", "run-0004"])
        self.assertEqual(archive_state[2][2], ["run-0003", "reset", True, "zone*s"])

    def test_list_shows_every_twin_with_its_state(self):
        for scenario in ("normal", "sensor_lost_after_danger", "unknown_enum"):
            with self.subTest(scenario=scenario):
                self.open(scenario, "#/list")
                self.wait_ready()
                self.assertEqual(self.body()["view"], "list")
                mine = self.mock.request("GET", MINE_PATH)["attributes"]
                attributes = {}
                for start in range(0, len(mine["manifest"]), 20):
                    ids = ",".join(mine["manifest"][start:start + 20])
                    for thing in self.mock.request("GET", f"/ditto/api/2/things?ids={ids}&fields=thingId,attributes"):
                        attributes[thing["thingId"]] = thing["attributes"]
                shift = self.mock.request("GET", SHIFT_PATH)
                scene = {item["thingId"]: item["features"] for item in shift["features"]["scene"]["properties"]["value"]}
                rows = {row["thingId"]: row for row in self.rows()}
                self.assertEqual(len(rows), len(self.rows()), "one row per twin")
                self.assertTrue(set(mine["dynamic_ids"]) <= set(rows), "every dynamic twin has a row")
                levels = {thing_id for thing_id, attrs in attributes.items() if attrs["kind"] == "level"}
                self.assertEqual(set(rows), set(mine["dynamic_ids"]) | levels)
                for thing_id in mine["dynamic_ids"]:
                    row = rows[thing_id]
                    kind = attributes[thing_id]["kind"]
                    self.assertEqual(row["kind"], kind, thing_id)
                    self.assertIn(attributes[thing_id]["label"], row["text"], thing_id)
                    for name, value in expected_row_attributes(kind, scene[thing_id]).items():
                        self.assertEqual(row.get(name), value, f"{thing_id} data-{name}")
                self.assertEqual(self.text_of("list-count"), f"Показано: {len(rows)} объектов")

        # Unknown codes of the last scenario read as unknown, never as a normal state.
        zone_a = rows[f"{NS}:zone-a"]
        self.assertEqual(zone_a["hazard"], "unknown")
        self.assertIn("состояние неизвестно (код elevated)", zone_a["text"])
        self.assertIn("неизвестно (resting)", rows[f"{NS}:worker-09"]["text"])
        self.assertIn("shelter", rows[f"{NS}:option-observe"]["text"])

    def test_list_texts_keep_the_three_axes_apart(self):
        self.open("sensor_lost_after_danger", "#/list")
        self.wait_ready()
        rows = {row["thingId"]: row for row in self.rows()}
        cells = self.page.evaluate(f"""[...document.querySelector('[data-testid="list"] tr[data-thing-id="{NS}:zone-c"]').cells]
          .map((cell) => cell.textContent.replace(/\\u00a0/g, ' '))""")
        self.assertEqual(cells[0], "участок")
        self.assertEqual(cells[1], "Участок В")
        # The moment of the last assessment by the model clock with its age (clarity pass, A8); the tick is in the title.
        self.assertRegex(cells[3], r"^состояние неизвестнопоследнее известное: опасно в 00:13:30 \(\d+ мин назад\)$",
                         "the last known danger stays visible after the sensor is lost")
        marks = self.page.evaluate(f"""[...document.querySelector('[data-testid="list"] tr[data-thing-id="{NS}:zone-c"]')
          .cells[3].children].map((node) => [node.className, node.hidden])""")
        self.assertEqual(marks, [["cell badge badge--unknown", False], ["cell-note badge badge--danger", False]],
                         "unknown now and danger before are two separate marks")
        self.assertEqual(cells[4], "данные потеряны")
        self.assertIn("новый вход запрещён моделью", cells[5])
        self.assertRegex(cells[7], r"^\d\d:\d\d:\d\d$")
        self.assertRegex(cells[8], r"^\d\d:\d\d:\d\d UTC$")
        sensor = rows[f"{NS}:sens-ext-05"]["text"]
        self.assertIn("данные потеряны; нет связи", sensor)
        self.assertIn("измерено", sensor)
        # A working without sensors: «состояние неизвестно» in the hazard cell and the short «без датчиков» in the
        # knowledge cell (the row stays one line high); the full sentence is the title of the cell and is in the card.
        bare = self.page.evaluate(f"""(() => {{
          const cells = document.querySelector('[data-testid="list"] tr[data-thing-id="{NS}:w-01"]').cells;
          return [cells[3].textContent, cells[4].textContent, cells[4].firstElementChild.title];
        }})()""")
        self.assertEqual(bare, ["состояние неизвестно", "без датчиков", "без датчиков, состояние не оценивается"])
        worker = rows[f"{NS}:worker-07"]["text"]
        self.assertIn("участок: состояние неизвестно", worker)
        self.assertIn("расчётный маршрут (модель)", worker)
        headers = self.page.evaluate("[...document.querySelectorAll('[data-testid=\"list\"] th')].map((th) => th.textContent)")
        self.assertEqual(headers, ["Тип", "Код", "Место", "Опасность", "Знание", "Достижимость", "Значение и состояние",
                                   "Время модели", "Время платформы"])

    def test_list_filter_selection_and_focus_survive_polling(self):
        self.open("normal", "#/list")
        self.wait_ready()
        self.page.evaluate("""(() => {
          const select = document.querySelector('[data-testid="list-type"]');
          select.value = 'worker';
          select.dispatchEvent(new Event('change', {bubbles: true}));
        })()""")
        self.page.wait_for("location.hash === '#/list?type=worker'")
        rows = self.rows()
        self.assertEqual(len(rows), 14)
        self.assertEqual({row["kind"] for row in rows}, {"worker"})
        self.assertTrue(all(row["selected"] == "false" for row in rows))

        target = f"{NS}:worker-07"
        self.page.evaluate(f"document.querySelector('[data-testid=\"list\"] tr[data-thing-id=\"{target}\"]').focus()")
        self.page.press("Enter")
        self.page.wait_for(f"location.hash === '#/list?type=worker&sel={target}'")
        selected = [row for row in self.rows() if row["selected"] == "true"]
        self.assertEqual([row["thingId"] for row in selected], [target])
        self.assertIn("(выбран)", selected[0]["text"])

        # Two more polls re-render the rows: focus, selection and the <select> stay where they are.
        seq = int(self.body()["seq"])
        self.page.wait_for(f"Number(document.body.dataset.seq) >= {seq + 2}", timeout=6.0)
        self.assertEqual(self.page.focus_info()["dataset"].get("thingId"), target)
        self.assertEqual(self.page.evaluate("document.querySelector('[data-testid=\"list-type\"]').value"), "worker")

        other = f"{NS}:worker-03"
        self.page.evaluate(f"document.querySelector('[data-testid=\"list\"] tr[data-thing-id=\"{other}\"]').focus()")
        self.page.press("Space")
        self.page.wait_for(f"location.hash === '#/list?type=worker&sel={other}'")
        self.page.click(f'[data-testid="list"] tr[data-thing-id="{target}"]')
        self.page.wait_for(f"location.hash === '#/list?type=worker&sel={target}'")
        self.assertEqual(self.js(APP + "return state.ui.selected;"), target)
        self.assertFalse(self.commands_logged(), "selecting an object sends nothing")


class SnapshotValidityTest(CoreTestCase):
    INVALID = {
        "invalid_missing_id": ("scene_missing_id", "worker-14"),
        "invalid_duplicate_id": ("scene_duplicate_id", "worker-14"),
        "invalid_mixed_tick": ("scene_mixed_tick", "sens-geo-02"),
        "invalid_missing_field": ("missing_field", "egress_status"),
        "invalid_contract_version": ("contract_version", "версия контракта данных 2"),
        "invalid_no_metadata": ("no_metadata", "_modified"),
    }

    def test_invalid_snapshot_keeps_the_last_full_one_and_blocks_commands(self):
        for scenario, (reason, fragment) in self.INVALID.items():
            with self.subTest(scenario=scenario):
                self.open(scenario, "#/list?type=worker")
                self.wait_ready()
                invalid = self.wait_body(8.0, snapshot="invalid")
                self.assertEqual(invalid["commands"], "blocked")
                self.assertEqual(invalid["blockReason"], "snapshot_invalid")
                self.assertEqual(invalid["snapshotReason"], reason)
                banner = self.wait_banner("snapshot_invalid", 2.0)
                self.assertEqual(banner["reason"], reason)
                self.assertEqual(banner["severity"], "danger")
                self.assertTrue(banner["text"].startswith("Состояние не принято: "), banner["text"])
                self.assertIn(fragment, banner["text"])
                self.assertRegex(banner["text"], r"Показан последний полный снимок: \d\d:\d\d:\d\d UTC, тик \d+\. Команды заблокированы")

                # The model goes on publishing; the screen stays on the last full snapshot.
                stale = self.wait_body(4.0, link="stale", snapshot="invalid")
                self.assertEqual((stale["tick"], stale["seq"], stale["run"]), (invalid["tick"], invalid["seq"], invalid["run"]))
                self.assertGreater(self.mock.state()["tick"], int(stale["tick"]))
                self.assertIn(f"тик {stale['tick']}", banner["text"])
                rows = self.rows()
                self.assertEqual(len(rows), 14)
                self.assertTrue(all(row.get("egress") == "ok" for row in rows), "rows still show the last full snapshot")
                self.assertRegex(plain(self.page.evaluate("document.getElementById('old-data').textContent")),
                                 rf"^Показаны данные на \d\d:\d\d:\d\d UTC, тик {stale['tick']}\. Текущее состояние неизвестно$")
                self.assertFalse(self.page.evaluate("document.getElementById('old-data').hidden"))
                self.assertEqual(self.body()["oldData"], "true")
                self.assertEqual(self.body()["publications"], "alive", "the heartbeat is still read from a rejected answer")
                self.assertNotIn("stale", self.banner_codes(), "one banner names the cause; the stale one would repeat it")
                self.assertIn("Команды заблокированы", self.text_of("status-commands"))
                result = self.js(APP + "return app.ctx.sendCommand('action.stop_zone', 'zone-b');")
                self.assertEqual((result["ok"], result["reason"]), (False, "blocked"))
                self.assertFalse(self.commands_logged(), "a blocked command never reaches the platform")

    def test_topology_mismatch_blocks_and_rereads_attributes_slowly(self):
        self.open("topology_mismatch", "#/list?type=zone")
        state = self.wait_body(8.0, boot="ready", snapshot="invalid")
        self.assertEqual(state["commands"], "blocked")
        self.assertEqual(state["snapshotReason"], "topology_mismatch")
        self.assertNotIn("run", state, "no state of the model is shown as current")
        banner = self.wait_banner("topology_mismatch", 2.0)
        self.assertTrue(banner["text"].startswith(
            "Схема не показана: версия топологии в двойниках (t1) не совпадает с версией модели (t2)."), banner["text"])
        self.assertEqual(banner["reason"], "topology_mismatch")
        self.assertNotIn("snapshot_invalid", self.banner_codes())
        rows = self.rows()
        self.assertEqual(len(rows), 4, "the list stays available from the attributes")
        self.assertTrue(all(row["hazard"] == "unknown" and "workState" not in row for row in rows),
                        "without a full snapshot no zone is shown in any published state")
        self.assertTrue(all("состояние не получено" in row["text"] for row in rows))
        self.assertEqual([self.text_of(f"incident-{name}") for name in ("in-danger", "no-route", "unknown", "total")],
                         ["—", "—", "—", "—"])
        time.sleep(6.5)
        mine_reads = [entry["t_ms"] for entry in self.platform_log() if entry["path"] == MINE_PATH]
        self.assertIn(len(mine_reads), (2, 3), f"attributes are re-read on a mismatch, at most once per 5 s: {mine_reads}")
        self.assertTrue(all(later - earlier >= 4900 for earlier, later in zip(mine_reads, mine_reads[1:])), mine_reads)
        self.assertEqual(self.body()["snapshot"], "invalid")
        self.assert_only_platform_calls_of_the_contract()

    def test_topology_change_recovers_without_reload(self):
        self.open("topology_change", "#/list?type=working")
        self.wait_ready()
        self.page.evaluate("window.__marker = 'same document'")
        self.assertEqual(len(self.rows()), 36)
        before = self.js(APP + "return [state.attributes.topologyVersion, state.attributes.things['team040.mine:w-19'].length_m];")
        self.assertEqual(before, ["t1", 90])
        self.wait_banner("topology_mismatch", 8.0)
        mismatch = self.body()
        self.assertEqual((mismatch["snapshot"], mismatch["commands"]), ("invalid", "blocked"))
        # Until the new attributes are read, the screen keeps the old topology with its own states.
        self.assertEqual(self.js(APP + "return [state.attributes.topologyVersion, state.snapshot.topologyVersion];"), ["t1", "t1"])
        self.wait_body(12.0, snapshot="ok", link="ok", commands="enabled")
        after = self.js(APP + """return [state.attributes.topologyVersion, state.snapshot.topologyVersion,
          state.attributes.things['team040.mine:w-19'].length_m, state.attributes.manifest.length,
          Object.keys(state.snapshot.scene).length, 'n-32' in state.attributes.mine.nodes];""")
        self.assertEqual(after, ["t2", "t2", 110, 78, 73, True])
        self.assertEqual(self.banner_codes(), [])
        rows = {row["thingId"] for row in self.rows()}
        self.assertEqual(len(rows), 37)
        self.assertIn(f"{NS}:w-37", rows)
        self.assertEqual(self.page.evaluate("window.__marker"), "same document")
        self.assert_only_platform_calls_of_the_contract()


class LinkStatesTest(CoreTestCase):
    WATCH_LINK = """(() => {
      window.__link = [];
      new MutationObserver(() => {
        const value = document.body.dataset.link;
        const last = window.__link[window.__link.length - 1];
        if (!last || last[0] !== value) window.__link.push([value, Math.round(performance.now())]);
      }).observe(document.body, {attributes: true, attributeFilter: ['data-link']});
      window.__marker = 'same document';
      return Math.round(performance.now());
    })()"""

    def test_paused_model_with_heartbeat_is_a_normal_state(self):
        self.open("paused_heartbeat")
        first = self.wait_ready()
        self.assertEqual(first["runState"], "paused")
        banner = self.wait_banner("paused_decision", 3.0)
        self.assertTrue(banner["text"].startswith("Модель на паузе для выбора действия."), banner["text"])
        self.assertEqual(banner["severity"], "info")
        time.sleep(6.5)
        later = self.body()
        self.assertEqual(later["tick"], first["tick"], "model time stands still")
        self.assertGreaterEqual(int(later["seq"]) - int(first["seq"]), 5, "the heartbeat goes on")
        self.assertEqual((later["publications"], later["link"], later["commands"]), ("alive", "ok", "enabled"))
        self.assertEqual(self.banner_codes(), ["paused_decision"])
        self.assertIn("модель на паузе для выбора действия", self.text_of("status-model-time"))
        self.assertEqual(self.text_of("status-conditions"), "Условия стенда: В-12 закрыта")
        strip = self.page.evaluate("document.querySelector('[data-testid=\"incident-strip\"]').dataset.incidentState")
        self.assertEqual(strip, "active")
        # Step 1 says the zone and what happened to it (clarity pass, A4); the state word is in its title.
        self.assertIn("Участок Б — закрыт проход В-12", self.text_of("incident-strip"))
        self.assertEqual(self.page.evaluate("document.body.dataset.dock"), "collapsed",
                         "an active incident brings the decision dock; at 1280x720 it shows its bar over the stage")

    def test_frozen_sequence_is_reported_after_five_seconds(self):
        self.open("frozen_seq")
        self.wait_ready()
        started = time.monotonic()
        banner = self.wait_banner("publications_stopped", 12.0)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 4.5, "a sequence that just stopped is not reported at once")
        self.assertTrue(banner["text"].startswith("Публикации модели остановились."), banner["text"])
        self.assertIn("Команды заблокированы", banner["text"])
        state = self.body()
        self.assertEqual((state["link"], state["snapshot"], state["publications"], state["commands"], state["blockReason"]),
                         ("ok", "ok", "stopped", "blocked", "publications_stopped"))
        self.assertEqual(state["oldData"], "true")
        self.assertEqual(self.text_of("status-publications"), "публикации остановились")
        self.assertRegex(self.text_of("status-age"), r"^данные [5-9] с назад$")
        self.assertEqual(self.banner_codes(), ["publications_stopped"])

    def test_old_frozen_sequence_is_reported_immediately(self):
        self.open("frozen_seq_old")
        self.wait_body(boot="ready")
        started = time.monotonic()
        banner = self.wait_banner("publications_stopped", 1.5)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertTrue(banner["text"].startswith("Публикации модели остановились."))
        state = self.body()
        self.assertEqual((state["publications"], state["commands"]), ("stopped", "blocked"))
        age = re.fullmatch(r"данные (\d+) с назад", self.text_of("status-age"))
        self.assertIsNotNone(age, self.text_of("status-age"))
        self.assertTrue(28 <= int(age.group(1)) <= 33, "the initial age is HTTP Date minus _modified, less the header precision")

    def test_http_502_degrades_then_stale_then_unavailable_and_recovers(self):
        self.open("normal")
        self.wait_ready()
        self.page.evaluate(self.WATCH_LINK)
        seq = int(self.body()["seq"])
        self.page.wait_for(f"Number(document.body.dataset.seq) > {seq}", timeout=4.0)   # a fresh full snapshot
        fault_at = self.page.evaluate("Math.round(performance.now())")
        self.mock.fault("http_502")
        self.wait_body(8.0, link="unavailable")
        seen = self.page.evaluate("window.__link")
        self.assertEqual([name for name, _ in seen], ["degraded", "stale", "unavailable"], seen)
        times = {name: at - fault_at for name, at in seen}
        self.assertLessEqual(times["degraded"], 1400, f"the first failed poll degrades the link: {times}")
        self.assertLessEqual(times["stale"], 2400, f"two seconds without a full snapshot: {times}")
        self.assertGreaterEqual(times["stale"], 900, times)
        self.assertLessEqual(times["unavailable"], 3600, f"three failed polls: {times}")

        state = self.body()
        self.assertEqual((state["commands"], state["blockReason"], state["publications"], state["oldData"]),
                         ("blocked", "platform_unavailable", "unknown", "true"))
        banner = self.wait_banner("platform_unavailable", 2.0)
        self.assertRegex(banner["text"], rf"^Платформа недоступна \(HTTP 502\)\. Показаны данные на \d\d:\d\d:\d\d UTC, "
                                         rf"тик {state['tick']}\. Текущее состояние неизвестно$")
        self.assertEqual(self.banner_codes(), ["platform_unavailable"])
        self.assertEqual(self.text_of("status-link"), "Платформа: недоступна (HTTP 502)")
        self.assertEqual(self.text_of("status-publications"), "публикации: неизвестно")
        self.assertEqual(self.page.evaluate("(() => { const tag = document.querySelector('.old-tag');"
                                            " return [tag.hidden, tag.textContent]; })()"),
                         [False, "последние полученные данные:"], "model time and run in the top bar are marked as old")
        self.assertFalse(self.page.evaluate("document.getElementById('old-data').hidden"))
        frozen = (state["tick"], state["seq"])
        time.sleep(1.2)
        self.assertEqual((self.body()["tick"], self.body()["seq"]), frozen, "nothing moves while the platform is away")

        self.mock.fault("none")
        recovered = self.wait_body(6.0, link="ok", snapshot="ok", commands="enabled")
        self.assertGreater(int(recovered["seq"]), int(frozen[1]))
        self.wait_body(3.0, publications="alive")
        self.assertEqual(self.banner_codes(), [])
        self.assertTrue(self.page.evaluate("document.getElementById('old-data').hidden"))
        self.assertEqual(self.page.evaluate("window.__marker"), "same document", "recovery needs no reload")

    def test_hanging_platform_goes_stale_during_the_pending_fetch(self):
        self.open("normal")
        self.wait_ready()
        self.page.evaluate(self.WATCH_LINK)
        seq = int(self.body()["seq"])
        self.page.wait_for(f"Number(document.body.dataset.seq) > {seq}", timeout=4.0)
        fault_at = self.page.evaluate("Math.round(performance.now())")
        self.mock.fault("hang")
        stale = self.wait_body(4.0, link="stale")
        self.assertEqual((stale["commands"], stale["blockReason"]), ("blocked", "stale"))
        banner = self.wait_banner("stale", 2.0)
        self.assertTrue(banner["text"].startswith("Данные устарели: полного снимка нет дольше 2 с"), banner["text"])
        self.wait_body(12.0, link="unavailable")
        seen = self.page.evaluate("window.__link")
        # The 2 s threshold fires while the first fetch is still pending; its 3 s timeout comes later,
        # so a separate "degraded" moment does not exist for a platform that hangs.
        self.assertEqual([name for name, _ in seen], ["stale", "unavailable"], seen)
        times = {name: at - fault_at for name, at in seen}
        self.assertTrue(900 <= times["stale"] <= 2400, f"stale two seconds after the last full snapshot: {times}")
        self.assertTrue(6500 <= times["unavailable"] <= 10800, f"three timeouts of 3 s: {times}")
        self.assertEqual(self.text_of("status-link"), "Платформа: недоступна (нет ответа за 3 с)")
        self.assertIn("Платформа недоступна (нет ответа за 3 с).", self.wait_banner("platform_unavailable", 2.0)["text"])
        polls = [entry for entry in self.page.requests if entry["url"].endswith(SHIFT_PATH)]
        pending = [entry for entry in polls if not entry["finished"]]
        self.assertLessEqual(len(pending), 1, "polls never overlap")

        self.mock.fault("none")
        self.wait_body(8.0, link="ok", snapshot="ok", commands="enabled")
        self.assertEqual(self.banner_codes(), [])
        self.assertEqual(self.page.evaluate("window.__marker"), "same document")

    def test_empty_stand_is_reported_and_left_when_twins_appear(self):
        self.open("empty")
        state = self.wait_body(8.0, boot="empty")
        self.assertEqual((state["commands"], state["blockReason"], state["link"]), ("blocked", "not_ready", "ok"))
        self.assertNotIn("run", state)
        self.assertEqual(self.banners(), [{
            "code": "empty_stand", "severity": "danger", "reason": None,
            "text": "Двойники рудника не найдены в платформе. Платформа отвечает, объектов в team040.mine нет",
        }])
        self.assertEqual(self.rows(), [], "no demonstration data stand in for the twins")
        self.assertEqual(self.text_of("status-run"), "Прогон: нет данных")
        self.page.evaluate("window.__marker = 'same document'")
        wait_until(lambda: len([entry for entry in self.platform_log() if entry["path"] == MINE_PATH]) >= 2,
                   timeout=6.0, message="the mine is asked for again")
        paths = {entry["path"] for entry in self.platform_log()}
        self.assertEqual(paths, {MINE_PATH}, "an empty stand is only asked for its mine")

        self.mock.scenario("normal")
        ready = self.wait_ready(10.0)
        self.assertEqual(ready["run"], "run-0005")
        self.assertEqual(self.banner_codes(), [])
        self.assertEqual(self.page.evaluate("window.__marker"), "same document")


class CommandsTest(CoreTestCase):
    def test_command_outcomes_without_optimistic_changes(self):
        self.open("commands", "#/list")
        self.wait_ready()
        self.record_phases()
        sent = self.js(APP + """
          const a = app.ctx.sendCommand('condition.close_working', 'w-12');
          const duplicate = app.ctx.sendCommand('condition.close_working', 'w-12');
          const b = app.ctx.sendCommand('condition.close_working', 'w-07');
          const c = app.ctx.sendCommand('action.stop_zone', 'zone-b');
          const d = app.ctx.sendCommand('condition.sensor_lost', 'sens-ext-05');
          return {a, duplicate, b, c, d, pending: app.store.getState().pending.map((entry) => [entry.id, entry.phase, entry.run])};
        """)
        a, b, c, d = (sent[name]["id"] for name in "abcd")
        for name in "abcd":
            self.assertTrue(sent[name]["ok"], sent[name])
            self.assertRegex(sent[name]["id"], r"^c-[0-9a-f]{32}$")
        self.assertEqual(len({a, b, c, d}), 4)
        self.assertEqual(sent["duplicate"], {"ok": False, "reason": "duplicate", "id": a},
                         "the same command for the same target is not sent twice while it is unresolved")
        self.assertEqual(sent["pending"], [[command_id, "sending", "run-0005"] for command_id in (a, b, c, d)])

        # 202 without a record: sent, not confirmed. Nothing about the object changes.
        self.wait_phase(a, "sent", 3.0)
        sent_at = time.monotonic()
        row = next(row for row in self.rows() if row["thingId"] == f"{NS}:w-12")
        self.assertEqual(row["passability"], "open")
        self.assertIn("pending", row, "the target is marked as waiting for a confirmation")
        self.assertIn("команда отправлена, не подтверждена", row["text"])

        # 503: the delivery is unknown; the retry carries the same identifier and body.
        self.wait_phase(c, "delivery_unknown", 3.0)
        failure = self.js(APP + f"return state.pending.find((entry) => entry.id === {c!r}).failure;")
        self.assertEqual(failure, {"kind": "http", "status": 503})
        self.assertEqual(next(row for row in self.rows() if row["thingId"] == f"{NS}:zone-b")["workState"], "working")
        retried = self.js(APP + f"return app.ctx.retryCommand({c!r});")
        self.assertEqual(retried, {"ok": True, "id": c})
        self.wait_phase(c, "applied", 5.0)
        self.page.wait_for(f"document.querySelector('[data-testid=\"list\"] tr[data-thing-id=\"{NS}:zone-b\"]')"
                           ".dataset.workState === 'stopped'", timeout=3.0)
        posts = wait_until(lambda: len(self.commands_logged(c)) == 2 and self.commands_logged(c), timeout=3.0)
        self.assertEqual(posts[0]["body"], posts[1]["body"])
        self.assertEqual(posts[0]["body"], {"command_id": c, "type": "action.stop_zone", "target": "zone-b", "run": "run-0005"})
        self.assertEqual([(post["status"], post["delivered"], post["effect_applied"]) for post in posts],
                         [(503, False, False), (202, True, True)], "exactly one effect")

        # A rejection of the model is shown with its reason and stays until dismissed.
        self.wait_phase(b, "rejected", 4.0)
        rejected = self.js(APP + f"""const entry = state.pending.find((item) => item.id === {b!r});
          return [entry.ack.status, entry.ack.reason, app.ctx.text.pendingText(entry)];""")
        self.assertEqual(rejected, ["rejected", "not_allowed_in_state",
                                    "Команда отклонена: недопустимо в текущем состоянии (not_allowed_in_state)"])
        self.assertEqual(next(row for row in self.rows() if row["thingId"] == f"{NS}:w-07")["passability"], "open")

        # The acknowledgement can arrive while the POST still hangs: the record is the truth.
        self.wait_phase(d, "applied", 4.0)
        self.page.wait_for("document.querySelector('[data-testid=\"status-conditions\"]').textContent.includes('Э-05')", timeout=3.0)
        self.assertEqual(self.text_of("status-conditions"), "Условия стенда: Э-05 без связи")
        self.page.wait_for(f"document.querySelector('[data-testid=\"list\"] tr[data-thing-id=\"{NS}:sens-ext-05\"]')"
                           ".dataset.link === 'offline'", timeout=3.0)

        # No record for 5 s: no acknowledgement, with a retry and a dismissal on offer.
        self.wait_phase(a, "no_ack", 8.0)
        waited = time.monotonic() - sent_at
        self.assertTrue(4.3 <= waited <= 6.8, f"the no-acknowledgement threshold is 5 s, measured {waited:.1f} s")
        self.assertEqual(self.js(APP + f"return app.ctx.text.pendingText(state.pending.find((entry) => entry.id === {a!r}));"),
                         "Нет подтверждения 5 с. Команда могла не дойти")

        # Applied commands leave on their own; the others wait for the user.
        self.page.wait_for("(async () => { const {app} = await import('/js/main.js');"
                           " return app.store.getState().pending.every((entry) => entry.phase !== 'applied'); })()", timeout=8.0)
        self.assertEqual(self.js(APP + "return state.pending.map((entry) => [entry.id, entry.phase]);"),
                         [[a, "no_ack"], [b, "rejected"]])
        history = self.page.evaluate("window.__phases")
        self.assertEqual(history[a], ["sending", "sent", "no_ack"])
        self.assertEqual(history[b], ["sending", "sent", "rejected"])
        self.assertEqual(history[c], ["sending", "delivery_unknown", "sending", "sent", "applied"])
        self.assertEqual(history[d], ["sending", "applied"], "the timeout of the hanging POST no longer matters")
        hung = wait_until(lambda: self.commands_logged(d), timeout=3.0)
        self.assertEqual([(post["status"], post["delivered"], post["effect_applied"]) for post in hung],
                         [("client_disconnected", True, True)])

        # Retry of the unacknowledged command: the same id and body again, and no second effect.
        self.assertEqual(self.js(APP + f"return app.ctx.retryCommand({a!r});"), {"ok": True, "id": a})
        repeats = wait_until(lambda: len(self.commands_logged(a)) == 2 and self.commands_logged(a), timeout=3.0)
        self.assertEqual(repeats[0]["body"], repeats[1]["body"])
        self.assertEqual([(post["duplicate"], post["effect_applied"]) for post in repeats], [(False, False), (True, False)])
        self.assertEqual(self.js(APP + f"return app.ctx.retryCommand({b!r});"), {"ok": False, "reason": "not_retryable", "id": b})
        self.js(APP + f"app.ctx.dismissCommand({a!r}); app.ctx.dismissCommand({b!r});")
        self.assertEqual(self.js(APP + "return state.pending.length;"), 0)

        for post in self.commands_logged():
            self.assertEqual(set(post["body"]), {"command_id", "type", "target", "run"})
            self.assertEqual(post["body"]["run"], "run-0005")
        self.assertEqual(len(self.commands_logged()), 6)
        self.assert_only_platform_calls_of_the_contract()

    def test_timeout_is_unknown_delivery_and_blocked_commands_are_not_sent(self):
        self.open("commands")
        self.wait_ready()
        seq = int(self.body()["seq"])
        self.page.wait_for(f"Number(document.body.dataset.seq) > {seq}", timeout=4.0)
        self.mock.fault("hang")
        first = self.js(APP + "return app.ctx.sendCommand('action.stop_zone', 'zone-a');")
        self.assertTrue(first["ok"], first)
        self.wait_phase(first["id"], "delivery_unknown", 5.0)
        message = self.js(APP + f"""const entry = state.pending.find((item) => item.id === {first['id']!r});
          return [entry.failure, app.ctx.text.pendingText(entry)];""")
        self.assertEqual(message, [{"kind": "timeout", "status": None},
                                   "Результат доставки неизвестен (нет ответа за 3 с). Команда могла дойти до модели"])

        self.wait_body(3.0, commands="blocked")
        second = self.js(APP + "return app.ctx.sendCommand('action.resume_zone', 'zone-a');")
        self.assertEqual((second["ok"], second["reason"]), (False, "blocked"))
        blocked = self.js(APP + f"""const entry = state.pending.find((item) => item.id === {second['id']!r});
          return [entry.phase, entry.attempts, entry.failure.kind, app.ctx.text.pendingText(entry)];""")
        self.assertEqual(blocked[:3], ["not_sent", 0, "blocked"])
        self.assertTrue(blocked[3].startswith("Команда не отправлена: команды заблокированы: "), blocked[3])
        self.assertEqual(self.js(APP + f"return app.ctx.retryCommand({first['id']!r});"),
                         {"ok": False, "reason": "blocked", "id": first["id"]})
        self.assertEqual(self.phase(first["id"]), "delivery_unknown")

        self.mock.fault("none")
        self.wait_body(8.0, link="ok", commands="enabled")
        self.assertEqual(self.js(APP + f"return app.ctx.retryCommand({first['id']!r});"), {"ok": True, "id": first["id"]})
        self.assertEqual(self.js(APP + f"return app.ctx.retryCommand({second['id']!r});"), {"ok": True, "id": second["id"]})
        self.wait_phase(first["id"], "applied", 5.0)
        self.wait_phase(second["id"], "rejected", 5.0)
        texts = self.js(APP + f"""const find = (id) => state.pending.find((item) => item.id === id);
          return [app.ctx.text.pendingText(find({first['id']!r})), app.ctx.text.pendingText(find({second['id']!r}))];""")
        self.assertEqual(texts, ["Команда применена без изменения: состояние уже такое",
                                 "Команда отклонена: на участке недостаточно персонала (insufficient_workers)"])
        # The mock does not read the body of a request it lets hang, so the two attempts are compared in the browser.
        def bodies(command_id):
            return [request["post_data"] for request in list(self.page.requests)
                    if request["method"] == "POST" and command_id in (request["post_data"] or "")]

        attempts = bodies(first["id"])
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0], attempts[1], "the retry is the identical body")
        self.assertEqual(len(bodies(second["id"])), 1, "the blocked attempt was never posted")
        accepted = wait_until(lambda: self.commands_logged(first["id"]), timeout=4.0)
        self.assertEqual([(post["status"], post["delivered"]) for post in accepted], [(202, True)])
        hung = [entry for entry in self.platform_log() if entry["method"] == "POST" and entry.get("fault") == "hang"]
        self.assertEqual(len(hung), 1)

    def test_execute_option_carries_the_decision_id(self):
        self.open("paused_heartbeat")
        self.wait_ready()
        sent = self.js(APP + """
          const published = state.model.byName['option-stop-withdraw'].values.decision_id;
          return {
            published,
            ok: app.ctx.sendCommand('action.execute_option', 'option-stop-withdraw'),
            unknownOption: app.ctx.sendCommand('action.execute_option', 'option-nowhere'),
          };
        """)
        self.assertEqual(sent["published"], "d-0005-01")
        self.assertTrue(sent["ok"]["ok"])
        self.assertEqual(sent["unknownOption"], {"ok": False, "reason": "no_decision_id"})
        posts = wait_until(lambda: self.commands_logged(sent["ok"]["id"]), timeout=3.0)
        self.assertEqual(posts[0]["body"], {"command_id": sent["ok"]["id"], "type": "action.execute_option",
                                            "target": "option-stop-withdraw", "run": "run-0005", "decision_id": "d-0005-01"})
        # The fixture has no rule here and answers with a reason the contract does not know.
        self.wait_phase(sent["ok"]["id"], "rejected", 4.0)
        self.assertEqual(self.js(APP + "return app.ctx.text.pendingText(state.pending[0]);"),
                         "Команда отклонена: неизвестная причина (not_scripted)")
        self.assertEqual(len(self.commands_logged()), 1)

    def test_reset_changes_the_run_without_mixing_two_runs(self):
        self.open("reset", "#/list?type=working")
        first = self.wait_ready()
        self.assertEqual((first["run"], first["runState"]), ("run-0005", "paused"))
        self.assertEqual(next(row for row in self.rows() if row["thingId"] == f"{NS}:w-12")["passability"], "closed")
        self.js(APP + """
          window.__mixed = [];
          window.__runs = [];
          app.store.subscribe((s) => {
            if (!s.snapshot) return;
            if (window.__runs[window.__runs.length - 1] !== s.snapshot.run) window.__runs.push(s.snapshot.run);
            for (const [id, features] of Object.entries(s.snapshot.scene)) {
              if (features.values.idSimulationRun !== s.snapshot.run) window.__mixed.push([id, features.values.idSimulationRun, s.snapshot.run]);
            }
            for (const thing of Object.values(s.model.things)) {
              if (thing.hasState && thing.values.idSimulationRun !== s.snapshot.run) window.__mixed.push(['model', thing.name]);
            }
          });
          window.__marker = 'same document';
        """)
        self.record_phases()
        sent = self.js(APP + "return app.ctx.sendCommand('run.reset');")
        self.assertTrue(sent["ok"], sent)
        blocked = self.wait_body(3.0, commands="blocked", ownReset="pending")
        self.assertEqual(blocked["blockReason"], "own_reset_pending")
        banner = self.wait_banner("resetting", 2.0)
        self.assertTrue(banner["text"].startswith("Выполняется сброс. Новый прогон ещё не начался"), banner["text"])
        other = self.js(APP + "return app.ctx.sendCommand('condition.open_working', 'w-12');")
        self.assertEqual((other["ok"], other["reason"]), (False, "blocked"))
        self.js(APP + f"app.ctx.dismissCommand({other['id']!r});")
        self.wait_body(5.0, runState="resetting")
        self.assertEqual(self.body()["run"], "run-0005")

        fresh = self.wait_body(10.0, run="run-0006", runState="running")
        self.assertLess(int(fresh["tick"]), 100, "the new run starts its own model time")
        self.wait_phase(sent["id"], "applied", 4.0)
        ack = self.js(APP + f"return state.pending.find((entry) => entry.id === {sent['id']!r}).ack;")
        self.assertEqual((ack["run"], ack["new_run"], ack["status"]), ("run-0005", "run-0006", "applied"))
        self.wait_body(4.0, commands="enabled", snapshot="ok")
        self.assertNotIn("resetting", self.banner_codes())
        self.assertEqual(self.text_of("status-conditions"), "Условия стенда: нет")
        self.assertEqual(next(row for row in self.rows() if row["thingId"] == f"{NS}:w-12")["passability"], "open")
        self.assertEqual(self.page.evaluate("window.__runs"), ["run-0005", "run-0006"])
        self.assertEqual(self.page.evaluate("window.__mixed"), [], "states of two runs never share the screen")
        self.assertEqual(self.page.evaluate("window.__marker"), "same document")

        self.page.wait_for("(async () => { const {app} = await import('/js/main.js'); const {archive} = app.store.getState();"
                           " return archive.status === 'ready' && archive.ids.includes('run-0005'); })()", timeout=5.0)
        interrupted = self.js(APP + """const run = state.archive.runs.find((item) => item.name === 'run-0005');
          return [run.values.completion_reason, 'last_out_s' in run.values, app.ctx.text.label('completionReason', run.values.completion_reason)];""")
        self.assertEqual(interrupted, ["reset", False, "прерван сбросом"])

        entries = self.platform_log()
        posts = self.commands_logged(sent["id"])
        self.assertEqual([post["body"] for post in posts],
                         [{"command_id": sent["id"], "type": "run.reset", "target": "run", "run": "run-0005"}])
        self.assertEqual(len(self.commands_logged()), 1, "the blocked command was not posted")
        self.assertGreaterEqual(len([entry for entry in entries if entry["path"] == MINE_PATH]), 2,
                                "the mine is read again when the run changes")
        self.assertEqual(len([entry for entry in entries if entry["path"].endswith("&fields=thingId,attributes")]), 4,
                         "the manifest did not change, so the other attributes are not read again")
        self.assertTrue([entry for entry in entries if "run-0005" in entry["path"] and entry["path"].endswith(",features")],
                        "the archive is read again for the new list of runs")
        self.assertEqual(self.page.evaluate("window.__phases")[sent["id"]], ["sending", "sent", "applied"])
        self.assert_only_platform_calls_of_the_contract()


class ShellTest(CoreTestCase):
    def test_hash_routes_open_views_and_never_send_commands(self):
        target = f"{NS}:sens-ext-05"
        self.open("normal", f"#/list?type=sensor&sel={target}")
        self.wait_ready()
        self.assertEqual(self.body()["view"], "list")
        self.assertEqual(self.page.evaluate("document.querySelector('[data-testid=\"list-type\"]').value"), "sensor")
        rows = self.rows()
        self.assertEqual(len(rows), 10)
        self.assertEqual([row["thingId"] for row in rows if row["selected"] == "true"], [target])
        visible = self.page.evaluate("['view-scheme', 'view-list', 'view-runs'].map((id) => !document.getElementById(id).hidden)")
        self.assertEqual(visible, [False, True, False])

        # View switches are real buttons, usable from the keyboard.
        self.page.evaluate("document.querySelector('[data-testid=\"tab-runs\"]').focus()")
        self.assertEqual(self.page.focus_info()["tag"], "button")
        self.page.press("Enter")
        self.page.wait_for("location.hash === '#/runs'")
        self.assertEqual(self.body()["view"], "runs")
        self.assertEqual(self.page.evaluate("document.querySelector('[data-testid=\"tab-runs\"]').getAttribute('aria-selected')"), "true")
        self.assertEqual(self.page.focus_info()["testid"], "tab-runs", "switching the view keeps the focus on its tab")
        self.page.click('[data-testid="tab-scheme"]')
        self.page.wait_for(f"location.hash === '#/scheme?sel={target}'", message="the selection is kept across views")

        # A changed fragment is followed without a reload.
        self.page.evaluate("window.__marker = 'same document'")
        self.page.goto(self.mock.url + f"/#/scheme?sel={NS}:worker-03&view=plan&level=level-320")
        self.page.wait_for("document.body.dataset.view === 'scheme'")
        ui = self.js(APP + "return state.ui;")
        # The fields of the route; the stage keeps fields of its own in the same object.
        self.assertEqual({key: ui[key] for key in ("view", "projection", "level", "selected", "listType")},
                         {"view": "scheme", "projection": "plan", "level": "level-320",
                          "selected": f"{NS}:worker-03", "listType": "sensor"})
        self.page.goto(self.mock.url + "/#/list?type=zone")
        self.page.wait_for("document.querySelectorAll('[data-testid=\"list\"] tbody tr').length === 4")
        self.assertEqual(self.page.evaluate("window.__marker"), "same document")

        # State to hash: the actions of ctx write the canonical route.
        self.js(APP + f"app.ctx.setView('scheme'); app.ctx.setProjection('axo'); app.ctx.setLevel(null); app.ctx.select('{NS}:w-12');")
        self.assertEqual(self.page.evaluate("location.hash"), f"#/scheme?sel={NS}:w-12")
        self.js(APP + "app.ctx.select(null); app.ctx.setListType('exit'); app.ctx.setView('list');")
        self.assertEqual(self.page.evaluate("location.hash"), "#/list?type=exit")

        # A route that looks like a command is only a route; a selection of a twin that does not exist is dropped.
        self.page.goto(self.mock.url + f"/#/scheme?sel={NS}:nothing&command=run.reset&type=run.reset")
        self.page.wait_for("location.hash === '#/scheme'")
        time.sleep(1.2)
        self.assertFalse(self.commands_logged())
        self.assertFalse([request for request in self.page.requests if request["method"] != "GET"])
        self.assert_only_platform_calls_of_the_contract()

    def test_layout_fills_both_viewports_without_page_scroll(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        for width, height in ((1920, 1080), (1280, 720)):
            with self.subTest(viewport=f"{width}x{height}"):
                self.page.set_viewport(width, height)
                self.open("paused_heartbeat", "#/scheme")
                self.wait_ready()
                self.wait_banner("paused_decision", 3.0)
                metrics = self.page.evaluate("""(() => {
                  const box = (selector) => {
                    const node = document.querySelector(selector);
                    const rect = node.getBoundingClientRect();
                    return {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
                            width: rect.width, height: rect.height, display: getComputedStyle(node).display};
                  };
                  const root = document.documentElement;
                  return {
                    scroll: [root.scrollWidth, root.scrollHeight, document.body.scrollWidth, document.body.scrollHeight],
                    regions: Object.fromEntries(['#statusbar', '#situation', '#centre', '#stage', '#right', '#decision-dock',
                      '#journal-region', '#actions'].map((selector) => [selector, box(selector)])),
                    always: Object.fromEntries(['status-notice', 'status-link', 'status-age', 'incident-in-danger',
                      'incident-no-route', 'incident-unknown', 'incident-total', 'situation-step-1', 'stand-toggle',
                      'legend', 'tab-scheme', 'tab-list', 'tab-runs']
                      .map((id) => [id, box('[data-testid="' + id + '"]')])),
                    run: box('[data-testid="status-run"]'),
                    drawer: getComputedStyle(document.getElementById('stand-drawer')).visibility,
                    font: getComputedStyle(document.body).fontFamily, fontSize: getComputedStyle(document.body).fontSize,
                  };
                })()""")
                self.assertEqual(metrics["scroll"], [width, height, width, height], "no page scroll in either direction")
                for name, box in {**metrics["regions"], **metrics["always"]}.items():
                    self.assertGreater(box["width"], 0, name)
                    self.assertGreater(box["height"], 0, name)
                    self.assertGreaterEqual(box["left"], 0, name)
                    self.assertLessEqual(box["right"], width + 0.5, name)
                    self.assertLessEqual(box["bottom"], height + 0.5, name)
                regions = metrics["regions"]
                compact = width < 1600
                self.assertEqual(round(regions["#right"]["width"]), 320 if compact else 400)
                self.assertEqual(round(regions["#statusbar"]["height"]), 52 if compact else 60, "the top bar is one line")
                self.assertAlmostEqual(regions["#right"]["left"], regions["#centre"]["right"], delta=1)
                self.assertAlmostEqual(regions["#situation"]["top"], regions["#statusbar"]["bottom"], delta=1)
                self.assertAlmostEqual(regions["#centre"]["top"], regions["#situation"]["bottom"], delta=1)
                stage = regions["#stage"]
                self.assertGreaterEqual(stage["width"] * stage["height"], max(box["width"] * box["height"] for name, box
                                        in regions.items() if name not in ("#centre", "#stage")), "the stage is the largest area")
                self.assertEqual(self.body()["dock"], "collapsed" if compact else "open",
                                 "a decision unfolds the dock under the stage; over the stage (compact) it shows its bar")
                if compact:
                    # The dock unfolds over the stage: the stage keeps its area.
                    self.assertGreaterEqual(stage["width"] * stage["height"] / (width * height), 0.6, "the stage keeps 60 % of 1280x720")
                    self.assertLessEqual(regions["#decision-dock"]["bottom"], stage["bottom"] + 0.5)
                else:
                    self.assertAlmostEqual(regions["#decision-dock"]["top"], stage["bottom"], delta=1, msg="the dock is under the stage")
                self.assertEqual(metrics["run"]["display"] == "none", compact, "run and seed fold away in the compact layout")
                self.assertEqual(metrics["drawer"], "hidden", "the stand drawer is closed by default")
                self.assertTrue(metrics["font"].startswith('"IBM Plex Sans"'), metrics["font"])
                self.assertEqual(metrics["fontSize"], "14px")
                self.page.screenshot(os.path.join(OUTPUT_DIR, f"core-shell-{width}x{height}.png"))

        # Compact layout: the drawer opens from the keyboard, survives a poll and closes with Esc; the dock folds.
        self.page.evaluate("document.querySelector('[data-testid=\"stand-toggle\"]').focus()")
        self.page.press("Enter")
        self.page.wait_for("document.body.dataset.stand === 'open'", timeout=2.0)
        self.assertEqual(self.page.evaluate("getComputedStyle(document.getElementById('stand-drawer')).visibility"), "visible")
        self.assertEqual(self.page.focus_info()["testid"], "stand-close", "the focus moves into the drawer")
        seq = int(self.body()["seq"])
        self.page.wait_for(f"Number(document.body.dataset.seq) >= {seq + 2}", timeout=6.0)
        self.assertEqual(self.body()["stand"], "open")
        self.page.press("Escape")
        self.page.wait_for("document.body.dataset.stand === 'closed'", timeout=2.0)
        self.assertEqual(self.page.focus_info()["testid"], "stand-toggle", "Esc gives the focus back to the button")
        self.page.click('[data-testid="dock-toggle"]')
        self.assertEqual(self.body()["dock"], "open")
        time.sleep(0.35)    # the dock unfolds over 200 ms (clarity pass, M3); the legend chip follows it
        cover = self.page.evaluate("[parseFloat(getComputedStyle(document.getElementById('centre')).getPropertyValue('--dock-cover')),"
                                   " document.getElementById('decision-dock').getBoundingClientRect().top,"
                                   " document.getElementById('legend').getBoundingClientRect().bottom]")
        self.assertGreater(cover[0], 100, "the unfolded dock lies over the stage")
        self.assertLessEqual(cover[2], cover[1] + 0.5, "the legend chip stays above the unfolded dock")
        self.page.click('[data-testid="journal-toggle"]')
        self.assertEqual(self.body()["journal"], "open")
        seq = int(self.body()["seq"])
        self.page.wait_for(f"Number(document.body.dataset.seq) >= {seq + 2}", timeout=6.0)
        state = self.body()
        self.assertEqual((state["journal"], state["dock"]), ("open", "open"), "a poll keeps what the user unfolded")
        self.assertGreater(self.page.evaluate("document.querySelectorAll('[data-testid=\"journal-entry\"]').length"), 3)
