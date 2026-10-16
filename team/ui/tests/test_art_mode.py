"""Art mode of the 3D stage and the honest walk of people (mine-art SPEC §3–6), in headless Chrome.

Art mode (`?art=ortho` in the address; phase II turns it on when the art's GLB matches the topology): one
orthographic camera from a fixed direction (azimuth 12°, elevation 28° from the south), pan and zoom only, zoom
1× (the overview) to 4×, the pan clamped to the mine, every move a critically damped glide (no overshoot, it ends),
instant under reduced motion, zero frames while idle; framing, labels, picking and the scale bar as in the
perspective stage; the spread of the slabs changes no geometry.

Walking (public/js/scene3d/walk.js, both modes): a playback buffer of the publications. A person moves between
two published places along the path (one working by offset_m; across workings only along the route published with
the earlier place, else at once), never beyond the newest one, ends exactly on it, stops at once on a pause, a
failed read or old data, the buffer is cleared on a new run, a hidden page costs no frames and takes the newest
state when shown again. A figure model with a clip `walk` plays it only while its person walks, at the rate that
makes its stride match the ground speed, and fades out when the person stops (actors.js).

    PYTHONUTF8=1 python -m unittest tests.test_art_mode        (from team/ui)
"""

import base64
import json
import math
import os
import struct
import time
import unittest

try:
    from .test_scene3d import APP, STRIP_EQUIPMENT, Stage3dStoryCase, thing
except ImportError:  # run as a top-level module from the tests directory
    from test_scene3d import APP, STRIP_EQUIPMENT, Stage3dStoryCase, thing

from browser_support import MockServer  # noqa: F401  (same module object as tests.browser_support)

ART = "?art=ortho"
# The vertical factor of art mode without the art's GLB (scene.js ART_DEFAULT, SPEC §3); with the GLB its own k.
ART_DEFAULT_K = 1.35

# The camera of the stage, as info() gives it, read in one evaluation.
CAMERA = f"(async () => {{ const i = {APP}.ctx.stage.info(); return {{camera: i.camera, art: i.art, frames: i.frames}}; }})()"

# Samples the camera once per animation frame while `act` runs, until the camera has stopped for 3 frames.
GLIDE = """(async () => {
  const app = (await import('/js/main.js')).app;
  const out = [];
  %(act)s;
  await new Promise((resolve) => {
    const t0 = performance.now();
    let still = 0;
    const tick = () => {
      const c = app.ctx.stage.info().camera;
      out.push([c.dist, c.target[0], c.target[1], c.target[2], c.gliding, c.goalDist, ...c.goal]);
      still = c.gliding ? 0 : still + 1;
      if (still >= 3 || performance.now() - t0 > 6000) resolve(); else requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
  return out;
})()"""

# Samples, every `step` ms for `ms` ms, the published place of each person and where the stage draws it.
WALK = """(async () => {
  const app = (await import('/js/main.js')).app;
  const out = [];
  const t0 = performance.now();
  while (performance.now() - t0 < %(ms)d) {
    const s = app.store.getState();
    const i = app.ctx.stage.info();
    out.push({t: Math.round(performance.now() - t0), seq: s.snapshot ? s.snapshot.seq : null, run: s.snapshot ? s.snapshot.run : null,
      runState: s.snapshot ? s.snapshot.runState : null, link: document.body.dataset.link,
      pub: Object.fromEntries(s.model.byKind.worker.filter((w) => typeof w.values.at_working === 'string')
        .map((w) => [w.name, [w.values.at_working, w.values.offset_m, w.values.status]])),
      at: i.walk.at, moving: i.walk.moving, behind: i.walk.behind, snapshots: i.walk.snapshots, clears: i.walk.clears,
      tweens: Number(document.querySelector('#stage').dataset.tweens || 0), f: i.actors.figures});
    await new Promise((resolve) => setTimeout(resolve, %(step)d));
  }
  return out;
})()"""

# Hides or shows the page as a browser does for a background tab (the visibility API only).
VISIBILITY = """((hidden) => {
  Object.defineProperty(document, 'hidden', {configurable: true, get: () => hidden});
  Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => (hidden ? 'hidden' : 'visible')});
  document.dispatchEvent(new Event('visibilitychange'));
  return document.visibilityState;
})"""

# Removes the published routes of the people from every /ditto/ answer: a person who changes working then has no
# route that confirms the way, and must be shown at the new place at once.
STRIP_ROUTES = """
(() => {
  const strip = (value) => {
    if (Array.isArray(value)) return value.map(strip);
    if (value !== null && typeof value === 'object') {
      for (const key of Object.keys(value)) {
        if (key === 'route' && value[key] && typeof value[key] === 'object' && 'properties' in value[key]) value[key].properties.value = [];
        else value[key] = strip(value[key]);
      }
    }
    return value;
  };
  const original = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await original(...args);
    const url = String((args[0] && args[0].url) || args[0]);
    if (!url.includes('/ditto/')) return response;
    const body = await response.text();
    let out = body;
    try { out = JSON.stringify(strip(JSON.parse(body))); } catch (error) { /* not JSON */ }
    return new Response(out, {status: response.status, statusText: response.statusText, headers: response.headers});
  };
})();
"""


def rigged_figure_glb(stride_m=1.5, walk_s=1.0, height=1.8):
    """A minimal skinned figure (a box 0.4 × height × 0.3 m, two bones, the lower half on the leg bone) with the
    clips `walk` (a loop swinging the leg, extras.strideM) and `idle` (still), as a GLB file's bytes. It stands in
    for the art's worker.glb (SPEC §6) to test the hook of the walk cycle."""
    hip = height / 2
    xs, zs = (-0.2, 0.2), (-0.15, 0.15)
    positions, joints = [], []
    for y in (0.0, height):
        for x in xs:
            for z in zs:
                positions += [x, y, z]
                joints += [1 if y == 0.0 else 0, 0, 0, 0]
    weights = [1.0, 0.0, 0.0, 0.0] * 8
    faces = [0, 1, 3, 0, 3, 2, 4, 6, 7, 4, 7, 5, 0, 4, 5, 0, 5, 1, 2, 3, 7, 2, 7, 6, 0, 2, 6, 0, 6, 4, 1, 5, 7, 1, 7, 3]
    ibm = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -hip, 0, 1] * 2
    swing = lambda a: [0.0, 0.0, math.sin(a / 2), math.cos(a / 2)]
    walk_t = [0.0, walk_s / 2, walk_s]
    walk_q = swing(0.4) + swing(-0.4) + swing(0.4)
    idle_t = [0.0, 1.0]
    idle_q = swing(0.0) * 2
    chunks = [
        ("POSITION", struct.pack(f"<{len(positions)}f", *positions), 5126, "VEC3", 8),
        ("JOINTS", struct.pack(f"<{len(joints)}B", *joints), 5121, "VEC4", 8),
        ("WEIGHTS", struct.pack(f"<{len(weights)}f", *weights), 5126, "VEC4", 8),
        ("INDICES", struct.pack(f"<{len(faces)}H", *faces), 5123, "SCALAR", len(faces)),
        ("IBM", struct.pack(f"<{len(ibm)}f", *ibm), 5126, "MAT4", 2),
        ("WALK_T", struct.pack("<3f", *walk_t), 5126, "SCALAR", 3),
        ("WALK_Q", struct.pack("<12f", *walk_q), 5126, "VEC4", 3),
        ("IDLE_T", struct.pack("<2f", *idle_t), 5126, "SCALAR", 2),
        ("IDLE_Q", struct.pack("<8f", *idle_q), 5126, "VEC4", 2),
    ]
    blob = b""
    views, accessors = [], []
    for name, data, component, kind, count in chunks:
        while len(blob) % 4:
            blob += b"\0"
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)})
        accessor = {"bufferView": len(views) - 1, "componentType": component, "type": kind, "count": count}
        if name == "POSITION":
            accessor.update({"min": [xs[0], 0.0, zs[0]], "max": [xs[1], height, zs[1]]})
        if name in ("WALK_T", "IDLE_T"):
            values = walk_t if name == "WALK_T" else idle_t
            accessor.update({"min": [min(values)], "max": [max(values)]})
        accessors.append(accessor)
        blob += data
    while len(blob) % 4:
        blob += b"\0"
    gltf = {
        "asset": {"version": "2.0", "generator": "test_art_mode"},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [
            {"name": "figure", "children": [1, 2]},
            {"name": "hip", "translation": [0, hip, 0], "children": [3]},
            {"name": "body", "mesh": 0, "skin": 0},
            {"name": "leg"},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "JOINTS_0": 1, "WEIGHTS_0": 2}, "indices": 3, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [0.95, 0.42, 0.1, 1], "metallicFactor": 0}}],
        "skins": [{"joints": [1, 3], "inverseBindMatrices": 4, "skeleton": 1}],
        "animations": [
            {"name": "walk", "extras": {"strideM": stride_m},
             "samplers": [{"input": 5, "output": 6, "interpolation": "LINEAR"}],
             "channels": [{"sampler": 0, "target": {"node": 3, "path": "rotation"}}]},
            {"name": "idle", "samplers": [{"input": 7, "output": 8, "interpolation": "LINEAR"}],
             "channels": [{"sampler": 0, "target": {"node": 3, "path": "rotation"}}]},
        ],
        "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(blob)}],
    }
    text = json.dumps(gltf).encode("utf-8")
    while len(text) % 4:
        text += b" "
    body = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(blob), 0x004E4942) + blob
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body


