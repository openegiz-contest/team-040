"""The depth rail of the stage (public/js/view/horizons.js) as the live depth instrument of the shift, in headless Chrome.

The rail at the right edge of the stage shows, from published data only: the horizons with the worst hazard of their
zones; the people as small markers at the depth where the 3D stage draws them (the same playback as the figures, so
dot and figure agree; side by side at one depth; gone when out and counted at 0 m «вышли N»). The pointer over the
gauge gives a probe line with its depth («−173 м») and the 3D stage draws a guide at that depth
(scene.setDepthProbe); a hovered horizon glows in the stage (scene.setLevelHighlight) with a chip of its published
summary; a press frames the horizon and the cursor of the rail slides there; the keyboard moves between the
horizons. Nothing moves on a pause, a failed read or a new run; reduced motion makes everything instant; nothing is
drawn while the pointer rests. The loaders of the model (CONTRACT.md §9) are small loader marks right of the axis at the
depth where the stage draws them, their state in the mark; the chip of a horizon names its loaders and the production of
its zones; an operator riding a loader is a person's dot at the machine's depth.

The scenario is sim_instability, the topology of the real simulation, where the illustrated mine is shown; the
procedural scene of variant 3 and the scheme are checked on `normal`.

    PYTHONUTF8=1 python -m unittest tests.test_depth_rail        (from team/ui)
"""

import json
import math
import time
import unittest

try:
    from .test_art_mode import CAM_FRAMES, ArtEnvCase, uncovered
    from .test_scene3d import APP, thing
except ImportError:  # run as a top-level module from the tests directory
    from test_art_mode import CAM_FRAMES, ArtEnvCase, uncovered
    from test_scene3d import APP, thing

GAUGE = "[data-testid=\"horizon-gauge\"]"

# The rail as drawn now, in viewport pixels: the gauge, its scale (from its ticks), the dots, the probe, the chip, the
# cursor; and what the stage says (people as drawn, the probe, the highlight, the focus).
RAIL = """(async () => {
  const app = (await import('/js/main.js')).app;
  const gauge = document.querySelector('[data-testid="horizon-gauge"]');
  const g = gauge.getBoundingClientRect();
  // The ticks drawn now (a short stage hides the minor ones).
  const ticks = [...gauge.querySelectorAll('.hz__tick')].filter((t) => t.getClientRects().length > 0)
    .map((t) => [Number(t.dataset.metres), t.getBoundingClientRect().top]);
  const counted = [...gauge.querySelectorAll('.hz__dot')].map((d) => d.dataset.person).sort();
  const more = [...gauge.querySelectorAll('.hz__more')].map((m) => Number(m.textContent.replace('+', '')) || 0).reduce((a, b) => a + b, 0);
  const dots = Object.fromEntries([...gauge.querySelectorAll('.hz__dot')].filter((d) => !d.hidden).map((d) => {
    const r = d.getBoundingClientRect();
    return [d.dataset.person, {z: Number(d.dataset.z), y: r.top + r.height / 2, x: r.left + r.width / 2, slot: Number(d.dataset.slot),
      egress: d.querySelector('.worker').dataset.egress || null, hazard: d.querySelector('.worker').dataset.locationHazard || null}];
  }));
  const probe = document.querySelector('[data-testid="horizon-probe"]');
  const chip = document.querySelector('[data-testid="horizon-chip"]');
  const cursor = document.querySelector('[data-testid="horizon-cursor"]');
  const out = document.querySelector('[data-testid="horizon-out"]');
  const info = app.ctx.stage.info();
  const people = app.ctx.stage.people();
  return {
    gauge: [g.left, g.top, g.width, g.height], ticks, dots, counted, more,
    probe: probe.hidden ? null : {y: probe.getBoundingClientRect().top, text: probe.textContent, z: Number(probe.dataset.z)},
    chip: chip.hidden ? null : {level: chip.dataset.level, text: chip.textContent},
    cursor: {at: cursor.dataset.at, transform: cursor.style.transform, animations: cursor.getAnimations().length},
    out: out.hidden ? null : out.textContent,
    stage: info ? {depthProbe: info.depthProbe, levelHighlight: info.levelHighlight, focus: info.focus, overview: info.overview,
      frames: info.frames, renderMs: info.renderMedianMs} : null,
    people: people ? Object.fromEntries(people.map((p) => [p.name, Math.round(p.z * 100) / 100])) : null,
    lens: document.querySelector('[data-testid="horizon-rail"]').dataset.lens || null,
    view: document.querySelector('[data-testid="horizon-rail"]').dataset.view,
  };
})()"""

# Samples the dots and the people drawn by the stage in the same moment, every `step` ms for `ms` ms (or until a
# person is out when `untilOut`).
SAMPLES = """(async () => {
  const app = (await import('/js/main.js')).app;
  const out = [];
  const t0 = performance.now();
  while (performance.now() - t0 < %(ms)d) {
    const dots = Object.fromEntries([...document.querySelectorAll('.hz__dot')].filter((d) => !d.hidden)
      .map((d) => [d.dataset.person, Number(d.dataset.z)]));
    const drawn = Object.fromEntries((app.ctx.stage.people() || []).map((p) => [p.name, Math.round(p.z * 100) / 100]));
    const s = app.store.getState();
    const gone = s.model.byKind.worker.filter((w) => w.values.status === 'out').map((w) => w.name).sort();
    const outText = document.querySelector('[data-testid="horizon-out"]');
    out.push({t: Math.round(performance.now() - t0), dots, drawn, gone, out: outText.hidden ? null : outText.textContent,
      link: document.body.dataset.link, run: s.snapshot ? s.snapshot.run : null, runState: s.snapshot ? s.snapshot.runState : null});
    if (%(untilOut)s && gone.length > 0) break;
    await new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, %(step)d)));
  }
  return out;
})()"""

# Records, in every animation frame for `ms` ms, the horizon the stage highlights and the depth of its probe.
FRAMES = """(async () => {
  const s3 = document.querySelector('#stage-3d .s3');
  const out = [];
  window.__frames = out;
  const t0 = performance.now();
  const tick = () => {
    out.push([s3.dataset.levelLit || null, s3.dataset.depthProbe || null, Number(s3.dataset.frames)]);
    if (performance.now() - t0 < %(ms)d) requestAnimationFrame(tick); else out.done = true;
  };
  requestAnimationFrame(tick);
  return true;
})()"""


