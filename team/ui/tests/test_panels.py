"""The interactive panels against the mock server: scenario conditions, dispatcher
actions, pending commands, the decision panel, the journal, the archive of runs
and the confirmation dialog.

The page is the production static; commands are sent by pressing its real
controls. Where a scenario is a long story, the mock publishes ten times
faster (`--publication-ms 100`); the wall-clock thresholds of the interface do
not scale, so tests of a threshold run against the contract's 1000 ms.

    python -m unittest discover -s team/ui/tests -t team/ui -p "test_panels.py" -v
"""

from __future__ import annotations

import json
import re
import time

from screenshots import settle
from browser_support import BrowserTestCase, MockServer, wait_until

NS = "team040.mine"
NBSP = " "
COMMAND_PATH = f"/ditto/api/2/things/{NS}:shift/inbox/messages/command?timeout=0"

APP = "const {app} = await import('/js/main.js'); const state = app.store.getState();"

CONDITIONS = '[data-testid="conditions-panel"]'
ACTIONS = '[data-testid="actions-panel"]'
DECISION = '[data-testid="decision-panel"]'
CLOSE = f'{CONDITIONS} button[data-command-type="condition.close_working"]'
SENSOR = f'{CONDITIONS} button[data-command-type="condition.sensor_lost"]'
STOP = f'{ACTIONS} button[data-command-type="action.stop_zone"]'
WITHDRAW = f'{ACTIONS} button[data-command-type="action.withdraw_zone"]'
RESUME = f'{ACTIONS} button[data-command-type="action.resume_zone"]'
RESET = '[data-testid="btn-reset"]'
EXECUTE = '[data-testid="btn-execute"]'
WORKING_SELECT = "#condition-working_closed"
SENSOR_SELECT = "#condition-sensor_lost"
ZONE_SELECT = "#action-zone"

NO_DIGIT = re.compile(r"^\D*$")
# The age of a journal line by the model clock (clarity pass, A8), for lines of a model that goes on.
AGE = re.compile(r" · (?:сейчас|\d+ с назад|\d+ мин назад|\d+ ч(?: \d+ мин)? назад) ")

# Test-side rewrite of the answers of `shift`, in the browser, before any script of the page: the function
# a test puts into `window.__rewrite` gets the parsed body and changes it. The page code does not know.
# For forms of the data that no fixture publishes (a forecast without its quality, options without one key).
REWRITE = """
(() => {
  window.__rewrite = null;
  const realFetch = window.fetch;
  window.fetch = async function (input, init) {
    const response = await realFetch.call(this, input, init);
    const url = typeof input === 'string' ? input : input.url;
    if (!window.__rewrite || !url.includes(':shift?') || !response.ok) return response;
    const body = await response.json();
    const scene = {};
    for (const item of body.features.scene.properties.value) scene[item.thingId.split(':')[1]] = item.features;
    window.__rewrite(body.features, scene);
    return new Response(JSON.stringify(body), {status: response.status, statusText: response.statusText, headers: response.headers});
  };
})();
"""


def plain(text):
    return re.sub(r"\s+", " ", text.replace(NBSP, " ")).strip() if isinstance(text, str) else text


class PanelsTestCase(BrowserTestCase):
    mock_args = ()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock = MockServer("normal", extra_args=cls.mock_args).start()
        cls.addClassCleanup(cls.mock.stop)

    # ---- helpers ---------------------------------------------------------

    def open(self, scenario, route=""):
        """Restart the scenario from its first frame and load the page as a new document."""
        self.mock.scenario(scenario)
        self.page.goto("about:blank")
        self.page.goto(self.mock.url + "/" + route)
        self.wait_body(boot="ready", snapshot="ok", link="ok")

    def js(self, body, timeout=20.0):
        return self.page.evaluate("(async () => {" + body + "})()", timeout=timeout)

    def body(self):
        return self.page.evaluate("Object.assign({}, document.body.dataset)")

    def wait_body(self, timeout=10.0, **expected):
        condition = " && ".join(f"document.body.dataset.{name} === {value!r}" for name, value in expected.items())
        try:
            self.page.wait_for(condition, timeout=timeout)
        except AssertionError as error:
            raise AssertionError(f"{error}\nbody: {self.body()}") from None
        return self.body()

    def wait_polls(self, count):
        """Wait until the page has rendered `count` further publications read by its own polling."""
        seq = int(self.body()["seq"])
        step = 10 if "100" in self.mock_args else 1
        self.page.wait_for(f"Number(document.body.dataset.seq) >= {seq + count * step}", timeout=4.0 + 1.5 * count)

    def text(self, selector):
        """Text of the first match, whitespace collapsed; None when nothing matches or the element is hidden."""
        return plain(self.page.evaluate(f"""(() => {{
          const node = document.querySelector({json.dumps(selector)});
          return node && !node.closest('[hidden]') ? node.textContent : null;
        }})()"""))

    def texts(self, selector):
        return [plain(item) for item in self.page.evaluate(
            f"[...document.querySelectorAll({json.dumps(selector)})].filter((node) => !node.closest('[hidden]'))"
            ".map((node) => node.textContent)")]

    def wait_text(self, selector, part, timeout=6.0):
        try:
            self.page.wait_for(f"""(() => {{
              const node = document.querySelector({json.dumps(selector)});
              return !!node && !node.closest('[hidden]') && node.textContent.replace(/\\u00a0/g, ' ').includes({json.dumps(part)});
            }})()""", timeout=timeout)
        except AssertionError as error:
            raise AssertionError(f"{error}\ntext of {selector}: {self.text(selector)!r}") from None
        return self.text(selector)

    def exists(self, selector):
        return self.page.evaluate(f"!!document.querySelector({json.dumps(selector)})")

    def attribute(self, selector, name):
        return self.page.evaluate(f"document.querySelector({json.dumps(selector)}).getAttribute({json.dumps(name)})")

    def is_off(self, selector):
        return self.attribute(selector, "aria-disabled") == "true"

    def choose(self, selector, value):
        """Change a <select> the way a keyboard user does: focus it and move with the arrow keys.
        A select of the stand drawer is reached by opening the drawer first."""
        if self.page.evaluate(f"!!document.querySelector({json.dumps(selector)}).closest('#stand-drawer')"):
            self.open_stand()
        move = self.page.evaluate(f"""(() => {{
          const select = document.querySelector({json.dumps(selector)});
          select.focus();
          return {{from: select.selectedIndex, to: [...select.options].findIndex((option) => option.value === {json.dumps(value)})}};
        }})()""")
        self.assertGreaterEqual(move["to"], 0, f"{selector} has no option {value}")
        for _ in range(abs(move["to"] - move["from"])):
            self.page.press("ArrowDown" if move["to"] > move["from"] else "ArrowUp")
        self.assertEqual(self.page.evaluate(f"document.querySelector({json.dumps(selector)}).value"), value)

    def pending(self):
        """The pending commands as the user sees them."""
        entries = self.page.evaluate("""[...document.querySelectorAll('[data-testid="pending"]')].map((node) => ({
          id: node.dataset.commandId, type: node.dataset.commandType, target: node.dataset.commandTarget,
          phase: node.dataset.phase, what: node.querySelector('.pending__what').textContent,
          shortId: node.querySelector('.pending__id').textContent, text: node.querySelector('.pending__text').textContent,
          buttons: Object.fromEntries([...node.querySelectorAll('button')].filter((button) => !button.hidden)
            .map((button) => [button.dataset.testid, button.textContent])),
        }))""")
        for entry in entries:
            entry["text"] = plain(entry["text"])
        return entries

    def pending_for(self, target, command_type=None):
        return next((entry for entry in self.pending()
                     if entry["target"] == target and command_type in (None, entry["type"])), None)

    def wait_pending(self, target, phase, timeout=8.0, command_type=None):
        selector = f'[data-testid="pending"][data-command-target="{target}"][data-phase="{phase}"]'
        if command_type:
            selector += f'[data-command-type="{command_type}"]'
        try:
            self.page.wait_for(f"!!document.querySelector({json.dumps(selector)})", timeout=timeout)
        except AssertionError as error:
            raise AssertionError(f"{error}\npending: {self.pending()}") from None
        return self.pending_for(target, command_type)

    def press_in_pending(self, target, test_id):
        self.page.click(f'[data-testid="pending"][data-command-target="{target}"] [data-testid="{test_id}"]')

    def commands_logged(self, command_id=None, command_type=None):
        return [entry for entry in self.mock.log()["entries"] if entry["kind"] == "command"
                and (command_id is None or (entry.get("body") or {}).get("command_id") == command_id)
                and (command_type is None or (entry.get("body") or {}).get("type") == command_type)]

    def wait_commands(self, count, **filters):
        return wait_until(lambda: len(self.commands_logged(**filters)) >= count and self.commands_logged(**filters),
                          timeout=4.0, message=f"{count} command(s) in the log of the mock")

    def cell(self, option, metric, scope=DECISION):
        return self.text(f'{scope} td[data-option="{option}"][data-metric="{metric}"]')

    def open_stand(self, open_=True):
        """Open (or close) the stand drawer by its button in the top bar; its controls are out of reach while it is closed."""
        if (self.body().get("stand") == "open") != open_:
            self.page.click('[data-testid="stand-toggle"]')
        self.page.wait_for(f"document.body.dataset.stand === {'open' if open_ else 'closed'!r}"
                           " && getComputedStyle(document.getElementById('stand-drawer')).visibility === "
                           f"{'visible' if open_ else 'hidden'!r}", timeout=3.0, message="the stand drawer")

    def unfold_dock(self):
        """Unfold the decision dock under the stage when it is folded to its bar (its toggle is view/dock.js's)."""
        self.page.evaluate("""(() => {
          const toggle = document.querySelector('[data-testid="dock-toggle"], [data-testid="decision-dock-toggle"]');
          if (toggle && toggle.getAttribute('aria-expanded') === 'false') toggle.click();
        })()""")
        self.page.wait_for("document.getElementById('decision').getClientRects().length > 0", timeout=3.0,
                           message="the decision dock is unfolded")
        settle(self.page)

    def bar(self, option, series="forecast", scope=DECISION):
        """The people bar of an option as drawn: its data-* counts, its cells by kind and how they are filled."""
        return self.page.evaluate(f"""(() => {{
          const bars = [...document.querySelectorAll({json.dumps(scope)} + ' [data-testid="people-bar"]')]
            .filter((bar) => bar.closest('[data-option="{option}"], [data-run="{option}"]') && bar.dataset.series === '{series}');
          if (bars.length !== 1) return {{count: bars.length}};
          const bar = bars[0];
          const cells = {{}};
          for (const cell of bar.querySelectorAll('.pb__cell')) {{
            const kind = [...cell.classList].find((name) => name !== 'pb__cell').slice(4);
            cells[kind] = (cells[kind] || 0) + 1;
          }}
          const filled = [...bar.querySelectorAll('rect.pb__out, rect.pb__in_danger')].map((rect) => rect.style.fill.startsWith('url(') ? 'hatched' : 'solid');
          return {{count: 1, out: bar.dataset.out, inDanger: bar.dataset.inDanger, noRoute: bar.dataset.noRoute,
                  total: bar.dataset.total === undefined ? null : bar.dataset.total, cells, filled: [...new Set(filled)],
                  label: bar.getAttribute('aria-label'),
                  words: bar.parentNode.querySelector('.pb-words') ? bar.parentNode.querySelector('.pb-words').textContent : null}};
        }})()""")

    def confirm_dialog(self, expect_in_message=()):
        self.page.wait_for("!!document.querySelector('[data-testid=\"dialog\"]')", timeout=3.0)
        message = self.text('[data-testid="dialog"]')
        for part in expect_in_message:
            self.assertIn(part, message)
        self.page.click('[data-testid="dialog-confirm"]')
        self.page.wait_for("!document.querySelector('[data-testid=\"dialog\"]')", timeout=3.0)
        return message

    def assert_no_page_overflow(self):
        size = self.page.evaluate("""(() => {
          const wide = (id) => { const node = document.getElementById(id); return node ? node.scrollWidth - node.clientWidth : 0; };
          const root = document.documentElement;
          return {page: [root.scrollWidth - innerWidth, root.scrollHeight - innerHeight],
                  left: wide('stand-drawer'), right: wide('right'), decision: wide('decision'), runs: wide('view-runs')};
        })()""")
        self.assertEqual(size["page"], [0, 0], "the page itself does not scroll")
        self.assertLessEqual(size["left"], 0, "the stand drawer has no horizontal overflow")
        self.assertLessEqual(size["right"], 0, "the right column has no horizontal overflow")
        self.assertLessEqual(size["decision"], 0, "the decision panel has no horizontal overflow")
        self.assertLessEqual(size["runs"], 0, "the runs view has no horizontal overflow")


