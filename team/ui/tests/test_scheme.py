"""The scheme, the legend and the card against the mock server.

The scheme is the «Схема» mode of the stage (the 3D model is the other one):
every page here is opened with `mode=scheme` in its route, the switch a user
has too. The page under test is the production static; nothing in it is
switched for the test. What is drawn is read from the DOM contract (`data-thing-id`,
`data-kind` and the state attributes of the implementation spec, section 5)
and compared with the rows of the «Список» view, which show the same twins.

    python -m unittest discover -s team/ui/tests -t team/ui -p "test_scheme.py" -v
"""

from __future__ import annotations

import json
import os
import time

from browser_support import OUTPUT_DIR, BrowserTestCase, MockServer
from screenshots import REWRITE_SHIFT

NS = "team040.mine"
NBSP = " "
APP = "const {app} = await import('/js/main.js'); const state = app.store.getState();"
STATE_ATTRIBUTES = ("kind", "hazard", "quality", "lastKnownHazard", "passability", "restriction", "pending",
                    "workState", "withdrawal", "link", "status", "egress", "locationHazard", "posQuality", "state")

# Counts calls that the design forbids, from before the first script of the page.
PROBE = """
window.__probe = {canvas: 0, raf: 0};
const getContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function (...args) { window.__probe.canvas += 1; return getContext.apply(this, args); };
const raf = window.requestAnimationFrame;
window.requestAnimationFrame = function (callback) { window.__probe.raf += 1; return raf.call(window, callback); };
"""

# Every twin drawn in the scheme and every row of the list, read in one step (one snapshot).
DRAWN = """(() => {
  const pick = (node) => {
    const out = {};
    for (const name of %s) out[name] = node.dataset[name] === undefined ? null : node.dataset[name];
    return out;
  };
  const scheme = {};
  for (const node of document.querySelectorAll('#scheme [data-thing-id]')) {
    (scheme[node.dataset.thingId] = scheme[node.dataset.thingId] || []).push(pick(node));
  }
  const list = {};
  for (const row of document.querySelectorAll('[data-testid="list"] tbody tr')) list[row.dataset.thingId] = pick(row);
  return {scheme, list, tick: document.body.dataset.tick};
})()""" % (list(STATE_ATTRIBUTES),)


def plain(text):
    return " ".join(text.replace(NBSP, " ").split()) if isinstance(text, str) else text


def thing(name):
    return f"{NS}:{name}"


def scheme_route(route):
    """The route with the stage in its scheme mode (`mode=scheme`), as the stage switch sets it."""
    if not route:
        return "#/scheme?mode=scheme"
    return route + ("&" if "?" in route else "?") + "mode=scheme"


