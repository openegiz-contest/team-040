"""Screenshots of the dispatcher screen, and measurements of its budgets.

A script, not a test. It starts the mock server and headless Chrome with
SwiftShader (the software WebGL a machine without a GPU has), drives the
production page through its real controls and writes a named set of PNG files
at 1280x720 and 1920x1080 to `team/ui/test-output/screenshots/` (git-ignored
evidence, regenerated on demand). The stories of the stage are taken twice,
in its 3D mode and in its scheme mode: `3d-<name>-<size>.png` and
`scheme-<name>-<size>.png`; the views that do not depend on the stage are
taken once, with the scheme.

    python team/ui/tests/screenshots.py                 the whole set, both sizes, both modes
    python team/ui/tests/screenshots.py --only no-path  the shots whose file name contains the text
    python team/ui/tests/screenshots.py --measure       no screenshots: measure and print

`--measure` reports numbers of this machine against the mock server: the time
to the first complete render of the scheme, the cost of one 1 Hz update, the
size of the DOM, the size of the static files and the request rate; and for the
3D stage the time to its first frame, the frame times of a camera glide (median
and 90th percentile), the triangles and draw calls of the light quality and the
frames drawn while nothing changes. They are measurements of a development
machine with a software renderer, not results of the stand and not a verdict on
the targets of DESIGN.md 6.1. The numbers are also written to
`test-output/measurements.json`.

Two shots (`states-not-in-fixtures`, and its greyscale twin) show states that no
fixture publishes: a zone in danger now, a stale sensor, a route that is not
computed, an unavailable exit. For them the script rewrites the answers of the
mock in the browser (REWRITE_SHIFT); the page code is the same and does not know.

The helpers that drive the page (`choose`, `close_working`, `execute_option`, ...)
are shared with the tests. Standard library only; the mock data are invented for tests.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser_support import OUTPUT_DIR, PUBLIC_DIR, Browser, MockServer, chrome_available  # noqa: E402

NS = "team040.mine"
SIZES = ((1280, 720), (1920, 1080))
MODES = ("3d", "scheme")
SHOTS_DIR = os.path.join(OUTPUT_DIR, "screenshots")
# Chrome's software WebGL (SwiftShader).
SWIFTSHADER = ("--use-angle=swiftshader", "--enable-unsafe-swiftshader")

CONDITIONS = '[data-testid="conditions-panel"]'
CLOSE = f'{CONDITIONS} button[data-command-type="condition.close_working"]'
WORKING_SELECT = "#condition-working_closed"
EXECUTE = '[data-testid="btn-execute"]'
RESET = '[data-testid="btn-reset"]'
READY = ("document.body.dataset.boot === 'ready' && document.body.dataset.snapshot === 'ok'"
         " && document.body.dataset.link === 'ok'")
DRAWN = (READY + " && document.querySelector('[data-testid=\"scheme-svg\"]').dataset.drawn === 'true'"
         " && !!document.querySelector('#scheme .worker')")
# The 3D stage has drawn the model and measured its first frames, and is at rest.
DRAWN_3D = (READY + " && (() => { const s = document.querySelector('#stage').dataset;"
            " return s.stageMode === '3d' && Number(s.frames) > 0 && s.measuredMs !== undefined && s.rendering === 'idle'"
            " && Number(s.levels) > 0; })()")
STAGE_IDLE = "document.querySelector('#stage').dataset.rendering !== 'active'"


# Test-side rewrite of the answers of the mock, in the browser, before any script of the page: the
# features named in `window.__patch` ({local name: {feature: value}}, "shift" for the shift itself)
# replace the published ones in every read of `shift`. The page code is unchanged and does not know.
# Used only to show states that no fixture publishes (a zone in danger now, a stale sensor, ...).
REWRITE_SHIFT = """
(() => {
  window.__patch = {};
  const realFetch = window.fetch;
  const put = (features, changes) => {
    for (const [name, value] of Object.entries(changes)) {
      features[name] = {properties: {...(features[name] ? features[name].properties : {}), value}};
    }
  };
  window.fetch = async function (input, init) {
    const response = await realFetch.call(this, input, init);
    const url = typeof input === 'string' ? input : input.url;
    if (!url.includes(':shift?') || !response.ok) return response;
    const body = await response.json();
    if (window.__patch.shift) put(body.features, window.__patch.shift);
    for (const item of body.features.scene.properties.value) {
      const changes = window.__patch[item.thingId.split(':')[1]];
      if (changes) put(item.features, changes);
    }
    return new Response(JSON.stringify(body), {status: response.status, statusText: response.statusText, headers: response.headers});
  };
})();
"""

_DANGER = {"hazard_state": "danger"}
_STALE = {"hazard_state": "unknown", "data_quality": "stale", "last_known_hazard_state": "attention", "last_known_hazard_tick": 1100}
# On top of the scenario `normal`: one zone in danger with its people, one zone known only by stale
# data, a worker whose route is not computed, a worker with a stale position, an unavailable exit
# and an exit in an unknown state.
STATES_PATCH = {
    "zone-b": _DANGER, **{name: _DANGER for name in ("w-13", "w-14", "w-15", "w-16", "w-17")},
    **{name: {"location_hazard": "danger"} for name in ("worker-03", "worker-04", "worker-05", "worker-06")},
    "zone-a": _STALE, **{name: _STALE for name in ("w-32", "w-33", "w-34", "w-35", "w-36")},
    "sens-ext-01": {"quality": "stale"},
    "worker-11": {"egress_status": "unknown", "egress_reason": "not_computed"},
    "worker-13": {"pos_quality": "stale"},
    "exit-raise": {"state": "unavailable"}, "exit-ramp": {"state": "unknown"},
    "shift": {"workers_in_danger": 4, "workers_unknown": 1},
}


# --------------------------------------------------------------------------
# Driving the page
# --------------------------------------------------------------------------

def open_page(page, mock, scenario, route="", ready=READY):
    """Restart the scenario from its first frame and load the page as a new document."""
    mock.scenario(scenario)
    page.goto("about:blank")
    page.goto(mock.url + "/" + route)
    if ready:
        page.wait_for(ready, timeout=15.0, message=f"{scenario}: the page is ready")


def set_stand(page, open_=True):
    """Open (or close) the stand drawer by its button in the top bar; its controls are out of reach while it is closed."""
    if (page.evaluate("document.body.dataset.stand") == "open") != open_:
        page.click('[data-testid="stand-toggle"]')
    page.wait_for(f"document.body.dataset.stand === {'open' if open_ else 'closed'!r}"
                  " && getComputedStyle(document.getElementById('stand-drawer')).visibility === "
                  f"{'visible' if open_ else 'hidden'!r}", timeout=3.0, message="the stand drawer")


def choose(page, selector, value):
    """Change a <select> the way a keyboard user does: focus it and move with the arrow keys.
    A select of the stand drawer is reached by opening the drawer first."""
    if page.evaluate(f"!!document.querySelector({json.dumps(selector)}).closest('#stand-drawer')"):
        set_stand(page)
    move = page.evaluate(f"""(() => {{
      const select = document.querySelector({json.dumps(selector)});
      select.focus();
      return {{from: select.selectedIndex, to: [...select.options].findIndex((option) => option.value === {json.dumps(value)})}};
    }})()""")
    if move["to"] < 0:
        raise AssertionError(f"{selector} has no option {value}")
    for _ in range(abs(move["to"] - move["from"])):
        page.press("ArrowDown" if move["to"] > move["from"] else "ArrowUp")


def close_working(page, working):
    """Set the stand condition «Закрыть выработку» for one working by the controls of the stand drawer,
    then close the drawer: the stage is what the condition changes."""
    choose(page, WORKING_SELECT, working)
    page.click(CLOSE)
    set_stand(page, False)


def wait_decision(page, timeout=10.0):
    page.wait_for("document.body.dataset.runState === 'paused'"
                  " && !!document.querySelector('[data-testid=\"decision-options\"] th[data-state=\"offered\"]')",
                  timeout=timeout, message="the decision point")


def show_right(page, part):
    """Bring a part forward where the layout folds it: "decision" unfolds the decision dock (folded to its
    bar over the stage at 1280x720) and closes the stand drawer that would cover it; "card" unfolds every
    published field of the card («Подробнее»)."""
    if part == "decision":
        page.evaluate("""(() => {
          if (document.body.dataset.stand === 'open') document.querySelector('[data-testid="stand-toggle"]').click();
          const toggle = document.querySelector('[data-testid="dock-toggle"]');
          if (toggle && toggle.getClientRects().length > 0 && toggle.getAttribute('aria-expanded') === 'false') toggle.click();
        })()""")
    elif part == "card":
        page.evaluate("""(() => {
          const more = document.querySelector('[data-testid="card-more"]');
          if (more && !more.hidden && more.getAttribute('aria-expanded') === 'false') more.click();
        })()""")


def execute_option(page, option):
    """Choose an option in the decision table, press «Запустить вариант» and confirm the dialog."""
    show_right(page, "decision")
    page.click(f'[data-testid="decision-options"] th[data-column="{option}"] input', timeout=3.0)
    page.click(EXECUTE, timeout=3.0)
    page.wait_for("!!document.querySelector('[data-testid=\"dialog-confirm\"]')", timeout=3.0)
    page.click('[data-testid="dialog-confirm"]')


def wait_seq(page, count, timeout=None):
    start = int(page.evaluate("document.body.dataset.seq"))
    page.wait_for(f"Number(document.body.dataset.seq) >= {start + count}", timeout=timeout or 5.0 + 1.5 * count)


# --------------------------------------------------------------------------
# The shots: name -> how the state is reached, in a mode of the stage
# --------------------------------------------------------------------------

def stage_route(route, mode):
    """The route with the stage mode asked for (`mode=3d|scheme`), as the stage switch writes it."""
    route = route or "#/scheme"
    return route + ("&" if "?" in route else "?") + "mode=" + mode


def open_stage(page, mock, scenario, mode, route=""):
    """Open a story on the stage in the given mode and wait until it is drawn (the 3D stage at rest)."""
    open_page(page, mock, scenario, stage_route(route, mode), ready=DRAWN_3D if mode == "3d" else DRAWN)


def select(page, mode, name):
    """Select a twin with the pointer, on the scheme or on the 3D model (by its label; a worker's label after
    «Показать на модели» of his zone has brought the camera close)."""
    thing_id = f"{NS}:{name}"
    if mode == "scheme":
        page.click(f'#scheme [data-thing-id="{thing_id}"]', force=True)
    else:
        label = f'#stage-3d .s3-label[data-thing-id="{thing_id}"]'
        if page.evaluate(f"(() => {{ const node = document.querySelector({json.dumps(label)});"
                         " return !node || node.hasAttribute('data-culled'); })()"):
            zone = page.evaluate(f"(async () => {{ const s = (await import('/js/main.js')).app.store.getState();"
                                 f" const w = s.model.byName[{json.dumps(name)}]; const at = w && w.values.at_working;"
                                 " const z = s.model.byKind.zone.find((zone) => (zone.attrs.workings || []).includes(at));"
                                 " return z ? z.thingId : null; })()")
            page.click(f'#stage-3d .s3-label[data-thing-id="{zone}"]')
            page.click('[data-testid="card-focus"]', timeout=3.0)
            page.wait_for(STAGE_IDLE, timeout=10.0)
            page.wait_for(f"!document.querySelector({json.dumps(label)}).hasAttribute('data-culled')", timeout=5.0,
                          message=f"the label of {name} is placed")
        page.click(label, timeout=3.0)
    page.wait_for(f"location.hash.includes({json.dumps('sel=' + thing_id)})", timeout=3.0, message=f"{name} is selected")


def shot_normal(page, mock, mode):
    open_stage(page, mock, "normal", mode)


def shot_danger_zone(page, mock, mode):
    """Участок Г in danger with three people in it; the decision point with the dock."""
    open_stage(page, mock, "danger_zone", mode)
    page.wait_for("document.body.dataset.runState === 'paused'", timeout=15.0, message="the decision point")


def shot_detour_route(page, mock, mode):
    """В-12 closed: the selected worker's longer route by the ramp."""
    open_stage(page, mock, "detour", mode)
    close_working(page, "w-12")
    wait_decision(page)
    select(page, mode, "worker-03")
    if mode == "scheme":
        page.wait_for("!!document.querySelector('#scheme .route[data-reason=\"selection\"]')", timeout=5.0)
    else:
        page.wait_for("document.querySelector('#stage').dataset.routes === '1'", timeout=5.0, message="his route")