def serve_figure_script(glb):
    """An init script that answers the page's request for models/miner.glb with `glb` (the rigged figure)."""
    data = base64.b64encode(glb).decode("ascii")
    return """
(() => {
  const bytes = Uint8Array.from(atob('%s'), (c) => c.charCodeAt(0));
  const original = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const url = String((args[0] && args[0].url) || args[0]);
    if (url.endsWith('/models/miner.glb')) return new Response(bytes.slice(), {status: 200, headers: {'Content-Type': 'model/gltf-binary'}});
    return original(...args);
  };
})();
""" % data


class ArtCase(Stage3dStoryCase):
    def tearDown(self):
        self.page.set_viewport(1280, 720)
        super().tearDown()

    def cam(self):
        return self.page.evaluate(CAMERA)

    def walk_samples(self, ms=4000, step=40):
        return self.page.evaluate(WALK % {"ms": ms, "step": step}, timeout=ms / 1000 + 30)

    def drag(self, start, end, button="left", steps=6):
        buttons = {"left": 1, "right": 2}[button]
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": start[0], "y": start[1]})
        self.page.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": start[0], "y": start[1], "button": button,
                                                    "buttons": buttons, "clickCount": 1})
        for i in range(1, steps + 1):
            x = start[0] + (end[0] - start[0]) * i / steps
            y = start[1] + (end[1] - start[1]) * i / steps
            self.page.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": button, "buttons": buttons})
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": end[0], "y": end[1], "button": button,
                                                    "buttons": 0, "clickCount": 1})

    def canvas_point(self):
        """A point of the canvas near the middle of the stage that no label or control covers (viewport pixels)."""
        point = self.page.evaluate("""(() => {
          const r = document.getElementById('stage-3d').getBoundingClientRect();
          for (let i = 0; i < 400; i += 1) {
            const x = r.left + r.width * (0.3 + 0.4 * ((i * 37) % 100) / 100);
            const y = r.top + r.height * (0.3 + 0.4 * ((i * 61) % 100) / 100);
            const under = document.elementFromPoint(x, y);
            if (under && under.matches('#stage-3d canvas')) return [x, y];
          }
          return null; })()""")
        self.assertIsNotNone(point, "a free point of the canvas")
        return point

    def wheel(self, x, y, delta):
        self.page.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": delta})

    def stage_box(self):
        return self.page.evaluate("(() => { const r = document.getElementById('stage-3d').getBoundingClientRect();"
                                  " return [r.left, r.top, r.width, r.height]; })()")

    def open_quiet(self, width=1280, height=720):
        """`normal` in art mode without the equipment twins: the model runs, nothing moves, no incident, no panel."""
        self.page.set_viewport(width, height)
        if not getattr(self.page, "_strip_equipment", False):
            self.page.add_init_script(STRIP_EQUIPMENT)
            self.page._strip_equipment = True
        return self.open("normal", ART)

    def home(self):
        """The overview (paused_heartbeat opens framed on its incident, beside the decision panel)."""
        self.focus_canvas()
        self.page.press("Home")
        self.wait_idle()
        return self.cam()

    def assert_view_fixed(self, camera, what):
        self.assertEqual(camera["type"], "orthographic", what)
        self.assertAlmostEqual(camera["az"], 12, places=6, msg=f"{what}: the azimuth is fixed")
        self.assertAlmostEqual(camera["el"], 28, places=6, msg=f"{what}: the elevation is fixed")
        az, el, _ = self.camera()
        self.assertEqual((az, el), (12, 28), what)


