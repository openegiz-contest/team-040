"""Acceptance tests: the checklist of team/CLAUDE_NEXT_TASK.md, section «Проверка», read end to end.

One test (or a small group) per item of the checklist, named after the item. Each drives the
production page served by the mock server through its real controls, wherever a control exists,
and asserts what a dispatcher would see (texts, `data-*` state, counts) and what the mock server
recorded. The other test files check the same behaviour module by module; this file is the proof
that the whole screen does it.

The stage in the middle of the screen has two modes: the 3D model (the default) and the SVG scheme.
The items that show the mine are checked in both: on the scheme (asked for by the route, `mode=scheme`),
in 3D with Chrome's software WebGL (SwiftShader), and on the no-WebGL path (Chrome with
--disable-webgl, where the stage falls back to the scheme by itself).

    item                                  scheme                                      3D (Checklist3dTest)                         no WebGL
    обычный кадр                          NormalFrameTest.test_normal_frame           test_normal_frame                           NormalFrameNoWebglTest
    обход                                 PassageClosedTest.test_detour               test_detour                                 PassageClosedNoWebglTest
    отсутствие пути                       PassageClosedTest.test_no_path              test_no_path                                PassageClosedNoWebglTest
    потерянный датчик после danger        SensorLostTest.test_sensor_lost_after_danger test_sensor_lost_after_danger,             SensorLostNoWebglTest
                                                                                      test_problem_zone_tags_are_in_sight_in_the_overview
    опасный участок (danger_zone)         test_composition.NoWebglTest                test_danger_zone
    сравнение вариантов                   test_panels.PeopleBarTest                   test_options_compared_by_their_people_bars
    платформа недоступна                  LinkFailureTest                             test_platform_unavailable
    невалидный/неполный снимок            InvalidSnapshotTest.test_invalid_*          test_invalid_snapshot_keeps_the_last_scene
    несовпадение topology_version         TopologyTest.test_topology_version_mismatch (both modes), ..._change_recovers
    пауза с живым heartbeat               HeartbeatTest.test_pause_with_live_heartbeat
    застывший publication_seq             HeartbeatTest.test_frozen_publication_seq, ..._old_at_first_load
    pending/rejected/timeout команды      CommandsTest.test_pending_rejected_and_timeout_commands,
                                          CommandsTest.test_post_timeout_is_unknown_delivery_then_retry
    повтор с тем же id                    CommandsTest.test_retry_with_the_same_id
    reset                                 ResetTest.test_reset
    неполный вывод без last_out_s         ResultsTest.test_incomplete_withdrawal_without_last_out_s     (and ResultsNoWebglTest)
    отсутствие прогноза                   ResultsTest.test_no_forecast                                  (and ResultsNoWebglTest)
    несколько пакетов manifest            NormalFrameTest.test_manifest_batches_with_scrambled_order

and the cross-cutting checks of the task and of DESIGN.md 6.1: LinkFailureTest, KeyboardTest,
ColourIndependenceTest, LayoutTest, HygieneTest, StaticSourcesTest, EveryScenarioTest. The composition
around the stage (situation strip, stand drawer, top bar, dock, page scroll, keyboard and reduced motion
in 3D) is test_composition.py; the 3D stage module itself is test_scene3d.py.

Everything here is verified against the mock server only; its numbers are invented for tests.

    python -m unittest discover -s team/ui/tests -t team/ui -p "test_scenarios.py" -v
"""

from __future__ import annotations

import json
import os
import re
import time
import unittest

from browser_support import OUTPUT_DIR, PUBLIC_DIR, BrowserTestCase, MockServer, read_png, wait_until
from screenshots import (
    CLOSE, EXECUTE, RESET, REWRITE_SHIFT, STATES_PATCH, WORKING_SELECT, choose, close_working, execute_option, set_stand,
    settle, show_right, wait_decision,
)

NS = "team040.mine"
NBSP = "\u00a0"
SHIFT_PATH = f"/ditto/api/2/things/{NS}:shift?fields=thingId,features,_modified,_revision"
MINE_PATH = f"/ditto/api/2/things/{NS}:mine?fields=thingId,attributes"
COMMAND_PATH = f"/ditto/api/2/things/{NS}:shift/inbox/messages/command?timeout=0"
BATCH = re.compile(r"/ditto/api/2/things\?ids=([^&]+)&fields=(thingId,attributes(?:,features)?)")

ACTIONS = '[data-testid="actions-panel"]'
CONDITIONS = '[data-testid="conditions-panel"]'
DECISION = '[data-testid="decision-panel"]'
CARD = '[data-testid="card"]'
STOP = f'{ACTIONS} button[data-command-type="action.stop_zone"]'
ZONE_SELECT = "#action-zone"
SCENARIOS = (
    "normal", "detour", "no_path", "sensor_lost_after_danger", "paused_heartbeat", "frozen_seq", "frozen_seq_old",
    "invalid_missing_id", "invalid_duplicate_id", "invalid_mixed_tick", "invalid_missing_field",
    "invalid_contract_version", "invalid_no_metadata", "topology_mismatch", "topology_change", "commands", "reset",
    "withdrawal_incomplete", "no_forecast", "partial_forecast", "route_segments", "unknown_enum", "empty", "danger_zone",
)

# The state attributes of every twin drawn in the scheme, by thingId (one snapshot, read in one step).
DRAWN = """(() => {
  const out = {};
  for (const node of document.querySelectorAll('#scheme [data-thing-id]')) {
    const {thingId, ...state} = node.dataset;
    out[thingId] = state;
  }
  return out;
})()"""

# Counts calls that the design forbids, from before the first script of the page.
PROBE = """
window.__probe = {canvas: 0, raf: 0};
const getContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function (...args) { window.__probe.canvas += 1; return getContext.apply(this, args); };
const raf = window.requestAnimationFrame;
window.requestAnimationFrame = function (callback) { window.__probe.raf += 1; return raf.call(window, callback); };
"""

# The non-colour cues of a drawn symbol: which shapes are rendered, with which dash style, weight,
# hatch pattern and sign. Colours are left out on purpose; so is geometry.
CUES = """
const cues = (group) => {
  const parts = [];
  for (const node of group.querySelectorAll('path, circle, rect')) {
    let shown = true;
    for (let up = node; up && up !== group.parentElement; up = up.parentElement) {
      if (getComputedStyle(up).display === 'none') shown = false;
    }
    const name = (node.getAttribute('class') || '').split(' ')[0];
    if (!shown || /__hit$|__plate$/.test(name)) continue;
    const style = getComputedStyle(node);
    const sign = node.closest('[data-sign]');
    const pattern = /url\\(/.test(node.style.fill) ? 'pattern ' + node.style.fill.replace(/^.*#[a-z]+-([a-z]+).*$/, '$1') : null;
    const fill = pattern || (style.fill === 'none' ? 'no fill' : 'filled');
    const dash = style.strokeDasharray === 'none' ? 'solid' : 'dashed';
    const weight = style.stroke === 'none' ? 'no stroke' : (parseFloat(style.strokeWidth) >= 2.5 ? 'heavy' : 'thin');
    parts.push([node.tagName, name, sign ? 'sign ' + sign.dataset.sign : '', fill, dash, weight].join(' / '));
  }
  return parts.sort().join(' | ');
};
"""


def plain(text):
    return re.sub(r"\s+", " ", text.replace(NBSP, " ")).strip() if isinstance(text, str) else text


def thing(name):
    return f"{NS}:{name}"


class ScenarioTestCase(BrowserTestCase):
    """One mock server per class; a test switches the scenario through the control API."""

    mock_args = ()
    # The SVG scheme is asked for by the route (`mode=scheme`); on the no-WebGL path the stage falls back to it by itself.
    scheme_by_route = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock = MockServer("normal", extra_args=cls.mock_args).start()
        cls.addClassCleanup(cls.mock.stop)

    # ---- the page --------------------------------------------------------

    def open(self, scenario, route="", ready=True, page=None, mock=None):
        """Restart the scenario from its first frame and load the page as a new document."""
        page = page or self.page
        mock = mock or self.mock
        mock.scenario(scenario)
        page.goto("about:blank")
        page.goto(mock.url + "/" + route)
        if ready:
            self.wait_body(boot="ready", snapshot="ok", link="ok")

    def js(self, body, timeout=20.0):
        return self.page.evaluate("(async () => {" + body + "})()", timeout=timeout)

    def body(self, page=None):
        return (page or self.page).evaluate("Object.assign({}, document.body.dataset)")

    def wait_body(self, timeout=10.0, page=None, **expected):
        """Wait until every given `<body>` data attribute has its value (camelCase names of `dataset`)."""
        condition = " && ".join(f"document.body.dataset.{name} === {value!r}" for name, value in expected.items())
        try:
            (page or self.page).wait_for(condition, timeout=timeout)
        except AssertionError as error:
            raise AssertionError(f"{error}\nbody: {self.body(page)}\nbanners: {self.banners(page)}") from None
        return self.body(page)

    def wait_drawn(self, timeout=10.0):
        """Wait for the SVG scheme. It is the «Схема» mode of the stage: the route asks for it (`mode=scheme`), as a link does;
        without WebGL the stage shows it by itself, with its notice."""
        if self.scheme_by_route:
            self.page.evaluate("""(() => {
              if (/[?&]mode=scheme/.test(location.hash)) return;
              const hash = location.hash && location.hash !== '#' ? location.hash : '#/scheme';
              location.hash = hash + (hash.includes('?') ? '&' : '?') + 'mode=scheme';
            })()""")
        else:
            self.page.wait_for("document.querySelector('#stage').dataset.fallback === 'no-webgl'"
                               " && document.querySelector('#stage').dataset.stageMode === 'scheme'"
                               " && !document.querySelector('[data-testid=\"stage-notice\"]').hidden", timeout=timeout,
                               message="without WebGL the stage falls back to the scheme, with its notice")
        self.page.wait_for("document.querySelector('[data-testid=\"scheme-svg\"]').dataset.drawn === 'true'"
                           " && !!document.querySelector('#scheme .worker')", timeout=timeout, message="the scheme is drawn")

    def wait_seq(self, count=1, timeout=None):
        """Wait until the page has rendered `count` further publications."""
        seq = int(self.body()["seq"])
        self.page.wait_for(f"Number(document.body.dataset.seq) >= {seq + count}", timeout=timeout or 4.0 + 1.5 * count)

    def text(self, selector, page=None):
        """Text of the first match as a reader sees it, whitespace collapsed; None when nothing matches or it is not rendered."""
        return plain((page or self.page).evaluate(f"""(() => {{
          const node = document.querySelector({json.dumps(selector)});
          return node && node.getClientRects().length > 0 ? node.textContent : null;
        }})()"""))

    def texts(self, selector):
        return [plain(item) for item in self.page.evaluate(
            f"[...document.querySelectorAll({json.dumps(selector)})].filter((node) => node.getClientRects().length > 0)"
            ".map((node) => node.textContent)")]

    def count(self, selector):
        return self.page.evaluate(f"document.querySelectorAll({json.dumps(selector)}).length")

    def attr(self, selector, name):
        return plain(self.page.evaluate(f"""(() => {{
          const node = document.querySelector({json.dumps(selector)});
          return node ? node.getAttribute({json.dumps(name)}) : null;
        }})()"""))

    def words(self, selector):
        """The text of the first match with its text nodes joined by spaces (a caption and its value do not run together)."""
        return plain(self.page.evaluate(f"""(() => {{
          const root = document.querySelector({json.dumps(selector)});
          if (!root || root.getClientRects().length === 0) return null;
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
          const parts = [];
          while (walker.nextNode()) {{
            if (walker.currentNode.parentElement.getClientRects().length > 0) parts.push(walker.currentNode.nodeValue);
          }}
          return parts.join(' ');
        }})()"""))

    def wait_for_selector(self, selector, timeout=6.0, message=""):
        self.page.wait_for(f"!!document.querySelector({json.dumps(selector)})", timeout=timeout, message=message or selector)

    def wait_text(self, selector, part, timeout=6.0):
        try:
            self.page.wait_for(f"""(() => {{
              const node = document.querySelector({json.dumps(selector)});
              return !!node && node.getClientRects().length > 0
                && node.textContent.replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').includes({json.dumps(part)});
            }})()""", timeout=timeout)
        except AssertionError as error:
            raise AssertionError(f"{error}\ntext of {selector}: {self.text(selector)!r}") from None
        return self.text(selector)

    def visible(self, selector):
        """True when the first match is rendered inside the viewport and is what the pointer would hit at its centre."""
        return self.page.evaluate(f"""(() => {{
          const node = document.querySelector({json.dumps(selector)});
          if (!node) return false;
          const box = node.getBoundingClientRect();
          if (box.width <= 0 || box.height <= 0) return false;
          if (box.left < 0 || box.top < 0 || box.right > innerWidth + 0.5 || box.bottom > innerHeight + 0.5) return false;
          const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
          return !!hit && (node.contains(hit) || hit.contains(node));
        }})()""")

    def banners(self, page=None):
        return (page or self.page).evaluate("""[...document.querySelectorAll('[data-testid="overlay-banner"]')].map((node) => ({
          code: node.dataset.code, reason: node.dataset.reason || null,
          text: node.textContent.replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim(),
        }))""")

    def banner_codes(self):
        return [banner["code"] for banner in self.banners()]

    def wait_banner(self, code, timeout=10.0, page=None):
        (page or self.page).wait_for(f"!!document.querySelector('[data-testid=\"overlay-banner\"][data-code=\"{code}\"]')",
                                     timeout=timeout, message=f"banner {code}")
        return next(banner for banner in self.banners(page) if banner["code"] == code)

    def counters(self):
        return {name: self.text(f'[data-testid="incident-{name}"]')
                for name in ("in-danger", "no-route", "unknown", "out", "total")}

    # ---- views -----------------------------------------------------------

    def show(self, view):
        """Open a view by its tab (once the panels stand still: the strip may be unfolding, clarity pass M2)."""
        settle(self.page)
        self.page.click(f'[data-testid="tab-{view}"]')
        self.page.wait_for(f"document.body.dataset.view === '{view}'", timeout=3.0)

    def scheme(self, name):
        return f'#scheme [data-thing-id="{thing(name)}"]'

    def row(self, name):
        return f'[data-testid="list"] tr[data-thing-id="{thing(name)}"]'

    def cells(self, name):
        return [plain(cell) for cell in self.page.evaluate(
            f"[...document.querySelector({json.dumps(self.row(name))}).cells].map((cell) => cell.innerText)")]

    def select_on_scheme(self, name):
        """Select a twin by a click on its mark in the scheme. The decision dock unfolded over the stage
        (1280x720) is folded first, as a user would: it covers the lower part of the picture."""
        if self.body().get("dock") == "open" and self.page.evaluate(
                "getComputedStyle(document.getElementById('decision-dock')).position") == "absolute":
            self.page.click('[data-testid="dock-toggle"]')
            settle(self.page)    # it folds over 200 ms (clarity pass, M3)
        self.page.click(self.scheme(name), force=True)
        self.page.wait_for(f"location.hash.includes('{name}')", timeout=3.0, message=f"{name} is selected")

    def card(self):
        show_right(self.page, "card")
        return self.words(CARD)

    def decision(self):
        show_right(self.page, "decision")
        return self.words(DECISION)

    def metric(self, option, metric):
        return self.text(f'{DECISION} td[data-option="{option}"][data-metric="{metric}"]')

    def drawn(self):
        return self.page.evaluate(DRAWN)

    # ---- commands --------------------------------------------------------

    def pending(self):
        entries = self.page.evaluate("""[...document.querySelectorAll('[data-testid="pending"]')].map((node) => ({
          id: node.dataset.commandId, type: node.dataset.commandType, target: node.dataset.commandTarget,
          phase: node.dataset.phase, what: node.querySelector('.pending__what').textContent,
          text: node.querySelector('.pending__text').textContent,
          buttons: [...node.querySelectorAll('button')].filter((button) => !button.hidden).map((button) => button.textContent),
        }))""")
        for entry in entries:
            entry["text"] = plain(entry["text"])
        return entries

    def wait_pending(self, target, phase, timeout=8.0, command_type=None):
        selector = f'[data-testid="pending"][data-command-target="{target}"][data-phase="{phase}"]'
        if command_type:
            selector += f'[data-command-type="{command_type}"]'
        try:
            self.page.wait_for(f"!!document.querySelector({json.dumps(selector)})", timeout=timeout)
        except AssertionError as error:
            raise AssertionError(f"{error}\npending: {self.pending()}") from None
        return next(entry for entry in self.pending()
                    if entry["target"] == target and command_type in (None, entry["type"]))

    def press_in_pending(self, target, test_id):
        self.page.click(f'[data-testid="pending"][data-command-target="{target}"] [data-testid="{test_id}"]')

    def is_off(self, selector):
        return self.attr(selector, "aria-disabled") == "true"

    def platform_log(self, mock=None):
        """Requests to the platform paths, as the mock recorded them."""
        return [entry for entry in (mock or self.mock).log()["entries"] if entry["kind"] in ("ditto", "command")]

    def commands_logged(self, command_type=None, mock=None):
        return [entry for entry in self.platform_log(mock) if entry["kind"] == "command"
                and (command_type is None or (entry.get("body") or {}).get("type") == command_type)]

    def wait_commands(self, count, command_type=None):
        return wait_until(lambda: len(self.commands_logged(command_type)) >= count and self.commands_logged(command_type),
                          timeout=4.0, message=f"{count} command(s) in the log of the mock")

    def assert_only_contract_requests(self, page=None, mock=None):
        """Every request of the page is on its origin, static or under /ditto/, and the mock saw only allowed calls."""
        page = page or self.page
        mock = mock or self.mock
        origin = mock.url + "/"
        for request in list(page.requests):
            url = request["url"]
            # A data: URL is an image the page drew itself, not a request to any server.
            if url == "about:blank" or url.startswith("data:"):
                continue
            self.assertTrue(url.startswith(origin), f"a request outside the origin: {url}")
            path = "/" + url[len(origin):]
            self.assertNotIn("__mock__", path, "production code never calls the control API")
            if path.startswith("/ditto/"):
                self.assertIn(request["type"], ("Fetch", "XHR"), path)
            else:
                self.assertRegex(path, r"^/(?:(?:css|js)/[\w./-]+\.(?:css|js)|fonts/[\w.-]+\.(?:css|woff2)|vendor/[\w./-]+\.js"
                                       r"|models/[\w.-]+\.glb)?$", f"not a static file of the page: {path}")
        entries = self.platform_log(mock)
        self.assertTrue(entries, "the page read the platform")
        for entry in entries:
            self.assertTrue(entry["allowed"], f"a request outside the contract: {entry['method']} {entry['path']}")
            if entry["kind"] == "command":
                self.assertEqual((entry["method"], entry["path"]), ("POST", COMMAND_PATH))
                continue
            self.assertEqual(entry["method"], "GET")
            if entry["path"] in (MINE_PATH, SHIFT_PATH):
                continue
            match = BATCH.fullmatch(entry["path"])
            self.assertIsNotNone(match, f"unexpected platform read: {entry['path']}")
            ids = match.group(1).split(",")
            self.assertLessEqual(len(ids), 20, "a batch holds at most 20 ids")
            self.assertTrue(all(item.startswith(NS + ":") for item in ids))


# --------------------------------------------------------------------------
# обычный кадр; несколько пакетов manifest
# --------------------------------------------------------------------------