class DepthRailCase(ArtEnvCase):
    # Publications every 500 ms: a withdrawal of sim_instability reaches the surface within half a minute.
    mock_args = ("--publication-ms", "500")

    def rail(self):
        return self.page.evaluate(RAIL, timeout=20)

    def move(self, x, y):
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})

    def leave(self):
        """The pointer to the middle of the canvas, off the rail."""
        x, y = self.canvas_point()
        self.move(x, y)

    @staticmethod
    def scale(rail):
        """The pixel y of an elevation on the gauge, from its ticks (linear)."""
        (z0, y0), (z1, y1) = rail["ticks"][0], rail["ticks"][-1]
        return lambda z: y0 + (z - z0) * (y1 - y0) / (z1 - z0)

    @staticmethod
    def depth_of(rail, y):
        """The whole metre under a pointer at viewport y (the rail rounds it)."""
        (z0, y0), (z1, y1) = rail["ticks"][0], rail["ticks"][-1]
        return round(z0 + (y - y0) * (z1 - z0) / (y1 - y0))

    def probe_x(self, rail):
        """A pointer x over the gauge right of the horizons (over the scale of metres)."""
        left, _, width, _ = rail["gauge"]
        return left + width - 18

    def level_point(self, name):
        return self.page.evaluate(f"""(() => {{ const r = document.querySelector('[data-testid="horizon-{name}"]').getBoundingClientRect();
          return [r.left + r.width * 0.4, r.top + r.height / 2]; }})()""")

    def start_decision(self):
        result = self.js(f"return {APP}.ctx.sendCommand('run.start_preset', 'p-instability');")
        self.assertTrue(result["ok"], result)
        self.page.wait_for("document.body.dataset.runState === 'paused'", timeout=60.0, message="the decision of sim_instability")
        time.sleep(1.0)
        self.wait_idle(timeout=20.0)

    def withdraw_all(self):
        result = self.js(f"return {APP}.ctx.sendCommand('action.execute_option', 'option-withdraw_all');")
        self.assertTrue(result["ok"], result)
        self.page.wait_for("document.body.dataset.runState === 'running'", timeout=15.0)

    def samples(self, ms, step=60, until_out=False):
        return self.page.evaluate(SAMPLES % {"ms": ms, "step": step, "untilOut": "true" if until_out else "false"}, timeout=ms / 1000 + 30)

    def assert_still(self, seconds, what):
        """Nothing in the rail and nothing in the stage moves for `seconds`: the same dots, no animation frame."""
        before = self.rail()["dots"]
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(seconds)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, f"{what}: no animation frame")
        after = self.rail()["dots"]
        self.assertEqual({name: dot["z"] for name, dot in before.items()}, {name: dot["z"] for name, dot in after.items()},
                         f"{what}: the dots stand")


class PeopleOnTheRailTest(DepthRailCase):
    def test_each_person_is_a_dot_at_the_depth_where_the_stage_draws_them(self):
        self.open_art()
        rail = self.rail()
        y_of = self.scale(rail)
        # Eight people: the six of the crews and the two operators riding their loaders (drawn at the machine's depth).
        expected = {"worker-a1": -120, "worker-a2": -120, "worker-a3": -120, "worker-a4": -120,
                    "worker-b1": -240, "worker-b2": -240, "worker-b3": -240, "worker-b4": -240}
        self.assertEqual(sorted(rail["dots"]), sorted(expected), "one dot per person underground")
        for name, dot in rail["dots"].items():
            self.assertAlmostEqual(dot["z"], expected[name], delta=0.05, msg=f"{name} at the depth of its published place")
            self.assertAlmostEqual(dot["z"], rail["people"][name], delta=0.01, msg=f"{name}: the dot and the figure agree")
            self.assertAlmostEqual(dot["y"], y_of(dot["z"]), delta=1.5, msg=f"{name}: drawn at its depth on the scale")
            self.assertEqual(dot["egress"], "ok", "the marker of the stage: reachability")
        # People at one depth sit side by side: distinct slots, no dot over another.
        for level in (-120, -240):
            row = [dot for name, dot in rail["dots"].items() if expected[name] == level]
            self.assertEqual(len({dot["slot"] for dot in row}), len(row), f"side by side at {level} m")
            xs = sorted(dot["x"] for dot in row)
            self.assertTrue(all(b - a >= 12 for a, b in zip(xs, xs[1:])), f"no dot over another at {level} m: {xs}")
        self.assertIsNone(rail["out"], "nobody is out yet: no count")
        # The zone in danger of the decision is marked at its horizon (the rail's hazard sign), consistently.
        self.start_decision()
        hazard = self.page.evaluate("document.querySelector('[data-testid=\"horizon-level-120\"]').dataset.hazard")
        zone = self.js(f"const z = {APP}.store.getState().model.byName['zone-a']; return z.hasState && z.hazard ? z.hazard.state : 'unknown';")
        self.assertIn(zone, ("danger", "attention", "unknown"), "zone A is not in norm at the decision")
        self.assertEqual(hazard, zone, "the zone not in norm is marked at its horizon")
        self.assertIsNone(self.page.evaluate("document.querySelector('[data-testid=\"horizon-level-240\"]').dataset.hazard || null"),
                          "a horizon whose zones are in norm carries no mark")
        dots = self.rail()["dots"]
        self.assertTrue(all(dots[name]["hazard"] == "danger" for name in ("worker-a1", "worker-a2", "worker-a3", "worker-a4")),
                        f"the people in the dangerous zone carry the danger ring: {dots}")

    def test_the_dots_rise_with_the_people_during_withdraw_all_and_the_out_are_counted_at_0_m(self):
        self.open_art()
        self.start_decision()
        self.withdraw_all()
        samples = self.samples(ms=50000, step=80, until_out=True)
        self.assertTrue(samples[-1]["gone"], "someone came out during the samples")
        rising = 0
        last = {}
        for sample in samples:
            for name, z in sample["dots"].items():
                self.assertIn(name, sample["drawn"], f"{name}: a dot only for a person the stage draws")
                self.assertAlmostEqual(z, sample["drawn"][name], delta=0.06, msg=f"{name}: the dot at the depth of its figure")
                if name in last:
                    self.assertGreaterEqual(z, last[name] - 0.06, f"{name} never sinks while walking out: {last[name]} -> {z}")
                last[name] = z
                if -235 < z < -5 and abs(z + 120) > 2:
                    rising += 1
        self.assertGreater(rising, 20, "the dots rise along the rail between the horizons, as the people walk the ramps")
        end = self.rail()
        gone = samples[-1]["gone"]
        for name in gone:
            self.assertNotIn(name, end["dots"], f"{name} is out: gone from the rail")
        count = self.js(f"return {APP}.store.getState().model.byKind.worker.filter((w) => w.values.status === 'out').length;")
        self.assertEqual(end["out"], f"вышли {count}", "the people who came out are counted")
        # The count stands at 0 m on the scale.
        y_of = self.scale(end)
        box = self.page.evaluate("(() => { const r = document.querySelector('[data-testid=\"horizon-out\"]').getBoundingClientRect();"
                                 " return [r.top, r.bottom]; })()")
        self.assertLess(abs((box[0] + box[1]) / 2 - y_of(0)), 26, f"«вышли N» beside 0 m: {box} vs {y_of(0)}")