class ArtCameraTest(ArtCase):
    """Art mode: one orthographic view, pan and zoom only."""

    def test_keys_and_drags_pan_and_never_turn_the_view(self):
        self.open("paused_heartbeat", ART)
        framed = self.cam()
        self.assert_view_fixed(framed["camera"], "framing the incident beside the decision panel on load")
        self.assertTrue(1 - 1e-6 <= framed["art"]["zoom"] <= 4 + 1e-6, f"every view is in the zoom range: {framed['art']}")
        stage = self.open_quiet()
        self.assertIn("art", stage, "the stage says it is in art mode")
        start = self.home()
        self.assert_view_fixed(start["camera"], "at the overview")
        self.assertAlmostEqual(start["art"]["zoom"], 1, places=6, msg="the overview is the zoom of 1×")
        self.assertAlmostEqual(start["art"]["k"], ART_DEFAULT_K, places=6, msg="the vertical factor of the art (SPEC §3 default)")
        self.focus_canvas()
        target = start["camera"]["target"]
        for key, shift in (("ArrowLeft", False), ("ArrowUp", False), ("ArrowRight", True), ("ArrowDown", True)):
            self.page.press(key, shift=shift)
            self.wait_idle()
            camera = self.cam()["camera"]
            self.assert_view_fixed(camera, key)
            self.assertNotEqual(camera["target"], target, f"{key} pans")
            target = camera["target"]
        # Drags with either button pan: the point under the pointer follows it.
        grab = self.canvas_point()
        for button in ("left", "right"):
            point = self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(thing('zone-b'))});")
            self.drag(grab, (grab[0] + 60, grab[1] + 40), button=button)
            self.wait_idle()
            camera = self.cam()["camera"]
            self.assert_view_fixed(camera, f"after a {button} drag")
            after = self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(thing('zone-b'))});")
            self.assertAlmostEqual(after["x"] - point["x"], 60, delta=3, msg=f"the {button} drag pans with the pointer")
            self.assertAlmostEqual(after["y"] - point["y"], 40, delta=3, msg=f"the {button} drag pans with the pointer")
        # No rotation key: the keys of the settings name the pan and the zoom.
        keys = self.page.evaluate("[...document.querySelectorAll('#stage-hud .hud__keys-body dd')].map((n) => n.textContent).join(' | ')")
        self.assertNotIn("повернуть", keys)
        self.assertIn("сдвинуть", keys)

    def test_zoom_stays_between_the_overview_and_four_times(self):
        self.open_quiet()
        self.home()
        for _ in range(10):
            self.page.press("+")
        self.wait_idle()
        art = self.cam()["art"]
        self.assertAlmostEqual(art["zoom"], 4, places=4, msg="+ stops at 4×")
        for _ in range(12):
            self.page.press("-")
        self.wait_idle()
        art = self.cam()["art"]
        self.assertAlmostEqual(art["zoom"], 1, places=4, msg="- stops at the overview")
        # The wheel zooms towards the pointer: the point under it stays under it (a point of the scene seen near the
        # pointer moves away from it by the zoom factor, as seen from the pointer).
        grab = self.canvas_point()
        point = self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(thing('zone-d'))});")
        for _ in range(3):
            self.wheel(grab[0], grab[1], -120)
        self.wait_idle()
        after = self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(thing('zone-d'))});")
        zoom = self.cam()["art"]["zoom"]
        self.assertGreater(zoom, 1.3, "the wheel zooms in")
        self.assertAlmostEqual(after["x"] - grab[0], (point["x"] - grab[0]) * zoom, delta=3, msg="towards the pointer")
        self.assertAlmostEqual(after["y"] - grab[1], (point["y"] - grab[1]) * zoom, delta=3, msg="towards the pointer")
        for _ in range(20):
            self.wheel(grab[0], grab[1], -200)
        self.wait_idle()
        self.assertLessEqual(self.cam()["art"]["zoom"], 4 + 1e-6, "the wheel stops at 4×")

    def test_the_pan_stays_over_the_mine(self):
        self.open_quiet()
        self.home()
        for _ in range(4):
            self.page.press("+")
        for key, side in (("ArrowRight", "maxU"), ("ArrowLeft", "minU"), ("ArrowUp", "maxV"), ("ArrowDown", "minV")):
            for _ in range(40):
                self.page.press(key)
            self.wait_idle()
            pan = self.cam()["art"]["pan"]
            box = pan["box"]
            self.assertTrue(box["minU"] - 1e-6 <= pan["u"] <= box["maxU"] + 1e-6 and box["minV"] - 1e-6 <= pan["v"] <= box["maxV"] + 1e-6,
                            f"{key}: the target stays over the mine: {pan}")
            value = pan["u"] if side.endswith("U") else pan["v"]
            self.assertAlmostEqual(value, box[side], places=3, msg=f"{key} ends at the edge of the mine ({side})")

    def test_a_glide_to_a_zone_never_overshoots_and_ends(self):
        """Glides to a zone, a level and a person (art mode frames a zone at up to 3x, a person at 4x)."""
        self.open_quiet(1920, 1080)
        self.home()
        for target in (thing("zone-b"), "level-380", thing("worker-11")):
            with self.subTest(target=target):
                self.check_glide(target)

    def check_glide(self, target):
        before = self.cam()["camera"]
        samples = self.page.evaluate(GLIDE % {"act": f"app.ctx.stage.focus({json.dumps(target)})"}, timeout=30)
        final = samples[-1]
        moved = final[:4] != [before["dist"], *before["target"]]
        if moved:
            self.assertGreaterEqual(len(samples), 8, "it glides over several frames")
        self.assertFalse(final[4], "the glide ended")
        goal = [final[5], final[6], final[7], final[8]]
        self.assertEqual(final[:4], goal, "it ends exactly on its goal")
        for index in range(4):
            values = [sample[index] for sample in samples]
            sign = math.copysign(1, values[0] - goal[index]) if values[0] != goal[index] else 0
            for a, b in zip(values, values[1:]):
                self.assertGreaterEqual(abs(a - goal[index]) + 1e-9, abs(b - goal[index]), f"component {index} approaches monotonically")
                if b != goal[index]:
                    self.assertEqual(math.copysign(1, b - goal[index]), sign, f"component {index} never crosses its goal")
        if target.endswith("worker-11"):
            self.assertAlmostEqual(self.cam()["art"]["zoom"], 4, places=4, msg="a person with a small surrounding, at 4x (the figures are part of the picture)")
        self.assertTrue(1 - 1e-6 <= self.cam()["art"]["zoom"] <= 4 + 1e-6)
        self.wait_idle()
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(1.5)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "no frame after the glide (no idle drift)")
        self.assertEqual(self.cam()["camera"]["target"], final[1:4], "the camera stays where the glide ended")

    def test_home_returns_to_the_overview(self):
        self.open_quiet()
        overview = self.home()["camera"]
        self.page.press("+")
        self.page.press("+")
        self.page.press("ArrowLeft")
        self.wait_idle()
        self.assertNotEqual(self.cam()["camera"]["dist"], overview["dist"])
        self.page.press("Home")
        self.wait_idle()
        camera = self.cam()["camera"]
        self.assertAlmostEqual(camera["dist"], overview["dist"], places=6)
        for a, b in zip(camera["target"], overview["target"]):
            self.assertAlmostEqual(a, b, places=6, msg="Home restores the overview")
        self.assertAlmostEqual(self.cam()["art"]["zoom"], 1, places=6)

    def test_no_frame_while_nothing_changes(self):
        self.open("paused_heartbeat", ART)
        self.wait_idle()
        seq = int(self.body()["seq"])
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(5.0)
        self.assertGreaterEqual(int(self.body()["seq"]) - seq, 4, "the page went on polling")
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "no animation frame while nothing changes")
        # A running model with still people (no equipment twins: their loaders move by publications).
        self.page.add_init_script(STRIP_EQUIPMENT)
        self.open("normal", ART)
        self.wait_idle()
        tick = int(self.body()["tick"])
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(4.0)
        self.assertGreater(int(self.body()["tick"]), tick)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "still people draw nothing")

    def test_the_spread_of_the_slabs_changes_no_geometry(self):
        self.open_quiet()
        hidden = self.page.evaluate("[document.querySelector('[data-testid=\"stage-explode\"]').closest('label').hidden,"
                                    " document.querySelector('[data-testid=\"stage-explode-toggle\"]').hidden]")
        self.assertEqual(hidden, [True, True], "the spread control is not offered in art mode")
        before = self.info()
        self.focus_canvas()
        self.page.press("e")
        self.js(f"document.getElementById('stage-explode').value = '10';"
                " document.getElementById('stage-explode').dispatchEvent(new Event('input')); return true;")
        time.sleep(0.8)
        self.wait_idle()
        after = self.info()
        self.assertAlmostEqual(after["art"]["k"], ART_DEFAULT_K, places=6)
        self.assertEqual([level["screenY"] for level in after["levels"]], [level["screenY"] for level in before["levels"]],
                         "the horizons stay where they are")
        self.assertEqual(after["model"], before["model"])

    def test_labels_picking_and_the_scale_bar(self):
        self.open_quiet()
        # Labels: placed in the stage.
        labels = self.page.evaluate("""(() => { const box = document.getElementById('stage-3d').getBoundingClientRect();
          return [...document.querySelectorAll('#stage-3d .s3-label:not([data-culled])')].map((n) => n.getBoundingClientRect())
            .filter((r) => r.width > 0).map((r) => [r.left - box.left, r.top - box.top, r.right - box.left, r.bottom - box.top]); })()""")
        _, _, width, height = self.stage_box()
        self.assertGreaterEqual(len(labels), 5, "labels are shown")
        for left, top, right, bottom in labels:
            self.assertTrue(left >= -1 and top >= -1 and right <= width + 1 and bottom <= height + 1, f"a label in the stage: {labels}")
        # Picking: a person by the marker, a working by its channel.
        worker = thing("worker-12")
        point = self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(worker)});")
        self.assertTrue(point and point["visible"], point)
        self.click_at(point["x"], point["y"])
        self.wait_selected(worker)
        # A working whose middle no label covers (the labels are buttons over the canvas).
        found = self.js(f"""const app = {APP}; const s = app.store.getState();
          const marks = [...s.model.byKind.worker, ...s.model.byKind.exit, ...s.model.byKind.sensor]
            .map((t) => app.ctx.stage.screenOf(t.thingId)).filter(Boolean);
          for (const name of ['w-30', 'w-12', 'w-10', 'w-27', 'w-19', 'w-06', 'w-08', 'w-11', 'w-26', 'w-29']) {{
            const p = app.ctx.stage.screenOf('{thing("")}' + name);
            const under = p && document.elementFromPoint(p.x, p.y + 2);
            const clear = p && marks.every((m) => Math.hypot(m.x - p.x, m.y - p.y) > 45);
            if (p && p.visible && clear && under && under.matches('#stage-3d canvas')) return [name, p.x, p.y + 2];
          }} return null;""")
        self.assertIsNotNone(found, "a working clear of the labels")
        self.click_at(found[1], found[2])
        self.wait_selected(thing(found[0]))
        # The scale bar: one scale for the whole orthographic view.
        bar = self.page.evaluate("""(() => ({w: document.querySelector('#stage-3d .s3__bar').getBoundingClientRect().width,
          text: document.querySelector('#stage-3d .s3__bar-text').textContent}))()""")
        metres = float(bar["text"].split()[0].replace(" ", "").replace(",", "."))
        camera = self.cam()["camera"]
        per_metre = height / (2 * camera["dist"] * math.tan(math.radians(15)))
        self.assertAlmostEqual(bar["w"], metres * per_metre, delta=1.5, msg=f"the scale bar measures the view: {bar}")


