"""Design variant 2 «Пульт смены»: the screen follows the situation of the shift.

Each agent of the variant appends its own test class here.

    python -m unittest discover -s team/ui/tests -t team/ui -p "test_v2.py" -v
"""

from __future__ import annotations

import re
import time

from browser_support import STRIP_EQUIPMENT, BrowserTestCase, MockServer, wait_until

NS = "team040.mine"
NBSP = " "


def plain(value):
    """Text with non-breaking spaces read as spaces."""
    return value.replace(NBSP, " ") if isinstance(value, str) else value


# ---- V2-D: the right panel «Решение» / «Выполнение» / «Итог» (view/decide.js, view/progress.js) ----------------

class RightPanelTest(BrowserTestCase):
    """The right panel by real clicks and keys, and its honesty rules, against the mock server.

    The stage runs as the SVG scheme (`mode=scheme`): the panel does not depend on WebGL, and the
    3D stage has tests of its own. Publications are 200 ms, so a withdrawal ends within seconds.
    """

    ROUTE = "/#/scheme?mode=scheme"
    PANEL_JS = "document.querySelector('#panel .dp')"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock = MockServer("normal", extra_args=("--publication-ms", "200")).start()
        cls.addClassCleanup(cls.mock.stop)

    # ---- helpers ---------------------------------------------------------------------------

    def open(self, scenario, situation=None, size=None, reduced=False, count_motion=False):
        self.mock.scenario(scenario)
        if size:
            self.page.set_viewport(*size)
        if reduced:
            self.page.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
        if count_motion:
            # Every animation of the panel body is counted where it starts (motion.js plays Web Animations).
            self.page.add_init_script("""
              window.__panelMotion = 0;
              const animate = Element.prototype.animate;
              Element.prototype.animate = function (...args) {
                if (this.classList && this.classList.contains('dp__body')) window.__panelMotion += 1;
                return animate.apply(this, args);
              };""")
        self.page.goto(self.mock.url + self.ROUTE)
        self.page.wait_for("document.body.dataset.boot === 'ready' && document.body.dataset.snapshot === 'ok'", timeout=20)
        if situation:
            self.page.wait_for(f"document.body.dataset.situation === '{situation}'", timeout=30)
            self.page.wait_for(f"document.querySelector('#panel')?.dataset.panelMode === '{situation}'", timeout=5)

    def js(self, body):
        return self.page.evaluate("(async () => {" + body + "})()")

    def cards(self):
        return self.js("""
          return [...document.querySelectorAll('#panel .dp-card')].map((card) => ({
            option: card.dataset.option, kind: card.dataset.optionKind, state: card.dataset.state,
            checked: card.getAttribute('aria-checked'), disabled: card.getAttribute('aria-disabled'),
            tabindex: card.getAttribute('tabindex'),
            verb: card.querySelector('.dp-card__verb').textContent,
            headline: card.querySelector('.dp-card__headline').textContent,
            rule: card.querySelector('.dp-card__headline').dataset.rule,
            text: card.textContent,
            barShown: !card.querySelector('.dp-card__bar').hidden,
            total: card.querySelector('svg.pb')?.getAttribute('data-total') ?? null,
          }));""")

    def hover_option(self):
        return self.js("const {app} = await import('/js/main.js'); return app.store.getState().ui.hoverOption;")

    def text_of(self, selector):
        return plain(self.page.evaluate(f"document.querySelector({selector!r})?.textContent ?? null"))

    def commands(self, type_):
        return [entry for entry in self.mock.log()["entries"] if entry.get("kind") == "command"
                and (entry.get("body") or {}).get("type") == type_]

    # ---- «Решение» -----------------------------------------------------------------------

    def test_danger_zone_decision_launch_executing_done_by_real_clicks(self):
        """Decision → choose «Остановить участок Г и вывести людей» → confirm → executing → done → «Закрыть итог»."""
        self.open("danger_zone", "decision")
        page = self.page
        self.assertEqual(self.text_of("#panel .dp__title"), "Решение")
        self.assertFalse(page.evaluate("document.querySelector('[data-testid=panel-pause]').hidden"))
        self.assertEqual(self.text_of("[data-testid=decide-what] .dp-what__line"), "Участок Г — опасно")
        self.assertIn("+ потеряны данные Э-05", self.text_of("[data-testid=decide-what-more]"))
        people = self.text_of("[data-testid=decide-people]")
        self.assertIn("3 человека в опасной зоне:", people)
        self.assertIn("2 — состояние неизвестно:", people)
        codes = page.evaluate("[...document.querySelectorAll('[data-testid=decide-people] [data-row=danger] .dp-who')].map((b) => b.textContent)")
        self.assertEqual(codes, ["Р-11", "Р-12", "Р-13"])
        caption = self.text_of("[data-testid=decide-caption]")
        self.assertIn("Прогноз модели на 15 мин", caption)
        self.assertIn("модель не рекомендует вариант — выбор за диспетчером", caption)

        cards = self.cards()
        self.assertEqual([card["verb"] for card in cards], ["Наблюдать", "Остановить участок Г и вывести людей", "Вывести всех"])
        # The headline of each card by the fixed rules (decision.js headline()).
        self.assertEqual([plain(card["headline"]) for card in cards],
                         ["3 человека останутся в опасной зоне", "В опасной зоне никого · вышли 4", "Все выйдут за 9 мин 40 с"])
        self.assertEqual([card["rule"] for card in cards], ["in_danger", "clear", "all_out"])
        self.assertTrue(all(card["checked"] == "false" for card in cards))
        launch = "[data-testid=btn-execute]"
        self.assertEqual(page.evaluate(f"document.querySelector('{launch}').getAttribute('aria-disabled')"), "true")
        self.assertEqual(self.text_of("[data-testid=decide-why]"), "Выберите вариант выше")
        # Pressing the launch while nothing is chosen sends nothing.
        page.click(launch)
        time.sleep(0.3)
        self.assertFalse(page.evaluate("Boolean(document.querySelector('[data-testid=dialog]'))"))

        page.click("#panel .dp-card[data-option-kind=stop_withdraw_zone]")
        page.wait_for("document.querySelector('#panel .dp-card[data-option-kind=stop_withdraw_zone]').getAttribute('aria-checked') === 'true'")
        self.assertEqual(self.hover_option(), f"{NS}:option-stop-withdraw", "the chosen option lights its zones on the stage")
        self.assertEqual(self.text_of(launch), "Запустить: Остановить участок Г и вывести людей")
        self.assertIsNone(page.evaluate(f"document.querySelector('{launch}').getAttribute('aria-disabled')"))

        page.click(launch)
        page.wait_for("document.querySelector('[data-testid=dialog]')")
        self.assertIn("Остановить участок Г и вывести людей", self.text_of("[data-testid=dialog]"))
        page.click("[data-testid=dialog-confirm]")
        wait_until(lambda: self.commands("action.execute_option"), timeout=5, message="the launch reaches the platform")
        body = self.commands("action.execute_option")[0]["body"]
        self.assertEqual((body["target"], body["decision_id"]), ("option-stop-withdraw", "d-0005-01"))

        # Выполнение.
        page.wait_for("document.querySelector('#panel')?.dataset.panelMode === 'executing'", timeout=10)
        self.assertEqual(self.text_of("#panel .dp__title"), "Выполняется: Остановить участок Г и вывести людей")
        self.assertIsNone(self.hover_option(), "outside the decision no option is pointed at")
        self.assertEqual(page.evaluate("document.querySelector('[data-testid=progress-main]').dataset.figure"), "out")
        self.assertEqual(self.text_of("[data-testid=progress-expect]"), "по прогнозу модели выйдут 4")
        listed = page.evaluate("[...document.querySelectorAll('[data-testid=progress-people] .dp-who__code')].map((n) => n.textContent).sort()")
        self.assertEqual(listed, ["Р-11", "Р-12", "Р-13", "Р-14"])
        self.assertIn("остановлен · вывод персонала идёт", self.text_of("[data-testid=progress-zones]"))
        # The figure is the published counter, whatever it is at this moment.
        published_out = self.js("const {app} = await import('/js/main.js'); return app.store.getState().model.shift.values.workers_out;")
        self.assertEqual(page.evaluate("Number(document.querySelector('[data-testid=progress-main]').dataset.value)"), published_out)

        # Итог.
        page.wait_for("document.querySelector('#panel')?.dataset.panelMode === 'done'", timeout=30)
        self.assertEqual(self.text_of("#panel .dp__title"), "Итог: Остановить участок Г и вывести людей")
        self.assertEqual(self.text_of("[data-testid=result-fact] .dp-result__line"), "В опасной зоне никого · вышли 4")
        self.assertEqual(self.text_of("[data-testid=result-forecast] .dp-result__line"), "В опасной зоне никого · вышли 4")
        heads = page.evaluate("[...document.querySelectorAll('[data-testid=result-table] thead th[data-column]')].map((th) => th.dataset.column)")
        self.assertEqual(heads, ["forecast", "actual"])
        self.assertEqual(self.text_of("[data-testid=result-table] td[data-metric=actual_all_out]"), "нет")
        page.click("[data-testid=result-close]")
        page.wait_for("document.body.dataset.panel === 'none' && document.querySelector('#panel').hidden")
        time.sleep(0.6)
        self.assertTrue(page.evaluate("document.querySelector('#panel').hidden"), "«Закрыть итог» holds over new publications")

    def test_cards_are_a_radio_group_and_the_launch_is_reachable_by_keys(self):
        self.open("danger_zone", "decision")
        page = self.page
        cards = self.cards()
        self.assertEqual([card["tabindex"] for card in cards], ["0", "-1", "-1"], "one tab stop for the group")
        self.assertEqual(page.evaluate("document.querySelector('[data-testid=decide-options]').getAttribute('role')"), "radiogroup")
        page.evaluate("document.querySelector('#panel .dp-card').focus()")
        page.press("Space")
        page.wait_for("document.querySelector('#panel .dp-card').getAttribute('aria-checked') === 'true'")
        page.press("ArrowDown")
        page.wait_for("document.activeElement.dataset.option === 'option-stop-withdraw'")
        self.assertEqual([card["checked"] for card in self.cards()], ["false", "true", "false"])
        self.assertEqual(self.hover_option(), f"{NS}:option-stop-withdraw")
        page.press("End")
        page.wait_for("document.activeElement.dataset.option === 'option-withdraw-all'")
        page.press("ArrowDown")
        page.wait_for("document.activeElement.dataset.option === 'option-observe'", message="the arrows wrap around")
        page.press("ArrowUp")
        page.wait_for("document.activeElement.dataset.option === 'option-withdraw-all'")
        self.assertEqual(self.cards()[2]["tabindex"], "0", "the tab stop follows the choice")
        # Tab leaves the group: «Подробнее», then the launch button.
        for _ in range(4):
            page.press("Tab")
            if page.evaluate("document.activeElement.dataset.testid") == "btn-execute":
                break
        self.assertEqual(page.evaluate("document.activeElement.dataset.testid"), "btn-execute")
        self.assertEqual(self.text_of("[data-testid=btn-execute]"), "Запустить: Вывести всех")
        page.press("Enter")
        page.wait_for("document.querySelector('[data-testid=dialog]')")
        page.press("Escape")
        page.wait_for("!document.querySelector('[data-testid=dialog]')")
        time.sleep(0.3)
        self.assertEqual(self.commands("action.execute_option"), [], "a cancelled dialog sends nothing")

    def test_hover_previews_an_option_and_leaving_returns_to_the_choice(self):
        self.open("danger_zone", "decision")
        page = self.page
        page.hover("#panel .dp-card[data-option-kind=withdraw_all]")
        page.wait_for(f"(async () => (await import('/js/main.js')).app.store.getState().ui.hoverOption === '{NS}:option-withdraw-all')()")
        page.click("#panel .dp-card[data-option-kind=observe]")
        page.hover("#panel .dp-card[data-option-kind=stop_withdraw_zone]")
        page.wait_for(f"(async () => (await import('/js/main.js')).app.store.getState().ui.hoverOption === '{NS}:option-stop-withdraw')()")
        page.hover("[data-testid=decide-what]")
        page.wait_for(f"(async () => (await import('/js/main.js')).app.store.getState().ui.hoverOption === '{NS}:option-observe')()",
                      message="leaving the cards falls back to the chosen option")

    def test_the_decision_panel_fits_both_sizes_without_console_errors(self):
        for size in ((1920, 1080), (1280, 720)):
            with self.subTest(size=size):
                self.open("danger_zone", "decision", size=size)
                got = self.js("""
                  const panel = document.querySelector('#panel');
                  const body = panel.querySelector('.dp__body');
                  const box = panel.getBoundingClientRect();
                  const launch = panel.querySelector('[data-testid=btn-execute]').getBoundingClientRect();
                  const cards = [...panel.querySelectorAll('.dp-card .dp-card__headline')].map((n) => n.getBoundingClientRect().bottom);
                  return {width: box.width, right: box.right, horizontal: body.scrollWidth - body.clientWidth,
                    launch: [launch.top, launch.bottom, launch.height], bodyBottom: body.getBoundingClientRect().bottom, cards,
                    pageScroll: document.scrollingElement.scrollHeight - innerHeight};""")
                self.assertEqual(got["horizontal"], 0, "no horizontal scroll inside the panel")
                self.assertLessEqual(got["right"], size[0])
                self.assertLessEqual(got["pageScroll"], 0, "the page itself does not scroll")
                self.assertGreaterEqual(got["launch"][2], 44, "the primary button is 44 px high")
                self.assertLessEqual(got["launch"][1], size[1], "the launch button is in sight")
                self.assertTrue(all(bottom <= got["bodyBottom"] + 1 for bottom in got["cards"]),
                                f"the headline of every option is in sight without scrolling: {got}")

    # ---- honesty -------------------------------------------------------------------------

    def test_headline_rules_never_invent_a_time_or_a_success(self):
        self.open("normal")
        got = self.js("""
          const T = await import('/js/text.js');
          const D = await import('/js/view/decision.js');
          const line = (values, prefix = 'forecast_') => { const got = D.headline(T, values, prefix); return got && [got.rule, got.text]; };
          return [
            line({forecast_all_out: true, forecast_last_out_s: 580, forecast_out: 14}),
            line({forecast_all_out: true, forecast_out: 14}),
            line({forecast_all_out: false, forecast_last_out_s: 580, forecast_in_danger: 0, forecast_out: 4}),
            line({forecast_all_out: false, forecast_in_danger: 3, forecast_no_route: 2, forecast_out: 0}),
            line({forecast_all_out: false, forecast_in_danger: 1}),
            line({forecast_all_out: false, forecast_in_danger: 0, forecast_no_route: 2, forecast_out: 12}),
            line({forecast_all_out: false, forecast_in_danger: 0}),
            line({forecast_downtime_s: 30}),
            line({}),
            line({decision_id: 'd-1', state: 'offered'}),
            line({actual_all_out: true, actual_last_out_s: 330}, 'actual_'),
            line({actual_all_out: false, actual_in_danger: 0, actual_no_route: 2, actual_out: 12}, 'actual_'),
            line({actual_all_out: 'maybe', actual_in_danger: 0, actual_out: 4}, 'actual_'),
          ];""")
        got = [item and [item[0], plain(item[1])] for item in got]
        self.assertEqual(got, [
            ["all_out", "Все выйдут за 9 мин 40 с"],
            ["all_out", "Все выйдут"],
            ["clear", "В опасной зоне никого · вышли 4"],
            ["in_danger", "3 человека останутся в опасной зоне"],
            ["in_danger", "1 человек останется в опасной зоне"],
            ["no_route", "Для 2 человек выход не рассчитан · вышли 12"],
            ["clear", "В опасной зоне никого"],
            ["none", "—"],
            None,
            None,
            ["all_out", "Все вышли за 5 мин 30 с"],
            ["no_route", "Вышли 12 — не все: для 2 человек выход не рассчитан"],
            ["clear", "В опасной зоне никого · вышли 4"],
        ])

    def test_no_path_after_closing_w07_says_that_no_option_brings_them_out(self):
        self.open("no_path")
        self.js("const {app} = await import('/js/main.js'); return app.ctx.sendCommand('condition.close_working', 'w-07');")
        self.page.wait_for("document.querySelector('#panel')?.dataset.panelMode === 'decision'", timeout=20)
        self.page.wait_for("document.querySelectorAll('#panel .dp-card').length === 3")
        self.assertEqual(self.text_of("[data-testid=decide-what] .dp-what__line"), "Участок В — закрыт проход В-07")
        self.assertEqual(self.text_of("[data-testid=decide-people] [data-row=noroute]"),
                         "у Р-07, Р-08 нет расчётного маршрута — ни один вариант модели их не выводит")
        self.assertTrue(self.page.evaluate("Boolean(document.querySelector('[data-testid=decide-no-path]'))"))
        cards = self.cards()
        self.assertEqual([card["rule"] for card in cards], ["no_route", "no_route", "no_route"])
        self.assertEqual([plain(card["headline"]) for card in cards], [
            "Для 2 человек выход не рассчитан · вышли 0", "Для 2 человек выход не рассчитан · вышли 0",
            "Для 2 человек выход не рассчитан · вышли 12"])
        for card in cards:
            self.assertNotIn("Все выйдут", card["text"])
            self.assertIsNone(card["total"], "no option says everyone is out: the bar has no group size")
            self.assertNotRegex(plain(card["text"]), r"из \d", "no invented group size")

    def test_no_forecast_shows_no_numbers_and_still_lets_choose(self):
        self.open("no_forecast", "decision")
        cards = self.cards()
        self.assertEqual(len(cards), 3)
        for card in cards:
            self.assertEqual(card["headline"], "Прогноз не опубликован")
            self.assertEqual(card["rule"], "not_published")
            self.assertFalse(card["barShown"])
            self.assertNotRegex(card["text"], r"\d", f"no number on a card without a forecast: {card['text']!r}")
        self.assertTrue(self.page.evaluate("document.querySelector('[data-testid=decide-caption]').hidden"))
        self.assertTrue(self.page.evaluate("document.querySelector('[data-testid=decide-details]').hidden"))
        self.page.click("#panel .dp-card[data-option-kind=observe]")
        self.page.wait_for("document.querySelector('[data-testid=btn-execute]').getAttribute('aria-disabled') === null")

    def test_partial_forecast_is_marked(self):
        self.open("partial_forecast", "decision")
        caption = self.text_of("[data-testid=decide-caption]")
        self.assertIn("по неполным данным", caption)
        self.assertEqual(self.page.evaluate("document.querySelector('[data-testid=decide-caption]').dataset.quality"), "partial")

    def test_sensor_lost_after_danger_executes_observe_and_keeps_the_last_danger_in_sight(self):
        self.open("sensor_lost_after_danger", "executing")
        self.assertEqual(self.text_of("#panel .dp__title"), "Выполняется: Наблюдать")
        main = self.page.evaluate("(() => { const n = document.querySelector('[data-testid=progress-main]'); return [n.dataset.figure, n.dataset.value, n.textContent]; })()")
        self.assertEqual(main[:2], ["in_danger", "0"])
        second = self.page.evaluate("(() => { const n = document.querySelector('[data-testid=progress-second]'); return [n.hidden, n.dataset.figure, n.dataset.value]; })()")
        self.assertEqual(second, [False, "unknown", "2"], "unknown is said next to the zero, never hidden by it")
        self.assertEqual(self.text_of("[data-testid=progress-expect]"), "по прогнозу модели: 2 человека останутся в опасной зоне")
        zones = self.text_of("[data-testid=progress-zones]")
        self.assertIn("последнее известное: опасно", zones)
        self.assertIn("состояние неизвестно", zones)
        rows = self.page.evaluate("[...document.querySelectorAll('[data-testid=progress-people] li')].map((li) => li.textContent)")
        self.assertEqual(sorted(plain(row) for row in rows),
                         ["Р-07работает · опасность на месте неизвестна", "Р-08работает · опасность на месте неизвестна"])

    def test_withdrawal_incomplete_is_no_success(self):
        self.open("withdrawal_incomplete", "done")
        self.assertEqual(self.text_of("#panel .dp__title"), "Итог: Вывести всех")
        fact = self.text_of("[data-testid=result-fact] .dp-result__line")
        self.assertEqual(fact, "Вышли 12 — не все: для 2 человек выход не рассчитан")
        self.assertNotRegex(fact, r"за \d", "no time unless everyone is out")
        alerts = self.text_of("[data-testid=result-alerts]")
        self.assertIn("Участок В: вывод не завершён", alerts)
        self.assertIn("у Р-07, Р-08 нет расчётного маршрута", alerts)
        self.assertEqual(self.text_of("[data-testid=result-table] td[data-metric=actual_all_out]"), "нет")
        self.assertEqual(self.text_of("[data-testid=result-table] td[data-metric=forecast_all_out]"), "нет")

    # ---- motion --------------------------------------------------------------------------

    def test_the_panel_switch_moves_once_per_change_and_never_on_load(self):
        self.open("danger_zone", "decision", count_motion=True)
        time.sleep(0.5)
        self.assertEqual(self.page.evaluate("window.__panelMotion"), 0, "nothing moves on load")
        self.page.click("#panel .dp-card[data-option-kind=stop_withdraw_zone]")
        self.page.click("[data-testid=btn-execute]")
        self.page.click("[data-testid=dialog-confirm]", timeout=3)
        self.page.wait_for("document.querySelector('#panel')?.dataset.panelMode === 'executing'", timeout=10)
        time.sleep(1.0)
        self.assertEqual(self.page.evaluate("window.__panelMotion"), 1, "decision → executing: one slide")
        self.page.wait_for("document.querySelector('#panel')?.dataset.panelMode === 'done'", timeout=30)
        time.sleep(1.0)
        self.assertEqual(self.page.evaluate("window.__panelMotion"), 2, "executing → done: one slide")

    def test_reduced_motion_switches_the_panel_instantly(self):
        self.open("danger_zone", "decision", reduced=True, count_motion=True)
        self.page.click("#panel .dp-card[data-option-kind=withdraw_all]")
        self.page.click("[data-testid=btn-execute]")
        self.page.click("[data-testid=dialog-confirm]", timeout=3)
        self.page.wait_for("document.querySelector('#panel')?.dataset.panelMode === 'executing'", timeout=10)
        time.sleep(0.5)
        self.assertEqual(self.page.evaluate("window.__panelMotion"), 0)