class NormalFrameTest(ScenarioTestCase):
    def test_normal_frame(self):
        """Обычный кадр: the screen of an undisturbed shift, without a single press."""
        self.open("normal")
        self.wait_drawn()
        state = self.wait_body(5.0, publications="alive")
        self.assertEqual((state["link"], state["snapshot"], state["commands"], state["run"], state["runState"]),
                         ("ok", "ok", "enabled", "run-0005", "running"))
        self.assertEqual(self.banners(), [], "nothing calls the screen into question")

        # Top bar: the notice, the link, the age of the data, model time, run, conditions.
        self.assertEqual(self.text('[data-testid="status-notice"]'), "Синтетические данные. Расчёт модели, не сведения о реальной шахте")
        self.assertEqual(self.text('[data-testid="status-link"]'), "Платформа: связь есть")
        self.assertRegex(self.text('[data-testid="status-age"]'), r"^данные [0-2] с назад$")
        # Time, not ticks; the seed in the title of the run (clarity pass, A7, A8).
        self.assertRegex(self.text('[data-testid="status-model-time"]'), r"^Модель \d\d:\d\d:\d\d · ×10 · модель идёт$")
        self.assertEqual(plain(self.page.evaluate("document.querySelector('[data-testid=\"status-run\"]').textContent")),
                         "Прогон run-0005")
        self.assertEqual(self.attr('[data-testid="status-run"]', "title"), "Прогон run-0005; seed 42")
        self.assertEqual(self.text('[data-testid="status-conditions"]'), "Условия стенда: нет")

        # No incident and no banner: the situation strip gives its room to the stage; the people figures of the
        # model stay in the top bar, the incident state stays in the DOM.
        self.assertEqual(self.attr('[data-testid="incident-strip"]', "data-incident-state"), "none")
        self.assertIn("Инцидентов нет", plain(self.page.evaluate("document.querySelector('[data-testid=\"incident-strip\"]').textContent")))
        self.assertFalse(self.visible('[data-testid="situation-strip"]'))
        self.assertEqual(self.counters(), {"in-danger": "0", "no-route": "0", "unknown": "0", "out": "0", "total": "14"})

        # The scheme: every placed twin once, with the published state and nothing normal by default.
        drawn = self.drawn()
        kinds = {}
        for state_of in drawn.values():
            kinds[state_of["kind"]] = kinds.get(state_of["kind"], 0) + 1
        self.assertEqual(kinds, {"working": 36, "zone": 4, "sensor": 10, "worker": 14, "exit": 3})
        hazards = {name: drawn[thing(name)]["hazard"] for name in ("zone-a", "zone-b", "zone-c", "zone-d")}
        self.assertEqual(hazards, {"zone-a": "normal", "zone-b": "normal", "zone-c": "normal", "zone-d": "attention"})
        workings = [item for item in drawn.values() if item["kind"] == "working"]
        by_hazard = {}
        for item in workings:
            by_hazard[item["hazard"]] = by_hazard.get(item["hazard"], 0) + 1
            if item["quality"] != "fresh":
                self.assertEqual(item["hazard"], "unknown", "a working without current data is never drawn as normal")
        self.assertEqual(by_hazard, {"normal": 12, "attention": 3, "unknown": 21})
        self.assertTrue(all(item["passability"] == "open" for item in workings))
        workers = [item for item in drawn.values() if item["kind"] == "worker"]
        self.assertTrue(all((item["egress"], item["status"]) == ("ok", "working") for item in workers))
        self.assertTrue(all(item["state"] == "available" for item in drawn.values() if item["kind"] == "exit"))
        self.assertTrue(all((item["quality"], item["link"]) == ("fresh", "online") for item in drawn.values() if item["kind"] == "sensor"))
        self.assertEqual(self.count("#scheme .route"), 0, "no route is drawn until something is selected")
        self.assertIn("Участок Г: внимание", self.attr(self.scheme("zone-d"), "aria-label"))
        self.assertIn("Вертикаль не в масштабе", self.text("#scheme .scheme__note"))

        # Legend, card, journal.
        self.assertEqual(self.texts('[data-testid="legend"] .legend__title'), ["Опасность:", "Данные:", "Достижимость:", "Выход:"])
        summary = self.card()
        for words in ("Сводка смены", "всего работников 14", "вышло 0", "Ствол: выход доступен (модель); вышло 0",
                      "Участок Г: внимание; работает; приказа о выводе нет; 3 работника", "Условия стенда нет"):
            self.assertIn(words, summary)
        self.assertGreaterEqual(self.count('[data-testid="journal-entry"]'), 2)
        self.assertIn("прогон начат", self.text('[data-testid="journal"]') or self.page.evaluate(
            "document.querySelector('[data-testid=\"journal\"]').textContent"))
        self.assertEqual(self.page.evaluate("document.getElementById('decision').childNodes.length"), 0,
                         "no incident: no decision is asked for")

        # Model time goes on and the picture follows it.
        tick = int(self.body()["tick"])
        self.wait_seq(2)
        self.assertGreater(int(self.body()["tick"]), tick)

        # The same twins as a list.
        self.show("list")
        self.assertEqual(self.count('[data-testid="list"] tbody tr'), 75)
        self.assertEqual(self.text('[data-testid="list-count"]'), "Показано: 75 объектов")
        self.assertEqual(self.commands_logged(), [], "a plain look at the screen sends no command")
        self.assert_only_contract_requests()

    def test_manifest_batches_with_scrambled_order(self):
        """Несколько пакетов manifest с переставленным порядком объектов."""
        self.open("normal")
        self.wait_drawn()
        reads = [entry for entry in self.platform_log() if entry["method"] == "GET"]
        self.assertEqual(reads[0]["path"], MINE_PATH, "the mine is read first: it carries the manifest")
        batches = [BATCH.fullmatch(entry["path"]) for entry in reads]
        batches = [match for match in batches if match and match.group(2) == "thingId,attributes"]
        requested = [match.group(1).split(",") for match in batches]
        self.assertEqual([len(ids) for ids in requested], [20, 20, 20, 17], "four attribute batches of at most 20 ids")
        every = [item for ids in requested for item in ids]
        self.assertEqual(len(set(every)), 77, "every id of the manifest once")

        # The same reads again, from the test: the mock answers every batch out of order.
        labels = {}
        for match, ids in zip(batches, requested):
            answer = self.mock.request("GET", match.group(0))
            order = [item["thingId"] for item in answer]
            self.assertEqual(sorted(order), sorted(ids))
            self.assertNotEqual(order, ids, "the answer is not in the order of the request")
            labels.update({item["thingId"]: item["attributes"].get("label") for item in answer})

        # The picture is complete and every twin carries its own attributes, whatever the order was.
        self.show("list")
        rows = dict(self.page.evaluate(
            "[...document.querySelectorAll('[data-testid=\"list\"] tbody tr')].map((row) => [row.dataset.thingId, row.cells[1].textContent])"))
        expected = {thing_id: label for thing_id, label in labels.items() if thing_id not in (thing("mine"), thing("shift"))}
        self.assertEqual(len(rows), 75)
        self.assertEqual(rows, expected, "each row shows the label of its own twin")
        self.show("scheme")
        drawn = self.drawn()
        for kind, count in (("working", 36), ("sensor", 10), ("worker", 14), ("exit", 3), ("zone", 4)):
            self.assertEqual(len([1 for item in drawn.values() if item["kind"] == kind]), count, kind)
        for name in ("w-01", "w-19", "w-36", "sens-geo-02", "exit-raise"):
            self.assertTrue(self.attr(self.scheme(name), "aria-label").startswith(labels[thing(name)] + ":"), name)
        lengths = self.page.evaluate(
            "[...document.querySelectorAll('#scheme .working')].map((node) => node.querySelector('path').getTotalLength())")
        self.assertTrue(all(length > 5 for length in lengths), "every working has its geometry")


# --------------------------------------------------------------------------
# обход; отсутствие пути
# --------------------------------------------------------------------------

class PassageClosedTest(ScenarioTestCase):
    SAMPLER = """(() => {
      window.__samples = [];
      window.__sampler = setInterval(() => {
        const entry = document.querySelector('[data-testid="pending"][data-command-target="%(target)s"]');
        const working = document.querySelector('#scheme [data-thing-id="%(thing)s"]');
        const pair = [entry ? entry.dataset.phase : null, working.dataset.passability, working.hasAttribute('data-pending')];
        const last = window.__samples[window.__samples.length - 1];
        if (!last || last.join() !== pair.join()) window.__samples.push(pair);
      }, 20);
    })()"""

    def close_by_the_stand_controls(self, working):
        """Press «Задать» for the working and return the samples [phase, passability, pending mark] taken on the way."""
        self.page.evaluate(self.SAMPLER % {"target": working, "thing": thing(working)})
        close_working(self.page, working)
        wait_decision(self.page)
        self.page.wait_for(f"document.querySelector('{self.scheme(working)}').dataset.passability === 'closed'", timeout=4.0)
        self.page.evaluate("clearInterval(window.__sampler)")
        return self.page.evaluate("window.__samples")

    def test_detour(self):
        """Обход: В-12 is closed, the people of the zone get a longer route by the ramp."""
        self.open("detour")
        self.wait_drawn()
        self.select_on_scheme("worker-03")
        route = f'#scheme .route[data-worker="{thing("worker-03")}"]'
        self.wait_for_selector(route)
        before = self.attr(route, "data-workings").split()
        self.assertIn("w-12", before)
        self.assertIn("расчётный маршрут (модель): 412 м, около 5 мин 30 с, выход Ствол", self.card())

        samples = self.close_by_the_stand_controls("w-12")
        # Until the model confirms, the working is open and marked as waiting; it closes only with the record.
        for phase, passability, _ in samples:
            if passability == "closed":
                self.assertEqual(phase, "applied", f"the working closed before the acknowledgement: {samples}")
        self.assertIn(["sent", "open", True], samples, "the unconfirmed command is marked on its target")

        state = self.body()
        self.assertEqual((state["runState"], state["commands"], state["publications"]), ("paused", "enabled", "alive"))
        closed = self.drawn()[thing("w-12")]
        self.assertEqual((closed["passability"], closed.get("pending")), ("closed", None))
        self.assertTrue(self.count(self.scheme("w-12") + " .working__barrier"), "a barrier is drawn across the closed working")
        self.assertEqual(self.attr(self.scheme("w-12"), "aria-label").split(": ", 1)[0], "В-12")
        self.assertIn("проход закрыт (условие стенда)", self.attr(self.scheme("w-12"), "aria-label"))
        tags = plain(" | ".join(self.page.evaluate("[...document.querySelectorAll('#scheme .tag')].map((tag) => tag.textContent)")))
        self.assertIn("В-12 · проход закрыт", tags)
        self.assertEqual(self.text('[data-testid="status-conditions"]'), "Условия стенда: В-12 закрыта")
        self.assertIn("Участок Б — закрыт проход В-12", self.text('[data-testid="incident-strip"]'))
        self.assertEqual(self.counters(), {"in-danger": "0", "no-route": "0", "unknown": "0", "out": "0", "total": "14"})
        self.assertTrue(self.wait_banner("paused_decision", 3.0)["text"].startswith("Модель на паузе для выбора действия."))

        # The route of the selected worker is redrawn as the model published it.
        self.page.wait_for(f"!document.querySelector('{route}').dataset.workings.split(' ').includes('w-12')", timeout=4.0)
        after = self.attr(route, "data-workings").split()
        self.assertIn("w-03", after, "the detour goes by the ramp")
        self.assertEqual(self.attr(route, "data-reason"), "selection")
        sentence = "расчётный маршрут (модель): 655 м (длиннее на 243 м), около 8 мин 44 с, выход Съезд"
        self.assertIn(sentence, self.card())
        self.assertTrue(self.visible(f"{CARD} .card__head"), "the card is on the screen next to the decision dock")

        # The decision panel: three offered options with the forecast of the model.
        panel = self.decision()
        self.assertRegex(panel, r"Прогноз модели на 15 мин · рассчитан в 00:20:\d0")
        self.assertEqual(self.count(f'{DECISION} th[data-state="offered"]'), 3)
        # «все вышли» is one row with its time (clarity pass, A3).
        self.assertEqual(self.metric("option-withdraw-all", "forecast_all_out"), "да, за 9 мин 40 с")
        self.assertEqual((self.metric("option-stop-withdraw", "forecast_out"), self.metric("option-stop-withdraw", "forecast_all_out")),
                         ("4", "нет"))

        # One command, one effect, one journal entry with the identifier of the command.
        posts = self.wait_commands(1)
        self.assertEqual(len(posts), 1)
        self.assertEqual({key: posts[0]["body"][key] for key in ("type", "target", "run")},
                         {"type": "condition.close_working", "target": "w-12", "run": "run-0005"})
        self.assertTrue(posts[0]["effect_applied"])
        entries = self.page.evaluate("""[...document.querySelectorAll('[data-testid="journal-entry"][data-code="condition.set"]')]
          .map((node) => node.textContent.replace(/\\s+/g, ' '))""")
        self.assertEqual(len(entries), 1)
        self.assertIn("условие задано: «В-12 закрыта»", entries[0])
        self.assertIn("команда " + posts[0]["body"]["command_id"][:10], entries[0])

        # The list says the same as the card.
        self.show("list")
        self.assertIn(sentence, self.cells("worker-03")[5])
        self.assertEqual(self.attr(self.row("w-12"), "data-passability"), "closed")
        self.assert_only_contract_requests()

    def test_no_path(self):
        """Отсутствие пути: В-07 is closed, two workers have no route and no option brings them out."""
        self.open("no_path")
        self.wait_drawn()
        self.close_by_the_stand_controls("w-07")
        self.page.wait_for("document.querySelectorAll('#scheme .worker[data-egress=\"none\"]').length === 2", timeout=4.0)
        drawn = self.drawn()
        stranded = sorted(name for name, item in drawn.items() if item["kind"] == "worker" and item["egress"] == "none")
        self.assertEqual(stranded, [thing("worker-07"), thing("worker-08")])
        for name in ("worker-07", "worker-08"):
            self.assertEqual(drawn[thing(name)]["status"], "working", "no order to leave was given: the status does not change")
            shapes = self.page.evaluate(f"""(() => {{
              const node = document.querySelector('{self.scheme(name)}');
              const shown = (part) => getComputedStyle(node.querySelector(part)).display !== 'none';
              return [shown('.worker__none'), shown('.worker__ok'), node.getAttribute('aria-label')];
            }})()""")
            self.assertEqual(shapes[:2], [True, False], "a crossed square, not a circle")
            self.assertIn("нет расчётного маршрута", shapes[2])

        # The number of the strip is the number of the model, and the list shows as many rows.
        self.assertEqual(self.counters(), {"in-danger": "0", "no-route": "2", "unknown": "0", "out": "0", "total": "14"})
        self.assertIn("Участок В — закрыт проход В-07", self.text('[data-testid="incident-strip"]'))
        self.assertIn("Р-07, Р-08: нет расчётного маршрута · ни один вариант модели их не выводит",
                      self.text('[data-testid="situation-step-3"]'))

        # The decision panel says what the model cannot do.
        self.assertEqual(self.body()["dock"], "collapsed", "an incident brings the decision dock; at 1280x720 its bar lies over the stage")
        show_right(self.page, "decision")
        self.assertEqual(self.text('[data-testid="decision-no-path"]'),
                         "В графе модели нет открытого пути до выхода для Р-07, Р-08. Модель не рассчитывает, как выводить этих работников")
        self.assertEqual(self.text('[data-testid="decision-nobody-left"]'), "Ни один вариант модели не выводит этих работников")
        for option in ("option-observe", "option-stop-withdraw", "option-withdraw-all"):
            self.assertEqual(self.metric(option, "forecast_no_route"), "2", option)
            self.assertEqual(self.metric(option, "forecast_all_out"), "нет", option)

        # A worker in a normal zone without a route: the two axes stay apart, on the scheme, in the card and in the list.
        self.select_on_scheme("worker-07")
        card = self.card()
        self.assertIn("Р-07: нет расчётного маршрута. В графе модели нет открытого пути до выхода", card)
        self.assertIn("Это утверждение о графе модели, а не о реальной шахте", card)
        self.assertIn("участок: норма", card)
        self.assertEqual(self.drawn()[thing("worker-07")]["locationHazard"], "normal")
        self.assertEqual(self.count(f'#scheme .route[data-worker="{thing("worker-07")}"]'), 0, "no route line is invented")
        self.show("list")
        cells = self.cells("worker-07")
        self.assertEqual((cells[3], cells[5]), ("участок: норма", "нет расчётного маршрута: в графе модели нет открытого пути до выхода"))
        without_route = self.page.evaluate("""[...document.querySelectorAll('[data-testid="list"] tr[data-kind="worker"]')]
          .filter((row) => row.cells[5].textContent.includes('нет расчётного маршрута')).length""")
        self.assertEqual(without_route, 2, "as many rows as the strip counts")
        self.assertEqual(len(self.commands_logged()), 1)


# --------------------------------------------------------------------------
# потерянный датчик после danger
# --------------------------------------------------------------------------

class SensorLostTest(ScenarioTestCase):
    def test_sensor_lost_after_danger(self):
        """Потерянный датчик после danger: unknown now, and the last known danger stays in sight."""
        self.open("sensor_lost_after_danger")
        self.wait_drawn()
        self.assertEqual(self.body()["dock"], "collapsed",
                         "loaded in the middle of an incident: the decision dock is there (its bar, at 1280x720)")
        self.assertTrue(self.visible('[data-testid="situation-step-1"]'), "what changed is in sight")
        drawn = self.drawn()
        zone = drawn[thing("zone-c")]
        self.assertEqual((zone["hazard"], zone["quality"], zone["lastKnownHazard"]), ("unknown", "lost", "danger"))
        sensor = drawn[thing("sens-ext-05")]
        self.assertEqual((sensor["quality"], sensor["link"]), ("lost", "offline"))

        # Scheme: the tag of the zone in words, the dashed danger outline, the crossed sensor.
        label = self.attr(self.scheme("zone-c"), "aria-label")
        for words in ("Участок В: состояние неизвестно", "данные потеряны", "последнее известное: опасно в 00:13:30",
                      "новый вход запрещён моделью"):
            self.assertIn(words, label)
        self.assertTrue(self.visible(self.scheme("zone-c")), "the tag of the zone is on the screen")
        tag = plain(self.page.evaluate(f"document.querySelector('{self.scheme('zone-c')}').textContent"))
        self.assertIn("последнее известное: опасно в 00:13:30", tag)
        self.assertEqual(self.page.evaluate(f"[...document.querySelectorAll('{self.scheme('zone-c')} [data-sign]')].map((node) => node.dataset.sign)"),
                         ["unknown", "lastDanger", "blocked"])
        for name in ("w-20", "w-21"):
            working = drawn[thing(name)]
            self.assertEqual((working["hazard"], working["lastKnownHazard"], working["restriction"]), ("unknown", "danger", "blocked"))
            self.assertIn("working--last-danger", self.attr(self.scheme(name), "class"))
            self.assertEqual(self.count(self.scheme(name) + ' [data-sign="lastDanger"]'), 1, "the dashed octagon of a past danger")
        self.assertNotEqual(self.page.evaluate(
            f"getComputedStyle(document.querySelector('{self.scheme('sens-ext-05')} .sensor__lost')).display"), "none")
        self.assertIn("Э-05 · данные потеряны", plain(" | ".join(self.page.evaluate(
            "[...document.querySelectorAll('#scheme .tag')].map((tag) => tag.textContent)"))))

        # The numbers: nobody is counted in danger, two are counted as unknown.
        self.assertEqual(self.counters(), {"in-danger": "0", "no-route": "0", "unknown": "2", "out": "0", "total": "14"})
        self.assertEqual({drawn[thing(name)]["locationHazard"] for name in ("worker-07", "worker-08")}, {"unknown"})

        # Card: selected by a click on the tag of the zone.
        self.select_on_scheme("zone-c")
        self.assertEqual(self.text(f"{CARD} .card__code"), "Участок В", "the card shows the selection of the user")
        # The three axes are the badges of the card's head; the sentences under them start with the last known danger.
        badges = self.texts(f"{CARD} [data-testid='card-badges'] .badge")
        self.assertEqual(badges[:2], ["состояние неизвестно", "данные потеряны"])
        lead = self.texts(f"{CARD} [data-testid='card-lead'] span")
        self.assertRegex(lead[0], r"^последнее известное: опасно в 00:13:30 \(\d+ мин назад\)$")
        self.assertIn("новый вход запрещён моделью", lead)
        self.assertIn("причина состояния: данные датчика потеряны: датчик Э-05", lead)
        self.select_on_scheme("sens-ext-05")
        card = self.card()
        self.assertIn("данные потеряны", card)
        self.assertIn("нет связи", card)
        self.assertRegex(card, r"Последнее измерение в \d\d:\d\d:\d\d \(\d+ мин назад\) по времени модели")

        # List: unknown now and danger before are two separate marks of one cell.
        self.show("list")
        cells = self.cells("zone-c")
        self.assertRegex(cells[3], r"^состояние неизвестно последнее известное: опасно в 00:13:30 \(\d+ мин назад\)$")
        self.assertEqual(cells[4], "данные потеряны")
        self.assertIn("новый вход запрещён моделью", cells[5])
        self.assertRegex(self.cells("w-20")[3], r"^состояние неизвестно последнее известное: опасно в 00:13:30 \(\d+ мин назад\)$")
        self.assertEqual(self.cells("sens-ext-05")[4], "данные потеряны; нет связи")
        self.assertNotIn("норма", " ".join(self.cells("zone-c")), "the zone is nowhere called normal")
        self.assertEqual(self.cells("worker-07")[3], "участок: состояние неизвестно")

        # The journal says that two events are missing instead of passing them over.
        gap = self.page.evaluate("document.querySelector('[data-testid=\"journal-gap\"]').textContent")
        self.assertEqual(plain(gap), "Пропущено 2 события: № 218–219")


# --------------------------------------------------------------------------
# невалидный/неполный снимок
# --------------------------------------------------------------------------