class CommandOutcomesTest(PanelsTestCase):
    """Scenario `commands` at the contract's publication interval: every outcome of a command, by the real buttons."""

    def test_condition_without_acknowledgement_and_a_rejected_one(self):
        self.open("commands", "#/list?type=working")
        self.assertTrue(self.is_off(CLOSE), "no target chosen yet")
        self.assertEqual(self.text(f"{WORKING_SELECT} option:checked"), "выберите…")
        self.choose(WORKING_SELECT, "w-12")
        self.assertEqual(self.attribute(CLOSE, "data-command-target"), "w-12")
        self.assertFalse(self.is_off(CLOSE))

        self.page.click(CLOSE)
        entry = self.wait_pending("w-12", "sent", 3.0)
        sent_at = time.monotonic()
        # A condition of the stand is said as the condition (clarity pass, A6), with the chalk «стенд» tag.
        self.assertEqual(entry["what"], "Условие стенда: В-12 закрыта")
        self.assertRegex(entry["text"], r"^Команда отправлена, не подтверждена \(\d с\)$")
        self.assertRegex(entry["id"], r"^c-[0-9a-f]{32}$")
        self.assertEqual(entry["shortId"], entry["id"][:10] + "…")
        self.assertEqual(entry["buttons"], {"btn-dismiss": "Снять ожидание"})
        # The object did not change, and the same command cannot be sent twice while it waits.
        row = f'[data-testid="list"] tr[data-thing-id="{NS}:w-12"]'
        self.assertEqual(self.attribute(row, "data-passability"), "open")
        self.assertTrue(self.is_off(CLOSE))
        self.assertEqual(self.text(f"{CONDITIONS} .pick:has({WORKING_SELECT}) + .note--why"), "Команда отправлена, не подтверждена")
        self.page.click(CLOSE)
        self.page.click(CLOSE)
        self.assertEqual(self.texts(f'{CONDITIONS} [data-testid="conditions-active"] li'), [])

        # Another target is another command; the model rejects it and the reason is written out.
        self.choose(WORKING_SELECT, "w-07")
        self.assertFalse(self.is_off(CLOSE))
        self.page.click(CLOSE)
        rejected = self.wait_pending("w-07", "rejected", 4.0)
        self.assertEqual(rejected["text"], "Команда отклонена: недопустимо в текущем состоянии (not_allowed_in_state)")
        self.assertEqual(rejected["buttons"], {"btn-dismiss": "Закрыть сообщение"})
        self.assertEqual(self.text(f"{CONDITIONS} .pick:has({WORKING_SELECT}) + .note--why"), rejected["text"],
                         "the refusal is also written next to the button")
        self.assertFalse(self.is_off(CLOSE), "a rejected command does not bar a new one")
        self.assertEqual(self.attribute(f'[data-testid="list"] tr[data-thing-id="{NS}:w-07"]', "data-passability"), "open")

        # Five seconds without a record: no acknowledgement, with a retry and a dismissal on offer.
        self.page.wait_for("/\\([1-4]\\u00a0с\\)$/.test(document.querySelector('[data-testid=\"pending\"]"
                           "[data-command-target=\"w-12\"] .pending__text').textContent)", timeout=4.0,
                           message="the seconds of waiting are counted")
        silent = self.wait_pending("w-12", "no_ack", 8.0)
        waited = time.monotonic() - sent_at
        self.assertTrue(4.3 <= waited <= 7.0, f"the threshold is 5 s of wall time, measured {waited:.1f} s")
        self.assertEqual(silent["text"], "Нет подтверждения 5 с. Команда могла не дойти")
        self.assertEqual(silent["buttons"], {"btn-retry": "Повторить с тем же идентификатором", "btn-dismiss": "Снять ожидание"})
        self.assertEqual(len(self.commands_logged(silent["id"])), 1, "the presses on the switched-off button sent nothing")

        self.press_in_pending("w-12", "btn-retry")
        again = self.wait_pending("w-12", "sent", 3.0)
        self.assertEqual(again["id"], silent["id"], "a retry is visibly the same command")
        self.assertIn("попыток: 2", again["text"])
        posts = self.wait_commands(2, command_id=silent["id"])
        self.assertEqual(posts[0]["body"], posts[1]["body"])
        self.assertEqual(posts[0]["body"], {"command_id": silent["id"], "type": "condition.close_working",
                                            "target": "w-12", "run": "run-0005"})
        self.assertEqual([(post["duplicate"], post["effect_applied"]) for post in posts], [(False, False), (True, False)])

        self.press_in_pending("w-12", "btn-dismiss")
        self.press_in_pending("w-07", "btn-dismiss")
        self.page.wait_for("document.querySelectorAll('[data-testid=\"pending\"]').length === 0", timeout=2.0)
        self.assertEqual(self.page.evaluate("document.getElementById('pending').childNodes.length"), 0,
                         "the empty group has no child nodes")
        self.assertEqual(len(self.commands_logged()), 3)
        for post in self.commands_logged():
            self.assertEqual((post["method"], post["path"]), ("POST", COMMAND_PATH))

    def test_stop_with_unknown_delivery_is_retried_once_and_applied_once(self):
        self.open("commands", "#/list?type=zone")
        self.choose(ZONE_SELECT, "zone-b")
        state = '[data-testid="actions-zone-state"]'
        self.assertEqual(self.attribute(state, "data-work-state"), "working")
        self.assertIn("работа участка работает", self.text(state))
        self.assertTrue(self.is_off(RESUME))
        self.assertEqual(self.text(f"{RESUME} + .note--why"), "Недоступно: участок работает")
        # Every sample: [phase of the command in the pending list, work state of the zone in the panel].
        self.page.evaluate("""(() => {
          window.__samples = [];
          window.__sampler = setInterval(() => {
            const entry = document.querySelector('[data-testid="pending"][data-command-type="action.stop_zone"]');
            const pair = [entry ? entry.dataset.phase : null,
                          document.querySelector('[data-testid="actions-zone-state"]').dataset.workState];
            const last = window.__samples[window.__samples.length - 1];
            if (!last || last[0] !== pair[0] || last[1] !== pair[1]) window.__samples.push(pair);
          }, 20);
        })()""")

        self.page.click(STOP)
        unknown = self.wait_pending("zone-b", "delivery_unknown", 4.0)
        self.assertEqual(unknown["what"], "Остановить участок: Участок Б")
        self.assertTrue(unknown["text"].startswith("Результат доставки неизвестен (HTTP 503)"), unknown["text"])
        self.assertEqual(unknown["buttons"], {"btn-retry": "Повторить с тем же идентификатором", "btn-dismiss": "Снять ожидание"})
        self.assertEqual(self.attribute(state, "data-work-state"), "working", "nothing changes on an unknown delivery")
        self.assertTrue(self.is_off(STOP), "the unresolved command bars a second one for the same zone")
        self.page.click(STOP)
        self.assertFalse(self.is_off(WITHDRAW), "another command for the zone is not barred")

        self.press_in_pending("zone-b", "btn-retry")
        applied = self.wait_pending("zone-b", "applied", 6.0)
        self.assertEqual(applied["id"], unknown["id"])
        self.assertEqual(applied["text"], "Команда применена · попыток: 2")
        self.page.wait_for(f"document.querySelector('{state}').dataset.workState === 'stopped'", timeout=2.0)
        self.assertIn("работа участка остановлен", self.text(state))
        self.page.evaluate("clearInterval(window.__sampler)")
        samples = self.page.evaluate("window.__samples")
        self.assertEqual([phase for phase, _ in samples if phase][-1], "applied")
        for phase, work_state in samples:
            if work_state != "working":
                self.assertEqual((phase, work_state), ("applied", "stopped"),
                                 f"the zone changed before the acknowledgement: {samples}")

        posts = self.wait_commands(2, command_id=unknown["id"])
        self.assertEqual(len(self.commands_logged(command_type="action.stop_zone")), 2, "the press on the barred button sent nothing")
        self.assertEqual(posts[0]["body"], posts[1]["body"])
        self.assertEqual(posts[0]["body"], {"command_id": unknown["id"], "type": "action.stop_zone", "target": "zone-b",
                                            "run": "run-0005"})
        self.assertEqual([(post["status"], post["delivered"], post["effect_applied"]) for post in posts],
                         [(503, False, False), (202, True, True)], "exactly one effect")
        # Now the published state of the zone switches the buttons.
        self.assertTrue(self.is_off(STOP))
        self.assertEqual(self.text(f"{STOP} + .note--why"), "Недоступно: участок остановлен")
        self.assertFalse(self.is_off(RESUME))

    def test_applied_without_change_and_a_rejection_with_its_reason(self):
        self.open("commands", "#/list?type=zone")
        # No incident: no zone until the user chooses one (clarity pass, A1).
        self.assertEqual(self.page.evaluate(f"document.querySelector('{ZONE_SELECT}').value"), "")
        self.choose(ZONE_SELECT, "zone-a")
        state = '[data-testid="actions-zone-state"]'
        self.assertEqual((self.attribute(state, "data-work-state"), self.attribute(state, "data-withdrawal")), ("stopped", "done"))

        # Resuming a zone whose people are out: the model refuses, the reason is a sentence.
        self.assertFalse(self.is_off(RESUME))
        self.page.click(RESUME)
        rejected = self.wait_pending("zone-a", "rejected", 4.0, "action.resume_zone")
        self.assertEqual(rejected["what"], "Возобновить работу: Участок А")
        self.assertEqual(rejected["text"], "Команда отклонена: на участке недостаточно персонала (insufficient_workers)")
        self.assertEqual(self.text(f"{RESUME} + .note--why"), rejected["text"])
        self.assertEqual(self.attribute(state, "data-work-state"), "stopped")

        # A stopped zone cannot be stopped from the panel: one published field says so, in words.
        self.assertTrue(self.is_off(STOP))
        self.assertEqual(self.text(f"{STOP} + .note--why"), "Недоступно: участок остановлен")
        self.page.click(STOP)
        time.sleep(0.3)
        self.assertFalse(self.commands_logged(command_type="action.stop_zone"))
        # The same command from another client would be "applied without change"; the panel has no button for it,
        # so this one command is sent through the function the buttons call.
        sent = self.js(APP + "return app.ctx.sendCommand('action.stop_zone', 'zone-a');")
        self.assertTrue(sent["ok"], sent)
        unchanged = self.wait_pending("zone-a", "applied", 4.0, "action.stop_zone")
        self.assertEqual(unchanged["text"], "Команда применена без изменения: состояние уже такое")
        self.assertEqual(self.attribute(state, "data-work-state"), "stopped")

        # The same outcome by the real controls: a condition that is already set.
        self.choose(SENSOR_SELECT, "sens-ext-05")
        self.page.click(SENSOR)
        first = self.wait_pending("sens-ext-05", "applied", 6.0)
        self.assertEqual(first["text"], "Команда применена")
        active = f'{CONDITIONS} [data-testid="conditions-active"] li[data-condition="sensor_lost:sens-ext-05"]'
        self.page.wait_for(f"!!document.querySelector({json.dumps(active)})", timeout=3.0)
        self.assertEqual(self.text(active + " .chip"), "Э-05 без связи")
        self.assertEqual(self.text(active + " button"), "Вернуть")
        self.assertEqual(self.attribute(active + " button", "data-command-type"), "condition.sensor_restored")
        self.assertFalse(self.is_off(SENSOR), "the condition buttons are not switched by a rule of the browser")
        self.page.click(SENSOR)
        second = self.wait_pending("sens-ext-05", "applied", 6.0)
        self.page.wait_for("document.querySelector('[data-testid=\"pending\"][data-command-target=\"sens-ext-05\"] .pending__text')"
                           ".textContent.includes('без изменения')", timeout=6.0)
        second = self.pending_for("sens-ext-05")
        self.assertNotEqual(second["id"], first["id"])
        self.assertEqual(second["text"], "Команда применена без изменения: состояние уже такое")
        effects = [post["effect_applied"] for post in self.commands_logged(command_type="condition.sensor_lost")]
        self.assertEqual(effects, [True, False], "one effect of the condition")

    def test_commands_are_blocked_with_a_visible_reason_and_come_back(self):
        self.open("paused_heartbeat", "#/list?type=zone")
        self.unfold_dock()
        self.unfold_dock()
        self.page.click(f'{DECISION} th[data-column="option-stop-withdraw"] input')
        buttons = """[...document.querySelectorAll('button[data-command-type]')].filter((button) => !button.closest('[hidden]'))
          .map((button) => [button.dataset.commandType, button.dataset.commandTarget || '', button.getAttribute('aria-disabled') === 'true'])"""
        before = self.page.evaluate(buttons)
        on = sorted((kind, target) for kind, target, off in before if not off)
        self.assertEqual(on, sorted([
            ("run.start_preset", "p-detour"), ("run.start_preset", "p-no-path"), ("condition.open_working", "w-12"),
            # The actions follow the incident's zone (clarity pass, A1).
            ("action.stop_zone", "zone-b"), ("action.withdraw_zone", "zone-b"), ("action.execute_option", "option-stop-withdraw"),
            ("run.reset", ""),
        ]))
        self.assertEqual(self.texts(".block-note"), [])

        self.mock.fault("http_502")
        blocked = self.wait_body(8.0, commands="blocked")
        self.assertEqual(blocked["blockReason"], "stale")
        during = self.page.evaluate(buttons)
        self.assertEqual(len(during), len(before))
        self.assertTrue(all(off for _, _, off in during), f"a command button is still on: {during}")
        reason = "Команды заблокированы: данные устарели"
        for group in ("#conditions", "#actions", "#reset", "#decision"):
            self.assertEqual(self.text(f"{group} .block-note"), reason, f"{group} says why its buttons are off")
            visible = self.page.evaluate(f"""(() => {{
              const box = document.querySelector('{group} .block-note').getBoundingClientRect();
              return box.width > 0 && box.height > 0;
            }})()""")
            self.assertTrue(visible, group)
        self.open_stand()
        self.page.click(RESET)
        self.open_stand(False)
        self.page.click(EXECUTE)
        time.sleep(0.3)
        self.assertFalse(self.exists('[data-testid="dialog"]'), "a switched-off button asks nothing")

        self.mock.fault("none")
        self.wait_body(8.0, commands="enabled", link="ok")
        self.assertEqual(self.page.evaluate(buttons), before, "the buttons are as they were, the choice of the option included")
        self.assertEqual(self.texts(".block-note"), [])
        self.assertFalse(self.commands_logged())