class ArtFramingTest(ArtCase):
    """«показать» and the decision panel in art mode: the zone and its people in the free part of the stage."""

    def test_show_keeps_the_zone_and_its_people_beside_the_panel(self):
        self.page.set_viewport(1280, 720)
        self.decision("danger_zone", ART)
        self.page.wait_for("document.body.dataset.panel === 'shown'", timeout=5.0)
        self.focus_canvas()
        self.page.press("Home")
        self.wait_idle()
        zone = thing("zone-d")
        self.js(f"{APP}.ctx.stage.focus({json.dumps(zone)}); return true;")
        self.wait_idle()
        info = self.info()
        self.assertEqual(info["focus"], zone)
        self.assertGreaterEqual(info["art"]["zoom"], 1 - 1e-9)
        self.assertLessEqual(info["art"]["zoom"], 4 + 1e-9)
        self.assert_in_free_area(self.place("w-23", "w-24", "w-25", "worker-11", "worker-12", "worker-13"), "zone and people beside the panel")
        under = self.page.evaluate("""(() => {
          const panel = document.getElementById('panel').getBoundingClientRect();
          return [...document.querySelectorAll('#stage-3d .s3-label:not([data-culled])')].map((n) => n.getBoundingClientRect())
            .filter((r) => r.right > panel.left + 1).length; })()""")
        self.assertEqual(under, 0, "the labels keep clear of the panel")


class ArtReducedMotionTest(ArtCase):
    def setUp(self):
        super().setUp()
        self.page.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})

    def test_every_camera_move_is_instant(self):
        self.open_quiet()
        self.home()
        for act in (f"app.ctx.stage.focus({json.dumps(thing('worker-11'))})", "app.ctx.stage.overview()"):
            samples = self.page.evaluate(GLIDE % {"act": act}, timeout=30)
            self.assertFalse(any(sample[4] for sample in samples), f"no glide: {act}")
            self.assertEqual(samples[0][:4], samples[-1][:4], "the first frame is already the end")
        self.focus_canvas()
        frames = int(self.stage()["frames"])
        self.page.press("+")
        self.page.press("ArrowRight")
        self.wait_idle()
        self.assertLessEqual(int(self.stage()["frames"]) - frames, 3, "keys move the camera at once")


# ---- walking -------------------------------------------------------------------------------------------------------

class WalkUnitTest(ArtCase):
    """walk.js on its own, in the page (ES module), with a small layout and a hand clock."""

    def test_the_playback_buffer(self):
        self.open("paused_heartbeat", drawn=False)
        result = self.js("""
          const {createWalk, legBetween, MAX_STEP_M} = await import('/js/scene3d/walk.js');
          const line = (name, from, to, lengthM) => [name, {name, from, to, lengthM}];
          const layout = {workings: new Map([line('a', 'n1', 'n2', 50), line('b', 'n2', 'n3', 40), line('c', 'n4', 'n2', 30)])};
          const out = {};
          const seg = (working, from, to) => ({working, from, to});
          out.same = legBetween(layout, {working: 'a', offsetM: 10}, {working: 'a', offsetM: 22.5}, null);
          out.noRoute = legBetween(layout, {working: 'a', offsetM: 45}, {working: 'b', offsetM: 7.5}, null);
          out.route = legBetween(layout, {working: 'a', offsetM: 45}, {working: 'b', offsetM: 7.5}, [seg('a', 'n1', 'n2'), seg('b', 'n2', 'n3')]);
          out.reverse = legBetween(layout, {working: 'a', offsetM: 45}, {working: 'c', offsetM: 22.5}, [seg('a', 'n1', 'n2'), seg('c', 'n2', 'n4')]);
          out.otherWay = legBetween(layout, {working: 'a', offsetM: 45}, {working: 'b', offsetM: 7.5}, [seg('a', 'n1', 'n2'), seg('c', 'n2', 'n4')]);
          out.backwards = legBetween(layout, {working: 'a', offsetM: 45}, {working: 'b', offsetM: 7.5}, [seg('a', 'n2', 'n1'), seg('b', 'n2', 'n3')]);
          out.atNode = legBetween(layout, {working: 'a', offsetM: 50}, {working: 'b', offsetM: 7.5}, [seg('b', 'n2', 'n3')]);
          out.offsets = legBetween(layout, {working: 'a', offsetM: 45}, {working: 'b', offsetM: 7.5},
            [{working: 'a', from: 'n1', to: 'n2', from_offset_m: 45, to_offset_m: 50, fromOffsetM: 45, toOffsetM: 50}, {...seg('b', 'n2', 'n3'), fromOffsetM: 0, toOffsetM: 7.5}]);
          out.long = legBetween(layout, {working: 'a', offsetM: 0}, {working: 'b', offsetM: 40}, [seg('a', 'n1', 'n2'), seg('b', 'n2', 'n3')]);
          out.maxStep = MAX_STEP_M;
          // Playback with a hand clock: publications every 1000 ms, frames every 16 ms.
          const w = createWalk();
          const pub = (at, places, routes = {}) => w.publish(layout, {at, places: new Map(Object.entries(places)),
            routes: new Map(Object.entries(routes))}, true);
          pub(0, {p: {working: 'a', offsetM: 10}, q: {working: 'a', offsetM: 45}});
          out.first = w.place('p');
          out.walking = pub(1000, {p: {working: 'a', offsetM: 22.5}, q: {working: 'b', offsetM: 7.5}});
          out.jumpAtOnce = w.place('q');
          const track = [];
          for (let now = 1000; now <= 2300; now += 16) {
            w.step(now);
            const p = w.place('p');
            track.push([now, p.offsetM, p.facing, p.moving]);
          }
          out.track = track;
          out.after = w.place('p');
          out.stepAfter = w.step(2400);
          // A walk on, then across workings along the route published with the earlier place.
          pub(3000, {p: {working: 'a', offsetM: 45}, q: {working: 'b', offsetM: 7.5}}, {p: [seg('a', 'n1', 'n2'), seg('b', 'n2', 'n3')]});
          for (let now = 3000; now <= 5200; now += 16) w.step(now);
          out.reached45 = w.place('p');
          pub(6000, {p: {working: 'b', offsetM: 7.5}, q: {working: 'b', offsetM: 7.5}}, {p: [seg('b', 'n2', 'n3')]});
          const cross = [];
          for (let now = 6000; now <= 9500; now += 16) {
            w.step(now);
            const p = w.place('p');
            cross.push([p.working, p.offsetM]);
          }
          out.cross = cross;
          // Snap: everyone at the newest place at once; clear: nothing left.
          pub(10000, {p: {working: 'b', offsetM: 20}}, {p: [seg('b', 'n2', 'n3')]});
          w.step(10016);
          out.midway = w.place('p');
          out.snapped = w.snap();
          out.afterSnap = w.place('p');
          w.clear();
          out.cleared = [w.place('p'), w.info(11000).snapshots, w.info(11000).clears];
          // Not allowed (pause, old data, reduced motion): the place is taken at once.
          w.publish(layout, {at: 12000, places: new Map([['p', {working: 'a', offsetM: 5}]]), routes: new Map()}, true);
          w.publish(layout, {at: 13000, places: new Map([['p', {working: 'a', offsetM: 15}]]), routes: new Map()}, false);
          out.notAllowed = [w.place('p'), w.step(13016)];
          return out;
        """)
        self.assertEqual(result["same"], {"pieces": [{"working": "a", "start": 10, "end": 22.5}], "length": 12.5})
        self.assertIsNone(result["noRoute"], "across workings without a route: no path")
        self.assertEqual(result["route"]["pieces"], [{"working": "a", "start": 45, "end": 50}, {"working": "b", "start": 0, "end": 7.5}])
        self.assertAlmostEqual(result["route"]["length"], 12.5)
        self.assertEqual(result["reverse"]["pieces"], [{"working": "a", "start": 45, "end": 50}, {"working": "c", "start": 30, "end": 22.5}])
        self.assertIsNone(result["otherWay"], "a route that does not reach the later working confirms nothing")
        self.assertIsNone(result["backwards"], "a route away from the later place confirms nothing")
        self.assertEqual(result["atNode"]["pieces"], [{"working": "b", "start": 0, "end": 7.5}], "from the node where the route begins")
        self.assertEqual(result["offsets"]["pieces"], [{"working": "a", "start": 45, "end": 50}, {"working": "b", "start": 0, "end": 7.5}])
        self.assertIsNone(result["long"], f"longer than {result['maxStep']} m: a jump")
        self.assertEqual(result["first"]["offsetM"], 10)
        self.assertTrue(result["walking"])
        self.assertEqual([result["jumpAtOnce"]["working"], result["jumpAtOnce"]["offsetM"]], ["b", 7.5], "without a route: at once")
        track = result["track"]
        offsets = [entry[1] for entry in track]
        self.assertEqual(offsets[0], 10, "the walk starts where the person was drawn")
        self.assertTrue(all(b >= a for a, b in zip(offsets, offsets[1:])), "monotonic along the working")
        self.assertTrue(any(10.5 < value < 22 for value in offsets), "drawn between the two published places")
        self.assertEqual(offsets[-1], 22.5, "it ends exactly at the published place")
        self.assertTrue(all(value <= 22.5 for value in offsets), "never beyond the newest publication")
        self.assertTrue(all(entry[2] == 1 for entry in track), "facing the travel")
        self.assertFalse(result["after"]["moving"])
        self.assertFalse(result["stepAfter"], "no frames once it stands")
        self.assertEqual([result["reached45"]["working"], result["reached45"]["offsetM"]], ["a", 45])
        cross = result["cross"]
        self.assertIn("a", [entry[0] for entry in cross])
        self.assertIn("b", [entry[0] for entry in cross])
        first_b = [entry[0] for entry in cross].index("b")
        self.assertTrue(all(entry[0] == "a" for entry in cross[:first_b]) and all(entry[0] == "b" for entry in cross[first_b:]),
                        f"along the route: first a to its end, then b: {cross}")
        self.assertTrue(all(entry[1] >= 45 for entry in cross[:first_b]))
        self.assertEqual(cross[-1], ["b", 7.5])
        self.assertTrue(result["midway"]["moving"])
        self.assertTrue(result["snapped"])
        self.assertEqual([result["afterSnap"]["offsetM"], result["afterSnap"]["moving"]], [20, False], "snap: the newest place at once")
        self.assertEqual(result["cleared"][:2], [None, 0], "clear forgets everything")
        self.assertEqual(result["notAllowed"][0]["offsetM"], 15)
        self.assertFalse(result["notAllowed"][1])