def shot_no_path(page, mock, mode):
    open_stage(page, mock, "no_path", mode)
    close_working(page, "w-07")
    wait_decision(page)
    marks = "#scheme .worker" if mode == "scheme" else "#stage-3d .s3-label[data-kind=\"worker\"]"
    page.wait_for(f"document.querySelectorAll('{marks}[data-egress=\"none\"]').length === 2", timeout=5.0)


def shot_sensor_lost(page, mock, mode):
    open_stage(page, mock, "sensor_lost_after_danger", mode)


def shot_options_compared(page, mock, mode):
    """The decision point of `detour`: the three options side by side in the unfolded dock."""
    open_stage(page, mock, "paused_heartbeat", mode)
    show_right(page, "decision")


def shot_stand_drawer(page, mock, mode):
    """The stand drawer open over the left edge of the stage, with an active condition and its chalk tag in the top bar."""
    open_stage(page, mock, "detour", mode)
    close_working(page, "w-12")
    wait_decision(page)
    set_stand(page)


def shot_platform_unavailable(page, mock, mode):
    open_stage(page, mock, "normal", mode)
    wait_seq(page, 2)
    mock.fault("http_502")
    page.wait_for("document.body.dataset.link === 'unavailable'", timeout=15.0, message="platform unavailable")


