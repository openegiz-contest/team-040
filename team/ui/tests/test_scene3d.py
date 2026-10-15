"""The 3D stage (public/js/view/stage.js, public/js/scene3d/) in headless Chrome.

Chrome runs with SwiftShader, the software WebGL that the judge's machine
without a GPU is expected to resemble ("--use-angle=swiftshader
--enable-unsafe-swiftshader"). The stage mirrors its state on the stage
element (#stage, read-only): data-stage-mode, data-quality, data-renderer,
data-fallback, data-explode, data-rendering, data-levels, data-workings,
data-workers-drawn, data-camera ("azimuth elevation distance", degrees and
metres), data-frames, data-tweens, data-routes, data-measured-ms.

    PYTHONUTF8=1 python -m unittest discover -s team/ui/tests -t team/ui -p "test_scene3d.py" -v

The clarity pass adds (clarity spec B, C): the framing of «показать» and of an
incident that opens (FramingTest), refits caused by panels (PanelRefitTest), the
highlight of a hovered decision option (HoverOptionTest) and the transitions
that explain a change (TransitionTest, ReducedMotionTransitionTest). Motion is
verified by sampling `ctx.stage.info().motion` in the page every 15–30 ms.

Variant 2 («Пульт смены») adds: the loader of each zone as the symbol of its
published work state (LoaderTest, LoaderLightTest), fewer words on the model
(LabelReductionTest), the camera following the situation of the shift once per
change (ChoreographyTest), and the decision panel beside or over the stage
instead of the dock of variant 1 (CompositionTest, FramingTest, HoverOptionTest).

The last test measures (and does not assert tightly) the figures reported in
the 3D section of the README; they are written to test-output/scene3d-measure.json.
"""

import json
import os
import statistics
import time
import unittest

from browser_support import OUTPUT_DIR, STRIP_EQUIPMENT, BrowserTestCase, MockServer, wait_until

NS = "team040.mine"
SWIFTSHADER = ("--use-angle=swiftshader", "--enable-unsafe-swiftshader")

# Counts animation frames and canvas contexts from before the first script of the page,
# and keeps the time of every animation frame callback.
PROBE = """
try {
  // The stage keeps the user's choices in localStorage; every test starts from none.
  if (!sessionStorage.getItem('scene3d-test')) {
    localStorage.removeItem('mine-ui.stage');
    sessionStorage.setItem('scene3d-test', '1');
  }
} catch (error) {}
window.__probe = {raf: 0, canvas: 0, times: []};
const getContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function (...args) { window.__probe.canvas += 1; return getContext.apply(this, args); };
const raf = window.requestAnimationFrame.bind(window);
window.requestAnimationFrame = function (callback) {
  window.__probe.raf += 1;
  return raf((time) => { window.__probe.times.push(performance.now()); callback(time); });
};
"""

APP = "(await import('/js/main.js')).app"


def thing(name):
    return f"{NS}:{name}"


class Stage3dCase(BrowserTestCase):
    chrome_args = SWIFTSHADER
    mock_args = ()
    # The static symbols of the zones' work are tested on a model without equipment twins (STRIP_EQUIPMENT).
    strip_equipment = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock = MockServer("normal", extra_args=cls.mock_args).start()
        cls.addClassCleanup(cls.mock.stop)

    def open(self, scenario, route="", drawn=True, probe=True, timeout=30.0):
        """Restart the scenario and load the page; wait for the first measured 3D frames when `drawn`."""
        if self.strip_equipment and not getattr(self.page, "_strip_equipment", False):
            self.page.add_init_script(STRIP_EQUIPMENT)
            self.page._strip_equipment = True
        if probe and not getattr(self.page, "_scene3d_probe", False):
            self.page.add_init_script(PROBE)
            self.page._scene3d_probe = True
        self.mock.scenario(scenario)
        self.page.goto("about:blank")
        self.page.goto(self.mock.url + "/" + route)
        self.page.wait_for("document.body.dataset.boot === 'ready'", timeout=timeout)
        if drawn:
            self.page.wait_for("(() => { const s = document.querySelector('#stage').dataset;"
                               " return s.stageMode === '3d' && Number(s.frames) > 0 && s.measuredMs !== undefined"
                               " && s.rendering === 'idle' && Number(s.levels) > 0; })()",
                               timeout=timeout, message="the 3D stage is drawn and measured")
        return self.stage()

    def stage(self):
        return self.page.evaluate("Object.assign({}, document.querySelector('#stage').dataset)")

    def js(self, body, timeout=20.0):
        return self.page.evaluate("(async () => {" + body + "})()", timeout=timeout)

    def wait_idle(self, timeout=10.0):
        self.page.wait_for("document.querySelector('#stage').dataset.rendering === 'idle'", timeout=timeout,
                           message="the stage stopped rendering")
        return self.stage()

    def camera(self):
        return [float(value) for value in self.stage()["camera"].split()]

    def body(self):
        return self.page.evaluate("Object.assign({}, document.body.dataset)")

    def click_at(self, x, y):
        for kind, buttons in (("mouseMoved", 0), ("mousePressed", 1), ("mouseReleased", 0)):
            params = {"type": kind, "x": x, "y": y}
            if kind != "mouseMoved":
                params.update({"button": "left", "buttons": buttons, "clickCount": 1})
            self.page.send("Input.dispatchMouseEvent", params)

    def selected(self):
        return self.js(f"return {APP}.store.getState().ui.selected;")

    def wait_selected(self, thing_id, timeout=5.0):
        self.page.wait_for(f"location.hash.includes({json.dumps('sel=' + thing_id)})", timeout=timeout,
                           message=f"{thing_id} is selected")

    def focus_canvas(self):
        self.page.evaluate("document.querySelector('#stage-3d .s3__canvas').focus()")


class BootTest(Stage3dCase):
    def test_boots_in_3d_with_a_software_renderer_and_the_light_quality(self):
        stage = self.open("normal")
        self.assertEqual(stage["stageMode"], "3d")
        self.assertEqual(stage["renderer"], "software", "SwiftShader is detected as a software renderer")
        self.assertEqual(stage["quality"], "low")
        self.assertEqual(stage.get("qualityAuto"), "true")
        self.assertNotIn("fallback", stage)
        counts = self.js(f"const s = {APP}.store.getState(); return [s.model.byKind.level.length, s.model.byKind.working.length,"
                         " s.model.byKind.worker.filter((w) => w.values.status !== 'out').length];")
        self.assertEqual(int(stage["levels"]), counts[0], "one slab per level")
        self.assertEqual(int(stage["workings"]), counts[1], "one channel or inter-level structure per working")
        self.assertEqual(int(stage["workersDrawn"]), counts[2], "every worker under ground is drawn")
        canvas = self.page.evaluate("(() => { const c = document.querySelector('#stage-3d canvas');"
                                    " return [c.getAttribute('role'), c.tabIndex, c.getAttribute('aria-label')]; })()")
        self.assertEqual(canvas[0], "img")
        self.assertEqual(canvas[1], 0, "the canvas is focusable for the keyboard camera")
        self.assertIn("Трёхмерная модель рудника", canvas[2])
        self.assertTrue(self.page.evaluate("getComputedStyle(document.querySelector('#scheme')).display === 'none'"),
                        "the SVG scheme is not shown under the 3D model")
        hud = self.page.evaluate("[...document.querySelectorAll('#stage-hud [data-mode]')].map((b) => [b.dataset.mode, b.getAttribute('aria-pressed')])")
        self.assertEqual(hud, [["3d", "true"], ["scheme", "false"]])
        info = self.js(f"return {APP}.ctx.stage.info();")
        self.assertLessEqual(info["triangles"], 60000, "the light quality stays within its triangle budget")
        self.assertLessEqual(info["calls"], 90, "and within its draw-call budget")

    def test_labels_are_buttons_with_the_state_attributes_of_the_list(self):
        self.open("sensor_lost_after_danger")
        labels = self.page.evaluate("""(() => {
          const out = {};
          for (const node of document.querySelectorAll('#stage-3d .s3-label[data-thing-id]')) {
            const {thingId, label, rank, culled, ...state} = node.dataset;
            if (node.tagName !== 'BUTTON') return 'not a button: ' + thingId;
            out[thingId] = state;
          }
          return out;
        })()""")
        self.assertIsInstance(labels, dict, labels)
        kinds = self.js(f"""const s = {APP}.store.getState();
          return Object.fromEntries(['zone', 'exit'].map((kind) => [kind, s.model.byKind[kind].map((t) => t.thingId)]));""")
        for kind, ids in kinds.items():
            for thing_id in ids:
                self.assertIn(thing_id, labels, f"a label button for the {kind} {thing_id}")
        for name in ("sens-ext-05", "zone-c"):
            self.assertIn(thing(name), labels, f"the problem object {name} has a label")
        self.assertEqual(labels[thing("zone-c")]["hazard"], "unknown")
        self.assertEqual(labels[thing("zone-c")]["lastKnownHazard"], "danger")
        self.assertEqual(labels[thing("sens-ext-05")]["quality"], "lost")
        # The same twins in the list carry the same state attributes.
        self.page.evaluate("location.hash = '#/list'")
        self.page.wait_for("document.body.dataset.view === 'list'", timeout=5.0)
        rows = self.page.evaluate("""(() => {
          const out = {};
          for (const node of document.querySelectorAll('[data-testid="list"] [data-thing-id]')) {
            const {thingId, ...state} = node.dataset;
            out[thingId] = state;
          }
          return out;
        })()""")
        state_keys = ("kind", "hazard", "quality", "lastKnownHazard", "passability", "restriction", "workState", "withdrawal",
                      "link", "status", "egress", "locationHazard", "posQuality", "state")
        compared = 0
        for thing_id, state in labels.items():
            if thing_id not in rows:
                continue
            for key in state_keys:
                self.assertEqual(state.get(key), rows[thing_id].get(key), f"{thing_id} {key}")
            compared += 1
        self.assertGreaterEqual(compared, 8, "labels and list rows were compared")

    def test_a_label_and_a_click_on_the_canvas_select_the_object_and_the_card_shows_it(self):
        self.open("normal")
        zone = thing("zone-d")
        self.page.click(f'#stage-3d .s3-label[data-thing-id="{zone}"]')
        self.wait_selected(zone)
        self.page.wait_for(f"document.querySelector('[data-testid=\"card\"]').textContent.includes('Участок Г')", timeout=3.0)
        self.page.wait_for(f"document.querySelector('#stage-3d .s3-label[data-thing-id=\"{zone}\"]').getAttribute('aria-pressed') === 'true'",
                           timeout=3.0)
        worker = thing("worker-12")
        point = self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(worker)});")
        self.assertTrue(point and point["visible"], point)
        self.click_at(point["x"], point["y"])
        self.wait_selected(worker)
        self.page.wait_for("document.querySelector('[data-testid=\"card\"]').textContent.includes('Р-12')", timeout=3.0)
        # A working, by its channel.
        working = thing("w-30")
        point = self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(working)});")
        self.click_at(point["x"], point["y"] + 2)
        self.wait_selected(working)
        # Esc on the canvas clears the selection.
        self.focus_canvas()
        self.page.press("Escape")
        self.page.wait_for("!location.hash.includes('sel=')", timeout=3.0)

    def test_keyboard_moves_the_camera_and_home_restores_the_overview(self):
        self.open("normal")
        home = self.camera()
        self.focus_canvas()
        self.page.press("ArrowLeft")
        self.wait_idle()
        turned = self.camera()
        self.assertAlmostEqual((turned[0] - home[0]) % 360, 15, delta=1.5, msg="ArrowLeft turns the camera by 15°")
        self.page.press("+")
        self.wait_idle()
        closer = self.camera()
        self.assertLess(closer[2], turned[2] * 0.9, "+ zooms in")
        self.page.press("ArrowUp", shift=True)
        self.wait_idle()
        self.assertEqual(self.camera()[:2], closer[:2], "Shift and an arrow pan without turning")
        self.page.press("PageDown")
        self.wait_idle()
        self.page.press("Home")
        self.wait_idle()
        self.assertEqual(self.camera(), home, "Home restores the overview")
        focus = self.page.focus_info()
        self.assertEqual(focus["role"], "img", "the canvas keeps the keyboard focus")
        outline = self.page.evaluate("getComputedStyle(document.querySelector('#stage-3d canvas')).outlineStyle")
        self.assertEqual(outline, "solid", "a visible focus ring on the canvas")

    def test_focus_glides_to_an_object_and_keeps_the_azimuth(self):
        self.open("normal")
        self.focus_canvas()
        self.page.press("ArrowLeft")
        self.page.press("ArrowLeft")
        self.wait_idle()
        before = self.camera()
        frames = int(self.stage()["frames"])
        self.assertTrue(self.js(f"return {APP}.ctx.stage.focus({json.dumps(thing('zone-b'))});"))
        self.page.wait_for("document.querySelector('#stage').dataset.rendering === 'active'", timeout=2.0)
        after = self.wait_idle()
        camera = [float(value) for value in after["camera"].split()]
        self.assertEqual(camera[0], before[0], "the azimuth is kept")
        self.assertEqual(camera[1], before[1], "and the elevation")
        # A zone is framed with its people, the ends of their routes and its horizon, never closer than about one
        # horizon width (clarity spec B): closer than the overview, not a close-up.
        self.assertLess(camera[2], before[2] * 0.9, "the camera came closer")
        self.assertGreaterEqual(int(after["frames"]) - frames, 8, "it glided over several frames")
        self.assertTrue(self.js(f"return {APP}.ctx.stage.focus('level-380');"), "a level by its local name")
        self.wait_idle()
        self.assertTrue(self.js(f"return {APP}.ctx.stage.overview();"))
        self.wait_idle()
        self.page.click('[data-testid="stage-mode-scheme"]')
        self.page.wait_for("document.querySelector('#stage').dataset.stageMode === 'scheme'", timeout=3.0)
        self.assertFalse(self.js(f"return {APP}.ctx.stage.focus({json.dumps(thing('zone-b'))});"), "false when not in 3D")
        self.assertFalse(self.js(f"return {APP}.ctx.stage.overview();"))
        self.assertIn("mode=scheme", self.page.evaluate("location.hash"))