MACHINES = """(async () => {
  const app = (await import('/js/main.js')).app;
  const out = [];
  const t0 = performance.now();
  while (performance.now() - t0 < %(ms)d) {
    const marks = Object.fromEntries([...document.querySelectorAll('.hz__machine')].map((m) => {
      const r = m.getBoundingClientRect();
      return [m.dataset.machine, {z: Number(m.dataset.z), y: r.top + r.height / 2, state: m.dataset.state, hazard: m.dataset.locationHazard || null,
        title: m.title}];
    }));
    const drawn = Object.fromEntries((app.ctx.stage.machines() || []).map((m) => [m.name, Math.round(m.z * 100) / 100]));
    const s = app.store.getState();
    const pub = Object.fromEntries(s.model.byKind.equipment.map((m) => [m.name, [m.values.state, m.values.location_hazard]]));
    out.push({t: Math.round(performance.now() - t0), marks, drawn, pub, runState: s.snapshot.runState});
    await new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, %(step)d)));
  }
  return out;
})()"""


class MachinesOnTheRailTest(DepthRailCase):
    """The loaders on the rail: a mark per machine at the depth where the stage draws it, its published state in it."""

    def machine_samples(self, ms, step=60):
        return self.page.evaluate(MACHINES % {"ms": ms, "step": step}, timeout=ms / 1000 + 30)

    def test_each_loader_is_a_mark_at_the_depth_where_the_stage_draws_it(self):
        self.open_art()
        self.start_decision()
        rail = self.rail()
        y_of = self.scale(rail)
        sample = self.machine_samples(ms=10, step=10)[0]
        self.assertEqual(sorted(sample["marks"]), ["lhd-a", "lhd-b"])
        for name, level in (("lhd-a", -120), ("lhd-b", -240)):
            mark = sample["marks"][name]
            self.assertAlmostEqual(mark["z"], sample["drawn"][name], delta=0.01, msg=f"{name}: the mark at the depth the stage draws it")
            self.assertAlmostEqual(mark["z"], level, delta=0.05)
            self.assertLessEqual(abs(mark["y"] - y_of(mark["z"])), 1.0, f"{name}: within 1 px of its depth on the scale")
            self.assertEqual(mark["state"], "working")
        self.assertEqual(sample["marks"]["lhd-a"]["hazard"], "danger", "the loader in the dangerous zone carries the danger ring")
        self.assertEqual(sample["marks"]["lhd-b"]["hazard"], "normal", "no ring in a zone in norm (the ring is drawn for danger only)")
        self.assertIn("ПДМ-A: везёт руду", sample["marks"]["lhd-a"]["title"])
        # The chip of level −120 names its loader and what it does, and the production of its zone.
        x, y = self.level_point("level-120")
        self.move(x, y)
        time.sleep(0.4)
        chip = self.rail()["chip"]
        self.assertEqual(chip["level"], "level-120")
        rate = self.js(f"return {APP}.store.getState().model.byName['zone-a'].values.production_rate;")
        self.assertIn("ПДМ-A: везёт руду", chip["text"])
        self.assertIn("Участок A: добыча " + f"{rate:.2f}".rstrip("0").rstrip(".").replace(".", ",") + "\u00a0т/ч", chip["text"])
        self.leave()
        # The pointer off the rail: its lens and the stage's highlight settle first.
        time.sleep(1.2)
        self.wait_idle()
        # Paused at the decision: the marks stand, no frame.
        before = self.machine_samples(ms=10, step=10)[0]["marks"]
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(2.0)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "no frame while paused")
        self.assertEqual({k: v["z"] for k, v in self.machine_samples(ms=10, step=10)[0]["marks"].items()}, {k: v["z"] for k, v in before.items()})
        # Withdraw all: the marks follow the stage in every sample, and show the stopped state.
        self.withdraw_all()
        samples = self.machine_samples(ms=6000, step=80)
        for sample in samples:
            for name, mark in sample["marks"].items():
                self.assertAlmostEqual(mark["z"], sample["drawn"][name], delta=0.06, msg=f"{name}: mark and machine agree")
                state = sample["pub"][name][0]
                self.assertEqual(mark["state"], state if state in ("working", "parked", "stopped") else "unknown")
        self.assertEqual(samples[-1]["marks"]["lhd-a"]["state"], "stopped", "a stopped loader is marked stopped")