# ---- V2-L: the frame, the top bar, the rail «Люди», the floating card, the menu overlays, the stand drawer -------

class FrameTest(BrowserTestCase):
    """The frame of «Пульт смены» against the mock server, in 3D through SwiftShader as on a machine without a GPU.

    Smoke of every situation at both sizes, the main flows of the frame by real clicks, and the honesty of the rail:
    the figures are the published counters, the dots follow each worker's published position and status.
    """

    chrome_args = ("--use-angle=swiftshader", "--enable-unsafe-swiftshader")
    viewport = (1920, 1080)
    SIZES = ((1920, 1080), (1280, 720))

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock = MockServer("normal").start()
        cls.addClassCleanup(cls.mock.stop)

    def setUp(self):
        super().setUp()
        self.mock.fault("none")

    # ---- helpers ---------------------------------------------------------------------------

    def open(self, scenario, situation=None, size=(1920, 1080), route=""):
        self.mock.scenario(scenario)
        self.page.set_viewport(*size)
        self.page.goto("about:blank")
        self.page.goto(self.mock.url + "/" + route)
        self.page.wait_for("document.body.dataset.boot === 'ready' && document.body.dataset.snapshot === 'ok'", timeout=30)
        if situation:
            self.page.wait_for(f"document.body.dataset.situation === '{situation}'", timeout=40)

    def js(self, body, timeout=20.0):
        return self.page.evaluate("(async () => {" + body + "})()", timeout=timeout)

    def body(self):
        return self.page.evaluate("Object.assign({}, document.body.dataset)")

    def frame(self):
        """Boxes of the regions and the published counters next to the figures of the rail."""
        return self.js("""
          const {app} = await import('/js/main.js');
          const box = (selector) => { const n = document.querySelector(selector); if (!n || n.offsetParent === null) return null;
            const r = n.getBoundingClientRect(); return {left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width}; };
          const values = app.store.getState().model.shift.values;
          const figures = {};
          for (const id of ['total', 'out', 'in-danger', 'no-route', 'unknown']) {
            const n = document.querySelector(`[data-testid="incident-${id}"]`);
            figures[id] = n ? n.textContent : null;
          }
          return {
            top: box('#statusbar'), rail: box('#rail-region'), centre: box('#centre'), panel: box('#panel'),
            hud: box('#stage-hud'), notice: document.querySelector('[data-testid=status-notice]').textContent,
            noticeShown: box('[data-testid=status-notice]') !== null,
            figures, published: {total: values.workers_total, out: values.workers_out, 'in-danger': values.workers_in_danger,
              'no-route': values.workers_no_route, unknown: values.workers_unknown},
            scroll: [document.scrollingElement.scrollWidth - innerWidth, document.scrollingElement.scrollHeight - innerHeight],
            coverRight: getComputedStyle(document.querySelector('#centre')).getPropertyValue('--cover-right').trim(),
          };""")

    def rail_groups(self):
        """The dots of the rail by group, and the groups the published fields of every worker call for."""
        return self.js("""
          const {app} = await import('/js/main.js');
          const M = await import('/js/model.js');
          const model = app.store.getState().model;
          const expected = {};
          const add = (key, id) => (expected[key] = expected[key] || []).push(id);
          for (const worker of M.thingsOfKind(model, 'worker')) {
            const v = worker.values;
            if (v.status === 'out') add('out:' + (v.at_exit || ''), worker.thingId);
            else if (typeof v.at_working === 'string') {
              const zone = M.zoneOfWorking(model, v.at_working);
              add(zone ? zone.thingId : 'outside', worker.thingId);
            } else add('no-position', worker.thingId);
          }
          const shown = {};
          for (const row of document.querySelectorAll('#rail .zrow')) {
            const key = row.dataset.railZone || row.dataset.railGroup;
            if (key === 'out') {
              for (const line of row.querySelectorAll('.zrow__exit')) {
                shown['out:' + (line.dataset.exit || '')] = [...line.querySelectorAll('[data-rail-worker]')].map((d) => d.dataset.railWorker);
              }
            } else {
              const dots = [...row.querySelectorAll('[data-rail-worker]')].map((d) => d.dataset.railWorker);
              if (dots.length) shown[key] = dots;
            }
          }
          for (const key of Object.keys(expected)) expected[key].sort();
          for (const key of Object.keys(shown)) shown[key].sort();
          const zones = [...document.querySelectorAll('#rail [data-rail-zone]')].map((row) => [row.dataset.railZone, row.dataset.hazard]);
          const published = M.thingsOfKind(model, 'zone').map((zone) => [zone.thingId, zone.hazard.state]);
          return {expected, shown, zones, published};""")

    # ---- every situation at both sizes ---------------------------------------------------------

    def test_every_situation_renders_at_both_sizes_with_the_frame_of_variant_2(self):
        cases = (("normal", "norm", "none"), ("danger_zone", "decision", "shown"),
                 ("sensor_lost_after_danger", "executing", "shown"), ("withdrawal_incomplete", "done", "shown"))
        for scenario, situation, panel in cases:
            for size in self.SIZES:
                with self.subTest(scenario=scenario, size=size):
                    self.open(scenario, situation, size)
                    body = self.body()
                    self.assertEqual(body["situation"], situation)
                    self.assertEqual(body["panel"], panel)
                    got = self.frame()
                    self.assertEqual(got["scroll"], [0, 0], "no page scroll, no horizontal scroll")
                    self.assertTrue(got["noticeShown"], "the synthetic-data notice is always in sight")
                    self.assertIn("Синтетические данные.", plain(got["notice"]))
                    self.assertIn("Расчёт модели, не сведения о реальной шахте", plain(got["notice"]))
                    self.assertEqual(got["top"]["bottom"], 48, "the top bar is 48 px high")
                    self.assertEqual(round(got["rail"]["width"]), 300 if size[0] == 1920 else 260)
                    # Published counters only: every figure is the published value, written as such.
                    for key, value in got["published"].items():
                        self.assertEqual(plain(got["figures"][key]), str(value), f"figure {key}")
                    # The stage keeps the centre: at 1920 the panel takes its own column, at 1280 it lies over the stage.
                    if panel == "shown":
                        self.assertIsNotNone(got["panel"])
                        self.assertEqual(round(got["panel"]["right"]), size[0])
                        if size[0] == 1920:
                            self.assertEqual(round(got["panel"]["width"]), 420)
                            self.assertLessEqual(got["centre"]["right"], got["panel"]["left"] + 0.5)
                        else:
                            self.assertEqual(round(got["panel"]["width"]), 360)
                            self.assertEqual(got["coverRight"], "360px")
                            self.assertLessEqual(got["hud"]["right"], got["panel"]["left"] + 0.5, "the HUD stays clear of the panel")
                    else:
                        self.assertIsNone(got["panel"], "no right panel in the norm")
                        self.assertEqual(round(got["centre"]["right"]), size[0])

    # ---- the rail: published values only ----------------------------------------------------------

    def test_rail_dots_follow_each_workers_published_position_and_status(self):
        for scenario, situation in (("danger_zone", "decision"), ("withdrawal_incomplete", "done"), ("normal", "norm")):
            with self.subTest(scenario=scenario):
                self.open(scenario, situation)
                got = self.rail_groups()
                self.assertEqual(got["shown"], got["expected"])
                self.assertEqual(got["zones"], got["published"], "one row per zone, in the order of the platform, displayed hazard")
        # A worker in the danger zone has the red ring of the stage marker; a worker without a route the crossed square.
        self.open("danger_zone", "decision")
        dot = self.page.evaluate("""(() => { const d = document.querySelector('[data-rail-worker="team040.mine:worker-11"]');
          return [d.getAttribute('aria-label'), d.dataset.locationHazard, d.dataset.egress,
            getComputedStyle(d.querySelector('.worker__danger')).display]; })()""")
        self.assertTrue(plain(dot[0]).startswith("Р-11: "), dot[0])
        self.assertIn("в опасной зоне", dot[0])
        self.assertEqual(dot[1:], ["danger", "ok", "inline"])

    def test_unknown_is_never_shown_as_normal_and_a_past_danger_stays_in_sight(self):
        self.open("sensor_lost_after_danger", "executing")
        row = self.page.evaluate("""(() => { const r = document.querySelector('[data-rail-zone="team040.mine:zone-c"]');
          return {hazard: r.dataset.hazard, badge: r.querySelector('.zrow__badge').className,
            words: r.querySelector('.zrow__badge').textContent, note: r.querySelector('.zrow__note').textContent,
            noteShown: !r.querySelector('.zrow__note').hidden, edge: getComputedStyle(r).borderLeftStyle}; })()""")
        self.assertEqual(row["hazard"], "unknown")
        self.assertIn("badge--unknown", row["badge"])
        self.assertEqual(row["words"], "неизвестно")
        self.assertTrue(row["noteShown"])
        self.assertIn("последнее известное: опасно", plain(row["note"]))
        self.assertEqual(row["edge"], "dashed")
        unknown = self.page.evaluate("document.querySelector('[data-figure=unknown]').className")
        self.assertIn("is-alert--unknown", unknown, "unknown above zero has the dashed «?» style")

    # ---- flows by real clicks ------------------------------------------------------------------------

    def test_zone_row_selects_the_zone_asks_the_stage_and_the_card_floats_until_closed(self):
        self.open("danger_zone", "decision")
        self.js("""const {app} = await import('/js/main.js'); window.__focus = [];
          const focus = app.ctx.stage.focus; app.ctx.stage.focus = (id) => { window.__focus.push(id); return focus(id); };""")
        self.page.click('[data-rail-zone="team040.mine:zone-d"] [data-testid=rail-zone]')
        self.page.wait_for("document.body.dataset.sheet === 'open'")
        self.assertEqual(self.page.evaluate("window.__focus"), [f"{NS}:zone-d"])
        self.assertIn("is-selected", self.page.evaluate("document.querySelector('[data-rail-zone=\"team040.mine:zone-d\"]').className"))
        self.assertEqual(self.page.evaluate("document.querySelector('#sheet .card__code').textContent"), "Участок Г")
        card = self.page.evaluate("(() => { const r = document.querySelector('#sheet').getBoundingClientRect(); const c = document.querySelector('#centre').getBoundingClientRect();"
                                  " return [r.right <= c.right, r.bottom <= c.bottom, r.top > c.top]; })()")
        self.assertEqual(card, [True, True, True], "the card floats inside the stage")
        self.page.press("Escape")
        self.page.wait_for("document.body.dataset.sheet === 'closed' && document.querySelector('#sheet').hidden")
        self.assertIsNone(self.js("const {app} = await import('/js/main.js'); return app.store.getState().ui.selected;"))
        # A dot selects its worker; × closes the card.
        self.page.click('[data-rail-worker="team040.mine:worker-12"]')
        self.page.wait_for("document.body.dataset.sheet === 'open'")
        self.assertEqual(self.page.evaluate("document.querySelector('#sheet .card__code').textContent"), "Р-12")
        self.assertEqual(self.page.evaluate("document.querySelector('[data-rail-worker=\"team040.mine:worker-12\"]').getAttribute('aria-pressed')"), "true")
        self.page.click("[data-testid=card-close]")
        self.page.wait_for("document.body.dataset.sheet === 'closed'")

    def test_zone_actions_unfold_under_the_row_and_are_secondary_while_the_model_waits(self):
        self.open("danger_zone", "decision")
        row = '[data-rail-zone="team040.mine:zone-d"]'
        self.assertTrue(self.page.evaluate(f"document.querySelector('{row} .zrow__actions').hidden"))
        self.page.click(f"{row} [data-testid=rail-zone-actions]")
        self.page.wait_for(f"!document.querySelector('{row} .zrow__actions').hidden")
        got = self.page.evaluate(f"""(() => {{ const a = document.querySelector('{row} [data-testid=actions-panel]');
          return {{types: [...a.querySelectorAll('button[data-command-type]')].map((b) => [b.dataset.commandType, b.dataset.commandTarget,
            b.classList.contains('btn--secondary'), b.getAttribute('aria-disabled')]),
            waits: !a.querySelector('[data-testid=actions-waits]').hidden}}; }})()""")
        self.assertTrue(got["waits"], "the note that the model waits for an option")
        self.assertEqual([item[:3] for item in got["types"]], [
            ["action.stop_zone", "zone-d", True], ["action.withdraw_zone", "zone-d", True], ["action.resume_zone", "zone-d", True]])
        self.assertEqual(got["types"][2][3], "true", "resume is off for a working zone, with its reason")
        self.page.click(f"{row} button[data-command-type='action.stop_zone']")
        self.page.wait_for("document.querySelector('#pending [data-testid=pending][data-command-type=\"action.stop_zone\"]')", timeout=5)
        wait_until(lambda: any((entry.get("body") or {}).get("type") == "action.stop_zone"
                               for entry in self.mock.log()["entries"] if entry.get("kind") == "command"), timeout=5)
        toast = self.page.evaluate("(() => { const t = document.querySelector('#pending').getBoundingClientRect();"
                                   " const c = document.querySelector('#centre').getBoundingClientRect(); return [t.left >= c.left, t.bottom <= c.bottom]; })()")
        self.assertEqual(toast, [True, True], "sent commands appear as toasts over the stage")

    def test_menu_overlays_open_over_the_frame_and_back_to_the_mine(self):
        self.open("sensor_lost_after_danger", "executing")
        page = self.page
        page.click("[data-testid=menu-toggle]")
        page.wait_for("!document.querySelector('#menu-list').hidden")
        page.click("[data-testid=tab-list]")
        page.wait_for("document.body.dataset.menu === 'list' && location.hash.startsWith('#/list')")
        cover = page.evaluate("(() => { const m = document.querySelector('#menu-view').getBoundingClientRect();"
                              " return [m.left, m.top, m.right, m.bottom, document.querySelector('#view-list').hidden]; })()")
        self.assertEqual(cover, [0, 48, 1920, 1080, False], "the overlay covers rail, stage and panel under the top bar")
        page.click("[data-testid=tab-scheme]")
        page.wait_for("document.body.dataset.menu === 'none' && document.querySelector('#menu-view').hidden")
        page.click("[data-testid=menu-toggle]")
        page.click("[data-testid=tab-journal]")
        page.wait_for("document.body.dataset.menu === 'journal'")
        self.assertGreater(page.evaluate("document.querySelectorAll('#journal [data-testid=journal-entry]').length"), 3,
                           "the whole journal, not the latest three")
        self.assertTrue(page.evaluate("Boolean(document.querySelector('#journal [data-testid=journal-gap]'))"), "a seq gap is said")
        page.press("Escape")
        page.wait_for("document.body.dataset.menu === 'none'")

    def test_stand_drawer_opens_from_the_top_bar_and_esc_returns_the_focus(self):
        self.open("normal", "norm")
        page = self.page
        page.click("[data-testid=stand-toggle]")
        page.wait_for("document.body.dataset.stand === 'open' && document.activeElement.dataset.testid === 'stand-close'")
        # The drawer slides in over 200 ms: measured where it ends.
        page.wait_for("Math.round(document.querySelector('#stand-drawer').getBoundingClientRect().left"
                      " - document.querySelector('#centre').getBoundingClientRect().left) === 0")
        got = page.evaluate("(() => { const s = document.querySelector('#stand-drawer').getBoundingClientRect();"
                            " const c = document.querySelector('#centre').getBoundingClientRect();"
                            " return [Math.round(s.left - c.left), Math.round(s.width), document.querySelector('#stand-drawer').textContent]; })()")
        self.assertEqual(got[:2], [0, 340], "the drawer lies over the left edge of the stage")
        self.assertIn("условия эксперимента, не действия диспетчера", got[2])
        page.press("Escape")
        page.wait_for("document.body.dataset.stand === 'closed' && document.activeElement.dataset.testid === 'stand-toggle'")

    def test_rail_folds_to_a_strip_of_figures(self):
        self.open("danger_zone", "decision", (1280, 720))
        self.page.click("[data-testid=rail-toggle]")
        self.page.wait_for("document.body.dataset.rail === 'collapsed'")
        got = self.page.evaluate("""(() => ({width: document.querySelector('#rail-region').getBoundingClientRect().width,
          zones: document.querySelector('#rail .rail__where').offsetParent !== null,
          danger: document.querySelector('[data-testid=incident-in-danger]').textContent,
          title: document.querySelector('[data-figure=in-danger]').title}))()""")
        self.assertEqual(round(got["width"]), 56)
        self.assertFalse(got["zones"])
        self.assertEqual(got["danger"], "3")
        self.assertEqual(got["title"], "в опасных зонах")

    def test_platform_unavailable_is_a_band_over_the_stage_and_the_rail_keeps_the_last_data(self):
        self.open("normal", "norm", (1280, 720))
        self.mock.fault("http_502")
        self.page.wait_for("document.body.dataset.link === 'unavailable'", timeout=20)
        got = self.page.evaluate("""(() => { const b = document.querySelector('[data-code=platform_unavailable]').getBoundingClientRect();
          const s = document.querySelector('#stage').getBoundingClientRect();
          return [b.height > 0, b.bottom <= s.top + 0.5, document.body.dataset.commands,
            document.querySelector('[data-testid=incident-total]').textContent]; })()""")
        self.assertEqual(got, [True, True, "blocked", "14"])
        self.mock.fault("none")

    def test_closing_the_result_gives_the_stage_the_freed_width(self):
        for size in self.SIZES:
            with self.subTest(size=size):
                self.open("withdrawal_incomplete", "done", size)
                self.page.wait_for("document.body.dataset.panel === 'shown' && document.querySelector('[data-testid=result-close]')")
                self.page.click("[data-testid=result-close]")
                self.page.wait_for("document.body.dataset.panel === 'none'")
                got = self.frame()
                self.assertIsNone(got["panel"])
                self.assertEqual(round(got["centre"]["right"]), size[0], "the stage takes the width of the closed panel")
                self.assertEqual(got["coverRight"], "0px")
                self.assertEqual(round(got["hud"]["right"]), size[0])