class SchemeTestCase(BrowserTestCase):
    viewport = (1280, 720)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock = MockServer("normal").start()
        cls.addClassCleanup(cls.mock.stop)

    # ---- helpers ---------------------------------------------------------

    def open(self, scenario, route="", mock=None, ready=True):
        mock = mock or self.mock
        mock.scenario(scenario)
        self.page.goto("about:blank")
        self.page.goto(mock.url + "/" + scheme_route(route))
        if ready:
            self.wait_drawn()

    def js(self, body, timeout=20.0):
        return self.page.evaluate("(async () => {" + body + "})()", timeout=timeout)

    def wait_drawn(self, timeout=15.0):
        self.page.wait_for("document.body.dataset.boot === 'ready' && document.body.dataset.snapshot === 'ok'"
                           " && document.querySelector('[data-testid=\"scheme-svg\"]').dataset.drawn === 'true'"
                           " && document.querySelector('#scheme .worker')", timeout=timeout, message="scheme drawn")

    def node(self, name):
        return f"#scheme [data-thing-id=\"{thing(name)}\"]"

    def attrs(self, name):
        return self.page.evaluate(f"(() => {{ const node = document.querySelector('{self.node(name)}');"
                                  " return node ? Object.assign({cls: node.getAttribute('class'),"
                                  " label: node.getAttribute('aria-label')}, node.dataset) : null; })()")

    def shown(self, selector):
        """True when the element exists and is rendered (not `display: none`)."""
        return self.page.evaluate(f"(() => {{ const node = document.querySelector({selector!r});"
                                  " return Boolean(node) && getComputedStyle(node).display !== 'none'; })()")

    def text_of(self, selector):
        """The text of an element, its text nodes joined by spaces (also when it is not rendered)."""
        return plain(self.page.evaluate(f"""(() => {{
          const root = document.querySelector({selector!r});
          if (!root) return '';
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
          const parts = [];
          while (walker.nextNode()) parts.push(walker.currentNode.nodeValue);
          return parts.join(' ');
        }})()"""))

    def scheme_text(self):
        return plain(self.page.evaluate(
            "[...document.querySelectorAll('#scheme .tag')].map((tag) => [...tag.querySelectorAll('tspan')]"
            ".map((line) => line.textContent).join(' / ')).join(' | ')"))

    def card(self):
        return self.text_of('[data-testid="card"]')

    def select(self, name):
        self.js(APP + f"app.ctx.select({thing(name)!r});")

    def send(self, command, target):
        result = self.js(APP + f"return app.ctx.sendCommand({command!r}, {target!r});")
        self.assertTrue(result["ok"], f"{command} {target} was not sent: {result}")
        return result

    def wait_attr(self, name, attribute, value, timeout=10.0):
        self.page.wait_for(f"document.querySelector('{self.node(name)}').getAttribute('data-{attribute}') === {value!r}",
                           timeout=timeout, message=f"{name} data-{attribute}={value}")

    def wait_polls(self, count, timeout=15.0):
        start = int(self.page.evaluate("document.body.dataset.seq"))
        self.page.wait_for(f"Number(document.body.dataset.seq) >= {start + count}", timeout=timeout,
                           message=f"{count} more publications read")

    def position(self, name):
        return self.page.evaluate(f"document.querySelector('{self.node(name)}').style.transform")

    # ---- what is drawn -----------------------------------------------------

    def test_every_placed_twin_is_drawn_once_with_the_attributes_of_its_list_row(self):
        self.open("normal")
        drawn = self.page.evaluate(DRAWN)
        scheme, rows = drawn["scheme"], drawn["list"]
        kinds = {}
        for thing_id, row in rows.items():
            if row["kind"] not in ("working", "zone", "sensor", "exit", "worker"):
                self.assertNotIn(thing_id, scheme, "a twin without a place is not on the scheme")
                continue
            self.assertIn(thing_id, scheme, f"{thing_id} is drawn")
            self.assertEqual(len(scheme[thing_id]), 1, f"{thing_id} is drawn exactly once")
            self.assertEqual(scheme[thing_id][0], row, f"{thing_id}: the scheme and the list carry the same state")
            kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
        self.assertEqual(kinds, {"working": 36, "zone": 4, "sensor": 10, "exit": 3, "worker": 14})
        self.assertEqual(set(scheme), {thing_id for thing_id, row in rows.items() if row["kind"] in kinds})

        roles = self.page.evaluate("""[...document.querySelectorAll('#scheme [data-thing-id]')].every((node) =>
          node.getAttribute('tabindex') === '0' && node.getAttribute('role') === 'button'
          && (node.getAttribute('aria-label') || '').length > 3)""")
        self.assertTrue(roles, "every object is focusable and named")
        self.assertEqual(self.page.evaluate("document.querySelectorAll('#scheme canvas, #legend canvas').length"), 0)
        # The three axes of a working without sensors, of a normal zone and of a worker with a route.
        self.assertTrue(self.shown(self.node("w-12") + " .working__line"), "no sensors: a bare line")
        self.assertTrue(self.shown(self.node("w-14") + " .working__band"), "an assessed working: a band")
        self.assertIn("url(", self.page.evaluate(
            f"document.querySelector('{self.node('w-23')} .working__band').style.fill"), "attention is hatched")
        self.assertTrue(self.shown(self.node("worker-03") + " .worker__ok"))
        self.assertFalse(self.shown(self.node("worker-03") + " .worker__none"))
        labels = self.scheme_text()
        for expected in ("Участок Б: норма", "Участок Г: внимание", "Ствол · вышло 0", "выход доступен (модель)",
                         "ствол В-01", "съезд В-03", "восстающий В-05", "Р-03"):
            self.assertIn(expected, labels)
        self.assertNotIn("В-14", labels, "ordinary working codes are left to the plan and the list")
        self.assertIn("Вертикаль не в масштабе; координаты условные, метры", self.text_of("#scheme .scheme__note"))
        self.assertIn("Гор. −320 м", self.text_of("#scheme .layer--planes"))

    def test_states_without_a_snapshot_are_unknown_never_normal(self):
        self.open("normal")
        # The state the reader leaves when attributes are read and no full snapshot was ever accepted. It is set
        # through the store and read back in the same step, before the next poll can replace it.
        drawn = self.js(APP + """
          const {buildModel} = await import('/js/model.js');
          app.store.update({snapshot: null, model: buildModel(state.attributes, null)});
          const all = (selector) => [...document.querySelectorAll('#scheme ' + selector)];
          const visible = (node) => node !== null && getComputedStyle(node).display !== 'none';
          return {
            hazards: all('[data-hazard]').map((node) => node.dataset.hazard),
            bands: all('.working').every((node) => node.querySelector('.working__band') !== null),
            workers: all('.worker').length,
            exits: all('.exit').map((node) => [node.dataset.state === undefined, visible(node.querySelector('.exit__unknown')),
              visible(node.querySelector('.exit__arrow'))]),
            sensors: all('.sensor').map((node) => [visible(node.querySelector('.sensor__unknown')), visible(node.querySelector('.sensor__dot'))]),
            note: document.querySelector('#scheme .scheme__note').textContent,
            zone: document.querySelector('#scheme .zone').textContent,
          };""")
        self.assertEqual(len(drawn["hazards"]), 40)
        self.assertEqual(set(drawn["hazards"]), {"unknown"}, "nothing is normal by default")
        self.assertTrue(drawn["bands"], "no working is drawn as a line without sensors: that is a published fact too")
        self.assertEqual(drawn["workers"], 0, "no position is invented")
        self.assertEqual(drawn["exits"], [[True, True, False]] * 3)
        self.assertEqual(drawn["sensors"], [[True, False]] * 10)
        self.assertIn("состояние не получено", drawn["note"])
        self.assertIn("состояние неизвестно", drawn["zone"])

    def test_detour_barrier_route_and_card(self):
        self.open("detour")
        self.send("condition.close_working", "w-12")
        self.wait_attr("w-12", "passability", "closed")
        self.assertTrue(self.shown(self.node("w-12") + " .working__barrier"), "a closed passage has a barrier")
        self.assertIn("В-12 · проход закрыт / условие стенда", self.scheme_text())
        # Nothing selected and an open incident: the routes of the workers of its zone are shown at once.
        self.page.wait_for("document.querySelectorAll('#scheme .route[data-reason=\"incident\"]').length === 4",
                           message="routes of the incident zone")
        self.select("worker-03")
        self.page.wait_for("document.querySelectorAll('#scheme .route[data-reason=\"selection\"]').length === 1",
                           message="route overlay")
        route = self.page.evaluate("Object.assign({d: document.querySelector('#scheme .route .route__line').getAttribute('d'),"
                                   " arrows: document.querySelector('#scheme .route .route__arrows').getAttribute('d')},"
                                   " document.querySelector('#scheme .route').dataset)")
        self.assertEqual(route["worker"], thing("worker-03"))
        self.assertEqual(route["workings"].split(), ["w-14", "w-15", "w-18", "w-03"])
        self.assertNotIn("w-12", route["workings"])
        self.assertGreater(route["d"].count("L"), 5, "the ramp is followed through its intermediate points")
        self.assertGreater(route["arrows"].count("M"), 3, "the route carries direction arrows")
        card = self.card()
        self.assertIn("расчётный маршрут (модель): 655 м (длиннее на 243 м), около 8 мин 44 с", card)
        self.assertIn("В-14 → В-15 → В-18 → В-03", card)
        self.assertNotIn("безопасн", self.page.evaluate("document.body.textContent").lower())
        self.assertTrue(self.attrs("worker-03")["cls"].count("is-selected"))

        # The routes of every worker of a selected zone.
        self.select("zone-b")
        self.page.wait_for("document.querySelectorAll('#scheme .route').length === 4", message="routes of the zone")

    def test_no_path_markers_and_card(self):
        self.open("no_path")
        self.send("condition.close_working", "w-07")
        self.wait_attr("worker-07", "egress", "none")
        without = self.page.evaluate("[...document.querySelectorAll('#scheme .worker[data-egress=\"none\"]')]"
                                     ".map((node) => node.dataset.thingId)")
        self.assertEqual(sorted(without), [thing("worker-07"), thing("worker-08")])
        for name in ("worker-07", "worker-08"):
            self.assertTrue(self.shown(self.node(name) + " .worker__none"), "a square crossed marker")
            self.assertFalse(self.shown(self.node(name) + " .worker__ok"))
            self.assertFalse(self.shown(self.node(name) + " .worker__unknown"))
        self.assertTrue(self.shown(self.node("worker-01") + " .worker__ok"))
        self.assertIn("Р-07 / нет расчётного маршрута", self.scheme_text())
        # No route in a zone that is normal: the two axes stay apart.
        self.assertEqual(self.attrs("zone-c")["hazard"], "normal")
        self.assertEqual(self.attrs("worker-07")["locationHazard"], "normal")
        self.select("worker-07")
        self.page.wait_for("document.querySelector('[data-testid=\"card\"]').textContent.includes('Р-07')")
        card = self.card()
        self.assertIn("нет расчётного маршрута", card)
        self.assertIn("В графе модели нет открытого пути до выхода", card)
        self.assertIn("утверждение о графе модели", card)
        self.assertIn("участок: норма", card)
        self.assertEqual(self.page.evaluate("document.querySelectorAll('#scheme .route').length"), 0)

    def test_normal_draws_no_route_until_something_is_selected(self):
        self.open("normal")
        self.assertEqual(self.page.evaluate("document.querySelectorAll('#scheme .route').length"), 0)
        self.select("worker-07")
        self.page.wait_for("document.querySelector('#scheme .route')", message="route overlay")
        self.assertEqual(self.page.evaluate("document.querySelector('#scheme .route').dataset.workings"),
                         "w-21 w-20 w-07 w-09 w-08 w-22 w-05")

    def test_sensor_lost_after_danger_keeps_the_last_known_danger(self):
        self.open("sensor_lost_after_danger")
        zone = self.attrs("zone-c")
        self.assertEqual((zone["hazard"], zone["quality"], zone["lastKnownHazard"]), ("unknown", "lost", "danger"))
        text = self.text_of(self.node("zone-c"))
        self.assertIn("Участок В: состояние неизвестно", text)
        self.assertIn("данные потеряны", text)
        self.assertIn("последнее известное: опасно (тик", text)
        self.assertIn("новый вход запрещён моделью", text)
        self.assertNotIn("норма", text)
        self.assertTrue(self.page.evaluate("document.querySelector('#scheme .halo--unknown.halo--last-danger') !== null"))
        for name in ("w-20", "w-21"):
            working = self.attrs(name)
            self.assertEqual((working["hazard"], working["lastKnownHazard"]), ("unknown", "danger"))
            self.assertIn("working--last-danger", working["cls"])
            self.assertTrue(self.shown(self.node(name) + " [data-sign=\"lastDanger\"]"))
        sensor = self.attrs("sens-ext-05")
        self.assertEqual((sensor["quality"], sensor["link"]), ("lost", "offline"))
        self.assertTrue(self.shown(self.node("sens-ext-05") + " .sensor__lost"), "a crossed sensor")
        self.assertFalse(self.shown(self.node("sens-ext-05") + " .sensor__dot"))
        self.assertTrue(self.shown(self.node("sens-ext-01") + " .sensor__dot"))
        self.select("zone-c")
        self.page.wait_for("document.querySelector('[data-testid=\"card\"]').textContent.includes('Участок В')")
        card = self.card()
        self.assertIn("последнее известное: опасно (тик", card)
        self.assertIn("синтетический индекс нестабильности", card)
        self.assertIn("последнее рассчитанное, тик", card)
        self.assertNotIn("вероятност", card.lower())

    def test_unknown_codes_are_shown_as_unknown(self):
        self.open("unknown_enum")
        zone = self.attrs("zone-a")
        self.assertEqual(zone["hazard"], "unknown")
        text = self.text_of(self.node("zone-a"))
        self.assertIn("состояние неизвестно (код elevated)", text)
        self.assertNotIn("норма", text)
        self.assertTrue(self.page.evaluate("document.querySelector('#scheme .halo--unknown') !== null"))
        worker = self.attrs("worker-09")
        self.assertEqual(worker["status"], "resting")
        self.assertIn("is-odd", worker["cls"])
        self.assertIn("неизвестно (resting)", plain(worker["label"]))
        self.select("worker-09")
        self.page.wait_for("document.querySelector('[data-testid=\"card\"]').textContent.includes('Р-09')")
        self.assertIn("неизвестно (resting)", self.card())
        self.select("option-observe")
        self.page.wait_for("document.querySelector('[data-testid=\"card\"]').textContent.includes('shelter')")

    def test_route_segments_draw_the_same_overlay_as_names(self):
        overlays = []
        for scenario in ("paused_heartbeat", "route_segments"):
            self.open(scenario)
            self.select("worker-03")
            self.page.wait_for("document.querySelectorAll('#scheme .route[data-reason=\"selection\"]').length === 1",
                               message="route overlay")
            overlays.append(self.page.evaluate(
                "[document.querySelector('#scheme .route .route__line').getAttribute('d'),"
                " document.querySelector('#scheme .route').dataset.workings]"))
        self.assertEqual(overlays[0], overlays[1])
        self.assertEqual(overlays[0][1], "w-14 w-15 w-18 w-03")

    def test_topology_change_adds_the_working_without_reload(self):
        self.open("topology_change")
        self.page.evaluate("window.__sameDocument = true")
        self.assertIsNone(self.attrs("w-37"))
        before = self.page.evaluate(f"document.querySelector('{self.node('w-19')} .working__line').getAttribute('d')")
        self.page.wait_for(f"document.querySelector('{self.node('w-37')}')", timeout=20.0, message="the added working")
        self.assertTrue(self.page.evaluate("window.__sameDocument === true"), "the page was not reloaded")
        after = self.page.evaluate(f"document.querySelector('{self.node('w-19')} .working__line').getAttribute('d')")
        self.assertNotEqual(before, after, "the moved node moved the working")
        self.assertEqual(self.page.evaluate("document.querySelectorAll('#scheme .working').length"), 37)

    def test_topology_mismatch_draws_no_scheme(self):
        self.open("topology_mismatch", ready=False)
        self.page.wait_for("document.querySelector('[data-testid=\"overlay-banner\"][data-code=\"topology_mismatch\"]')",
                           timeout=15.0, message="mismatch banner")
        self.assertEqual(self.page.evaluate("document.querySelectorAll('#scheme [data-thing-id], #scheme .plane, #scheme .tag').length"), 0)
        self.assertEqual(self.page.evaluate("document.querySelector('[data-testid=\"scheme-svg\"]').dataset.drawn"), "false")
        self.assertIn("Схема не показана", self.text_of("#scheme .scheme__empty"))
        self.assertTrue(self.page.evaluate("document.querySelector('[data-testid=\"legend\"]').textContent.length > 100"),
                        "the legend stays")

    # ---- projections ---------------------------------------------------------

    def test_plan_projection_and_level_select(self):
        self.open("normal")
        svg = "document.querySelector('[data-testid=\"scheme-svg\"]')"
        self.assertEqual(self.page.evaluate(f"{svg}.dataset.projection"), "axo")
        self.assertEqual(self.page.evaluate("document.querySelectorAll('#scheme .plane').length"), 3)
        self.assertEqual(self.page.evaluate("[...document.querySelectorAll('[data-testid=\"level-select\"] option')]"
                                            ".map((option) => option.value)"),
                         ["", "level-260", "level-320", "level-380"])
        self.page.click('[data-testid="projection-plan"]')
        self.page.wait_for(f"{svg}.dataset.projection === 'plan'")
        self.assertEqual(self.page.evaluate(f"{svg}.dataset.level"), "level-260", "the upper level by default")
        self.assertEqual(self.page.evaluate("document.querySelector('[data-testid=\"level-select\"]').value"), "level-260")
        self.assertEqual(self.page.evaluate("document.querySelector('[data-testid=\"projection-plan\"]').getAttribute('aria-pressed')"), "true")
        self.assertIn("view=plan", self.page.evaluate("location.hash"))

        self.page.evaluate("""(() => { const select = document.querySelector('[data-testid="level-select"]');
          select.value = 'level-320'; select.dispatchEvent(new Event('change', {bubbles: true})); })()""")
        self.page.wait_for(f"{svg}.dataset.level === 'level-320'")
        self.assertIn("level=level-320", self.page.evaluate("location.hash"))
        self.assertEqual(self.page.evaluate("document.querySelectorAll('#scheme .plane').length"), 1)
        drawn = self.page.evaluate("[...document.querySelectorAll('#scheme .working')].map((node) => node.dataset.thingId.split(':')[1])")
        # Workings of the level, and stubs of the four that leave it: two shafts and two ramps.
        self.assertEqual(sorted(drawn), sorted([f"w-{n:02d}" for n in range(11, 20)] + ["w-01", "w-02", "w-03", "w-04"]))
        labels = self.scheme_text()
        self.assertIn("ствол В-01 / на Гор. −260 м", labels)
        self.assertIn("съезд В-04 / на Гор. −380 м", labels)
        self.assertIn("В-14", labels, "the plan shows ordinary codes")
        self.assertIn("Э-02", labels)
        self.assertIsNone(self.attrs("zone-a"))
        self.assertIsNotNone(self.attrs("zone-b"))
        self.assertIsNone(self.attrs("exit-shaft"), "exits are on the upper level")
        workers = self.page.evaluate("[...document.querySelectorAll('#scheme .worker')].map((node) => node.dataset.thingId.split(':')[1])")
        self.assertEqual(sorted(workers), ["worker-03", "worker-04", "worker-05", "worker-06"])

        self.page.evaluate("""(() => { const select = document.querySelector('[data-testid="level-select"]');
          select.value = ''; select.dispatchEvent(new Event('change', {bubbles: true})); })()""")
        self.page.wait_for(f"{svg}.dataset.projection === 'axo'")
        self.assertEqual(self.page.evaluate("document.querySelectorAll('#scheme .working').length"), 36)

        self.open("normal", "#/scheme?view=plan&level=level-380&sel=team040.mine:worker-07")
        self.page.wait_for(f"{svg}.dataset.level === 'level-380'")
        self.assertIn("is-selected", self.attrs("worker-07")["cls"])
        self.assertIn("Р-07", self.card())

    def test_refit_on_resize(self):
        self.open("normal")
        box = "document.querySelector('[data-testid=\"scheme-svg\"]').getAttribute('viewBox')"
        before = self.page.evaluate(box)
        place = self.position("worker-01")
        self.page.set_viewport(1920, 1080)
        self.page.wait_for(f"{box} !== {before!r}", message="the picture is fitted again")
        size = self.page.evaluate("(() => { const r = document.getElementById('scheme').getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; })()")
        self.assertEqual(self.page.evaluate(box), f"0 0 {size[0]} {size[1]}")
        self.assertNotEqual(self.position("worker-01"), place)
        inside = self.page.evaluate("""(() => { const frame = document.getElementById('scheme').getBoundingClientRect();
          return [...document.querySelectorAll('#scheme [data-thing-id], #scheme .tag')].every((node) => {
            const box = node.getBoundingClientRect();
            return box.left >= frame.left - 1 && box.right <= frame.right + 1 && box.top >= frame.top - 1 && box.bottom <= frame.bottom + 1;
          }); })()""")
        self.assertTrue(inside, "everything is inside the picture")

    # ---- interaction ---------------------------------------------------------

    # The two marks of an object of the scheme, by what is drawn (colours left out on purpose): the frame of
    # keyboard focus and the mark of selection, each as {element, dash, weight} or null when it is not shown.
    MARKS = """((thingId) => {
      const node = document.querySelector(`#scheme [data-thing-id="${thingId}"]`);
      const describe = (element) => {
        const style = getComputedStyle(element);
        const box = element.getBoundingClientRect();
        return {element: element.getAttribute('class').split(' ')[0], tag: element.tagName,
                dash: style.strokeDasharray === 'none' ? 'solid' : 'dashed', weight: parseFloat(style.strokeWidth),
                box: [box.left, box.top, box.right, box.bottom].map(Math.round)};
      };
      const painted = (element) => {
        const style = getComputedStyle(element);
        return style.display !== 'none' && style.stroke !== 'none' && !/, 0\\)$/.test(style.stroke) && parseFloat(style.strokeOpacity) > 0;
      };
      const frame = node.querySelector(':scope > .obj__focus');
      const carrier = node.querySelector(':scope > .working__hit, :scope > .worker__hit, :scope > .sensor__hit, :scope > .exit__hit, :scope > .tag__box');
      const selected = node.classList.contains('is-selected') || node.classList.contains('tag--selected');
      const body = node.querySelector('.working__band, .working__line, .worker__shape, .sensor__body, .exit__body, .tag__box').getBoundingClientRect();
      return {
        kind: node.dataset.kind, focused: document.activeElement === node, keyboard: node.matches(':focus-visible'), selected,
        focus: painted(frame) ? describe(frame) : null,
        selection: selected && painted(carrier) ? describe(carrier) : null,
        body: [body.left, body.top, body.right, body.bottom].map(Math.round),
      };
    })"""

    def marks(self, thing_id):
        return self.page.evaluate(f"{self.MARKS}({thing_id!r})")

    def clip_around(self, thing_id, name):
        """A screenshot of the object with some of the scheme around it, for the eye (test-output/fix/)."""
        box = self.page.evaluate(f"""(() => {{
          const box = document.querySelector('#scheme [data-thing-id="{thing_id}"]').getBoundingClientRect();
          return [Math.max(0, box.left - 60), Math.max(0, box.top - 60), box.width + 120, box.height + 120];
        }})()""")
        self.page.screenshot(os.path.join(OUTPUT_DIR, "fix", name), clip=box)

    def test_keyboard_reaches_selects_and_keeps_focus(self):
        self.open("normal")
        self.page.evaluate("document.querySelector('[data-testid=\"tab-scheme\"]').focus()")
        reached = None
        for _ in range(12):
            self.page.press("Tab")
            info = self.page.focus_info()
            if info["dataset"].get("thingId"):
                reached = info
                break
        self.assertIsNotNone(reached, "Tab reaches an object of the scheme")
        self.assertEqual(reached["role"], "button")
        self.assertTrue(reached["aria-label"])
        thing_id = reached["dataset"]["thingId"]

        # S10. Focused and not selected: a dashed frame, an element of its own, and no mark of selection.
        focused = self.marks(thing_id)
        self.assertEqual((focused["focused"], focused["keyboard"], focused["selected"]), (True, True, False))
        self.assertEqual((focused["focus"]["element"], focused["focus"]["dash"]), ("obj__focus", "dashed"))
        self.assertGreaterEqual(focused["focus"]["weight"], 3)
        self.assertIsNone(focused["selection"], "a focused object does not look selected")
        frame, body = focused["focus"]["box"], focused["body"]
        self.assertTrue(frame[0] <= body[0] and frame[1] <= body[1] and frame[2] >= body[2] and frame[3] >= body[3],
                        f"the frame goes around the object: {frame} around {body}")
        self.clip_around(thing_id, "scheme-focused-not-selected.png")

        self.page.press("Enter")
        self.page.wait_for(f"document.querySelector('#scheme [data-thing-id=\"{thing_id}\"]').classList.contains('is-selected')")
        self.assertEqual(self.js(APP + "return state.ui.selected;"), thing_id)
        self.assertIn(f"sel={thing_id}", self.page.evaluate("location.hash"))
        # Selected and still focused: both marks at once, on different elements, one solid and one dashed.
        both = self.marks(thing_id)
        self.assertEqual((both["focus"]["element"], both["focus"]["dash"]), ("obj__focus", "dashed"))
        self.assertEqual(both["selection"]["dash"], "solid")
        self.assertNotEqual(both["selection"]["element"], both["focus"]["element"], "focus and selection are different elements")
        self.clip_around(thing_id, "scheme-selected-and-focused.png")
        self.wait_polls(3)
        self.assertEqual(self.page.focus_info()["dataset"].get("thingId"), thing_id, "three polls did not move focus")
        self.assertEqual(self.marks(thing_id)["focus"]["dash"], "dashed", "three polls did not take the frame away")

        # Space selects as well; a click on empty space clears the selection.
        self.page.press("Tab")
        second = self.page.focus_info()["dataset"]["thingId"]
        self.assertNotEqual(second, thing_id)
        # The first object is selected and no longer focused: the solid mark alone. The second one: the frame alone.
        left = self.marks(thing_id)
        self.assertIsNone(left["focus"], "the frame leaves with the focus")
        self.assertEqual(left["selection"]["dash"], "solid")
        moved = self.marks(second)
        self.assertEqual((moved["focus"]["dash"], moved["selection"]), ("dashed", None))
        self.clip_around(thing_id, "scheme-selected-not-focused.png")
        # The same two marks for every kind of object: focused by the keyboard, then selected.
        kinds = {}
        for name in ("zone-b", "sens-ext-01", "exit-shaft", "worker-03"):
            self.page.evaluate(f"document.querySelector('{self.node(name)}').focus()")
            alone = self.marks(thing(name))
            self.clip_around(thing(name), f"scheme-focused-{alone['kind']}.png")
            self.select(name)
            self.page.wait_for(f"location.hash.includes('sel={thing(name)}')")
            kinds[alone["kind"]] = (alone, self.marks(thing(name)))
            self.clip_around(thing(name), f"scheme-selected-{alone['kind']}.png")
        self.assertEqual(sorted(kinds), ["exit", "sensor", "worker", "zone"])
        for kind, (alone, chosen) in kinds.items():
            with self.subTest(kind=kind):
                self.assertTrue(alone["keyboard"], "focus moved after a key press counts as keyboard focus")
                self.assertEqual((alone["focus"]["element"], alone["focus"]["dash"], alone["selection"]), ("obj__focus", "dashed", None))
                self.assertEqual(chosen["selection"]["dash"], "solid")
                self.assertNotEqual(chosen["selection"]["element"], chosen["focus"]["element"])
                frame, body = alone["focus"]["box"], alone["body"]
                self.assertTrue(frame[0] <= body[0] and frame[1] <= body[1] and frame[2] >= body[2] and frame[3] >= body[3],
                                f"{kind}: the frame goes around the object: {frame} around {body}")
        self.page.evaluate(f"document.querySelector('#scheme [data-thing-id=\"{second}\"]').focus()")
        self.page.press("Space")
        self.page.wait_for(f"location.hash.includes('sel={second}')")
        self.page.evaluate("document.querySelector('[data-testid=\"scheme-svg\"]').dispatchEvent(new MouseEvent('click', {bubbles: true}))")
        self.page.wait_for("!location.hash.includes('sel=')", message="selection cleared")
        self.assertIn("Сводка смены", self.card())

    def test_click_selects_and_card_links_select(self):
        self.open("normal")
        self.assertIn("Сводка смены", self.card())
        self.assertIn("всего работников 14", self.card())
        self.assertIn("Ствол: выход доступен (модель); вышло 0", self.card())
        self.page.click(self.node("zone-d"))
        self.page.wait_for("location.hash.includes('sel=team040.mine:zone-d')")
        card = self.card()
        self.assertIn("участок Участок Г", card)
        self.assertIn("внимание", card)
        self.assertIn("причина состояния: скорость изменения выше порога «внимание»: датчик Э-04, значение 1,3 мм/ч, порог 1 мм/ч", card)
        self.assertIn("синтетический индекс нестабильности: 0,46", card)
        self.assertIn("производительность 47,5 т/ч", card)
        self.assertIn("время модели:", card)
        self.assertIn("UTC", card)
        related = self.page.evaluate("[...document.querySelectorAll('[data-testid=\"card\"] [data-select]')].map((node) => node.dataset.select.split(':')[1])")
        for name in ("w-23", "w-24", "w-25", "sens-ext-04", "sens-conv-03", "worker-11", "level-380"):
            self.assertIn(name, related)
        # A related button keeps focus over polls and selects its twin.
        self.page.evaluate("document.querySelector('[data-testid=\"card\"] [data-select=\"team040.mine:sens-ext-04\"]').focus()")
        self.wait_polls(2)
        self.assertEqual(self.page.focus_info()["dataset"].get("select"), thing("sens-ext-04"))
        self.page.press("Enter")
        self.page.wait_for("location.hash.includes('sel=team040.mine:sens-ext-04')")
        card = self.card()
        self.assertIn("датчик Э-04", card)
        self.assertIn("скорость изменения 1,3 мм/ч", card)
        self.assertIn("Измерено 00:", card)
        self.assertIn("is-selected", self.attrs("sens-ext-04")["cls"])
        self.page.click('[data-testid="card-close"]')
        self.page.wait_for("!location.hash.includes('sel=')")

    def test_a_worker_who_is_out_is_not_drawn_under_ground(self):
        """S2: `status = out` with `at_working` and `offset_m` still published: no marker, no place in a working."""
        self.page.add_init_script(REWRITE_SHIFT)
        self.open("normal")
        before = self.attrs("worker-05")
        self.assertEqual(before["status"], "working", "the fixture draws this worker under ground")
        zone_before = int(self.page.evaluate(f"document.querySelectorAll('#scheme [data-kind=\"worker\"]').length"))
        # The model says the worker is out; the working and the offset of the earlier publication stay in the answer.
        self.page.evaluate("window.__patch = " + json.dumps({"worker-05": {"status": "out"}}))
        self.page.wait_for(f"!document.querySelector('{self.node('worker-05')}')", timeout=6.0, message="the marker is gone")
        row = f'[data-testid="list"] tr[data-thing-id="{thing("worker-05")}"]'
        self.page.wait_for(f"document.querySelector({row!r}).dataset.status === 'out'", timeout=3.0)
        state = self.js(APP + """
          const worker = state.model.byName['worker-05'];
          return {working: worker.values.at_working, offset: typeof worker.values.offset_m};
        """)
        self.assertEqual(state["offset"], "number", "the old position is still published: the test is about that")
        self.assertEqual(int(self.page.evaluate("document.querySelectorAll('#scheme [data-kind=\"worker\"]').length")), zone_before - 1)
        place = plain(self.page.evaluate(f"document.querySelector({row!r}).cells[2].textContent"))
        self.assertEqual(place, "—", "no working is named as the place of a worker who is out")
        self.assertNotIn("Р-05", self.text_of("#scheme .scheme__lost"), "nor is the worker listed as lost under ground")
        # Nor among the people of the working and of the zone.
        self.select(state["working"])
        self.page.wait_for(f"location.hash.includes('sel={thing(state['working'])}')")
        related = self.page.evaluate("[...document.querySelectorAll('[data-testid=\"card\"] [data-select]')].map((node) => node.dataset.select.split(':')[1])")
        self.assertNotIn("worker-05", related)
        # Selected, the worker has no route drawn from a place where they are not.
        self.select("worker-05")
        self.page.wait_for("location.hash.includes('sel=team040.mine:worker-05')")
        self.wait_polls(1)
        self.assertEqual(self.page.evaluate("document.querySelectorAll('#scheme .route').length"), 0)
        # With the exit published the place is the exit.
        self.page.evaluate("window.__patch = " + json.dumps({"worker-05": {"status": "out", "at_exit": "exit-shaft"}}))
        self.page.wait_for(f"document.querySelector({row!r}).cells[2].textContent.includes('Ствол')", timeout=6.0)
        self.assertIsNone(self.attrs("worker-05"))

    def test_pending_command_is_marked_and_changes_nothing(self):
        self.open("commands")
        self.send("condition.close_working", "w-12")
        self.page.wait_for(f"document.querySelector('{self.node('w-12')}').hasAttribute('data-pending')", message="pending mark")
        working = self.attrs("w-12")
        self.assertEqual(working["passability"], "open", "no optimistic change")
        self.assertTrue(self.shown(self.node("w-12") + " .working__mark--pending"))
        self.assertFalse(self.shown(self.node("w-12") + " .working__barrier"))
        self.assertIn("В-12 / команда отправлена, не подтверждена", self.scheme_text())
        self.assertIn("команда отправлена, не подтверждена", plain(working["label"]))
        rows = self.page.evaluate(DRAWN)
        self.assertEqual(rows["scheme"][thing("w-12")][0], rows["list"][thing("w-12")])

    # ---- movement ------------------------------------------------------------

    def test_markers_move_between_polls_group_by_data_and_stop_when_the_link_fails(self):
        with MockServer("detour", extra_args=("--publication-ms", "200")) as fast:
            self.open("detour", mock=fast)
            self.send("condition.close_working", "w-12")
            self.page.wait_for("document.body.dataset.runState === 'paused'", message="decision point")
            self.send("action.execute_option", "option-withdraw-all")
            self.wait_attr("worker-03", "status", "moving_to_exit")
            self.assertIn("move-transition", self.attrs("worker-03")["cls"])
            self.assertIn("is-going", self.attrs("worker-03")["cls"], "a walking worker carries a direction arrow")
            seen = [self.position("worker-03")]
            deadline = time.monotonic() + 8.0
            while len(seen) < 3 and time.monotonic() < deadline:
                now = self.position("worker-03")
                if now != seen[-1]:
                    seen.append(now)
                time.sleep(0.1)
            self.assertEqual(len(seen), 3, f"the marker moved with the publications: {seen}")
            self.assertEqual(self.page.evaluate(
                f"getComputedStyle(document.querySelector('{self.node('worker-03')}')).transitionDuration"), "0.6s")

            # Р-12 and Р-13 walk the same stretch of one working: one marker with a count.
            self.page.wait_for(f"document.querySelector('{self.node('worker-12')}').dataset.group === '2'"
                               f" && document.querySelector('{self.node('worker-13')}').dataset.group === '2'",
                               timeout=10.0, message="a group of two")
            group = self.page.evaluate(f"""(() => {{
              const a = document.querySelector('{self.node('worker-12')}');
              const b = document.querySelector('{self.node('worker-13')}');
              return {{same: a.style.transform === b.style.transform,
                merged: [a, b].filter((node) => node.classList.contains('is-merged')).length,
                working: [a.dataset.thingId, b.dataset.thingId]}};
            }})()""")
            self.assertTrue(group["same"], "members of a group share one position")
            self.assertEqual(group["merged"], 1, "the marker of the group is drawn once")
            self.assertIn("×2", self.scheme_text())

            fast.fault("http_502")
            self.allow_console_errors = True  # the browser reports the failed reads
            self.page.wait_for("document.body.dataset.link !== 'ok'", message="link degraded")
            self.assertEqual(self.page.evaluate(
                f"getComputedStyle(document.querySelector('{self.node('worker-03')}')).transitionDuration"), "0s",
                "no glide while the link is not ok")
            # The banners of a failing link change the height of the picture; the comparison starts when they are all up.
            self.page.wait_for("document.body.dataset.link === 'unavailable'", message="platform unavailable")
            time.sleep(0.5)
            frozen = self.position("worker-03")
            tick = self.page.evaluate("document.body.dataset.tick")
            time.sleep(2.5)
            self.assertEqual(self.position("worker-03"), frozen, "nothing moves without new snapshots")
            self.assertEqual(self.page.evaluate("document.body.dataset.tick"), tick)
            self.assertIsNotNone(self.attrs("worker-03"), "the last full snapshot stays on the screen")

    def test_no_canvas_and_no_animation_frames(self):
        self.page.add_init_script(PROBE)
        self.open("paused_heartbeat")
        self.select("worker-03")
        self.page.wait_for("document.querySelector('#scheme .route[data-reason=\"selection\"]')")
        self.page.evaluate("window.__probe.raf = 0")
        seq = int(self.page.evaluate("document.body.dataset.seq"))
        tick = self.page.evaluate("document.body.dataset.tick")
        time.sleep(5.0)
        probe = self.page.evaluate("window.__probe")
        self.assertGreaterEqual(int(self.page.evaluate("document.body.dataset.seq")), seq + 3, "polls went on")
        self.assertEqual(self.page.evaluate("document.body.dataset.tick"), tick, "the data did not change")
        self.assertEqual(probe["raf"], 0, "no animation frame is requested while the data do not change")
        self.assertEqual(probe["canvas"], 0, "no canvas context is ever created")
        self.assertEqual(self.page.evaluate("document.querySelectorAll('canvas').length"), 0)
        self.assertEqual(self.page.evaluate(
            "[...document.querySelectorAll('#scheme *, #legend *')].filter((node) => getComputedStyle(node).filter !== 'none'"
            " || getComputedStyle(node).animationName !== 'none').length"), 0, "no filters and no animation")

    # ---- legend --------------------------------------------------------------

    def test_legend_chip_unfolds_into_the_full_legend(self):
        """The legend is a one-row chip at the bottom left of the stage; Enter unfolds the full legend, Esc folds it."""
        self.open("normal")
        chip = self.page.evaluate("""(() => {
          const chip = document.querySelector('[data-testid="legend-toggle"]');
          const box = chip.getBoundingClientRect();
          const stage = document.getElementById('stage').getBoundingClientRect();
          const shown = [...chip.querySelectorAll('.legend__item, .legend__title')].filter((node) => node.getClientRects().length > 0);
          return {
            expanded: chip.getAttribute('aria-expanded'), tag: chip.tagName, panelHidden: document.getElementById('legend-panel').hidden,
            titles: [...chip.querySelectorAll('.legend__title')].map((node) => node.textContent),
            hints: [...chip.querySelectorAll('.legend__item')].map((node) => node.title),
            height: Math.round(box.height), oneRow: shown.every((node) => {
              const item = node.getBoundingClientRect(); return item.top >= box.top - 1 && item.bottom <= box.bottom + 1; }),
            clipped: chip.scrollWidth > chip.clientWidth + 1,
            corner: [Math.round(box.left - stage.left), Math.round(stage.bottom - box.bottom)],
            symbols: chip.querySelectorAll('.legend__item svg').length,
          };
        })()""")
        self.assertEqual((chip["tag"], chip["expanded"], chip["panelHidden"]), ("BUTTON", "false", True), "folded at first")
        # Folded: the three axes and the exit by name, each with its key symbols, the closed passage and the route.
        self.assertEqual(chip["titles"], ["Опасность:", "Знание:", "Достижимость:", "Выход:"])
        for words in ("норма", "внимание", "опасно", "состояние неизвестно", "данные актуальны", "данные устарели",
                      "данные потеряны", "без датчиков, состояние не оценивается", "расчётный маршрут (модель)",
                      "нет расчётного маршрута", "маршрут не рассчитан", "доступен (модель)", "проход закрыт"):
            self.assertIn(words, chip["hints"], "every key symbol of the chip names its state")
        self.assertEqual(chip["symbols"], 14, "4 hazard, 4 knowledge, 3 reachability, the exit, the closed passage, the route")
        self.assertTrue(chip["oneRow"], "the chip is one row")
        self.assertLessEqual(chip["height"], 44)
        self.assertFalse(chip["clipped"], "nothing of the chip is cut off at 1280x720")
        self.assertTrue(0 <= chip["corner"][0] <= 24 and 0 <= chip["corner"][1] <= 24, f"bottom left corner of the stage: {chip['corner']}")

        # Enter unfolds the full legend above the chip: every state of the three axes, with its sample and its words.
        self.page.evaluate("document.querySelector('[data-testid=\"legend-toggle\"]').focus()")
        self.page.press("Enter")
        self.page.wait_for("!document.getElementById('legend-panel').hidden", timeout=3.0, message="the legend unfolds")
        self.assertEqual(self.page.evaluate("document.querySelector('[data-testid=\"legend-toggle\"]').getAttribute('aria-expanded')"), "true")
        legend = self.text_of("#legend-panel")
        for axis in ("Опасность:", "Знание:", "Достижимость:", "Выход:", "Команды:"):
            self.assertIn(axis, legend)
        for words in ("норма", "внимание", "опасно", "состояние неизвестно", "последнее известное: опасно",
                      "данные актуальны", "данные устарели", "данные потеряны", "без датчиков, состояние не оценивается",
                      "расчётный маршрут (модель)", "нет расчётного маршрута", "маршрут не рассчитан", "работник в опасной зоне",
                      "идёт к выходу", "проход закрыт", "новый вход запрещён моделью", "команда отправлена, не подтверждена",
                      "доступен (модель)", "недоступен"):
            self.assertIn(words, legend)
        self.assertNotIn("Пороги", legend, "the thresholds are in the summary of the shift, not in the legend")
        self.assertEqual(self.page.evaluate("document.querySelectorAll('#legend-panel [data-legend-group]').length"), 5)
        self.assertGreaterEqual(self.page.evaluate("document.querySelectorAll('#legend-panel .legend__item svg').length"), 20)
        # The samples are the symbols of the scheme: same parts, same classes, and on the screen.
        self.assertTrue(self.shown('#legend-panel .worker[data-egress="none"] .worker__none'))
        self.assertTrue(self.shown('#legend-panel .sensor[data-quality="lost"] .sensor__lost'))
        self.assertTrue(self.shown('#legend-panel .working .working__barrier'))
        self.assertIn("url(", self.page.evaluate(
            "document.querySelector('#legend-panel .working[data-hazard=\"danger\"] .working__band').style.fill"))
        self.assertTrue(self.page.evaluate("""(() => { const box = document.getElementById('legend-panel').getBoundingClientRect();
          return box.height > 100 && box.top >= 0 && box.bottom <= window.innerHeight; })()"""), "the unfolded legend is on the screen")
        summary = self.card()
        self.assertIn("Пороги — настройка демонстрации", summary)
        self.assertIn("синтетический индекс нестабильности внимание 0,4, опасно 0,7", summary)
        # Esc folds it and gives the focus back to the chip.
        self.page.press("Escape")
        self.page.wait_for("document.getElementById('legend-panel').hidden", timeout=3.0, message="the legend folds")
        self.assertEqual(self.page.focus_info()["testid"], "legend-toggle")

    def test_symbols_for_the_stage_are_the_symbols_of_the_scheme(self):
        """icons.js symbol(): standalone SVG of every state, built by the scheme's own functions, also as self-contained text."""
        self.open("normal")
        got = self.js("""
          const icons = await import('/js/icons.js');
          const out = {};
          for (const [kind, states] of Object.entries(icons.SYMBOLS)) {
            for (const state of states) {
              const svg = icons.symbol(kind, state, {size: 24});
              out[kind + ':' + state] = {tag: svg.tagName, height: svg.getAttribute('height'),
                                          parts: svg.querySelectorAll('path, circle, rect').length, data: svg.dataset.symbol};
            }
          }
          const markup = icons.symbolMarkup('hazard', 'danger');
          const sample = document.querySelector('#legend-panel .working[data-hazard="danger"]');
          const symbol = icons.symbol('hazard', 'danger').querySelector('.working');
          const parts = (node) => [...node.children].map((child) => child.getAttribute('class')).join(' ');
          return {out, markup, sameParts: parts(sample) === parts(symbol)};""")
        for name, item in got["out"].items():
            self.assertEqual((item["tag"], item["height"], item["data"]), ("svg", "24", name))
            self.assertGreater(item["parts"], 0, name)
        self.assertTrue(got["sameParts"], "the symbol of a hazard state has the parts of the working on the scheme")
        markup = got["markup"]
        self.assertTrue(markup.startswith("<svg") and 'xmlns="http://www.w3.org/2000/svg"' in markup)
        self.assertIn("<pattern", markup, "the hatch travels with the symbol")
        self.assertRegex(markup, r'fill="url\((&quot;)?#sym\d+-danger(&quot;)?\)"', "the computed hatch is written into the shape")

    # ---- measurements (reported, loosely bounded) -------------------------------

    def test_measure_dom_size_and_update_time(self):
        self.open("normal")
        counts = self.page.evaluate("({total: document.querySelectorAll('*').length,"
                                    " svg: document.querySelectorAll('[data-testid=\"scheme-svg\"] *').length})")
        update = self.js(APP + """
          const id = 'team040.mine:worker-03';
          const times = [];
          for (let i = 0; i < 40; i += 1) {
            const start = performance.now();
            app.ctx.select(i % 2 === 0 ? id : null);
            times.push(performance.now() - start);
          }
          times.sort((a, b) => a - b);
          return {median: times[20], max: times[39]};""")
        print(f"\n[measure] normal, 1280x720: DOM nodes total {counts['total']}, inside the scheme SVG {counts['svg']};"
              f" one update of all views (selection change): median {update['median']:.1f} ms, max {update['max']:.1f} ms")
        self.assertLess(counts["svg"], 2500)
        self.assertLess(update["median"], 100)