class IdleAndMotionTest(Stage3dCase):
    def test_no_animation_frames_while_the_data_do_not_change(self):
        self.open("paused_heartbeat")
        self.wait_idle()
        seq = int(self.body()["seq"])
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(5.2)
        probe = self.page.evaluate("window.__probe")
        self.assertGreaterEqual(int(self.body()["seq"]) - seq, 4, "the page went on polling")
        self.assertEqual(probe["raf"], 0, "no animation frame is requested while nothing changes")
        self.assertEqual(self.stage()["rendering"], "idle")

    def test_a_running_model_with_still_people_draws_nothing_once_the_first_frames_are_done(self):
        """In `normal` the model ticks every second but nothing visible changes: after the boot frames
        (first frame, the measured frames, labels) the stage requests no animation frame at all. (Without the
        equipment twins: their loaders move by publications, EquipmentTest.)"""
        self.page.add_init_script(STRIP_EQUIPMENT)
        self.open("normal")
        self.wait_idle()
        boot = self.page.evaluate("window.__probe.raf")
        self.assertGreater(boot, 0, "the boot frames were drawn")
        self.assertLessEqual(boot, 16, "a bounded number of boot frames")
        tick = int(self.body()["tick"])
        contexts = self.page.evaluate("window.__probe.canvas")
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(5.2)
        self.assertGreater(int(self.body()["tick"]), tick, "the model time advanced")
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "and no frame was requested")
        self.assertEqual(self.page.evaluate("window.__probe.canvas"), contexts, "and no canvas context was created")

    def start_withdrawal(self):
        """Close В-12 and execute «stop and withdraw» of the detour story: four people walk to the exit."""
        result = self.js(f"return {APP}.ctx.sendCommand('condition.close_working', 'w-12');")
        self.assertTrue(result["ok"], result)
        self.page.wait_for("document.body.dataset.runState === 'paused'", timeout=10.0)
        self.page.wait_for("(async () => { const s = (await import('/js/main.js')).app.store.getState();"
                           " const o = s.model.byName['option-stop-withdraw']; return o && o.values.state === 'offered'; })()",
                           timeout=10.0)
        result = self.js(f"return {APP}.ctx.sendCommand('action.execute_option', 'option-stop-withdraw');")
        self.assertTrue(result["ok"], result)
        self.page.wait_for("document.body.dataset.runState === 'running'", timeout=10.0)

    def test_workers_glide_between_polls_and_stop_at_once_on_a_failed_read(self):
        self.open("detour")
        self.start_withdrawal()
        worker = thing("worker-03")
        samples = []
        tweening = 0
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            sample = self.js(f"const p = {APP}.ctx.stage.screenOf({json.dumps(worker)});"
                             " return [Number(document.body.dataset.seq), p && Math.round(p.x * 10) / 10, p && Math.round(p.y * 10) / 10,"
                             " Number(document.querySelector('#stage').dataset.tweens)];")
            samples.append(sample)
            tweening = max(tweening, sample[3])
            time.sleep(0.12)
        self.assertGreater(tweening, 0, "positions glide while the link is ok and the model runs")
        moved_within_one_poll = any(a[0] == b[0] and (a[1], a[2]) != (b[1], b[2]) for a, b in zip(samples, samples[1:]))
        self.assertTrue(moved_within_one_poll, f"the marker moved between two polls: {samples[:12]}")
        self.mock.fault("http_502")
        self.page.wait_for("document.body.dataset.link !== 'ok'", timeout=5.0)
        self.page.wait_for("document.querySelector('#stage').dataset.tweens === '0'", timeout=1.0,
                           message="the first failed read stops every glide")
        first = self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(worker)}).world;")
        self.page.wait_for("document.body.dataset.link === 'unavailable'", timeout=10.0)
        self.page.wait_for("document.querySelector('#stage-3d .s3').hasAttribute('data-old')", timeout=3.0,
                           message="the scene marks itself as showing the last data")
        self.wait_idle(timeout=3.0)
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(2.5)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "nothing moves while reads fail")
        self.assertEqual(self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(worker)}).world;"), first,
                         "the marker stays where the last read put it")
        caption = self.page.evaluate("document.querySelector('#stage-3d .s3__old-text').textContent")
        self.assertIn("последние полученные данные", caption)
        self.mock.fault("none")


class ReducedMotionTest(Stage3dCase):
    def setUp(self):
        super().setUp()
        self.page.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})

    def test_reduced_motion_jumps_without_tween_frames(self):
        self.open("detour")
        IdleAndMotionTest.start_withdrawal(self)
        self.page.evaluate("window.__probe.raf = 0")
        seq = int(self.body()["seq"])
        tweening = 0
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            tweening = max(tweening, int(self.stage().get("tweens", "0")))
            time.sleep(0.1)
        polls = int(self.body()["seq"]) - seq
        raf = self.page.evaluate("window.__probe.raf")
        self.assertEqual(tweening, 0, "no glide under reduced motion")
        self.assertGreaterEqual(polls, 3)
        self.assertLessEqual(raf, polls + 2, f"one frame per new publication, not a tween ({raf} frames, {polls} polls)")
        # A camera request is instant too.
        frames = int(self.stage()["frames"])
        self.assertTrue(self.js(f"return {APP}.ctx.stage.focus({json.dumps(thing('zone-b'))});"))
        self.wait_idle()
        self.assertLessEqual(int(self.stage()["frames"]) - frames, 2, "no glide frames")


class SchemeModeTest(Stage3dCase):
    def test_mode_scheme_in_the_hash_shows_the_svg_and_never_loads_three(self):
        self.open("normal", "#/scheme?mode=scheme", drawn=False)
        self.page.wait_for("document.querySelector('[data-testid=\"scheme-svg\"]').dataset.drawn === 'true'", timeout=10.0)
        stage = self.stage()
        self.assertEqual(stage["stageMode"], "scheme")
        self.assertNotIn("renderer", stage, "WebGL is not even probed")
        time.sleep(1.0)
        loaded = [entry["url"] for entry in self.page.requests if "/vendor/three/" in entry["url"] or "/scene3d/" in entry["url"]]
        self.assertEqual(loaded, [], "the scheme mode downloads no file of the 3D stage")
        self.assertEqual(self.page.evaluate("window.__probe.canvas"), 0)
        self.assertTrue(self.page.evaluate("getComputedStyle(document.querySelector('#stage-3d')).display === 'none'"))
        # The switch of the HUD goes to 3D and back.
        self.page.click('[data-testid="stage-mode-3d"]')
        self.page.wait_for("Number(document.querySelector('#stage').dataset.frames) > 0", timeout=20.0)
        self.assertIn("mode=3d", self.page.evaluate("location.hash"))
        self.page.click('[data-testid="stage-mode-scheme"]')
        self.page.wait_for("document.querySelector('#stage').dataset.stageMode === 'scheme'", timeout=3.0)
        self.assertEqual(self.page.evaluate("document.querySelectorAll('#stage-3d canvas').length"), 0, "the 3D scene is released")


class NoWebglTest(Stage3dCase):
    chrome_args = ("--disable-webgl",)

    def test_without_webgl_the_scheme_is_shown_with_a_calm_notice(self):
        self.open("normal", drawn=False)
        self.page.wait_for("document.querySelector('#stage').dataset.fallback === 'no-webgl'", timeout=10.0)
        stage = self.stage()
        self.assertEqual(stage["stageMode"], "scheme")
        self.assertEqual(stage["renderer"], "none")
        self.page.wait_for("document.querySelector('[data-testid=\"scheme-svg\"]').dataset.drawn === 'true'", timeout=10.0)
        notice = self.page.evaluate("(() => { const n = document.querySelector('[data-testid=\"stage-notice\"]');"
                                    " return n.hidden ? null : n.textContent; })()")
        self.assertIn("WebGL", notice)
        self.assertIn("показана схема", notice)
        loaded = [entry["url"] for entry in self.page.requests if "/vendor/three/" in entry["url"]]
        self.assertEqual(loaded, [], "three.js is not downloaded when it cannot run")


class FallbackTest(Stage3dCase):
    def test_slow_first_frames_give_way_to_the_scheme_with_a_way_back(self):
        self.open("normal")
        self.assertEqual(self.stage()["quality"], "low")
        # The first frames of a scene are measured once per quality: a slow machine is emulated by throttling
        # the CPU and asking for a new scene.
        self.page.send("Emulation.setCPUThrottlingRate", {"rate": 20})
        try:
            self.page.evaluate("(() => { const s = document.querySelector('[data-testid=\"stage-quality\"]');"
                               " s.value = 'high'; s.dispatchEvent(new Event('change')); })()", timeout=30.0)
            self.page.wait_for("document.querySelector('#stage').dataset.fallback === 'slow'", timeout=150.0, interval=1.0,
                               message="slow frames switch to the scheme")
        finally:
            self.page.send("Emulation.setCPUThrottlingRate", {"rate": 1})
        stage = self.stage()
        self.assertEqual(stage["stageMode"], "scheme")
        self.assertGreater(int(stage["measuredMs"]), 200)
        text = self.page.evaluate("document.querySelector('[data-testid=\"stage-notice\"]').textContent")
        self.assertIn("3D на этом устройстве работает медленно — показана схема", text)
        # Long tasks queued under the throttling may still run: the click is repeated once if it was not taken.
        time.sleep(1.0)
        self.page.click('[data-testid="stage-back-3d"]')
        time.sleep(4.0)
        if self.stage()["stageMode"] != "3d":
            self.page.click('[data-testid="stage-back-3d"]', timeout=3.0)
        try:
            self.page.wait_for("(() => { const s = document.querySelector('#stage').dataset;"
                               " return s.stageMode === '3d' && Number(s.frames) > 0 && !s.fallback; })()", timeout=40.0,
                               message="the button returns to 3D")
        except AssertionError as error:
            raise AssertionError(f"{error}; stage: {self.stage()}") from None
        self.page.evaluate("localStorage.removeItem('mine-ui.stage')")

    def test_a_lost_graphics_context_shows_the_scheme_until_it_is_restored(self):
        self.open("normal")
        self.js("const gl = document.querySelector('#stage-3d canvas').getContext('webgl2');"
                " window.__lose = gl.getExtension('WEBGL_lose_context'); window.__lose.loseContext(); return true;")
        self.page.wait_for("document.querySelector('#stage').dataset.fallback === 'context-lost'", timeout=5.0)
        self.assertEqual(self.stage()["stageMode"], "scheme")
        self.page.wait_for("document.querySelector('[data-testid=\"scheme-svg\"]').dataset.drawn === 'true'", timeout=10.0)
        self.assertIn("контекст", self.page.evaluate("document.querySelector('[data-testid=\"stage-notice\"]').textContent"))
        self.js("window.__lose.restoreContext(); return true;")
        self.page.wait_for("(() => { const s = document.querySelector('#stage').dataset;"
                           " return s.stageMode === '3d' && !s.fallback && Number(s.frames) > 0; })()", timeout=20.0,
                           message="3D comes back when the context is restored")