class InvalidSnapshotTest(BrowserTestCase):
    """Each `invalid_*` scenario: the last full snapshot stays, the specific reason is shown, commands are blocked.

    The six scenarios turn invalid three seconds after their start, so they run side by side:
    one mock server and one page per scenario, started together. The pages show the stage in its
    scheme mode (`mode=scheme`): six 3D scenes booting at once in one software-rendered browser
    would not have their first valid publications drawn within those three seconds. The same rule
    in 3D is checked by Checklist3dTest.test_invalid_snapshot_keeps_the_last_scene.
    """

    CASES = {
        "invalid_missing_id": ("scene_missing_id", "в состоянии нет 1 объект: Р-14 (worker-14)"),
        "invalid_duplicate_id": ("scene_duplicate_id", "объект повторяется в состоянии: Р-14 (worker-14)"),
        "invalid_mixed_tick": ("scene_mixed_tick", "объект Г-02 (sens-geo-02) относится к другому моменту модели: tick"),
        "invalid_missing_field": ("missing_field", "у объекта Р-05 (worker-05) нет обязательного поля egress_status"),
        "invalid_contract_version": ("contract_version", "версия контракта данных 2, интерфейс работает с версией 1"),
        "invalid_no_metadata": ("no_metadata", "ответ платформы без метаданных (_modified): его нельзя считать актуальным"),
    }
    # From before the first script of the page: the moment of the last full snapshot it showed, and how many
    # people the scheme drew then. (Recorded from the start: a page may turn invalid before the others are loaded.)
    WATCH = """
      window.__full = [];
      new MutationObserver(() => {
        if (!document.body) return;
        const {snapshot, tick, seq} = document.body.dataset;
        if (snapshot === 'ok' && tick) window.__full = [tick, seq, document.querySelectorAll('#scheme .worker').length];
      }).observe(document, {attributes: true, childList: true, subtree: true});
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cases = {}
        for scenario in cls.CASES:
            mock = MockServer(scenario).start()
            cls.addClassCleanup(mock.stop)
            page = cls.browser.new_page()
            cls.addClassCleanup(page.close)
            page.add_init_script(cls.WATCH)
            mock.scenario(scenario)    # its three valid publications start now
            page.goto(mock.url + "/#/scheme?mode=scheme")
            cls.cases[scenario] = (mock, page)
        for scenario, (_, page) in cls.cases.items():
            page.wait_for("document.body.dataset.boot === 'ready' && window.__full.length > 0", timeout=10.0,
                          message=f"{scenario}: a full snapshot before the damaged ones")
            page.evaluate("window.__marker = 'same document'")

    def check(self, scenario):
        code, reason = self.CASES[scenario]
        mock, page = self.cases[scenario]
        page.wait_for("document.body.dataset.snapshot === 'invalid'", timeout=10.0, message=f"{scenario}: the snapshot is rejected")
        state = page.evaluate("Object.assign({}, document.body.dataset)")
        self.assertEqual((state["snapshotReason"], state["commands"], state["blockReason"]), (code, "blocked", "snapshot_invalid"))

        # The specific reason, in words, with the moment of the data that are still shown.
        banners = page.evaluate("""[...document.querySelectorAll('[data-testid="overlay-banner"]')].map((node) =>
          [node.dataset.code, node.dataset.reason, node.textContent.replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim()])""")
        self.assertEqual([(banner[0], banner[1]) for banner in banners], [("snapshot_invalid", code)])
        text = banners[0][2]
        self.assertTrue(text.startswith("Состояние не принято: " + reason), text)
        tick, seq, workers = page.evaluate("window.__full")
        self.assertRegex(text, rf"Показан последний полный снимок: \d\d:\d\d:\d\d UTC, тик {tick}\. Команды заблокированы$")

        # The last full snapshot stays on the screen while the model goes on publishing.
        wait_until(lambda: mock.state()["tick"] >= int(tick) + 30, timeout=8.0, message="the mock publishes further")
        later = page.evaluate("Object.assign({}, document.body.dataset)")
        self.assertEqual((later["tick"], later["seq"], later["snapshot"]), (tick, seq, "invalid"))
        self.assertEqual(page.evaluate("document.querySelectorAll('#scheme .worker').length"), workers)
        self.assertEqual(workers, 14)
        self.assertEqual(page.evaluate("document.querySelector('[data-testid=\"scheme-svg\"]').dataset.drawn"), "true")
        old = page.evaluate("(() => { const node = document.getElementById('old-data'); return [node.hidden, node.textContent]; })()")
        self.assertFalse(old[0], "the scheme is marked with the time of its data")
        self.assertRegex(plain(old[1]), rf"^Показаны данные на \d\d:\d\d:\d\d UTC, тик {tick}\. Текущее состояние неизвестно$")

        # Commands are blocked, visibly, and a press sends nothing: the dispatcher's actions and, in the stand drawer, the
        # conditions and the reset.
        self.assertEqual(plain(page.evaluate("document.querySelector('#actions .block-note').textContent")),
                         "Команды заблокированы: последний снимок отклонён")
        set_stand(page)
        buttons = page.evaluate("""[...document.querySelectorAll('button[data-command-type]')].filter((button) => button.getClientRects().length > 0)
          .map((button) => button.getAttribute('aria-disabled'))""")
        self.assertGreaterEqual(len(buttons), 8)
        self.assertEqual(set(buttons), {"true"}, "every command button is off")
        page.click(STOP)
        page.click(RESET)
        time.sleep(0.4)
        self.assertEqual(page.evaluate("document.querySelectorAll('[data-testid=\"dialog\"], [data-testid=\"pending\"]').length"), 0)
        self.assertEqual([entry for entry in mock.log()["entries"] if entry["kind"] == "command"], [])
        self.assertEqual(page.evaluate("window.__marker"), "same document")
        self.assertEqual(list(page.console_errors), [])

    def test_invalid_missing_id(self):
        self.check("invalid_missing_id")

    def test_invalid_duplicate_id(self):
        self.check("invalid_duplicate_id")

    def test_invalid_mixed_tick(self):
        self.check("invalid_mixed_tick")

    def test_invalid_missing_field(self):
        self.check("invalid_missing_field")

    def test_invalid_contract_version(self):
        self.check("invalid_contract_version")

    def test_invalid_no_metadata(self):
        self.check("invalid_no_metadata")


# --------------------------------------------------------------------------
# a publication of an unexpected form must not freeze any view
# --------------------------------------------------------------------------

class UnexpectedFormTest(ScenarioTestCase):
    """The answers of the mock are rewritten in the page (REWRITE_SHIFT) to forms no fixture publishes."""

    TICKS = """(() => ({
      body: document.body.dataset.tick || null,
      status: document.querySelector('[data-testid="status-model-time"]').dataset.tick || null,
      list: document.querySelector('[data-testid="list-table"]').dataset.tick || null,
      scheme: document.querySelector('[data-testid="scheme-svg"]').dataset.tick || null,
    }))()"""

    def wait_all_views_past(self, tick, timeout=8.0):
        """Wait until the status bar, the list and the scheme all show one tick later than `tick`; return it."""
        try:
            self.page.wait_for(f"""(() => {{
              const ticks = {self.TICKS};
              const values = Object.values(ticks);
              return values.every((value) => value !== null && value === values[0]) && Number(values[0]) > {tick};
            }})()""", timeout=timeout)
        except AssertionError as error:
            raise AssertionError(f"{error}\na view does not follow the state: {self.page.evaluate(self.TICKS)}") from None
        return int(self.page.evaluate(self.TICKS)["body"])

    def test_duplicate_and_object_conditions_and_a_null_cause_freeze_no_view(self):
        """M1: repeated conditions, conditions as objects and `causes: [null]` once stopped every view after the status bar."""
        self.page.add_init_script(REWRITE_SHIFT)
        self.open("normal")
        self.wait_drawn()
        start = self.wait_all_views_past(-1)
        self.page.evaluate("window.__patch = " + json.dumps({
            "shift": {"conditions": [
                "working_closed:w-07", "working_closed:w-07",
                {"kind": "sensor_lost", "target": "sens-ext-05"}, {"kind": "sensor_lost", "target": "sens-ext-05"},
                {"type": "instability", "target": "zone-b"},
                {"note": "x"}, {"note": "x"}, 42, None,
            ]},
            "incident": {"state": "active", "zone": "zone-b",
                         "causes": [None, "passage_closed", 7, {"trigger": "passage_closed", "subject": "w-07", "tick": 1200}]},
        }))
        chips = '[data-testid="status-conditions"] .chip'
        self.page.wait_for(f"document.querySelectorAll({json.dumps(chips)}).length > 0", timeout=6.0, message="the rewritten conditions")
        expected = ["В-07 закрыта", "Э-05 без связи", "Участок Б рост нестабильности",
                    '{"note":"x"} (неизвестное условие)', "42 (неизвестное условие)", "null (неизвестное условие)"]
        self.assertEqual(self.texts(chips), expected, "each condition once, whatever its form; an unknown form as its JSON text")

        # Every view goes on with the polls: three more publications are shown by all of them.
        tick = start
        for _ in range(3):
            later = self.wait_all_views_past(tick)
            self.assertGreater(later, tick)
            tick = later
        self.assertEqual(self.body()["link"], "ok")
        self.assertEqual(self.body()["snapshot"], "ok")
        self.assertEqual(self.texts(chips), expected)

        # The other places that read the same fields.
        active = self.page.evaluate("""[...document.querySelectorAll('[data-testid="conditions-active"] > li')].map((node) => [
          node.dataset.condition, node.querySelector('.chip').textContent.replace(/\\u00a0/g, ' '),
          node.querySelector('button') ? node.querySelector('button').dataset.commandType + ' ' + node.querySelector('button').dataset.commandTarget : null])""")
        self.assertEqual(active, [
            ["working_closed:w-07", "В-07 закрыта", "condition.open_working w-07"],
            ["sensor_lost:sens-ext-05", "Э-05 без связи", "condition.sensor_restored sens-ext-05"],
            ["instability:zone-b", "Участок Б рост нестабильности", "condition.instability_off zone-b"],
            ['{"note":"x"}', '{"note":"x"} (неизвестное условие)', None],
            ["42", "42 (неизвестное условие)", None],
            ["null", "null (неизвестное условие)", None],
        ], "an undo button only where the condition is known")
        # Step 1 of the strip: the zone and what happened to it (clarity pass, A4); the moment by the model clock (A8).
        self.assertEqual(self.text('[data-testid="situation-step-1"] .step__line'), "Участок Б — закрыт проход В-07")
        show_right(self.page, "decision")
        self.assertEqual(self.texts(f"{DECISION} .decision__causes li"), ["закрыт проход: В-07, в 00:20:00"])
        self.show("list")
        self.assertIn("закрыт проход (В-07)", self.cells("incident")[6])
        self.assertEqual(self.page.evaluate("document.querySelectorAll('[data-testid=\"list\"] tbody tr').length"), 75)
        self.show("scheme")
        self.assertEqual(self.wait_all_views_past(tick) > tick, True)
        self.assertEqual(self.page.console_errors, [], "no view threw")

    def test_duplicate_preset_ids_give_one_button(self):
        """M1: two presets with one id are one preset; the conditions panel is drawn and goes on."""
        self.page.add_init_script("""
          (() => {
            const realFetch = window.fetch;
            window.fetch = async function (input, init) {
              const response = await realFetch.call(this, input, init);
              const url = typeof input === 'string' ? input : input.url;
              if (!url.includes(':mine?') || !response.ok) return response;
              const body = await response.json();
              const presets = body.attributes.presets;
              body.attributes.presets = [...presets, {...presets[0], label: 'the same id again'}, null, 'text', {label: 'no id'}];
              return new Response(JSON.stringify(body), {status: response.status, statusText: response.statusText, headers: response.headers});
            };
          })();
        """)
        self.open("normal")
        self.wait_drawn()
        presets = self.page.evaluate("""[...document.querySelectorAll('[data-testid="conditions-panel"] [data-preset]')]
          .map((node) => [node.dataset.preset, node.querySelector('button').textContent])""")
        self.assertEqual([item[0] for item in presets], ["p-detour", "p-no-path"])
        self.assertNotIn("the same id again", [item[1] for item in presets])
        set_stand(self.page)
        self.assertTrue(self.visible(f'{CONDITIONS} select'))
        self.wait_seq(2)
        self.assertEqual(self.page.console_errors, [])


# --------------------------------------------------------------------------
# несовпадение topology_version
# --------------------------------------------------------------------------

class TopologyTest(ScenarioTestCase):
    def test_topology_version_mismatch(self):
        """Несовпадение topology_version: no picture of the mine in either mode of the stage, a list without states, no commands."""
        self.open("topology_mismatch", ready=False)
        state = self.wait_body(10.0, boot="ready", snapshot="invalid")
        self.assertEqual((state["snapshotReason"], state["commands"]), ("topology_mismatch", "blocked"))
        self.assertNotIn("tick", state, "no state was ever accepted")
        banner = self.wait_banner("topology_mismatch", 3.0)
        self.assertEqual(banner["text"], "Схема не показана: версия топологии в двойниках (t1) не совпадает с версией модели (t2). "
                                         "Вид «Список» доступен. Команды заблокированы")

        # The 3D stage (the default mode): the banner says why, and no model of the wrong topology is built.
        self.assertEqual(self.attr("#stage", "data-stage-mode"), "3d")
        time.sleep(2.0)    # time for a scene to be built, if one were going to be
        stage = self.page.evaluate("Object.assign({}, document.getElementById('stage').dataset)")
        self.assertIn(stage.get("levels"), (None, "0"), f"no slab of a topology the model does not use: {stage}")
        self.assertIn(stage.get("workings"), (None, "0"), f"and no working: {stage}")
        self.assertEqual(self.count("#stage-3d [data-thing-id]"), 0, "no label of an object of the wrong topology")
        self.assertTrue(self.visible('[data-testid="overlay-banner"][data-code="topology_mismatch"]'), "the banner is in sight")

        # The SVG scheme, its other mode (by the route, as a link opens it).
        self.page.evaluate("location.hash = '#/scheme?mode=scheme'")
        self.page.wait_for("document.querySelector('#stage').dataset.stageMode === 'scheme'", timeout=3.0)
        self.assertEqual(self.attr('[data-testid="scheme-svg"]', "data-drawn"), "false")
        self.assertEqual(self.count("#scheme [data-thing-id]"), 0, "a scheme of the wrong topology is not drawn")
        self.assertEqual(self.text("#scheme .scheme__empty"), "Схема не показана")
        self.assertTrue(self.visible('[data-testid="legend"]'), "the legend stays")
        self.assertEqual(self.text('[data-testid="status-model-time"]'), "Модель: нет данных")
        self.assertEqual(self.counters(), {name: "—" for name in ("in-danger", "no-route", "unknown", "out", "total")})

        self.show("list")
        self.assertEqual(self.count('[data-testid="list"] tbody tr'), 75, "the list is available")
        states = self.page.evaluate("""[...document.querySelectorAll('[data-testid="list"] tbody tr')].map((row) =>
          [row.dataset.kind, row.dataset.hazard || null, row.cells[6].textContent])""")
        for kind, hazard, value in states:
            self.assertNotEqual(hazard, "normal", "nothing is normal by default")
            if kind != "level":
                self.assertEqual(value, "состояние не получено")
        self.assertTrue(self.is_off(STOP))
        # The attributes are asked for again, but not more often than once in five seconds.
        time.sleep(1.5)
        mine_reads = [entry["t_ms"] for entry in self.platform_log() if entry["path"] == MINE_PATH]
        self.assertGreaterEqual(len(mine_reads), 1)
        gaps = [later - earlier for earlier, later in zip(mine_reads, mine_reads[1:])]
        self.assertTrue(all(gap >= 4500 for gap in gaps), f"attribute re-reads are too frequent: {gaps}")
        self.assertEqual(self.commands_logged(), [])

    def test_topology_change_recovers(self):
        """The topology changes on the platform: the attributes are read again and the screen recovers without a reload."""
        self.open("topology_change")
        self.wait_drawn()
        self.page.evaluate("""(() => {
          window.__marker = 'same document';
          window.__seen = [];
          new MutationObserver(() => {
            const value = document.body.dataset.snapshot + ':' + (document.body.dataset.snapshotReason || '');
            if (window.__seen[window.__seen.length - 1] !== value) window.__seen.push(value);
          }).observe(document.body, {attributes: true});
        })()""")
        self.assertEqual(self.count("#scheme .working"), 36)
        self.assertEqual(self.count(self.scheme("w-37")), 0)
        self.page.wait_for(f"!!document.querySelector('{self.scheme('w-37')}')", timeout=12.0,
                           message="the working of the new topology is drawn")
        state = self.wait_body(4.0, snapshot="ok", commands="enabled", link="ok")
        self.assertEqual(self.count("#scheme .working"), 37)
        self.assertEqual(self.banners(), [])
        self.assertEqual(self.page.evaluate("window.__marker"), "same document", "no reload")
        self.assertEqual(self.page.evaluate("performance.getEntriesByType('navigation').length"), 1)
        seen = self.page.evaluate("window.__seen")
        self.assertIn("invalid:topology_mismatch", seen, f"the mismatch was noticed before the attributes were read again: {seen}")
        self.assertEqual(seen[-1], "ok:")
        self.assertGreaterEqual(len([entry for entry in self.platform_log() if entry["path"] == MINE_PATH]), 2)
        self.show("list")
        self.assertEqual(self.count('[data-testid="list"] tbody tr'), 76)
        self.assertIn("длина 110 м", self.cells("w-19")[6], "the changed attribute of an old twin is shown")
        self.assertGreater(int(self.body()["tick"]), int(state["tick"]) - 1)


# --------------------------------------------------------------------------
# пауза с живым heartbeat; застывший publication_seq
# --------------------------------------------------------------------------

class HeartbeatTest(ScenarioTestCase):
    WATCH = """(() => {
      window.__states = [];
      const note = () => {
        const {publications, link, commands, tick, seq} = document.body.dataset;
        const banners = [...document.querySelectorAll('[data-testid="overlay-banner"]')].map((node) => node.dataset.code).join('+');
        const value = [publications, link, commands, banners].join(' ');
        const last = window.__states[window.__states.length - 1];
        if (!last || last.value !== value) window.__states.push({value, at: Math.round(performance.now()), tick, seq});
        window.__seqAt = window.__seq === seq ? window.__seqAt : Math.round(performance.now());
        window.__seq = seq;
      };
      note();
      new MutationObserver(note).observe(document.body, {attributes: true, subtree: true, childList: true});
    })()"""

    def test_pause_with_live_heartbeat(self):
        """Пауза с живым heartbeat: model time stands, publications go on, nothing reads as «stopped»."""
        self.open("paused_heartbeat")
        first = self.wait_body(5.0, publications="alive", runState="paused")
        self.page.evaluate(self.WATCH)
        started = time.monotonic()
        time.sleep(8.3)
        elapsed = time.monotonic() - started
        later = self.body()
        self.assertGreaterEqual(elapsed, 8.0)
        self.assertEqual(later["tick"], first["tick"], "model time stands still")
        self.assertGreaterEqual(int(later["seq"]) - int(first["seq"]), 7, "the heartbeat goes on")
        states = self.page.evaluate("window.__states")
        self.assertEqual([item["value"] for item in states], ["alive ok enabled paused_decision"],
                         f"for {elapsed:.1f} s the screen never left the normal paused state: {states}")
        self.assertEqual(self.wait_banner("paused_decision", 1.0)["text"],
                         "Модель на паузе для выбора действия. Время модели стоит, публикации идут")
        self.assertRegex(self.text('[data-testid="status-model-time"]'), r"модель на паузе для выбора действия$")
        # At 1280x720 the top bar says the publications only when they are not going on; the words are in the DOM.
        self.assertEqual(plain(self.page.evaluate("document.querySelector('[data-testid=\"status-publications\"]').textContent")),
                         "публикации идут")
        self.assertRegex(self.text('[data-testid="status-age"]'), r"^данные [0-2] с назад$")
        show_right(self.page, "decision")
        self.assertEqual(self.text('[data-testid="decision-pause"]'), "Модель на паузе для выбора действия")
        self.assertNotIn("data-old-data", self.page.evaluate("document.body.getAttributeNames()"))
        self.assertFalse(self.is_off(STOP), "commands are accepted during the pause")

    def test_frozen_publication_seq(self):
        """Отвечающий сервер с застывшим publication_seq: reported after five seconds, the link itself stays fine."""
        self.open("frozen_seq")
        self.wait_body(5.0, publications="alive")
        self.page.evaluate(self.WATCH)
        self.wait_body(14.0, publications="stopped")
        timing = self.page.evaluate("({states: window.__states, seqAt: window.__seqAt, now: Math.round(performance.now())})")
        stopped = next(item for item in timing["states"] if item["value"].startswith("stopped"))
        waited = stopped["at"] - timing["seqAt"]
        self.assertTrue(4300 <= waited <= 6600, f"reported {waited} ms after the last new publication; the threshold is 5 s")
        state = self.body()
        self.assertEqual((state["link"], state["snapshot"], state["commands"], state["blockReason"], state["oldData"]),
                         ("ok", "ok", "blocked", "publications_stopped", "true"))
        banner = self.wait_banner("publications_stopped", 2.0)
        self.assertRegex(banner["text"], rf"^Публикации модели остановились\. Платформа отвечает, но номер публикации не меняется\. "
                                         rf"Показано последнее состояние: \d\d:\d\d:\d\d UTC, тик {state['tick']}\. Команды заблокированы$")
        self.assertEqual(self.banner_codes(), ["publications_stopped"])
        self.assertEqual(self.text('[data-testid="status-link"]'), "Платформа: связь есть", "the platform does answer")
        self.assertEqual(self.text('[data-testid="status-publications"]'), "публикации остановились")
        self.assertRegex(self.text("#old-data"), rf"^Показаны данные на \d\d:\d\d:\d\d UTC, тик {state['tick']}\. Текущее состояние неизвестно$")
        self.assertTrue(self.is_off(STOP))
        polls = len([entry for entry in self.platform_log() if entry["path"] == SHIFT_PATH])
        time.sleep(2.2)
        self.assertGreaterEqual(len([entry for entry in self.platform_log() if entry["path"] == SHIFT_PATH]), polls + 2,
                                "the page goes on asking")
        self.assertEqual(self.body()["publications"], "stopped")

    def test_frozen_publication_seq_old_at_first_load(self):
        """`frozen_seq_old`: a state that was old already when the page opened is not shown as current, not even for five seconds."""
        self.page.add_init_script("""new MutationObserver(() => {
          if (!window.__stoppedAt && document.body && document.body.dataset.publications === 'stopped') window.__stoppedAt = performance.now();
          if (!window.__drawnAt && document.querySelector('#scheme .worker')) window.__drawnAt = performance.now();
        }).observe(document, {attributes: true, subtree: true, childList: true});""")
        self.open("frozen_seq_old", ready=False)
        state = self.wait_body(10.0, boot="ready", publications="stopped")
        self.wait_drawn()
        timing = self.page.evaluate("[window.__stoppedAt, window.__drawnAt]")
        self.assertLessEqual(timing[0] - timing[1], 300, f"reported with the first picture, not five seconds later: {timing}")
        self.assertEqual((state["commands"], state["blockReason"], state["link"]), ("blocked", "publications_stopped", "ok"))
        age = re.fullmatch(r"данные (\d+) с назад", self.text('[data-testid="status-age"]'))
        self.assertIsNotNone(age)
        self.assertTrue(28 <= int(age.group(1)) <= 34, "the age starts from HTTP Date minus _modified")
        self.assertTrue(self.wait_banner("publications_stopped", 1.0)["text"].startswith("Публикации модели остановились."))
        self.assertFalse(self.page.evaluate("document.getElementById('old-data').hidden"))


# --------------------------------------------------------------------------
# HTTP failure
# --------------------------------------------------------------------------

class LinkFailureTest(ScenarioTestCase):
    WATCH = """(() => {
      window.__marker = 'same document';
      window.__link = [];
      const place = () => [...document.querySelectorAll('#scheme .worker')].map((node) => {
        const box = node.getBoundingClientRect();
        return node.dataset.thingId.slice(-2) + ':' + box.x.toFixed(1) + ',' + box.y.toFixed(1);
      }).join(' ');
      const failed = () => performance.getEntriesByType('resource')
        .filter((entry) => entry.name.includes(':shift?') && entry.responseStatus >= 500).length;
      window.__place = place;
      let last = document.body.dataset.link;
      new MutationObserver(() => {
        const value = document.body.dataset.link;
        if (value === last) return;
        last = value;
        const event = {link: value, at: Math.round(performance.now()), failed: failed(), place: place(),
          glide: getComputedStyle(document.querySelector('#scheme .worker')).transitionDuration, later: []};
        window.__link.push(event);
        // Read twice after the strip took the banner's line and the picture was fitted anew.
        for (const delay of [500, 900]) setTimeout(() => event.later.push(place()), delay);
      }).observe(document.body, {attributes: true, attributeFilter: ['data-link']});
      let seq = document.body.dataset.seq;
      window.__fullAt = Math.round(performance.now());
      new MutationObserver(() => {
        if (document.body.dataset.seq !== seq) { seq = document.body.dataset.seq; window.__fullAt = Math.round(performance.now()); }
      }).observe(document.body, {attributes: true, attributeFilter: ['data-seq']});
    })()"""

    def test_http_failure_freezes_goes_stale_then_unavailable_and_recovers(self):
        """HTTP failure while people are walking out: stop at once, stale in 2 s, unavailable after three polls, recovery without a reload."""
        self.open("detour")
        self.wait_drawn()
        close_working(self.page, "w-12")
        wait_decision(self.page)
        execute_option(self.page, "option-withdraw-all")
        self.page.wait_for("document.querySelectorAll('#scheme .worker[data-status=\"moving_to_exit\"]').length >= 10"
                           " && document.body.dataset.runState === 'running'", timeout=10.0, message="people are walking")
        show_right(self.page, "card")
        self.page.evaluate(self.WATCH)
        # While the link is fine the markers move from one published position to the next, gliding.
        first = self.page.evaluate("window.__place()")
        self.assertEqual(self.page.evaluate("getComputedStyle(document.querySelector('#scheme .worker')).transitionDuration"), "0.6s")
        self.wait_seq(2)
        self.assertNotEqual(self.page.evaluate("window.__place()"), first, "the markers move between polls")
        before = self.drawn()
        tick = self.body()["tick"]

        self.mock.fault("http_502")
        state = self.wait_body(10.0, link="unavailable")
        time.sleep(0.6)
        events = self.page.evaluate("({link: window.__link, fullAt: window.__fullAt})")
        seen = {event["link"]: event for event in events["link"]}
        self.assertEqual([event["link"] for event in events["link"]], ["degraded", "stale", "unavailable"])

        # The first failed poll: the glide is switched off and no marker moves any more.
        degraded = seen["degraded"]
        self.assertEqual(degraded["failed"], 1, "the link degrades on the first failed poll")
        self.assertEqual(degraded["glide"], "0s", "position transitions are off the moment the link is not fine")
        # (The banner takes a line, so the scheme is fitted anew once, without a glide; after that nothing moves.)
        self.assertEqual(degraded["later"][0], degraded["later"][1], "no marker moved after the first failure")
        frozen = self.page.evaluate("window.__place()")

        # Two seconds without a full snapshot: stale, commands blocked. Three failed polls: unavailable.
        self.assertTrue(1800 <= seen["stale"]["at"] - events["fullAt"] <= 2700,
                        f"stale {seen['stale']['at'] - events['fullAt']} ms after the last full snapshot")
        self.assertEqual(seen["unavailable"]["failed"], 3, "«Платформа недоступна» after three failed polls")
        self.assertEqual((state["commands"], state["blockReason"], state["tick"], state["oldData"]),
                         ("blocked", "platform_unavailable", tick, "true"))
        banner = self.wait_banner("platform_unavailable", 2.0)
        self.assertRegex(banner["text"], rf"^Платформа недоступна \(HTTP 502\)\. Показаны данные на \d\d:\d\d:\d\d UTC, тик {tick}\. "
                                         r"Текущее состояние неизвестно$")
        self.assertEqual(self.text('[data-testid="status-link"]'), "Платформа: недоступна (HTTP 502)")
        self.assertTrue(self.is_off(STOP))

        # The scheme says how old it is, and nothing became normal (or anything else) while the platform was away.
        self.assertTrue(self.visible("#old-data"))
        self.assertRegex(self.text("#old-data"), rf"^Показаны данные на \d\d:\d\d:\d\d UTC, тик {tick}\. Текущее состояние неизвестно$")
        box = self.page.evaluate("""(() => {
          const mark = document.getElementById('old-data').getBoundingClientRect();
          const stage = document.getElementById('stage').getBoundingClientRect();
          return [mark.bottom <= stage.top + 1, mark.left >= stage.left - 4 && mark.right <= stage.right + 4,
                  getComputedStyle(document.getElementById('centre')).outlineStyle];
        })()""")
        self.assertEqual(box, [True, True, "dashed"], "the mark stands right above the stage, inside its dashed frame")
        self.assertEqual(self.text(".old-tag"), "последние полученные данные:")
        self.assertEqual(self.drawn(), before, "every drawn state is the one of the last full snapshot")
        time.sleep(1.2)
        self.assertEqual(self.page.evaluate("window.__place()"), frozen)

        # Recovery: the first full snapshot brings everything back, in the same document.
        self.mock.fault("none")
        recovered = self.wait_body(8.0, link="ok", snapshot="ok", commands="enabled")
        self.assertGreater(int(recovered["tick"]), int(tick))
        self.wait_body(4.0, publications="alive")
        self.assertEqual(self.banners(), [])
        self.assertTrue(self.page.evaluate("document.getElementById('old-data').hidden"))
        self.assertEqual(self.page.evaluate("window.__marker"), "same document")
        self.assertEqual(self.page.evaluate("performance.getEntriesByType('navigation').length"), 1)
        self.assertNotEqual(self.page.evaluate("window.__place()"), frozen, "the markers are at the newly published positions")
        self.assertEqual(self.page.evaluate("getComputedStyle(document.querySelector('#scheme .worker')).transitionDuration"), "0.6s")


# --------------------------------------------------------------------------
# pending / rejected / timeout команды; повтор с тем же id
# --------------------------------------------------------------------------

class CommandsTest(ScenarioTestCase):
    def test_pending_rejected_and_timeout_commands(self):
        """Pending, rejected, and no acknowledgement in five seconds: what each looks like, and what it does not change."""
        self.open("commands")
        self.wait_drawn()
        close_working(self.page, "w-12")
        waiting = self.wait_pending("w-12", "sent", 3.0)
        sent_at = time.monotonic()
        self.assertEqual(waiting["what"], "Условие стенда: В-12 закрыта", "a condition of the stand, not a command (clarity pass, A6)")
        self.assertRegex(waiting["text"], r"^Команда отправлена, не подтверждена \(\d с\)$")
        self.assertRegex(waiting["id"], r"^c-[0-9a-f]{32}$")
        self.assertEqual(self.text("#pending .panel__title"), "Отправленные команды")
        # The scheme marks the target and keeps its published state.
        target = self.drawn()[thing("w-12")]
        self.assertEqual(target["passability"], "open")
        self.assertIn("pending", target, "the target carries the mark of an unconfirmed command")
        self.assertEqual(self.count(self.scheme("w-12") + " .working__mark--pending"), 1)
        self.assertEqual(self.count(self.scheme("w-12") + " .working__barrier"), 0)
        self.assertIn("команда отправлена, не подтверждена", self.attr(self.scheme("w-12"), "aria-label"))
        self.assertTrue(self.is_off(CLOSE), "the same command cannot be sent again while it waits")

        close_working(self.page, "w-07")
        rejected = self.wait_pending("w-07", "rejected", 4.0)
        self.assertEqual(rejected["text"], "Команда отклонена: недопустимо в текущем состоянии (not_allowed_in_state)")
        self.assertEqual(rejected["buttons"], ["Закрыть сообщение"])
        refused = self.drawn()[thing("w-07")]
        self.assertEqual((refused["passability"], refused.get("pending")), ("open", None))

        silent = self.wait_pending("w-12", "no_ack", 8.0)
        waited = time.monotonic() - sent_at
        self.assertTrue(4.3 <= waited <= 7.0, f"the threshold is 5 s of wall time, measured {waited:.1f} s")
        self.assertEqual(silent["text"], "Нет подтверждения 5 с. Команда могла не дойти")
        self.assertEqual(silent["buttons"], ["Повторить с тем же идентификатором", "Снять ожидание"])
        self.assertEqual(self.drawn()[thing("w-12")]["passability"], "open")
        self.assertEqual(self.text('[data-testid="status-conditions"]'), "Условия стенда: нет")
        posts = self.commands_logged()
        self.assertEqual([(post["body"]["target"], post["status"], post["effect_applied"]) for post in posts],
                         [("w-12", 202, False), ("w-07", 202, False)])
        self.assertEqual(posts[1]["ack"]["status"], "rejected")
        self.press_in_pending("w-12", "btn-dismiss")
        self.press_in_pending("w-07", "btn-dismiss")
        self.page.wait_for("document.getElementById('pending').childNodes.length === 0", timeout=2.0)

    def test_retry_with_the_same_id(self):
        """Повтор с тем же id: the identical id and body twice in the log of the mock, exactly one effect."""
        self.open("commands")
        self.wait_drawn()
        choose(self.page, ZONE_SELECT, "zone-b")
        self.assertEqual(self.drawn()[thing("zone-b")]["workState"], "working")
        self.page.click(STOP)
        unknown = self.wait_pending("zone-b", "delivery_unknown", 4.0)
        self.assertEqual(unknown["what"], "Остановить участок: Участок Б")
        self.assertEqual(unknown["text"], "Результат доставки неизвестен (HTTP 503). Команда могла дойти до модели")
        self.assertEqual(unknown["buttons"], ["Повторить с тем же идентификатором", "Снять ожидание"])
        self.assertEqual(self.drawn()[thing("zone-b")]["workState"], "working", "nothing changes on an unknown delivery")

        self.press_in_pending("zone-b", "btn-retry")
        applied = self.wait_pending("zone-b", "applied", 6.0)
        self.assertEqual(applied["id"], unknown["id"], "the retry is the same command")
        self.assertEqual(applied["text"], "Команда применена · попыток: 2")
        self.page.wait_for(f"document.querySelector('{self.scheme('zone-b')}').dataset.workState === 'stopped'", timeout=3.0)
        self.assertIn("остановлен", self.attr(self.scheme("zone-b"), "aria-label"))

        posts = self.wait_commands(2, "action.stop_zone")
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0]["body"], posts[1]["body"])
        self.assertEqual(posts[0]["body"], {"command_id": unknown["id"], "type": "action.stop_zone", "target": "zone-b",
                                            "run": "run-0005"})
        sent = [request["post_data"] for request in list(self.page.requests) if request["method"] == "POST"]
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0], sent[1], "byte for byte the same body")
        self.assertEqual([(post["status"], post["delivered"], post["effect_applied"]) for post in posts],
                         [(503, False, False), (202, True, True)], "exactly one effect")
        applied_events = self.page.evaluate("""[...document.querySelectorAll('[data-testid="journal-entry"][data-code="command.applied"]')]
          .map((node) => node.textContent)""")
        self.assertEqual(len([event for event in applied_events if unknown["id"][:10] in event]), 1,
                         "one journal entry for the command")

    def test_post_timeout_is_unknown_delivery_then_retry(self):
        """POST timeout: «Результат доставки неизвестен», then a retry with the same id."""
        self.open("commands")
        self.wait_drawn()
        choose(self.page, ZONE_SELECT, "zone-b")
        self.wait_seq(1)
        self.mock.fault("hang")
        self.page.click(STOP)
        started = time.monotonic()
        unknown = self.wait_pending("zone-b", "delivery_unknown", 6.0)
        waited = time.monotonic() - started
        self.assertTrue(2.6 <= waited <= 4.2, f"the request timeout is 3 s, measured {waited:.1f} s")
        self.assertEqual(unknown["text"], "Результат доставки неизвестен (нет ответа за 3 с). Команда могла дойти до модели")
        self.assertEqual(self.drawn()[thing("zone-b")]["workState"], "working", "no optimistic change")
        # The platform does not answer the polls either: everything is blocked, the retry included, and says why.
        self.wait_body(3.0, commands="blocked")
        retry = '[data-testid="pending"][data-command-target="zone-b"] [data-testid="btn-retry"]'
        self.assertTrue(self.is_off(retry))
        self.assertRegex(self.text("#pending .block-note"), r"^Команды заблокированы: ")

        self.mock.fault("none")
        self.wait_body(10.0, link="ok", commands="enabled")
        self.assertFalse(self.is_off(retry))
        self.page.click(retry)
        # The fixture answers the first POST it sees for this command with 503: unknown once more, the same id again.
        again = self.wait_pending("zone-b", "delivery_unknown", 4.0)
        self.assertEqual(again["id"], unknown["id"])
        self.assertTrue(again["text"].startswith("Результат доставки неизвестен (HTTP 503)"), again["text"])
        self.page.click(retry)
        applied = self.wait_pending("zone-b", "applied", 6.0)
        self.assertEqual((applied["id"], applied["text"]), (unknown["id"], "Команда применена · попыток: 3"))
        self.page.wait_for(f"document.querySelector('{self.scheme('zone-b')}').dataset.workState === 'stopped'", timeout=3.0)

        sent = [request["post_data"] for request in list(self.page.requests) if request["method"] == "POST"]
        self.assertEqual(len(sent), 3)
        self.assertEqual(len(set(sent)), 1, "three attempts, one body")
        self.assertEqual(json.loads(sent[0])["command_id"], unknown["id"])
        posts = self.wait_commands(2, "action.stop_zone")
        self.assertEqual([(post["status"], post["delivered"], post["effect_applied"]) for post in posts],
                         [(503, False, False), (202, True, True)], "the mock read two of them, and one had an effect")
        hung = [entry for entry in self.platform_log() if entry["method"] == "POST" and entry.get("fault") == "hang"]
        self.assertEqual(len(hung), 1)


# --------------------------------------------------------------------------
# reset
# --------------------------------------------------------------------------

class ResetTest(ScenarioTestCase):
    def test_reset(self):
        """Reset: resetting state, a new run, the acknowledgement found in the new run, the interrupted run in the archive."""
        self.open("reset")
        self.wait_drawn()
        self.assertEqual((self.body()["run"], self.body()["dock"]), ("run-0005", "collapsed"))
        self.assertEqual(self.drawn()[thing("w-12")]["passability"], "closed")
        self.page.evaluate("window.__marker = 'same document'")

        # The dialog names the run; «Отмена» sends nothing. The reset is in the stand drawer.
        set_stand(self.page)
        self.page.click(RESET)
        self.wait_for_selector('[data-testid="dialog"]', 3.0)
        dialog = self.text('[data-testid="dialog"]')
        self.assertIn("Начать новый прогон?", dialog)
        self.assertIn("Текущий прогон run-0005 будет завершён с пометкой «прерван сбросом» и останется в сравнении", dialog)
        self.page.click('[data-testid="dialog-cancel"]')
        self.page.wait_for("!document.querySelector('[data-testid=\"dialog\"]')", timeout=3.0)
        time.sleep(0.5)
        self.assertEqual(self.commands_logged(), [])
        self.assertEqual(self.pending(), [])

        self.page.click(RESET)
        self.wait_for_selector('[data-testid="dialog-confirm"]', 3.0)
        self.page.click('[data-testid="dialog-confirm"]')
        sent = self.wait_pending("run", "sent", 3.0, "run.reset")
        self.assertEqual(sent["what"], "Полный сброс прогона")
        blocked = self.wait_body(3.0, commands="blocked")
        self.assertEqual(blocked["blockReason"], "own_reset_pending")
        banner = self.wait_banner("resetting", 3.0)
        self.assertEqual(banner["text"], "Выполняется сброс. Новый прогон ещё не начался. Команды заблокированы")
        # The model says «resetting»: the old run is still on the screen, nothing is cleared ahead of the data.
        resetting = self.wait_body(5.0, runState="resetting")
        self.assertEqual(resetting["run"], "run-0005")
        self.assertRegex(self.text('[data-testid="status-model-time"]'), r"выполняется сброс$")
        self.assertEqual(self.drawn()[thing("w-12")]["passability"], "closed")
        self.assertTrue(self.is_off(RESET))
        self.assertTrue(self.is_off(STOP))

        # The new run.
        fresh = self.wait_body(10.0, run="run-0006", runState="running")
        self.assertLess(int(fresh["tick"]), 100, "the new run has its own model time")
        applied = self.wait_pending("run", "applied", 4.0, "run.reset")
        self.assertEqual((applied["id"], applied["text"]), (sent["id"], "Команда применена"),
                         "the acknowledgement is found in the commands of the new run")
        self.wait_body(4.0, commands="enabled", snapshot="ok")
        self.assertNotIn("resetting", self.banner_codes())
        self.assertEqual(self.text('[data-testid="status-conditions"]'), "Условия стенда: нет")
        self.assertEqual(self.drawn()[thing("w-12")]["passability"], "open")
        self.assertIn("Инцидентов нет", plain(self.page.evaluate("document.querySelector('[data-testid=\"incident-strip\"]').textContent")))
        self.assertEqual(self.body()["dock"], "none", "the incident is gone: so is the decision dock")
        self.assertEqual(self.page.evaluate("window.__marker"), "same document")
        ack = next(record for record in self.mock.state()["acknowledgements"] if record["id"] == sent["id"])
        self.assertEqual((ack["run"], ack["new_run"], ack["status"]), ("run-0005", "run-0006", "applied"))
        self.assertEqual([post["body"] for post in self.commands_logged()],
                         [{"command_id": sent["id"], "type": "run.reset", "target": "run", "run": "run-0005"}])

        # The archive: the interrupted run is there, and it is never a completed withdrawal.
        self.show("runs")
        row = '[data-testid="runs-table"] tr[data-run="run-0005"][data-series="actual"]'
        self.wait_for_selector(row, 6.0)
        self.assertEqual(self.attr(row, "data-completion"), "reset")
        self.assertEqual(self.attr(row, "data-comparable"), "false")
        self.assertEqual(self.text(row + ' [data-testid="run-ending"]'), "прерван сбросом")
        self.assertEqual(self.text(row + ' [data-testid="run-mark"]'), "итог неполный, в сравнение не входит")
        self.assertEqual(self.text(row + ' td[data-metric="last_out_s"]'), "—", "no time of a withdrawal that did not happen")
        self.assertNotEqual(self.text(row + ' td[data-metric="all_out"]'), "да")
        words = self.text(row)
        self.assertNotIn("вывод завершён", words)
        self.assertNotIn("вывод персонала завершён", words)
        self.assertEqual(self.count('[data-testid="runs-table"] tr[data-series="actual"]'), 5)
        # The journal goes on across the runs and marks the entries of the old one.
        old = self.page.evaluate("document.querySelector('[data-testid=\"journal-entry\"][data-code=\"run.reset\"]').textContent")
        self.assertIn("run-0005: прогон прерван сбросом", plain(old))
        self.assertIn("другой прогон: run-0005", plain(old))


# --------------------------------------------------------------------------
# неполный вывод без last_out_s; отсутствие прогноза
# --------------------------------------------------------------------------

class ResultsTest(ScenarioTestCase):
    def test_incomplete_withdrawal_without_last_out_s(self):
        """Неполный вывод без last_out_s: not everyone is out, so no time «until everyone is out» is shown anywhere."""
        self.open("withdrawal_incomplete")
        self.wait_drawn()
        self.assertEqual(self.body()["dock"], "collapsed", "an incident that is over keeps its dock with the result")
        self.assertEqual(self.counters(), {"in-danger": "0", "no-route": "2", "unknown": "0", "out": "12", "total": "14"})
        self.assertIn("Инцидент завершён", self.text('[data-testid="incident-strip"]'))

        show_right(self.page, "decision")
        fact = f'{DECISION} [data-testid="decision-fact"][data-option="option-withdraw-all"]'
        self.assertEqual(self.text(fact + " .decision__alert"),
                         "Вывод не завершён: 2 работника без расчётного маршрута. Это за пределами того, что решает модель")
        # «все вышли — нет», and the time has no row of its own (clarity pass, A3).
        self.assertEqual(self.text(fact + ' td[data-metric="actual_all_out"]'), "нет")
        self.assertEqual(self.text(fact + ' td[data-metric="actual_out"]'), "12")
        self.assertEqual(self.text(fact + ' td[data-metric="actual_no_route"]'), "2")
        # Forecast and fact are two columns under two headings; for this run neither holds a time, for any option.
        self.assertEqual(self.texts(fact + " thead th")[1:], ["прогноз модели", "факт прогона"])
        times = self.page.evaluate("""[...document.querySelectorAll('#decision td[data-metric$="all_out"]')].map((cell) => cell.textContent)""")
        self.assertEqual(len(times), 5, "the fact, its forecast, and the forecast of each of the three options")
        for value in times:
            self.assertNotRegex(value, r"\d", f"a time is shown for a withdrawal that is not complete: {value!r}")

        # Scheme: the zone says «вывод не завершён», the two workers stand where they were, without a route.
        zone = self.drawn()[thing("zone-c")]
        self.assertEqual(zone["withdrawal"], "incomplete")
        self.assertIn("вывод не завершён", self.attr(self.scheme("zone-c"), "aria-label"))
        left = sorted(name[-9:] for name, item in self.drawn().items() if item["kind"] == "worker")
        self.assertEqual(left, ["worker-07", "worker-08"], "the others are out and not on the scheme")
        self.assertEqual({item["egress"] for item in self.drawn().values() if item["kind"] == "worker"}, {"none"})

        # Summary, list and card of the option: the same, and still no time.
        summary = self.card()
        self.assertIn("все вышли нет", summary)
        self.assertIn("вышло 12", summary)
        self.show("list")
        option = self.cells("option-withdraw-all")[6]
        self.assertIn("факт: все вышли нет", option)
        self.assertNotIn("факт: время выхода всех", option, "the list names no time of the fact")
        self.page.click(self.row("option-withdraw-all"))
        self.page.wait_for("location.hash.includes('sel=')", timeout=3.0)
        card = self.card()
        self.assertIn("факт: все вышли нет", card)
        self.assertNotIn("факт: время выхода всех", card)
        self.assertIn("вывод не завершён", " ".join(self.cells("zone-c")))
        self.show("runs")
        self.page.wait_for("document.querySelectorAll('[data-testid=\"runs-table\"] tr[data-series=\"actual\"]').length >= 4", timeout=6.0)
        self.assertEqual(self.count('[data-testid="runs-table"] tr[data-run="run-0005"]'), 0, "the run goes on: it is not in the archive yet")

    def test_no_forecast(self):
        """Отсутствие прогноза: the words «Прогноз не опубликован» and not one digit where a forecast would be."""
        self.open("no_forecast")
        self.wait_drawn()
        self.assertEqual(self.body()["dock"], "collapsed")
        show_right(self.page, "decision")
        self.assertEqual(self.text('[data-testid="decision-no-forecast"]'), "Прогноз не опубликован")
        forecast = '[data-testid="decision-forecast"]'
        self.assertEqual(self.page.evaluate(f"""[...document.querySelectorAll('{forecast} td[data-metric]')]
          .filter((cell) => cell.getClientRects().length > 0).length"""), 0, "no metric cell is shown")
        self.assertEqual(self.texts(f"{forecast} [data-testid='decision-caption'] li"), [], "no «прогноз на N секунд» without a forecast")
        shown = self.page.evaluate(f"document.querySelector('{forecast}').innerText")
        for label in ("Вариант 1", "Вариант 2", "Вариант 3"):
            self.assertIn(label, shown)
            shown = shown.replace(label, "")
        self.assertNotRegex(shown, r"\d", f"a number where a forecast would be: {shown!r}")
        self.assertEqual(self.count(f'{DECISION} th[data-state="offered"]'), 3, "the options are offered all the same")
        self.assertEqual(self.count(f'{DECISION} [data-testid="decision-fact"]'), 0)

        self.show("list")
        for option in ("option-observe", "option-stop-withdraw", "option-withdraw-all"):
            value = self.cells(option)[6]
            self.assertIn("Прогноз не опубликован", value)
            self.assertNotIn("прогноз:", value)
            self.assertNotRegex(value, r"\d", value)
        self.page.click(self.row("option-withdraw-all"))
        self.page.wait_for("location.hash.includes('sel=')", timeout=3.0)
        show_right(self.page, "card")
        fields = self.texts(f"{CARD} [data-section='state'] dt")
        self.assertTrue(fields)
        self.assertEqual([field for field in fields if field.startswith(("прогноз", "факт"))], [])


# --------------------------------------------------------------------------
# keyboard
# --------------------------------------------------------------------------

class KeyboardTest(ScenarioTestCase):
    FOCUS = """(() => {
      const node = document.activeElement;
      if (!node || node === document.body) return null;
      const style = getComputedStyle(node);
      // An object of the scheme shows the focus as a dashed frame around it: an element of its own, never the
      // shape that carries the selection (the two must differ by more than a colour or a width).
      const frame = node instanceof SVGElement ? node.querySelector(':scope > .obj__focus') : null;
      const stroke = frame ? getComputedStyle(frame) : null;
      const ring = frame
        ? (stroke.display !== 'none' && stroke.stroke !== 'none' && stroke.strokeDasharray !== 'none' && parseFloat(stroke.strokeWidth) >= 3
          && frame.getBoundingClientRect().width > 0 ? 'frame ' + stroke.stroke : 'none')
        : (style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) >= 2 ? 'outline ' + style.outlineColor : 'none');
      return {tag: node.tagName.toLowerCase(), id: node.id || null, testid: node.dataset.testid || null,
              command: node.dataset.commandType || null, target: node.dataset.commandTarget || null,
              thing: node.dataset.thingId || null, name: node.getAttribute('name'),
              control: node.matches('button, select, input, summary, [tabindex="0"]'), cls: (node.getAttribute('class') || '').split(' ')[0],
              ring, keyboard: node.matches(':focus-visible')};
    })()"""

    def tab_to(self, selector, limit=220, shift=False):
        """Press Tab until the focus is on an element that matches; return what the focus looks like there."""
        for _ in range(limit):
            self.page.press("Tab", shift=shift)
            if self.page.evaluate(f"!!document.activeElement && document.activeElement.matches({json.dumps(selector)})"):
                return self.page.evaluate(self.FOCUS)
        self.fail(f"Tab never reached {selector}; the focus is on {self.page.evaluate(self.FOCUS)}")

    def assert_focus_ring(self, focus, what):
        self.assertTrue(focus["keyboard"], f"{what}: reached by keyboard")
        self.assertRegex(focus["ring"], r"^(outline|frame) rgb\(200, 131, 79\)$", f"{what}: a visible focus ring in the focus colour (copper)")

    def test_keyboard_reaches_and_activates_the_main_controls(self):
        """Tab reaches the main controls, Enter and Space activate them, the focus is visible and survives polls."""
        self.open("detour")
        self.wait_drawn()

        # View tabs, with Enter and Space.
        self.assert_focus_ring(self.tab_to('[data-testid="tab-scheme"]'), "view tab")
        self.tab_to('[data-testid="tab-list"]', 5)
        self.page.press("Enter")
        self.page.wait_for("document.body.dataset.view === 'list'", timeout=2.0)
        # A row of the list.
        row = self.tab_to('[data-testid="list"] tr[data-thing-id]', 30)
        self.assert_focus_ring(row, "row of the list")
        self.page.press("Enter")
        self.page.wait_for(f"location.hash.includes({json.dumps(row['thing'])}) && document.activeElement.getAttribute('aria-selected') === 'true'",
                           timeout=2.0, message="Enter selects the row")
        self.assertIn(row["thing"].split(":")[1].replace("level-", "−"), self.card() or "")
        self.tab_to('[data-testid="tab-runs"]', 220, shift=True)
        self.page.press("Space")
        self.page.wait_for("document.body.dataset.view === 'runs'", timeout=2.0)
        self.tab_to('[data-testid="tab-scheme"]', 5, shift=True)
        self.page.press("Space")
        self.page.wait_for("document.body.dataset.view === 'scheme'", timeout=2.0)

        # An object on the scheme, with Space; the focus stays on it through two polls.
        mark = self.tab_to('#scheme [data-thing-id][role="button"]', 30)
        self.assert_focus_ring(mark, "object on the scheme")
        self.page.press("Space")
        self.page.wait_for(f"location.hash.includes({json.dumps(mark['thing'])})", timeout=2.0, message="Space selects the object")
        self.page.evaluate("window.__focused = document.activeElement")
        self.wait_seq(2)
        self.assertTrue(self.page.evaluate("document.activeElement === window.__focused && window.__focused.isConnected"),
                        "two polls later the focus is on the same object")

        # A condition of the stand: open the drawer from its button, choose the working with the arrow keys, Tab to «Задать», Enter.
        self.tab_to('[data-testid="stand-toggle"]', 220, shift=True)
        self.page.press("Enter")
        self.page.wait_for("document.body.dataset.stand === 'open'", timeout=2.0)
        self.tab_to(WORKING_SELECT)
        choose(self.page, WORKING_SELECT, "w-12")
        button = self.tab_to(f'{CONDITIONS} button[data-command-type="condition.close_working"]', 3)
        self.assertEqual(button["target"], "w-12")
        self.assert_focus_ring(button, "«Задать»")
        self.page.press("Enter")
        wait_decision(self.page)
        self.assertEqual(self.page.evaluate(self.FOCUS)["command"], "condition.close_working", "the command did not take the focus away")

        # A dispatcher action with Space.
        self.tab_to(STOP)
        self.assert_focus_ring(self.page.evaluate(self.FOCUS), "«Остановить участок»")
        self.page.press("Space")
        self.wait_commands(1, "action.stop_zone")
        self.assertEqual(self.page.evaluate(self.FOCUS)["command"], "action.stop_zone")

        # Reset: Space opens the dialog on its safe answer, Esc cancels and gives the focus back; Enter on «Отмена» cancels too.
        self.tab_to(RESET)
        self.page.press("Space")
        self.wait_for_selector('[data-testid="dialog"]', 2.0)
        focus = self.page.evaluate(self.FOCUS)
        self.assertEqual(focus["testid"], "dialog-cancel")
        self.assert_focus_ring(focus, "«Отмена»")
        self.page.press("Tab")
        self.assertEqual(self.page.evaluate(self.FOCUS)["testid"], "dialog-confirm")
        self.page.press("Tab")
        self.assertEqual(self.page.evaluate(self.FOCUS)["testid"], "dialog-cancel", "the focus stays inside the dialog")
        self.page.press("Escape")
        self.page.wait_for("!document.querySelector('[data-testid=\"dialog\"]')", timeout=2.0)
        self.assertEqual(self.page.evaluate(self.FOCUS)["testid"], "btn-reset")
        self.page.press("Enter")
        self.wait_for_selector('[data-testid="dialog"]', 2.0)
        self.page.press("Enter")
        self.page.wait_for("!document.querySelector('[data-testid=\"dialog\"]')", timeout=2.0)
        time.sleep(0.4)
        self.assertEqual(self.commands_logged("run.reset"), [], "a cancelled reset sends nothing")

        # The choice of an option: the dock unfolds from its button; arrow keys move through the radio group,
        # Tab goes to «Запустить вариант».
        self.tab_to('[data-testid="dock-toggle"]')
        if self.attr('[data-testid="dock-toggle"]', "aria-expanded") == "false":
            self.page.press("Enter")
        radio = self.tab_to('input[name="decision-option"]')
        self.assert_focus_ring(radio, "option")
        self.page.press("Space")
        self.page.press("ArrowRight")
        self.page.press("ArrowRight")
        self.assertEqual(self.page.evaluate("document.querySelector('input[name=\"decision-option\"]:checked').value"),
                         "option-withdraw-all")
        self.wait_seq(1)
        self.assertEqual(self.page.evaluate("document.activeElement.value"), "option-withdraw-all", "a poll does not move the choice")
        execute = self.tab_to(EXECUTE, 3)
        self.assertEqual(execute["target"], "option-withdraw-all")
        self.page.press("Enter")
        self.wait_for_selector('[data-testid="dialog"]', 2.0)
        self.assertIn("Запустить вариант?", self.text('[data-testid="dialog"]'))
        self.page.press("Tab")
        self.page.press("Enter")
        self.page.wait_for("!document.querySelector('[data-testid=\"dialog\"]')", timeout=2.0)
        self.wait_body(8.0, runState="running")
        launched = self.wait_commands(1, "action.execute_option")[0]
        self.assertEqual((launched["body"]["target"], launched["body"]["decision_id"], launched["effect_applied"]),
                         ("option-withdraw-all", "d-0005-01", True))

        # The undo of the condition, with Enter.
        undo = self.tab_to(f'{CONDITIONS} button[data-command-type="condition.open_working"]', 220, shift=True)
        self.assertEqual(undo["target"], "w-12")
        self.page.press("Enter")
        opened = self.wait_commands(1, "condition.open_working")[0]
        self.assertEqual(opened["body"]["target"], "w-12")
        self.assertEqual([post["body"]["type"] for post in self.commands_logged()],
                         ["condition.close_working", "action.stop_zone", "action.execute_option", "condition.open_working"],
                         "four commands, each sent by one key press")

    def test_every_control_is_in_the_tab_order(self):
        """One round of Tab through the screen at the decision point: nothing that can be pressed is skipped."""
        self.open("paused_heartbeat")
        self.wait_drawn()
        # The stand drawer open and the decision dock unfolded: then every control of the screen is on it.
        set_stand(self.page)
        show_right(self.page, "decision")
        set_stand(self.page)
        # The focus is in the drawer now: Tab to the end of the document first, so that the round starts at its top.
        for _ in range(200):
            self.page.press("Tab")
            if self.page.evaluate(self.FOCUS) is None:
                break
        seen = []
        for _ in range(400):
            self.page.press("Tab")
            focus = self.page.evaluate(self.FOCUS)
            if focus is None:
                break
            key = json.dumps(focus, sort_keys=True)
            if seen and key == seen[0]:
                break
            seen.append(key)
        reached = [json.loads(item) for item in seen]
        # A disclosure (<summary> of a <details>) is a control too: the decision panel unfolds its details with one.
        expected = self.page.evaluate("""[...document.querySelectorAll('button, select, input, summary, [tabindex="0"]')]
          .filter((node) => node.getClientRects().length > 0 && !node.disabled && getComputedStyle(node).visibility !== 'hidden').length""")
        # A radio group is one stop of the Tab order.
        radios = self.count('input[name="decision-option"]:not([disabled])')
        others = [item for item in reached if not item["control"]]
        self.assertEqual(others, [], "a Tab stop that is not a control (a scrolling box the browser made focusable?)")
        self.assertEqual(len(reached), expected - max(radios - 1, 0), "every visible control is one Tab stop")
        without_ring = [item for item in reached if not item["keyboard"] or item["ring"] == "none"]
        self.assertEqual(without_ring, [], "every stop shows the focus")
        commands = {(item["command"], item["target"]) for item in reached if item["command"]}
        # The dispatcher's actions follow the incident's zone, Участок Б (clarity pass, A1).
        for command in (("run.start_preset", "p-detour"), ("condition.open_working", "w-12"), ("action.stop_zone", "zone-b"),
                        ("action.withdraw_zone", "zone-b"), ("action.resume_zone", "zone-b"), ("run.reset", None)):
            self.assertIn(command, commands)
        self.assertEqual(len([1 for item in reached if item["thing"] and item["tag"] == "g"]), self.count("#scheme [data-thing-id]"),
                         "every object of the scheme")
        ids = {item["testid"] or item["id"] for item in reached}
        for control in ("tab-scheme", "tab-list", "tab-runs", "projection-axo", "projection-plan", "level-select",
                        "condition-working_closed", "condition-sensor_lost", "condition-instability", "action-zone",
                        "btn-reset", "btn-execute", "stand-toggle", "stand-close", "dock-toggle", "card-more", "journal-toggle"):
            self.assertIn(control, ids)


# --------------------------------------------------------------------------
# legibility without colour
# --------------------------------------------------------------------------

class ColourIndependenceTest(ScenarioTestCase):
    """Every state of the three axes differs by shape, hatch, sign or line style and by its words.

    What the assertions check: each state value has its own combination of non-colour cues in the
    DOM (hatch pattern, sign, marker shape, dash style, line weight) and its own visible text, and
    the marks on the scheme are the ones the legend explains. What they do not check: whether a
    person can tell the states apart. That judgement — «readable in greyscale» — was made by an
    agent looking at the greyscale screenshots this test saves to `test-output/greyscale/` (and at
    the set of `screenshots.py`), not by an assertion.
    """

    LEGEND = """(() => {
      %s
      const legend = document.querySelector('[data-testid="legend"]');
      // The full legend unfolds from its chip; its samples are the ones read here.
      const toggle = legend.querySelector('[data-testid="legend-toggle"]');
      if (toggle && toggle.getAttribute('aria-expanded') === 'false') toggle.click();
      const sample = (selector) => {
        const node = legend.querySelector(selector);
        return {cues: cues(node), text: node.closest('.legend__item').textContent, shown: node.getClientRects().length > 0};
      };
      const bare = [...legend.querySelectorAll('.working')].filter((node) => node.querySelector('.working__line'));
      const closed = bare.find((node) => node.querySelector('.working__barrier'));
      const open = bare.find((node) => !node.querySelector('.working__barrier'));
      const of = (node) => ({cues: cues(node), text: node.closest('.legend__item').textContent, shown: node.getClientRects().length > 0});
      return {
        hazard: {
          normal: sample('.working[data-hazard="normal"]'), attention: sample('.working[data-hazard="attention"]'),
          danger: sample('.working[data-hazard="danger"]'),
          unknown: of([...legend.querySelectorAll('.working[data-hazard="unknown"]:not(.working--last-danger)')]
            .find((node) => node.querySelector('.working__band'))),
          lastDanger: sample('.working--last-danger'),
        },
        knowledge: {
          fresh: sample('.sensor[data-quality="fresh"]'), stale: sample('.sensor[data-quality="stale"]'),
          lost: sample('.sensor[data-quality="lost"]'), none: of(open),
        },
        reach: {
          ok: sample('.worker[data-egress="ok"]'), none: sample('.worker[data-egress="none"]'),
          unknown: sample('.worker[data-egress="unknown"]'),
        },
        passage: {open: of(open), closed: of(closed)},
        exit: {
          available: sample('.exit[data-state="available"]'), unavailable: sample('.exit[data-state="unavailable"]'),
          unknown: sample('.exit[data-state="unknown"]'),
        },
      };
    })()""" % CUES

    SCHEME = """(() => {
      %s
      const out = {};
      for (const node of document.querySelectorAll('#scheme .obj[data-thing-id]')) {
        if (node.classList.contains('zone')) continue;
        out[node.dataset.thingId.split(':')[1]] = {cues: cues(node), ...node.dataset, cls: node.getAttribute('class')};
      }
      return out;
    })()""" % CUES

    def grey_screenshot(self, name):
        path = os.path.join(OUTPUT_DIR, "greyscale", name + ".png")
        self.page.emulate_vision("achromatopsia")
        time.sleep(0.7)
        self.page.screenshot(path)
        box = self.page.evaluate("(() => { const box = document.getElementById('scheme').getBoundingClientRect();"
                                 " return [Math.round(box.x), Math.round(box.y), Math.round(box.width), Math.round(box.height)]; })()")
        clip = os.path.join(OUTPUT_DIR, "greyscale", name + "-clip.png")
        self.page.screenshot(clip, clip=(box[0] + box[2] // 4, box[1] + box[3] // 4, 240, 160))
        self.page.emulate_vision("none")
        image = read_png(clip)
        shades = set()
        for y in range(0, image.height, 3):
            for x in range(0, image.width, 3):
                red, green, blue, _ = image.pixel(x, y)
                self.assertLessEqual(max(red, green, blue) - min(red, green, blue), 2, "the screenshot is greyscale")
                shades.add(red)
        self.assertGreater(len(shades), 3, "the picture is not blank")
        os.remove(clip)
        return path

    def test_states_differ_without_colour(self):
        """Legibility without colour: distinct non-colour cues and distinct words for every state; greyscale screenshots saved."""
        self.open("sensor_lost_after_danger")
        self.wait_drawn()
        legend = self.page.evaluate(self.LEGEND)
        for axis, samples in legend.items():
            cues = {value: sample["cues"] for value, sample in samples.items()}
            texts = {value: plain(sample["text"]) for value, sample in samples.items()}
            self.assertEqual(len(set(cues.values())), len(cues), f"{axis}: two states share every non-colour cue: {cues}")
            if axis != "passage":
                self.assertEqual(len(set(texts.values())), len(texts), f"{axis}: two states share their words: {texts}")
            for value, sample in samples.items():
                self.assertTrue(sample["shown"], f"{axis} {value}: the legend shows its sample at 1280x720")
                self.assertTrue(sample["cues"], f"{axis} {value}")
                self.assertGreater(len(texts[value]), 3, f"{axis} {value}: a word next to the sample")
        # What exactly tells the states apart, so that a change of the drawing is noticed here.
        hazard = legend["hazard"]
        self.assertIn("pattern attention", hazard["attention"]["cues"])
        self.assertIn("pattern danger", hazard["danger"]["cues"])
        self.assertIn("heavy", hazard["danger"]["cues"])
        self.assertIn("sign unknown", hazard["unknown"]["cues"])
        self.assertIn("dashed", hazard["unknown"]["cues"])
        self.assertIn("sign lastDanger", hazard["lastDanger"]["cues"])
        self.assertNotIn("pattern", hazard["normal"]["cues"])
        self.assertIn("rect", legend["reach"]["none"]["cues"])
        self.assertNotIn("rect", legend["reach"]["ok"]["cues"])
        self.assertIn("dashed", legend["reach"]["unknown"]["cues"])
        self.assertIn("working__line", legend["knowledge"]["none"]["cues"])
        self.assertIn("working__bars", legend["passage"]["closed"]["cues"])

        # The marks on the scheme are the ones of the legend: states the model published in this scenario.
        scheme = self.page.evaluate(self.SCHEME)
        checked = set()
        for name, item in scheme.items():
            if item["kind"] == "sensor":
                self.assertEqual(item["cues"], legend["knowledge"][item["quality"]]["cues"], name)
                checked.add("sensor " + item["quality"])
            elif item["kind"] == "exit":
                self.assertEqual(item["cues"], legend["exit"][item["state"]]["cues"], name)
                checked.add("exit " + item["state"])
            elif item["kind"] == "worker" and "is-merged" not in item["cls"] and item["locationHazard"] != "danger":
                self.assertEqual(item["cues"], legend["reach"][item["egress"]]["cues"], name)
                checked.add("worker " + item["egress"])
            elif item["kind"] == "working" and "working--between" not in item["cls"] and item["passability"] == "open" \
                    and item.get("restriction") != "blocked" or (item["kind"] == "working" and item.get("lastKnownHazard") == "danger"):
                if item["quality"] == "none":
                    self.assertEqual(item["cues"], legend["knowledge"]["none"]["cues"], name)
                    checked.add("working none")
                else:
                    value = "lastDanger" if item.get("lastKnownHazard") == "danger" else item["hazard"]
                    self.assertEqual(item["cues"], legend["hazard"][value]["cues"], name)
                    checked.add("working " + value)
        self.assertEqual(checked, {"sensor fresh", "sensor lost", "exit available", "worker ok", "working none",
                                   "working normal", "working attention", "working lastDanger"})
        self.grey_screenshot("sensor-lost-after-danger")

        self.open("no_path")
        self.wait_drawn()
        close_working(self.page, "w-07")
        wait_decision(self.page)
        scheme = self.page.evaluate(self.SCHEME)
        self.assertEqual(scheme["worker-07"]["cues"], legend["reach"]["none"]["cues"])
        self.assertEqual(scheme["w-07"]["passability"], "closed")
        self.assertIn("working__bars", scheme["w-07"]["cues"])
        self.assertIn("working__cross", scheme["w-07"]["cues"])
        self.grey_screenshot("no-path")

    def test_states_no_fixture_publishes_are_drawn_like_the_legend(self):
        """A zone in danger now, a stale sensor, an unknown route, an unavailable exit: no fixture has them.

        The test rewrites the answers of the mock in the browser (REWRITE_SHIFT and STATES_PATCH of
        screenshots.py) and leaves the page code alone, so these states go through the real reading,
        validation and drawing.
        """
        self.page.add_init_script(REWRITE_SHIFT)
        self.open("normal")
        self.wait_drawn()
        self.page.evaluate("window.__patch = " + json.dumps(STATES_PATCH))
        self.page.wait_for(f"document.querySelector('{self.scheme('zone-b')}').dataset.hazard === 'danger'", timeout=5.0)
        self.assertEqual(self.body()["snapshot"], "ok", "the rewritten snapshot is still a full one")
        legend = self.page.evaluate(ColourIndependenceTest.LEGEND)
        scheme = self.page.evaluate(ColourIndependenceTest.SCHEME)
        self.assertEqual(scheme["w-14"]["cues"], legend["hazard"]["danger"]["cues"], "a working in danger is hatched densely with a heavy outline")
        self.assertEqual(scheme["w-33"]["hazard"], "unknown")
        self.assertEqual(scheme["w-33"]["cues"], legend["hazard"]["unknown"]["cues"], "by stale data: unknown, never normal")
        self.assertEqual(scheme["sens-ext-01"]["cues"], legend["knowledge"]["stale"]["cues"])
        self.assertEqual(scheme["worker-11"]["cues"], legend["reach"]["unknown"]["cues"])
        self.assertEqual(scheme["exit-raise"]["cues"], legend["exit"]["unavailable"]["cues"])
        self.assertEqual(scheme["exit-ramp"]["cues"], legend["exit"]["unknown"]["cues"])
        self.assertNotEqual(scheme["worker-03"]["cues"], scheme["worker-09"]["cues"], "a worker in a danger zone has a second ring")
        self.assertIn("worker__danger", scheme["worker-03"]["cues"])
        tags = plain(" | ".join(self.page.evaluate("[...document.querySelectorAll('#scheme .tag')].map((tag) => tag.textContent)")))
        for words in ("Участок Б: опасно", "Участок А: состояние неизвестно", "по устаревшим данным", "выход недоступен",
                      "состояние выхода неизвестно", "маршрут не рассчитан", "данные устарели"):
            self.assertIn(words, tags)
        self.assertEqual(self.counters()["in-danger"], "4")
        self.show("list")
        self.assertEqual(self.cells("zone-b")[3], "опасно")
        self.assertRegex(self.cells("zone-a")[3], r"^состояние неизвестно последнее известное: внимание в 00:18:20 \(\d+ (?:с|мин) назад\)$")
        self.assertEqual(self.cells("zone-a")[4], "данные устарели")
        self.assertIn("маршрут не рассчитан", self.cells("worker-11")[5])
        self.assertEqual(self.cells("exit-raise")[5], "выход недоступен")
        self.assertEqual(self.cells("worker-03")[3], "участок: опасно")
        self.assertIn("расчётный маршрут (модель)", self.cells("worker-03")[5], "in a danger zone and with a route: two axes")
        self.show("scheme")
        self.grey_screenshot("states-no-fixture-publishes")


# --------------------------------------------------------------------------
# both sizes
# --------------------------------------------------------------------------

class LayoutTest(ScenarioTestCase):
    NEVER_FOLDED = ('[data-testid="status-notice"]', '[data-testid="status-link"]', '[data-testid="status-age"]',
                    '[data-testid="incident-in-danger"]', '[data-testid="incident-no-route"]', '[data-testid="incident-unknown"]',
                    '[data-testid="legend"]', '[data-testid="stand-toggle"]')
    PAGE = """(() => {
      const root = document.documentElement;
      const box = (id) => { const rect = document.getElementById(id).getBoundingClientRect();
        return {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height}; };
      const stage = box('stage');
      const legend = box('legend');
      const drawer = document.getElementById('stand-drawer');
      return {
        scroll: [root.scrollWidth - innerWidth, root.scrollHeight - innerHeight, document.body.scrollWidth - innerWidth,
                 document.body.scrollHeight - innerHeight],
        overflow: [getComputedStyle(root).overflow, scrollX, scrollY],
        stage: [Math.round(stage.width), Math.round(stage.height)],
        share: stage.width * stage.height / (innerWidth * innerHeight),
        legendOnStage: legend.left >= stage.left - 1 && legend.right <= stage.right + 1 && legend.top >= stage.top - 1
          && legend.bottom <= stage.bottom + 1,
        legendHeight: Math.round(legend.height),
        // The two families: the stand in a drawer of chalk mark-up, closed by default; the dispatcher's actions in the right column.
        groups: [getComputedStyle(drawer).borderRightStyle, getComputedStyle(drawer).visibility,
                 getComputedStyle(document.getElementById('actions')).borderTopStyle,
                 document.getElementById('right').contains(document.getElementById('actions')),
                 drawer.contains(document.getElementById('conditions')) && drawer.contains(document.getElementById('reset'))],
        incident: document.querySelector('[data-testid="incident-strip"]').dataset.open === 'true',
      };
    })()"""

    def check_layout(self, size, scenario, crowded=False):
        where = f"{scenario} at {size[0]}x{size[1]}"
        page = self.page.evaluate(self.PAGE)
        self.assertEqual(page["scroll"], [0, 0, 0, 0], f"{where}: the page does not scroll, neither way")
        self.assertEqual(page["overflow"], ["hidden", 0, 0], where)
        for selector in self.NEVER_FOLDED:
            self.assertTrue(self.visible(selector), f"{where}: {selector} is in the viewport and in sight")
        if page["incident"]:
            self.assertTrue(self.visible('[data-testid="situation-step-1"]'), f"{where}: what changed is in sight")
        self.assertTrue(self.visible("#actions .panel__title"), f"{where}: the heading of the dispatcher's actions is in sight")
        self.assertTrue(page["legendOnStage"], f"{where}: the legend chip lies on the stage")
        self.assertEqual(page["groups"], ["dashed", "hidden", "solid", True, True],
                         f"{where}: the stand controls (a closed drawer of chalk mark-up) and the dispatcher's actions are apart")
        if size == (1280, 720):
            self.assertGreaterEqual(page["share"], 0.58 if crowded else 0.6, f"{where}: the stage keeps the largest area")
        self.assertEqual(self.text('[data-testid="status-notice"]'), "Синтетические данные. Расчёт модели, не сведения о реальной шахте")
        return page

    def test_both_sizes_without_page_scroll_and_with_what_never_folds(self):
        """1280x720 and 1920x1080: no page scroll, the stage is the largest area, and what never folds is in the viewport."""
        measured = {}
        for size in ((1280, 720), (1920, 1080)):
            self.page.set_viewport(*size)
            for scenario in ("normal", "sensor_lost_after_danger", "paused_heartbeat"):
                self.open(scenario)
                self.wait_drawn()
                with self.subTest(size=size, scenario=scenario):
                    measured[(size, scenario)] = self.check_layout(size, scenario)
            # With a banner and two pending commands the never-folding elements are still there.
            self.open("commands")
            self.wait_drawn()
            close_working(self.page, "w-12")
            close_working(self.page, "w-07")
            self.wait_pending("w-07", "rejected", 5.0)
            self.mock.fault("http_502")
            self.wait_body(10.0, link="unavailable")
            with self.subTest(size=size, scenario="commands, platform unavailable"):
                self.check_layout(size, "commands, platform unavailable", crowded=True)
                self.assertTrue(self.visible('[data-testid="overlay-banner"][data-code="platform_unavailable"]'))
                # The list of sent commands has a limited height and scrolls inside: an entry is one scroll away.
                self.assertTrue(self.visible("#pending .panel__title"), "the list of sent commands is in sight")
                self.page.evaluate("document.querySelector('[data-testid=\"pending\"][data-command-target=\"w-07\"]')"
                                   ".scrollIntoView({block: 'nearest'})")
                self.assertTrue(self.visible('[data-testid="pending"][data-command-target="w-07"]'))
            self.mock.fault("none")
        compact = measured[((1280, 720), "normal")]
        wide = measured[((1920, 1080), "normal")]
        self.assertLessEqual(compact["legendHeight"], 76, "the legend chip stays small at 1280x720")
        self.assertGreaterEqual(compact["stage"][1], 470, f"room for the stage at 1280x720: {compact['stage']}")
        self.assertGreaterEqual(wide["stage"][1], 600, f"room for the stage at 1920x1080: {wide['stage']}")

    def test_sent_commands_leave_the_dispatcher_actions_in_reach_at_1280(self):
        """S11: with three listed commands the zone select and the three actions stay in sight."""
        self.page.set_viewport(1280, 720)
        self.open("commands")
        self.wait_drawn()
        close_working(self.page, "w-12")                  # accepted, never acknowledged
        close_working(self.page, "w-07")                  # rejected
        choose(self.page, ZONE_SELECT, "zone-b")
        self.page.click(STOP)                             # the first POST fails with 503: delivery unknown
        self.wait_pending("w-07", "rejected", 6.0)
        self.wait_pending("zone-b", "delivery_unknown", 6.0)
        self.wait_pending("w-12", "no_ack", 9.0)          # the tallest entry: a sentence and two buttons
        # Newest first: the command sent last is right under the heading, whole, without any scrolling.
        order = self.page.evaluate("[...document.querySelectorAll('[data-testid=\"pending\"]')].map((node) => node.dataset.commandTarget)")
        self.assertEqual(order, ["zone-b", "w-07", "w-12"])
        newest = '[data-testid="pending"][data-command-target="zone-b"]'
        for part in (".pending__what", ".pending__text"):
            self.assertTrue(self.visible(f"{newest} {part}"), f"the command just sent and its outcome are in sight without scrolling: {part}")
        measured = self.page.evaluate("""(() => {
          const right = document.getElementById('right');
          const group = document.getElementById('pending');
          return {
            entries: group.querySelectorAll('[data-testid="pending"]').length,
            share: group.getBoundingClientRect().height / right.clientHeight,
            scrollsInside: group.scrollHeight > group.clientHeight + 1,
            overflow: getComputedStyle(group).overflowY,
            journal: [...document.querySelectorAll('[data-testid="journal-entry"]')].filter((node) => node.getClientRects().length > 0
              && node.getBoundingClientRect().bottom <= right.getBoundingClientRect().bottom + 1).length,
          };
        })()""")
        os.makedirs(os.path.join(OUTPUT_DIR, "fix"), exist_ok=True)
        self.page.screenshot(os.path.join(OUTPUT_DIR, "fix", "three-sent-commands-1280x720.png"))
        self.assertEqual(measured["entries"], 3)
        self.assertLessEqual(measured["share"], 0.33, "the list of sent commands takes at most a third of the right column")
        self.assertTrue(measured["scrollsInside"], "three entries do not fit: the list scrolls inside its own frame")
        self.assertEqual(measured["overflow"], "auto")
        self.assertGreaterEqual(measured["journal"], 1, "the journal keeps its latest line under the list")
        actions = (ZONE_SELECT, STOP, f'{ACTIONS} button[data-command-type="action.withdraw_zone"]',
                   f'{ACTIONS} button[data-command-type="action.resume_zone"]')
        for selector in actions:
            self.assertTrue(self.visible(selector), f"{selector} is in sight and not under the list of sent commands")
        self.assertTrue(self.visible("#pending .panel__title"), "the list itself stays in sight")
        # Every entry and its buttons can be reached inside the list, and that does not push the actions away.
        for target, part in (("w-12", ".pending__what"), ("w-12", '[data-testid="btn-retry"]'), ("w-07", ".pending__what"),
                             ("w-07", '[data-testid="btn-dismiss"]'), ("zone-b", '[data-testid="btn-retry"]'), ("zone-b", ".pending__what")):
            inside = f'[data-testid="pending"][data-command-target="{target}"] {part}'
            self.page.evaluate(f"document.querySelector({json.dumps(inside)}).scrollIntoView({{block: 'nearest'}})")
            self.assertTrue(self.visible(inside), f"{inside} can be scrolled into view")
        for selector in actions:
            self.assertTrue(self.visible(selector), selector)
        # At 1920x1080 the same holds.
        self.page.set_viewport(1920, 1080)
        for selector in actions:
            self.assertTrue(self.visible(selector), f"1920x1080: {selector}")
        self.page.screenshot(os.path.join(OUTPUT_DIR, "fix", "three-sent-commands-1920x1080.png"))

    def test_compact_layout_folds_what_the_design_folds(self):
        """1280x720: the run folds away, the decision dock folds to its bar over the stage and unfolds over it,
        the card stays beside it, and the journal shows its latest three lines and unfolds inside the right column."""
        self.page.set_viewport(1280, 720)
        self.open("sensor_lost_after_danger")
        self.wait_drawn()
        self.assertFalse(self.visible('[data-testid="status-run"]'))
        self.assertEqual(plain(self.page.evaluate("document.querySelector('[data-testid=\"status-run\"]').textContent")),
                         "Прогон run-0005", "the run is still in the document")

        # The dock: its bar over the stage, the options unfolded on request («к вариантам» of the strip), the stage keeps its size.
        stage = """(() => { const rect = document.getElementById('stage').getBoundingClientRect(); return [rect.width, rect.height]; })()"""
        before = self.page.evaluate(stage)
        self.assertEqual(self.body()["dock"], "collapsed")
        self.assertTrue(self.visible('[data-testid="dock-toggle"]'))
        self.assertTrue(self.visible(f"{CARD} .card__head"), "the card is on the screen with the dock")
        self.assertEqual(self.page.evaluate("document.getElementById('decision').getClientRects().length"), 0)
        self.page.click('[data-testid="situation-show-4"]')
        self.page.wait_for("document.body.dataset.dock === 'open'", timeout=2.0)
        settle(self.page)    # it unfolds over 200 ms (clarity pass, M3)
        self.assertTrue(self.visible("#decision"))
        self.assertEqual(self.page.evaluate(stage), before, "the dock lies over the stage; the stage does not shrink")
        self.assertTrue(self.visible(f"{CARD} .card__head"))
        self.assertTrue(self.visible('[data-testid="legend"]'), "the legend chip moves above the unfolded dock")
        self.page.click('[data-testid="dock-toggle"]')
        self.assertEqual(self.body()["dock"], "collapsed")

        boxes = """(() => {
          const box = (id) => { const rect = document.getElementById(id).getBoundingClientRect();
            return {left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, height: rect.height}; };
          const journal = box('journal-region');
          return {centre: box('centre'), right: box('right'), journal,
                  lines: [...document.querySelectorAll('.journal-line')].filter((node) => node.getClientRects().length > 0
                    && node.getBoundingClientRect().bottom <= journal.bottom + 1 && node.getBoundingClientRect().top >= journal.top - 1).length};
        })()"""
        folded = self.page.evaluate(boxes)
        self.assertEqual(folded["lines"], 3, "folded: the latest three entries")
        self.page.click('[data-testid="journal-toggle"]')
        self.page.wait_for("document.body.dataset.journal === 'open'", timeout=2.0)
        unfolded = self.page.evaluate(boxes)
        journal, right = unfolded["journal"], unfolded["right"]
        self.assertGreater(journal["height"], 250)
        self.assertGreaterEqual(unfolded["lines"], 6)
        self.assertGreaterEqual(journal["left"], right["left"] - 1, "the unfolded journal stays in the right column")
        self.assertEqual(unfolded["centre"], folded["centre"], "the centre column does not move")
        self.assertEqual(self.count('[data-testid="journal-gap"]'), 1, "the missing events are said in their own line")
        self.page.click('[data-testid="journal-toggle"]')
        self.assertEqual(self.body()["journal"], "collapsed")

    def test_list_rows_are_one_or_two_lines_at_1920(self):
        """«Список» at 1920x1080: a row of a working is one line, a worker with a plain route two; more than twenty rows in sight."""
        self.page.set_viewport(1920, 1080)
        self.open("normal", "#/list")
        self.page.wait_for("document.querySelectorAll('[data-testid=\"list\"] tbody tr').length === 75", timeout=5.0)
        rows = self.page.evaluate("""(() => {
          const scroll = document.querySelector('#view-list .view__scroll').getBoundingClientRect();
          const line = parseFloat(getComputedStyle(document.querySelector('[data-testid="list"] td')).lineHeight);
          return {line, overflow: document.querySelector('#view-list .view__scroll').scrollWidth - document.querySelector('#view-list .view__scroll').clientWidth,
            rows: [...document.querySelectorAll('[data-testid="list"] tbody tr')].map((row) => {
              const box = row.getBoundingClientRect();
              return {kind: row.dataset.kind, lines: Math.round((box.height - 7) / line), inSight: box.top >= scroll.top && box.bottom <= scroll.bottom};
            })};
        })()""")
        self.assertEqual(rows["overflow"], 0, "no horizontal scrolling of the list")
        by_kind = {}
        for row in rows["rows"]:
            by_kind.setdefault(row["kind"], []).append(row["lines"])
        self.assertEqual(max(by_kind["level"] + by_kind["option"] + by_kind["incident"]), 1)
        self.assertLessEqual(sorted(by_kind["working"])[32], 1, f"workings outside the zone with a reason to tell: {by_kind['working']}")
        self.assertLessEqual(sorted(by_kind["worker"])[10], 2, f"workers with a plain route: {by_kind['worker']}")
        self.assertLessEqual(max(by_kind["worker"]), 4, f"a route through a zone «внимание» is two more lines: {by_kind['worker']}")
        self.assertLessEqual(max(by_kind["sensor"] + by_kind["exit"]), 2)
        self.assertLessEqual(sorted(by_kind["zone"])[2], 2, f"zones: {by_kind['zone']}")
        self.assertGreaterEqual(len([1 for row in rows["rows"] if row["inSight"]]), 22)
        # The states of the hazard and knowledge columns are whole on one line.
        wrapped = self.page.evaluate("""[...document.querySelectorAll('[data-testid="list"] tbody td:nth-child(4) .badge, [data-testid="list"] tbody td:nth-child(5) .badge')]
          .filter((node) => node.getClientRects().length > 0 && node.getBoundingClientRect().height > 24).map((node) => node.textContent)""")
        self.assertEqual(wrapped, [])
        self.assertEqual(self.cells("w-01")[3:5], ["состояние неизвестно", "без датчиков"])


# --------------------------------------------------------------------------
# production hygiene
# --------------------------------------------------------------------------

class HygieneTest(ScenarioTestCase):
    def test_requests_stay_on_origin_and_inside_the_contract_through_a_full_session(self):
        """Every view and every kind of command in one session: all requests on the origin, static or /ditto/, all allowed by the mock."""
        self.page.add_init_script(PROBE)
        self.open("detour")
        self.wait_drawn()
        self.show("list")
        self.page.evaluate("document.querySelector('[data-testid=\"list-type\"]').focus()")
        self.page.press("ArrowDown")
        self.page.click('[data-testid="list"] tbody tr')
        self.show("runs")
        self.page.wait_for("document.querySelectorAll('[data-testid=\"runs-table\"] tr[data-series=\"actual\"]').length >= 4", timeout=6.0)
        self.show("scheme")
        self.page.click('[data-testid="projection-plan"]')
        self.page.wait_for("document.querySelector('[data-testid=\"scheme-svg\"]').dataset.projection === 'plan'", timeout=3.0)
        choose(self.page, '[data-testid="level-select"]', "level-320")
        self.page.click('[data-testid="projection-axo"]')
        self.select_on_scheme("worker-03")
        self.page.click('[data-testid="journal-toggle"]')
        self.page.click('[data-testid="journal-toggle"]')
        set_stand(self.page)
        set_stand(self.page, False)
        close_working(self.page, "w-12")
        wait_decision(self.page)
        self.page.click(STOP)
        execute_option(self.page, "option-stop-withdraw")
        self.wait_body(8.0, runState="running")
        self.wait_seq(3)
        self.page.goto(self.mock.url + "/#/list?type=worker&sel=" + thing("worker-07"))
        self.page.wait_for("document.body.dataset.view === 'list'", timeout=3.0)
        time.sleep(1.2)
        self.assert_only_contract_requests()
        types = [post["body"]["type"] for post in self.commands_logged()]
        self.assertEqual(types, ["condition.close_working", "action.stop_zone", "action.execute_option"],
                         "the hash route sent nothing, and every command went to the one allowed path")
        self.assertEqual([entry for entry in self.mock.log()["entries"] if not entry["allowed"]], [],
                         "the mock saw no request a proxy of the contract would refuse")

        # A second story on the same tab: a preset that starts a new run, then the archive. (Switching the
        # scenario empties the log of the mock, so each story is checked on its own.)
        self.open("detour")
        set_stand(self.page)
        self.page.click(f'{CONDITIONS} button[data-command-type="run.start_preset"][data-command-target="p-detour"]', timeout=3.0)
        self.wait_for_selector('[data-testid="dialog-confirm"]', 3.0)
        self.page.click('[data-testid="dialog-confirm"]')
        self.wait_body(12.0, run="run-0006", runState="running")
        set_stand(self.page, False)    # the open drawer lies over the view tabs
        self.show("runs")
        self.wait_for_selector('[data-testid="runs-table"] tr[data-run="run-0005"]', 6.0)
        self.assert_only_contract_requests()
        self.assertEqual([post["body"]["type"] for post in self.commands_logged()], ["run.start_preset"])
        self.assertEqual([entry for entry in self.mock.log()["entries"] if not entry["allowed"]], [])
        # The page's own fonts and model are local files (their paths are checked above); an image only as a data: URL.
        kinds = {request["type"] for request in list(self.page.requests) if not request["url"].startswith("data:")}
        self.assertLessEqual(kinds, {"Document", "Stylesheet", "Script", "Fetch", "Font"}, "no other kind of resource")
        self.assertEqual(self.page.evaluate("[...document.querySelectorAll('canvas')].filter((node) => !node.closest('#stage-3d')).length"), 0,
                         "a canvas only as the 3D stage")

    def test_no_canvas_context_and_no_animation_frames_while_data_do_not_change(self):
        """A canvas only as the 3D stage, and no `requestAnimationFrame` during five seconds of unchanged data, in any view."""
        self.page.add_init_script(PROBE)
        self.open("paused_heartbeat")
        self.wait_drawn()
        self.select_on_scheme("worker-03")
        self.show("list")
        self.show("runs")
        self.show("scheme")
        self.wait_seq(1)
        first = self.body()
        self.page.evaluate("window.__probe.raf = 0")
        started = time.monotonic()
        time.sleep(5.2)
        probe = self.page.evaluate("window.__probe")
        later = self.body()
        self.assertGreaterEqual(time.monotonic() - started, 5.0)
        self.assertEqual(later["tick"], first["tick"], "the data did not change")
        self.assertGreaterEqual(int(later["seq"]) - int(first["seq"]), 4, "while the page went on polling and rendering")
        self.assertEqual(probe["raf"], 0, "no animation frame is requested")
        self.assertEqual(self.page.evaluate("[...document.querySelectorAll('canvas')].filter((node) => !node.closest('#stage-3d')).length"), 0,
                         "a canvas only as the 3D stage")
        animated = self.page.evaluate("""[...document.querySelectorAll('*')].filter((node) => {
          const style = getComputedStyle(node);
          return style.animationName !== 'none' || style.filter !== 'none' || style.backdropFilter !== 'none' || style.boxShadow !== 'none';
        }).map((node) => node.tagName + '.' + node.getAttribute('class'))""")
        self.assertEqual(animated, [], "no animation, filter, blur or shadow anywhere")
        self.assertEqual(self.page.evaluate("document.getAnimations().length"), 0, "nothing is in motion")


def _strip_comments(source, kind):
    """The code of a production file without its comments (strings and regular expressions are kept)."""
    if kind == "html":
        return re.sub(r"<!--.*?-->", "", source, flags=re.S)
    if kind == "css":
        return re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    out = []
    stack = []          # brace depth of each `${` of a template that is open
    position = 0
    last = ""           # the last significant character of code, to tell a division from a regular expression
    while position < len(source):
        char = source[position]
        pair = source[position:position + 2]
        if pair == "//":
            end = source.find("\n", position)
            position = len(source) if end < 0 else end
        elif pair == "/*":
            end = source.find("*/", position + 2)
            position = len(source) if end < 0 else end + 2
        elif char in "'\"":
            end = position + 1
            while source[end] != char:
                end += 2 if source[end] == "\\" else 1
            out.append(source[position:end + 1])
            position, last = end + 1, char
        elif char == "`" or (char == "}" and stack and stack[-1] == 0):
            if char == "}":
                stack.pop()
            end = position + 1
            while source[end] != "`" and source[end:end + 2] != "${":
                end += 2 if source[end] == "\\" else 1
            if source[end] == "`":
                out.append(source[position:end + 1])
                position, last = end + 1, "`"
            else:
                out.append(source[position:end + 2])
                stack.append(0)
                position, last = end + 2, "{"
        elif char == "/" and (last == "" or last in "(,=:[!&|?{};"):
            end = position + 1
            in_class = False
            while source[end] != "/" or in_class:
                if source[end] == "\\":
                    end += 1
                elif source[end] == "[":
                    in_class = True
                elif source[end] == "]":
                    in_class = False
                end += 1
            out.append(source[position:end + 1])
            position, last = end + 1, "/"
        else:
            if stack and char == "{":
                stack[-1] += 1
            elif stack and char == "}":
                stack[-1] -= 1
            out.append(char)
            if not char.isspace():
                last = char
            position += 1
    return "".join(out)


class StaticSourcesTest(unittest.TestCase):
    """A grep over `team/ui/public/`: what the production static must not contain. No browser is needed."""

    NAMESPACES = ("http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink", "http://www.w3.org/1999/xhtml",
                  "http://www.w3.org/XML/1998/namespace", "http://www.w3.org/2000/xmlns/")
    # Identifiers and labels of the fixture mine. Generic vocabulary («участок», «ствол», "zone", "worker") is not in the list.
    FIXTURE = (r"\bw-\d{2}\b", r"\bzone-[a-d]\b", r"\bworker-\d{2}\b", r"\bsens-(?:ext|conv|geo)\b", r"\bexit-(?:shaft|ramp|raise)\b",
               r"\blevel-\d{3}\b", r"\brun-\d{4}\b", r"\boption-(?:observe|stop-withdraw|withdraw-all)\b", r"\bp-(?:detour|no-path)\b",
               r"\bn-\d{2}\b", r"\bd-\d{4}-\d{2}\b", r"Участок [А-ЯЁ]\b", r"(?<![\w-])[РВЭКГ]-\d{2}\b", r"Гор\. ",
               r"\b(?:Ствол|Съезд|Восстающий)\b", r"Вариант \d", r"\bseed 42\b", r"Рудник \(условный\)")

    # Third-party code, vendored as published (three.js, see vendor/three/SOURCE.md): not searched for our rules.
    VENDOR = "vendor/"
    # The 3D stage (redesign spec 3): WebGL and a canvas are allowed there and only there.
    SCENE = ("js/scene3d/", "js/view/stage.js", "js/text3d.js", "css/scene3d.css")

    @classmethod
    def setUpClass(cls):
        cls.files = {}
        cls.others = []
        for folder, _, names in os.walk(PUBLIC_DIR):
            for name in names:
                path = os.path.join(folder, name)
                relative = os.path.relpath(path, PUBLIC_DIR).replace(os.sep, "/")
                if relative.rsplit(".", 1)[-1] not in ("html", "css", "js"):
                    cls.others.append(relative)
                    continue
                with open(path, encoding="utf-8") as handle:
                    cls.files[relative] = handle.read()

    def own(self):
        """The files of the team: everything but the vendored code."""
        return {name: source for name, source in self.files.items() if not name.startswith(self.VENDOR)}

    def test_only_html_css_and_javascript_are_served(self):
        self.assertGreaterEqual(len(self.own()), 30)
        # Besides the code: the bundled fonts with their licence, the vendored three.js with its licence, the model.
        for name in self.others:
            self.assertRegex(name, r"^(?:fonts/(?:[\w.-]+\.woff2|LICENSE-[\w-]+|SOURCE\.md)|vendor/three/(?:LICENSE|SOURCE\.md)"
                                   r"|models/[\w.-]+\.glb)$", f"not a file the page may serve: {name}")

    def test_no_html_injection_no_control_api_no_canvas_no_external_url(self):
        for name, source in self.own().items():
            with self.subTest(file=name):
                for word in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "__mock__", "eval(", "new Function"):
                    self.assertNotIn(word, source, f"{name} contains {word}")
                if not name.startswith(self.SCENE):
                    self.assertNotRegex(source, r"(?i)\bcanvas\b|webgl|getContext", f"{name} mentions a canvas outside the 3D stage")
                    self.assertNotIn("requestAnimationFrame", source, f"{name}: no animation loop outside the 3D stage")
                for url in re.findall(r"""(?:https?:)?//[\w.-]+\.[a-z]{2,}[^\s'"`)]*""", source):
                    self.assertIn(url, self.NAMESPACES, f"{name} contains the URL {url}")
                if name == "fonts/fonts.css":
                    # The bundled fonts: every url() is a file next to it.
                    self.assertEqual(re.findall(r"url\((?!\./[\w.-]+\.woff2\))", source), [], name)
                    continue
                self.assertNotRegex(source, r"@import|@font-face|url\(\s*['\"]?(?!#|data:)", f"{name} loads a resource from CSS")
                self.assertNotRegex(source, r"(?i)backdrop-filter|box-shadow|text-shadow|@keyframes|feGaussianBlur|<filter",
                                    f"{name}: filters, shadows and animations are not used")
                if name.endswith(".css"):
                    self.assertNotRegex(source, r"(?:^|[;{])\s*(?:filter|animation)\s*:", f"{name}: no filter and no animation")

    def test_no_identifier_or_label_of_the_fixture_mine_in_the_code(self):
        """The interface knows no mine: codes and labels come from the platform.

        Comments are left out (they quote the examples of DESIGN.md, such as «В-12»); everything
        else, strings included, is searched.
        """
        for name, source in self.own().items():
            code = _strip_comments(source, name.rsplit(".", 1)[-1])
            with self.subTest(file=name):
                self.assertTrue(code.strip(), "the comments were stripped, not the code")
                for pattern in self.FIXTURE:
                    found = re.findall(pattern, code)
                    self.assertEqual(found, [], f"{name}: {found[:3]} looks like a twin of the fixture mine")
        js = "".join(_strip_comments(source, "js") for name, source in self.own().items() if name.endswith(".js"))
        self.assertIn("export function mount", js)
        self.assertNotRegex(js, r"(?m)^\s*//", "the stripper removes line comments")
        self.assertIn("'http://www.w3.org/2000/svg'", js, "and keeps strings whole")

    def test_wording_rules(self):
        """DESIGN.md 2.2: the words that are never written, in any production file."""
        for name, source in self.own().items():
            with self.subTest(file=name):
                lowered = _strip_comments(source, name.rsplit(".", 1)[-1]).lower()
                for word in ("безопасн", "вероятност", "риск обрушения", "выхода нет", "заблокирован ", "ожидаемый результат"):
                    self.assertNotIn(word, lowered, f"{name} writes «{word}»")
        text = self.files["js/text.js"]
        for words in ("расчётный маршрут (модель)", "синтетический индекс нестабильности", "нет расчётного маршрута",
                      "прогноз модели", "состояние неизвестно", "Синтетические данные. Расчёт модели, не сведения о реальной шахте"):
            self.assertIn(words, text)

    def test_user_visible_strings_live_in_text_js(self):
        """No Russian text in the code of any other module: views take their words from text.js (the 3D stage from text3d.js)."""
        for name, source in self.own().items():
            if not name.endswith(".js") or name in ("js/text.js", "js/text3d.js"):
                continue
            with self.subTest(file=name):
                self.assertEqual(re.findall(r"[А-Яа-яЁё]+", _strip_comments(source, "js")), [], name)