def shot_withdrawal_in_progress(page, mock, mode):
    open_stage(page, mock, "detour", mode)
    close_working(page, "w-12")
    wait_decision(page)
    execute_option(page, "option-withdraw-all")
    page.wait_for("document.body.dataset.runState === 'running'", timeout=12.0, message="people are walking")
    wait_seq(page, 6)


def shot_invalid_snapshot(page, mock, mode):
    open_stage(page, mock, "invalid_missing_field", mode)
    page.wait_for("document.body.dataset.snapshot === 'invalid'", timeout=15.0, message="the snapshot is rejected")


def shot_frozen_publications(page, mock, mode):
    open_page(page, mock, "frozen_seq_old", stage_route("", mode), ready=None)
    page.wait_for("document.body.dataset.publications === 'stopped'"
                  " && document.querySelector('[data-testid=\"scheme-svg\"]').dataset.drawn === 'true'",
                  timeout=15.0, message="publications stopped")


def shot_pending_rejected(page, mock, mode):
    open_stage(page, mock, "commands", mode)
    close_working(page, "w-12")
    page.wait_for("!!document.querySelector('[data-testid=\"pending\"][data-command-target=\"w-12\"][data-phase=\"sent\"]')",
                  timeout=5.0)
    close_working(page, "w-07")
    page.wait_for("!!document.querySelector('[data-testid=\"pending\"][data-command-target=\"w-07\"][data-phase=\"rejected\"]')",
                  timeout=8.0, message="the rejected command")