# ---- V2-S: the 3D stage of the shift desk (view/stage.js, js/scene3d/) ----------------------------------------

class StageV2Test(BrowserTestCase):
    """The 3D stage in the shift desk, with SwiftShader as on a machine without a GPU: the loader of each zone shows
    its published work state, and the decision launched by real clicks is seen on the model (the stopped zone's
    loader goes dark and carries «остановлен»); the camera follows the situation; no console errors at both sizes."""

    chrome_args = ("--use-angle=swiftshader", "--enable-unsafe-swiftshader")
    APP = "(await import('/js/main.js')).app"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock = MockServer("normal", extra_args=("--publication-ms", "300")).start()
        cls.addClassCleanup(cls.mock.stop)

    def tearDown(self):
        self.page.set_viewport(1280, 720)
        super().tearDown()

    def open(self, scenario, size):
        self.page.add_init_script("try { localStorage.removeItem('mine-ui.stage'); } catch (e) {}")
        # The loaders as the static symbols of the zones' work: a model without equipment twins (their loaders that move
        # by publications are tested in test_scene3d.EquipmentTest).
        self.page.add_init_script(STRIP_EQUIPMENT)
        self.page.set_viewport(*size)
        self.mock.scenario(scenario)
        self.page.goto("about:blank")
        self.page.goto(self.mock.url + "/")
        self.page.wait_for("document.body.dataset.boot === 'ready'", timeout=30)
        self.page.wait_for("(() => { const s = document.querySelector('#stage').dataset; return s.stageMode === '3d'"
                           " && Number(s.frames) > 0 && s.decor === 'loaded' && s.rendering === 'idle'; })()", timeout=40,
                           message="the 3D stage is drawn with its loaders")

    def js(self, body):
        return self.page.evaluate("(async () => {" + body + "})()", timeout=20)

    def loaders(self):
        return {entry["zone"]: entry for entry in self.js(f"return {self.APP}.ctx.stage.info().loaders;")}

    def idle(self, timeout=20):
        self.page.wait_for("document.querySelector('#stage').dataset.rendering === 'idle'", timeout=timeout)

    def free_right(self):
        """The right edge of the stage not covered by the panel, in viewport pixels."""
        return self.page.evaluate("""(() => {
          const box = document.getElementById('stage-3d').getBoundingClientRect();
          const r = document.getElementById('panel').getBoundingClientRect();
          return r.width > 0 && r.left < box.right - 1 ? r.left : box.right; })()""")

    def test_the_decision_launched_by_clicks_is_seen_on_the_model(self):
        for size in ((1920, 1080), (1280, 720)):
            with self.subTest(size=f"{size[0]}x{size[1]}"):
                self.open("danger_zone", size)
                self.page.wait_for("document.body.dataset.situation === 'decision' && document.body.dataset.panel === 'shown'", timeout=30)
                self.page.wait_for("document.querySelector('#stage').dataset.choreo === 'decision:zone-d'", timeout=10,
                                   message="the decision frames the incident zone")
                self.idle()
                before = self.loaders()
                self.assertEqual(sorted(before), ["zone-a", "zone-b", "zone-c", "zone-d"], "one loader per zone")
                self.assertTrue(all(entry["state"] == "working" and entry["light"] == 1 for entry in before.values()))
                self.page.click("#panel .dp-card[data-option-kind=stop_withdraw_zone]")
                self.page.click("[data-testid=btn-execute]")
                self.page.wait_for("document.querySelector('[data-testid=dialog]')", timeout=5)
                self.page.click("[data-testid=dialog-confirm]")
                self.page.wait_for("document.body.dataset.situation === 'executing'", timeout=15)
                self.page.wait_for(f"(async () => {{ const l = {self.APP}.ctx.stage.info().loaders.find((x) => x.zone === 'zone-d');"
                                   " return l.state === 'stopped' && l.light === 0; })()", timeout=10,
                                   message="the stopped zone's loader goes dark")
                self.page.wait_for("document.querySelector('#stage').dataset.choreo === 'executing:walk:zone-d'", timeout=10)
                self.idle()
                after = self.loaders()
                for zone in ("zone-a", "zone-b", "zone-c"):
                    self.assertEqual((after[zone]["state"], after[zone]["light"]), ("working", 1), f"{zone} keeps working")
                self.assertEqual({zone: entry["world"] for zone, entry in after.items()},
                                 {zone: entry["world"] for zone, entry in before.items()}, "no loader moves")
                # The sign of the stopped loader is on the free part of the stage, a button that selects the zone.
                sign = self.page.evaluate(f"""(() => {{ const n = document.querySelector('#stage-3d .s3-label--loader[data-zone="{NS}:zone-d"]');
                  if (!n || n.hasAttribute('data-culled')) return null; const r = n.getBoundingClientRect();
                  return {{text: n.textContent, right: r.right, left: r.left, tag: n.tagName}}; }})()""")
                self.assertIsNotNone(sign, "«остановлен» is shown on the model")
                self.assertEqual(sign["text"], "остановлен")
                self.assertLessEqual(sign["right"], self.free_right() + 0.5, "not under the panel")
                loader = self.js(f"return {self.APP}.ctx.stage.screenOf('loader:zone-d');")
                self.assertTrue(loader["visible"] and loader["x"] <= self.free_right(), f"the dark loader is in sight: {loader}")
                # The end: the overview.
                self.page.wait_for("document.body.dataset.situation === 'done'", timeout=60, interval=0.5)
                self.page.wait_for("document.querySelector('#stage').dataset.choreo === 'done:overview'", timeout=10)
                self.idle()
                self.assertTrue(self.js(f"return {self.APP}.ctx.stage.info().overview;"))
                self.assertEqual(list(self.page.console_errors), [], "no console errors")

    def test_every_situation_draws_without_console_errors_at_both_sizes(self):
        for size in ((1920, 1080), (1280, 720)):
            for scenario, situation in (("normal", "norm"), ("danger_zone", "decision"), ("sensor_lost_after_danger", None),
                                        ("commands", "norm")):
                with self.subTest(size=f"{size[0]}x{size[1]}", scenario=scenario):
                    self.open(scenario, size)
                    if situation:
                        self.page.wait_for(f"document.body.dataset.situation === '{situation}'", timeout=30)
                    time.sleep(0.8)
                    self.idle()
                    info = self.js(f"return {self.APP}.ctx.stage.info();")
                    self.assertEqual(len(info["loaders"]), 4)
                    self.assertLessEqual(info["triangles"], 60000)
                    self.assertLessEqual(info["calls"], 90)
                    published = self.js(f"""const s = {self.APP}.store.getState();
                      return Object.fromEntries(s.model.byKind.zone.map((z) => [z.name, z.values.work_state]));""")
                    for entry in info["loaders"]:
                        self.assertEqual(entry["state"], published[entry["zone"]], f"{entry['zone']}: the published work state")
                    self.assertEqual(list(self.page.console_errors), [])