# --------------------------------------------------------------------------
# no console errors in any scenario, in any view
# --------------------------------------------------------------------------

class EveryScenarioTest(ScenarioTestCase):
    mock_args = ("--publication-ms", "100")

    def test_no_console_errors_in_any_scenario_with_each_view_opened(self):
        """All 24 scenarios, each with the stage (in its 3D mode), the list and the runs opened: no console error, the notice always there."""
        self.assertEqual(sorted(item["name"] for item in self.mock.scenarios()["scenarios"]), sorted(SCENARIOS),
                         "the mock has exactly the scenarios this test goes through")
        self.allow_console_errors = True    # checked here, per scenario
        problems = []
        for scenario in SCENARIOS:
            before = len(self.page.console_errors)
            self.open(scenario, ready=False)
            self.page.wait_for("document.body.dataset.boot !== 'loading'"
                               " && (document.body.dataset.snapshot !== 'none' || document.body.dataset.boot !== 'ready')",
                               timeout=10.0, message=f"{scenario}: the first outcome")
            seen = {}
            for view in ("list", "runs", "scheme"):
                self.show(view)
                time.sleep(0.45)    # several publications are read and rendered with this view in front
                seen[view] = self.page.evaluate(f"""(() => {{
                  const panel = document.getElementById('view-{view}');
                  return {{shown: !panel.hidden && panel.getClientRects().length > 0, text: panel.innerText.trim().length}};
                }})()""")
            state = self.body()
            notice = self.text('[data-testid="status-notice"]')
            errors = [entry["text"] for entry in self.page.console_errors[before:]]
            with self.subTest(scenario=scenario):
                self.assertEqual(errors, [], f"{scenario}: console errors")
                self.assertEqual(notice, "Синтетические данные. Расчёт модели, не сведения о реальной шахте")
                self.assertTrue(all(item["shown"] and item["text"] > 0 for item in seen.values()), f"{scenario}: {seen}")
                self.assertIn(state["boot"], ("ready", "empty"), scenario)
                self.assertEqual(self.page.evaluate("document.documentElement.scrollWidth - innerWidth"), 0, scenario)
            if errors:
                problems.append((scenario, errors[:2]))
        self.assertEqual(problems, [])