class StillTest(DepthRailCase):
    def test_nothing_moves_on_a_pause_or_a_failed_read(self):
        self.open_art()
        self.start_decision()
        # The decision: the model is paused.
        self.assert_still(2.0, "paused at the decision")
        self.withdraw_all()
        self.page.wait_for("(() => [...document.querySelectorAll('.hz__dot')].some((d) => Number(d.dataset.z) > -119 && Number(d.dataset.z) < -100"
                           " || Number(d.dataset.z) > -239 && Number(d.dataset.z) < -200))()", timeout=40.0, interval=0.05,
                           message="people on the ramps")
        self.mock.fault("http_502")
        try:
            self.page.wait_for("document.body.dataset.link !== 'ok'", timeout=6.0)
            self.page.wait_for("document.querySelector('#stage').dataset.tweens === '0'", timeout=2.0)
            rail = self.rail()
            published = self.js(f"""const s = {APP}.store.getState();
              return Object.fromEntries(s.model.byKind.worker.filter((w) => w.values.status !== 'out').map((w) => [w.name, w.values.offset_m]));""")
            self.assertEqual(sorted(rail["dots"]), sorted(published), "every person still on the rail")
            for name, dot in rail["dots"].items():
                self.assertAlmostEqual(dot["z"], rail["people"][name], delta=0.01, msg=f"{name}: at the last published place, with its figure")
            self.page.wait_for("document.querySelector('#stage-3d .s3').hasAttribute('data-old')", timeout=10.0)
            self.wait_stage_size_settled()
            self.wait_idle(timeout=5.0)
            self.assert_still(2.0, "reads fail")
        finally:
            self.mock.fault("none")

    def test_a_new_run_clears_the_playback_and_nothing_walks_over(self):
        self.open_art()
        clears = self.info()["walk"]["clears"]
        run = self.js(f"return {APP}.store.getState().snapshot.run;")
        result = self.js(f"return {APP}.ctx.sendCommand('run.start_preset', 'p-instability');")
        self.assertTrue(result["ok"], result)
        self.page.wait_for(f"(async () => {APP}.store.getState().snapshot.run !== {json.dumps(run)})()", timeout=20.0)
        samples = [sample for sample in self.samples(ms=2500, step=60) if sample["run"] != run]
        self.assertTrue(samples)
        self.assertGreater(self.info()["walk"]["clears"], clears, "the playback was cleared for the new run")
        for sample in samples:
            self.assertEqual(sample["dots"], samples[0]["dots"], "nothing walks over from the old run")
            for name, z in sample["dots"].items():
                self.assertIn(round(z), (-120, -240), f"{name}: at its published place of the new run")
                self.assertAlmostEqual(z, sample["drawn"][name], delta=0.01)


class ProbeTest(DepthRailCase):
    def test_the_probe_reads_the_depth_under_the_pointer_and_the_stage_draws_it_there(self):
        self.open_art()
        rail = self.rail()
        x = self.probe_x(rail)
        y_of = self.scale(rail)
        frames = rail["stage"]["frames"]
        moves = 0
        for z in (-30, -95, -173, -205):
            y = y_of(z) + 0.3
            self.move(x, y)
            moves += 1
            time.sleep(0.12)
            now = self.rail()
            want = self.depth_of(rail, y)
            self.assertIsNotNone(now["probe"], "the probe line is shown")
            self.assertEqual(now["probe"]["text"], f"−{abs(want)} м", "the readout is the depth under the pointer")
            self.assertAlmostEqual(now["probe"]["y"], y_of(want), delta=1.5, msg="the probe line at that depth")
            self.assertEqual(now["stage"]["depthProbe"]["z"], want, "the stage draws its guide at the same depth")
            self.assertEqual(now["stage"]["depthProbe"]["mode"], "contour", "over the art: a contour on the rock")
            k = self.info()["art"]["k"]
            self.assertAlmostEqual(now["stage"]["depthProbe"]["y"], want * k, delta=0.01, msg="at the scene height of that depth (k of the art)")
            self.assertEqual(self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.depthProbe"), str(want))
        # The lens: the ticks near the pointer grow, those far away do not.
        lens = self.page.evaluate(f"""(() => [...document.querySelectorAll('{GAUGE} .hz__tick')].map((t) =>
          [Number(t.dataset.metres), t.firstChild.getBoundingClientRect().width / t.firstChild.offsetWidth]))()""")
        near = [grow for metres, grow in lens if abs(metres + 205) <= 6]
        far = [grow for metres, grow in lens if abs(metres + 205) >= 120]
        self.assertTrue(near and all(grow > 1.5 for grow in near), f"the ticks near the pointer magnify: {near}")
        self.assertTrue(all(abs(grow - 1) < 1e-3 for grow in far), "the ticks far away keep their size")
        # The model paused (the decision: nothing else asks for frames): one frame of the stage per pointer move, and
        # none at all while the pointer rests (the lens has settled).
        self.leave()
        self.start_decision()
        rail = self.rail()
        x = self.probe_x(rail)
        y_of = self.scale(rail)
        frames = rail["stage"]["frames"]
        moves = 0
        for z in (-40, -77, -150, -190, -201):
            self.move(x, y_of(z))
            moves += 1
            time.sleep(0.1)
        self.wait_idle()
        drawn = self.rail()["stage"]["frames"] - frames
        self.assertLessEqual(drawn, moves + 1, f"one frame per pointer move: {drawn} frames for {moves} moves")
        self.assertEqual(self.rail()["stage"]["depthProbe"]["z"], -201)
        time.sleep(0.8)
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(1.5)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "no frame while the pointer rests on the rail")
        # Off the rail: the probe goes, in the rail and in the stage; the lens closes and stops.
        self.leave()
        time.sleep(0.8)
        now = self.rail()
        self.assertIsNone(now["probe"])
        self.assertIsNone(now["stage"]["depthProbe"])
        self.assertEqual(now["lens"], "closed")
        self.assertEqual(self.page.evaluate(f"[...document.querySelectorAll('{GAUGE} .hz__tick')].filter((t) => t.style.getPropertyValue('--lens')).length"),
                         0, "every tick back to its size")
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(1.5)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "zero frames when idle")

    def test_hover_on_a_horizon_glows_its_workings_and_shows_its_summary_without_a_blink(self):
        self.open_art()
        x, y = self.level_point("level-120")
        self.move(x, y)
        time.sleep(0.4)
        rail = self.rail()
        self.assertEqual(rail["stage"]["levelHighlight"]["level"], "level-120")
        self.assertGreater(rail["stage"]["levelHighlight"]["meshes"], 0, "the outlines of its workings glow")
        self.assertIsNone(rail["stage"]["depthProbe"], "over a horizon the horizon speaks, not the probe")
        self.assertEqual(rail["chip"]["level"], "level-120")
        for words in ("Горизонт -120 м", "4 работника", "Участок A — норма", "ПДМ-A: ", "Участок A: добыча"):
            self.assertIn(words, rail["chip"]["text"])
        # Moving over the horizon and then straight onto the next one: never a frame without a highlight in between,
        # never the probe over a horizon.
        self.page.evaluate(FRAMES % {"ms": 1200})
        for dx, dy in ((4, 1), (-6, -2), (8, 2), (-3, 0)):
            self.move(x + dx, y + dy)
            time.sleep(0.05)
        x2, y2 = self.level_point("level-240")
        self.move(x2, y2)
        self.page.wait_for("window.__frames.done === true", timeout=10.0)
        frames = self.page.evaluate("window.__frames")
        lit = [entry[0] for entry in frames]
        self.assertEqual(lit[0], "level-120")
        self.assertEqual(lit[-1], "level-240")
        self.assertTrue(all(value in ("level-120", "level-240") for value in lit), f"the highlight never blinks: {sorted(set(map(str, lit)))}")
        self.assertTrue(all(entry[1] is None for entry in frames), "no probe over a horizon")
        rail = self.rail()
        self.assertEqual(rail["chip"]["level"], "level-240")
        self.assertIn("Участок B — норма", rail["chip"]["text"])
        # Off: the highlight and the chip go.
        self.leave()
        time.sleep(0.3)
        rail = self.rail()
        self.assertIsNone(rail["stage"]["levelHighlight"])
        self.assertIsNone(rail["chip"])


