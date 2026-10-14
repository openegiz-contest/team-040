"""The 3D stage (public/js/view/stage.js, public/js/scene3d/) in headless Chrome.

Chrome runs with SwiftShader, the software WebGL that the judge's machine
without a GPU is expected to resemble ("--use-angle=swiftshader
--enable-unsafe-swiftshader"). The stage mirrors its state on the stage
element (#stage, read-only): data-stage-mode, data-quality, data-renderer,
data-fallback, data-explode, data-rendering, data-levels, data-workings,
data-workers-drawn, data-camera ("azimuth elevation distance", degrees and
metres), data-frames, data-tweens, data-routes, data-measured-ms.

    PYTHONUTF8=1 python -m unittest discover -s team/ui/tests -t team/ui -p "test_scene3d.py" -v

The last test measures (and does not assert tightly) the figures reported in
the 3D section of the README; they are written to test-output/scene3d-measure.json.
"""

import json
import os
import statistics
import time
import unittest

from browser_support import OUTPUT_DIR, BrowserTestCase, MockServer, wait_until

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

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock = MockServer("normal", extra_args=cls.mock_args).start()
        cls.addClassCleanup(cls.mock.stop)

    def open(self, scenario, route="", drawn=True, probe=True, timeout=30.0):
        """Restart the scenario and load the page; wait for the first measured 3D frames when `drawn`."""
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
        self.assertLessEqual(info["calls"], 80, "and within its draw-call budget")

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
        self.assertLess(camera[2], before[2] * 0.6, "the camera came closer")
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
        (first frame, the measured frames, labels) the stage requests no animation frame at all."""
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
    """The stage keeps most of the screen at a decision, and the overview uses the room it has."""

    DOCK = """(() => {
      const box = (node) => { const r = node.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
      const dock = document.getElementById('decision-dock');
      const body = document.getElementById('decision');
      const visible = (node) => { const r = node.getBoundingClientRect(); const b = body.getBoundingClientRect();
        return r.height > 0 && r.top >= b.top - 0.5 && r.bottom <= b.bottom + 0.5; };
      const table = document.querySelector('[data-testid="decision-options"]');
      return {
        stage: box(document.getElementById('stage')), dock: box(dock), viewport: [innerWidth, innerHeight],
        rows: [...table.querySelectorAll('tbody tr:not([hidden])')].map((row) => [row.dataset.metricRow || row.dataset.row, visible(row)]),
        heads: [...table.querySelectorAll('thead th[data-column]')].map(visible),
        bars: [...table.querySelectorAll('[data-testid="people-bar"]')].map(visible),
        button: visible(document.querySelector('[data-testid="btn-execute"]')),
        more: document.querySelector('[data-testid="decision-more"]').open,
        scrolls: body.scrollHeight > body.clientHeight + 1,
      };
    })()"""

    def open_decision(self, route=""):
        self.page.set_viewport(1920, 1080)
        self.open("danger_zone", route, drawn=route == "")
        self.page.wait_for("document.body.dataset.runState === 'paused' && document.body.dataset.dock === 'open'", timeout=30.0,
                           message="the decision point unfolds the dock under the stage")
        time.sleep(1.0)
        return self.page.evaluate(self.DOCK)

    def test_with_the_dock_open_the_stage_keeps_58_percent_and_the_options_are_whole(self):
        for route in ("", "#/scheme?mode=scheme"):
            with self.subTest(mode=route or "3d"):
                got = self.open_decision(route)
                height = got["viewport"][1]
                stage = got["stage"][3] - got["stage"][1]
                self.assertGreaterEqual(stage / height, 0.58, f"the stage keeps 58 % of the height: {got['stage']}")
                self.assertAlmostEqual(got["dock"][1], got["stage"][3], delta=1, msg="the dock is under the stage")
                self.assertEqual(len(got["heads"]), 3)
                self.assertTrue(all(got["heads"]), "the three option columns are in sight")
                self.assertEqual(len(got["bars"]), 3)
                self.assertTrue(all(got["bars"]), "and their people bars")
                hidden = [name for name, shown in got["rows"] if not shown]
                self.assertEqual(hidden, [], "every metric row is in sight without scrolling")
                self.assertTrue(got["button"], "the launch is in sight")
                self.assertFalse(got["more"], "how the numbers are counted is folded")
        self.page.set_viewport(1280, 720)

    def test_the_overview_fills_the_stage_and_refits_when_the_dock_folds(self):
        self.open_decision()
        self.wait_idle()
        info = self.js(f"return {APP}.ctx.stage.info();")
        left, top, right, bottom = info["model"]
        width, height = info["stage"]
        self.assertGreaterEqual(left, 0)
        self.assertGreaterEqual(top, 0)
        self.assertLessEqual(right, width)
        self.assertLessEqual(bottom, height)
        self.assertTrue((bottom - top) / height >= 0.8 or (right - left) / width >= 0.8,
                        f"the model fills the stage in one direction: {info['model']} of {info['stage']}")
        camera = self.camera()
        self.page.click('[data-testid="dock-toggle"]')
        self.page.wait_for("document.body.dataset.dock === 'collapsed'", timeout=3.0)
        time.sleep(0.5)
        self.wait_idle()
        folded = self.js(f"return {APP}.ctx.stage.info();")
        self.assertGreater(folded["stage"][1], height + 150, "folded, the dock gives its height to the stage")
        self.assertGreater(folded["model"][3] - folded["model"][1], bottom - top, "the overview grew with the stage")
        self.assertEqual(self.camera()[:2], camera[:2], "the azimuth and the elevation are kept")
        self.page.set_viewport(1280, 720)


class LoaderTest(Stage3dCase):
    """The decorative loader: enlarged as the channels, on a free floor, shown only when it can be recognised."""

    def decor(self):
        return self.js(f"return {APP}.ctx.stage.info().decor;")

    def check_free(self, decor):
        state = self.js(f"""const s = {APP}.store.getState(); const w = {json.dumps(decor['working'])};
          const working = s.model.things[w];
          return {{passability: working.values.passability,
            workers: s.model.byKind.worker.filter((t) => t.values.at_working === working.name).map((t) => t.values.offset_m),
            routes: s.model.byKind.worker.flatMap((t) => (Array.isArray(t.values.route) ? t.values.route : [])
              .map((piece) => (typeof piece === 'string' ? piece : piece.working))).filter((name) => name === working.name).length}};""")
        self.assertNotEqual(state["passability"], "closed", "never on a closed passage (its barricade)")
        low, high = decor["span"]
        for offset in state["workers"]:
            self.assertFalse(low - 6 <= offset <= high + 6, f"no person on its stretch: {offset} in {decor['span']}")
        return state

    def test_the_loader_is_enlarged_like_the_channels_and_stands_clear_of_people(self):
        self.open("normal")
        self.page.wait_for("document.querySelector('#stage-3d .s3').getAttribute('data-decor') === 'loaded'", timeout=20.0)
        decor = self.decor()
        self.assertIsNotNone(decor, "a free place was found")
        self.assertEqual(decor["factor"], 2, "the channels are drawn twice as wide as a drift")
        self.assertEqual(decor["lengthM"], 20, "the 10 m loader is enlarged as much")
        self.assertFalse(decor["shown"], "at the overview it would be a speck: it is not drawn")
        self.check_free(decor)
        # Close to its working it is drawn, its hover says what it is, and no person marker lies on it.
        self.assertTrue(self.js(f"return {APP}.ctx.stage.focus({json.dumps(decor['working'])});"))
        self.wait_idle()
        self.assertTrue(self.decor()["shown"], "close up it is drawn")
        at = self.js(f"return {APP}.ctx.stage.screenOf('decor:loader');")
        self.assertTrue(at and at["visible"], at)
        caption = self.page.evaluate("document.querySelector('[data-testid=\"scene3d-gizmo\"]').textContent")
        self.assertIn("ПДМ — оформление, увеличена ×2", caption)
        workers = self.js(f"""const s = {APP}.store.getState(); const st = {APP}.ctx.stage;
          return s.model.byKind.worker.map((t) => st.screenOf(t.thingId)).filter((p) => p && p.visible).map((p) => [p.x, p.y]);""")
        self.assertGreater(len(workers), 0)
        nearest = min(((x - at["x"]) ** 2 + (y - at["y"]) ** 2) ** 0.5 for x, y in workers)
        self.assertGreater(nearest, 40, f"no person marker on the loader ({nearest:.0f} px away)")
        self.click_at(at["x"], at["y"])
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": at["x"] + 1, "y": at["y"]})
        self.page.wait_for("!document.querySelector('#stage-3d .s3__tip').hidden", timeout=3.0)
        tip = self.page.evaluate("document.querySelector('#stage-3d .s3__tip').textContent")
        self.assertIn("ПДМ — элемент оформления, нет данных в модели", tip)
        self.assertIn("масштаб увеличен ×2, как ширина выработок", tip)
        self.assertIsNone(self.selected(), "a click on the decor selects nothing")

    def test_the_loader_keeps_off_a_closed_passage_and_the_people_of_a_story(self):
        self.open("no_path")
        self.page.wait_for("document.querySelector('#stage-3d .s3').getAttribute('data-decor') === 'loaded'", timeout=20.0)
        self.js(f"return {APP}.ctx.sendCommand('condition.close_working', 'w-07');")
        self.page.wait_for("document.body.dataset.runState === 'paused'", timeout=15.0)
        time.sleep(1.0)
        decor = self.decor()
        if decor is not None:
            self.check_free(decor)


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
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(5.0)
        idle = self.page.evaluate("window.__probe.raf") / 5.0
        heap = self.page.metrics().get("JSHeapUsedSize", 0) / 1e6
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


if __name__ == "__main__":
    unittest.main()