# --------------------------------------------------------------------------
# the checklist on the no-WebGL path
# --------------------------------------------------------------------------

class NoWebgl:
    """Chrome without WebGL: the stage falls back to the SVG scheme by itself (no `mode=scheme` in the route), and the
    checklist items run there unchanged. The notice and the strip on this path: test_composition.NoWebglTest."""

    chrome_args = ("--disable-webgl",)
    scheme_by_route = False


class NormalFrameNoWebglTest(NoWebgl, NormalFrameTest):
    test_manifest_batches_with_scrambled_order = None    # not about the stage


class PassageClosedNoWebglTest(NoWebgl, PassageClosedTest):
    pass


class SensorLostNoWebglTest(NoWebgl, SensorLostTest):
    pass


class ResultsNoWebglTest(NoWebgl, ResultsTest):
    pass


# --------------------------------------------------------------------------
# the checklist in the 3D stage
# --------------------------------------------------------------------------

# Chrome's software WebGL: what a judge's machine without a GPU is expected to resemble.
SWIFTSHADER = ("--use-angle=swiftshader", "--enable-unsafe-swiftshader")

# Every test starts with the stage's own remembered choices (mode, quality, spread of the slabs) forgotten.
FORGET_STAGE = """
try {
  if (!sessionStorage.getItem('stage-choices-forgotten')) {
    localStorage.removeItem('mine-ui.stage');
    sessionStorage.setItem('stage-choices-forgotten', '1');
  }
} catch (error) {}
"""

