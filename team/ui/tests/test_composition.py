"""The composition of the redesigned screen around the stage, in 3D (SwiftShader) and in the scheme mode.

    situation strip: «показать» moves the camera in 3D, selects in the scheme   SituationStripTest
    stand drawer: opens, closes, gives the focus back, its controls apart       StandDrawerTest
    top bar: the counters the model published, nothing counted by the page      TopBarTest
    decision dock: opens and folds; only with an incident                      DockTest
    no page scroll, no horizontal scroll: both sizes, both modes               PageScrollTest
    keyboard in 3D: Tab to the canvas and the labels, camera keys, Enter, Esc  Keyboard3dTest
    reduced motion: no tween frames, camera and selection change at once       ReducedMotion3dTest
    no WebGL: the scheme with a calm notice, and its controls work             NoWebglTest

The checklist items themselves in 3D are Checklist3dTest in test_scenarios.py; the same items on the
no-WebGL path are the *NoWebglTest classes there. The 3D stage module itself is test_scene3d.py.

    python -m unittest discover -s team/ui/tests -t team/ui -p "test_composition.py" -v
"""

from __future__ import annotations

import json
import time

from screenshots import REWRITE_SHIFT, close_working, set_stand, show_right, wait_decision

from .test_scenarios import APP, DECISION, PROBE, Stage3dScenarioCase, ScenarioTestCase, plain, thing

SIZES = ((1280, 720), (1920, 1080))
CHALK = ("btn--stand", "btn--danger")

# Where an object is drawn relative to the stage: the share of the stage's width and height from its top left corner.
WHERE = """(async (id) => {
  const point = (await import('/js/main.js')).app.ctx.stage.screenOf(id);
  const stage = document.getElementById('stage-3d').getBoundingClientRect();
  return point && {visible: point.visible, x: (point.x - stage.left) / stage.width, y: (point.y - stage.top) / stage.height};
})"""


class SituationStripTest(Stage3dScenarioCase):
    def where(self, name):
        return self.page.evaluate(f"{WHERE}({json.dumps(thing(name))})")

    def test_show_steps_move_the_camera_in_3d(self):
        """Every «показать» of the strip glides the camera to its object, and selects nothing; «к вариантам» opens the dock."""
        self.open3d("sensor_lost_after_danger")
        self.assertEqual(self.attr('[data-testid="incident-strip"]', "data-open"), "true")
        # The incident of this story: causes `hazard` of Участок В (tick 700) and `data_lost` of Э-05; every step points at the zone.
        far = self.where("zone-c")
        for step, target in ((1, "zone-c"), (2, "zone-c"), (3, "zone-c")):
            with self.subTest(step=step):
                self.page.click('[data-testid="stage-overview"]')
                overview = self.wait_idle()["camera"]
                frames = int(self.stage()["frames"])
                self.assertTrue(self.visible(f'[data-testid="situation-show-{step}"]'))
                self.page.click(f'[data-testid="situation-show-{step}"]')
                self.page.wait_for("document.querySelector('#stage').dataset.rendering === 'active'", timeout=2.0,
                                   message="the camera starts to move")
                stage = self.wait_idle()
                self.assertNotEqual(stage["camera"], overview, "the camera moved")
                self.assertGreaterEqual(int(stage["frames"]) - frames, 5, "it glided over several frames")
                distance = [float(value) for value in stage["camera"].split()][2]
                self.assertLess(distance, [float(value) for value in overview.split()][2] * 0.6, "and came closer")
                where = self.where(target)
                self.assertTrue(where["visible"])
                self.assertTrue(0.05 <= where["x"] <= 0.95 and 0.05 <= where["y"] <= 0.95,
                                f"{target} is brought into the stage: {where}")
                self.assertIsNone(self.js(f"return {APP}.store.getState().ui.selected;"), "showing is not selecting")
        self.assertNotEqual(far, self.where("zone-c"))
        # Step 4 unfolds the dock with the options and puts the focus on its toggle.
        self.page.click('[data-testid="situation-show-4"]')
        self.page.wait_for("document.body.dataset.dock === 'open'", timeout=2.0)
        self.assertEqual(self.page.focus_info()["testid"], "dock-toggle")
        self.assertTrue(self.visible("#decision"))

    def test_show_steps_select_in_the_scheme_mode(self):
        """In the scheme mode the stage cannot glide: «показать» selects the object, and the scheme and the card show it."""
        self.open("sensor_lost_after_danger", "#/scheme?mode=scheme")
        self.wait_drawn()
        self.page.wait_for("document.querySelector('[data-testid=\"incident-strip\"]').dataset.open === 'true'", timeout=4.0)
        for step, target, code in ((1, "zone-c", "Участок В"), (2, "zone-c", "Участок В"), (3, "zone-c", "Участок В")):
            with self.subTest(step=step):
                self.js(f"{APP}.ctx.select(null);")
                self.page.wait_for("!location.hash.includes('sel=')", timeout=2.0)
                self.page.click(f'[data-testid="situation-show-{step}"]')
                self.page.wait_for(f"location.hash.includes('sel={thing(target)}')", timeout=2.0, message=f"{target} is selected")
                self.assertIn("mode=scheme", self.page.evaluate("location.hash"), "the stage stays in its scheme mode")
                self.assertEqual(self.text('[data-testid="card"] .card__code'), code)
                self.assertRegex(self.attr(self.scheme(target), "class"), r"\b(is-selected|tag--selected)\b", "the scheme marks it")