class ResetTest(PanelsTestCase):
    def test_reset_asks_first_and_the_interrupted_run_is_archived_as_such(self):
        self.open("reset", "#/list?type=working")
        self.assertEqual(self.body()["run"], "run-0005")
        self.assertIn("run-0005", self.text("#reset"))

        self.open_stand()
        self.page.click(RESET)
        self.page.wait_for("!!document.querySelector('[data-testid=\"dialog\"]')", timeout=3.0)
        dialog = self.text('[data-testid="dialog"]')
        self.assertIn("Начать новый прогон?", dialog)
        self.assertIn("Текущий прогон run-0005 будет завершён", dialog)
        self.assertIn("останется в сравнении", dialog)
        self.assertTrue(self.page.evaluate("document.getElementById('app').inert"), "the page behind the dialog is inert")
        self.page.click('[data-testid="dialog-cancel"]')
        self.page.wait_for("!document.querySelector('[data-testid=\"dialog\"]')", timeout=3.0)
        self.assertFalse(self.page.evaluate("document.getElementById('app').inert"))
        time.sleep(1.2)
        self.assertFalse(self.commands_logged(), "a cancelled dialog sends nothing")
        self.assertEqual(self.pending(), [])

        self.page.click(RESET)
        self.confirm_dialog(["run-0005"])
        entry = self.wait_pending("run", "sent", 3.0, "run.reset")
        self.assertEqual(entry["what"], "Полный сброс прогона")
        blocked = self.wait_body(3.0, commands="blocked")
        self.assertEqual(blocked["blockReason"], "own_reset_pending")
        self.assertTrue(self.is_off(RESET))
        self.assertTrue(self.is_off(f'{CONDITIONS} button[data-command-type="condition.open_working"]'))
        self.assertTrue(self.is_off(STOP))
        self.assertEqual(self.text("#conditions .block-note"), "Команды заблокированы: сброс отправлен и ещё не подтверждён")
        self.wait_body(5.0, runState="resetting")
        self.assertEqual(self.text("#actions .block-note"), "Команды заблокированы: выполняется сброс")
        self.assertTrue(self.is_off(RESET))
        self.assertEqual(self.body()["run"], "run-0005")

        fresh = self.wait_body(10.0, run="run-0006", runState="running")
        self.assertLess(int(fresh["tick"]), 100)
        # The acknowledgement is published only by the new run: the waiting command finds it there.
        applied = self.wait_pending("run", "applied", 4.0, "run.reset")
        self.assertEqual((applied["id"], applied["text"]), (entry["id"], "Команда применена"))
        self.wait_body(4.0, commands="enabled")
        self.assertFalse(self.is_off(RESET))
        self.assertIn("run-0006", self.text("#reset"))
        self.assertEqual(self.texts(f'{CONDITIONS} [data-testid="conditions-active"] li'), [])
        self.assertEqual(self.page.evaluate("document.getElementById('decision').childNodes.length"), 0,
                         "no incident in the new run: the decision panel is empty")
        posts = self.commands_logged()
        self.assertEqual([post["body"] for post in posts],
                         [{"command_id": entry["id"], "type": "run.reset", "target": "run", "run": "run-0005"}])

        # The journal goes on across the runs and says which entries belong to the old one.
        old = '[data-testid="journal-entry"][data-code="run.reset"]'
        self.page.wait_for(f"!!document.querySelector('{old}')", timeout=3.0)
        self.assertIn("run-0005: прогон прерван сбросом", self.text(old))
        self.assertIn("другой прогон: run-0005", self.text(old))
        self.assertIn("команда " + entry["id"][:10], self.text(old))
        self.assertNotIn("другой прогон", self.text('[data-testid="journal-entry"][data-code="run.started"]'))

        self.page.click('[data-testid="tab-runs"]')
        row = '[data-testid="runs-table"] tr[data-run="run-0005"][data-series="actual"]'
        self.page.wait_for(f"!!document.querySelector('{row}')", timeout=6.0)
        self.assertEqual(self.attribute(row, "data-completion"), "reset")
        self.assertEqual(self.text(row + ' [data-testid="run-ending"]'), "прерван сбросом")
        self.assertEqual(self.text(row + ' [data-testid="run-mark"]'), "итог неполный, в сравнение не входит")
        self.assertEqual(self.text(row + ' td[data-metric="last_out_s"]'), "—", "no withdrawal time for an interrupted run")
        self.assertNotEqual(self.text(row + ' td[data-metric="all_out"]'), "да")
        self.assertEqual(len(self.texts('[data-testid="runs-table"] tr[data-series="actual"]')), 5)