# The label buttons of the 3D stage by thingId: their state attributes (the same as the rows of the list),
# their lines of text, and whether a reader sees them (placed, not hidden by the decluttering, and on top
# at their centre, so not under the dock or the HUD).
LABELS = r"""(() => {
  const out = {};
  for (const node of document.querySelectorAll('#stage-3d .s3-label[data-thing-id]')) {
    const {thingId, label, rank, culled, group, ...state} = node.dataset;
    const box = node.getBoundingClientRect();
    const hit = box.width > 0 ? document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2) : null;
    out[thingId] = {
      ...state, group: group || null,
      shown: !node.hasAttribute('data-culled') && box.width > 0 && !!hit && node.contains(hit),
      lines: [...node.querySelectorAll('.s3-label__line')].map((line) => line.textContent.replace(/\u00a0/g, ' ')),
      signs: [...node.querySelectorAll('[data-symbol]')].map((sign) => sign.dataset.symbol.replace(/^sign:/, '')),
      aria: node.getAttribute('aria-label'), pressed: node.getAttribute('aria-pressed'), cls: node.className,
    };
  }
  return out;
})()"""

SCENE_DRAWN = """(() => {
  const s = document.querySelector('#stage').dataset;
  return s.stageMode === '3d' && Number(s.frames) > 0 && s.measuredMs !== undefined && s.rendering === 'idle' && Number(s.levels) > 0;
})()"""