class StandDrawerTest(Stage3dScenarioCase):
    def drawer(self):
        return self.page.evaluate("""(() => {
          const drawer = document.getElementById('stand-drawer');
          const box = drawer.getBoundingClientRect();
          const stage = document.getElementById('stage').getBoundingClientRect();
          return {open: drawer.dataset.open, inert: drawer.inert, visibility: getComputedStyle(drawer).visibility,
                  left: box.left - stage.left, width: box.width, top: box.top - stage.top,
                  stage: [Math.round(stage.width), Math.round(stage.height)],
                  expanded: document.querySelector('[data-testid="stand-toggle"]').getAttribute('aria-expanded')};
        })()""")

    def test_drawer_opens_closes_gives_the_focus_back_and_keeps_its_controls_apart(self):
        self.open3d("detour")
        closed = self.drawer()
        self.assertEqual((closed["open"], closed["inert"], closed["visibility"], closed["expanded"]), ("false", True, "hidden", "false"),
                         "closed by default, and out of the Tab order")

        # Open from the keyboard: the focus goes into the drawer; the stage keeps its size under it.
        self.page.evaluate("document.querySelector('[data-testid=\"stand-toggle\"]').focus()")
        self.page.press("Enter")
        self.page.wait_for("document.body.dataset.stand === 'open'", timeout=2.0)
        opened = self.drawer()
        self.assertEqual((opened["open"], opened["inert"], opened["visibility"], opened["expanded"]), ("true", False, "visible", "true"))
        self.assertEqual(self.page.focus_info()["testid"], "stand-close", "the focus moves into the drawer")
        self.assertEqual(opened["stage"], closed["stage"], "the drawer lies over the stage; the stage does not shrink")
        self.assertTrue(opened["left"] <= 1 and opened["left"] + opened["width"] < opened["stage"][0] / 2 and opened["width"] <= 360,
                        f"over the left edge of the stage: {opened}")
        title = plain(self.page.evaluate("document.getElementById('stand-title').textContent"))
        self.assertEqual(title, "стенд Управление стендом")
        self.assertEqual(self.text("#stand-drawer .stand__subtitle"), "условия эксперимента, не действия диспетчера")

        # Two families of buttons that are never confused: chalk mark-up in the drawer, copper in «Действия диспетчера».
        families = self.page.evaluate("""(() => {
          const of = (root) => [...root.querySelectorAll('button[data-command-type]')].map((button) => [
            button.dataset.commandType, [...button.classList].filter((name) => name.startsWith('btn--')).join(' ')]);
          return {drawer: of(document.getElementById('stand-drawer')), right: of(document.getElementById('right')),
                  actionsTitle: document.querySelector('#actions .panel__title').textContent};
        })()""")
        self.assertTrue(families["drawer"] and families["right"])
        for command, classes in families["drawer"]:
            self.assertTrue(command.startswith(("condition.", "run.")), f"only stand controls in the drawer: {command}")
            self.assertTrue(any(name in classes.split() for name in CHALK), f"{command}: {classes}")
            self.assertNotIn("btn--dispatch", classes)
        for command, classes in families["right"]:
            if command.startswith("action."):
                self.assertIn("btn--dispatch", classes.split(), f"{command}: {classes}")
            self.assertFalse(command.startswith(("condition.", "run.")), f"no stand control in the right column: {command}")
        self.assertEqual(plain(families["actionsTitle"]), "Действия диспетчера")

        # A poll keeps it open; Esc closes it and gives the focus back to the button.
        self.wait_seq(2)
        self.assertEqual(self.body()["stand"], "open")
        self.page.press("Escape")
        self.page.wait_for("document.body.dataset.stand === 'closed'", timeout=2.0)
        self.assertEqual(self.page.focus_info()["testid"], "stand-toggle")
        self.assertTrue(self.drawer()["inert"])

        # A condition set in the drawer stays in sight as a chalk tag of the top bar when the drawer is closed.
        close_working(self.page, "w-12")
        wait_decision(self.page)
        self.assertEqual(self.body()["stand"], "closed")
        self.assertEqual(self.text('[data-testid="status-conditions"]'), "Условия стенда: В-12 закрыта")
        self.assertTrue(self.visible('[data-testid="status-conditions"] .chip'))
        # «Закрыть» closes it too, and the focus goes back to the button.
        set_stand(self.page)
        self.page.click('[data-testid="stand-close"]')
        self.page.wait_for("document.body.dataset.stand === 'closed'", timeout=2.0)
        self.assertEqual(self.page.focus_info()["testid"], "stand-toggle")