class WalkTest(ArtCase):
    """People walk by publications in the stage (art mode here; the perspective stage uses the same buffer)."""

    route = ART

    def withdraw(self):
        """detour: close В-12 and execute «stop and withdraw»: four people walk out of zone B."""
        self.open("detour", self.route)
        result = self.js(f"return {APP}.ctx.sendCommand('condition.close_working', 'w-12');")
        self.assertTrue(result["ok"], result)
        self.page.wait_for("document.body.dataset.runState === 'paused'", timeout=10.0)
        self.page.wait_for("(async () => { const s = (await import('/js/main.js')).app.store.getState();"
                           " const o = s.model.byName['option-stop-withdraw']; return o && o.values.state === 'offered'; })()",
                           timeout=10.0)
        result = self.js(f"return {APP}.ctx.sendCommand('action.execute_option', 'option-stop-withdraw');")
        self.assertTrue(result["ok"], result)
        self.page.wait_for("document.body.dataset.runState === 'running'", timeout=10.0)

    def check_honest(self, samples):
        """Every drawn place is a published place or lies on the way between the previous and the newest published one;
        on one working it moves monotonically from the earlier towards the later. Returns how many samples were between."""
        previous, newest, last_drawn = {}, {}, {}
        between = 0
        for sample in samples:
            for name, published in sample["pub"].items():
                key = (published[0], published[1])
                if newest.get(name, key) != key:
                    previous[name] = newest[name]
                newest[name] = key
                drawn = sample["at"].get(name)
                if drawn is None:
                    continue
                working, offset, facing, moving = drawn
                start = previous.get(name)
                if start and start[0] == key[0] == working:
                    low, high = sorted((start[1], key[1]))
                    self.assertTrue(low - 1e-6 <= offset <= high + 1e-6, f"{name}: {offset} between {start} and {key}")
                    if low + 0.3 < offset < high - 0.3:
                        between += 1
                        self.assertEqual(facing, 1 if key[1] > start[1] else -1, f"{name} faces its travel")
                    before = last_drawn.get(name)
                    if before and before[0] == working:
                        direction = 1 if key[1] >= start[1] else -1
                        self.assertGreaterEqual((offset - before[1]) * direction, -1e-6, f"{name} never walks back: {before} -> {drawn}")
                elif not start and sample["runState"] == "running":
                    pass
                last_drawn[name] = (working, offset)
        return between

    def test_a_person_walks_along_a_working_and_ends_exactly_at_the_published_place(self):
        self.withdraw()
        samples = self.walk_samples(ms=4500, step=30)
        between = self.check_honest(samples)
        self.assertGreater(between, 10, "drawn between two publications while walking")
        self.assertTrue(any(sample["tweens"] > 0 for sample in samples), "the stage says people walk")
        # Publications stop (a read that hangs): the walk reaches the newest published place exactly and stops there
        # before the data are declared old; nothing is extrapolated.
        self.mock.fault("hang")
        try:
            samples = self.walk_samples(ms=1900, step=25)
            last = samples[-1]
            fresh = [sample for sample in samples if sample["link"] == "ok" and sample["seq"] == last["seq"] and sample["t"] >= 1200]
            self.assertTrue(fresh, "samples after the walk had time to end, before the data are old")
            for sample in fresh:
                for name, published in sample["pub"].items():
                    drawn = sample["at"].get(name)
                    if drawn is None or published[2] == "out":
                        continue
                    self.assertEqual((drawn[0], drawn[1]), (published[0], published[1]), f"{name} ends exactly on its published place")
                    self.assertFalse(drawn[3], f"{name} stands")
            self.assertTrue(all(sample["tweens"] == 0 for sample in fresh))
        finally:
            self.mock.fault("none")

    def test_a_change_of_working_follows_the_published_route(self):
        self.withdraw()
        samples = self.walk_samples(ms=9000, step=40)
        self.check_honest(samples)
        # A person drawn on its earlier working while the newest publication has it on the next one: walking to the node.
        crossing = [sample for sample in samples for name, drawn in sample["at"].items()
                    if drawn and name in sample["pub"] and drawn[0] != sample["pub"][name][0] and drawn[3]]
        self.assertTrue(crossing, "someone walked from one working onto the next along the route")

    def test_nothing_moves_on_a_pause_or_a_failed_read(self):
        self.withdraw()
        self.page.wait_for(f"(async () => {APP}.ctx.stage.info().walk.moving.length > 0)()", timeout=10.0, interval=0.02)
        self.mock.fault("http_502")
        try:
            self.page.wait_for("document.body.dataset.link !== 'ok'", timeout=5.0)
            self.page.wait_for("document.querySelector('#stage').dataset.tweens === '0'", timeout=1.0,
                               message="the first failed read stops every walk")
            sample = self.walk_samples(ms=10, step=10)[0]
            for name, published in sample["pub"].items():
                drawn = sample["at"].get(name)
                if drawn:
                    self.assertEqual((drawn[0], drawn[1]), (published[0], published[1]), f"{name} at the last published place")
            self.page.wait_for("document.querySelector('#stage-3d .s3').hasAttribute('data-old')", timeout=10.0)
            self.wait_stage_size_settled()
            self.wait_idle(timeout=3.0)
            self.page.evaluate("window.__probe.raf = 0")
            time.sleep(2.0)
            self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "nothing moves while reads fail")
        finally:
            self.mock.fault("none")
        # A paused model: the decision of danger_zone.
        self.decision("danger_zone", self.route)
        samples = self.walk_samples(ms=2000, step=50)
        self.assertTrue(all(sample["runState"] == "paused" for sample in samples))
        self.assertTrue(all(not sample["moving"] and sample["tweens"] == 0 for sample in samples), "nobody walks while paused")
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(2.0)
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "no frame while paused")

    def test_a_jump_across_workings_without_a_route_is_instant(self):
        self.page.add_init_script(STRIP_ROUTES)
        self.withdraw()
        routes = self.js(f"return {APP}.store.getState().model.byKind.worker.map((w) => (w.values.route || []).length);")
        self.assertEqual(set(routes), {0}, "the routes are removed")
        samples = self.walk_samples(ms=9000, step=30)
        changes = 0
        for sample in samples:
            for name, drawn in sample["at"].items():
                published = sample["pub"].get(name)
                if not drawn or not published:
                    continue
                if drawn[0] != published[0]:
                    self.fail(f"{name} drawn on {drawn[0]} while published on {published[0]}: no route confirms a way between")
        for a, b in zip(samples, samples[1:]):
            for name, drawn in b["at"].items():
                before = a["at"].get(name)
                if drawn and before and drawn[0] != before[0]:
                    changes += 1
                    self.assertEqual((drawn[0], drawn[1]), tuple(b["pub"][name][:2]), "the new place is taken at once")
        self.assertGreater(changes, 0, "someone changed working during the samples")

    def test_a_new_run_clears_the_buffer(self):
        self.open("detour", self.route)
        clears = self.walk_samples(ms=10, step=10)[0]["clears"]
        run = self.js(f"return {APP}.store.getState().snapshot.run;")
        result = self.js(f"return {APP}.ctx.sendCommand('run.start_preset', 'p-detour');")
        self.assertTrue(result["ok"], result)
        self.page.wait_for(f"(async () => {APP}.store.getState().snapshot.run !== {json.dumps(run)})()", timeout=15.0)
        samples = self.walk_samples(ms=1500, step=30)
        self.assertGreater(samples[-1]["clears"], clears, "the buffer was cleared for the new run")
        for sample in samples:
            self.assertFalse(sample["moving"], "nothing walks over from the old run")

    def test_a_hidden_page_costs_no_frames_and_shows_the_newest_state_when_back(self):
        self.withdraw()
        self.page.wait_for(f"(async () => {APP}.ctx.stage.info().walk.moving.length > 0)()", timeout=10.0, interval=0.02)
        self.assertEqual(self.page.evaluate(VISIBILITY + "(true)"), "hidden")
        time.sleep(0.3)
        seq = int(self.body()["seq"])
        self.page.evaluate("window.__probe.raf = 0")
        time.sleep(3.0)
        self.assertGreaterEqual(int(self.body()["seq"]) - seq, 2, "publications kept coming")
        self.assertEqual(self.page.evaluate("window.__probe.raf"), 0, "no frame while hidden")
        self.page.evaluate(VISIBILITY + "(false)")
        sample = self.walk_samples(ms=10, step=10)[0]
        for name, published in sample["pub"].items():
            drawn = sample["at"].get(name)
            if drawn and sample["seq"] == int(self.body()["seq"]):
                self.assertEqual((drawn[0], drawn[1]), (published[0], published[1]), f"{name}: the newest state, no replay")
        self.assertEqual(sample["snapshots"], 1, "no queue of publications kept")


