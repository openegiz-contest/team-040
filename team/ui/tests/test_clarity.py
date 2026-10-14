"""The clarity and interface-motion pass (clarity-motion spec, sections A, B and C), on the scheme mode of the stage.

    A1  «Действия диспетчера» follow the incident's zone; a choice of another zone is said   ActionsFollowIncidentTest
    A2  one primary decision path while the model waits for an option                       ActionsFollowIncidentTest
    A3  the table of options reads as an answer: header, row order, minutes, «да, за …»     VariantTableTest
    A6  a stand command in «Отправленные команды» is a condition, not a decision             SentCommandsTest
    A7  the people counters under «Люди»; unknown is never quieter than a zero               TopBarTest
    A9  colour roles: selection, primary action, copper, reset, journal gap                 ColourRolesTest
    C   the option pointed at lights the zones of its scope and their people                OptionHighlightTest
    B   motion: once per change, nothing on load, nothing over old data, instant
        under reduced motion, frames sampled                                                MotionTest, ReducedMotionTest
    A3/A8 the shared formatters: model clock and age, minutes, the «все вышли» cell       FormattersTest

The 3D side of these items (selection light, zone labels, camera) is test_scene3d.py and test_composition.py.

    python -m unittest discover -s team/ui/tests -t team/ui -p "test_clarity.py" -v
"""

from __future__ import annotations

import json
import time

from screenshots import close_working, settle, show_right, wait_decision

from .test_scenarios import ACTIONS, APP, DECISION, ScenarioTestCase, plain, thing

ZONE_SELECT = "#action-zone"
ACTION_BUTTONS = f'{ACTIONS} button[data-command-type^="action."]'
SELECTION = "rgb(242, 239, 233)"
ACTION = "rgb(174, 187, 199)"
INK0 = "rgb(17, 19, 22)"
COPPER = "rgb(200, 131, 79)"
UNKNOWN = "rgb(163, 167, 173)"

# Every Web Animation the page starts, from before its first script: when, on what, how long, with which frames.
RECORD = """
window.__motion = [];
const animate = Element.prototype.animate;
Element.prototype.animate = function (keyframes, options) {
  const animation = animate.call(this, keyframes, options);
  const holder = this.closest ? this.closest('[data-testid]') : null;
  window.__motion.push({t: performance.now(), cls: this.getAttribute('class') || '', id: this.id || '',
    testid: holder ? holder.dataset.testid : '', duration: options && options.duration,
    iterations: options && options.iterations, frames: JSON.stringify(keyframes), text: (this.textContent || '').trim().slice(0, 60)});
  return animation;
};
"""