APP = "(await import('/js/main.js')).app"
HAZARD_SIGNS = ("attention", "danger", "unknown", "lastDanger")


class Stage3dScenarioCase(ScenarioTestCase):
    """The page with the stage in its 3D mode, rendered by SwiftShader; the scene is the subject."""

    chrome_args = SWIFTSHADER

    def setUp(self):
        super().setUp()
        self.page.add_init_script(FORGET_STAGE)

    def open3d(self, scenario, route=""):
        self.open(scenario, route)
        self.wait_scene()

    def wait_scene(self, timeout=30.0):
        try:
            self.page.wait_for(SCENE_DRAWN, timeout=timeout, message="the 3D stage is drawn")
        except AssertionError as error:
            raise AssertionError(f"{error}\nstage: {self.stage()}") from None

    def wait_idle(self, timeout=10.0):
        self.page.wait_for("document.querySelector('#stage').dataset.rendering === 'idle'", timeout=timeout,
                           message="the 3D stage stopped rendering")
        return self.stage()

    def stage(self):
        return self.page.evaluate("Object.assign({}, document.getElementById('stage').dataset)")

    def labels(self):
        return self.page.evaluate(LABELS)

    def label(self, name):
        return self.labels().get(thing(name))

    def label_selector(self, name):
        return f'#stage-3d .s3-label[data-thing-id="{thing(name)}"]'

    def wait_label(self, name, condition, timeout=8.0, message=""):
        """Wait until the label of `name` satisfies a JS condition on `node` (the button); return the label."""
        try:
            self.page.wait_for(f"(() => {{ const node = document.querySelector({json.dumps(self.label_selector(name))});"
                               f" return !!node && ({condition}); }})()", timeout=timeout, message=message or f"label {name}: {condition}")
        except AssertionError as error:
            raise AssertionError(f"{error}\nlabel: {self.label(name)}") from None
        return self.label(name)

    def wait_label_shown(self, name, timeout=8.0):
        """Wait until the label of `name` is placed and readable (labels are placed on the next frame of the scene)."""
        deadline = time.monotonic() + timeout
        while True:
            label = self.label(name)
            if label and label["shown"]:
                return label
            if time.monotonic() > deadline:
                self.fail(f"the label of {name} is not in sight: {label}")
            time.sleep(0.1)

    def camera(self):
        return self.stage()["camera"]

    def screen_of(self, name):
        return self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(thing(name))});")

    def published(self):
        """The shift as the mock publishes it now, read by the test itself: {local name: {feature: value}}, "shift" for the shift."""
        answer = self.mock.request("GET", SHIFT_PATH)
        values = {"shift": {name: feature["properties"]["value"] for name, feature in answer["features"].items()}}
        for item in values["shift"]["scene"]:
            values[item["thingId"].split(":")[1]] = {name: feature["properties"]["value"]
                                                     for name, feature in item["features"].items()}
        return values

    def assert_labels_match_the_list(self, labels):
        """The state attributes of the label buttons are those of the rows of «Список» (the same twins, the same codes)."""
        self.show("list")
        rows = self.page.evaluate("""(() => {
          const out = {};
          for (const node of document.querySelectorAll('[data-testid="list"] tr[data-thing-id]')) {
            const {thingId, ...state} = node.dataset;
            out[thingId] = state;
          }
          return out;
        })()""")
        self.show("scheme")
        keys = ("kind", "hazard", "quality", "lastKnownHazard", "passability", "restriction", "pending", "workState", "withdrawal",
                "link", "status", "egress", "locationHazard", "posQuality", "state")
        compared = 0
        for thing_id, state in labels.items():
            if thing_id in rows:
                self.assertEqual({key: state.get(key) for key in keys}, {key: rows[thing_id].get(key) for key in keys}, thing_id)
                compared += 1
        self.assertGreaterEqual(compared, 20, "labels and rows were compared")