class TopBarTest(Stage3dScenarioCase):
    def test_the_people_figures_are_the_published_counters(self):
        """The top bar shows the counters of `shift` as published, even when the per-worker fields would count otherwise."""
        self.page.add_init_script(REWRITE_SHIFT)
        self.open3d("normal")
        figures = self.page.evaluate("[...document.querySelectorAll('#statusbar .topbar__people [data-figure]')].map((node) => node.dataset.figure)")
        self.assertEqual(figures, ["total", "out", "in-danger", "no-route", "unknown"], "the five counters of the model, nothing else")
        self.assertEqual(self.counters(), {"in-danger": "0", "no-route": "0", "unknown": "0", "out": "0", "total": "14"})
        people = lambda: {thing_id: (item["locationHazard"], item["egress"], item["status"])  # noqa: E731
                          for thing_id, item in self.labels().items() if item["kind"] == "worker"}
        before = people()
        self.assertNotIn("danger", {value[0] for value in before.values()})
        # The published counters change; no worker's own fields do.
        self.page.evaluate("window.__patch = " + json.dumps({"shift": {
            "workers_total": 21, "workers_out": 2, "workers_in_danger": 7, "workers_no_route": 5, "workers_unknown": 4}}))
        self.page.wait_for("document.querySelector('[data-testid=\"incident-in-danger\"]').textContent === '7'", timeout=5.0)
        self.assertEqual(self.counters(), {"in-danger": "7", "no-route": "5", "unknown": "4", "out": "2", "total": "21"})
        self.assertEqual(self.body()["snapshot"], "ok")
        self.assertEqual(people(), before,
                         "the people on the model keep their own published state: the bar is not counted from them, nor they from it")
        signs = self.page.evaluate("[...document.querySelectorAll('#statusbar .figure__sign')].map((node) => node.getAttribute('class'))")
        self.assertEqual(len(signs), 3, f"each counter above zero shows its sign: {signs}")