class CompositionTest(Stage3dCase):
    """The stage keeps the centre of the shift desk: the decision panel stands beside it (1920) or over its right part
    (1280), and the incident stays clear of it; with no panel the overview uses the room it has."""

    GEOMETRY = """(() => {
      const box = (id) => { const r = document.getElementById(id).getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
      return {stage: box('stage-3d'), panel: box('panel'), viewport: [innerWidth, innerHeight], shown: document.body.dataset.panel};
    })()"""

    def tearDown(self):
        self.page.set_viewport(1280, 720)
        super().tearDown()

    def test_at_a_decision_the_stage_keeps_the_centre_and_the_incident_stays_clear_of_the_panel(self):
        for width, height in ((1920, 1080), (1280, 720)):
            with self.subTest(size=f"{width}x{height}"):
                self.page.set_viewport(width, height)
                self.open("danger_zone")
                self.page.wait_for("document.body.dataset.runState === 'paused' && document.body.dataset.panel === 'shown'", timeout=30.0,
                                   message="the decision point opens the panel")
                time.sleep(1.0)
                self.wait_idle()
                got = self.page.evaluate(self.GEOMETRY)
                stage_left, _, stage_right, _ = got["stage"]
                free_right = got["panel"][0] if got["panel"][0] < stage_right else stage_right
                self.assertGreaterEqual((free_right - stage_left) / width, 0.5, f"the free stage keeps half the width: {got}")
                points = self.js(f"""const st = {APP}.ctx.stage;
                  return ['worker-11', 'worker-12', 'worker-13'].map((n) => st.screenOf('{NS}:' + n));""")
                for point in points:
                    self.assertTrue(point and point["visible"], point)
                    self.assertTrue(stage_left <= point["x"] <= free_right, f"a person of the incident beside the panel: {point} {got}")

    def test_the_overview_fills_the_stage(self):
        for width, height in ((1920, 1080), (1280, 720)):
            with self.subTest(size=f"{width}x{height}"):
                self.page.set_viewport(width, height)
                self.open("normal")
                info = self.js(f"return {APP}.ctx.stage.info();")
                left, top, right, bottom = info["model"]
                w, h = info["stage"]
                self.assertTrue(left >= 0 and top >= 0 and right <= w and bottom <= h, f"{info['model']} in {info['stage']}")
                # About four fifths in one direction: the rest is the room of the horizon labels, the exits and the HUD.
                self.assertTrue((bottom - top) / h >= 0.75 or (right - left) / w >= 0.75,
                                f"the model fills the stage in one direction: {info['model']} of {info['stage']}")


# Samples `ctx.stage.info().motion` every `step` ms for `ms` ms, after running `act` (a statement), in the page;
# the samples are kept in window.__samples, and returned when `wait` is true.
SAMPLE = """(async () => {
  const app = (await import('/js/main.js')).app;
  const stage = document.querySelector('#stage');
  const out = [];
  window.__samples = out;
  const run = async () => {
    %(act)s;
    const t0 = performance.now();
    while (performance.now() - t0 < %(ms)d) {
      const info = app.ctx.stage.info();
      out.push({t: Math.round(performance.now() - t0), m: info && info.motion, r: stage.dataset.rendering,
        fx: document.querySelector('#stage-3d .s3').dataset.fx || null});
      await new Promise((resolve) => setTimeout(resolve, %(step)d));
    }
    out.done = true;
    return out;
  };
  return %(wait)s ? run() : (run(), true);
})()"""

# Where an object is drawn, relative to the 3D stage, and whether a label is shown inside it.
PLACE = """(async (ids) => {
  const app = (await import('/js/main.js')).app;
  const box = document.getElementById('stage-3d').getBoundingClientRect();
  return ids.map((id) => {
    const p = app.ctx.stage.screenOf(id);
    return p && {id, visible: p.visible, x: p.x - box.left, y: p.y - box.top};
  });
})"""

LABEL = """((key) => {
  const node = document.querySelector(`#stage-3d .s3-label[data-label="${key}"]`);
  if (!node) return null;
  const r = node.getBoundingClientRect();
  const box = document.getElementById('stage-3d').getBoundingClientRect();
  return {culled: node.hasAttribute('data-culled'), x: r.left - box.left, y: r.top - box.top, w: r.width, h: r.height,
    cls: node.className};
})"""


class Stage3dStoryCase(Stage3dCase):
    """A story with an incident: danger_zone reaches its decision point six publications after the start."""

    def decision(self, scenario="danger_zone", route=""):
        stage = self.open(scenario, route)
        self.page.wait_for("document.body.dataset.runState === 'paused'", timeout=30.0, message="the decision point")
        time.sleep(0.8)
        self.wait_idle()
        return stage

    def info(self):
        return self.js(f"return {APP}.ctx.stage.info();")

    def place(self, *names):
        return self.page.evaluate(f"{PLACE}({json.dumps([thing(name) for name in names])})", timeout=10.0)

    def label(self, key):
        return self.page.evaluate(f"{LABEL}({json.dumps(key)})")

    def sample(self, act="", ms=900, step=25):
        return self.page.evaluate(SAMPLE % {"act": act, "ms": ms, "step": step, "wait": "true"}, timeout=ms / 1000 + 20)

    def sample_around(self, action, ms=900, step=15):
        """Start sampling in the page, then do `action` (from Python, e.g. a real pointer move), and give the samples."""
        self.page.evaluate(SAMPLE % {"act": "", "ms": ms, "step": step, "wait": "false"})
        action()
        self.page.wait_for("window.__samples.done === true", timeout=ms / 1000 + 20)
        return self.page.evaluate("window.__samples")

    def free_area(self):
        """The part of the 3D stage not under the panel when it lies over the stage, in stage pixels: [top, bottom, right]."""
        return self.page.evaluate("""(() => {
          const box = document.getElementById('stage-3d').getBoundingClientRect();
          const r = document.getElementById('panel').getBoundingClientRect();
          const over = r.width > 0 && r.left < box.right - 1 && r.right > box.left + 1;
          return [0, box.height, over ? r.left - box.left : box.width];
        })()""")

    def assert_in_free_area(self, points, what):
        top, bottom, width = self.free_area()
        for point in points:
            self.assertIsNotNone(point, what)
            self.assertTrue(point["visible"], f"{what}: {point}")
            self.assertTrue(0 <= point["x"] <= width and top <= point["y"] <= bottom, f"{what} {point['id']} in the free stage {top}..{bottom}: {point}")