class PerspectiveWalkTest(WalkTest):
    """The same walk in the perspective stage of variant 3 (two of the tests, to keep the time down)."""

    route = ""

    test_a_change_of_working_follows_the_published_route = None
    test_a_jump_across_workings_without_a_route_is_instant = None
    test_a_new_run_clears_the_buffer = None
    test_a_hidden_page_costs_no_frames_and_shows_the_newest_state_when_back = None


class WalkCycleTest(ArtCase):
    """A figure model with a clip `walk` (here a small skinned box standing in for the art's worker.glb)."""

    def test_the_walk_plays_only_while_walking_at_the_speed_of_the_ground(self):
        self.page.set_viewport(1920, 1080)
        self.page.add_init_script(serve_figure_script(rigged_figure_glb(stride_m=1.5, walk_s=1.0)))
        self.decision()
        self.page.wait_for("document.querySelector('#stage-3d .s3').getAttribute('data-decor') === 'loaded'", timeout=20.0)
        figures = self.info()["actors"]["figures"]
        self.assertIsNotNone(figures.get("rig"), f"the rigged figure is taken: {figures}")
        self.assertEqual(figures["rig"]["strideM"], 1.5, "the stride of the clip's extras")
        self.js(f"return {APP}.ctx.sendCommand('action.execute_option', 'option-stop-withdraw');")
        self.page.wait_for("document.body.dataset.runState === 'running'", timeout=10.0)
        walker = self.js(f"""const s = {APP}.store.getState();
          return s.model.byKind.worker.filter((x) => x.values.status === 'moving_to_exit').map((x) => x.name).sort()[0] || null;""")
        self.assertIsNotNone(walker)
        self.js(f"return {APP}.ctx.stage.focus({json.dumps(thing(walker))});")
        self.wait_idle()
        self.focus_canvas()
        self.page.press("+")
        self.page.press("+")
        self.wait_idle(timeout=15.0)
        samples = self.walk_samples(ms=4000, step=25)
        rig = samples[-1]["f"]["rig"]
        stride = rig["strideM"] * 2.5
        walking = 0
        for sample in samples:
            walks = sample["f"].get("walks") or {}
            for name, (weight, rate, speed) in walks.items():
                drawn = sample["at"].get(name)
                if not drawn:
                    continue
                if not drawn[3]:
                    self.assertLessEqual(weight, 1.0)
                    continue
                if weight >= 1 and speed > 1:
                    walking += 1
                    # One stride per cycle: the clip runs at speed / stride cycles per second.
                    self.assertAlmostEqual(rate, speed * rig["walkS"] / stride, delta=0.02 + 0.02 * rate, msg=f"{name}: no sliding feet")
        self.assertGreater(walking, 5, "the walk cycle played while people walked")
        # The reads hang: the people reach their published places and stop; the walk fades out within about 200 ms.
        self.mock.fault("hang")
        try:
            samples = self.walk_samples(ms=1900, step=25)
            stood = [sample for sample in samples if sample["link"] == "ok" and sample["t"] >= 1500]
            self.assertTrue(stood)
            for sample in stood:
                for name, (weight, rate, _) in (sample["f"].get("walks") or {}).items():
                    self.assertEqual(weight, 0, f"{name}: the walk faded out when the person stopped")
                    self.assertEqual(rate, 0)
        finally:
            self.mock.fault("none")


# ---- the illustrated mine (env.glb of the art, phase II) --------------------------------------------------------

ENV_GLB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "models", "mine-art", "env.glb")


def art_extras():
    """scene.extras of the art's env.glb (SPEC §5): the browser takes k, cx, cy, zTop from there, so do the tests."""
    with open(ENV_GLB, "rb") as handle:
        head = handle.read(20)
        length = struct.unpack("<I", head[12:16])[0]
        gltf = json.loads(handle.read(length))
    return gltf["scenes"][gltf.get("scene", 0)].get("extras", {})


def art_point(x, y, z):
    """A mine point in the art's scene (SPEC §3: X = x - cx, Y = k (z - zTop), Z = cy - y, the values of env.glb)."""
    extras = art_extras()
    return [x - extras["cx"], extras["k"] * (z - extras.get("zTop", 0)), extras["cy"] - y]


def decimal(value):
    """A factor as the scale note writes it: one decimal, a comma («1,6»)."""
    return f"{value:.1f}".replace(".", ",")


LAMPS = """(async () => {
  const app = (await import('/js/main.js')).app;
  const out = [];
  app.ctx.sendCommand('action.execute_option', 'option-withdraw_all');
  const t0 = performance.now();
  while (performance.now() - t0 < 4000) {
    const i = app.ctx.stage.info();
    const s = app.store.getState();
    out.push({t: Math.round(performance.now() - t0), l: Object.fromEntries(i.art.machines.map((m) => [m.name, m.light])),
      w: Object.fromEntries(s.model.byKind.zone.map((z) => [z.name, z.values.work_state]))});
    await new Promise((resolve) => setTimeout(resolve, 15));
  }
  return out;
})()"""


class ArtEnvCase(ArtCase):
    def open_art(self, scenario="sim_instability", size=(1920, 1080)):
        self.page.set_viewport(*size)
        self.open(scenario)
        self.page.wait_for("(() => { const s = document.querySelector('#stage-3d .s3'); return s && s.dataset.artEnv === 'on'"
                           " && s.dataset.artFigure && s.dataset.artMachines; })()", timeout=40.0,
                           message="the art of the mine is shown")
        time.sleep(0.5)
        return self.wait_idle(timeout=20.0)

    def decision_art(self, size=(1920, 1080)):
        self.open_art(size=size)
        result = self.js(f"return {APP}.ctx.sendCommand('run.start_preset', 'p-instability');")
        self.assertTrue(result["ok"], result)
        self.page.wait_for("document.body.dataset.runState === 'paused'", timeout=60.0, message="the decision of sim_instability")
        self.page.wait_for("document.querySelector('#stage-3d .s3').dataset.choreo === 'decision:zone-a'", timeout=15.0)
        time.sleep(1.0)
        self.wait_idle(timeout=20.0)