def shot_reset_dialog(page, mock, mode):
    open_stage(page, mock, "reset", mode)
    set_stand(page)
    page.click(RESET, timeout=3.0)
    page.wait_for("!!document.querySelector('[data-testid=\"dialog\"]')", timeout=3.0)


def shot_no_forecast(page, mock, mode):
    open_stage(page, mock, "no_forecast", mode)
    show_right(page, "decision")


def shot_withdrawal_incomplete(page, mock, mode):
    open_stage(page, mock, "withdrawal_incomplete", mode)


def shot_list(page, mock, mode):
    open_page(page, mock, "normal", "#/list")
    page.wait_for("document.querySelectorAll('[data-testid=\"list\"] tbody tr').length > 70", timeout=10.0)


def shot_runs(page, mock, mode):
    open_page(page, mock, "normal", "#/runs")
    page.wait_for("document.querySelectorAll('[data-testid=\"runs-table\"] tr[data-series=\"actual\"]').length >= 4",
                  timeout=10.0)


def shot_plan(page, mock, mode):
    open_stage(page, mock, "normal", mode, "#/scheme?view=plan&level=level-320")
    page.wait_for("document.querySelector('[data-testid=\"scheme-svg\"]').dataset.projection === 'plan'", timeout=5.0)


def shot_journal_open(page, mock, mode):
    open_stage(page, mock, "sensor_lost_after_danger", mode)
    page.evaluate("""(() => {
      const toggle = document.querySelector('[data-testid="journal-toggle"]');
      if (toggle.getClientRects().length > 0) toggle.click();
    })()""")


def shot_states_not_in_fixtures(page, mock, mode):
    """States no fixture publishes, by a rewrite of the mock's answers in the browser (REWRITE_SHIFT)."""
    page.add_init_script(REWRITE_SHIFT)
    open_stage(page, mock, "normal", mode)
    page.evaluate("window.__patch = " + json.dumps(STATES_PATCH))
    page.wait_for("(async () => (await import('/js/main.js')).app.store.getState().model.byName['zone-b'].hazard.state === 'danger')()",
                  timeout=6.0)


def grey(shot):
    def run(page, mock, mode):
        page.emulate_vision("achromatopsia")
        shot(page, mock, mode)
    return run