class DecisionStatesTest(PanelsTestCase):
    def test_decision_point_shows_causes_pause_options_and_identifiers(self):
        self.open("paused_heartbeat", "#/list?type=option")
        self.unfold_dock()
        panel = f"{DECISION} .decision"
        self.assertEqual(self.attribute(panel, "data-incident-state"), "active")
        # Moments by the model clock, ticks in the titles (clarity pass, A8); the header of the table (A3).
        self.assertEqual(self.text(f"{DECISION} .decision__causes"), "закрыт проход: В-12, в 00:20:10")
        self.assertEqual(self.attribute(f"{DECISION} .decision__causes li", "title"), "тик\u00a01210")
        self.assertIn("участок: Участок Б", self.text(DECISION))
        self.assertEqual(self.text('[data-testid="decision-pause"]'), "Модель на паузе для выбора действия")
        self.assertEqual(self.text('[data-testid="decision-caption"]'), "Прогноз модели на 15 мин · рассчитан в 00:20:10")

        heads = self.page.evaluate(f"""[...document.querySelectorAll('{DECISION} [data-testid="decision-options"] thead th[data-column]')]
          .map((th) => [th.dataset.column, th.dataset.state, th.textContent.replace(/\\u00a0/g, ' '), th.querySelector('input').disabled])""")
        self.assertEqual([head[0] for head in heads], ["option-observe", "option-stop-withdraw", "option-withdraw-all"])
        self.assertEqual({head[1] for head in heads}, {"offered"})
        self.assertIn("Вариант 1Наблюдатьпредложен", heads[0][2])
        self.assertIn("Остановить участок и вывести персонал", heads[1][2])
        self.assertIn("Вывести всех", heads[2][2])
        self.assertFalse(any(head[3] for head in heads))
        scope = self.texts(f'{DECISION} [data-testid="decision-options"] tr[data-row="lead"] > *')
        self.assertEqual(scope, ["участки", "—", "Участок Б", "все участки"])

        # CONTRACT section 6: a time only where everyone is out; counts and exposures are separate rows.
        # «все вышли» is one row with its time (clarity pass, A3).
        self.assertEqual(self.cell("option-withdraw-all", "forecast_all_out"), "да, за 9 мин 40 с")
        for option in ("option-observe", "option-stop-withdraw"):
            self.assertEqual(self.cell(option, "forecast_all_out"), "нет")
        self.assertEqual([self.cell(option, "forecast_out") for option in ("option-observe", "option-stop-withdraw", "option-withdraw-all")],
                         ["0", "4", "14"])
        self.assertEqual(self.cell("option-stop-withdraw", "forecast_in_danger"), "0")
        # Exposures and downtime in minutes, a conversion of the published unit (clarity pass, A3).
        self.assertEqual(self.cell("option-stop-withdraw", "forecast_danger_exposure_person_s"), "0 чел.·мин")
        self.assertEqual(self.cell("option-stop-withdraw", "forecast_unknown_exposure_person_s"), "0 чел.·мин")
        self.assertEqual(self.cell("option-stop-withdraw", "forecast_no_route"), "0")
        self.assertEqual(self.cell("option-withdraw-all", "forecast_downtime_s"), "38,7 уч.·мин")
        rows = self.texts(f'{DECISION} [data-testid="decision-options"] tbody tr[data-metric-row] > th')
        # The order of the question (clarity pass, A3): danger at the end, everyone out (with the time), out, no route,
        # exposures, downtime; the people bar after them as the summary.
        self.assertEqual(rows, ["в опасных зонах на конец расчёта", "все вышли", "вышло", "без расчётного маршрута",
                                "пребывание в опасных зонах", "пребывание в зонах с неизвестным состоянием",
                                "суммарный простой участков"])

        self.assertEqual(self.attribute(panel, "data-decision-id"), "d-0005-01")
        self.assertEqual(self.attribute(panel, "data-comparison"), "shared")
        ids = self.text('[data-testid="decision-ids"]')
        self.assertIn("идентификатор решения: d-0005-01", ids)
        self.assertIn("ключ сравнения: ck-2d0eeaecec47 — общий для всех вариантов", ids)
        self.assertFalse(self.exists('[data-testid="decision-fact"]'), "no fact before the model publishes one")
        self.assertIsNone(self.text('[data-testid="decision-nobody-left"]'))

        # Nothing is chosen for the user; the button says what is missing.
        self.assertTrue(self.is_off(EXECUTE))
        self.assertEqual(self.text(EXECUTE), "Запустить вариант…")
        self.assertEqual(self.text('[data-testid="decision-command"]'), "Выберите вариант в заголовке таблицы")
        self.page.click(f'{DECISION} th[data-column="option-stop-withdraw"] input')
        self.assertFalse(self.is_off(EXECUTE))
        self.assertEqual(self.attribute(EXECUTE, "data-command-target"), "option-stop-withdraw")
        self.assertEqual(self.text(f"{DECISION} .decision__picked"), "Выбран: Вариант 2 — Остановить участок и вывести персонал")
        # The choice survives the polls, and a cancelled dialog sends nothing.
        self.wait_polls(2)
        self.assertTrue(self.page.evaluate(f"document.querySelector('{DECISION} th[data-column=\"option-stop-withdraw\"] input').checked"))
        self.page.click(EXECUTE)
        self.page.wait_for("!!document.querySelector('[data-testid=\"dialog\"]')", timeout=3.0)
        self.assertIn("Вариант 2 — Остановить участок и вывести персонал. Участки: Участок Б", self.text('[data-testid="dialog"]'))
        self.wait_polls(2)
        self.assertTrue(self.exists('[data-testid="dialog"]'), "a poll does not close the dialog")
        self.page.press("Escape")
        self.page.wait_for("!document.querySelector('[data-testid=\"dialog\"]')", timeout=3.0)
        self.assertEqual(self.page.focus_info()["testid"], "btn-execute")
        self.assertFalse(self.commands_logged())
        self.assert_no_page_overflow()

    def test_no_forecast_shows_the_words_and_not_one_number(self):
        self.open("no_forecast", "#/list?type=option")
        self.unfold_dock()
        self.assertEqual(self.text('[data-testid="decision-no-forecast"]'), "Прогноз не опубликован")
        self.assertEqual(self.texts('[data-testid="decision-caption"] li'), [])
        self.assertEqual(self.texts(f"{DECISION} td[data-metric]"), [], "no metric cell without a forecast")
        for cell in self.texts(f'{DECISION} [data-testid="decision-forecast"] td'):
            self.assertRegex(cell, NO_DIGIT)
        self.assertFalse(self.exists('[data-testid="decision-fact"]'))
        # The options are still offered with their decision: the dispatcher can act without a forecast.
        self.assertEqual(self.attribute(f"{DECISION} .decision", "data-decision-id"), "d-0005-01")
        self.assertEqual(len(self.texts(f"{DECISION} thead th[data-column]")), 3)
        self.assertTrue(self.is_off(EXECUTE))
        time.sleep(0.3)    # the dock unfolds over 200 ms (clarity pass, M3)
        self.page.click(f'{DECISION} th[data-column="option-observe"] input')
        self.assertFalse(self.is_off(EXECUTE))

    def test_partial_forecast_is_marked(self):
        self.open("partial_forecast", "#/list?type=option")
        caption = self.text('[data-testid="decision-caption"]')
        self.assertIn("Прогноз модели на 15 мин", caption)
        self.assertIn("по неполным данным", caption)
        self.assertEqual(self.attribute('[data-testid="decision-caption"] li', "data-quality"), "partial")
        # «все вышли» carries its time (clarity pass, A3).
        self.assertEqual(self.cell("option-withdraw-all", "forecast_all_out"), "да, за 9 мин 40 с")

    def test_incomplete_withdrawal_is_not_a_success(self):
        self.open("withdrawal_incomplete", "#/list?type=zone")
        fact = '[data-testid="decision-fact"][data-option="option-withdraw-all"]'
        self.assertEqual(self.attribute(f"{DECISION} .decision", "data-incident-state"), "done")
        self.assertIn("Факт прогона: Вариант 3 — Вывести всех", self.text(fact))
        self.assertIn("Вывод не завершён: 2 работника без расчётного маршрута. Это за пределами того, что решает модель",
                      self.text(fact))
        self.assertEqual(self.texts(fact + " thead th"), ["Показатель", "прогноз модели", "факт прогона"])
        # «все вышли — нет», and no time at all: the time has no row of its own (clarity pass, A3).
        self.assertEqual(self.cell("option-withdraw-all", "actual_all_out", fact), "нет")
        self.assertFalse(self.exists(f'{fact} td[data-metric="actual_last_out_s"]'))
        self.assertEqual(self.cell("option-withdraw-all", "actual_out", fact), "12")
        self.assertEqual(self.cell("option-withdraw-all", "actual_no_route", fact), "2")
        self.assertEqual(self.cell("option-withdraw-all", "forecast_no_route", fact), "2", "the forecast keeps its own column")
        self.assertIn("нет открытого пути до выхода для Р-07, Р-08", self.text('[data-testid="decision-no-path"]'))
        # Nothing is offered any more: the options are listed with their states and cannot be chosen.
        states = self.page.evaluate(f"""[...document.querySelectorAll('{DECISION} [data-testid="decision-options"] thead th[data-column]')]
          .map((th) => [th.dataset.state, th.querySelector('input').hidden])""")
        self.assertEqual(states, [["unavailable", True], ["unavailable", True], ["done", True]])
        self.assertIsNone(self.text(EXECUTE))
        # S6: an option the model no longer offers is «недоступен», not «не выбран» (nobody is choosing any more).
        observe = self.text(f'{DECISION} [data-testid="decision-options"] th[data-column="option-observe"]')
        self.assertIn("недоступен", observe)
        self.assertNotIn("не выбран", observe)
        self.assertIn("исполнен", self.text(f'{DECISION} [data-testid="decision-options"] th[data-column="option-withdraw-all"]'))
        self.unfold_dock()
        self.assert_no_page_overflow()

    def test_every_cause_of_the_incident_is_listed(self):
        self.open("sensor_lost_after_danger", "#/list?type=zone")
        self.assertEqual(self.texts(f"{DECISION} .decision__causes li"),
                         ["опасность на участке: Участок В, в 00:11:40", "потеряны данные датчиков: Э-05, в 00:13:40"])
        self.assertEqual(self.attribute(f"{DECISION} .decision", "data-incident-state"), "executing")
        self.assertIsNone(self.text('[data-testid="decision-pause"]'))
        self.assertEqual(self.cell("option-observe", "forecast_in_danger"), "2")
        self.assertEqual(self.cell("option-observe", "forecast_danger_exposure_person_s"), "30 чел.·мин")
        self.assertEqual(self.attribute(f'{DECISION} th[data-column="option-observe"]', "data-state"), "executing")
        # «исполняется» and twice «недоступен» in the headings: the table still fits the dock at 1280x720.
        self.unfold_dock()
        self.assert_no_page_overflow()

    # The decision panel without an incident: no children, the note in its attribute, and the dock under the stage
    # not on the screen at all (the stage takes its room).
    EMPTY_NOTE = """(() => {
      const panel = document.getElementById('decision');
      const dock = document.getElementById('decision-dock') || panel;
      return {children: panel.childNodes.length, note: panel.getAttribute('data-empty-note'),
              shown: dock.getClientRects().length > 0};
    })()"""

    def test_no_incident_leaves_the_panel_empty(self):
        self.open("normal")
        self.assertEqual(self.page.evaluate("document.getElementById('decision').childNodes.length"), 0)
        self.assertEqual(self.attribute("#decision", "data-empty-note"), "Инцидентов нет. Варианты не предложены")
        self.assertEqual(self.page.evaluate(self.EMPTY_NOTE),
                         {"children": 0, "note": "Инцидентов нет. Варианты не предложены", "shown": False})

    def test_empty_panel_claims_no_incident_only_when_the_model_published_that(self):
        """S5a: without a full snapshot, or without a published incident state, the note says «no data»."""
        no_data = "Нет данных об инциденте и вариантах"
        # Never a full snapshot: the attributes are read, every state is rejected.
        self.mock.scenario("topology_mismatch")
        self.page.goto("about:blank")
        self.page.goto(self.mock.url + "/")
        self.wait_body(boot="ready", snapshot="invalid")
        empty = self.page.evaluate(self.EMPTY_NOTE)
        self.assertEqual((empty["children"], empty["note"], empty["shown"]), (0, no_data, False))
        self.assertNotIn("Инцидентов нет", self.text("#right") or "")

        # The attributes are read again and a full snapshot arrives: now the model itself says that there is no incident.
        self.mock.scenario("normal")
        self.page.wait_for("document.getElementById('decision').getAttribute('data-empty-note') === 'Инцидентов нет. Варианты не предложены'",
                           timeout=15.0, message="the note follows the published state")
        self.assertEqual(self.body()["snapshot"], "ok")
        self.assertEqual(self.page.evaluate(self.EMPTY_NOTE)["note"], "Инцидентов нет. Варианты не предложены")

    def test_forecast_without_its_quality_is_marked(self):
        """S5b: forecast numbers whose `forecast_quality` is not published carry a visible mark."""
        mark = "полнота прогноза не опубликована"
        self.page.add_init_script(REWRITE)
        self.open("paused_heartbeat", "#/list?type=option")
        self.unfold_dock()
        caption = '[data-testid="decision-caption"] li'
        self.assertNotIn(mark, self.text(caption), "a full forecast needs no mark")
        self.page.evaluate("""window.__rewrite = (shift, scene) => {
          for (const name of Object.keys(scene)) if (name.startsWith('option-')) delete scene[name].forecast_quality;
        }""")
        self.wait_text(caption, mark)
        self.assertEqual(self.attribute(caption, "data-quality"), "")
        shown = self.page.evaluate(f"""(() => {{
          const node = document.querySelector('{caption}').lastElementChild;
          return {{text: node.textContent, hidden: node.hidden, cls: node.className, height: node.getBoundingClientRect().height}};
        }})()""")
        self.assertEqual((shown["text"], shown["hidden"], shown["cls"]), (mark, False, "badge badge--unknown"))
        self.assertGreater(shown["height"], 0, "the mark is on the screen")
        self.assertEqual(self.cell("option-withdraw-all", "forecast_all_out"), "да, за 9 мин 40 с", "the numbers stay, with the mark above them")
        # The list says the same in the row of each option.
        for option in ("option-observe", "option-stop-withdraw", "option-withdraw-all"):
            row = plain(self.page.evaluate(f"document.querySelector('[data-testid=\"list\"] tr[data-thing-id=\"{NS}:{option}\"]').textContent"))
            self.assertIn(mark, row)
        # An executed option: the forecast column of its fact table carries the mark as well.
        self.page.evaluate("window.__rewrite = null")
        self.open("withdrawal_incomplete", "#/list?type=option")
        fact = '[data-testid="decision-fact"][data-option="option-withdraw-all"]'
        self.assertNotIn(mark, self.text(fact))
        self.page.evaluate("""window.__rewrite = (shift, scene) => { delete scene['option-withdraw-all'].forecast_quality; }""")
        self.wait_text(fact + ' th[data-column="forecast"]', mark)
        self.assertNotIn(mark, self.text(fact + ' th[data-column="actual"]'))

    def test_one_comparison_key_is_claimed_only_when_every_option_has_it(self):
        """S5c: one option without the key, or with another one, and the columns are no longer called a comparison."""
        self.page.add_init_script(REWRITE)
        self.open("paused_heartbeat")
        self.unfold_dock()
        panel = f"{DECISION} .decision"
        warning = '[data-testid="decision-keys-differ"]'
        ids = '[data-testid="decision-ids"]'
        self.assertEqual(self.attribute(panel, "data-comparison"), "shared")
        self.assertIsNone(self.text(warning))
        self.assertIn("общий для всех вариантов", self.text(ids))

        # One option does not publish the key.
        self.page.evaluate("window.__rewrite = (shift, scene) => { delete scene['option-observe'].comparison_key; }")
        self.page.wait_for(f"document.querySelector({panel!r}).dataset.comparison === 'different'", timeout=6.0)
        self.assertEqual(self.text(warning),
                         "У вариантов нет общего ключа сравнения (Вариант 1: не опубликован; Вариант 2: ck-2d0eeaecec47; "
                         "Вариант 3: ck-2d0eeaecec47). Их показатели нельзя сравнивать между собой")
        self.assertNotIn("общий для всех вариантов", self.text(ids))
        self.assertNotIn("ключ сравнения", self.text(ids))
        order = self.page.evaluate(f"""(() => {{
          const note = document.querySelector('{warning}').getBoundingClientRect();
          const table = document.querySelector('[data-testid="decision-options"]').getBoundingClientRect();
          return {{above: note.bottom <= table.top + 1, height: note.height,
                  before: !!(document.querySelector('{warning}').compareDocumentPosition(document.querySelector('[data-testid="decision-options"]')) & 4)}};
        }})()""")
        self.assertTrue(order["above"] and order["before"] and order["height"] > 0, f"the warning stands above the table: {order}")
        self.assertEqual(self.cell("option-withdraw-all", "forecast_out"), "14", "the numbers are still shown, under the warning")

        # Another key in one option.
        self.page.evaluate("window.__rewrite = (shift, scene) => { scene['option-withdraw-all'].comparison_key.properties.value = 'ck-other'; }")
        self.wait_text(warning, "Вариант 3: ck-other")
        self.assertEqual(self.attribute(panel, "data-comparison"), "different")
        # A key that is not text is not a key.
        self.page.evaluate("window.__rewrite = (shift, scene) => { scene['option-stop-withdraw'].comparison_key.properties.value = 17; }")
        self.wait_text(warning, "Вариант 2: не опубликован")
        self.assertEqual(self.attribute(panel, "data-comparison"), "different")
        # All the same again.
        self.page.evaluate("window.__rewrite = null")
        self.page.wait_for(f"document.querySelector({panel!r}).dataset.comparison === 'shared'", timeout=6.0)
        self.assertIsNone(self.text(warning))