class DockTest(Stage3dScenarioCase):
    def test_the_dock_comes_with_an_incident_and_opens_and_folds(self):
        self.open3d("normal")
        self.assertEqual(self.body()["dock"], "none")
        self.assertFalse(self.page.evaluate("document.getElementById('decision-dock').getClientRects().length > 0"), "no incident, no dock")

        # 1280x720: the decision point brings the dock's bar over the stage; it unfolds over the stage and folds back.
        self.open3d("no_path")
        close_working(self.page, "w-07")
        wait_decision(self.page)
        self.assertEqual(self.body()["dock"], "collapsed")
        self.assertTrue(self.visible('[data-testid="dock-toggle"]'))
        self.assertEqual(self.attr('[data-testid="dock-toggle"]', "aria-expanded"), "false")
        self.assertTrue(plain(self.page.evaluate("document.querySelector('[data-testid=\"decision-summary\"]').textContent")),
                        "the bar of the folded dock sums the options up in one line")
        self.wait_banner("paused_decision", 3.0)    # the strip has its final height
        size = "(() => { const box = document.getElementById('stage').getBoundingClientRect(); return [box.width, box.height]; })()"
        before = self.page.evaluate(size)
        self.page.click('[data-testid="dock-toggle"]')
        self.page.wait_for("document.body.dataset.dock === 'open'", timeout=2.0)
        self.assertEqual(self.attr('[data-testid="dock-toggle"]', "aria-expanded"), "true")
        self.assertTrue(self.visible("#decision"))
        self.assertEqual(self.count(f'{DECISION} th[data-state="offered"]'), 3)
        self.assertEqual(self.page.evaluate(size), before, "over the stage: the stage keeps its size")
        self.page.click('[data-testid="dock-toggle"]')
        self.page.wait_for("document.body.dataset.dock === 'collapsed'", timeout=2.0)
        self.assertFalse(self.page.evaluate("document.getElementById('decision').getClientRects().length > 0"))

        # 1920x1080: the decision point unfolds the dock under the stage by itself; folding it gives the room back.
        self.page.set_viewport(1920, 1080)
        self.open3d("paused_heartbeat")
        self.wait_body(4.0, dock="open")
        heights = "[document.getElementById('stage').getBoundingClientRect().height, document.querySelector('#stage-3d canvas').clientHeight]"
        open_heights = self.page.evaluate(heights)
        self.page.click('[data-testid="dock-toggle"]')
        self.page.wait_for("document.body.dataset.dock === 'collapsed'", timeout=2.0)
        self.page.wait_for(f"document.querySelector('#stage-3d canvas').clientHeight > {open_heights[1] + 100}", timeout=3.0,
                           message="the model is drawn anew in the larger stage")
        self.wait_idle()
        folded = self.page.evaluate(heights)
        self.assertGreater(folded[0], open_heights[0] + 100, "folded, the dock gives its room to the stage")


class PageScrollTest(Stage3dScenarioCase):
    PAGE = """(() => {
      const root = document.documentElement;
      const wide = (selector) => { const node = document.querySelector(selector); return node ? node.scrollWidth - node.clientWidth : 0; };
      return {scroll: [root.scrollWidth - innerWidth, root.scrollHeight - innerHeight, document.body.scrollWidth - innerWidth,
                       document.body.scrollHeight - innerHeight, scrollX, scrollY],
              wide: {statusbar: wide('#statusbar'), situation: wide('#situation'), centre: wide('#centre'), right: wide('#right'),
                     hud: wide('#stage-hud'), dock: wide('#decision-dock'), drawer: wide('#stand-drawer')}};
    })()"""

    def check(self, where):
        page = self.page.evaluate(self.PAGE)
        self.assertEqual(page["scroll"], [0, 0, 0, 0, 0, 0], f"{where}: the page does not scroll, neither way")
        self.assertEqual({name: value for name, value in page["wide"].items() if value > 0}, {},
                         f"{where}: no region scrolls sideways")

    def test_no_page_scroll_and_no_horizontal_scroll_in_both_modes_at_both_sizes(self):
        for size in SIZES:
            self.page.set_viewport(*size)
            for mode in ("3d", "scheme"):
                route = "#/scheme?mode=scheme" if mode == "scheme" else ""
                self.open("danger_zone", route)
                if mode == "3d":
                    self.wait_scene()
                else:
                    self.wait_drawn()
                self.wait_body(12.0, runState="paused")
                where = f"{mode} at {size[0]}x{size[1]}"
                with self.subTest(where=where):
                    self.assertEqual(self.stage()["stageMode"], mode)
                    self.check(where + ", decision point")
                    show_right(self.page, "decision")
                    self.check(where + ", dock unfolded")
                    set_stand(self.page)
                    self.check(where + ", stand drawer open")
                    set_stand(self.page, False)
                    self.show("list")
                    self.check(where + ", list")
                    self.show("runs")
                    self.check(where + ", runs")
                    self.show("scheme")