class FramingTest(Stage3dStoryCase):
    """«показать» and the incident: the zone, its people, the ends of their routes and the horizon label (clarity spec B)."""

    def tearDown(self):
        self.page.set_viewport(1280, 720)
        super().tearDown()

    def test_show_frames_the_zone_its_people_route_ends_and_horizon_label(self):
        for width, height in ((1920, 1080), (1280, 720)):
            with self.subTest(size=f"{width}x{height}"):
                self.page.set_viewport(width, height)
                self.decision()
                self.focus_canvas()
                self.page.press("Home")
                overview = self.wait_idle()["camera"]
                frames = int(self.stage()["frames"])
                zone = thing("zone-d")
                self.js(f"{APP}.ctx.select({json.dumps(zone)}); {APP}.ctx.stage.focus({json.dumps(zone)}); return true;")
                stage = self.wait_idle()
                self.assertNotEqual(stage["camera"], overview)
                self.assertGreaterEqual(int(stage["frames"]) - frames, 5, "it glided")
                info = self.info()
                self.assertEqual(info["focus"], zone)
                # The zone (its workings), the people in it, and where their published routes end (exit-raise).
                self.assert_in_free_area(self.place("w-23", "w-24", "w-25", "worker-11", "worker-12", "worker-13"), "zone and people")
                if width == 1920:
                    self.assert_in_free_area(self.place("exit-raise"), "the end of their routes")
                level = self.label("level:level-380")
                self.assertFalse(level["culled"], "the horizon label is shown")
                self.assertTrue(level["x"] >= 0 and level["y"] >= 0 and level["x"] + level["w"] <= info["stage"][0]
                                and level["y"] + level["h"] <= info["stage"][1], f"the horizon label is in the stage: {level}")
                widths = {entry["name"]: entry["width"] for entry in info["levels"]}
                self.assertGreaterEqual(info["viewWidth"], 0.9 * widths["level-380"],
                                        f"never closer than about one horizon width: {info['viewWidth']} m of {widths['level-380']} m")

    def test_at_1280_the_panel_over_the_stage_keeps_the_incident_beside_it(self):
        self.page.set_viewport(1280, 720)
        self.decision()
        self.page.wait_for("document.body.dataset.panel === 'shown'", timeout=5.0)
        self.focus_canvas()
        self.page.press("Home")
        self.wait_idle()
        zone = thing("zone-d")
        self.js(f"{APP}.ctx.stage.focus({json.dumps(zone)}); return true;")
        self.wait_idle()
        info = self.info()
        self.assertEqual(info["focus"], zone, "the incident, not the whole mine")
        self.assert_in_free_area(self.place("w-23", "w-24", "w-25", "worker-11", "worker-12", "worker-13"), "zone and people beside the panel")
        level = self.label("level:level-380")
        _, _, right = self.free_area()
        self.assertFalse(level["culled"])
        self.assertLessEqual(level["x"] + level["w"], right, f"the horizon label is beside the panel: {level}")
        widths = {entry["name"]: entry["width"] for entry in info["levels"]}
        self.assertGreaterEqual(info["viewWidth"], 0.9 * widths["level-380"], "about one horizon width at least")
        # No label of the scene lies under the panel.
        under = self.page.evaluate("""(() => {
          const panel = document.getElementById('panel').getBoundingClientRect();
          return [...document.querySelectorAll('#stage-3d .s3-label:not([data-culled])')].map((n) => n.getBoundingClientRect())
            .filter((r) => r.right > panel.left + 1).length; })()""")
        self.assertEqual(under, 0, "the labels keep clear of the panel")
        # The HUD keeps clear of the panel and folds to icons; the scale box goes.
        hud = self.page.evaluate("""(() => ({
          words: [...document.querySelectorAll('#stage-hud .hud__text')].map((n) => getComputedStyle(n).display),
          icons: [...document.querySelectorAll('#stage-hud .hud__btn > .hud__icon')].map((n) => getComputedStyle(n).display),
          scale: getComputedStyle(document.querySelector('#stage-3d .s3__gizmo-text')).display,
          right: document.querySelector('#stage-hud .hud__row').getBoundingClientRect().right,
          panel: document.getElementById('panel').getBoundingClientRect().left,
          names: [...document.querySelectorAll('#stage-hud button, #stage-hud summary')].filter((n) => n.offsetWidth > 0)
            .map((n) => n.getAttribute('aria-label') || n.textContent.trim()),
        }))()""")
        self.assertEqual(set(hud["words"]), {"none"}, hud)
        self.assertNotIn("none", hud["icons"], hud)
        self.assertEqual(hud["scale"], "none")
        self.assertLessEqual(hud["right"], hud["panel"], "the HUD is not under the panel")
        self.assertTrue(all(hud["names"]), f"every folded control keeps its name: {hud['names']}")

    def test_an_incident_that_opens_is_framed_once_unless_the_user_moved_the_camera(self):
        self.page.set_viewport(1920, 1080)
        self.open("danger_zone")
        self.assertTrue(self.info()["overview"], "the overview first")
        self.page.wait_for("document.querySelector('#stage-3d .s3').dataset.autoFramed !== undefined", timeout=30.0,
                           message="the incident is framed when it opens")
        self.assertIn("zone-d", self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.autoFramed"))
        self.wait_idle()
        info = self.info()
        self.assertEqual(info["focus"], thing("zone-d"))
        self.assert_in_free_area(self.place("worker-11", "worker-12", "worker-13"), "the people of the incident")
        # Once per incident: the next publications of the same incident do not move the camera.
        camera = self.camera()
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(3.0)
        self.assertEqual(self.camera(), camera)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "nothing moves after it")
        # A user who moved the camera in the last 10 s keeps his view.
        self.open("danger_zone")
        self.focus_canvas()
        self.page.press("ArrowLeft")
        moved = self.wait_idle()["camera"]
        self.page.wait_for("document.body.dataset.runState === 'paused'", timeout=30.0)
        time.sleep(1.0)
        self.wait_idle()
        self.assertIsNone(self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.autoFramed || null"))
        self.assertEqual(self.camera()[:2], [float(v) for v in moved.split()][:2], "the user's azimuth and elevation stay")
        self.assertIsNone(self.info()["focus"])

    def test_an_incident_already_open_on_load_is_not_flown_to(self):
        """No camera move on load (motion rule). The panel of the decision may refit the picture at once when it
        would hide the incident (variant 2: over the stage at 1280); the incident's people stay in sight."""
        for scenario in ("paused_heartbeat", "sensor_lost_after_danger"):
            with self.subTest(scenario=scenario):
                self.open(scenario)
                time.sleep(1.5)
                self.wait_idle()
                self.assertIsNone(self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.autoFramed || null"))
                self.assertIsNone(self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.choreo || null"))
                zone = self.js(f"return {APP}.store.getState().model.byKind.incident[0].values.zone;")
                people = self.js(f"""const s = {APP}.store.getState(); const w = s.model.byName[{json.dumps(zone)}].attrs.workings;
                  return s.model.byKind.worker.filter((t) => t.values.status !== 'out' && w.includes(t.values.at_working)).map((t) => t.name);""")
                if people:
                    self.assert_in_free_area(self.place(*people), "the people of the open incident")


class PanelRefitTest(Stage3dStoryCase):
    def test_opening_the_legend_never_moves_the_mine(self):
        for scenario in ("normal", "danger_zone"):
            with self.subTest(scenario=scenario):
                if scenario == "normal":
                    self.open(scenario)
                else:
                    self.decision(scenario)
                camera = self.wait_idle()["camera"]
                refits = self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.refits || '0'")
                self.page.click('[data-testid="legend-toggle"]')
                self.page.wait_for("document.querySelector('[data-testid=\"legend-toggle\"]').getAttribute('aria-expanded') === 'true'",
                                   timeout=3.0)
                time.sleep(0.6)
                self.wait_idle()
                self.assertEqual(self.camera(), [float(v) for v in camera.split()], "the legend opened over the stage")
                self.assertEqual(self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.refits || '0'"), refits)
                self.page.click('[data-testid="legend-toggle"]')
                time.sleep(0.6)
                self.wait_idle()
                self.assertEqual(self.camera(), [float(v) for v in camera.split()], "and closed")

    def test_the_stand_drawer_moves_the_overview_only_when_it_would_hide_the_incident(self):
        self.open("normal")
        camera = self.wait_idle()["camera"]
        self.page.evaluate("document.querySelector('[data-testid=\"stand-toggle\"]').click()")
        self.page.wait_for("document.body.dataset.stand === 'open'", timeout=3.0)
        time.sleep(0.6)
        self.wait_idle()
        self.assertEqual(self.stage()["camera"], camera, "no incident: the drawer does not move the mine")
        self.page.evaluate("document.querySelector('[data-testid=\"stand-toggle\"]').click()")
        self.page.wait_for("document.body.dataset.stand === 'closed'", timeout=3.0)


class HoverOptionTest(Stage3dStoryCase):
    """C: the option under the pointer in the panel lights the zones of its published scope and the people in them now."""

    def unfold(self):
        """The decision panel is open by itself at the decision point."""
        self.page.wait_for("document.body.dataset.panel === 'shown'", timeout=5.0)
        time.sleep(0.6)
        self.wait_idle()

    def point_at(self, name):
        """Move the pointer over the card of an option in the panel, or over the stage when `name` is None."""
        if name:
            box = self.page.evaluate(f"""(() => {{ const n = document.querySelector('[data-testid="option-card"][data-option="{name}"]')
              || document.querySelector('[data-option="{name}"]');
              const r = n.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()""")
        else:
            box = self.page.evaluate("(() => { const r = document.getElementById('stage-3d').getBoundingClientRect();"
                                     " return [r.left + 40, r.top + r.height / 2]; })()")
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": box[0], "y": box[1]})

    def scope_labels(self):
        return self.page.evaluate("[...document.querySelectorAll('#stage-3d .s3-label.is-scope')].map((n) => n.dataset.thingId).sort()")

    def test_hovered_option_highlights_its_zones_and_their_people(self):
        self.page.set_viewport(1920, 1080)
        self.decision()
        self.unfold()
        model = self.js(f"""const s = {APP}.store.getState();
          const zones = (name) => s.model.byName[name].attrs.workings;
          return Object.fromEntries(s.model.byKind.zone.map((z) => [z.name, s.model.byKind.worker
            .filter((w) => w.values.status !== 'out' && zones(z.name).includes(w.values.at_working)).map((w) => w.name).sort()]));""")
        cases = (("option-stop-withdraw", ["zone-d"]), ("option-withdraw-all", ["zone-a", "zone-b", "zone-c", "zone-d"]),
                 ("option-observe", []))
        for option, zones in cases:
            with self.subTest(option=option):
                self.point_at(option)
                self.page.wait_for(f"(async () => (await import('/js/main.js')).app.store.getState().ui.hoverOption === {json.dumps(thing(option))})()",
                                   timeout=3.0, message="the panel names the option under the pointer")
                time.sleep(0.4)
                self.wait_idle()
                motion = self.info()["motion"]
                people = sorted(name for zone in zones for name in model[zone])
                self.assertEqual(motion["scopeZones"], zones, "the zones of the published scope")
                self.assertEqual(motion["scopeWorkers"], people, "and the people now in them")
                self.assertEqual(motion["scope"], 1)
                labelled = self.scope_labels()
                for zone in zones:
                    self.assertIn(thing(zone), labelled, f"the tag of {zone} is lit")
                for other in {"zone-a", "zone-b", "zone-c", "zone-d"} - set(zones):
                    self.assertNotIn(thing(other), labelled)
                if option == "option-stop-withdraw":
                    self.assertNotIn("worker-14", people, "Р-14 belongs to Участок Г but stands outside it: not lit")
                    self.assertTrue(any(thing(name) in labelled for name in ("worker-11", "worker-12", "worker-13")),
                                    f"the labels of its people are lit: {labelled}")
        self.point_at(None)
        time.sleep(0.5)
        self.wait_idle()
        self.assertEqual(self.info()["motion"]["scopeZones"], [], "nothing is lit without an option")
        self.assertEqual(self.scope_labels(), [])
        self.page.set_viewport(1280, 720)

    def test_the_highlight_fades_in_and_out_once(self):
        self.page.set_viewport(1920, 1080)
        self.decision()
        self.unfold()
        samples = self.sample_around(lambda: self.point_at("option-stop-withdraw"), ms=800)
        levels = [s["m"]["scope"] for s in samples if s["m"]["scopeZones"] == ["zone-d"]]
        self.assertTrue(levels, samples[:4])
        self.assertTrue(any(0 < level < 1 for level in levels), f"it fades in: {levels}")
        self.assertEqual(levels[-1], 1, "and ends lit")
        self.assertEqual(levels, sorted(levels), "once, never back")
        lit = [s["t"] for s in samples if s["m"]["scopeZones"] == ["zone-d"] and s["m"]["scope"] == 1]
        first = [s["t"] for s in samples if s["m"]["scopeZones"] == ["zone-d"]][0]
        self.assertLessEqual(lit[0] - first, 450, f"over about 150 ms: lit {lit[0] - first} ms after it began")
        self.wait_idle()
        samples = self.sample_around(lambda: self.point_at(None), ms=800)
        out = [s["m"]["scope"] for s in samples if s["m"]["scopeZones"] == ["zone-d"]]
        self.assertTrue(any(0 < level < 1 for level in out), f"it fades out: {out}")
        self.assertEqual(out, sorted(out, reverse=True), "once")
        self.assertEqual(samples[-1]["m"]["scopeZones"], [], "and nothing stays lit")
        self.page.set_viewport(1280, 720)


class TransitionTest(Stage3dStoryCase):
    """B, M6–M10: each transition runs once, ends in the published state, never on load."""
    # The end picture is compared pixel by pixel with a fresh load: moving loaders would differ between the two.
    strip_equipment = True

    def test_a_hazard_change_sweeps_once_and_ends_in_the_published_state(self):
        self.page.set_viewport(1280, 720)
        self.open("danger_zone")
        self.assertIsNone(self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.fxCount || null"), "nothing on load")
        samples = self.sample(ms=11000, step=30)
        with_fx = [s for s in samples if s["m"]["fx"]]
        self.assertTrue(with_fx, "the change of Участок Г was explained")
        names = with_fx[0]["fx"].split()
        for name in ("zone:zone-d", "zone:zone-c", "sensor:sens-ext-05"):
            self.assertIn(name, names, f"{name} changed in this publication")
        sweeps = [s["m"]["fx"]["sweeps"] for s in with_fx if s["m"]["fx"]["started"] and s["m"]["fx"]["sweeps"]]
        fades = [s["m"]["fx"]["fades"] for s in with_fx if s["m"]["fx"]["started"] and s["m"]["fx"]["fades"]]
        self.assertTrue(any(0 < value < 1 for sweep in sweeps for value in sweep), f"the outline swept: {sweeps[:6]}")
        self.assertTrue(any(0 < value < 1 for fade in fades for value in fade), f"the hatch faded in: {fades[:6]}")
        duration = with_fx[-1]["t"] - with_fx[0]["t"]
        self.assertLessEqual(duration, 1200, f"about 450 ms, not more: {duration} ms")
        self.assertIsNone(samples[-1]["m"]["fx"], "it ended")
        self.assertEqual(self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.fxCount"), "1", "once")
        self.wait_idle()
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(2.5)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "and nothing moves after it")
        # The end is the published state: the same pixels as the same state drawn without a transition.
        after = self.stage_pixels("after")
        self.page.goto(self.mock.url + "/")
        self.page.wait_for("document.body.dataset.boot === 'ready' && document.body.dataset.runState === 'paused'", timeout=30.0)
        self.page.wait_for("(() => { const s = document.querySelector('#stage').dataset; return Number(s.frames) > 0"
                           " && s.measuredMs !== undefined && s.rendering === 'idle'; })()", timeout=30.0)
        time.sleep(1.0)
        self.wait_idle()
        self.assertIsNone(self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.fxCount || null"), "no transition on load")
        self.assertEqual(self.stage_pixels("fresh"), after, "the transition ended exactly in the published picture")

    def stage_pixels(self, name):
        """The canvas of the overview without the HTML over it (labels and their leaders, gizmo, HUD, legend, tabs), as PNG bytes."""
        self.focus_canvas()
        self.page.press("Home")
        self.wait_idle()
        over = "'#stage-3d .s3__labels, #stage-3d .s3__leaders, #stage-3d .s3__gizmo, #stage-hud, #legend, #centre > .centre__bar'"
        self.page.evaluate(f"document.querySelectorAll({over}).forEach((n) => {{ n.style.visibility = 'hidden'; }})")
        box = self.page.evaluate("(() => { const r = document.querySelector('#stage-3d canvas').getBoundingClientRect();"
                                 " return [r.left, r.top, r.width, r.height]; })()")
        path = os.path.join(OUTPUT_DIR, f"scene3d-end-state-{name}.png")
        self.page.screenshot(path, clip=tuple(box))
        self.page.evaluate(f"document.querySelectorAll({over}).forEach((n) => {{ n.style.visibility = ''; }})")
        with open(path, "rb") as handle:
            return handle.read()

    def test_a_closed_passage_sets_its_barricade_once(self):
        self.open("no_path")
        samples = self.sample(act="app.ctx.sendCommand('condition.close_working', 'w-07')", ms=6000, step=20)
        scales = [s["m"]["fx"]["scales"] for s in samples if s["m"]["fx"] and s["m"]["fx"]["started"] and s["m"]["fx"]["scales"]]
        self.assertTrue(scales, "the barricade of В-07 was set in place")
        values = [scale[0] for scale in scales]
        self.assertGreaterEqual(min(values), 0.7)
        self.assertEqual(values, sorted(values), f"it grows once: {values}")
        names = [s["fx"] for s in samples if s["fx"]]
        self.assertIn("closed:w-07", names[0].split())
        self.assertIsNone(samples[-1]["m"]["fx"])
        self.assertFalse(self.page.evaluate("Boolean(document.querySelector('#stage-3d .s3-label.is-arriving'))"),
                         "the label appeared and stays without the transition class")
        self.assertEqual(self.page.evaluate(f"document.querySelector('#stage-3d .s3-label[data-thing-id=\"{thing('w-07')}\"]').dataset.passability"),
                         "closed")

    def test_a_route_change_fades_the_old_route_and_draws_the_new_one(self):
        self.open("paused_heartbeat")
        self.js(f"{APP}.ctx.select({json.dumps(thing('worker-03'))}); return true;")
        self.wait_idle()
        self.assertEqual(self.stage()["routes"], "1")
        samples = self.sample(act=f"app.ctx.select({json.dumps(thing('worker-04'))})", ms=900, step=20)
        ghosts = [s["m"]["ghosts"] for s in samples if s["m"]["ghosts"]]
        self.assertTrue(ghosts, "the route of Р-03 fades out")
        values = [ghost[0] for ghost in ghosts]
        self.assertEqual(values, sorted(values, reverse=True), f"once: {values}")
        self.assertTrue(any(s["m"]["drawIn"] > 0 for s in samples), "the route of Р-04 draws itself in")
        self.assertEqual(samples[-1]["m"]["ghosts"], [], "no lasting ghost")
        self.assertEqual(samples[-1]["m"]["drawIn"], 0)
        levels = [s["m"]["select"] for s in samples]
        self.assertTrue(any(0 < level < 1 for level in levels), f"the work light fades in (M10): {levels[:10]}")
        self.assertEqual(levels[-1], 1)

    def test_nothing_runs_on_load(self):
        for scenario, route in (("sensor_lost_after_danger", ""), ("paused_heartbeat", f"#/scheme?sel={thing('worker-03')}"),
                                ("no_path", "")):
            with self.subTest(scenario=scenario):
                self.open(scenario, route)
                time.sleep(1.2)
                self.wait_idle()
                motion = self.info()["motion"]
                self.assertIsNone(self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.fxCount || null"))
                self.assertEqual((motion["fx"], motion["ghosts"], motion["drawIn"], motion["select"]), (None, [], 0, 1))

    def test_no_transition_for_a_change_seen_after_old_data(self):
        self.open("danger_zone")
        self.mock.fault("http_502")
        try:
            self.page.wait_for("document.body.dataset.link === 'unavailable'", timeout=10.0)
            self.page.wait_for("document.querySelector('#stage-3d .s3').hasAttribute('data-old')", timeout=3.0)
            time.sleep(4.0)
        finally:
            self.mock.fault("none")
        samples = self.sample(ms=6000, step=30)
        self.assertTrue(any(s["m"] and s["r"] for s in samples))
        self.assertEqual([s["fx"] for s in samples if s["fx"]], [], "the change that happened meanwhile is shown at once")
        self.assertIsNone(self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.fxCount || null"))


class ReducedMotionTransitionTest(Stage3dStoryCase):
    def setUp(self):
        super().setUp()
        self.page.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})

    def test_every_transition_is_instant(self):
        self.open("danger_zone")
        samples = self.sample(ms=10000, step=30)
        self.page.wait_for("document.body.dataset.runState === 'paused'", timeout=10.0)
        self.wait_idle()
        self.assertEqual([s["fx"] for s in samples if s["fx"]], [], "no hazard transition")
        self.assertEqual(self.info()["focus"], thing("zone-d"), "the incident is framed, at once")
        frames = int(self.stage()["frames"])
        samples = self.sample(act=f"app.ctx.select({json.dumps(thing('zone-d'))}); app.ctx.hoverOption({json.dumps(thing('option-withdraw-all'))})",
                              ms=600, step=20)
        self.assertTrue(all(s["m"]["select"] == 1 and s["m"]["scope"] == 1 and not s["m"]["ghosts"] for s in samples),
                        "the work light and the scope appear at once")
        self.wait_idle()
        self.assertLessEqual(int(self.stage()["frames"]) - frames, 2, "one frame for the change")
        self.assertEqual(self.page.evaluate("document.getAnimations().length"), 0, "no CSS transition either")


class ReducedMotionLoaderTest(Stage3dStoryCase):
    strip_equipment = True

    def setUp(self):
        super().setUp()
        self.page.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})

    def test_the_stop_and_the_camera_change_at_once(self):
        self.decision()
        self.page.wait_for("document.querySelector('#stage-3d .s3').getAttribute('data-decor') === 'loaded'", timeout=20.0)
        samples = self.page.evaluate(LIGHTS % {"act": f"await app.ctx.sendCommand('action.execute_option', 'option-stop-withdraw')",
                                               "ms": 3000, "step": 15}, timeout=30.0)
        values = [s["l"]["zone-d"][1] for s in samples]
        self.assertEqual(values[-1], 0)
        self.assertTrue(all(value in (0, 1) for value in values), f"no fade under reduced motion: {values}")
        self.assertIsNone(samples[-1]["fx"])
        self.page.wait_for("document.querySelector('#stage-3d .s3').dataset.choreo === 'executing:walk:zone-d'", timeout=10.0)
        self.wait_idle()
        self.assertEqual(self.info()["focus"], thing("zone-d"), "the walk is framed, at once")
        self.assertEqual(self.page.evaluate("document.getAnimations().length"), 0, "no CSS transition either")


class LeaderTest(Stage3dStoryCase):
    """A label the decluttering pushed away from its anchor keeps a leader to its object (danger_zone at 1280x720:
    the tag of Участок Г on −380 m must not read as a tag of −320 m it may lie over)."""

    def test_pushed_labels_lead_to_their_objects(self):
        self.decision()
        found = self.js("""
          const st = (await import('/js/main.js')).app.ctx.stage;
          const svg = document.querySelector('#stage-3d .s3__leaders');
          const origin = svg.getBoundingClientRect();
          const {min, labels} = st.info().labels;
          return {min, hidden: svg.getAttribute('aria-hidden'), labels: labels.map((label) => {
            const p = label.thingId ? st.screenOf(label.thingId) : null;
            const g = svg.querySelector(`[data-leader="${CSS.escape(label.key)}"]`);
            const line = g && g.querySelector('.s3-leader__line');
            return {...label, mark: p && p.visible ? [p.x - origin.left, p.y - origin.top] : label.anchor,
              drawn: line ? ['x1', 'y1', 'x2', 'y2'].map((name) => Number(line.getAttribute(name))) : null};
          })};""")
        self.assertEqual(found["hidden"], "true", "the leaders are not read by assistive technology")
        pushed = [label for label in found["labels"] if label["off"] > found["min"]]
        self.assertTrue(pushed, f"some label is pushed away in danger_zone at 1280x720: {found['labels']}")
        for label in found["labels"]:
            with self.subTest(label=label["key"]):
                # A label in its own place may still carry a short stem (a zone's tag floating above its zone).
                if label["off"] <= found["min"] and not label["drawn"]:
                    continue
                box = label["box"]
                mark = label["mark"]
                near = [min(max(mark[0], box["x"]), box["x"] + box["w"]), min(max(mark[1], box["y"]), box["y"] + box["h"])]
                if ((near[0] - mark[0]) ** 2 + (near[1] - mark[1]) ** 2) ** 0.5 <= 4:
                    continue  # the mark touches the label: nothing to lead to
                self.assertIsNotNone(label["drawn"], f"pushed {label['off']} px from its anchor, it has a leader")
                x1, y1, x2, y2 = label["drawn"]
                self.assertLessEqual(((x2 - mark[0]) ** 2 + (y2 - mark[1]) ** 2) ** 0.5, 3.0,
                                     f"the leader ends on the object's mark {mark}: {label['drawn']}")
                # It starts on the label's edge and never runs over the label itself.
                self.assertTrue(box["x"] - 0.5 <= x1 <= box["x"] + box["w"] + 0.5 and box["y"] - 0.5 <= y1 <= box["y"] + box["h"] + 0.5)
                edge = min(abs(x1 - box["x"]), abs(x1 - box["x"] - box["w"]), abs(y1 - box["y"]), abs(y1 - box["y"] - box["h"]))
                self.assertLessEqual(edge, 0.2, f"the leader starts on the edge of {box}: {label['drawn']}")


# Samples the light of every loader (0 dark … 1 lit) every `step` ms for `ms` ms after running `act`, in the page.
LIGHTS = """(async () => {
  const app = (await import('/js/main.js')).app;
  const s3 = () => document.querySelector('#stage-3d .s3');
  const out = [];
  %(act)s;
  const t0 = performance.now();
  while (performance.now() - t0 < %(ms)d) {
    const info = app.ctx.stage.info();
    out.push({t: Math.round(performance.now() - t0), l: Object.fromEntries((info.loaders || []).map((x) => [x.zone, [x.state, x.light]])),
      w: Object.fromEntries((info.loaders || []).map((x) => [x.zone, x.world.join()])), fx: s3().dataset.loaderFxCount || null});
    await new Promise((resolve) => setTimeout(resolve, %(step)d));
  }
  return out;
})()"""

ZONES_OF = f"""(async () => {{
  const s = (await import('/js/main.js')).app.store.getState();
  return Object.fromEntries(s.model.byKind.zone.map((z) => [z.name, z.values.work_state]));
}})()"""


class LoaderTest(Stage3dStoryCase):
    """The loader of each zone: one machine per zone with workings, standing still on a free floor, its look bound to the
    zone's published work state (variant 2: the 3D model carries meaning)."""
    strip_equipment = True


    def loaders(self):
        return self.js(f"return {APP}.ctx.stage.info().loaders;")

    def wait_loaded(self):
        self.page.wait_for("document.querySelector('#stage-3d .s3').getAttribute('data-decor') === 'loaded'", timeout=20.0)
        self.wait_idle()

    def check_free(self, entry):
        state = self.js(f"""const s = {APP}.store.getState(); const w = {json.dumps(entry['working'])};
          const working = s.model.things[w];
          return {{passability: working.values.passability, zone: working.name,
            workers: s.model.byKind.worker.filter((t) => t.values.at_working === working.name).map((t) => t.values.offset_m)}};""")
        self.assertNotEqual(state["passability"], "closed", "never on a closed passage (its barricade)")
        low, high = entry["span"]
        for offset in state["workers"]:
            self.assertFalse(low - 1.5 <= offset <= high + 1.5, f"no person on its stretch: {offset} in {entry['span']}")
        return state

    def tearDown(self):
        self.page.set_viewport(1280, 720)
        super().tearDown()

    def test_one_loader_per_zone_shows_the_published_work_state_at_the_overview(self):
        self.page.set_viewport(1920, 1080)
        self.open("normal")
        self.wait_loaded()
        info = self.info()
        zones = self.js(f"""const s = {APP}.store.getState();
          return s.model.byKind.zone.filter((z) => (z.attrs.workings || []).length > 0).map((z) => [z.name, z.values.work_state]).sort();""")
        loaders = info["loaders"]
        self.assertEqual([entry["zone"] for entry in loaders], [name for name, _ in zones], "one loader per zone with workings")
        for (name, published), entry in zip(zones, loaders):
            self.assertEqual(entry["state"], published, f"{name}: the look is the published work state")
            self.assertEqual(entry["light"], 1, f"{name}: a working zone's loader has its lamps lit")
            self.assertFalse(entry["fading"])
            self.check_free(entry)
        self.assertEqual(info["loader"]["scale"], 2.5, "drawn 2.5 times larger")
        self.assertEqual(info["loader"]["lengthM"], 25)
        # Visible at the overview, inside the stage, larger than a speck.
        width, height = info["stage"]
        for entry in loaders:
            p = self.js(f"return {APP}.ctx.stage.screenOf('loader:{entry['zone']}');")
            self.assertTrue(p and p["visible"], f"{entry['zone']} at the overview: {p}")
        self.assertEqual(self.page.evaluate("document.querySelectorAll('#stage-3d .s3-label--loader').length"), 0,
                         "a working zone's loader needs no word")
        caption = self.page.evaluate("document.querySelector('[data-testid=\"scene3d-gizmo\"]').textContent")
        self.assertIn("ПДМ — символ работы участка, ×2,5", caption)
        # Its hover says what it stands for, honestly; a click selects the zone.
        p = self.js(f"return {APP}.ctx.stage.screenOf('loader:zone-d');")
        box = self.page.evaluate("(() => { const r = document.getElementById('stage-3d').getBoundingClientRect(); return [r.left, r.top]; })()")
        self.assertTrue(box[0] <= p["x"] and box[1] <= p["y"], p)
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": p["x"], "y": p["y"]})
        self.page.wait_for("!document.querySelector('#stage-3d .s3__tip').hidden", timeout=3.0)
        tip = self.page.evaluate("document.querySelector('#stage-3d .s3__tip').textContent")
        self.assertIn("Символ работы участка Г: работает · 47,5\u00a0т/ч (данные модели)", tip)
        self.assertIn("Техника в модели не описана", tip)
        self.click_at(p["x"], p["y"])
        self.wait_selected(thing("zone-d"))

    def test_a_zone_stopped_before_the_page_opened_shows_a_dark_loader_at_once(self):
        self.open("commands")
        self.wait_loaded()
        self.assertEqual(self.page.evaluate(ZONES_OF)["zone-a"], "stopped")
        loaders = {entry["zone"]: entry for entry in self.loaders()}
        self.assertEqual(loaders["zone-a"]["state"], "stopped")
        self.assertEqual(loaders["zone-a"]["light"], 0, "its lamps are dark")
        self.assertEqual(loaders["zone-b"]["light"], 1)
        self.assertIsNone(self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.loaderFxCount || null"),
                          "no fade on load: the state is shown as it is")
        sign = self.page.evaluate(f"""(() => {{ const n = document.querySelector('#stage-3d .s3-label--loader[data-zone="{thing('zone-a')}"]');
          return n && {{text: n.textContent, state: n.dataset.workState, tag: n.tagName, name: n.getAttribute('aria-label')}}; }})()""")
        self.assertIsNotNone(sign, "a stopped zone's loader carries a sign")
        self.assertEqual(sign["text"], "остановлен")
        self.assertEqual(sign["state"], "stopped")
        self.assertEqual(sign["tag"], "BUTTON")
        self.assertIn("Символ работы участка А: остановлен", sign["name"])
        self.page.click(f'#stage-3d .s3-label--loader[data-zone="{thing("zone-a")}"]')
        self.wait_selected(thing("zone-a"))

    def test_an_unknown_work_state_is_grey_with_a_question(self):
        self.open("paused_heartbeat")
        self.wait_loaded()
        # A work state outside the vocabulary (as if published by a newer model): the loader does not look normal.
        # The reads are stopped first, so that no new publication replaces the edited state while it is checked.
        self.mock.fault("http_502")
        try:
            self.page.wait_for("document.body.dataset.link !== 'ok'", timeout=10.0)
            self.js(f"""const app = {APP}; const s = app.store.getState();
              s.model.byName['zone-b'].values.work_state = 'idle_unknown_code';
              app.ctx.select({json.dumps(thing('zone-c'))}); return true;""")
            self.page.wait_for("document.querySelector('#stage-3d .s3-label--loader-unknown') !== null", timeout=5.0)
            self.wait_idle()
            loaders = {entry["zone"]: entry for entry in self.loaders()}
            self.assertEqual(loaders["zone-b"]["state"], "unknown")
            self.assertEqual(loaders["zone-b"]["light"], 0)
            text = self.page.evaluate("document.querySelector('#stage-3d .s3-label--loader-unknown').textContent")
            self.assertIn("?", text)
        finally:
            self.mock.fault("none")

    def test_the_loader_keeps_off_a_closed_passage_and_the_people_of_a_story(self):
        self.open("no_path")
        self.wait_loaded()
        self.js(f"return {APP}.ctx.sendCommand('condition.close_working', 'w-07');")
        self.page.wait_for("document.body.dataset.runState === 'paused'", timeout=15.0)
        time.sleep(1.0)
        for entry in self.loaders():
            with self.subTest(zone=entry["zone"]):
                self.check_free(entry)

    def test_the_light_quality_keeps_its_budget_with_every_loader_drawn(self):
        for width, height in ((1920, 1080), (1280, 720)):
            with self.subTest(size=f"{width}x{height}"):
                self.page.set_viewport(width, height)
                self.open("danger_zone")
                self.wait_loaded()
                info = self.info()
                self.assertEqual(info["renderer"].count("SwiftShader") > 0, True)
                self.assertEqual(len(info["loaders"]), 4)
                self.assertLessEqual(info["triangles"], 60000, f"{info['triangles']} triangles with four loaders")
                self.assertLessEqual(info["calls"], 90, f"{info['calls']} draw calls")
                self.assertLessEqual(info["loader"]["calls"], 7, "instanced: the draw calls of the loaders do not grow with the zones")
                self.assertLessEqual(info["loader"]["triangles"], 8000, "one machine is the 7 960 triangles of lhd.glb")


class LoaderLightTest(Stage3dStoryCase):
    """A stop executed from the decision turns the lights of that zone's loader off once, in about 400 ms."""
    strip_equipment = True


    def test_stop_turns_the_lights_of_that_zone_off_once(self):
        self.decision()
        self.page.wait_for("document.querySelector('#stage-3d .s3').getAttribute('data-decor') === 'loaded'", timeout=20.0)
        before = {entry["zone"]: entry["world"] for entry in self.info()["loaders"]}
        self.assertIsNone(self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.loaderFxCount || null"), "nothing on load")
        samples = self.page.evaluate(LIGHTS % {"act": f"await app.ctx.sendCommand('action.execute_option', 'option-stop-withdraw')",
                                               "ms": 4000, "step": 15}, timeout=30.0)
        lights = [(s["t"], s["l"]["zone-d"][1]) for s in samples]
        values = [value for _, value in lights]
        self.assertEqual(values[0], 1, "lit before the stop")
        self.assertEqual(values[-1], 0, "dark after it")
        self.assertTrue(any(0 < value < 1 for value in values), f"the lights fade: {values}")
        self.assertEqual(values, sorted(values, reverse=True), "once, never back")
        fading = [t for t, value in lights if 0 < value < 1]
        self.assertLessEqual(fading[-1] - fading[0], 700, f"about 400 ms: {fading[0]}…{fading[-1]} ms")
        for zone in ("zone-a", "zone-b", "zone-c"):
            self.assertTrue(all(s["l"][zone] == ["working", 1] for s in samples), f"{zone} keeps working")
        self.assertEqual(samples[-1]["l"]["zone-d"][0], "stopped")
        self.assertTrue(all(s["w"] == samples[0]["w"] for s in samples), "no loader moves")
        self.assertEqual({zone: world.split(",") for zone, world in samples[-1]["w"].items()},
                         {zone: [str(v) if v != int(v) else str(int(v)) for v in world] for zone, world in before.items()})
        self.assertEqual(samples[-1]["fx"], "1", "one fade for one change")
        self.wait_idle()
        sign = self.page.evaluate(f"document.querySelector('#stage-3d .s3-label--loader[data-zone=\"{thing('zone-d')}\"]').textContent")
        self.assertEqual(sign, "остановлен")
        # More publications of the walk: no other fade.
        time.sleep(3.0)
        self.assertEqual(self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.loaderFxCount"), "1")
        # Loaded again in this state: dark at once.
        self.page.goto(self.mock.url + "/")
        self.page.wait_for("document.body.dataset.boot === 'ready' && document.querySelector('#stage-3d .s3')"
                           " && document.querySelector('#stage-3d .s3').getAttribute('data-decor') === 'loaded'", timeout=30.0)
        time.sleep(1.0)
        self.wait_idle()
        loaders = {entry["zone"]: entry for entry in self.info()["loaders"]}
        self.assertEqual((loaders["zone-d"]["state"], loaders["zone-d"]["light"]), ("stopped", 0))
        self.assertIsNone(self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.loaderFxCount || null"), "no fade on load")


class LabelReductionTest(Stage3dStoryCase):
    """Few words on the model: horizons, one line per zone, exits and the objects in a problem state; codes on hover,
    on selection or close up."""

    SHOWN = """(() => [...document.querySelectorAll('#stage-3d .s3-label:not([data-culled])')].map((n) => ({
      kind: n.dataset.kind || null, thingId: n.dataset.thingId || null, lines: n.querySelectorAll('.s3-label__line').length,
      problem: /s3-label--(problem|indanger|noroute|unknown|closed|danger|attention)/.test(n.className) || n.classList.contains('s3-label--zone'),
      text: n.textContent})))()"""

    def shown(self):
        return self.page.evaluate(self.SHOWN)

    def tearDown(self):
        self.page.set_viewport(1280, 720)
        super().tearDown()

    def test_the_overview_names_horizons_zones_and_exits_in_one_line_each(self):
        for width, height in ((1920, 1080), (1280, 720)):
            with self.subTest(size=f"{width}x{height}"):
                self.page.set_viewport(width, height)
                self.open("normal")
                shown = self.shown()
                kinds = {entry["kind"] for entry in shown}
                self.assertTrue(kinds <= {"level", "zone", "exit"}, f"only horizons, zones and exits: {shown}")
                for entry in shown:
                    if entry["kind"] in ("zone", "exit"):
                        self.assertEqual(entry["lines"], 1, f"one line: {entry['text']}")
                zone_d = [entry["text"] for entry in shown if entry["thingId"] == thing("zone-d")]
                self.assertEqual(zone_d, ["Участок Г · внимание · 3 чел."])
                exits = sorted(entry["text"] for entry in shown if entry["kind"] == "exit")
                self.assertIn("Восстающий · вышли 0", exits)

    def test_at_a_decision_only_the_problems_are_named_and_codes_come_close_up_or_on_hover(self):
        self.page.set_viewport(1920, 1080)
        self.decision()
        shown = self.shown()
        ordinary = [entry["text"] for entry in shown if entry["kind"] in ("worker", "working", "sensor") and not entry["problem"]]
        self.assertEqual(ordinary, [], "no ordinary codes at the framing of the incident")
        problems = {entry["thingId"] for entry in shown if entry["kind"] == "worker"}
        for name in ("worker-11", "worker-12", "worker-13"):
            self.assertIn(thing(name), problems, f"{name} in danger is named")
        self.assertIn(thing("sens-ext-05"), {entry["thingId"] for entry in shown}, "the stale sensor is named")
        # Hover: the code of an ordinary person appears.
        p = self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(thing('worker-01'))});")
        self.assertTrue(p and p["visible"], p)
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": p["x"], "y": p["y"]})
        self.page.wait_for(f"(() => {{ const n = document.querySelector('#stage-3d .s3-label[data-thing-id=\"{thing('worker-01')}\"]');"
                           " return n && !n.hasAttribute('data-culled'); })()", timeout=3.0, message="the hovered person is named")
        # Close up: the codes of the workings and people near the camera.
        self.js(f"{APP}.ctx.stage.focus('loader:zone-b'); return true;")
        self.wait_idle()
        close = self.shown()
        self.assertTrue(any(entry["kind"] in ("working", "worker") and not entry["problem"] for entry in close), close)
        # The details of a zone: on its selection, and always in its tooltip and accessible name.
        zone = self.page.evaluate(f"""(() => {{ const n = document.querySelector('#stage-3d .s3-label[data-thing-id="{thing('zone-d')}"]');
          return {{lines: n.querySelectorAll('.s3-label__line').length, name: n.getAttribute('aria-label')}}; }})()""")
        self.assertEqual(zone["lines"], 1)
        self.assertIn("вход запрещён", zone["name"])
        self.js(f"{APP}.ctx.select({json.dumps(thing('zone-d'))}); return true;")
        self.page.wait_for(f"document.querySelector('#stage-3d .s3-label[data-thing-id=\"{thing('zone-d')}\"]')"
                           ".querySelectorAll('.s3-label__line').length > 1", timeout=3.0, message="the selected zone shows its details")


class ChoreographyTest(Stage3dStoryCase):
    """The camera follows the situation of the shift once per change: the decision frames the incident, the execution
    the walk, the result the overview; never on load, never against a user who moved the camera in the last 10 s."""

    def s3(self):
        return self.page.evaluate("Object.assign({}, document.querySelector('#stage-3d .s3').dataset)")

    def tearDown(self):
        self.page.set_viewport(1280, 720)
        super().tearDown()

    def test_the_camera_follows_each_situation_once(self):
        self.page.set_viewport(1920, 1080)
        self.decision()
        s3 = self.s3()
        self.assertEqual(s3.get("choreo"), "decision:zone-d")
        self.assertEqual(s3.get("choreoCount"), "1")
        self.assertEqual(self.info()["focus"], thing("zone-d"))
        self.js(f"return {APP}.ctx.sendCommand('action.execute_option', 'option-stop-withdraw');")
        self.page.wait_for("document.querySelector('#stage-3d .s3').dataset.choreo === 'executing:walk:zone-d'", timeout=15.0,
                           message="the execution frames the walk")
        self.wait_idle()
        self.assertEqual(self.s3().get("choreoCount"), "2")
        info = self.info()
        self.assertEqual(info["focus"], thing("zone-d"))
        self.assert_in_free_area(self.place("worker-11", "worker-12", "worker-13", "exit-raise"), "the people walking out and their exit")
        camera = self.camera()
        time.sleep(3.0)
        self.assertEqual(self.camera(), camera, "once: the next publications of the walk do not move the camera")
        self.assertEqual(self.s3().get("choreoCount"), "2")
        self.page.wait_for("document.body.dataset.situation === 'done'", timeout=90.0, interval=1.0, message="the walk ends")
        self.page.wait_for("document.querySelector('#stage-3d .s3').dataset.choreo === 'done:overview'", timeout=5.0)
        self.wait_idle()
        self.assertEqual(self.s3().get("choreoCount"), "3")
        self.assertTrue(self.info()["overview"], "the result is seen from the overview")

    def test_a_user_who_moved_the_camera_keeps_it(self):
        self.decision()
        self.focus_canvas()
        self.page.press("ArrowLeft")
        moved = self.wait_idle()["camera"]
        self.js(f"return {APP}.ctx.sendCommand('action.execute_option', 'option-stop-withdraw');")
        self.page.wait_for("document.querySelector('#stage-3d .s3').dataset.choreo === 'executing:skipped-touched'", timeout=15.0)
        time.sleep(1.0)
        self.wait_idle()
        self.assertEqual(self.camera()[:2], [float(v) for v in moved.split()][:2], "the user's azimuth and elevation stay")
        self.assertEqual(self.s3().get("choreoCount"), "1")

    def test_nothing_on_load(self):
        for scenario in ("paused_heartbeat", "sensor_lost_after_danger", "commands"):
            with self.subTest(scenario=scenario):
                self.open(scenario)
                time.sleep(1.5)
                self.wait_idle()
                self.assertIsNone(self.s3().get("choreo"))
                # (A panel that would hide an open incident may still refit the picture at once: not a choreography.)
                self.assertIsNone(self.s3().get("autoFramed"))


class ScenariosTest(Stage3dCase):
    mock_args = ("--publication-ms", "200")

    def test_every_story_draws_without_console_errors(self):
        for scenario in ("normal", "no_path", "sensor_lost_after_danger", "danger_zone", "paused_heartbeat", "route_segments",
                         "withdrawal_incomplete", "unknown_enum", "topology_change", "invalid_missing_id"):
            with self.subTest(scenario=scenario):
                self.open(scenario, probe=False)
                time.sleep(1.0)
                stage = self.stage()
                self.assertEqual(stage["stageMode"], "3d")
                self.assertGreater(int(stage["workersDrawn"]), 0)
        self.mock.scenario("empty")
        self.page.goto("about:blank")
        self.page.goto(self.mock.url + "/")
        self.page.wait_for("document.body.dataset.boot === 'empty'", timeout=10.0)
        time.sleep(1.0)
        self.assertEqual(self.stage().get("levels"), None, "no mine, no model drawn")


class MeasureTest(Stage3dCase):
    """Figures for the report; asserted only loosely."""

    def measure_size(self, width, height):
        self.page.set_viewport(width, height)
        stage = self.open("normal")
        first_frame = int(stage["firstFrameMs"])
        info = self.js(f"return {APP}.ctx.stage.info();")
        self.page.evaluate("window.__probe.times = []")
        self.js(f"return {APP}.ctx.stage.focus({json.dumps(thing('zone-b'))});")
        self.wait_idle()
        times = self.page.evaluate("window.__probe.times")
        deltas = [b - a for a, b in zip(times, times[1:])]
        heap = self.page.metrics().get("JSHeapUsedSize", 0) / 1e6
        # Idle: a model that publishes nothing new (paused). In `normal` the loaders of the model move by publications.
        self.open("paused_heartbeat")
        self.wait_idle()
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(5.0)
        idle = self.page.evaluate("window.__probe.raf") / 5.0
        return {
            "size": f"{width}x{height}", "renderer": info["renderer"], "first_3d_frame_ms": first_frame,
            "measured_first_frames_ms": int(stage["measuredMs"]),
            "glide_frames": len(deltas),
            "glide_frame_ms_median": round(statistics.median(deltas), 1) if deltas else None,
            "glide_frame_ms_p90": round(sorted(deltas)[int(len(deltas) * 0.9) - 1], 1) if deltas else None,
            "triangles": info["triangles"], "draw_calls": info["calls"],
            "idle_frames_per_s": idle, "js_heap_mb": round(heap, 1),
        }

    def test_measure_both_sizes(self):
        results = [self.measure_size(1280, 720), self.measure_size(1920, 1080)]
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(os.path.join(OUTPUT_DIR, "scene3d-measure.json"), "w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=1)
        print("\n" + json.dumps(results, ensure_ascii=False, indent=1))
        for result in results:
            self.assertEqual(result["idle_frames_per_s"], 0)
            self.assertLess(result["first_3d_frame_ms"], 15000)



# ---- S3b: loaders that move by the published equipment twins, and figures of people close up -------------------

# Samples, every `step` ms for `ms` ms after `act`, the published fields of every equipment twin and the loaders as the
# stage draws them: p = [at_working, offset_m, state, toward_node, loaded, from, to] of the twin (from/to: its working),
# d = [working, offset, facing, gliding] as drawn, l = [look, light, loaded] of the loader, f = the figures of people.
MACHINES = """(async () => {
  const app = (await import('/js/main.js')).app;
  const out = [];
  %(act)s;
  const t0 = performance.now();
  while (performance.now() - t0 < %(ms)d) {
    const s = app.store.getState();
    const info = app.ctx.stage.info();
    const ends = (name) => { const w = s.model.byName[name]; return w ? [w.attrs.from, w.attrs.to] : [null, null]; };
    out.push({t: Math.round(performance.now() - t0), seq: s.snapshot ? s.snapshot.seq : null, run: s.snapshot ? s.snapshot.runState : null,
      link: document.body.dataset.link,
      p: Object.fromEntries((s.model.byKind.equipment || []).map((x) => [x.name, [x.values.at_working, x.values.offset_m,
        x.values.state, x.values.toward_node, x.values.loaded === true, ...ends(x.values.at_working)]])),
      d: Object.fromEntries(info.actors.machines.map((m) => [m.name, [m.working, m.offsetM, m.facing, m.gliding]])),
      l: Object.fromEntries((info.loaders || []).map((x) => [x.zone, [x.state, x.light, x.loaded]])),
      glides: info.actors.glides, f: info.actors.figures,
      w: Object.fromEntries(s.model.byKind.worker.map((x) => [x.name, [x.values.at_working, x.values.offset_m]]))});
    await new Promise((resolve) => setTimeout(resolve, %(step)d));
  }
  return out;
})()"""

LIGHT_OF = {"working": 1, "parked": 0.35, "stopped": 0}


class EquipmentCase(Stage3dStoryCase):
    """The loaders of the model (equipment twins `lhd-*`, contract question 18)."""

    def tearDown(self):
        self.page.set_viewport(1280, 720)
        super().tearDown()

    def wait_loaded(self):
        self.page.wait_for("document.querySelector('#stage-3d .s3').getAttribute('data-decor') === 'loaded'", timeout=20.0)
        self.wait_idle()

    def machines(self, act="", ms=4000, step=20):
        return self.page.evaluate(MACHINES % {"act": act, "ms": ms, "step": step}, timeout=ms / 1000 + 30)

    def published(self):
        return self.js(f"""const s = {APP}.store.getState();
          return Object.fromEntries((s.model.byKind.equipment || []).map((x) => [x.name, x.values]));""")

    def assert_honest(self, samples, glide_expected):
        """Every drawn loader is at its published position, or on the step between the previous and the newly published
        one (never beyond either end), facing its travel while it glides and its published toward_node when it stands."""
        previous = {}
        before = {}
        glided = 0
        between = 0
        for sample in samples:
            for name, published in sample["p"].items():
                if published[0] is None or name not in sample["d"]:
                    continue
                key = (published[0], published[1])
                if before.get(name, key) != key:
                    previous[name] = before[name]
                before[name] = key
                working, offset, facing, gliding = sample["d"][name]
                if not gliding:
                    self.assertEqual((working, round(offset, 1)), (published[0], round(published[1], 1)),
                                     f"{name} stands where it is published: {sample}")
                    side = 1 if published[3] == published[6] else (-1 if published[3] == published[5] else None)
                    if side is not None:
                        self.assertEqual(facing, side, f"{name} faces its published toward_node {published[3]}")
                    continue
                glided += 1
                start = previous.get(name)
                if start and start[0] == published[0] == working:
                    low, high = sorted((start[1], published[1]))
                    self.assertTrue(low - 0.05 <= offset <= high + 0.05, f"{name} glides only between {start} and {key}: {offset}")
                    self.assertEqual(facing, 1 if published[1] > start[1] else -1, f"{name} faces its travel")
                    if low + 0.5 < offset < high - 0.5:
                        between += 1
        if glide_expected:
            self.assertGreater(glided, 0, "the loaders glide between publications")
            self.assertGreater(between, 0, "drawn between two published positions while gliding")
        else:
            self.assertEqual(glided, 0, "no glide")
        return glided

    def moved(self, samples, name=None):
        """The loaders whose published position changed during the samples."""
        out = set()
        for a, b in zip(samples, samples[1:]):
            for key, value in b["p"].items():
                if (name is None or key == name) and key in a["p"] and a["p"][key][:2] != value[:2]:
                    out.add(key)
        return out


class EquipmentTest(EquipmentCase):
    """With equipment twins the loaders are the machines of the model: each where it is published, moving only by
    publications, its lamps by its published state, a load in its bucket; hover names it, a click selects its twin."""

    def test_each_loader_of_the_model_stands_where_it_is_published_with_its_look(self):
        self.page.set_viewport(1920, 1080)
        self.open("normal")
        self.wait_loaded()
        # The drawing and the published fields, read together while no loader glides (the model runs in `normal`).
        self.page.wait_for(f"(async () => {APP}.ctx.stage.info().actors.glides === 0)()", timeout=5.0, interval=0.02)
        info, published = self.js(f"""const app = {APP}; const s = app.store.getState();
          return [app.ctx.stage.info(), Object.fromEntries((s.model.byKind.equipment || []).map((x) => [x.name, x.values]))];""")
        self.assertEqual(info["actors"]["glides"], 0)
        self.assertTrue(info["actors"]["equipment"], "the loaders are drawn from the equipment twins")
        self.assertEqual(sorted(entry["zone"] for entry in info["loaders"]), sorted(published), "one loader per equipment twin")
        self.assertEqual(len(published), 4)
        for entry in info["loaders"]:
            values = published[entry["zone"]]
            with self.subTest(machine=entry["zone"]):
                look = values.get("state") if values.get("state") in LIGHT_OF else "unknown"
                self.assertEqual(entry["state"], look, "the look is the published state")
                self.assertEqual(entry["light"], LIGHT_OF.get(look, 0))
                self.assertEqual(entry["loaded"], values.get("loaded") is True, "a published load is in the bucket")
                self.assertEqual(entry["working"], thing(values["at_working"]))
                self.assertAlmostEqual(entry["offsetM"], values["offset_m"], places=2)
                p = self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(thing(entry['zone']))});")
                self.assertTrue(p and p["visible"], f"in sight at the overview: {p}")
        caption = self.page.evaluate("document.querySelector('[data-testid=\"scene3d-gizmo\"]').textContent")
        self.assertIn("ПДМ — по данным модели, ×2,5", caption)
        self.assertEqual(self.page.evaluate("document.querySelectorAll('#stage-3d .s3-label--loader[data-zone]').length"), 0,
                         "no symbol of a zone's work: the machines are the model's")
        self.assertLessEqual(info["loader"]["calls"], 8, "instanced: the draw calls do not grow with the machines")
        self.assertEqual(list(self.page.console_errors), [])

    def test_loaders_glide_between_publications_and_never_beyond(self):
        self.open("normal")
        self.wait_loaded()
        samples = self.machines(ms=5000)
        self.assertTrue(self.moved(samples), "the published positions change in `normal`")
        self.assert_honest(samples, glide_expected=True)
        # The step of a glide ends exactly at the published position.
        self.page.wait_for(f"(async () => {APP}.ctx.stage.info().actors.glides === 0)()", timeout=3.0)

    def test_frozen_on_pause_and_at_once_on_a_failed_read(self):
        self.decision()
        self.wait_loaded()
        samples = self.machines(ms=2500, step=50)
        self.assertTrue(all(sample["run"] == "paused" for sample in samples))
        self.assertFalse(self.moved(samples), "a paused model publishes the same positions")
        self.assert_honest(samples, glide_expected=False)
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(2.0)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "no frame while paused")
        # A running model, then a failed read: the glide ends at once at the last published position, nothing moves.
        self.open("normal")
        self.wait_loaded()
        self.page.wait_for(f"(async () => {APP}.ctx.stage.info().actors.glides > 0)()", timeout=10.0, interval=0.02,
                           message="a loader glides")
        self.mock.fault("http_502")
        try:
            self.page.wait_for("document.body.dataset.link !== 'ok'", timeout=5.0)
            self.page.wait_for(f"(async () => {APP}.ctx.stage.info().actors.glides === 0)()", timeout=1.0,
                               message="the first failed read ends every glide")
            first = self.machines(ms=10, step=10)[0]
            for name, published in first["p"].items():
                self.assertEqual(first["d"][name][:2], [published[0], published[1]], f"{name} at its last published position")
            self.page.wait_for("document.querySelector('#stage-3d .s3').hasAttribute('data-old')", timeout=10.0)
            self.wait_idle(timeout=3.0)
            self.page.evaluate("window.__probe.raf = 0")
            time.sleep(2.0)
            self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "nothing moves while reads fail")
            self.assertEqual(self.machines(ms=10, step=10)[0]["d"], first["d"])
        finally:
            self.mock.fault("none")

    def test_stop_parks_that_zones_loader_dark_and_the_others_keep_working(self):
        self.decision()
        self.wait_loaded()
        zone_of = self.js(f"""const s = {APP}.store.getState();
          return Object.fromEntries((s.model.byKind.equipment || []).map((x) => [x.name, x.attrs.zone]));""")
        stopped = [name for name, zone in zone_of.items() if zone == "zone-d"]
        self.assertEqual(len(stopped), 1, zone_of)
        stopped = stopped[0]
        samples = self.machines(act="await app.ctx.sendCommand('action.execute_option', 'option-stop-withdraw')", ms=7000, step=30)
        last = samples[-1]
        self.assertEqual(last["p"][stopped][2], "stopped", "the model stops the incident zone's loader")
        self.assertEqual(last["l"][stopped][:2], ["stopped", 0], "its lamps are out")
        lights = [sample["l"][stopped][1] for sample in samples]
        self.assertEqual(lights, sorted(lights, reverse=True), f"its lights go out once: {lights}")
        first = samples[0]
        for name in zone_of:
            if name == stopped:
                continue
            self.assertEqual(last["l"][name][:2], first["l"][name][:2], f"{name} keeps its published state and light")
            self.assertEqual(last["l"][name][0], last["p"][name][2])
        self.assertTrue(self.moved(samples) - {stopped}, "the other loaders keep moving")
        self.assert_honest([sample for sample in samples if sample["run"] == "running"], glide_expected=True)

    def test_hover_names_the_loader_and_a_click_selects_its_twin(self):
        self.page.set_viewport(1920, 1080)
        self.decision()
        self.wait_loaded()
        machine = self.js(f"""const s = {APP}.store.getState();
          return (s.model.byKind.equipment || []).find((x) => x.attrs.zone === 'zone-d').name;""")
        self.js(f"return {APP}.ctx.stage.focus({json.dumps(thing(machine))});")
        self.wait_idle()
        p = self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(thing(machine))});")
        self.assertTrue(p and p["visible"], p)
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": p["x"], "y": p["y"]})
        self.page.wait_for("!document.querySelector('#stage-3d .s3__tip').hidden", timeout=3.0)
        tip = self.page.evaluate("document.querySelector('#stage-3d .s3__tip').textContent")
        label = self.js(f"return {APP}.store.getState().model.byName[{json.dumps(machine)}].label;")
        self.assertIn(f"{label} · ", tip)
        self.assertIn("· участок Г (данные модели)", tip)
        self.assertIn("по публикации модели", tip)
        self.click_at(p["x"], p["y"])
        self.wait_selected(thing(machine))
        card = self.page.evaluate("document.querySelector('.card').innerText")
        self.assertIn("техника", card)
        self.assertIn(label, card)
        self.assertIn("Участок Г", card)
        self.wait_idle()
        selected = {entry["zone"]: entry for entry in self.info()["loaders"]}[machine]
        self.assertTrue(selected["selected"], "the selected loader carries its ring on the floor")
        self.assertEqual(list(self.page.console_errors), [])

    def test_the_light_quality_keeps_its_budget_with_the_loaders_of_the_model(self):
        for width, height in ((1920, 1080), (1280, 720)):
            with self.subTest(size=f"{width}x{height}"):
                self.page.set_viewport(width, height)
                self.decision()
                self.wait_loaded()
                info = self.info()
                self.assertTrue(info["actors"]["equipment"])
                self.assertLessEqual(info["triangles"], 60000, f"{info['triangles']} triangles")
                self.assertLessEqual(info["calls"], 90, f"{info['calls']} draw calls")
                self.assertLessEqual(info["loader"]["calls"], 8)