class FramingAndKeysTest(DepthRailCase):
    def test_a_press_frames_the_horizon_and_the_cursor_slides_there(self):
        self.open_art()
        rail = self.rail()
        self.assertEqual(rail["cursor"]["at"], "all")
        self.click_at(*self.level_point("level-240"))
        time.sleep(0.05)
        moving = self.rail()["cursor"]
        self.assertEqual(moving["at"], "level-240")
        self.assertEqual(moving["animations"], 1, "the cursor slides (one motion)")
        duration = self.page.evaluate("document.querySelector('[data-testid=\"horizon-cursor\"]').getAnimations()[0].effect.getTiming().duration")
        self.assertLessEqual(duration, 400, "at most ~400 ms")
        self.wait_idle(timeout=10.0)
        time.sleep(0.5)
        rail = self.rail()
        self.assertFalse(rail["stage"]["overview"])
        self.assertEqual(rail["stage"]["focus"], "level-240", "the camera framed the horizon")
        self.assertEqual(rail["view"], "level-240")
        self.assertEqual(rail["cursor"]["animations"], 0, "the slide has ended")
        y_of = self.scale(rail)
        top = float(rail["cursor"]["transform"].split("translateY(")[1].split("px")[0]) + rail["gauge"][1]
        self.assertAlmostEqual(top + 15, y_of(-240), delta=1.5, msg="the cursor at the horizon")
        self.assertEqual(self.page.evaluate("document.querySelector('[data-testid=\"horizon-level-240\"]').getAttribute('aria-current')"), "true")
        self.click_at(*self.page.evaluate("(() => { const r = document.querySelector('[data-testid=\"horizon-all\"]').getBoundingClientRect();"
                                          " return [r.left + r.width / 2, r.top + r.height / 2]; })()"))
        self.wait_idle(timeout=10.0)
        time.sleep(0.6)
        rail = self.rail()
        self.assertTrue(rail["stage"]["overview"], "«Все» returns to the overview")
        self.assertEqual(rail["cursor"]["at"], "all")

    def test_the_keyboard_moves_between_the_horizons_frames_and_returns(self):
        self.open_art()
        stops = self.page.evaluate("[...document.querySelectorAll('.hz__level')].filter((b) => b.tabIndex === 0).length")
        self.assertEqual(stops, 1, "the horizons are one tab stop")
        self.page.evaluate("document.querySelector('[data-testid=\"horizon-surface\"]').focus()")
        self.page.press("ArrowDown")
        time.sleep(0.2)
        focused = self.page.evaluate("document.activeElement.dataset.testid")
        self.assertEqual(focused, "horizon-level-120")
        rail = self.rail()
        self.assertEqual(rail["stage"]["levelHighlight"]["level"], "level-120", "the focused horizon glows")
        self.assertEqual(rail["chip"]["level"], "level-120", "and shows its summary")
        self.page.press("ArrowDown")
        self.page.press("ArrowDown")
        self.assertEqual(self.page.evaluate("document.activeElement.dataset.testid"), "horizon-level-240", "the last horizon holds")
        self.page.press("ArrowUp")
        self.page.press("ArrowDown")
        self.page.press("Enter")
        self.wait_idle(timeout=10.0)
        time.sleep(0.5)
        rail = self.rail()
        self.assertEqual(rail["stage"]["focus"], "level-240", "Enter frames the horizon")
        self.page.press("Escape")
        self.wait_idle(timeout=10.0)
        time.sleep(0.5)
        rail = self.rail()
        self.assertTrue(rail["stage"]["overview"], "Escape returns to the overview")
        self.assertEqual(rail["view"], "all")


class ReducedMotionRailTest(DepthRailCase):
    def setUp(self):
        super().setUp()
        self.page.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})

    def test_everything_is_instant_and_there_is_no_lens(self):
        self.open_art()
        self.start_decision()
        self.click_at(*self.level_point("level-240"))
        time.sleep(0.05)
        rail = self.rail()
        self.assertEqual(rail["cursor"]["at"], "level-240")
        self.assertEqual(rail["cursor"]["animations"], 0, "the cursor jumps")
        self.wait_idle(timeout=10.0)
        rail = self.rail()
        x = self.probe_x(rail)
        y_of = self.scale(rail)
        self.move(x, y_of(-60))
        time.sleep(0.05)
        rail = self.rail()
        self.assertEqual(rail["probe"]["text"], "−60 м", "the probe at once")
        self.assertEqual(rail["stage"]["depthProbe"]["z"], -60)
        lensed = self.page.evaluate(f"[...document.querySelectorAll('{GAUGE} .hz__tick')].filter((t) => t.style.getPropertyValue('--lens')).length")
        self.assertEqual(lensed, 0, "no lens under reduced motion")
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(1.0)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "no frame of the rail's own")