BOTH = MODES
SCHEME = ("scheme",)
# name, how, the modes of the stage it is taken in
SHOTS = (
    # The stories of the stage, in 3D and in the scheme.
    ("normal", shot_normal, BOTH),
    ("danger-zone", shot_danger_zone, BOTH),
    ("detour-route", shot_detour_route, BOTH),
    ("no-path", shot_no_path, BOTH),
    ("sensor-lost-after-danger", shot_sensor_lost, BOTH),
    ("options-compared", shot_options_compared, BOTH),
    ("stand-drawer", shot_stand_drawer, BOTH),
    ("platform-unavailable", shot_platform_unavailable, BOTH),
    ("withdrawal-in-progress", shot_withdrawal_in_progress, BOTH),
    ("states-not-in-fixtures", shot_states_not_in_fixtures, BOTH),
    ("grey-normal", grey(shot_normal), BOTH),
    ("grey-danger-zone", grey(shot_danger_zone), BOTH),
    # The panels and the views beside the stage, once.
    ("invalid-snapshot", shot_invalid_snapshot, SCHEME),
    ("frozen-publications", shot_frozen_publications, SCHEME),
    ("pending-and-rejected-command", shot_pending_rejected, SCHEME),
    ("reset-dialog", shot_reset_dialog, SCHEME),
    ("no-forecast", shot_no_forecast, SCHEME),
    ("withdrawal-incomplete", shot_withdrawal_incomplete, SCHEME),
    ("list", shot_list, SCHEME),
    ("runs-archive", shot_runs, SCHEME),
    ("plan-projection", shot_plan, SCHEME),
    ("journal-unfolded", shot_journal_open, SCHEME),
    ("grey-no-path", grey(shot_no_path), SCHEME),
    ("grey-sensor-lost-after-danger", grey(shot_sensor_lost), SCHEME),
    ("grey-states-not-in-fixtures", grey(shot_states_not_in_fixtures), SCHEME),
)


def take_screenshots(only=None, sizes=SIZES, out_dir=SHOTS_DIR):
    """Write the set and return the list of files and the list of problems."""
    written = []
    problems = []
    with MockServer("normal") as mock, Browser(*sizes[0], extra_args=SWIFTSHADER) as browser:
        for width, height in sizes:
            for name, shot, modes in SHOTS:
                for mode in modes:
                    file_name = f"{mode}-{name}-{width}x{height}.png"
                    if only and only not in file_name:
                        continue
                    path = os.path.join(out_dir, file_name)
                    page = browser.new_page()
                    try:
                        # Each shot starts from the stage's own default choices (quality, spread), not from a former one.
                        page.add_init_script("try { localStorage.removeItem('mine-ui.stage'); } catch (error) {}")
                        page.set_viewport(width, height)
                        mock.fault("none")
                        shot(page, mock, mode)
                        time.sleep(0.9)  # the glide of the markers (600 ms) has ended
                        if mode == "3d":
                            page.wait_for(STAGE_IDLE, timeout=10.0, message="the 3D stage is at rest")
                        page.screenshot(path)
                        written.append(path)
                        for entry in page.console_errors:
                            problems.append(f"{file_name}: console error: {entry['text']}")
                    except Exception as error:  # one failed shot must not hide the others
                        problems.append(f"{file_name}: {type(error).__name__}: {error}")
                        try:
                            page.screenshot(path)
                            written.append(path)
                        except Exception:
                            pass
                    finally:
                        page.close()
                        mock.fault("none")
    return written, problems


# --------------------------------------------------------------------------
# Measurements
# --------------------------------------------------------------------------

# Records, from before the first script of the page, when the first complete picture of `normal`
# is in the DOM and when the frame after it was produced. Measuring code only: the page itself, in
# the scheme mode of the stage, never asks for an animation frame.
FIRST_RENDER_PROBE = """
(() => {
  window.__first = {};
  const complete = () => {
    const body = document.body;
    const svg = document.querySelector('[data-testid="scheme-svg"]');
    return !!body && body.dataset.boot === 'ready' && body.dataset.snapshot === 'ok' && !!svg
      && svg.dataset.drawn === 'true' && svg.querySelectorAll('.worker').length > 0
      && svg.querySelectorAll('.working').length > 0
      && document.querySelectorAll('[data-testid="legend"] .legend__item').length > 0
      && document.querySelector('[data-testid="incident-total"]').textContent.trim() !== ''
      && document.querySelector('[data-testid="card"]').textContent.trim() !== '';
  };
  const observer = new MutationObserver(() => {
    if (!complete()) return;
    observer.disconnect();
    window.__first.dom = performance.now();
    requestAnimationFrame(() => requestAnimationFrame(() => { window.__first.frame = performance.now(); }));
  });
  observer.observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
})();
"""

DOM_COUNT = """(() => {
  const svg = document.querySelector('[data-testid="scheme-svg"]');
  return {
    elements: document.querySelectorAll('*').length,
    schemeSvg: svg.querySelectorAll('*').length + 1,
    allSvg: [...document.querySelectorAll('svg')].reduce((sum, node) => sum + node.querySelectorAll('*').length + 1, 0),
    legend: document.querySelectorAll('[data-testid="legend"] *').length,
  };
})()"""

UPDATE_KEYS = ("ScriptDuration", "LayoutDuration", "RecalcStyleDuration", "TaskDuration")