class EquipmentReducedMotionTest(EquipmentCase):
    def setUp(self):
        super().setUp()
        self.page.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})

    def test_loaders_jump_to_each_publication(self):
        self.open("normal")
        self.wait_loaded()
        samples = self.machines(ms=4000, step=25)
        self.assertTrue(self.moved(samples))
        self.assert_honest(samples, glide_expected=False)


class EquipmentFallbackTest(EquipmentCase):
    """Without equipment twins (a stand that does not publish them) the loaders stay the static symbols of the zones."""

    def test_without_equipment_twins_the_static_symbols_of_the_zones_stay(self):
        self.page.add_init_script(STRIP_EQUIPMENT)
        self.open("normal")
        self.wait_loaded()
        self.assertEqual(self.published(), {}, "the page sees no equipment twin")
        info = self.info()
        self.assertFalse(info["actors"]["equipment"])
        self.assertEqual(info["actors"]["machines"], [])
        self.assertEqual([entry["zone"] for entry in info["loaders"]], ["zone-a", "zone-b", "zone-c", "zone-d"])
        self.assertTrue(all(entry["state"] == "working" and entry["light"] == 1 for entry in info["loaders"]))
        caption = self.page.evaluate("document.querySelector('[data-testid=\"scene3d-gizmo\"]').textContent")
        self.assertIn("ПДМ — символ работы участка, ×2,5", caption)
        worlds = [entry["world"] for entry in info["loaders"]]
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(3.0)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "nothing moves")
        self.assertEqual([entry["world"] for entry in self.info()["loaders"]], worlds)
        self.assertEqual(list(self.page.console_errors), [])