def contrast(a, b):
    def lum(rgb):
        channels = [int(part) / 255 for part in rgb[rgb.index("(") + 1:rgb.index(")")].split(",")[:3]]
        channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    high, low = sorted((lum(a), lum(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class ClarityTestCase(ScenarioTestCase):
    def open_decision(self, scenario="danger_zone"):
        self.open(scenario)
        self.wait_drawn()
        self.wait_body(15.0, runState="paused")
        self.page.wait_for("!!document.querySelector('[data-testid=\"decision-options\"] th[data-state=\"offered\"]')", timeout=5.0)
        settle(self.page)

    def styles(self, selector, *names):
        return self.page.evaluate(f"""(() => {{
          const node = document.querySelector({json.dumps(selector)});
          if (!node) return null;
          const style = getComputedStyle(node);
          return Object.fromEntries({json.dumps(list(names))}.map((name) => [name, style.getPropertyValue(name)]));
        }})()""")

    def ui(self):
        return self.js(f"return {APP}.store.getState().ui;")


class ActionsFollowIncidentTest(ClarityTestCase):
    def test_the_zone_follows_the_incident_until_the_user_chooses(self):
        # No incident and no choice: an empty option, every button off with its reason.
        self.open("normal")
        self.wait_drawn()
        self.assertEqual(self.page.evaluate(f"document.querySelector('{ZONE_SELECT}').value"), "")
        self.assertEqual(self.page.evaluate(f"document.querySelector('{ZONE_SELECT}').options[0].textContent"), "— выберите участок —")
        for button in self.page.evaluate(f"[...document.querySelectorAll('{ACTION_BUTTONS}')].map((b) => [b.getAttribute('aria-disabled'),"
                                         " b.nextElementSibling.textContent])"):
            self.assertEqual(button, ["true", "Выберите участок"], "every switched-off button says why")

        # The incident opens: the actions are for its zone, without a press.
        self.open_decision()
        self.assertEqual(self.page.evaluate(f"document.querySelector('{ZONE_SELECT}').value"), "zone-d")
        self.assertEqual(self.attr(ACTIONS, "data-zone-from"), "incident")
        self.assertIsNone(self.text('[data-testid="actions-other-zone"]'))

        # Another zone chosen by the user: said above the buttons, and it stays through the polls.
        self.page.evaluate(f"(() => {{ const s = document.querySelector('{ZONE_SELECT}'); s.value = 'zone-a';"
                           " s.dispatchEvent(new Event('change')); })()")
        self.assertEqual(self.text('[data-testid="actions-other-zone"]'), "Инцидент: Участок Г. Выбран другой участок: Участок А")
        self.wait_seq(2)
        self.assertEqual(self.page.evaluate(f"document.querySelector('{ZONE_SELECT}').value"), "zone-a")
        self.assertEqual(self.attr(ACTIONS, "data-zone-from"), "choice")

        # Step 1 «показать» selects the incident's zone: the card and the actions follow it.
        self.page.click('[data-testid="situation-show-1"]')
        self.page.wait_for(f"location.hash.includes('sel={thing('zone-d')}')", timeout=2.0)
        self.assertEqual(self.text('[data-testid="card"] .card__code'), "Участок Г")
        self.assertEqual(self.page.evaluate(f"document.querySelector('{ZONE_SELECT}').value"), "zone-d")
        self.assertIsNone(self.text('[data-testid="actions-other-zone"]'))
        self.assertFalse(self.commands_logged(), "following and selecting send nothing")

    def test_one_primary_decision_path_while_the_model_waits(self):
        self.open_decision()
        filled = f"""[...document.querySelectorAll('button')].filter((b) => b.getClientRects().length > 0
          && getComputedStyle(b).backgroundColor === '{ACTION}').map((b) => b.dataset.testid || b.dataset.commandType)"""
        # The zone actions are secondary, with the note that says where the decision is.
        classes = self.page.evaluate(f"[...document.querySelectorAll('{ACTION_BUTTONS}')].map((b) => b.className)")
        self.assertTrue(classes and all("btn--secondary" in name for name in classes), classes)
        self.assertEqual(self.text('[data-testid="actions-waits"]'),
                         "Модель ждёт выбора варианта — см. «Варианты решения». Здесь — отдельные команды по участку")
        self.assertEqual(self.page.evaluate(filled), [], "nothing is filled before an option is chosen")
        show_right(self.page, "decision")
        self.page.click(f'{DECISION} th[data-column="option-withdraw-all"] input')
        self.page.wait_for("document.querySelector('[data-testid=\"btn-execute\"]').getAttribute('aria-disabled') === null", timeout=2.0)
        self.page.evaluate("document.getAnimations().forEach((animation) => animation.finish())")    # the 120 ms colour change of a button
        self.assertEqual(self.page.evaluate(filled), ["btn-execute"], "«Запустить вариант…» is the only filled primary button")
        style = self.styles('[data-testid="btn-execute"]', "background-color", "color")
        self.assertEqual((style["background-color"], style["color"]), (ACTION, INK0))
        self.assertGreaterEqual(contrast(style["background-color"], style["color"]), 4.5)


class VariantTableTest(ClarityTestCase):
    def test_the_table_reads_as_an_answer(self):
        self.open_decision()
        show_right(self.page, "decision")
        self.assertEqual(self.text(f'{DECISION} [data-testid="decision-caption"] li > span'),
                         "Прогноз модели на 15 мин · рассчитан в 00:21:00")
        self.assertIn("тик расчёта 1260", self.attr(f'{DECISION} [data-testid="decision-caption"] li', "title"))
        self.assertEqual(self.text('[data-testid="decision-advice"]'), "Модель не рекомендует вариант — сравните и выберите")
        rows = self.texts(f'{DECISION} [data-testid="decision-options"] tbody tr > th')
        self.assertEqual(rows, ["участки", "в опасных зонах на конец расчёта", "все вышли", "вышло", "без расчётного маршрута",
                                "пребывание в опасных зонах", "пребывание в зонах с неизвестным состоянием",
                                "суммарный простой участков", "люди через 15 мин"])
        cell = lambda option, metric: self.text(f'{DECISION} td[data-option="{option}"][data-metric="forecast_{metric}"]')  # noqa: E731
        self.assertEqual([cell(option, "all_out") for option in ("option-observe", "option-stop-withdraw", "option-withdraw-all")],
                         ["нет", "нет", "да, за 9 мин 40 с"])
        self.assertEqual(self.count(f'{DECISION} td[data-metric="forecast_last_out_s"]'), 0, "the time is part of «все вышли»")
        self.assertEqual(cell("option-observe", "danger_exposure_person_s"), "45 чел.·мин")
        self.assertEqual(cell("option-observe", "unknown_exposure_person_s"), "30 чел.·мин")
        self.assertEqual(cell("option-withdraw-all", "downtime_s"), "38,7 уч.·мин")
        title = self.attr(f'{DECISION} td[data-option="option-observe"][data-metric="forecast_danger_exposure_person_s"] span', "title")
        self.assertEqual(plain(title), "2700 чел.·с, опубликовано в человеко-секундах", "the published value stays in the title")
        self.assertNotIn("нет: не все вышли", self.words(DECISION))
        self.assertEqual(self.attr(f'{DECISION} [data-testid="decision-options"] tbody tr:last-child', "data-row"), "people")

    def test_no_invented_group_size(self):
        self.open("no_path")
        self.wait_drawn()
        close_working(self.page, "w-07")
        wait_decision(self.page)
        show_right(self.page, "decision")
        words = self.texts(f'{DECISION} [data-testid="decision-options"] .pb-words')
        self.assertEqual(words[0], "вышли 0 · для 2 чел. выход не рассчитан")
        self.assertTrue(all(" из " not in item and "?" not in item for item in words), words)


class SentCommandsTest(ClarityTestCase):
    def test_a_stand_condition_is_not_a_dispatcher_command(self):
        self.open("detour")
        self.wait_drawn()
        close_working(self.page, "w-12")
        wait_decision(self.page)
        stand = self.page.evaluate("""(() => {
          const node = document.querySelector('[data-testid="pending"][data-command-type="condition.close_working"]');
          return {origin: node.dataset.origin, tag: node.querySelector('[data-testid="pending-stand-tag"]').textContent,
                  tagStyle: getComputedStyle(node.querySelector('[data-testid="pending-stand-tag"]')).borderTopStyle,
                  what: node.querySelector('.pending__what').textContent};
        })()""")
        self.assertEqual(stand, {"origin": "stand", "tag": "стенд", "tagStyle": "dashed", "what": "Условие стенда: В-12 закрыта"})
        self.page.click(f'{ACTIONS} button[data-command-type="action.stop_zone"]')
        self.wait_for_selector('[data-testid="pending"][data-command-type="action.stop_zone"]')
        dispatcher = self.page.evaluate("""(() => {
          const node = document.querySelector('[data-testid="pending"][data-command-type="action.stop_zone"]');
          return {origin: node.dataset.origin, tags: node.querySelectorAll('[data-testid="pending-stand-tag"]').length,
                  what: node.querySelector('.pending__what').textContent};
        })()""")
        self.assertEqual(dispatcher, {"origin": "dispatcher", "tags": 0, "what": "Остановить участок: Участок Б"})


class TopBarTest(ClarityTestCase):
    def test_people_under_one_caption_and_unknown_at_full_weight(self):
        self.open_decision()
        self.assertEqual(self.text("#statusbar .topbar__people-cap"), "Люди")
        self.assertEqual(self.words("#statusbar .topbar__people-row"),
                         "всего 14 вышли 0 в опасных зонах 3 без расчётного маршрута 0 состояние неизвестно 2")
        self.assertEqual(plain(self.page.evaluate("document.querySelector('[data-testid=\"status-run\"]').textContent")), "Прогон run-0005")
        self.assertEqual(self.attr('[data-testid="status-run"]', "title"), "Прогон run-0005; seed 42")
        unknown = self.styles('[data-figure="unknown"] .figure__value', "font-weight", "color", "font-style")
        zero = self.styles('[data-figure="no-route"] .figure__value', "font-weight", "color")
        frame = self.styles('[data-figure="unknown"] .figure__slot', "border-top-style", "border-top-color")
        self.assertGreaterEqual(int(unknown["font-weight"]), 600)
        self.assertGreaterEqual(int(unknown["font-weight"]), int(zero["font-weight"]), "never quieter than a zero")
        self.assertEqual(unknown["font-style"], "normal")
        self.assertGreaterEqual(contrast(unknown["color"], INK0), contrast(zero["color"], INK0) - 0.01)
        self.assertEqual((frame["border-top-style"], frame["border-top-color"]), ("dashed", UNKNOWN))
        self.assertTrue(self.page.evaluate("getComputedStyle(document.querySelector('[data-figure=\"unknown\"] .figure__sign')).display !== 'none'"),
                        "with its «?»")


class ColourRolesTest(ClarityTestCase):
    def test_selection_primary_copper_and_reset_roles(self):
        self.page.set_viewport(1920, 1080)
        self.open_decision()
        # Selection: a chalk-white double outline on the scheme (worker, zone tag) and in the list.
        self.js(f"{APP}.ctx.select('{thing('worker-11')}');")
        inner = self.styles(f'{self.scheme("worker-11")} .worker__hit', "stroke")
        outer = self.styles(f'{self.scheme("worker-11")} > .obj__sel', "stroke", "display")
        self.assertEqual((inner["stroke"], outer["stroke"], outer["display"]), (SELECTION, SELECTION, "inline"))
        self.js(f"{APP}.ctx.select('{thing('zone-d')}');")
        self.assertEqual(self.styles(f'{self.scheme("zone-d")} .tag__box', "stroke")["stroke"], SELECTION)
        self.assertEqual(self.styles(f'{self.scheme("zone-d")} > .tag__sel', "stroke", "display"), {"stroke": SELECTION, "display": "inline"})
        self.show("list")
        row = self.styles(self.row("zone-d"), "outline-color", "outline-style")
        self.assertEqual((row["outline-color"], row["outline-style"]), (SELECTION, "double"))
        self.show("scheme")

        # Copper: only the brand mark (and the active tab underline and the focus ring, not scanned here as colours).
        show_right(self.page, "decision")
        self.page.click(f'{DECISION} th[data-column="option-observe"] input')
        self.page.evaluate("document.activeElement && document.activeElement.blur()")
        coppered = self.page.evaluate(f"""(() => {{
          const props = ['color', 'background-color', 'border-top-color', 'border-left-color', 'border-right-color',
                         'border-bottom-color', 'stroke', 'fill'];
          const out = [];
          for (const root of ['#statusbar', '#situation', '#centre', '#right', '#stand-drawer']) {{
            for (const node of document.querySelector(root).querySelectorAll('*')) {{
              if (node.closest('#stage-3d, #stage-hud')) continue;
              const style = getComputedStyle(node);
              if (style.display === 'none') continue;
              const hit = props.filter((name) => {{
                if (!style.getPropertyValue(name).includes('{COPPER}')) return false;
                return !name.startsWith('border') || style.getPropertyValue(name.replace('color', 'width')) !== '0px';
              }});
              if (hit.length > 0) out.push((node.getAttribute('class') || node.tagName) + ': ' + hit.join(','));
            }}
          }}
          return out;
        }})()""")
        self.assertEqual(sorted(set(coppered)), ["mark__slab: stroke"], "copper marks only the brand")
        self.assertEqual(self.styles('[data-testid="tab-scheme"]', "text-decoration-color")["text-decoration-color"], COPPER)
        self.page.evaluate("document.querySelector('[data-testid=\"tab-list\"]').focus()")
        self.page.press("Tab")
        focused = self.page.evaluate("getComputedStyle(document.activeElement).outlineColor")
        self.assertEqual(focused, COPPER, "the keyboard focus ring is copper")

        # Reset: a neutral outline; red stays hazard-only.
        reset = self.styles('[data-testid="btn-reset"]', "border-top-color", "background-color")
        self.assertNotIn(reset["border-top-color"], ("rgb(224, 72, 58)", "rgb(240, 122, 110)"))
        self.assertEqual(reset["background-color"], "rgba(0, 0, 0, 0)")

    def test_the_journal_gap_is_unknown_grey(self):
        self.open("sensor_lost_after_danger")
        self.wait_drawn()
        self.wait_for_selector('[data-testid="journal-gap"]')
        self.page.click('[data-testid="journal-toggle"]')
        gap = self.styles('[data-testid="journal-gap"]', "border-top-style", "border-top-color", "color")
        self.assertEqual((gap["border-top-style"], gap["border-top-color"]), ("dashed", UNKNOWN))
        self.assertNotIn(gap["color"], ("rgb(226, 164, 59)",), "not the amber of attention")


class OptionHighlightTest(ClarityTestCase):
    SCOPE = """(() => ({
      zones: [...document.querySelectorAll('#scheme .halo.is-in-scope')].length,
      zoneIds: [...document.querySelectorAll('#scheme [data-thing-id][data-kind="zone"]')]
        .filter((node) => document.querySelector('#scheme .halo.is-in-scope') !== null).length,
      workers: [...document.querySelectorAll('#scheme .worker.is-in-scope')].map((node) => node.dataset.thingId).sort(),
    }))()"""

    def hover(self, option):
        self.page.evaluate(f"""document.querySelector('{DECISION} th[data-column="{option}"]')
          .dispatchEvent(new MouseEvent('mouseover', {{bubbles: true}}))""")

    def leave(self):
        self.page.evaluate(f"document.querySelector('{DECISION} [data-testid=\"decision-options\"]').dispatchEvent(new MouseEvent('mouseleave'))")

    def test_pointing_at_an_option_lights_its_zones_and_their_people(self):
        self.open_decision()
        show_right(self.page, "decision")
        self.assertIsNone(self.ui()["hoverOption"])
        self.hover("option-stop-withdraw")
        self.assertEqual(self.ui()["hoverOption"], thing("option-stop-withdraw"))
        self.page.wait_for("document.querySelectorAll('#scheme .halo.is-in-scope').length === 1", timeout=2.0)
        lit = self.page.evaluate(self.SCOPE)
        self.assertEqual(lit["workers"], [thing("worker-11"), thing("worker-12"), thing("worker-13")],
                         "the people now in Участок Г, by their published positions")
        scope = self.styles('#scheme .halo.is-in-scope .halo__scope', "stroke", "transition-duration")
        self.assertEqual((scope["stroke"], scope["transition-duration"]), (ACTION, "0.15s"))
        time.sleep(0.3)
        self.assertEqual(self.styles('#scheme .halo.is-in-scope .halo__scope', "stroke-opacity")["stroke-opacity"], "1")
        # Withdraw all: every zone.
        self.hover("option-withdraw-all")
        self.page.wait_for("document.querySelectorAll('#scheme .halo.is-in-scope').length === 4", timeout=2.0)
        self.leave()
        self.page.wait_for("document.querySelectorAll('#scheme .is-in-scope').length === 0", timeout=2.0)
        self.assertIsNone(self.ui()["hoverOption"])
        # The keyboard: focus on the radio button of a column names its option too.
        self.page.evaluate(f"document.querySelector('{DECISION} th[data-column=\"option-observe\"] input').focus()")
        self.assertEqual(self.ui()["hoverOption"], thing("option-observe"))
        self.page.evaluate("document.activeElement.blur()")
        self.assertIsNone(self.ui()["hoverOption"])
        # A chosen option keeps its light after the pointer leaves.
        self.page.click(f'{DECISION} th[data-column="option-stop-withdraw"] input')
        self.leave()
        self.assertEqual(self.ui()["hoverOption"], thing("option-stop-withdraw"))
        self.assertEqual(len(self.page.evaluate(self.SCOPE)["workers"]), 3)
        self.assertFalse(self.commands_logged(), "pointing sends nothing")


class MotionTest(ClarityTestCase):
    def motion(self):
        return self.page.evaluate("window.__motion")

    def test_the_incident_moves_once_and_nothing_moves_on_load(self):
        self.page.add_init_script(RECORD)
        self.open("danger_zone")
        self.wait_drawn()
        self.assertEqual(self.text('[data-testid="incident-in-danger"]'), "0")
        self.wait_seq(1)
        self.assertEqual(self.motion(), [], "nothing moves on load")
        # The danger arrives: sample the crossfade of the counter while it runs, then its end.
        self.page.wait_for("!!document.querySelector('[data-figure=\"in-danger\"] .figure__ghost')", timeout=15.0, interval=0.02)
        early = self.page.evaluate("""(() => {
          const ghost = document.querySelector('[data-figure="in-danger"] .figure__ghost');
          return {old: ghost.textContent, now: document.querySelector('[data-testid="incident-in-danger"]').textContent,
                  ghost: Number(getComputedStyle(ghost).opacity), value: Number(getComputedStyle(document.querySelector('[data-testid="incident-in-danger"]')).opacity)};
        })()""")
        self.assertEqual((early["old"], early["now"]), ("0", "3"), "only the old and the new published numbers, nothing between")
        self.assertGreater(early["ghost"], 0.0)
        self.assertLess(early["value"], 1.0)
        time.sleep(0.35)
        late = self.page.evaluate("""(() => ({ghosts: document.querySelectorAll('.figure__ghost').length,
          value: Number(getComputedStyle(document.querySelector('[data-testid="incident-in-danger"]')).opacity),
          mark: Number(getComputedStyle(document.querySelector('[data-figure="in-danger"] .figure__mark')).opacity)}))()""")
        self.assertEqual(late["ghosts"], 0, "the old number is gone")
        self.assertEqual(late["value"], 1.0)
        self.assertGreater(late["mark"], 0.0, "the underline still fades")
        time.sleep(1.0)
        self.assertEqual(self.page.evaluate("document.getAnimations().length"), 0, "everything has ended")
        self.assertEqual(self.styles('[data-figure="in-danger"] .figure__mark', "opacity")["opacity"], "0")

        records = self.motion()
        by = lambda **match: [r for r in records if all(r.get(k) == v for k, v in match.items())]  # noqa: E731
        self.assertTrue(all(r["iterations"] == 1 for r in records), "nothing loops")
        for figure in ("in-danger", "unknown"):
            self.assertEqual(len([r for r in records if r["cls"] == "figure__ghost" and r["duration"] == 200]), 2)
            self.assertEqual(len(by(testid=f"incident-{figure}", duration=200)), 1, figure)
        self.assertEqual(len(by(cls="figure__mark", duration=1000)), 2, "one underline per changed counter")
        self.assertEqual(len(by(id="situation", duration=180)), 1, "the strip unfolds once")
        self.assertEqual(sorted(r["text"].split(":")[0] for r in by(duration=450)), ["Участок В", "Участок Г"],
                         "the zones whose hazard changed flash once in the summary")
        count = len(records)
        self.wait_seq(3)
        self.assertEqual(len(self.motion()), count, "a repeated publication moves nothing")
        self.assertEqual(self.page.evaluate("document.getAnimations().length"), 0)

    def test_dock_card_and_drawer(self):
        self.page.set_viewport(1920, 1080)
        self.page.add_init_script(RECORD)
        self.open_decision("paused_heartbeat")
        self.assertEqual(self.body()["dock"], "open")
        self.wait_seq(1)
        self.assertEqual(self.motion(), [])
        # The dock folds over 200 ms: sampled at about 0, 100 and 300 ms.
        height = "(() => { const n = document.getElementById('decision'); return n.getClientRects().length ? n.getBoundingClientRect().height : 0; })()"
        start = self.page.evaluate(height)
        self.page.click('[data-testid="dock-toggle"]')
        samples = []
        for _ in range(3):
            samples.append(self.page.evaluate(height))
            time.sleep(0.1)
        time.sleep(0.15)
        self.assertEqual(self.body()["dock"], "collapsed")
        self.assertEqual(self.page.evaluate(height), 0, "folded at the end")
        self.assertIsNone(self.attr('#decision-dock', "data-folding"))
        self.assertTrue(any(0 < value < start for value in samples), f"it folded over several frames: {start} -> {samples}")
        self.page.click('[data-testid="dock-toggle"]')
        time.sleep(0.4)
        self.assertGreater(self.page.evaluate(height), start * 0.9, "unfolded again")
        self.assertEqual([r["duration"] for r in self.motion() if r["id"] == "decision"], [200, 200])

        # «Подробнее» of the card: 180 ms of height and fade, both ways.
        self.page.click('[data-testid="card-more"]')
        time.sleep(0.3)
        self.page.click('[data-testid="card-more"]')
        time.sleep(0.3)
        self.assertTrue(self.page.evaluate("document.getElementById('card-fields').hidden"))
        disclosure = [r for r in self.motion() if r["testid"] == "card-fields"]
        self.assertEqual([r["duration"] for r in disclosure], [180, 180])
        self.assertIn("opacity", disclosure[0]["frames"])
        # The stand drawer slides in 200 ms (a transition of the stylesheet).
        self.assertIn("0.2s", self.styles("#stand-drawer", "transition-duration")["transition-duration"])
        self.assertEqual(self.page.evaluate("document.getAnimations().length"), 0)

    def test_nothing_moves_over_old_data(self):
        self.page.add_init_script(RECORD)
        self.open_decision("paused_heartbeat")
        self.mock.fault("http_502")
        try:
            self.wait_body(10.0, link="stale")
            self.page.click('[data-testid="dock-toggle"]')
            self.page.click('[data-testid="card-more"]')
            time.sleep(0.2)
            self.assertEqual(self.motion(), [], "old data: every change is at once")
            self.assertEqual(self.styles("#stand-drawer", "transition-duration")["transition-duration"], "0s")
            allowed = self.js("""const m = await import('/js/motion.js');
              const s = (await import('/js/main.js')).app.store.getState();
              return [m.motionAllowed(s), m.motionAllowed({...s, link: {...s.link, link: 'ok', snapshot: 'ok', publications: 'alive'}})];""")
            self.assertEqual(allowed, [False, True])
        finally:
            self.mock.fault("none")


class ReducedMotionTest(ClarityTestCase):
    def setUp(self):
        super().setUp()
        self.page.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})

    def test_every_change_is_instant(self):
        self.page.add_init_script(RECORD)
        self.open("danger_zone")
        self.wait_drawn()
        self.wait_body(15.0, runState="paused")
        self.assertEqual(self.text('[data-testid="incident-in-danger"]'), "3")
        self.assertEqual(self.count(".figure__ghost"), 0)
        self.page.click('[data-testid="dock-toggle"]')
        self.page.click('[data-testid="card-more"]')
        self.assertEqual(self.page.evaluate("window.__motion"), [], "no Web Animation is started")
        self.assertEqual(self.page.evaluate("document.getAnimations().length"), 0)
        for selector in ("#stand-drawer", "#scheme .halo .halo__scope"):
            self.assertEqual(self.styles(selector, "transition-duration")["transition-duration"], "0s", selector)


class FormattersTest(ClarityTestCase):
    def test_time_minutes_and_the_everyone_out_row(self):
        """The formatters of text.js the panels and the 3D labels share (A3, A8), and the cell of «все вышли»."""
        self.open("normal")
        got = self.js("""
          const T = await import('/js/text.js');
          const D = await import('/js/view/decision.js');
          const twin = (values, units = {}) => ({values, units});
          return {
            ago: [T.agoText(810, 810), T.agoText(810, 850), T.agoText(810, 1230), T.agoText(810, 4810), T.agoText(810, 800), T.agoText(810)],
            clock: [T.clockAgo(810, 1230), T.clockAgoLine(810, 1230), T.atClockAgo(810, 1230), T.clockAgo(810)],
            last: [T.lastKnownText({last_known_hazard_state: 'danger', last_known_hazard_tick: 810}, 1230),
                   T.lastKnownText({last_known_hazard_state: 'danger'}, 1230), T.lastKnownText({}, 1230)],
            minutes: [T.perMinute(2700, 'person*s'), T.perMinute(2320, 'zone*s'), T.perMinute(5, 'mm'), T.perMinute(undefined, 'person*s')],
            cells: [D.decisionCell(T, twin({forecast_all_out: true, forecast_last_out_s: 580}), 'forecast_', 'all_out').text,
                    D.decisionCell(T, twin({forecast_all_out: true}), 'forecast_', 'all_out').text,
                    D.decisionCell(T, twin({forecast_all_out: false, forecast_last_out_s: 580}), 'forecast_', 'all_out').text,
                    D.decisionCell(T, twin({forecast_all_out: 'maybe'}), 'forecast_', 'all_out').text,
                    D.decisionCell(T, twin({}), 'forecast_', 'all_out').text],
            rows: D.DECISION_ROWS,
          };""")
        nb = lambda value: plain(value) if isinstance(value, str) else value  # noqa: E731
        self.assertEqual([nb(item) for item in got["ago"]], ["сейчас", "40 с назад", "7 мин назад", "1 ч 6 мин назад", "", ""])
        self.assertEqual([nb(item) for item in got["clock"]],
                         ["00:13:30 (7 мин назад)", "00:13:30 · 7 мин назад", "в 00:13:30, 7 мин назад", "00:13:30"])
        self.assertEqual([nb(item) for item in got["last"]],
                         ["последнее известное: опасно в 00:13:30 (7 мин назад)", "последнее известное: опасно", ""])
        self.assertEqual([nb(item["text"]) for item in got["minutes"]], ["45 чел.·мин", "38,7 уч.·мин", "5 мм", "—"])
        self.assertEqual(nb(got["minutes"][0]["title"]), "2700 чел.·с, опубликовано в человеко-секундах")
        self.assertEqual([nb(item) for item in got["cells"]], ["да, за 9 мин 40 с", "да", "нет", "неизвестно (maybe)", "—"],
                         "a time only next to a published all_out = true; never «нет: не все вышли»")
        self.assertEqual(got["rows"], ["in_danger", "all_out", "out", "no_route", "danger_exposure_person_s",
                                       "unknown_exposure_person_s", "downtime_s"])