class ArtEnvTest(ArtEnvCase):
    """The art is shown for the topology it was built for (sim_instability), never for another (the invented fixtures)."""

    def test_the_art_turns_on_for_its_topology_only(self):
        self.open_art()
        info = self.info()
        art = info["art"]
        self.assertTrue(art["env"], art)
        extras = art_extras()
        self.assertEqual(art["origin"], {"cx": extras["cx"], "cy": extras["cy"], "zTop": extras.get("zTop", 0)}, "the GLB's origin")
        self.assertAlmostEqual(art["k"], extras["k"], places=6, msg="the vertical factor read from the GLB")
        self.assertAlmostEqual(art["az"], 12, places=3, msg="MainView's azimuth")
        self.assertAlmostEqual(art["el"], 23, places=3, msg="MainView's elevation")
        self.assertAlmostEqual(art["zoom"], 1, places=6)
        self.assertEqual(info["camera"]["type"], "orthographic")
        self.assertLessEqual(info["calls"], 40, "draw calls of the art")
        self.assertEqual(sorted((m["name"], m["kind"]) for m in art["machines"]),
                         [("drill", "drill"), ("lhd_zone-a", "lhd"), ("lhd_zone-b", "lhd"), ("truck", "truck")])
        self.assertEqual(self.page.evaluate("document.querySelector('#stage-3d .s3').dataset.artFigure"), "worker.glb")
        notes = self.page.evaluate("document.querySelector('[data-testid=\"scene3d-gizmo\"]').textContent")
        for words in (f"вертикаль ×{decimal(extras['k'])}", "шире настоящих", "оформление", "только работу своего участка",
                      "машины ×2,2 настоящих", "фигуры людей ×4,4"):
            self.assertIn(words, notes)
        # An invented fixture (another topology): the procedural scene of variant 3, perspective, no art.
        self.page.set_viewport(1280, 720)
        self.open("normal")
        self.page.wait_for("document.querySelector('#stage-3d .s3').dataset.artEnv === 'off'", timeout=20.0)
        info = self.info()
        self.assertIsNone(info["art"])
        self.assertEqual(info["camera"]["type"], "perspective")
        self.assertNotIn("art", self.stage())

    def test_people_stand_on_the_drawn_floor_at_their_published_places(self):
        self.open_art()
        self.js(f"return {APP}.ctx.stage.focus({json.dumps(thing('zone-a'))});")
        self.wait_idle()
        info = self.info()
        figures = info["actors"]["figures"]
        self.assertEqual(figures["source"], "worker.glb")
        published = self.js(f"""const s = {APP}.store.getState();
          return Object.fromEntries(s.model.byKind.worker.map((w) => [w.name, [w.values.at_working, w.values.offset_m]]));""")
        expected = {}
        for name, (working, offset) in published.items():
            # w-07: b (150, 0, -120) -> face-a (150, -80, -120); w-12: f (150, 0, -240) -> face-b (150, -80, -240).
            expected[name] = art_point(150, -offset, {"w-07": -120, "w-12": -240}[working])
        self.assertGreaterEqual(len(figures["feet"]), 3, "the people of the framed zone are figures")
        for name, feet in figures["feet"].items():
            for got, want in zip(feet, [expected[name][0], expected[name][1] + 0.05, expected[name][2]]):
                self.assertAlmostEqual(got, want, delta=0.01, msg=f"{name} at the mapped published place: {feet} vs {expected[name]}")
            self.assertAlmostEqual(info["art"]["floorGaps"][name], -0.05, delta=0.1, msg=f"{name} stands on the drawn floor")
            mark = self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(thing(name))});")
            self.assertAlmostEqual(mark["world"][0], expected[name][0], delta=0.05, msg="the marker over the person")
            self.assertAlmostEqual(mark["world"][2], expected[name][2], delta=0.05, msg="the marker over the person")

    def test_show_zooms_in_on_a_zone_and_a_person(self):
        self.open_art()
        self.focus_canvas()
        for target, low in ((thing("zone-b"), 2.5), (thing("worker-a2"), 2.9)):
            self.page.press("Home")
            self.wait_idle()
            self.js(f"return {APP}.ctx.stage.focus({json.dumps(target)});")
            self.wait_idle()
            zoom = self.info()["art"]["zoom"]
            self.assertTrue(low <= zoom <= 4 + 1e-9, f"{target} framed close: {zoom}")
        self.assert_in_free_area(self.place("worker-a2"), "the person in the free stage")

    def test_the_decision_frames_the_zone_close_with_its_overlays(self):
        self.decision_art()
        info = self.info()
        self.assertGreaterEqual(info["art"]["zoom"], 2.5, "the decision frames zone A close")
        self.assert_in_free_area(self.place("w-07", "worker-a1", "worker-a2", "worker-a3"), "zone A and its people beside the panel")
        overlays = info["art"]["overlays"]
        names = [entry["material"] for entry in overlays]
        self.assertIn("danger", names, "the danger hatch on the drawn floor of zone A")
        self.assertNotIn("zone", names, "no decal on a normal floor: the art paints it")
        self.assertIn("route", names, "the published routes")
        for entry in overlays:
            if entry["material"] in ("danger", "attention", "unknown"):
                self.assertTrue(entry["polygonOffset"], "decals sit on the floor without z-fighting")

    def test_a_withdrawal_is_framed_close_on_the_walking_figures(self):
        self.decision_art()
        result = self.js(f"return {APP}.ctx.sendCommand('action.execute_option', 'option-withdraw_all');")
        self.assertTrue(result["ok"], result)
        self.page.wait_for("(document.querySelector('#stage-3d .s3').dataset.choreo || '').startsWith('executing:walk:')", timeout=15.0,
                           message="the walk is framed")
        time.sleep(2.5)
        info = self.info()
        self.assertGreaterEqual(info["art"]["zoom"], 2.5, "close on the walk")
        walkers = self.js(f"""const s = {APP}.store.getState();
          return s.model.byKind.worker.filter((w) => w.values.status === 'moving_to_exit' && w.values.at_working
            && ['w-07', 'w-04', 'w-03'].includes(w.values.at_working)).map((w) => w.name);""")
        self.assertTrue(walkers, "people walking out of zone A")
        self.assert_in_free_area(self.place(*walkers), "the walking people in the free stage")
        figures = info["actors"]["figures"]
        self.assertGreaterEqual(figures["px"], figures["threshold"], "the people are figures at this zoom")
        walking = [entry for name, entry in figures["walks"].items() if name in walkers and entry[0] == 1]
        self.assertTrue(walking, f"the walk cycle plays: {figures['walks']}")
        for weight, rate, _ in walking:
            self.assertLessEqual(rate, 2.4 + 1e-6, "at most 2.4 cycles a second")

    def test_a_click_on_a_drawn_floor_selects_its_working(self):
        self.open_art()
        found = self.js(f"""const app = {APP}; const s = app.store.getState();
          const marks = [...s.model.byKind.worker, ...s.model.byKind.exit, ...s.model.byKind.sensor]
            .map((t) => app.ctx.stage.screenOf(t.thingId)).filter(Boolean);
          for (const name of ['w-10', 'w-04', 'w-03', 'w-11', 'w-05', 'w-06']) {{
            const p = app.ctx.stage.screenOf('{thing("")}' + name);
            const under = p && document.elementFromPoint(p.x, p.y);
            const clear = p && marks.every((m) => Math.hypot(m.x - p.x, m.y - p.y) > 40);
            if (p && p.visible && clear && under && under.matches('#stage-3d canvas')) return [name, p.x, p.y];
          }} return null;""")
        self.assertIsNotNone(found, "a drawn floor clear of labels and markers")
        self.click_at(found[1], found[2])
        self.wait_selected(thing(found[0]))

    def test_lamps_follow_the_published_work_state_of_their_zone(self):
        self.decision_art()
        lights = {m["name"]: m["light"] for m in self.info()["art"]["machines"]}
        self.assertEqual(lights, {"lhd_zone-a": 1, "lhd_zone-b": 1, "truck": 0, "drill": 0}, "working zones: lit; decor: dark")
        samples = self.page.evaluate(LAMPS, timeout=40)
        self.assertEqual(samples[-1]["w"], {"zone-a": "stopped", "zone-b": "stopped"}, "both zones stopped")
        for name in ("lhd_zone-a", "lhd_zone-b"):
            values = [sample["l"][name] for sample in samples]
            self.assertEqual(values[-1], 0, f"{name}: dark once its zone is stopped")
            self.assertEqual(values, sorted(values, reverse=True), f"{name}: one fade, never back")
            fading = [sample["t"] for sample in samples if 0 < sample["l"][name] < 1]
            self.assertTrue(fading, f"{name}: the lamps fade")
            self.assertLessEqual(fading[-1] - fading[0], 450, f"{name}: about 300 ms")
        self.assertTrue(all(sample["l"]["truck"] == 0 and sample["l"]["drill"] == 0 for sample in samples))