class MinerFigureTest(EquipmentCase):
    """Close up, people are small miners under their markers (the markers keep the three axes); at the overview,
    markers only. Figures move as their markers do, by published positions."""

    def figures(self):
        return self.info()["actors"]["figures"]

    def test_markers_only_at_the_overview_figures_close_up_under_the_markers(self):
        for width, height in ((1920, 1080), (1280, 720)):
            with self.subTest(size=f"{width}x{height}"):
                self.page.set_viewport(width, height)
                self.open("normal")
                self.wait_loaded()
                figures = self.figures()
                self.assertEqual(figures["shown"], 0, f"markers only at the overview: {figures}")
                self.assertLess(figures["px"], figures["threshold"])
                worker = thing("worker-11")
                at_overview = self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(worker)}).world;")
                self.js(f"return {APP}.ctx.stage.focus({json.dumps(worker)});")
                self.wait_idle()
                self.focus_canvas()
                for _ in range(2):
                    self.page.press("+")
                self.wait_idle()
                figures = self.figures()
                self.assertIn("worker-11", figures["at"], f"close up the person is a figure: {figures}")
                self.assertGreaterEqual(figures["px"], figures["threshold"])
                self.assertLessEqual(figures["triangles"], 400, "a low-poly figure")
                close = self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(worker)}).world;")
                self.assertAlmostEqual(close[1] - at_overview[1], 1.8 * 2.5 + 3.5 - 6, places=1,
                                       msg="the marker stands over the helmet of its figure")
                # The marker keeps its state: its sprite and label are still there.
                label = self.page.evaluate(f"!!document.querySelector('#stage-3d .s3-label[data-thing-id=\"{worker}\"]')")
                self.assertTrue(label)
                caption = self.page.evaluate("document.querySelector('[data-testid=\"scene3d-gizmo\"]').textContent")
                self.assertIn("фигуры людей ×2,5", caption)

    def test_figures_walk_with_their_markers_by_published_positions(self):
        self.page.set_viewport(1920, 1080)
        self.decision()
        self.wait_loaded()
        self.js(f"return {APP}.ctx.sendCommand('action.execute_option', 'option-stop-withdraw');")
        self.page.wait_for("document.body.dataset.runState === 'running'", timeout=10.0)
        walker = self.js(f"""const s = {APP}.store.getState();
          return s.model.byKind.worker.filter((x) => x.values.status === 'moving_to_exit').map((x) => x.name).sort()[0] || null;""")
        self.assertIsNotNone(walker)
        self.js(f"return {APP}.ctx.stage.focus({json.dumps(thing(walker))});")
        self.wait_idle()
        samples = self.machines(ms=4000, step=25)
        seen = [sample for sample in samples if walker in (sample["f"].get("at") or {})]
        self.assertTrue(seen, "the walker is drawn as a figure close up")
        before = None
        between = 0
        previous = None
        for sample in seen:
            published = tuple(sample["w"][walker])
            if before is not None and published != before:
                previous = before
            before = published
            working, offset, _ = sample["f"]["at"][walker]
            if previous and previous[0] == published[0] == working:
                low, high = sorted((previous[1], published[1]))
                self.assertTrue(low - 0.05 <= offset <= high + 0.05, f"never beyond the published positions: {offset} {previous} {published}")
                if low + 0.5 < offset < high - 0.5:
                    between += 1
        self.assertGreater(between, 0, "the figure glides with its marker between two publications")