class Keyboard3dTest(Stage3dScenarioCase):
    FOCUS = """(() => {
      const node = document.activeElement;
      if (!node || node === document.body) return null;
      const style = getComputedStyle(node);
      return {tag: node.tagName.toLowerCase(), cls: node.getAttribute('class') || '', thing: node.dataset.thingId || null,
              kind: node.dataset.kind || null, keyboard: node.matches(':focus-visible'),
              ring: style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) >= 2 ? style.outlineColor : 'none'};
    })()"""

    def tab_to(self, selector, limit=150, shift=False):
        for _ in range(limit):
            self.page.press("Tab", shift=shift)
            if self.page.evaluate(f"!!document.activeElement && document.activeElement.matches({json.dumps(selector)})"):
                return self.page.evaluate(self.FOCUS)
        self.fail(f"Tab never reached {selector}; the focus is on {self.page.evaluate(self.FOCUS)}")

    def press_and_wait(self, key, shift=False):
        before = self.camera()
        self.page.press(key, shift=shift)
        self.wait_idle()
        return before, self.camera()

    def test_tab_reaches_the_canvas_and_the_labels_and_the_keys_drive_the_camera(self):
        self.open3d("normal")
        overview = self.camera()
        canvas = self.tab_to("#stage-3d canvas")
        self.assertTrue(canvas["keyboard"])
        self.assertEqual(canvas["ring"], "rgb(200, 131, 79)", "a copper focus ring on the canvas")

        # Camera keys on the canvas: arrows turn, + and - zoom, Home goes back to the overview.
        camera = lambda value: [float(part) for part in value.split()]  # noqa: E731
        before, after = self.press_and_wait("ArrowLeft")
        self.assertNotEqual(camera(after)[0], camera(before)[0], "ArrowLeft turns the camera")
        before, after = self.press_and_wait("ArrowUp")
        self.assertNotEqual(camera(after)[1], camera(before)[1], "ArrowUp raises it")
        before, after = self.press_and_wait("+")
        self.assertLess(camera(after)[2], camera(before)[2], "+ comes closer")
        before, after = self.press_and_wait("-")
        self.assertGreater(camera(after)[2], camera(before)[2], "- goes back")
        _, home = self.press_and_wait("Home")
        self.assertEqual(home, overview, "Home restores the overview")

        # The labels after the canvas are buttons: Tab reaches a zone, Enter selects it.
        label = self.tab_to("#stage-3d .s3-label[data-kind='zone']", 40)
        self.assertTrue(label["keyboard"])
        self.assertEqual(label["ring"], "rgb(200, 131, 79)", "a copper focus ring on the label")
        self.page.press("Enter")
        self.page.wait_for(f"location.hash.includes('sel={label['thing']}')", timeout=2.0, message="Enter selects the zone")
        self.page.wait_for(f"document.querySelector('#stage-3d .s3-label[data-thing-id=\"{label['thing']}\"]').getAttribute('aria-pressed') === 'true'",
                           timeout=2.0)
        self.assertEqual(self.page.evaluate(self.FOCUS)["thing"], label["thing"], "the focus stays on the label")
        self.wait_seq(2)
        self.assertEqual(self.page.evaluate(self.FOCUS)["thing"], label["thing"], "two polls later too")
        # Back to the canvas; Esc clears the selection.
        self.tab_to("#stage-3d canvas", 60, shift=True)
        self.page.press("Escape")
        self.page.wait_for("!location.hash.includes('sel=')", timeout=2.0, message="Esc clears the selection")
        # Space on a label selects as well.
        self.tab_to("#stage-3d .s3-label[data-kind='exit']", 60)
        self.page.press("Space")
        self.page.wait_for("location.hash.includes('sel=team040.mine:exit-')", timeout=2.0, message="Space selects the exit")