# Times every update inside the page, from before its first script. The page parses, validates and
# renders a read of `shift` in the microtasks that follow the body of the answer, so a task queued
# at that moment starts when the update is done: `script` is the time until then (it includes a
# frame, if the browser made one in between). Reading a box then forces whatever style and layout
# the update left pending: `layout`. Measuring code only; the page is unchanged.
UPDATE_PROBE = """
(() => {
  window.__updates = [];
  const realFetch = window.fetch;
  window.fetch = async function (input, init) {
    const response = await realFetch.call(this, input, init);
    const url = typeof input === 'string' ? input : input.url;
    if (!url.includes(':shift?')) return response;
    const readText = response.text.bind(response);
    response.text = async () => {
      const body = await readText();
      const start = performance.now();
      setTimeout(() => {
        const script = performance.now() - start;
        const before = performance.now();
        document.getElementById('app').getBoundingClientRect();
        window.__updates.push({script, layout: performance.now() - before, bytes: body.length});
      }, 0);
      return body;
    };
    return response;
  };
})();
"""


def spread(values):
    return {"min": round(min(values), 1), "median": round(statistics.median(values), 1), "max": round(max(values), 1)}


def measure_first_render(browser, mock, size, loads=5):
    dom, frame, load = [], [], []
    for _ in range(loads):
        page = browser.new_page()
        try:
            page.set_viewport(*size)
            page.add_init_script(FIRST_RENDER_PROBE)
            mock.scenario("normal")
            page.goto(mock.url + "/" + stage_route("", "scheme"))
            page.wait_for("window.__first && window.__first.frame > 0", timeout=20.0, message="first complete render")
            first = page.evaluate("window.__first")
            dom.append(first["dom"])
            frame.append(first["frame"])
            load.append(page.evaluate("performance.getEntriesByType('navigation')[0].loadEventEnd"))
        finally:
            page.close()
    return {"loads": loads, "dom_complete_ms": spread(dom), "next_frame_ms": spread(frame), "load_event_ms": spread(load)}


# Counts animation frames and keeps the time of each, from before the first script of the page.
FRAME_PROBE = """
window.__frames = {count: 0, times: []};
const realRaf = window.requestAnimationFrame.bind(window);
window.requestAnimationFrame = function (callback) {
  window.__frames.count += 1;
  return realRaf((time) => { window.__frames.times.push(performance.now()); callback(time); });
};
"""
FORGET_STAGE = "try { localStorage.removeItem('mine-ui.stage'); } catch (error) {}"


def measure_3d(browser, mock, size, loads=3):
    """The 3D stage on `normal`: time to its first frame (from navigation start, `data-first-frame-ms`), the median of
    its measured first frames, the frame times of one camera glide, the renderer's triangles and draw calls, and the
    animation frames requested during five seconds in which nothing visible changes."""
    first, measured = [], []
    for _ in range(loads):
        page = browser.new_page()
        try:
            page.add_init_script(FORGET_STAGE)
            page.set_viewport(*size)
            open_stage(page, mock, "normal", "3d")
            stage = page.evaluate("Object.assign({}, document.getElementById('stage').dataset)")
            first.append(int(stage["firstFrameMs"]))
            measured.append(int(stage["measuredMs"]))
        finally:
            page.close()
    page = browser.new_page()
    try:
        page.add_init_script(FORGET_STAGE)
        page.add_init_script(FRAME_PROBE)
        page.set_viewport(*size)
        open_stage(page, mock, "normal", "3d")
        info = page.evaluate("(async () => (await import('/js/main.js')).app.ctx.stage.info())()")
        page.evaluate("window.__frames.times = []")
        page.evaluate(f"(async () => (await import('/js/main.js')).app.ctx.stage.focus({json.dumps(NS + ':zone-b')}))()")
        page.wait_for("document.querySelector('#stage').dataset.rendering === 'active'", timeout=3.0)
        page.wait_for(STAGE_IDLE, timeout=15.0)
        times = page.evaluate("window.__frames.times")
        glide = sorted(later - earlier for earlier, later in zip(times, times[1:]))
        page.evaluate("(async () => (await import('/js/main.js')).app.ctx.stage.overview())()")
        page.wait_for(STAGE_IDLE, timeout=15.0)
        seq = int(page.evaluate("document.body.dataset.seq"))
        page.evaluate("window.__frames.count = 0")
        started = time.monotonic()
        time.sleep(5.0)
        idle = page.evaluate("window.__frames.count") / (time.monotonic() - started)
        return {
            "renderer": info["renderer"], "quality": page.evaluate("document.getElementById('stage').dataset.quality"),
            "loads": loads, "first_3d_frame_ms": spread(first), "measured_first_frames_ms": spread(measured),
            "glide": {"frames": len(times), "frame_ms_median": round(statistics.median(glide), 1) if glide else None,
                      "frame_ms_p90": round(glide[max(0, int(len(glide) * 0.9) - 1)], 1) if glide else None},
            "triangles": info["triangles"], "draw_calls": info["calls"],
            "idle": {"seconds": 5.0, "publications": int(page.evaluate("document.body.dataset.seq")) - seq,
                     "frames_per_second": round(idle, 2)},
            "console_errors": len(page.console_errors),
        }
    finally:
        page.close()