class ProceduralAndSchemeTest(DepthRailCase):
    """The rail keeps working over the procedural scene of variant 3 (another topology) and in the scheme."""

    def test_dots_and_probe_over_the_slabs_and_in_the_scheme(self):
        self.page.set_viewport(1920, 1080)
        self.open("normal")
        self.page.wait_for("document.querySelector('#stage-3d .s3').dataset.artEnv === 'off'", timeout=20.0)
        self.wait_idle()
        rail = self.rail()
        self.assertTrue(rail["dots"], "people on the rail")
        for name, dot in rail["dots"].items():
            self.assertAlmostEqual(dot["z"], rail["people"][name], delta=0.01, msg=f"{name}: with its marker in the stage")
        x = self.probe_x(rail)
        y_of = self.scale(rail)
        z = rail["ticks"][len(rail["ticks"]) // 2][0] - 3
        self.move(x, y_of(z))
        time.sleep(0.15)
        rail = self.rail()
        self.assertEqual(rail["stage"]["depthProbe"]["z"], z)
        self.assertEqual(rail["stage"]["depthProbe"]["mode"], "slice", "over the slabs: a slice at that depth")
        self.leave()
        # The scheme: no 3D stage; the dots at the published places, the probe in the rail only.
        self.click_at(*self.page.evaluate("(() => { const r = document.querySelector('[data-testid=\"stage-mode-scheme\"]').getBoundingClientRect();"
                                          " return [r.left + r.width / 2, r.top + r.height / 2]; })()"))
        self.page.wait_for("document.querySelector('#stage').dataset.stageMode === 'scheme'", timeout=10.0)
        time.sleep(0.5)
        rail = self.rail()
        self.assertIsNone(rail["stage"])
        self.assertTrue(rail["dots"], "people on the rail at their published places")
        published = self.js(f"""const s = {APP}.store.getState();
          return s.model.byKind.worker.filter((w) => w.values.status !== 'out' && typeof w.values.at_working === 'string').map((w) => w.name).sort();""")
        self.assertEqual(rail["counted"], published, "every person underground has a dot")
        self.assertEqual(len(rail["dots"]) + rail["more"], len(published), "more people at one depth than fit side by side: counted (+N)")
        self.move(self.probe_x(rail), self.scale(rail)(z))
        time.sleep(0.15)
        self.assertEqual(self.rail()["probe"]["text"], f"−{abs(z)} м", "the readout works without the 3D stage")


class FrameCostTest(DepthRailCase):
    """Measures (and loosely bounds) what the rail costs the stage: frames per pointer move, the frame time."""

    def test_frame_cost_of_the_probe(self):
        self.open_art()
        self.start_decision()
        rail = self.rail()
        x = self.probe_x(rail)
        y_of = self.scale(rail)
        frames = rail["stage"]["frames"]
        self.page.evaluate("window.__probe.times = []")
        started = time.time()
        moves = 0
        for z in range(-20, -230, -7):
            self.move(x, y_of(z))
            moves += 1
            time.sleep(0.04)
        self.leave()
        self.wait_idle()
        time.sleep(0.8)
        rail = self.rail()
        drawn = rail["stage"]["frames"] - frames
        print(f"\n[depth rail] {moves} pointer moves in {time.time() - started:.1f} s: {drawn} frames of the stage, "
              f"render median {rail['stage']['renderMs']:.1f} ms")
        self.assertLessEqual(drawn, moves + 2, "at most one frame of the stage per pointer move")
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(1.5)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "idle: zero frames")


# ---- the rail as a scroll control of the camera through depth ---------------------------------------------------------

# In every animation frame for `ms` ms: the window as drawn ([top, bottom] of its data), what the stage says it shows,
# the camera (for the coverage sampling) and the stage's frame count. window.__scroll; .done at the end.
SCROLL_FRAMES = """(async () => {
  const app = (await import('/js/main.js')).app;
  const {FOV} = await import('/js/scene3d/camera.js');
  const win = document.querySelector('[data-testid="horizon-window"]');
  const out = [];
  window.__scroll = out;
  const t0 = performance.now();
  const tick = () => {
    const v = app.ctx.stage.depthView();
    const i = app.ctx.stage.info();
    out.push({t: Math.round(performance.now() - t0), win: [Number(win.dataset.top), Number(win.dataset.bottom)],
      view: v && [v.top, v.centre, v.bottom, v.goalCentre], overview: v && v.overview, zoom: v && v.zoom, gliding: v && v.gliding,
      cam: {target: i.camera.target, dist: i.camera.dist, az: i.camera.az, el: i.camera.el, w: i.stage[0], h: i.stage[1], fov: FOV}});
    if (performance.now() - t0 < %(ms)d) requestAnimationFrame(tick); else out.done = true;
  };
  requestAnimationFrame(tick);
  return true;
})()"""

DEPTH_VIEW = f"return {APP}.ctx.stage.depthView();"


class ScrollCase(DepthRailCase):
    def view(self):
        return self.js(DEPTH_VIEW)

    def wheel(self, x, y, delta):
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": delta})

    def mouse(self, kind, x, y, pressed=False):
        params = {"type": kind, "x": x, "y": y}
        if kind != "mouseMoved" or pressed:
            params.update({"button": "left", "buttons": 1 if (pressed or kind == "mousePressed") else 0})
        if kind in ("mousePressed", "mouseReleased"):
            params["clickCount"] = 1
        self.page.send("Input.dispatchMouseEvent", params)

    @staticmethod
    def across(cam):
        """Where the camera's target lies along the screen's right (metres): the horizontal place of the view."""
        az = math.radians(cam["az"])
        return cam["target"][0] * math.cos(az) - cam["target"][2] * math.sin(az)

    def frames_while(self, act, ms=1500):
        self.page.evaluate(SCROLL_FRAMES % {"ms": ms})
        act()
        self.page.wait_for("window.__scroll.done === true", timeout=ms / 1000 + 20)
        return self.page.evaluate("window.__scroll", timeout=20)

    def rail_point(self, z):
        rail = self.rail()
        return self.probe_x(rail), self.scale(rail)(z)

    def settle(self):
        self.wait_idle(timeout=10.0)
        time.sleep(0.5)
        self.wait_idle(timeout=10.0)