class JournalAndRunsTest(PanelsTestCase):
    def lines(self):
        return self.page.evaluate("""[...document.querySelectorAll('[data-testid="journal"] li')].map((node) => ({
          gap: node.dataset.gap || null, seq: node.dataset.seq ? Number(node.dataset.seq) : null, code: node.dataset.code || null,
          text: node.textContent.replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim(),
        }))""")

    def test_journal_is_newest_first_with_sentences_and_command_ids(self):
        self.open("paused_heartbeat")
        lines = self.lines()
        self.assertEqual([line["seq"] for line in lines], [218, 217, 216, 215, 214, 213, 212])
        by_seq = {line["seq"]: line["text"] for line in lines}
        # The moment by the model clock and its age (clarity pass, A8); the model stands still at 00:20:10 here.
        self.assertEqual(by_seq[218], "00:20:10 · сейчас Р-06: изменён расчётный маршрут — выход Съезд")
        self.assertEqual(by_seq[214], "00:20:10 · сейчас условие задано: «В-12 закрыта» команда c-783b3b20…")
        self.assertEqual(by_seq[213], "00:00:00 · 20 мин назад Участок Г: изменилась опасность — внимание")
        self.assertEqual(by_seq[212], "00:00:00 · 20 мин назад run-0005: прогон начат")
        self.assertEqual(self.page.evaluate("document.querySelector('[data-testid=\"journal-entry\"][data-seq=\"218\"] .journal-line__time').title"),
                         "тик\u00a01210", "the tick stays in the title")
        self.assertFalse([line for line in lines if line["gap"]])
        # Condensed journal of the right column: the latest three entries, one line each, inside the region.
        strip = self.page.evaluate("""(() => {
          const body = document.querySelector('[data-testid="journal"]').getBoundingClientRect();
          const shown = [...document.querySelectorAll('[data-testid="journal"] li')].filter((li) => li.getClientRects().length > 0);
          const boxes = shown.map((li) => li.getBoundingClientRect());
          return {shown: shown.map((li) => Number(li.dataset.seq)),
                  inside: boxes.every((box) => box.top >= body.top - 0.5 && box.bottom <= body.bottom + 0.5),
                  oneLine: boxes.every((box) => box.height <= 30)};
        })()""")
        self.assertEqual(strip, {"shown": [218, 217, 216], "inside": True, "oneLine": True})
        self.assertEqual(self.text('[data-testid="journal-toggle"]'), "Весь журнал (7 событий)")
        self.page.click('[data-testid="journal-toggle"]')
        self.assertEqual(self.page.evaluate("[...document.querySelectorAll('[data-testid=\"journal\"] li')]"
                                            ".filter((li) => li.getClientRects().length > 0).length"), 7)
        self.assertGreater(self.page.evaluate("document.querySelector('[data-testid=\"journal\"]').getBoundingClientRect().height"), 150)

    def test_journal_says_where_events_are_missing(self):
        self.open("sensor_lost_after_danger")
        lines = self.lines()
        order = [("gap", line["gap"]) if line["gap"] else line["seq"] for line in lines]
        at = order.index(("gap", "2"))
        self.assertEqual(order[at - 1:at + 2], [220, ("gap", "2"), 217])
        self.assertEqual(lines[at]["text"], "Пропущено 2 события: № 218–219")
        self.assertEqual([item for item in order if not isinstance(item, tuple)],
                         sorted((item for item in order if not isinstance(item, tuple)), reverse=True))
        self.assertEqual(len([item for item in order if isinstance(item, tuple)]), 1)

    def test_journal_shows_an_unknown_code_as_it_is(self):
        self.open("unknown_enum")
        unknown = next(line for line in self.lines() if line["code"] == "ventilation.changed")
        self.assertEqual(AGE.sub(" · ", unknown["text"]), "00:15:00 · Участок А: ventilation.changed — reduced")

    def test_journal_words_for_command_and_withdrawal_events(self):
        self.open("commands")
        texts = [AGE.sub(" · ", line["text"]) for line in self.lines()]
        self.assertIn("00:11:50 · Участок А: вывод персонала завершён", texts)
        self.assertIn("00:06:40 · Участок А: команда применена — Вывести персонал участка команда c-2584dcf4…", texts)
        self.assertIn("00:06:20 · Участок А: команда отклонена — недопустимо в текущем состоянии "
                      "(not_allowed_in_state) команда c-e86e3a2d…", texts)
        self.assertIn("00:09:20 · Р-09: работник вышел — выход Съезд", texts)

    def test_runs_table_groups_comparable_runs_and_marks_the_others(self):
        self.open("normal", "#/runs")
        table = '[data-testid="runs-table"]'
        self.page.wait_for(f"document.querySelectorAll('{table} tr[data-series=\"actual\"]').length === 4", timeout=6.0)
        self.assertIn("Показаны последние 10 завершённых прогонов", self.text("#view-runs"))
        groups = self.page.evaluate(f"""[...document.querySelectorAll('{table} tbody')].map((body) => ({{
          kind: body.dataset.group, key: body.dataset.comparisonKey,
          title: body.querySelector('.runs-group__title').textContent.replace(/\\u00a0/g, ' '),
          runs: [...body.querySelectorAll('tr[data-series="actual"]')].map((row) => [row.dataset.run, row.dataset.comparable]),
        }}))""")
        self.assertEqual(groups, [
            {"kind": "single", "key": "ck-7b107a5ea7bd", "title": "Ключ сравнения ck-7b107a5ea7bd: нет сравнимых прогонов",
             "runs": [["run-0004", "false"]]},
            {"kind": "comparison", "key": "ck-cd9c9d8910d8", "title": "Сравнение: 2 прогона с ключом ck-cd9c9d8910d8",
             "runs": [["run-0001", "true"], ["run-0002", "true"], ["run-0003", "false"]]},
        ])
        # One key is one common group: its size is published where a run of the key says that everyone was out.
        self.assertEqual(self.text(f'{table} tbody[data-comparison-key="ck-cd9c9d8910d8"] .runs-group__size'), "общая группа 14")
        self.assertFalse(self.exists(f'{table} tbody[data-comparison-key="ck-7b107a5ea7bd"] .runs-group__size'))

        def run(name, series="actual"):
            row = f'{table} tr[data-run="{name}"][data-series="{series}"]'
            cells = self.page.evaluate(f"""Object.fromEntries([...document.querySelectorAll('{row} td')]
              .map((td) => [td.dataset.metric, td.textContent.replace(/\\u00a0/g, ' ')]))""")
            return cells

        def about(name, test_id):
            return self.text(f'{table} tr[data-run="{name}"] [data-testid="{test_id}"]')

        # Not everyone out: no time, in the fact and in the forecast alike.
        first = run("run-0001")
        self.assertEqual((first["all_out"], first["last_out_s"], first["out"]), ("не все вышли", "нет: не все вышли", "4"))
        self.assertRegex(run("run-0001", "forecast")["last_out_s"], NO_DIGIT)
        self.assertEqual(about("run-0001", "run-ending"), "вывод завершён")
        self.assertIsNone(about("run-0001", "run-mark"))
        self.assertIn("seed 42 · Вариант 2 — Остановить участок и вывести персонал", self.text(f'{table} tr[data-run="run-0001"] .runs-about'))
        second = run("run-0002")
        self.assertEqual((second["all_out"], second["last_out_s"], second["out"], second["downtime_s"]),
                         ("да", "9 мин 40 с", "14", "2320 уч.·с"))
        self.assertEqual((second["in_danger"], second["danger_exposure_person_s"], second["unknown_exposure_person_s"],
                          second["no_route"]), ("0", "0 чел.·с", "0 чел.·с", "0"))
        # Interrupted: what the run published stays, what it did not is a dash; the promise of the forecast is another row.
        third = run("run-0003")
        self.assertEqual(about("run-0003", "run-ending"), "прерван сбросом")
        self.assertEqual(about("run-0003", "run-mark"), "итог неполный, в сравнение не входит")
        self.assertEqual((third["all_out"], third["last_out_s"], third["out"]), ("не все вышли", "—", "3"))
        promised = run("run-0003", "forecast")
        self.assertEqual((promised["all_out"], promised["last_out_s"], promised["out"]), ("да", "9 мин 40 с", "14"))
        self.assertEqual(self.text(f'{table} tr[data-run="run-0003"][data-series="forecast"] th'), "прогноз модели")
        self.assertEqual(self.text(f'{table} tr[data-run="run-0003"][data-series="actual"] .runs-series'), "факт прогона")
        fourth = run("run-0004")
        self.assertEqual(about("run-0004", "run-ending"), "достигнут горизонт расчёта")
        self.assertEqual(about("run-0004", "run-mark"), "несравним: условие изменено после решения")
        self.assertRegex(fourth["last_out_s"], NO_DIGIT)
        self.assertEqual(self.texts(f"{table} thead th"), ["Прогон", "Данные", "все вышли", "выход всех", "вышло", "в оп. зонах",
                                                          "в оп. зонах, чел.·с", "неизв., чел.·с", "без маршр.", "простой, уч.·с"])
        self.assert_no_page_overflow()

        # Reading and failure of the archive are said in words (the state is set here; the reads themselves are test_core's).
        words = self.js(APP + """
          const archive = app.store.getState().archive;
          const status = () => document.querySelector('[data-testid="runs-status"]');
          app.store.update({archive: {...archive, status: 'loading'}});
          const loading = [status().hidden, status().textContent];
          app.store.update({archive: {...archive, status: 'error', failure: {kind: 'http', status: 502}}});
          const failed = [status().hidden, status().textContent];
          app.store.update({archive: {status: 'ready', ids: [], runs: [], failure: null}});
          const empty = [...document.querySelectorAll('#view-runs .empty-note')].filter((node) => !node.hidden).map((node) => node.textContent);
          app.store.update({archive});
          return {loading, failed, empty};
        """)
        self.assertEqual(words, {"loading": [False, "Архив прогонов читается"],
                                 "failed": [False, "Архив прогонов не прочитан: HTTP 502"],
                                 "empty": ["Завершённых прогонов нет"]})


    def test_a_run_without_a_classified_ending_is_not_compared(self):
        """S3: an absent or unknown `completion_reason` is shown as it is, marked, and left out of the comparison."""
        self.open("normal", "#/runs")
        table = '[data-testid="runs-table"]'
        self.page.wait_for(f"document.querySelectorAll('{table} tr[data-series=\"actual\"]').length === 4", timeout=6.0)
        got = self.js(APP + """
          const archive = app.store.getState().archive;
          const withRun = (name, edit) => ({...archive, runs: archive.runs.map((run) => {
            if (run.name !== name) return run;
            const values = {...run.values};
            edit(values);
            return {...run, values};
          })});
          const read = (name) => {
            const row = document.querySelector(`[data-testid="runs-table"] tr[data-run="${name}"][data-series="actual"]`);
            const about = (id) => { const node = row.querySelector(`[data-testid="${id}"]`); return node ? node.textContent : null; };
            const cell = (metric) => row.querySelector(`td[data-metric="${metric}"]`).textContent;
            const group = row.closest('tbody');
            return {ending: about('run-ending'), mark: about('run-mark'), comparable: row.dataset.comparable,
                    cells: [cell('all_out'), cell('last_out_s'), cell('out')],
                    group: [group.dataset.group, group.querySelector('.runs-group__title').textContent]};
          };
          const out = {before: read('run-0001')};
          app.store.update({archive: withRun('run-0001', (values) => { delete values.completion_reason; })});
          out.absent = read('run-0001');
          out.other = read('run-0002');
          app.store.update({archive: withRun('run-0001', (values) => { values.completion_reason = 'evacuated'; })});
          out.unknown = read('run-0001');
          app.store.update({archive: withRun('run-0002', (values) => { values.state = 'running'; })});
          out.running = read('run-0002');
          // The forecast row of a run names how complete the forecast was, or that this is not published.
          const forecastLabel = () => document.querySelector('[data-testid="runs-table"] tr[data-run="run-0002"][data-series="forecast"] th').textContent;
          out.forecast = [];
          for (const edit of [() => {}, (values) => { values.forecast_quality = 'partial'; }, (values) => { delete values.forecast_quality; }]) {
            app.store.update({archive: withRun('run-0002', edit)});
            out.forecast.push(forecastLabel());
          }
          app.store.update({archive});
          out.restored = read('run-0001');
          return out;
        """)
        got = json.loads(plain(json.dumps(got, ensure_ascii=False)))
        comparison = ["comparison", "Сравнение: 2 прогона с ключом ck-cd9c9d8910d8"]
        single = ["single", "Ключ сравнения ck-cd9c9d8910d8: нет сравнимых прогонов"]
        mark = "итог не классифицирован, в сравнение не входит"
        self.assertEqual(got["before"], {"ending": "вывод завершён", "mark": None, "comparable": "true",
                                         "cells": ["не все вышли", "нет: не все вышли", "4"], "group": comparison})
        # No ending published: the state of the twin is shown, the run is marked and leaves the comparison;
        # its missing time is a dash, not the verdict «нет: не все вышли».
        self.assertEqual(got["absent"], {"ending": "завершён", "mark": mark, "comparable": "false",
                                         "cells": ["не все вышли", "—", "4"], "group": single})
        self.assertEqual((got["other"]["mark"], got["other"]["comparable"]), ("нет сравнимых прогонов", "true"))
        # An ending this interface does not know: the raw code, the same mark.
        self.assertEqual((got["unknown"]["ending"], got["unknown"]["mark"], got["unknown"]["comparable"]), ("evacuated", mark, "false"))
        # A run that is not finished has no final result, whatever ending it names.
        self.assertEqual((got["running"]["mark"], got["running"]["comparable"]), (mark, "false"))
        self.assertEqual(got["running"]["ending"], "вывод завершён · состояние: идёт")
        self.assertEqual(got["forecast"], ["прогноз модели", "прогноз модели: по неполным данным",
                                           "прогноз модели: полнота прогноза не опубликована"])
        self.assertEqual(got["restored"], got["before"])