def nodes_after_gc(page):
    """DOM nodes alive in the renderer after a forced garbage collection (`Performance.getMetrics`, Nodes)."""
    page.send("HeapProfiler.collectGarbage", timeout=30.0)
    return int(page.metrics()["Nodes"])


def measure_updates(page, polls=20):
    """The cost of one 1 Hz update over `polls` publications read by the page, measured two ways.

    `Performance.getMetrics` deltas give the main-thread time of the whole second between two
    polls (TaskDuration: script, style, layout, paint and the 250 ms timers together) and Chrome's
    own split of it; its ScriptDuration does not count work done in promise callbacks, which is
    where this page does its updates, so the in-page probe (UPDATE_PROBE) times each update itself.
    """
    seq = int(page.evaluate("document.body.dataset.seq"))
    nodes = nodes_after_gc(page)
    page.evaluate("window.__updates.length = 0")
    before = page.metrics()
    started = time.monotonic()
    page.wait_for(f"Number(document.body.dataset.seq) >= {seq + polls}", timeout=10.0 + 1.5 * polls)
    after = page.metrics()
    read = int(page.evaluate("document.body.dataset.seq")) - seq
    updates = page.evaluate("window.__updates")
    result = {"polls": read, "wall_s": round(time.monotonic() - started, 1)}
    for key in UPDATE_KEYS:
        result[key + "_ms_per_poll"] = round((after[key] - before[key]) * 1000 / read, 2)
    each = [item["script"] + item["layout"] for item in updates]
    result["in_page"] = {"updates": len(updates), "script_and_layout_ms": spread(each),
                         "script_ms": spread([item["script"] for item in updates]),
                         "layout_ms": spread([item["layout"] for item in updates]),
                         "answer_bytes": max(item["bytes"] for item in updates)}
    result["nodes_after_gc"] = {"before": nodes, "after": nodes_after_gc(page)}
    return result


def static_size():
    files = []
    for folder, _, names in os.walk(PUBLIC_DIR):
        for name in names:
            path = os.path.join(folder, name)
            files.append((os.path.getsize(path), os.path.relpath(path, PUBLIC_DIR).replace(os.sep, "/")))
    files.sort(reverse=True)
    return {"files": len(files), "total_bytes": sum(size for size, _ in files),
            "largest": [{"file": name, "bytes": size} for size, name in files[:3]]}


def measure():
    result = {"chrome": None, "sizes": {}, "static": static_size()}
    with MockServer("normal") as mock, Browser(*SIZES[1], extra_args=SWIFTSHADER) as browser:
        result["chrome"] = browser.version()
        for size in SIZES:
            label = f"{size[0]}x{size[1]}"
            entry = result["sizes"][label] = {}
            entry["stage_3d"] = measure_3d(browser, mock, size)
            entry["first_render_normal"] = measure_first_render(browser, mock, size)

            page = browser.new_page()
            try:
                page.set_viewport(*size)
                page.add_init_script(UPDATE_PROBE)
                open_stage(page, mock, "normal", "scheme")
                entry["dom_normal"] = page.evaluate(DOM_COUNT)
                page.clear_logs()
                started = time.monotonic()
                entry["update_normal"] = measure_updates(page)
                elapsed = time.monotonic() - started
                requests = [item for item in list(page.requests) if "/ditto/" in item["url"]]
                entry["idle_requests"] = {"seconds": round(elapsed, 1), "requests": len(requests),
                                          "per_second": round(len(requests) / elapsed, 2),
                                          "other_requests": len(page.requests) - len(requests)}

                # The busiest second of the story: people walking out after «вывести всех».
                open_stage(page, mock, "detour", "scheme")
                close_working(page, "w-12")
                wait_decision(page)
                execute_option(page, "option-withdraw-all")
                page.wait_for("document.querySelectorAll('#scheme .worker[data-status=\"moving_to_exit\"]').length > 3",
                              timeout=12.0)
                entry["update_withdrawal"] = measure_updates(page)
                entry["dom_withdrawal"] = page.evaluate(DOM_COUNT)
                entry["console_errors"] = len(page.console_errors)
            finally:
                page.close()
    return result