class ScrollTest(ScrollCase):
    def test_the_window_spans_the_visible_depth_and_follows_every_camera_move_in_the_same_frame(self):
        self.open_art()
        view = self.view()
        self.assertTrue(view["overview"])
        self.assertGreaterEqual(view["top"], 0, "at 1× the window spans the whole mine: the surface")
        self.assertLessEqual(view["bottom"], -240, "... down to the lowest horizon")
        rail = self.rail()
        y_of = self.scale(rail)
        box = self.page.evaluate("(() => { const r = document.querySelector('[data-testid=\"horizon-window\"]').getBoundingClientRect();"
                                 " return [r.top, r.bottom]; })()")
        gauge_top, gauge_bottom = rail["gauge"][1], rail["gauge"][1] + rail["gauge"][3]
        self.assertAlmostEqual(box[0], max(y_of(view["top"]), gauge_top), delta=1.5, msg="the window's top at the depth seen at the top")
        self.assertAlmostEqual(box[1], min(y_of(view["bottom"]), gauge_bottom), delta=1.5, msg="... and its bottom")
        # A zoom and a pan of the stage itself (keys on the canvas): the window follows in the same frame, every frame.
        self.focus_canvas()
        def act():
            self.page.press("+")
            self.page.press("ArrowDown")
        frames = self.frames_while(act, ms=1500)
        moved = [f for f in frames if abs(f["view"][0] - frames[0]["view"][0]) > 0.5]
        self.assertGreater(len(moved), 3, "the camera moved over several frames")
        for f in frames:
            self.assertAlmostEqual(f["win"][0], round(f["view"][0], 1), delta=0.06, msg=f"the window's top in this frame: {f}")
            self.assertAlmostEqual(f["win"][1], round(f["view"][2], 1), delta=0.06, msg=f"the window's bottom in this frame: {f}")
        end = self.view()
        self.assertFalse(end["overview"])
        self.assertLess(end["top"] - end["bottom"], view["top"] - view["bottom"] - 50, "zoomed in: the window is shorter")

    def test_the_wheel_over_the_rail_reads_scrolls_snaps_and_returns(self):
        self.open_art()
        x, y = self.rail_point(-100)
        # At 1×: the first tick down zooms to a depth reading at the pointer's depth.
        self.wheel(x, y, 100)
        self.settle()
        view = self.view()
        self.assertAlmostEqual(view["zoom"], 2, delta=0.05, msg="a depth reading: 2×")
        self.assertAlmostEqual(view["goalCentre"], -100, delta=1.0, msg="centred on the depth under the pointer")
        across = self.across(self.frames_while(lambda: None, ms=60)[-1]["cam"])
        # Ticks down: the middle goes down monotonically, every frame on the art; at rest it settles on a horizon.
        def ticks():
            for _ in range(3):
                self.wheel(x, y, 100)
                time.sleep(0.06)
        frames = self.frames_while(ticks, ms=1600)
        centres = [f["view"][1] for f in frames]
        for a, b in zip(centres, centres[1:]):
            self.assertLessEqual(b, a + 0.05, "scrolling down never goes back up (no overshoot)")
        self.assertLess(centres[-1], -100 - 30, "it scrolled down")
        self.assertAlmostEqual(self.across(frames[-1]["cam"]), across, delta=0.01, msg="the horizontal place is kept")
        for f in frames:
            self.assertEqual(uncovered(f["cam"]), 0, f"the stage stays on the art: {f['cam']}")
        self.settle()
        view = self.view()
        nearest = min((0, -120, -240), key=lambda z: abs(z - view["goalCentre"]))
        before_snap = frames[-1]["view"][3]
        if abs(before_snap - nearest) <= 12:
            self.assertAlmostEqual(view["goalCentre"], nearest, delta=0.1, msg="the soft snap took the horizon within 12 m")
        # One tick from a horizon, then rest: back onto it (within 12 m).
        self.page.evaluate("document.querySelector('[data-testid=\"horizon-level-240\"]').focus()")
        self.page.press("End")
        self.settle()
        self.assertAlmostEqual(self.view()["goalCentre"], -240, delta=0.5)
        self.wheel(x, y, -30)
        time.sleep(0.05)
        self.assertNotAlmostEqual(self.view()["goalCentre"], -240, delta=2, msg="the tick moved it")
        self.settle()
        self.assertAlmostEqual(self.view()["goalCentre"], -240, delta=0.1, msg="at rest, the snap to the horizon")
        # Up past the top: the overview again.
        for _ in range(14):
            self.wheel(x, y, -100)
            time.sleep(0.08)
        self.settle()
        self.assertTrue(self.view()["overview"], "scrolling up past the top returns to 1×")
        self.assertAlmostEqual(self.view()["zoom"], 1, delta=0.01)

    def test_drag_the_window_1_to_1_and_click_the_track_to_glide_there(self):
        self.open_art()
        x, y = self.rail_point(-60)
        # A press on the track at the overview: a depth reading there.
        self.mouse("mouseMoved", x, y)
        self.mouse("mousePressed", x, y)
        self.mouse("mouseReleased", x, y)
        self.settle()
        view = self.view()
        self.assertAlmostEqual(view["goalCentre"], -60, delta=1.0)
        rail = self.rail()
        px_per_m = (rail["ticks"][-1][1] - rail["ticks"][0][1]) / (rail["ticks"][0][0] - rail["ticks"][-1][0])
        win = self.page.evaluate("(() => { const r = document.querySelector('[data-testid=\"horizon-window\"]').getBoundingClientRect();"
                                 " return [r.left + r.width / 2, r.top + r.height / 2]; })()")
        self.mouse("mouseMoved", win[0], win[1])
        self.mouse("mousePressed", win[0], win[1])
        for i in range(1, 11):
            self.mouse("mouseMoved", win[0], win[1] + 7 * i, pressed=True)
            time.sleep(0.03)
        time.sleep(0.3)
        dragged = self.view()
        self.assertAlmostEqual(dragged["goalCentre"], view["goalCentre"] - 70 / px_per_m, delta=0.3, msg="the camera follows the drag 1:1 in depth")
        self.assertAlmostEqual(dragged["centre"], dragged["goalCentre"], delta=0.3, msg="at once, no lag behind the pointer")
        probe = self.rail()["probe"]
        self.assertEqual(probe["z"], round(dragged["centre"]), "while dragging the probe reads the middle of the window")
        self.mouse("mouseReleased", win[0], win[1] + 70)
        self.settle()
        # A press on the track below the window: the window glides there (several frames, no overshoot).
        x, y = self.rail_point(-225)
        def press():
            self.mouse("mouseMoved", x, y)
            self.mouse("mousePressed", x, y)
            self.mouse("mouseReleased", x, y)
        frames = self.frames_while(press, ms=1400)
        centres = [f["view"][1] for f in frames]
        self.assertGreater(len([c for c in centres if abs(c - centres[0]) > 1 and abs(c - centres[-1]) > 1]), 3, "it glides")
        for a, b in zip(centres, centres[1:]):
            self.assertLessEqual(b, a + 0.05, "towards the press, never back")
        self.settle()
        self.assertAlmostEqual(self.view()["goalCentre"], -225, delta=1.0, msg="the middle of the window at the pressed depth")

    def test_page_keys_scroll_by_a_horizon_and_home_end_go_to_the_ends(self):
        self.open_art()
        self.page.evaluate("document.querySelector('[data-testid=\"horizon-level-120\"]').focus()")
        self.page.press("PageDown")
        self.settle()
        view = self.view()
        self.assertFalse(view["overview"])
        self.assertAlmostEqual(view["goalCentre"], 0, delta=12, msg="from the overview: a reading at the upper horizon (as far as the art allows)")
        start = view["goalCentre"]
        self.page.press("PageDown")
        self.settle()
        self.assertAlmostEqual(self.view()["goalCentre"], start - 120, delta=0.5, msg="one horizon spacing down")
        self.page.press("End")
        self.settle()
        self.assertAlmostEqual(self.view()["goalCentre"], -240, delta=0.5, msg="End: the lower horizon")
        self.page.press("PageUp")
        self.settle()
        self.assertAlmostEqual(self.view()["goalCentre"], -120, delta=0.5, msg="one spacing up")
        self.page.press("Home")
        self.settle()
        top = self.view()["goalCentre"]
        self.assertAlmostEqual(top, 0, delta=12, msg="Home: the upper horizon (as far as the art allows)")
        self.page.press("PageUp")
        self.settle()
        self.assertTrue(self.view()["overview"], "PageUp at the top: the overview")

    def test_scrolling_to_the_limits_keeps_the_stage_on_the_art(self):
        self.open_art()
        x, y = self.rail_point(-150)
        self.wheel(x, y, 100)
        self.settle()
        def down():
            for _ in range(16):
                self.wheel(x, y, 120)
                time.sleep(0.05)
        frames = self.frames_while(down, ms=2200)
        for f in frames:
            self.assertEqual(uncovered(f["cam"]), 0, f"no uncovered stage at the bottom limit: {f['cam']}")
        bottom = self.view()["goalCentre"]
        self.wheel(x, y, 120)
        time.sleep(0.4)
        self.assertAlmostEqual(self.view()["goalCentre"], bottom, delta=0.5, msg="the scroll stops at the covered limit")