class PeopleBarTest(PanelsTestCase):
    """The people bar of the dock and of the archive: one cell per person of the common group, published counts only."""

    def test_detour_decision_bars_count_the_common_group(self):
        self.open("paused_heartbeat")
        self.unfold_dock()
        # The size of the group: «Вывести всех» publishes all_out = true with out = 14 (CONTRACT.md 6).
        self.assertEqual(self.attribute('[data-testid="decision-group"]', "data-total"), "14")
        self.assertIn("Общая группа решения — 14 человек", self.text('[data-testid="decision-group"]'))
        expected = {
            "option-observe": ({"out": "0", "inDanger": "0", "noRoute": "0", "total": "14"}, {"left": 14}, "вышли 0 из 14 · 14 ещё под землёй"),
            "option-stop-withdraw": ({"out": "4", "inDanger": "0", "noRoute": "0", "total": "14"}, {"out": 4, "left": 10},
                                     "вышли 4 из 14 · 10 ещё под землёй"),
            "option-withdraw-all": ({"out": "14", "inDanger": "0", "noRoute": "0", "total": "14"}, {"out": 14}, "вышли 14 из 14"),
        }
        for option, (counts, cells, words) in expected.items():
            with self.subTest(option=option):
                bar = self.bar(option, scope='[data-testid="decision-options"]')
                self.assertEqual(bar["count"], 1, "one bar per option")
                self.assertEqual({key: bar[key] for key in counts}, counts)
                self.assertEqual(bar["cells"], cells, "one cell per person, and nothing else")
                self.assertEqual(plain(bar["words"]), words)
                self.assertEqual(plain(bar["label"]), words, "the bar says its words to assistive technology")
                if cells.get("out"):
                    self.assertEqual(bar["filled"], ["hatched"], "a forecast is hatched, never solid")

    def test_no_path_bars_say_the_group_is_not_published(self):
        self.open("no_path")
        self.js(APP + "return app.ctx.sendCommand('condition.close_working', 'w-07');")
        self.page.wait_for("document.body.dataset.runState === 'paused' && !!document.querySelector('[data-testid=\"decision-options\"] th[data-state=\"offered\"]')",
                           timeout=8.0, message="the decision point")
        self.unfold_dock()
        # No option brings everyone out: the size of the group is not published, and nothing is guessed.
        self.assertIsNone(self.attribute('[data-testid="decision-group"]', "data-total"))
        self.assertIn("Размер общей группы модель не публикует", self.text('[data-testid="decision-group"]'))
        # Without a published group size no «из N» is written (clarity pass, A3).
        expected = {"option-observe": ("0", {"no_route": 2, "unknown": 1}, "вышли 0 · для 2 чел. выход не рассчитан"),
                    "option-stop-withdraw": ("0", {"no_route": 2, "unknown": 1}, "вышли 0 · для 2 чел. выход не рассчитан"),
                    "option-withdraw-all": ("12", {"out": 12, "no_route": 2, "unknown": 1}, "вышли 12 · для 2 чел. выход не рассчитан")}
        for option, (out, cells, words) in expected.items():
            with self.subTest(option=option):
                bar = self.bar(option, scope='[data-testid="decision-options"]')
                self.assertEqual((bar["out"], bar["noRoute"], bar["inDanger"], bar["total"]), (out, "2", "0", None))
                self.assertEqual(bar["cells"], cells, "the published counts, then an open «?» end")
                self.assertEqual(plain(bar["words"]), words)

    def test_incomplete_withdrawal_fact_bar_is_solid_and_not_everyone_is_out(self):
        self.open("withdrawal_incomplete")
        self.unfold_dock()
        fact = '[data-testid="decision-fact"][data-option="option-withdraw-all"]'
        actual = self.bar("option-withdraw-all", series="fact", scope=fact)
        self.assertEqual((actual["out"], actual["noRoute"], actual["inDanger"], actual["total"]), ("12", "2", "0", None))
        self.assertEqual(actual["cells"], {"out": 12, "no_route": 2, "unknown": 1})
        self.assertEqual(actual["filled"], ["solid"], "a fact is solid")
        self.assertEqual(plain(actual["words"]), "вышли 12 · для 2 чел. выход не рассчитан")
        forecast = self.bar("option-withdraw-all", series="forecast", scope=fact)
        self.assertEqual((forecast["out"], forecast["noRoute"]), ("12", "2"))
        self.assertEqual(forecast["filled"], ["hatched"], "its forecast beside it stays hatched")
        # The line of the folded dock says the same, and never a time.
        summary = plain(self.text('#decision-summary') or self.text('.decision__summary'))
        self.assertEqual(summary, "факт прогона, Вариант 3 — Вывести всех: вышли 12 · для 2 чел. выход не рассчитан")

    def test_a_time_only_where_everyone_is_out_and_forecast_apart_from_fact(self):
        self.open("paused_heartbeat")
        self.unfold_dock()
        options = '[data-testid="decision-options"]'
        cells = self.page.evaluate(f"""Object.fromEntries([...document.querySelectorAll('{options} td[data-metric$="last_out_s"], {options} td[data-metric$="all_out"]')]
          .map((td) => [td.dataset.option + ' ' + td.dataset.metric, [td.textContent.replace(/\\u00a0/g, ' '), td.firstChild.className]]))""")
        # «все вышли» is one row: its time only next to a published `all_out = true` (clarity pass, A3).
        self.assertEqual(cells["option-withdraw-all forecast_all_out"][0], "да, за 9 мин 40 с")
        self.assertNotIn("option-withdraw-all forecast_last_out_s", cells)
        for option in ("option-observe", "option-stop-withdraw"):
            self.assertEqual(cells[f"{option} forecast_all_out"][0], "нет", "no time without everyone out")
        self.assertTrue(all("val--forecast" in cls and "val--fact" not in cls for _, cls in cells.values()), cells)
        # Neutral: the options are not ranked, and the dock says that the model recommends none of them.
        self.assertEqual(self.text('[data-testid="decision-advice"]'), "Модель не рекомендует вариант — сравните и выберите")
        words = plain(self.text(DECISION)).lower().replace("модель не рекомендует вариант", "")
        for word in ("лучш", "рекоменд", "оптимал"):
            self.assertNotIn(word, words)
        self.assertFalse(self.exists(f"{DECISION} [class*='best'], {DECISION} [class*='rank']"))

        self.open("withdrawal_incomplete")
        self.unfold_dock()
        fact = '[data-testid="decision-fact"][data-option="option-withdraw-all"]'
        self.assertEqual(self.cell("option-withdraw-all", "actual_all_out", fact), "нет")
        self.assertFalse(self.exists(f'{fact} td[data-metric="actual_last_out_s"]'))
        classes = self.page.evaluate(f"""[...document.querySelectorAll('{fact} td[data-metric^="actual_"] > span')].map((span) => span.className)""")
        self.assertTrue(classes and all("val--fact" in cls or "val--none" in cls for cls in classes), classes)

        # The archive: the same rule in the fact rows, and the bars of one key share the common group.
        self.open("normal", "#/runs")
        table = '[data-testid="runs-table"]'
        self.page.wait_for(f"document.querySelectorAll('{table} tr[data-series=\"actual\"]').length === 4", timeout=6.0)
        self.assertEqual(self.text(f'{table} tr[data-run="run-0002"][data-series="actual"] td[data-metric="last_out_s"]'), "9 мин 40 с")
        self.assertEqual(self.text(f'{table} tr[data-run="run-0001"][data-series="actual"] td[data-metric="last_out_s"]'), "нет: не все вышли")
        first = self.bar("run-0001", series="fact", scope=f'{table} tr[data-run="run-0001"][data-series="actual"]')
        self.assertEqual((first["out"], first["total"], first["cells"]), ("4", "14", {"out": 4, "left": 10}))
        cut = self.bar("run-0003", series="fact", scope=f'{table} tr[data-run="run-0003"][data-series="actual"]')
        self.assertEqual((cut["out"], cut["total"]), ("3", "14"))
        self.assertEqual(self.attribute(f'{table} tr[data-run="run-0003"][data-series="actual"]', "data-ending"), "interrupted")