class ReducedMotion3dTest(Stage3dScenarioCase):
    def setUp(self):
        super().setUp()
        self.page.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})

    def instantly(self, action, what):
        """Run `action`; the change is drawn in at most two frames and no tween runs on the way."""
        self.wait_idle()
        frames = int(self.stage()["frames"])
        self.page.evaluate("""(() => {
          window.__tweens = 0;
          window.__watch = new MutationObserver(() => {
            window.__tweens = Math.max(window.__tweens, Number(document.querySelector('#stage').dataset.tweens || 0));
          });
          window.__watch.observe(document.getElementById('stage'), {attributes: true});
        })()""")
        action()
        time.sleep(0.4)
        stage = self.wait_idle()
        self.page.evaluate("window.__watch.disconnect()")
        drawn = int(stage["frames"]) - frames
        self.assertGreaterEqual(drawn, 1, f"{what}: it was drawn")
        self.assertLessEqual(drawn, 2, f"{what}: at once, not over a glide ({drawn} frames)")
        self.assertEqual(self.page.evaluate("window.__tweens"), 0, f"{what}: no tween")
        return stage

    def test_camera_and_selection_change_at_once(self):
        self.open3d("detour")
        overview = self.camera()
        self.instantly(lambda: self.page.click(self.label_selector("zone-b")), "a selection with its routes")
        self.assertEqual(self.stage()["routes"], "4")
        stage = self.instantly(lambda: self.page.click('[data-testid="card-focus"]'), "«Показать на модели»")
        self.assertNotEqual(stage["camera"], overview)
        self.page.evaluate("document.querySelector('#stage-3d canvas').focus()")
        stage = self.instantly(lambda: self.page.press("Home"), "Home")
        self.assertEqual(stage["camera"], overview)
        close_working(self.page, "w-12")
        wait_decision(self.page)
        self.wait_idle()
        stage = self.instantly(lambda: self.page.click('[data-testid="situation-show-1"]'), "«показать» of the strip")
        self.assertNotEqual(stage["camera"], overview)
        self.assertEqual(self.page.evaluate("document.getAnimations().length"), 0, "no CSS transition or animation runs either")


class NoWebglTest(ScenarioTestCase):
    """Chrome without WebGL: the stage falls back to the scheme with a calm notice; the rest of the screen is the same.
    The checklist items on this path: the *NoWebglTest classes of test_scenarios.py."""

    chrome_args = ("--disable-webgl",)

    def test_the_scheme_with_a_notice_and_the_strip_selects(self):
        self.page.add_init_script(PROBE)
        self.open("danger_zone")
        self.page.wait_for("document.querySelector('#stage').dataset.fallback === 'no-webgl'", timeout=10.0)
        stage = self.page.evaluate("Object.assign({}, document.getElementById('stage').dataset)")
        self.assertEqual((stage["stageMode"], stage["renderer"]), ("scheme", "none"))
        self.page.wait_for("document.querySelector('[data-testid=\"scheme-svg\"]').dataset.drawn === 'true'", timeout=10.0)
        self.assertEqual(self.text('[data-testid="stage-notice"] .stage-notice__text'), "WebGL 2 недоступен в этом браузере — показана схема")
        self.assertTrue(self.visible('[data-testid="stage-notice"]'))
        self.assertFalse(self.visible('[data-testid="stage-back-3d"]'), "no way back to a 3D that cannot run")
        self.assertEqual(self.banners(), [], "a calm notice on the stage, not an alarm banner")
        self.assertEqual([request["url"] for request in self.page.requests if "/vendor/three/" in request["url"]], [],
                         "three.js is not downloaded")
        self.assertEqual(self.page.evaluate("document.querySelectorAll('canvas').length"), 0)

        self.wait_body(12.0, runState="paused")
        self.assertEqual(self.counters()["in-danger"], "3")
        self.assertEqual(self.drawn()[thing("zone-d")]["hazard"], "danger")
        self.page.click('[data-testid="situation-show-2"]')
        self.page.wait_for(f"location.hash.includes('sel={thing('zone-d')}')", timeout=2.0, message="«показать» selects the zone")
        self.assertEqual(self.text('[data-testid="card"] .card__code'), "Участок Г")
        self.page.click('[data-testid="situation-show-4"]')
        self.page.wait_for("document.body.dataset.dock === 'open'", timeout=2.0)
        self.assertEqual(self.count(f'{DECISION} th[data-state="offered"]'), 3)
        # The idle rule of the scheme holds here too.
        self.page.click('[data-testid="dock-toggle"]')
        self.page.evaluate("window.__probe = {canvas: 0, raf: 0}")    # (the boot probed WebGL once, on a canvas of its own)
        self.wait_seq(3)
        self.assertEqual(self.page.evaluate("window.__probe"), {"canvas": 0, "raf": 0}, "no frame and no canvas while the data tick")