class ScrollIdleTest(ScrollCase):
    def test_no_frame_when_idle_and_frames_only_while_the_camera_moves(self):
        self.open_art()
        self.start_decision()
        x, y = self.rail_point(-150)
        self.wheel(x, y, 100)
        self.settle()
        frames = int(self.stage()["frames"])
        self.wheel(x, y, 100)
        self.settle()
        drawn = int(self.stage()["frames"]) - frames
        self.assertGreater(drawn, 3, "a scroll glides over frames")
        self.assertLess(drawn, 90, f"and stops: {drawn} frames")
        time.sleep(0.6)
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(1.5)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "zero frames when idle")


class ScrollReducedMotionTest(ScrollCase):
    def setUp(self):
        super().setUp()
        self.page.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})

    def test_scroll_and_snap_are_instant(self):
        self.open_art()
        x, y = self.rail_point(-100)
        self.wheel(x, y, 100)
        time.sleep(0.15)
        view = self.view()
        self.assertAlmostEqual(view["centre"], view["goalCentre"], delta=0.01, msg="the reading at once")
        self.assertAlmostEqual(view["goalCentre"], -100, delta=1.0)
        frames = self.frames_while(lambda: self.wheel(x, y, 60), ms=200)
        self.assertTrue(all(not f["gliding"] for f in frames), "no glide")
        time.sleep(0.6)
        view = self.view()
        self.assertAlmostEqual(view["centre"], view["goalCentre"], delta=0.01)
        self.assertAlmostEqual(view["goalCentre"], -120, delta=0.1, msg="the snap at once")


class ScrollProceduralTest(ScrollCase):
    def test_the_procedural_scene_scrolls_too(self):
        self.page.set_viewport(1920, 1080)
        self.open("normal")
        self.page.wait_for("document.querySelector('#stage-3d .s3').dataset.artEnv === 'off'", timeout=20.0)
        self.wait_idle()
        view = self.view()
        self.assertTrue(view["overview"])
        window = self.page.evaluate("Object.assign({}, document.querySelector('[data-testid=\"horizon-window\"]').dataset)")
        self.assertIn("scroll", window, "the window is a scroll control over the slabs as well")
        x, y = self.rail_point(-320)
        self.wheel(x, y, 100)
        self.settle()
        view = self.view()
        self.assertFalse(view["overview"])
        self.assertAlmostEqual(view["goalCentre"], -320, delta=2.0, msg="a reading at the pointer's depth")
        self.wheel(x, y, 100)
        self.settle()
        self.assertLess(self.view()["goalCentre"], -320 - 5, "and a scroll down")


if __name__ == "__main__":
    unittest.main()