class Checklist3dTest(Stage3dScenarioCase):
    """The checklist items that show the mine, read from the 3D stage: its label buttons (the accessible
    mirror of the scene) and the attributes it mirrors on #stage. The scheme versions are the tests above."""

    def test_normal_frame(self):
        """Обычная смена in 3D: three slabs, every working and every person under ground, quiet labels."""
        self.page.add_init_script(PROBE)
        self.open3d("normal")
        stage = self.stage()
        self.assertEqual((stage["stageMode"], stage["renderer"], stage["quality"]), ("3d", "software", "low"),
                         "SwiftShader is a software renderer: the light quality is chosen by itself")
        self.assertNotIn("fallback", stage)
        self.assertEqual((stage["levels"], stage["workings"], stage["workersDrawn"], stage["routes"]), ("3", "36", "14", "0"),
                         "one slab per level, every working, the 14 people under ground, no route until something is selected")
        self.assertEqual(self.page.evaluate("getComputedStyle(document.getElementById('scheme')).display"), "none",
                         "the SVG scheme is not drawn under the model")
        self.assertEqual(self.banners(), [])

        labels = self.labels()
        by_kind = {}
        for state in labels.values():
            by_kind.setdefault(state["kind"], []).append(state)
        self.assertEqual({kind: len(items) for kind, items in by_kind.items()},
                         {"level": 3, "zone": 4, "exit": 3, "working": 36, "sensor": 10, "worker": 14},
                         "one label button per placed twin (in `normal` nobody shares a stretch)")
        for kind in ("level", "zone", "exit"):
            self.assertTrue(all(item["shown"] for item in by_kind[kind]), f"every {kind} is labelled in the overview")
        zones = {name: labels[thing(name)] for name in ("zone-a", "zone-b", "zone-c", "zone-d")}
        self.assertEqual({name: item["hazard"] for name, item in zones.items()},
                         {"zone-a": "normal", "zone-b": "normal", "zone-c": "normal", "zone-d": "attention"})
        # The 3D zone tag adds the published count of its people (clarity pass, A10).
        self.assertEqual(zones["zone-d"]["lines"][0], "Участок Г: внимание · 3 чел.")
        self.assertEqual(zones["zone-d"]["signs"], ["attention"], "attention has its triangle, not only a colour")
        self.assertEqual([sign for sign in zones["zone-a"]["signs"] if sign in HAZARD_SIGNS], [], "a normal zone has no hazard sign")
        self.assertTrue(all(item["state"] == "available" for item in by_kind["exit"]))
        self.assertTrue(all((item["egress"], item["status"]) == ("ok", "working") for item in by_kind["worker"]))
        problems = [thing_id for thing_id, item in labels.items() if "s3-label--problem" in item["cls"] or "s3-label--noroute" in item["cls"]]
        self.assertEqual(problems, [], "nothing is marked as a problem in an undisturbed shift")
        self.assertEqual(self.counters(), {"in-danger": "0", "no-route": "0", "unknown": "0", "out": "0", "total": "14"})
        self.assert_labels_match_the_list(labels)

        # The model time goes on and the still picture draws nothing new.
        self.wait_idle()
        self.page.evaluate("window.__probe.raf = 0")
        tick = int(self.body()["tick"])
        self.wait_seq(2)
        self.assertGreater(int(self.body()["tick"]), tick)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "no frame while nothing visible changes")
        self.assertEqual(self.commands_logged(), [], "a plain look at the screen sends no command")
        self.assert_only_contract_requests()

    def test_detour(self):
        """Обход in 3D: the selected worker's route is drawn on the model; after В-12 closes, a barricade and the longer route."""
        self.open3d("detour")
        # The zone by its label, closer with «Показать на модели» of the card, then the worker by his label.
        self.page.click(self.label_selector("zone-b"))
        self.page.wait_for(f"location.hash.includes('sel={thing('zone-b')}')", timeout=3.0)
        self.page.wait_for("document.querySelector('#stage').dataset.routes === '4'", timeout=3.0,
                           message="the routes of the four people of the zone are drawn while it is selected")
        overview = self.camera()
        self.page.click('[data-testid="card-focus"]')
        self.page.wait_for(f"document.querySelector('#stage').dataset.camera !== {json.dumps(overview)}", timeout=3.0,
                           message="«Показать на модели» moves the camera")
        self.wait_idle()
        self.wait_label_shown("worker-03")
        self.page.click(self.label_selector("worker-03"))
        self.page.wait_for(f"location.hash.includes('sel={thing('worker-03')}')", timeout=3.0)
        self.wait_label("worker-03", "node.getAttribute('aria-pressed') === 'true'")
        self.page.wait_for(f"document.querySelector('#stage').dataset.routes === '1'"
                           f" && document.querySelector('#stage-3d .s3').dataset.selected === {json.dumps(thing('worker-03'))}",
                           timeout=3.0, message="the route of the selected worker, and only his")
        self.assertIn("расчётный маршрут (модель): 412 м, около 5 мин 30 с, выход Ствол", self.card())

        frames = int(self.wait_idle()["frames"])
        close_working(self.page, "w-12")
        wait_decision(self.page)
        closed = self.wait_label("w-12", "node.dataset.passability === 'closed'")
        self.assertIn("s3-label--closed", closed["cls"])
        self.assertEqual(closed["lines"], ["В-12", "проход закрыт", "условие стенда"], "the barricade says who closed it")
        self.assertIn("blocked", closed["signs"])
        self.assertEqual(self.wait_label_shown("w-12")["passability"], "closed")
        sentence = "расчётный маршрут (модель): 655 м (длиннее на 243 м), около 8 мин 44 с, выход Съезд"
        self.page.wait_for(f"document.querySelector('[data-testid=\"card\"]').textContent.replace(/\\u00a0/g, ' ').includes({json.dumps(sentence)})",
                           timeout=4.0, message="the card names the published detour")
        stage = self.wait_idle()
        self.assertEqual(stage["routes"], "1", "the selected worker's new route replaces the old one")
        self.assertGreater(int(stage["frames"]), frames, "the model was drawn again with the barricade and the new route")
        self.assertEqual(self.text('[data-testid="status-conditions"]'), "Условия стенда: В-12 закрыта")
        self.assertEqual(self.counters()["no-route"], "0")

    def test_no_path(self):
        """Отсутствие пути in 3D: the barricade of В-07 and two labels «нет расчётного маршрута», no route line invented."""
        self.open3d("no_path")
        close_working(self.page, "w-07")
        wait_decision(self.page)
        closed = self.wait_label("w-07", "node.dataset.passability === 'closed'")
        self.assertEqual(closed["lines"], ["В-07", "проход закрыт", "условие стенда"])
        self.wait_label_shown("w-07")
        for name in ("worker-07", "worker-08"):
            self.wait_label(name, "node.dataset.egress === 'none'")
        self.wait_idle()
        labels = self.labels()
        stranded = {thing_id: item for thing_id, item in labels.items() if item["kind"] == "worker" and item["egress"] == "none"}
        self.assertEqual(sorted(stranded), [thing("worker-07"), thing("worker-08")])
        for thing_id, item in stranded.items():
            self.assertTrue(item["shown"], f"{thing_id}: a person without a route is labelled in the overview")
            self.assertEqual(item["lines"][1:], ["нет расчётного маршрута"], thing_id)
            self.assertIn("s3-label--noroute", item["cls"])
            self.assertEqual((item["status"], item["locationHazard"]), ("working", "normal"), "the other two axes are their own")
        self.assertEqual(self.counters(), {"in-danger": "0", "no-route": "2", "unknown": "0", "out": "0", "total": "14"})

        # Enter on the label selects the worker: no route line is drawn for him, and the card says why.
        self.page.evaluate(f"document.querySelector({json.dumps(self.label_selector('worker-07'))}).focus()")
        self.page.press("Enter")
        self.page.wait_for(f"location.hash.includes('sel={thing('worker-07')}')", timeout=3.0)
        stage = self.wait_idle()
        self.assertEqual(stage["routes"], "0", "no route line is invented")
        self.assertIn("Р-07: нет расчётного маршрута. В графе модели нет открытого пути до выхода", self.card())

    def test_sensor_lost_after_danger(self):
        """Потерянный датчик после danger in 3D: unknown now, and the last known danger in the zone's label."""
        self.open3d("sensor_lost_after_danger")
        labels = self.labels()
        zone = labels[thing("zone-c")]
        self.assertEqual((zone["hazard"], zone["quality"], zone["lastKnownHazard"]), ("unknown", "lost", "danger"))
        # The moment of the last assessment by the model clock (clarity pass, A8); U2 may add the count of people.
        self.assertTrue(zone["lines"][0].startswith("Участок В: состояние неизвестно"), zone["lines"])
        self.assertTrue(zone["lines"][1].startswith("последнее известное: опасно в 00:13:30"), zone["lines"])
        self.assertEqual(zone["lines"][2:], ["данные потеряны", "новый вход запрещён моделью"])
        self.assertEqual(zone["signs"][:2], ["unknown", "lastDanger"], "unknown and the past danger by their signs")
        self.assertIn("blocked", zone["signs"])
        self.assertIn("s3-label--unknown", zone["cls"], "unknown is never drawn like normal")
        sensor = labels[thing("sens-ext-05")]
        self.assertEqual((sensor["quality"], sensor["link"], sensor["lines"]), ("lost", "offline", ["Э-05 · данные потеряны"]))
        self.assertTrue(sensor["shown"], "the lost sensor is labelled in the overview")
        for name in ("w-20", "w-21"):
            working = labels[thing(name)]
            self.assertEqual((working["hazard"], working["lastKnownHazard"], working["restriction"]), ("unknown", "danger", "blocked"))
        self.assertEqual(self.counters(), {"in-danger": "0", "no-route": "0", "unknown": "2", "out": "0", "total": "14"})

        # «показать» of what changed brings the zone and its last known danger into sight.
        overview = self.camera()
        self.page.click('[data-testid="situation-show-1"]')
        self.page.wait_for(f"document.querySelector('#stage').dataset.camera !== {json.dumps(overview)}", timeout=3.0,
                           message="«показать» moves the camera")
        self.wait_idle()
        shown = self.wait_label_shown("zone-c")
        self.assertTrue(any(line.startswith("последнее известное: опасно в 00:13:30") for line in shown["lines"]), shown["lines"])
        self.assert_labels_match_the_list(self.labels())

    def test_problem_zone_tags_are_in_sight_in_the_overview(self):
        """Zone tags with their state are always labelled (redesign spec 3, «Labels»): in the overview, at both sizes,
        the zone a story is about is not the one left out."""
        for size in ((1280, 720), (1920, 1080)):
            self.page.set_viewport(*size)
            for scenario in ("sensor_lost_after_danger", "danger_zone"):
                self.open3d(scenario)
                if scenario == "danger_zone":
                    self.wait_body(12.0, runState="paused")
                self.wait_idle()
                time.sleep(0.5)
                with self.subTest(size=size, scenario=scenario):
                    zones = {thing_id.split(":")[1]: (item["hazard"], item["shown"])
                             for thing_id, item in self.labels().items() if item["kind"] == "zone"}
                    hidden = sorted(name for name, (_, shown) in zones.items() if not shown)
                    self.assertEqual(hidden, [], f"zone tags not in sight in the overview: {zones}")

    def test_danger_zone(self):
        """Опасный участок in 3D: the zone in danger, the three people in it, the top bar and the dock with three options."""
        self.open3d("danger_zone")
        self.wait_body(12.0, runState="paused")
        zone = self.wait_label("zone-d", "node.dataset.hazard === 'danger'")
        self.assertEqual((zone["quality"], zone["lines"]), ("fresh", ["Участок Г: опасно · 3 чел.", "новый вход запрещён моделью"]))
        self.assertIn("s3-label--danger", zone["cls"])
        self.assertEqual(zone["signs"][0], "danger", "danger has its octagon, not only a colour")
        self.wait_idle()
        labels = self.labels()
        self.assertTrue(labels[thing("zone-d")]["shown"])
        people = {thing_id.split(":")[1]: item for thing_id, item in labels.items() if item["kind"] == "worker"
                  and item["locationHazard"] == "danger"}
        self.assertEqual(sorted(people), ["worker-11", "worker-12", "worker-13"])
        for name, item in people.items():
            self.assertTrue(item["shown"], f"{name}: a person in a danger zone is labelled in the overview")
            self.assertIn("в опасной зоне", item["lines"])
            self.assertEqual(item["egress"], "ok", "in a danger zone and with a route: two axes")
        stale = labels[thing("zone-c")]
        self.assertEqual((stale["hazard"], stale["quality"], stale["lastKnownHazard"]), ("unknown", "stale", "normal"))
        self.assertEqual(labels[thing("sens-ext-05")]["quality"], "stale")

        # The top bar: the counters the model published.
        self.assertEqual(self.counters(), {"in-danger": "3", "no-route": "0", "unknown": "2", "out": "0", "total": "14"})
        self.assertEqual(plain(self.page.evaluate(
            "document.querySelector('[data-testid=\"incident-in-danger\"]').closest('.figure').textContent")), "в опасных зонах 3")
        published = self.published()["shift"]
        self.assertEqual((published["workers_in_danger"], published["workers_unknown"]), (3, 2))

        # The dock with the three options of the model.
        show_right(self.page, "decision")
        self.assertTrue(self.visible("#decision"))
        self.assertEqual(self.count(f'{DECISION} th[data-state="offered"]'), 3)
        self.assertEqual(self.page.evaluate(f"[...document.querySelectorAll('{DECISION} th[data-column]')].map((th) => th.dataset.column)"),
                         ["option-observe", "option-stop-withdraw", "option-withdraw-all"])

    def test_options_compared_by_their_people_bars(self):
        """Сравнение вариантов: the people bar of each option holds the published forecast, and nothing else."""
        self.open3d("paused_heartbeat")
        show_right(self.page, "decision")
        published = self.published()
        bars = self.page.evaluate("""[...document.querySelectorAll('[data-testid="decision-options"] [data-testid="people-bar"]')]
          .map((bar) => ({option: bar.closest('[data-option]').dataset.option, series: bar.dataset.series, out: bar.dataset.out,
                          inDanger: bar.dataset.inDanger, noRoute: bar.dataset.noRoute, total: bar.dataset.total || null,
                          cells: bar.querySelectorAll('.pb__cell').length}))""")
        self.assertEqual(sorted(bar["option"] for bar in bars), ["option-observe", "option-stop-withdraw", "option-withdraw-all"])
        for bar in bars:
            values = published[bar["option"]]
            with self.subTest(option=bar["option"]):
                self.assertEqual(bar["series"], "forecast")
                self.assertEqual((bar["out"], bar["inDanger"], bar["noRoute"]),
                                 (str(values["forecast_out"]), str(values["forecast_in_danger"]), str(values["forecast_no_route"])))
                self.assertEqual(bar["total"], "14", "the common group: «Вывести всех» publishes everyone out")
                self.assertEqual(bar["cells"], 14, "one cell per person of the group")
                self.assertEqual(self.metric(bar["option"], "forecast_out"), str(values["forecast_out"]))
        self.assertEqual(self.stage()["stageMode"], "3d", "the dock lies beside the model, which stays")

    def test_platform_unavailable(self):
        """Платформа недоступна in 3D: the model is marked as the last data, and nothing moves."""
        self.page.add_init_script(PROBE)
        self.open3d("normal")
        self.wait_seq(1)
        workers = ("worker-03", "worker-07", "worker-12")
        before = {name: self.screen_of(name)["world"] for name in workers}
        tick = self.body()["tick"]
        self.mock.fault("http_502")
        state = self.wait_body(10.0, link="unavailable")
        self.assertEqual(state["commands"], "blocked")
        self.page.wait_for("document.querySelector('#stage-3d .s3').hasAttribute('data-old')", timeout=3.0,
                           message="the scene marks itself as showing the last data")
        stage = self.wait_idle()
        tick = self.body()["tick"]
        self.assertEqual(stage["tweens"], "0")
        # The caption lets the pointer through (pointer-events: none), so it is checked by its box, not by a hit.
        inside = self.page.evaluate("""(() => {
          const caption = document.querySelector('#stage-3d .s3__old-text').getBoundingClientRect();
          const stage = document.getElementById('stage').getBoundingClientRect();
          return caption.width > 0 && caption.left >= stage.left && caption.right <= stage.right
            && caption.top >= stage.top && caption.bottom <= stage.bottom;
        })()""")
        self.assertTrue(inside, "the caption of the old data lies on the stage")
        self.assertIn("последние полученные данные", self.text("#stage-3d .s3__old-text"))
        self.assertRegex(self.text("#old-data"), rf"^Показаны данные на \d\d:\d\d:\d\d UTC, тик {tick}\. Текущее состояние неизвестно$")
        self.assertTrue(self.wait_banner("platform_unavailable", 2.0)["text"].startswith("Платформа недоступна (HTTP 502)"))
        after = {name: self.screen_of(name)["world"] for name in workers}
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(2.2)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "no frame: motion has stopped")
        self.assertEqual({name: self.screen_of(name)["world"] for name in workers}, after, "everyone stays at the last read position")
        self.assertEqual(after, before, "in `normal` nobody walks: the positions are those of the last full snapshot")
        self.assertEqual(self.labels()[thing("zone-d")]["hazard"], "attention", "nothing becomes anything else while the platform is away")

        self.mock.fault("none")
        self.wait_body(10.0, link="ok", snapshot="ok", commands="enabled")
        self.page.wait_for("!document.querySelector('#stage-3d .s3').hasAttribute('data-old')", timeout=3.0,
                           message="the mark goes with the first full snapshot")

    def test_invalid_snapshot_keeps_the_last_scene(self):
        """Невалидный снимок in 3D: the last full state stays on the model, marked as old; commands are blocked."""
        self.open3d("invalid_missing_field")
        full = self.labels()
        self.wait_body(10.0, snapshot="invalid")
        self.page.wait_for("document.querySelector('#stage-3d .s3').hasAttribute('data-old')", timeout=3.0)
        tick = self.body()["tick"]
        self.assertEqual(self.wait_banner("snapshot_invalid", 2.0)["reason"], "missing_field")
        time.sleep(2.0)
        self.assertEqual(self.body()["tick"], tick, "the state of the rejected snapshots is not shown")
        stage = self.stage()
        self.assertEqual((stage["workersDrawn"], stage["levels"]), ("14", "3"), "the last full state stays drawn")
        keys = ("hazard", "quality", "egress", "status", "state", "passability")
        self.assertEqual({key: {k: item.get(k) for k in keys} for key, item in self.labels().items()},
                         {key: {k: item.get(k) for k in keys} for key, item in full.items()})
        self.assertEqual(self.body()["commands"], "blocked")