class BeautyTest(Stage3dStoryCase):
    """The massif around the slabs, the light and the lamps (scene3d/environment.js): decoration that never covers the
    mine, keeps the light quality within its budget and draws nothing while idle, and under which the states stay
    distinguishable without colour."""

    def environment(self):
        return self.info()["environment"]

    def test_the_far_walls_are_never_in_front_of_the_mine_from_any_azimuth(self):
        # A model at rest (paused, heartbeat only): every frame here is one the camera asked for.
        self.open("paused_heartbeat")
        self.focus_canvas()
        seen = set()
        for turn in range(8):
            env = self.environment()
            box = env["box"]
            camera = env["camera"]
            walls = env["walls"]
            self.assertEqual(len(walls), 2, f"two far walls at a time: {walls}")
            self.assertEqual({wall[-1] for wall in walls}, {"X", "Z"}, "one per horizontal axis")
            # A wall's plane separates nothing inside the box from the camera: the camera is on its inner side.
            for wall in walls:
                axis = 0 if wall.endswith("X") else 2
                inward = 1 if wall.startswith("min") else -1
                self.assertGreater((camera[axis] - box[wall]) * inward, 0, f"turn {turn}: the camera is outside the {wall} wall")
            self.assertTrue(env["floor"], "the floor of the massif is under the camera")
            # Every object of the mine lies inside the box, so the camera sees it before the walls.
            points = self.js(f"""const app = {APP}; const s = app.store.getState();
              const ids = [...s.model.byKind.worker, ...s.model.byKind.exit, ...s.model.byKind.sensor].map((t) => t.thingId);
              return ids.map((id) => app.ctx.stage.screenOf(id)).filter(Boolean).map((p) => p.world);""")
            self.assertGreater(len(points), 10)
            for point in points:
                self.assertTrue(box["minX"] < point[0] < box["maxX"] and box["minZ"] < point[2] < box["maxZ"]
                                and box["floorY"] < point[1], f"{point} inside the massif box {box}")
            seen.update(walls)
            for _ in range(3):
                self.page.press("ArrowLeft")
                time.sleep(0.35)
            self.wait_idle()
        self.assertEqual(seen, {"minX", "maxX", "minZ", "maxZ"}, "turning the model round re-picks every wall")
        # Picking the walls asks for no frame of its own: once the camera rests nothing is drawn.
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(2.5)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "no frame while idle after turning")

    def test_the_light_quality_keeps_its_budget_at_both_sizes(self):
        for width, height in ((1920, 1080), (1280, 720)):
            with self.subTest(size=f"{width}x{height}"):
                self.page.set_viewport(width, height)
                stage = self.open("paused_heartbeat")
                self.assertEqual(stage["quality"], "low")
                info = self.info()
                env = info["environment"]
                self.assertLessEqual(info["triangles"], 60000, f"{info['triangles']} triangles")
                self.assertLessEqual(info["calls"], 90, f"{info['calls']} draw calls")
                self.assertGreater(env["lamps"], 10, "lamps along the workings")
                self.assertLessEqual(env["calls"], 6, "the massif and the lamps are a few draw calls, whatever the size of the mine")
                self.page.evaluate("window.__probe.raf = 0")
                time.sleep(3.0)
                self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "and no frame while idle")
        self.page.set_viewport(1280, 720)

    def clip_stats(self, point, size=10):
        """Mean and standard deviation of the luminance (greyscale) of a small square of the page around a point."""
        from browser_support import read_png
        path = os.path.join(OUTPUT_DIR, "beauty-clip.png")
        self.page.screenshot(path, clip=(int(point["x"]) - size // 2, int(point["y"]) - size // 2, size, size))
        image = read_png(path)
        values = [0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b, _ in (image.pixel(x, y) for y in range(image.height) for x in range(image.width))]
        return statistics.mean(values), statistics.pstdev(values)

    def floor_window(self, hazard, score, size=6, reach=70):
        """Grey statistics of the best-scoring small square near the middles of the workings of a zone in that hazard
        state: its floor found by colour (between the people and signs on it), then measured without colour."""
        from browser_support import read_png
        centre = self.js(f"""const app = {APP}; const s = app.store.getState();
          const zone = s.model.byKind.zone.find((z) => z.hazard && z.hazard.state === {json.dumps(hazard)});
          const mids = zone.attrs.workings.map((name) => app.ctx.stage.screenOf(s.model.byName[name].thingId)).filter(Boolean);
          return [mids.reduce((a, p) => a + p.x, 0) / mids.length, mids.reduce((a, p) => a + p.y, 0) / mids.length];""")
        path = os.path.join(OUTPUT_DIR, f"beauty-{hazard}.png")
        self.page.screenshot(path, clip=(int(centre[0] - reach), int(centre[1] - reach), 2 * reach, 2 * reach))
        image = read_png(path)
        pixels = [[image.pixel(x, y)[:3] for x in range(image.width)] for y in range(image.height)]
        best = None
        for y in range(0, image.height - size, 2):
            for x in range(0, image.width - size, 2):
                window = [pixels[y + j][x + i] for j in range(size) for i in range(size)]
                value = sum(score(*pixel) for pixel in window)
                if best is None or value > best[0]:
                    best = (value, window)
        self.assertGreater(best[0], size * size * 0.6, f"the {hazard} floor is found by its colour")
        values = [0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in best[1]]
        return statistics.mean(values), statistics.pstdev(values)

    def test_hazard_floors_stay_distinguishable_from_the_rock_in_greyscale(self):
        self.decision()
        # The labels are HTML over the scene: hidden here, so the pixels are the scene's own.
        self.page.evaluate("document.querySelector('#stage-3d .s3__labels').style.visibility = 'hidden'")
        self.assertTrue(self.info()["environment"]["walls"])
        # The rock of the massif beside the model.
        box = self.page.evaluate("(() => { const r = document.querySelector('#stage-3d').getBoundingClientRect(); return [r.left, r.top, r.height]; })()")
        rock = self.clip_stats({"x": box[0] + 40, "y": box[1] + box[2] * 0.5}, size=12)
        # Danger: red with its dark cross-hatch (found by the red); normal: the pale sawn floor (found by its paleness).
        danger = self.floor_window("danger", lambda r, g, b: 1 if r > 140 and r > g + 60 else 0)
        normal = self.floor_window("normal", lambda r, g, b: 1 if min(r, g, b) > 170 and max(r, g, b) - min(r, g, b) < 40 else 0)
        stats = {"rock": rock, "danger": danger, "normal": normal}
        self.assertGreater(danger[1], 14, f"the cross-hatch of danger survives without colour: {stats}")
        self.assertGreater(danger[1], rock[1] + 6, f"the hatch of danger is busier than the rock: {stats}")
        self.assertGreater(normal[0], rock[0] + 60, f"a normal floor is far paler than the rock: {stats}")
        self.assertGreater(abs(danger[0] - normal[0]), 30, f"danger and normal differ in grey: {stats}")
        self.assertLess(rock[0], 90, f"the massif stays dark behind the model: {stats}")


if __name__ == "__main__":
    unittest.main()