# ---- the sizes of the art: people bigger, machines to match, nobody walks through a machine -----------------------

# Puts worker-a2 and worker-a3 at the published place of worker-a1 (w-07, 20 m; a3 one metre on) in every /ditto/
# answer: three people at one place.
CROWD = """
(() => {
  const at = {'team040.mine:worker-a2': 20, 'team040.mine:worker-a3': 21};
  const visit = (value) => {
    if (Array.isArray(value)) { value.forEach(visit); return value; }
    if (value !== null && typeof value === 'object') {
      if (typeof value.thingId === 'string' && value.thingId in at && value.features && value.features.offset_m
        && value.features.offset_m.properties) value.features.offset_m.properties.value = at[value.thingId];
      Object.values(value).forEach(visit);
    }
    return value;
  };
  const original = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await original(...args);
    const url = String((args[0] && args[0].url) || args[0]);
    if (!url.includes('/ditto/')) return response;
    const body = await response.text();
    let out = body;
    try { out = JSON.stringify(visit(JSON.parse(body))); } catch (error) { /* not JSON */ }
    return new Response(out, {status: response.status, statusText: response.statusText, headers: response.headers});
  };
})();
"""


class ArtSizeTest(ArtEnvCase):
    """The worker of the art is drawn 8 m tall (1.6 × worker.glb), a figure from the overview of a 1920×1080 stage on;
    the machines 2.2× real; the people of one place stand apart; no walking line runs through a machine."""

    def test_figures_show_at_the_overview_and_the_pin_stays_over_the_helmet(self):
        self.open_art()
        info = self.info()
        self.assertAlmostEqual(info["art"]["zoom"], 1, places=3, msg="the overview")
        figures = info["actors"]["figures"]
        self.assertEqual(figures["source"], "worker.glb")
        self.assertAlmostEqual(figures["scale"], 1.6, places=6, msg="the worker drawn 1.6 × its 5 m")
        self.assertAlmostEqual(figures["rig"]["top"], 1.6 * 5.02, delta=0.05, msg="8 m tall")
        self.assertLessEqual(figures["threshold"], 10, "a figure from about 10 px on")
        self.assertGreaterEqual(figures["px"], 10, f"at least 10 px tall at the overview: {figures['px']}")
        self.assertEqual(figures["shown"], figures["people"], "every person is a figure at the overview, not a disc")
        # The small state pin stands over the helmet of its figure.
        for name in ("worker-a1", "worker-b2"):
            feet = figures["feet"][name]
            mark = self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(thing(name))});")
            self.assertGreater(mark["world"][1] - feet[1], figures["rig"]["top"], f"{name}: the pin over the helmet")
            self.assertLess(mark["world"][1] - feet[1], figures["rig"]["top"] + 6, f"{name}: the pin close over the helmet")
        # A person framed close: up to four times the overview.
        self.js(f"return {APP}.ctx.stage.focus({json.dumps(thing('worker-a2'))});")
        self.wait_idle()
        self.assertAlmostEqual(self.info()["art"]["zoom"], 4, delta=0.05, msg="a person framed at 4×")

    def test_people_of_one_place_stand_apart(self):
        self.page.add_init_script(CROWD)
        self.open_art()
        published = self.js(f"""const s = {APP}.store.getState();
          return Object.fromEntries(s.model.byKind.worker.map((w) => [w.name, w.values.offset_m]));""")
        self.assertEqual((published["worker-a1"], published["worker-a2"], published["worker-a3"]), (20, 20, 21), "three people at one place")
        self.js(f"return {APP}.ctx.stage.focus({json.dumps(thing('zone-a'))});")
        self.wait_idle()
        figures = self.info()["actors"]["figures"]
        feet = [figures["feet"][name] for name in ("worker-a1", "worker-a2", "worker-a3")]
        tall = figures["rig"]["top"]
        for i in range(3):
            for j in range(i + 1, 3):
                apart = math.hypot(feet[i][0] - feet[j][0], feet[i][2] - feet[j][2])
                self.assertGreater(apart, 0.4 * tall, f"figures {i} and {j} stand apart: {apart:.2f} m")
        # Their places as published are kept (the figures stand apart, the data do not move).
        self.assertEqual([figures["at"][name][:2] for name in ("worker-a1", "worker-a2", "worker-a3")],
                         [["w-07", 20], ["w-07", 20], ["w-07", 21]])
        # One pin for the place, with the count (the markers of the scene: a single group).
        marks = [self.js(f"return {APP}.ctx.stage.screenOf({json.dumps(thing(name))});")["world"] for name in ("worker-a1", "worker-a2", "worker-a3")]
        self.assertTrue(all(mark == marks[0] for mark in marks), "one pin over the three")
        # The floor under each figure is the drawn floor.
        for name, gap in self.info()["art"]["floorGaps"].items():
            if name in ("worker-a1", "worker-a2", "worker-a3"):
                self.assertIsNotNone(gap, f"{name} stands on the drawn floor")
                self.assertLess(abs(gap), 0.6, f"{name} stands on the drawn floor: {gap}")

    def test_machines_are_twice_real_and_clear_of_every_walking_line(self):
        self.open_art()
        info = self.info()
        machines = info["art"]["machines"]
        self.assertEqual(info["art"]["machineFactor"], 2.2)
        self.assertEqual(len(machines), 4)
        for machine in machines:
            self.assertAlmostEqual(machine["scale"], 2.2 / 1.5, delta=0.002, msg=f"{machine['name']}: 2.2× real (built 1.5×)")
        lines = self.js(f"""const s = {APP}.store.getState(); const nodes = s.attributes.mine.nodes;
          return s.model.byKind.working.map((w) => [w.name, [[nodes[w.attrs.from].x, nodes[w.attrs.from].y, nodes[w.attrs.from].z],
            ...(w.attrs.points || []), [nodes[w.attrs.to].x, nodes[w.attrs.to].y, nodes[w.attrs.to].z]]]);""")
        tall = info["actors"]["figures"]["rig"]["top"]
        # A person drawn on a walking line takes up to 4.5 m to its side (people of one place stand apart) and half a
        # body (about 1.6 m at this size): the machine keeps clear of that.
        need = 4.5 + 1.6
        nearest = {}
        for machine in machines:
            x0, y0, z0, x1, y1, z1 = machine["box"]
            best = math.inf
            for name, points in lines:
                scene = [art_point(*p) for p in points]
                for a, b in zip(scene, scene[1:]):
                    steps = max(1, int(math.dist(a, b)))
                    for i in range(steps + 1):
                        p = [a[k] + (b[k] - a[k]) * i / steps for k in range(3)]
                        # A person standing there: from the floor to the top of the head.
                        if p[1] + tall < y0 or p[1] > y1:
                            continue
                        dx = max(x0 - p[0], 0, p[0] - x1)
                        dz = max(z0 - p[2], 0, p[2] - z1)
                        best = min(best, math.hypot(dx, dz))
            nearest[machine["name"]] = round(best, 2)
            self.assertGreaterEqual(best, need, f"{machine['name']}: {best:.1f} m from the nearest walking line (box {machine['box']})")
        print(f"\n[art sizes] machines 2.2x real; nearest walking line: {nearest}")


if __name__ == "__main__":
    unittest.main()