class KeyboardTest(PanelsTestCase):
    def tab_until(self, predicate, limit=40):
        """Press Tab until the focused element satisfies `predicate`; return the trail of focused elements."""
        trail = []
        for _ in range(limit):
            self.page.press("Tab")
            info = self.page.focus_info()
            trail.append(info)
            if predicate(info):
                return trail
        self.fail("Tab did not reach the control; focus went through: "
                  + ", ".join(f"{item['tag']}#{item['id'] or item['testid'] or item['dataset'].get('commandType')}" for item in trail))

    def test_tab_order_enter_space_and_the_dialog(self):
        self.open("normal")
        # The stand drawer is closed and inert: Tab passes it by. Its button in the top bar opens it from the keyboard.
        self.page.evaluate("document.activeElement && document.activeElement.blur()")
        self.page.press("Tab")
        self.assertEqual(self.page.focus_info()["testid"], "stand-toggle")
        self.page.press("Enter")
        self.page.wait_for("document.body.dataset.stand === 'open'", timeout=2.0)
        self.assertEqual(self.page.focus_info()["testid"], "stand-close", "the focus moves into the opened drawer")
        trail = self.tab_until(lambda info: info["testid"] == "btn-reset", limit=30)
        trail += self.tab_until(lambda info: info["dataset"].get("commandType") == "action.resume_zone", limit=60)
        controls = [(item["tag"], item["id"] or item["dataset"].get("commandType") or item["testid"]) for item in trail
                    if item["id"].startswith(("condition-", "action-")) or item["dataset"].get("commandType")]
        self.assertEqual(controls, [
            ("button", "run.start_preset"), ("button", "run.start_preset"),
            ("select", "condition-working_closed"), ("button", "condition.close_working"),
            ("select", "condition-sensor_lost"), ("button", "condition.sensor_lost"),
            ("select", "condition-instability"), ("button", "condition.instability_on"), ("button", "run.reset"),
            ("select", "action-zone"), ("button", "action.stop_zone"), ("button", "action.withdraw_zone"),
            ("button", "action.resume_zone"),
        ], "the stand controls are one group in the drawer, the dispatcher's actions another, and every control is a Tab stop")
        self.page.evaluate("document.querySelector('[data-testid=\"btn-reset\"]').focus()")

        # Enter on the reset button opens the dialog; focus is inside and stays inside.
        self.page.press("Enter")
        self.page.wait_for("!!document.querySelector('[data-testid=\"dialog\"]')", timeout=3.0)
        self.assertEqual(self.page.focus_info()["testid"], "dialog-cancel", "the safe answer has the focus")
        seen = []
        for shift in (False, False, False, True, True):
            self.page.press("Tab", shift=shift)
            seen.append(self.page.focus_info()["testid"])
        self.assertEqual(seen, ["dialog-confirm", "dialog-cancel", "dialog-confirm", "dialog-cancel", "dialog-confirm"])
        self.wait_polls(2)
        self.assertEqual(self.page.focus_info()["testid"], "dialog-confirm", "a poll does not move the focus in the dialog")
        self.page.press("Escape")
        self.page.wait_for("!document.querySelector('[data-testid=\"dialog\"]')", timeout=3.0)
        self.assertEqual(self.page.focus_info()["testid"], "btn-reset", "focus returns to the control that asked")
        self.assertFalse(self.commands_logged())
        # Enter on the cancel button is a cancel as well; Space on the confirm button confirms.
        self.page.press("Enter")
        self.page.wait_for("!!document.querySelector('[data-testid=\"dialog\"]')", timeout=3.0)
        self.page.press("Enter")
        self.page.wait_for("!document.querySelector('[data-testid=\"dialog\"]')", timeout=3.0)
        time.sleep(0.3)
        self.assertFalse(self.commands_logged())

        # A select changed from the keyboard, then Enter on its button sends the command.
        self.page.evaluate(f"document.querySelector('{WORKING_SELECT}').focus()")
        for _ in range(12):
            self.page.press("ArrowDown")
        self.assertEqual(self.page.focus_info()["value"], "w-12")
        self.page.press("Tab")
        self.assertEqual(self.page.focus_info()["dataset"].get("commandType"), "condition.close_working")
        self.page.press("Enter")
        closing = self.wait_commands(1, command_type="condition.close_working")
        self.assertEqual(closing[0]["body"]["target"], "w-12")
        self.assertEqual(self.page.focus_info()["dataset"].get("commandType"), "condition.close_working",
                         "the pressed button keeps the focus while its command waits")

        # Space on a dispatcher button; then three polls: focus and both selects stay as the user left them.
        self.page.evaluate(f"document.querySelector('{ZONE_SELECT}').focus()")
        # The first option is «— выберите участок —» (clarity pass, A1).
        for _ in range(3):
            self.page.press("ArrowDown")
        self.assertEqual(self.page.focus_info()["value"], "zone-c")
        self.page.press("Tab")
        self.page.press("Space")
        stopping = self.wait_commands(1, command_type="action.stop_zone")
        self.assertEqual(stopping[0]["body"]["target"], "zone-c")
        self.wait_polls(3)
        focus = self.page.focus_info()
        self.assertEqual((focus["tag"], focus["dataset"].get("commandType"), focus["dataset"].get("commandTarget")),
                         ("button", "action.stop_zone", "zone-c"))
        self.assertEqual(self.page.evaluate(f"[document.querySelector('{WORKING_SELECT}').value, document.querySelector('{ZONE_SELECT}').value]"),
                         ["w-12", "zone-c"])
        self.assertEqual(len(self.commands_logged()), 2)

    def test_the_two_groups_differ_by_heading_frame_and_button_shape(self):
        self.open("normal")
        self.choose(ZONE_SELECT, "zone-a")
        self.open_stand()
        # Read the settled colours: the dispatcher button fades in from its blocked look when commands unblock.
        self.page.wait_for(f"document.body.dataset.commands === 'enabled' && "
                           f"document.querySelector({json.dumps(WITHDRAW)}).getAttribute('aria-disabled') !== 'true'",
                           message="commands enabled")
        self.page.evaluate("document.getAnimations().forEach((animation) => animation.finish())")
        look = self.page.evaluate(f"""(() => {{
          const style = (selector, ...names) => {{
            const computed = getComputedStyle(document.querySelector(selector));
            return names.map((name) => computed[name]);
          }};
          const tag = (selector) => getComputedStyle(document.querySelector(selector), '::before').content;
          return {{
            drawer: document.querySelector('[data-testid="stand-drawer"]').textContent.slice(0, 80),
            headings: ['#conditions h2', '#actions h2'].map((selector) => document.querySelector(selector).textContent),
            subtitles: ['#conditions .panel__subtitle', '#actions .panel__subtitle'].map((selector) => document.querySelector(selector).textContent),
            frames: [style('#stand-drawer', 'borderRightStyle'), style('#actions', 'borderTopStyle')],
            buttons: [{json.dumps(CONDITIONS + ' button[data-command-type="run.start_preset"]')}, {json.dumps(WITHDRAW)}]
              .map((selector) => style(selector, 'borderTopStyle', 'backgroundColor')),
            tags: [tag({json.dumps(CONDITIONS + ' button[data-command-type="run.start_preset"]')}), tag({json.dumps(WITHDRAW)})],
          }};
        }})()""")
        self.assertIn("Управление стендом", look["drawer"])
        self.assertIn("условия эксперимента, не действия диспетчера", look["drawer"])
        self.assertEqual(look["headings"], ["Условия сценария (стенд)", "Действия диспетчера"])
        self.assertEqual(look["subtitles"], ["что происходит с шахтой", "что решает диспетчер"])
        self.assertEqual(look["frames"], [["dashed"], ["solid"]])
        # Stand: chalk dashed outline, never filled, with the «стенд» tag. Dispatcher: solid light steel fill
        # (clarity pass, A9: copper is no longer an action colour).
        self.assertEqual([style for style, _ in look["buttons"]], ["dashed", "solid"])
        self.assertEqual(look["buttons"][0][1], "rgba(0, 0, 0, 0)")
        self.assertRegex(look["buttons"][1][1], r"^rgba?\(174, 187, 199(, 1)?\)$")
        self.assertEqual(look["tags"], ['"стенд"', "none"])

    def test_selects_follow_the_selected_object_until_the_user_chooses(self):
        self.open("normal", f"#/list?type=sensor&sel={NS}:sens-ext-05")
        values = f"['{WORKING_SELECT}', '{SENSOR_SELECT}', '#condition-instability', '{ZONE_SELECT}'].map((id) => document.querySelector(id).value)"
        # No incident and no choice: no zone (clarity pass, A1).
        self.assertEqual(self.page.evaluate(values), ["", "sens-ext-05", "", ""])
        self.js(APP + f"app.ctx.select('{NS}:zone-c');")
        self.assertEqual(self.page.evaluate(values), ["", "sens-ext-05", "zone-c", "zone-c"])
        self.assertEqual(self.attribute('[data-testid="actions-zone-state"]', "data-zone"), "zone-c")
        # The user's own choice stays through the polls and through a selection of another kind.
        self.choose(ZONE_SELECT, "zone-b")
        self.choose(SENSOR_SELECT, "sens-geo-01")
        self.wait_polls(2)
        self.js(APP + f"app.ctx.select('{NS}:worker-03');")
        self.assertEqual(self.page.evaluate(values), ["", "sens-geo-01", "zone-c", "zone-b"])
        self.js(APP + f"app.ctx.select('{NS}:w-07');")
        self.assertEqual(self.page.evaluate(values), ["w-07", "sens-geo-01", "zone-c", "zone-b"])
        self.assertFalse(self.commands_logged(), "selecting sends nothing")