def print_measurements(result):
    print("Measured on this machine against the mock server (not results of the stand).")
    print(f"Chrome: {result['chrome']}")
    for label, entry in result["sizes"].items():
        first = entry["first_render_normal"]
        print(f"\n== {label} ==")
        stage = entry["stage_3d"]
        print(f"3D stage, `normal`, {stage['renderer']}, quality {stage['quality']}:")
        print(f"  first 3D frame, ms from navigation start, {stage['loads']} loads (min / median / max):"
              f" {stage['first_3d_frame_ms']['min']} / {stage['first_3d_frame_ms']['median']} / {stage['first_3d_frame_ms']['max']};"
              f" median of its measured first frames {stage['measured_first_frames_ms']['median']} ms")
        print(f"  camera glide to a zone: {stage['glide']['frames']} frames, frame time median {stage['glide']['frame_ms_median']} ms,"
              f" 90th percentile {stage['glide']['frame_ms_p90']} ms")
        print(f"  {stage['triangles']} triangles, {stage['draw_calls']} draw calls per frame")
        print(f"  while nothing visible changes: {stage['idle']['frames_per_second']} frames per second"
              f" ({stage['idle']['publications']} publications read in {stage['idle']['seconds']} s)")
        print(f"first complete render of `normal`, {first['loads']} loads, ms from navigation start (min / median / max):")
        for key, title in (("dom_complete_ms", "  picture complete in the DOM"), ("next_frame_ms", "  frame after it produced   "),
                           ("load_event_ms", "  (load event of the document)")):
            print(f"{title}: {first[key]['min']} / {first[key]['median']} / {first[key]['max']}")
        for key, title in (("update_normal", "one 1 Hz update, `normal`"),
                           ("update_withdrawal", "one 1 Hz update, people walking (`detour`, вывести всех)")):
            update = entry[key]
            inside = update["in_page"]
            print(f"{title}, {update['polls']} polls in {update['wall_s']} s:")
            print(f"  in the page, per update (min / median / max): script {inside['script_ms']['min']} / {inside['script_ms']['median']}"
                  f" / {inside['script_ms']['max']} ms, layout left after it {inside['layout_ms']['min']} / {inside['layout_ms']['median']}"
                  f" / {inside['layout_ms']['max']} ms, together {inside['script_and_layout_ms']['min']} /"
                  f" {inside['script_and_layout_ms']['median']} / {inside['script_and_layout_ms']['max']} ms"
                  f" ({inside['updates']} updates, answer of {inside['answer_bytes']} characters)")
            print(f"  Performance.getMetrics, mean per poll: all main-thread tasks of the second {update['TaskDuration_ms_per_poll']} ms"
                  f" (of them layout {update['LayoutDuration_ms_per_poll']} ms, style {update['RecalcStyleDuration_ms_per_poll']} ms,"
                  f" script outside promise callbacks {update['ScriptDuration_ms_per_poll']} ms)")
            print(f"  DOM nodes alive after a forced GC: {update['nodes_after_gc']['before']} before,"
                  f" {update['nodes_after_gc']['after']} after the {update['polls']} polls")
        for key, title in (("dom_normal", "DOM, `normal`"), ("dom_withdrawal", "DOM, withdrawal")):
            dom = entry[key]
            print(f"{title}: {dom['elements']} elements,"
                  f" {dom['schemeSvg']} in the scheme SVG, {dom['allSvg']} in all SVG, {dom['legend']} in the legend")
        idle = entry["idle_requests"]
        print(f"requests while idle: {idle['requests']} to /ditto/ in {idle['seconds']} s = {idle['per_second']} per second;"
              f" other requests: {idle['other_requests']}")
        print(f"console errors during the measurement: {entry['console_errors']} (scheme), {entry['stage_3d']['console_errors']} (3D)")
    static = result["static"]
    print(f"\nstatic files of public/: {static['files']} files, {static['total_bytes']} bytes"
          f" ({static['total_bytes'] / 1024:.1f} KiB), not compressed")
    for item in static["largest"]:
        print(f"  {item['bytes']:>7} bytes  {item['file']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--measure", action="store_true", help="measure the budgets instead of taking screenshots")
    parser.add_argument("--only", default=None, help="take only the shots whose name contains this text")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not chrome_available():
        print("Chrome не найден: снимки и измерения не выполнены")
        return 2
    if args.measure:
        result = measure()
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(os.path.join(OUTPUT_DIR, "measurements.json"), "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=1)
        print_measurements(result)
        return 0
    written, problems = take_screenshots(args.only)
    for path in written:
        print(path)
    print(f"{len(written)} files written to {SHOTS_DIR}")
    for problem in problems:
        print("PROBLEM: " + problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