class StoriesTest(PanelsTestCase):
    """The passage-closure journey of DESIGN.md section 3; the mock publishes every 100 ms."""

    mock_args = ("--publication-ms", "100")

    def set_condition_and_reach_decision(self, scenario, working, label):
        self.open(scenario, f"#/list?type=zone&sel={NS}:{working}")
        self.assertEqual(self.page.evaluate(f"document.querySelector('{WORKING_SELECT}').value"), working,
                         "the working selected in the list is the target")
        self.assertEqual(self.page.evaluate("document.getElementById('decision').childNodes.length"), 0)
        self.open_stand()
        self.page.click(CLOSE)
        active = f'{CONDITIONS} [data-testid="conditions-active"] li[data-condition="working_closed:{working}"]'
        self.page.wait_for(f"!!document.querySelector({json.dumps(active)})", timeout=5.0)
        self.assertEqual(self.text(active + " .chip"), f"{label} закрыта")
        self.assertEqual(self.text(active + " button"), "Открыть")
        self.assertEqual(self.attribute(active + " button", "data-command-type"), "condition.open_working")
        self.assertIn("Отмена условия не возвращает людей и не возобновляет работу участка", self.text(CONDITIONS))
        self.page.wait_for(f"!!document.querySelector('{DECISION} .decision[data-incident-state=\"active\"]')", timeout=3.0)
        self.assertEqual(self.text('[data-testid="decision-pause"]'), "Модель на паузе для выбора действия")
        self.assertEqual(self.attribute(f"{DECISION} .decision", "data-decision-id"), "d-0005-01")
        self.assertEqual(self.attribute(f"{DECISION} .decision", "data-comparison"), "shared")
        self.assertEqual(len(self.texts(f"{DECISION} thead th[data-column]")), 3)
        # The drawer is closed again and the dock unfolded: the options are in reach.
        self.open_stand(False)
        self.unfold_dock()
        return active

    def run_option(self, option, name):
        settle(self.page)    # the strip and the dock may still be moving (clarity pass, section B)
        self.page.click(f'{DECISION} th[data-column="{option}"] input')
        self.page.click(EXECUTE)
        self.confirm_dialog(["Запустить вариант?", name])
        post = self.wait_commands(1, command_type="action.execute_option")[0]
        self.assertEqual({key: post["body"][key] for key in ("type", "target", "run", "decision_id")},
                         {"type": "action.execute_option", "target": option, "run": "run-0005", "decision_id": "d-0005-01"})
        self.page.wait_for(f"document.querySelector('{DECISION} .decision').dataset.incidentState !== 'active'", timeout=4.0)
        self.assertIsNone(self.text(EXECUTE), "nothing is offered once an option runs")
        self.assertIsNone(self.text('[data-testid="decision-pause"]'))

    def test_detour_withdraw_all_everyone_is_out_and_the_undo_restores_nothing(self):
        active = self.set_condition_and_reach_decision("detour", "w-12", "В-12")
        # «все вышли» is one row with its time (clarity pass, A3).
        self.assertEqual(self.cell("option-withdraw-all", "forecast_all_out"), "да, за 9 мин 40 с")
        self.assertEqual(self.cell("option-stop-withdraw", "forecast_all_out"), "нет")
        self.assertIsNone(self.text('[data-testid="decision-nobody-left"]'))
        self.run_option("option-withdraw-all", "Вариант 3 — Вывести всех")
        head = f'{DECISION} [data-testid="decision-options"] th[data-column="option-withdraw-all"]'
        self.assertEqual(self.attribute(head, "data-state"), "executing")
        self.assertFalse(self.exists('[data-testid="decision-fact"]'), "no fact while the option is running")

        fact = '[data-testid="decision-fact"][data-option="option-withdraw-all"]'
        self.page.wait_for(f"!!document.querySelector('{fact}')", timeout=15.0)
        self.assertEqual(self.attribute(f"{DECISION} .decision", "data-incident-state"), "done")
        self.assertEqual(self.cell("option-withdraw-all", "actual_all_out", fact), "да, за 9 мин 40 с")
        self.assertEqual(self.cell("option-withdraw-all", "actual_out", fact), "14")
        self.assertEqual(self.cell("option-withdraw-all", "forecast_all_out", fact), "да, за 9 мин 40 с")
        self.assertIsNone(self.text(fact + " .decision__alert"))
        # The forecast of the options that were not chosen stays in the table.
        self.assertEqual(self.attribute(f'{DECISION} [data-testid="decision-options"] th[data-column="option-observe"]', "data-state"),
                         "unavailable")
        self.assertEqual(self.cell("option-stop-withdraw", "forecast_out", '[data-testid="decision-options"]'), "4")

        # Undo of the condition after the withdrawal: the passage opens, people stay out, zones stay stopped.
        self.open_stand()
        self.page.click(active + " button")
        self.page.wait_for(f"!document.querySelector({json.dumps(active)})", timeout=5.0)
        self.assertEqual(self.text(f"{CONDITIONS} [data-testid=\"conditions-active\"] + p"), "нет активных")
        state = '[data-testid="actions-zone-state"]'
        for zone in ("zone-a", "zone-b", "zone-c", "zone-d"):
            self.choose(ZONE_SELECT, zone)
            self.assertEqual((self.attribute(state, "data-zone"), self.attribute(state, "data-work-state"),
                              self.attribute(state, "data-withdrawal")), (zone, "stopped", "done"))
            self.assertIn("работников на участке 0", self.text(state))
        self.assertFalse(self.is_off(RESUME), "resuming is a separate command of the dispatcher")
        self.assertEqual(self.cell("option-withdraw-all", "actual_all_out", fact), "да, за 9 мин 40 с")
        journal = self.texts('[data-testid="journal"] li')
        self.assertTrue(any("условие отменено: «В-12 закрыта»" in line for line in journal), journal[:5])
        self.assertTrue(any("условие задано: «В-12 закрыта»" in line for line in journal))
        self.assertEqual([post["body"]["type"] for post in self.commands_logged()],
                         ["condition.close_working", "action.execute_option", "condition.open_working"])

    def test_detour_stop_and_withdraw_zone_is_not_everyone_out(self):
        self.set_condition_and_reach_decision("detour", "w-12", "В-12")
        self.run_option("option-stop-withdraw", "Вариант 2 — Остановить участок и вывести персонал. Участки: Участок Б")
        fact = '[data-testid="decision-fact"][data-option="option-stop-withdraw"]'
        self.page.wait_for(f"!!document.querySelector('{fact}')", timeout=15.0)
        self.assertEqual(self.cell("option-stop-withdraw", "actual_all_out", fact), "нет")
        self.assertFalse(self.exists(f'{fact} td[data-metric="actual_last_out_s"]'), "no time without everyone out")
        self.assertEqual(self.cell("option-stop-withdraw", "actual_out", fact), "4")
        # Downtime in minutes, the published zone-seconds in the title (clarity pass, A3).
        self.assertEqual(self.cell("option-stop-withdraw", "actual_downtime_s", fact), "8,8 уч.·мин")
        self.assertEqual(plain(self.attribute(f'{fact} td[data-metric="actual_downtime_s"] span', "title")),
                         "530 уч.·с, опубликовано в участко-секундах")
        # The order for the zone itself is complete; that is the zone's own state, not "everyone is out".
        self.choose(ZONE_SELECT, "zone-b")
        state = '[data-testid="actions-zone-state"]'
        self.assertEqual((self.attribute(state, "data-work-state"), self.attribute(state, "data-withdrawal")), ("stopped", "done"))
        self.choose(ZONE_SELECT, "zone-a")
        self.assertEqual(self.attribute(state, "data-work-state"), "working")

    def test_no_path_no_option_brings_the_two_workers_out(self):
        self.set_condition_and_reach_decision("no_path", "w-07", "В-07")
        options = ("option-observe", "option-stop-withdraw", "option-withdraw-all")
        self.assertEqual([self.cell(option, "forecast_no_route") for option in options], ["2", "2", "2"])
        for option in options:
            self.assertEqual(self.cell(option, "forecast_all_out"), "нет")
        self.assertEqual(self.text('[data-testid="decision-nobody-left"]'), "Ни один вариант модели не выводит этих работников")
        self.assertEqual(self.text('[data-testid="decision-no-path"]'),
                         "В графе модели нет открытого пути до выхода для Р-07, Р-08. Модель не рассчитывает, как выводить этих работников")
        self.assertEqual(self.cell("option-withdraw-all", "forecast_out"), "12")

        self.run_option("option-withdraw-all", "Вариант 3 — Вывести всех")
        fact = '[data-testid="decision-fact"][data-option="option-withdraw-all"]'
        self.page.wait_for(f"!!document.querySelector('{fact}')", timeout=15.0)
        self.assertEqual(self.text(fact + " .decision__alert"),
                         "Вывод не завершён: 2 работника без расчётного маршрута. Это за пределами того, что решает модель")
        self.assertEqual(self.cell("option-withdraw-all", "actual_all_out", fact), "нет")
        self.assertFalse(self.exists(f'{fact} td[data-metric="actual_last_out_s"]'))
        self.assertEqual((self.cell("option-withdraw-all", "actual_out", fact), self.cell("option-withdraw-all", "actual_no_route", fact)),
                         ("12", "2"))
        self.choose(ZONE_SELECT, "zone-c")
        self.assertEqual(self.attribute('[data-testid="actions-zone-state"]', "data-withdrawal"), "incomplete")
        self.assertIn("вывод не завершён", self.text('[data-testid="actions-zone-state"]'))

    def test_preset_starts_a_new_run_and_reaches_its_decision_point(self):
        self.open("detour")
        presets = self.page.evaluate(f"""[...document.querySelectorAll('{CONDITIONS} li[data-preset]')]
          .map((node) => [node.dataset.preset, node.querySelector('button').textContent, node.querySelector('.note').textContent])""")
        self.assertEqual(presets, [
            ["p-detour", "Закрыть В-12 на 60-й секунде", "обход есть · Закрыть выработку: В-12 — в 00:01:00 модельного времени"],
            ["p-no-path", "Закрыть В-07 на 60-й секунде", "пути нет · Закрыть выработку: В-07 — в 00:01:00 модельного времени"],
        ])
        preset = f'{CONDITIONS} button[data-command-type="run.start_preset"][data-command-target="p-detour"]'
        self.open_stand()
        self.page.click(preset)
        self.page.wait_for("!!document.querySelector('[data-testid=\"dialog\"]')", timeout=3.0)
        self.page.click('[data-testid="dialog-cancel"]')
        time.sleep(0.4)
        self.assertFalse(self.commands_logged())

        self.page.click(preset)
        self.confirm_dialog(["Запустить сценарий с новым прогоном?", "Текущий прогон run-0005 будет прерван",
                             "«Закрыть В-12 на 60-й секунде»"])
        post = self.wait_commands(1)[0]
        self.assertEqual({key: post["body"][key] for key in ("type", "target", "run")},
                         {"type": "run.start_preset", "target": "p-detour", "run": "run-0005"})
        self.wait_body(10.0, run="run-0006")
        applied = self.wait_pending("p-detour", "applied", 4.0)
        self.assertEqual(applied["what"], "Запустить сценарий: Закрыть В-12 на 60-й секунде")

        # The schedule of the preset sets the condition at model second 60; the model pauses for the decision.
        self.page.wait_for(f"!!document.querySelector('{DECISION} .decision[data-decision-id=\"d-0006-01\"]')", timeout=8.0)
        self.assertEqual(self.body()["runState"], "paused")
        self.assertEqual(self.text('[data-testid="decision-pause"]'), "Модель на паузе для выбора действия")
        self.assertEqual(self.text(f"{DECISION} .decision__causes"), "закрыт проход: В-12, в 00:01:00")
        self.assertEqual(self.texts(f'{CONDITIONS} [data-testid="conditions-active"] .chip'), ["В-12 закрыта"])
        self.assertEqual(self.cell("option-withdraw-all", "forecast_all_out"), "да, за 9 мин 40 с")
        journal = self.texts('[data-testid="journal"] li')
        self.assertTrue(any("В-12: условие задано — сценарий «Закрыть В-12 на 60-й секунде»" in line for line in journal), journal)
        self.assertTrue(any("run-0006: прогон начат — сценарий «Закрыть В-12 на 60-й секунде»" in line for line in journal), journal)
        self.assertEqual(len(self.commands_logged()), 1)

    def test_every_scenario_renders_the_panels_without_console_errors(self):
        names = [item["name"] for item in self.mock.scenarios()["scenarios"]]
        self.assertGreaterEqual(len(names), 23)
        for name in names:
            with self.subTest(scenario=name):
                self.mock.scenario(name)
                self.page.goto("about:blank")
                self.page.goto(self.mock.url + "/#/runs")
                # Long enough for the boot, three publications and whatever the scenario does after them.
                time.sleep(1.6)
                self.page.click('[data-testid="journal-toggle"]', force=True)
                self.assertEqual(self.page.console_errors, [], name)
                shown = self.page.evaluate("""({
                  groups: ['conditions', 'actions', 'reset'].map((id) => document.getElementById(id).childElementCount > 0),
                  runs: !!document.querySelector('[data-testid="runs-table"]'),
                  journal: document.querySelector('[data-testid="journal"]').childElementCount > 0,
                  offWithoutReason: [...document.querySelectorAll(':is(.group, .stand__part) button[data-command-type][aria-disabled="true"]')]
                    .filter((button) => {
                      const group = button.closest('.group, .stand__part');
                      const block = group.querySelector('.block-note');
                      const why = button.parentElement.querySelector('.note--why') || button.closest('li, .group__part, .act')?.querySelector('.note--why');
                      const select = button.parentElement.querySelector('select');
                      return !((block && !block.hidden) || (why && !why.hidden) || (select && select.value === ''));
                    }).map((button) => button.dataset.commandType),
                })""")
                self.assertEqual(shown, {"groups": [True, True, True], "runs": True, "journal": True, "offWithoutReason": []})
