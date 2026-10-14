"""Tests of the test harness itself: the CDP driver and the helpers in browser_support.

    python -m unittest discover -s team/ui/tests -t team/ui -p "test_harness_smoke.py" -v

The WebSocket, MockServer and skip-reporting tests need no browser. Everything
else runs real headless Chrome against small fixture pages written to a temp
directory, and is reported as skipped when Chrome is absent.
"""

import base64
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock

from browser_support import (
    CHROME_MISSING_MESSAGE,
    OUTPUT_DIR,
    BrowserTestCase,
    MockServer,
    MockServerError,
    StaticServer,
    _parse_listening_line,
    chrome_available,
    failure_artifact_path,
    png_size,
    read_png,
    repo_path,
    requires_chrome,
    wait_until,
)
import cdp
from cdp import Browser, CdpError, ChromeNotFound, ElementError, JsError, NavigationError, WaitTimeout

INDEX_HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Harness fixture</title>
<style>
  body { margin: 0; font: 16px sans-serif; }
  #hidden { display: none; }
  #covered { position: absolute; top: 200px; left: 20px; width: 120px; height: 40px; }
  #cover { position: absolute; top: 190px; left: 10px; width: 200px; height: 80px; background: #ccc; }
  #svg { position: absolute; top: 300px; left: 20px; }
  #far { position: absolute; top: 3000px; left: 20px; }
</style>
</head>
<body>
<button id="a" data-testid="btn-a" data-thing-id="team040.mine:w-01">  Alpha
   button </button>
<button id="b" data-testid="btn-b">Beta</button>
<select id="s"><option value="one">One</option><option value="two">Two</option><option value="three">Three</option></select>
<button id="hidden">Hidden</button>
<button id="covered">Covered</button>
<div id="cover" data-testid="cover"></div>
<svg id="svg" width="300" height="120">
  <g id="working" tabindex="0" role="button" aria-label="Выработка w-01">
    <line x1="10" y1="10" x2="290" y2="110" stroke="#000" stroke-width="8"/>
  </g>
  <path id="bent" d="M 10 115 L 10 80 L 120 80" fill="none" stroke="#000" stroke-width="6"/>
</svg>
<button id="far">Far</button>
<script>
  window.initSeenByPageScript = window.__initMarker || null;
  window.events = [];
  for (const id of ["a", "b", "far", "covered", "cover", "working", "bent"]) {
    document.getElementById(id).addEventListener("click", (event) => {
      window.events.push("click:" + id + (event.isTrusted ? ":trusted" : ":synthetic"));
    });
  }
  document.addEventListener("keydown", (event) => {
    window.events.push("keydown:" + event.key + (event.shiftKey ? ":shift" : ""));
  });
  document.getElementById("s").addEventListener("change", (event) => {
    window.events.push("change:" + event.target.value);
  });
  setTimeout(() => { window.lateValue = "arrived"; }, 300);
</script>
</body>
</html>
"""

COLORS_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Colours</title>
<style>
  body { margin: 0; background: #fff; }
  div { position: absolute; top: 0; width: 100px; height: 100px; }
</style></head>
<body>
<div style="left: 0; background: #ff0000"></div>
<div style="left: 100px; background: #00ff00"></div>
</body></html>
"""

TALL_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Tall</title>
<style>body { margin: 0; } div { height: 2500px; background: linear-gradient(#fff, #888); }</style></head>
<body><div></div></body></html>
"""

ERRORS_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Errors</title></head>
<body>
<script>
console.warn("fixture warning");
console.error("fixture console error", {code: 7});
setTimeout(() => { throw new Error("fixture uncaught"); }, 0);
Promise.reject(new Error("fixture rejection"));
</script>
</body></html>
"""

MODULE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Module</title></head>
<body><script type="module" src="./main.js"></script></body></html>
"""

MAIN_JS = """import { answer, label } from "./dep.js";
window.moduleValue = answer;
document.body.dataset.module = label;
"""

DEP_JS = """export const answer = 42;
export const label = "готово";
"""

FIXTURE_FILES = {
    "index.html": INDEX_HTML,
    "colors.html": COLORS_HTML,
    "tall.html": TALL_HTML,
    "errors.html": ERRORS_HTML,
    "module.html": MODULE_HTML,
    "main.js": MAIN_JS,
    "dep.js": DEP_JS,
    "data.json": '{"ok": true}\n',
}


def closed_port():
    """A 127.0.0.1 port nothing listens on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# --------------------------------------------------------------------------
# WebSocket client against a scripted server (no browser needed)
# --------------------------------------------------------------------------

def server_frame(opcode, payload, fin=True):
    """An unmasked server frame with the shortest length encoding."""
    head = bytes([(0x80 if fin else 0) | opcode])
    size = len(payload)
    if size < 126:
        head += bytes([size])
    elif size < 65536:
        head += bytes([126]) + struct.pack(">H", size)
    else:
        head += bytes([127]) + struct.pack(">Q", size)
    return head + payload


def read_exact(connection, size):
    data = b""
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise ConnectionError("client hung up")
        data += chunk
    return data


def read_client_frame(connection):
    """Read one client frame; return (opcode, payload, was it masked)."""
    first, second = read_exact(connection, 2)
    size = second & 0x7F
    if size == 126:
        (size,) = struct.unpack(">H", read_exact(connection, 2))
    elif size == 127:
        (size,) = struct.unpack(">Q", read_exact(connection, 8))
    masked = bool(second & 0x80)
    key = read_exact(connection, 4) if masked else b"\0\0\0\0"
    payload = bytes(byte ^ key[i % 4] for i, byte in enumerate(read_exact(connection, size)))
    return first & 0x0F, payload, masked


class ScriptedWebSocketServer:
    """Accepts one client, upgrades it, then runs `script(connection, notes)` in a thread."""

    def __init__(self, script, break_accept=False):
        self.notes = {}
        self.error = None
        self._script = script
        self._break_accept = break_accept
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self.url = f"ws://127.0.0.1:{self._listener.getsockname()[1]}/devtools/test"
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        try:
            connection, _ = self._listener.accept()
            with connection:
                connection.settimeout(10)
                request = b""
                while b"\r\n\r\n" not in request:
                    request += connection.recv(4096)
                self.notes["request"] = request.decode("latin-1")
                key = re.search(r"Sec-WebSocket-Key: (\S+)", self.notes["request"]).group(1)
                accept = base64.b64encode(
                    hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
                if self._break_accept:
                    accept = "wrong" + accept[5:]
                connection.sendall((
                    "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode())
                self._script(connection, self.notes)
        except Exception as error:  # reported by the test through `finish`
            self.error = error

    def finish(self):
        self._thread.join(timeout=10)
        self._listener.close()
        if self.error is not None:
            raise self.error


class WebSocketClientTest(unittest.TestCase):
    def test_fragments_ping_lengths_masking_and_close(self):
        word = "привет".encode("utf-8")
        medium = "m" * 300                       # 16-bit length
        large = bytes(range(256)) * 300          # 76 800 bytes: 64-bit length

        def script(connection, notes):
            # A text message cut into three frames inside a UTF-8 character, a ping in between.
            connection.sendall(server_frame(0x1, word[:3], fin=False))
            connection.sendall(server_frame(0x9, b"ping-1"))
            connection.sendall(server_frame(0x0, word[3:7], fin=False))
            connection.sendall(server_frame(0x0, word[7:], fin=True))
            notes["pong"] = read_client_frame(connection)
            connection.sendall(server_frame(0x1, medium.encode()))
            connection.sendall(server_frame(0x2, large))
            notes["received"] = [read_client_frame(connection) for _ in range(3)]
            connection.sendall(server_frame(0x8, struct.pack(">H", 1000) + b"bye"))
            notes["close"] = read_client_frame(connection)

        server = ScriptedWebSocketServer(script)
        client = cdp.WebSocket(server.url)
        self.addCleanup(client.close)
        self.assertEqual(client.recv(timeout=5), "привет")
        self.assertEqual(client.recv(timeout=5), medium)
        self.assertEqual(client.recv(timeout=5), large)
        client.send("small")
        client.send(medium)
        client.send(large)
        with self.assertRaises(cdp.WebSocketClosed) as closed:
            client.recv(timeout=5)
        server.finish()

        self.assertEqual((closed.exception.code, closed.exception.reason), (1000, "bye"))
        self.assertIn("Sec-WebSocket-Version: 13", server.notes["request"])
        self.assertNotIn("Origin:", server.notes["request"])
        self.assertEqual(server.notes["pong"], (0xA, b"ping-1", True))
        self.assertEqual(server.notes["received"], [
            (0x1, b"small", True),
            (0x1, medium.encode(), True),
            (0x2, large, True),
        ])
        self.assertEqual(server.notes["close"][0], 0x8)
        self.assertTrue(server.notes["close"][2], "the close frame of a client must be masked")

    def test_receive_timeout_keeps_a_partial_frame(self):
        timed_out = threading.Event()
        frame = server_frame(0x1, b"x" * 1000)

        def script(connection, notes):
            connection.sendall(frame[:400])
            timed_out.wait(5)
            connection.sendall(frame[400:])
            connection.sendall(server_frame(0x1, b"next"))
            read_client_frame(connection)

        server = ScriptedWebSocketServer(script)
        client = cdp.WebSocket(server.url)
        started = time.monotonic()
        with self.assertRaises(cdp.WebSocketTimeout):
            client.recv(timeout=0.3)
        self.assertLess(time.monotonic() - started, 2.0)
        timed_out.set()
        self.assertEqual(client.recv(timeout=5), "x" * 1000)
        self.assertEqual(client.recv(timeout=5), "next")
        client.close()
        server.finish()

    def test_wrong_accept_key_is_refused(self):
        server = ScriptedWebSocketServer(lambda connection, notes: None, break_accept=True)
        with self.assertRaises(CdpError):
            cdp.WebSocket(server.url)
        server.finish()


# --------------------------------------------------------------------------
# The driver in real headless Chrome
# --------------------------------------------------------------------------

class DriverTest(BrowserTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.site_dir = tempfile.mkdtemp(prefix="harness-site-")
        cls.addClassCleanup(shutil.rmtree, cls.site_dir, True)
        for name, text in FIXTURE_FILES.items():
            with open(os.path.join(cls.site_dir, name), "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        cls.server = StaticServer(cls.site_dir).start()
        cls.addClassCleanup(cls.server.stop)

    def open(self, name="index.html"):
        self.page.goto(f"{self.server.url}/{name}")

    def events(self):
        return self.page.evaluate("window.events")

    # ---- navigation and evaluate ----

    def test_goto_resolves_after_load(self):
        self.open()
        self.assertEqual(self.page.evaluate("document.readyState"), "complete")
        self.assertEqual(self.page.evaluate("document.title"), "Harness fixture")
        self.assertEqual(self.page.evaluate("location.pathname"), "/index.html")

    def test_goto_fragment_change_returns_without_reload(self):
        self.open()
        self.page.evaluate("window.keptAcrossHashChange = true")
        started = time.monotonic()
        self.page.goto(f"{self.server.url}/index.html#/list?type=worker")
        self.assertLess(time.monotonic() - started, 3.0)
        self.assertEqual(self.page.evaluate("location.hash"), "#/list?type=worker")
        self.assertIs(self.page.evaluate("window.keptAcrossHashChange"), True)

    def test_reload_gives_a_new_document(self):
        self.open()
        self.page.evaluate("window.keptAcrossHashChange = true")
        self.page.reload()
        self.assertIsNone(self.page.evaluate("window.keptAcrossHashChange"))

    def test_goto_unreachable_server_raises(self):
        with self.assertRaises(NavigationError) as raised:
            self.page.goto(f"http://127.0.0.1:{closed_port()}/")
        self.assertIn("ERR_CONNECTION_REFUSED", str(raised.exception))

    def test_evaluate_values(self):
        self.open()
        self.assertEqual(self.page.evaluate("1 + 2"), 3)
        self.assertEqual(self.page.evaluate("({a: [1, 'x', null], b: {c: true}})"),
                         {"a": [1, "x", None], "b": {"c": True}})
        self.assertIsNone(self.page.evaluate("undefined"))
        self.assertIsNone(self.page.evaluate("null"))
        self.assertEqual(self.page.evaluate("'Шахта № ' + 'Ⅰ'"), "Шахта № Ⅰ")
        self.assertEqual(self.page.evaluate("document.querySelector('#working').getAttribute('aria-label')"),
                         "Выработка w-01")

    def test_evaluate_awaits_promises(self):
        self.open()
        self.assertEqual(self.page.evaluate("Promise.resolve(7)"), 7)
        self.assertEqual(
            self.page.evaluate("new Promise((resolve) => setTimeout(() => resolve('later'), 50))"), "later")
        self.assertEqual(self.page.evaluate("fetch('/data.json').then((response) => response.json())"), {"ok": True})

    def test_evaluate_large_messages_both_ways(self):
        # Above 65 535 bytes the WebSocket frame switches to a 64-bit length.
        self.open()
        self.assertEqual(self.page.evaluate("'ж'.repeat(200000)"), "ж" * 200000)
        self.assertEqual(self.page.evaluate("'" + "y" * 150000 + "'.length"), 150000)

    def test_evaluate_exception_raises_js_error(self):
        self.open()
        with self.assertRaises(JsError) as thrown:
            self.page.evaluate("(() => { throw new Error('boom'); })()")
        self.assertEqual(thrown.exception.message, "Error: boom")
        self.assertIn("boom", thrown.exception.stack)
        self.assertIn("at ", thrown.exception.stack)
        with self.assertRaises(JsError) as rejected:
            self.page.evaluate("Promise.reject(new TypeError('rejected'))")
        self.assertIn("TypeError: rejected", rejected.exception.message)
        with self.assertRaises(JsError) as syntax:
            self.page.evaluate("][")
        self.assertIn("SyntaxError", syntax.exception.message)
        # None of these reached the page's own error log (checked again at teardown).
        self.assertEqual(self.page.console_errors, [])

    def test_wait_for_returns_the_truthy_value(self):
        self.open()
        self.assertIsNone(self.page.evaluate("window.lateValue"))
        self.assertEqual(self.page.wait_for("window.lateValue", timeout=5), "arrived")
        self.assertEqual(self.page.wait_for("[]", timeout=1), [], "an empty array is truthy in JavaScript")

    def test_wait_for_tolerates_errors_until_the_element_exists(self):
        self.open()
        self.page.evaluate("setTimeout(() => { const el = document.createElement('p'); el.id = 'late'; "
                           "el.textContent = 'here'; document.body.append(el); }, 300)")
        self.assertEqual(self.page.wait_for("document.querySelector('#late').textContent", timeout=5), "here")

    def test_wait_for_timeout(self):
        self.open()
        started = time.monotonic()
        with self.assertRaises(WaitTimeout) as raised:
            self.page.wait_for("window.neverSet", timeout=0.5, message="neverSet did not appear")
        self.assertLess(time.monotonic() - started, 3.0)
        self.assertIn("neverSet did not appear", str(raised.exception))
        self.assertIsNone(raised.exception.last_value)
        self.assertIsInstance(raised.exception, AssertionError)
        with self.assertRaises(WaitTimeout) as zero:
            self.page.wait_for("0", timeout=0.3)
        self.assertEqual(zero.exception.last_value, 0)
        with self.assertRaises(WaitTimeout) as broken:
            self.page.wait_for("document.querySelector('#absent').textContent", timeout=0.3)
        self.assertIsInstance(broken.exception.last_error, JsError)
        self.assertIn("TypeError", str(broken.exception))

    # ---- viewport, screenshots, vision ----

    def test_default_viewport_is_the_browser_size(self):
        self.open()
        self.assertEqual(self.page.evaluate("[innerWidth, innerHeight, devicePixelRatio]"), [1280, 720, 1])

    def test_set_viewport(self):
        self.open()
        self.page.set_viewport(1920, 1080)
        self.assertEqual(self.page.evaluate("[innerWidth, innerHeight]"), [1920, 1080])
        self.page.set_viewport(800, 600)
        self.assertEqual(self.page.evaluate("[innerWidth, innerHeight]"), [800, 600])

    def test_screenshot_is_a_png_of_the_viewport_size(self):
        self.open()
        directory = tempfile.mkdtemp(prefix="harness-shots-")
        self.addCleanup(shutil.rmtree, directory, True)
        small = self.page.screenshot(os.path.join(directory, "new", "nested", "hd.png"))
        with open(small, "rb") as handle:
            self.assertEqual(handle.read(8), b"\x89PNG\r\n\x1a\n")
        self.assertEqual(png_size(small), (1280, 720))
        self.page.set_viewport(1920, 1080)
        large = self.page.screenshot(os.path.join(directory, "fullhd.png"))
        self.assertEqual(png_size(large), (1920, 1080))
        self.assertGreater(os.path.getsize(large), 1000)

    def test_screenshot_full_page_scale_and_clip(self):
        self.open("tall.html")
        directory = tempfile.mkdtemp(prefix="harness-shots-")
        self.addCleanup(shutil.rmtree, directory, True)
        self.assertEqual(png_size(self.page.screenshot(os.path.join(directory, "full.png"), full_page=True)),
                         (1280, 2500))
        self.assertEqual(png_size(self.page.screenshot(os.path.join(directory, "clip.png"), clip=(10, 20, 64, 48))),
                         (64, 48))
        self.page.set_viewport(400, 300, device_scale_factor=2)
        self.assertEqual(png_size(self.page.screenshot(os.path.join(directory, "dense.png"))), (800, 600))

    def test_achromatopsia_makes_red_and_green_grey(self):
        self.open("colors.html")
        directory = tempfile.mkdtemp(prefix="harness-shots-")
        self.addCleanup(shutil.rmtree, directory, True)

        def patches(name):
            image = read_png(self.page.screenshot(os.path.join(directory, name), clip=(0, 0, 200, 100)))
            self.assertEqual((image.width, image.height), (200, 100))
            return image.pixel(50, 50)[:3], image.pixel(150, 50)[:3]

        self.assertEqual(patches("colour.png"), ((255, 0, 0), (0, 255, 0)))
        self.page.emulate_vision("achromatopsia")
        red, green = patches("grey.png")
        for name, (r, g, b) in (("red", red), ("green", green)):
            self.assertTrue(r == g == b, f"the {name} patch is not grey under achromatopsia: {(r, g, b)}")
        self.assertNotEqual(red, green, "the two greys must still differ in lightness")
        self.page.emulate_vision("none")
        self.assertEqual(patches("colour-again.png"), ((255, 0, 0), (0, 255, 0)))
        with self.assertRaises(ValueError):
            self.page.emulate_vision("sepia")

    # ---- mouse and keyboard ----

    def test_click_is_a_trusted_mouse_click(self):
        self.open()
        point = self.page.click("#b")
        self.assertEqual(self.events(), ["click:b:trusted"])
        self.assertEqual(self.page.evaluate("document.elementFromPoint(%f, %f).id" % (point["x"], point["y"])), "b")
        self.assertEqual(self.page.focus_info()["id"], "b", "a mouse click focuses the button")

    def test_click_scrolls_the_element_into_view(self):
        self.open()
        self.assertEqual(self.page.evaluate("scrollY"), 0)
        self.page.click("#far")
        self.assertEqual(self.events(), ["click:far:trusted"])
        self.assertGreater(self.page.evaluate("scrollY"), 0)

    def test_click_on_svg_shapes(self):
        self.open()
        self.page.click("#working")   # a group holding a diagonal line
        self.page.click("#bent")      # the centre of its bounding box is empty
        self.assertEqual(self.events(), ["click:working:trusted", "click:bent:trusted"])

    def test_click_errors(self):
        self.open()
        with self.assertRaisesRegex(ElementError, "no element matches '#absent'"):
            self.page.click("#absent")
        with self.assertRaisesRegex(ElementError, "has no size"):
            self.page.click("#hidden")
        with self.assertRaisesRegex(ElementError, r'div#cover\[data-testid="cover"\]'):
            self.page.click("#covered")
        self.assertEqual(self.events(), [])
        self.page.click("#covered", force=True)
        self.assertEqual(self.events(), ["click:cover:trusted"])

    def test_click_waits_for_a_late_element(self):
        self.open()
        self.page.evaluate("setTimeout(() => { const b = document.createElement('button'); b.id = 'late-button'; "
                           "b.textContent = 'Late'; b.onclick = () => window.events.push('click:late'); "
                           "document.body.prepend(b); }, 300)")
        self.page.click("#late-button", timeout=5)
        self.assertEqual(self.events(), ["click:late"])

    def test_tab_moves_focus_and_enter_space_activate(self):
        self.open()
        self.assertEqual(self.page.focus_info()["tag"], "body")
        self.page.press("Tab")
        self.assertEqual(self.page.focus_info()["id"], "a")
        self.page.press("Tab")
        self.assertEqual(self.page.focus_info()["id"], "b")
        self.page.press("Tab", shift=True)
        self.assertEqual(self.page.focus_info()["id"], "a")
        self.assertTrue(self.page.evaluate("document.activeElement.matches(':focus-visible')"))
        self.page.press("Enter")
        self.page.press("Space")
        self.assertEqual(self.events(), [
            "keydown:Tab", "keydown:Tab", "keydown:Shift:shift", "keydown:Tab:shift",
            "keydown:Enter", "click:a:trusted", "keydown: ", "click:a:trusted",
        ])

    def test_escape_arrows_and_characters_are_delivered(self):
        self.open()
        self.page.press("Escape")
        self.page.press("x")
        self.page.press("ArrowUp")
        self.assertEqual(self.events(), ["keydown:Escape", "keydown:x", "keydown:ArrowUp"])
        for _ in range(3):
            self.page.press("Tab")
        self.assertEqual(self.page.focus_info()["id"], "s")
        self.page.press("ArrowDown")
        self.assertEqual(self.page.wait_for("document.getElementById('s').value === 'two' && 'two'", timeout=3), "two")
        self.assertIn("change:two", self.events())
        with self.assertRaises(ValueError):
            self.page.press("NoSuchKey")

    def test_focus_info(self):
        self.open()
        self.page.press("Tab")
        info = self.page.focus_info()
        self.assertEqual(info["tag"], "button")
        self.assertEqual(info["id"], "a")
        self.assertEqual(info["data-testid"], "btn-a")
        self.assertEqual(info["testid"], "btn-a")
        self.assertEqual(info["text"], "Alpha button")
        self.assertEqual(info["dataset"], {"testid": "btn-a", "thingId": "team040.mine:w-01"})
        self.page.evaluate("document.getElementById('working').focus()")
        info = self.page.focus_info()
        self.assertEqual((info["tag"], info["role"], info["aria-label"]), ("g", "button", "Выработка w-01"))
        self.page.evaluate("document.getElementById('a').textContent = 'я'.repeat(200)")
        self.page.evaluate("document.getElementById('a').focus()")
        self.assertEqual(self.page.focus_info()["text"], "я" * 80)

    # ---- init scripts, modules, dialogs, metrics ----

    def test_init_script_runs_before_page_scripts_on_every_navigation(self):
        self.page.add_init_script("window.__initMarker = 'set before page scripts';")
        self.open()
        self.assertEqual(self.page.evaluate("window.initSeenByPageScript"), "set before page scripts")
        self.open("module.html")
        self.assertEqual(self.page.evaluate("window.__initMarker"), "set before page scripts")

    def test_es_module_page_loads(self):
        self.open("module.html")
        self.assertEqual(self.page.wait_for("window.moduleValue", timeout=5), 42)
        self.assertEqual(self.page.evaluate("document.body.dataset.module"), "готово")
        scripts = {entry["url"].rsplit("/", 1)[-1]: entry["status"]
                   for entry in self.page.requests if entry["type"] == "Script"}
        self.assertEqual(scripts, {"main.js": 200, "dep.js": 200})

    def test_native_dialog_does_not_block_the_page(self):
        self.open()
        self.assertEqual(self.page.evaluate("(() => { alert('fixture alert'); return 'after'; })()"), "after")
        self.assertIs(self.page.evaluate("confirm('fixture confirm')"), False)
        self.assertEqual(self.page.dialogs, [
            {"type": "alert", "message": "fixture alert"},
            {"type": "confirm", "message": "fixture confirm"},
        ])

    def test_metrics(self):
        self.open()
        metrics = self.page.metrics()
        self.assertGreater(metrics["Nodes"], 10)
        for name in ("ScriptDuration", "LayoutDuration", "JSHeapUsedSize", "JSEventListeners"):
            self.assertIn(name, metrics)
            self.assertGreaterEqual(metrics[name], 0)

    # ---- network and console recording ----

    def test_requests_record_status_method_and_body(self):
        self.open()
        document = self.page.wait_for_request("/index.html")
        self.assertEqual((document["method"], document["status"], document["failed"]), ("GET", 200, False))

        self.assertEqual(self.page.evaluate("fetch('/data.json?n=1').then((response) => response.status)"), 200)
        fetched = self.page.wait_for_request("/data.json?n=1")
        self.assertEqual(fetched["url"], f"{self.server.url}/data.json?n=1")
        self.assertEqual((fetched["method"], fetched["status"], fetched["failed"]), ("GET", 200, False))

        self.assertEqual(self.page.evaluate("fetch('/missing.json').then((response) => response.status)"), 404)
        missing = self.page.wait_for_request("/missing.json")
        self.assertEqual((missing["status"], missing["failed"]), (404, False))

        body = json.dumps({"command_id": "c-0123", "type": "run.reset"})
        self.page.evaluate("fetch('/commands', {method: 'POST', headers: {'Content-Type': 'application/json'}, "
                           f"body: {json.dumps(body)}}}).then((response) => response.status)")
        posted = self.page.wait_for_request("/commands", method="POST")
        self.assertEqual(posted["post_data"], body)
        self.assertEqual(posted["status"], 501, "the static fixture server implements no POST")

    def test_requests_record_a_failed_connection(self):
        self.open()
        url = f"http://127.0.0.1:{closed_port()}/unreachable"
        outcome = self.page.evaluate(f"fetch({json.dumps(url)}).then(() => 'answered', () => 'failed')")
        self.assertEqual(outcome, "failed")
        entry = self.page.wait_for_request("/unreachable")
        self.assertIs(entry["failed"], True)
        self.assertIsNone(entry["status"])
        self.assertIn("ERR_CONNECTION_REFUSED", entry["error"])
        # A failed load is a network fact, not a script error: it is in the
        # browser log and in `requests`, and does not fail the test at teardown.
        wait_until(lambda: [entry for entry in self.page.log_entries if entry["source"] == "network"],
                   message="no network entry in the browser log")
        self.assertEqual(self.page.console_errors, [])

    def test_console_errors_capture_exceptions_and_console_error(self):
        self.allow_console_errors = True
        self.open("errors.html")
        wait_until(lambda: len(self.page.console_errors) >= 3, message="expected three console errors")
        by_kind = {}
        for entry in self.page.console_errors:
            by_kind.setdefault(entry["kind"], []).append(entry)
        self.assertEqual(sorted(by_kind), ["console.error", "exception"])

        logged = by_kind["console.error"][0]
        self.assertEqual(logged["text"], "fixture console error {code: 7}")
        self.assertEqual(logged["url"], f"{self.server.url}/errors.html")
        self.assertEqual(logged["line"], ERRORS_HTML.split("\n").index(
            'console.error("fixture console error", {code: 7});') + 1)

        thrown = sorted(entry["text"].split("\n")[0] for entry in by_kind["exception"])
        self.assertEqual(thrown, ["Uncaught (in promise) Error: fixture rejection", "Uncaught Error: fixture uncaught"])
        for entry in by_kind["exception"]:
            self.assertEqual(entry["url"], f"{self.server.url}/errors.html")
            self.assertGreater(entry["line"], 0)

        self.assertIn("fixture warning", [entry["text"] for entry in self.page.console_messages])
        self.assertNotIn("fixture warning", [entry["text"] for entry in self.page.console_errors])

    def test_clear_logs(self):
        self.allow_console_errors = True
        self.open("errors.html")
        wait_until(lambda: len(self.page.console_errors) >= 3)
        errors, requests = self.page.console_errors, self.page.requests
        self.assertTrue(requests)
        self.page.clear_logs()
        self.assertEqual((self.page.console_errors, self.page.requests, self.page.console_messages), ([], [], []))
        self.assertIs(self.page.console_errors, errors, "the lists are emptied in place")
        self.assertIs(self.page.requests, requests)
        self.page.evaluate("fetch('/data.json').then((response) => response.status)")
        self.assertEqual(self.page.wait_for_request("/data.json")["status"], 200)

    def test_each_test_gets_its_own_page(self):
        self.assertEqual(self.page.evaluate("location.href"), "about:blank")
        self.assertEqual(self.page.requests, [])
        other = self.browser.new_page()
        self.addCleanup(other.close)
        other.goto(f"{self.server.url}/index.html")
        self.open("colors.html")
        self.assertEqual(other.evaluate("document.title"), "Harness fixture")
        self.assertEqual(self.page.evaluate("document.title"), "Colours")
        self.assertFalse([entry for entry in self.page.requests if "index.html" in entry["url"]])


# --------------------------------------------------------------------------
# Process and profile cleanup
# --------------------------------------------------------------------------

def chrome_command_lines_mentioning(marker):
    """How many chrome.exe processes carry `marker` in their command line; None when it cannot be asked."""
    if os.name != "nt":
        return None
    query = "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | ForEach-Object { $_.CommandLine }"
    try:
        listing = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", query],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if listing.returncode != 0:
        return None
    return sum(marker in line for line in listing.stdout.decode("utf-8", "replace").splitlines())


@requires_chrome
class ProcessCleanupTest(unittest.TestCase):
    def assert_gone(self, pids, profile_dir):
        wait_until(lambda: not cdp.alive_pids(pids), timeout=10,
                   message=f"Chrome processes still running: {cdp.alive_pids(pids)}")
        self.assertFalse(os.path.exists(profile_dir), f"temp profile left behind: {profile_dir}")

    def test_close_leaves_no_chrome_process_and_no_profile(self):
        browser = Browser()
        self.addCleanup(browser.close)
        page = browser.new_page()
        page.goto("data:text/html,<title>cleanup</title>")
        self.assertRegex(browser.version(), r"^(Headless)?Chrome/\d+")
        pids = browser.process_ids()
        marker = os.path.basename(browser.profile_dir)
        self.assertEqual(pids[0], browser.pid)
        self.assertGreaterEqual(len(pids), 3, "expected the browser process with renderer and helper children")
        self.assertTrue(os.path.isdir(browser.profile_dir))
        seen_before = chrome_command_lines_mentioning(marker)

        browser.close()
        browser.close()  # a second call is harmless
        page.close()     # so is closing a page of a closed browser

        self.assert_gone(pids, browser.profile_dir)
        if seen_before:  # an independent look at the process list, by command line
            self.assertEqual(chrome_command_lines_mentioning(marker), 0)
        with self.assertRaises(CdpError):
            browser.new_page()
        with self.assertRaises(CdpError):
            page.evaluate("1")

    def test_context_manager_cleans_up_when_the_body_raises(self):
        with self.assertRaisesRegex(RuntimeError, "test body failed"):
            with Browser(width=800, height=600) as browser:
                page = browser.new_page()
                self.assertEqual(page.evaluate("[innerWidth, innerHeight]"), [800, 600])
                pids, profile_dir = browser.process_ids(), browser.profile_dir
                raise RuntimeError("test body failed")
        self.assert_gone(pids, profile_dir)

    def test_extra_args_reach_chrome(self):
        with Browser(extra_args=("--user-agent=HarnessSmoke/1.0",)) as browser:
            self.assertEqual(browser.new_page().evaluate("navigator.userAgent"), "HarnessSmoke/1.0")

    @unittest.skipUnless(os.name == "nt", "the kill-on-exit job object exists on Windows only")
    def test_chrome_dies_with_a_killed_test_runner(self):
        script = textwrap.dedent(f"""
            import json, os, sys
            sys.path.insert(0, {repo_path("team", "ui", "tools")!r})
            import cdp
            browser = cdp.Browser()
            browser.new_page()
            print(json.dumps({{"pids": browser.process_ids(), "profile": browser.profile_dir}}), flush=True)
            os._exit(3)  # no atexit, no finally: as if the runner had been killed
        """)
        finished = subprocess.run([sys.executable, "-c", script], stdin=subprocess.DEVNULL,
                                  capture_output=True, timeout=60, check=False)
        self.assertEqual(finished.returncode, 3, finished.stderr.decode("utf-8", "replace"))
        report = json.loads(finished.stdout)
        self.assertGreaterEqual(len(report["pids"]), 2)
        wait_until(lambda: not cdp.alive_pids(report["pids"]), timeout=10,
                   message=f"orphaned Chrome processes: {cdp.alive_pids(report['pids'])}")
        # The dead runner could not delete its profile; the next browser start
        # sweeps it (here, or in a test run going on next to this one).
        wait_until(lambda: report["profile"] in cdp.sweep_stale_profiles() or not os.path.exists(report["profile"]),
                   timeout=10, message="the orphaned profile was not swept")
        self.assertFalse(os.path.exists(report["profile"]))


# --------------------------------------------------------------------------
# BrowserTestCase rules and skip reporting
# --------------------------------------------------------------------------

def run_case(case_class):
    result = unittest.TestResult()
    unittest.defaultTestLoader.loadTestsFromTestCase(case_class).run(result)
    return result


@requires_chrome
class BrowserTestCaseRulesTest(unittest.TestCase):
    def test_console_errors_fail_the_test_and_failures_leave_evidence(self):
        class Inner(BrowserTestCase):
            def test_clean(self):
                self.assertEqual(self.page.evaluate("1 + 1"), 2)

            def test_console_error(self):
                self.page.evaluate("console.error('inner console error')")

            def test_console_error_allowed(self):
                self.allow_console_errors = True
                self.page.evaluate("console.error('tolerated console error')")

            def test_failing(self):
                self.page.goto("data:text/html,<h1>evidence</h1>")
                self.assertEqual(self.page.evaluate("1 + 1"), 3, "deliberate failure")

        def artifacts(name):
            test_id = Inner(name).id()
            return failure_artifact_path(test_id), failure_artifact_path(test_id, ".txt")

        # The evidence of these deliberate failures goes to a private directory:
        # it must not pose as a real failure in test-output/, nor collide with
        # the same test in a run going on next to this one.
        self.assertEqual(OUTPUT_DIR, repo_path("team", "ui", "test-output"))
        output_dir = tempfile.mkdtemp(prefix="harness-output-")
        self.addCleanup(shutil.rmtree, output_dir, True)
        patcher = mock.patch("browser_support.OUTPUT_DIR", output_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

        result = run_case(Inner)

        self.assertEqual(result.testsRun, 4)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.skipped, [])
        failed = {test._testMethodName: text for test, text in result.failures}
        self.assertEqual(sorted(failed), ["test_console_error", "test_failing"])
        self.assertIn("inner console error", failed["test_console_error"])
        self.assertIn("deliberate failure", failed["test_failing"])

        for name in ("test_console_error", "test_failing"):
            screenshot, log = artifacts(name)
            self.assertEqual(os.path.dirname(screenshot), os.path.join(output_dir, "failures"))
            self.assertRegex(os.path.basename(screenshot), rf"^[A-Za-z0-9_.-]+\.Inner\.{name}\.png$")
            self.assertEqual(png_size(screenshot), (1280, 720))
            self.assertTrue(os.path.isfile(log))
        with open(artifacts("test_failing")[1], encoding="utf-8") as handle:
            self.assertIn("url: data:text/html,<h1>evidence</h1>", handle.read())
        for name in ("test_clean", "test_console_error_allowed"):
            self.assertFalse(os.path.exists(artifacts(name)[0]), "a passing test must leave no failure screenshot")
        self.assertIsNone(Inner.browser.close(), "the class browser is already closed; closing again is harmless")
        self.assertEqual(Inner.browser.process_ids(), [])


class MissingChromeTest(unittest.TestCase):
    def setUp(self):
        missing = os.path.join(tempfile.gettempdir(), "no-such-dir", "chrome.exe")
        patcher = mock.patch.dict(os.environ, {"CHROME_PATH": missing})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_find_chrome_honours_chrome_path(self):
        with self.assertRaisesRegex(ChromeNotFound, "CHROME_PATH"):
            cdp.find_chrome()
        self.assertFalse(chrome_available())
        with self.assertRaises(ChromeNotFound):
            Browser()
        with mock.patch.dict(os.environ, {"CHROME_PATH": sys.executable}):
            self.assertEqual(cdp.find_chrome(), sys.executable)

    def test_browser_tests_are_reported_as_skipped_not_passed(self):
        class WithBaseClass(BrowserTestCase):
            def test_never_runs(self):
                raise AssertionError("ran without Chrome")

        @requires_chrome
        class WithDecorator(unittest.TestCase):
            def test_never_runs(self):
                raise AssertionError("ran without Chrome")

        for case_class in (WithBaseClass, WithDecorator):
            with self.subTest(case_class.__name__):
                result = run_case(case_class)
                self.assertEqual([reason for _, reason in result.skipped], [CHROME_MISSING_MESSAGE])
                self.assertEqual((result.failures, result.errors), ([], []))
                self.assertTrue(result.wasSuccessful())


# --------------------------------------------------------------------------
# MockServer helper against a stand-in for mock_server.py
# --------------------------------------------------------------------------

STAND_IN_SERVER = '''
import argparse, json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, required=True)
parser.add_argument("--scenario", required=True)
parser.add_argument("--behave", default="serve")
args = parser.parse_args()

if args.behave == "crash":
    sys.stderr.write("stand-in: cannot start (тест)\\n")
    sys.exit(3)
if args.behave == "wrong-line":
    print("Serving on port 1234", flush=True)
    time.sleep(60)
if args.behave == "silent":
    time.sleep(60)

STATE = {"scenario": args.scenario, "fault": "none", "frame": 0, "port_argument": args.port}
LOG = []
FAULTS = ("none", "http_502", "http_503", "hang", "drop")


class Handler(BaseHTTPRequestHandler):
    def answer(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/__mock__/state":
            self.answer(200, STATE)
        elif self.path == "/__mock__/log":
            self.answer(200, LOG)
        elif self.path == "/__mock__/scenarios":
            self.answer(200, ["normal", "detour"])
        else:
            self.answer(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        LOG.append({"method": "POST", "path": self.path, "body": body,
                    "content_type": self.headers["Content-Type"]})
        if self.path == "/__mock__/scenario":
            STATE.update(scenario=body["name"], frame=0)
            self.answer(200, {"ok": True, "scenario": body["name"]})
        elif self.path == "/__mock__/fault" and body.get("mode") in FAULTS:
            STATE["fault"] = body["mode"]
            self.send_response(204)
            self.end_headers()
        else:
            self.answer(400, {"error": "unknown fault mode"})

    def log_message(self, format, *args):
        sys.stderr.write("x" * 8000 + "\\n")   # a chatty server must not block on its pipe


server = HTTPServer(("127.0.0.1", args.port), Handler)
print("LISTENING http://127.0.0.1:%d" % server.server_address[1], flush=True)
print("scenario " + args.scenario, flush=True)
server.serve_forever()
'''


class MockServerHelperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.mkdtemp(prefix="harness-mock-")
        cls.addClassCleanup(shutil.rmtree, directory, True)
        cls.script = os.path.join(directory, "stand_in_server.py")
        with open(cls.script, "w", encoding="utf-8") as handle:
            handle.write(STAND_IN_SERVER)

    def test_listening_line_parsing(self):
        self.assertEqual(_parse_listening_line("LISTENING http://127.0.0.1:8123"), ("http://127.0.0.1:8123", 8123))
        self.assertEqual(_parse_listening_line("LISTENING http://127.0.0.1:50555/\r\n"),
                         ("http://127.0.0.1:50555", 50555))
        for line in ("", "LISTENING", "LISTENING http://0.0.0.0:8123", "LISTENING http://127.0.0.1:port",
                     "Serving HTTP on 127.0.0.1 port 8123", "listening http://127.0.0.1:8123"):
            with self.subTest(line=line):
                with self.assertRaises(MockServerError):
                    _parse_listening_line(line)

    def test_start_control_api_and_termination(self):
        with MockServer("detour", script=self.script) as server:
            self.assertRegex(server.url, r"^http://127\.0\.0\.1:\d+$")
            self.assertEqual(server.url, f"http://127.0.0.1:{server.port}")
            pid = server.pid
            self.assertEqual(cdp.alive_pids([pid]), [pid])
            self.assertEqual(server.state(), {"scenario": "detour", "fault": "none", "frame": 0, "port_argument": 0})

            self.assertEqual(server.scenario("no_path"), {"ok": True, "scenario": "no_path"})
            self.assertIsNone(server.fault("http_502"), "an empty answer body is returned as None")
            self.assertEqual(server.state()["scenario"], "no_path")
            self.assertEqual(server.state()["fault"], "http_502")
            self.assertEqual(server.scenarios(), ["normal", "detour"])
            self.assertEqual(server.log(), [
                {"method": "POST", "path": "/__mock__/scenario", "body": {"name": "no_path"},
                 "content_type": "application/json"},
                {"method": "POST", "path": "/__mock__/fault", "body": {"mode": "http_502"},
                 "content_type": "application/json"},
            ])
            with self.assertRaisesRegex(MockServerError, "HTTP 400.*unknown fault mode"):
                server.fault("earthquake")
            with self.assertRaisesRegex(MockServerError, "HTTP 404"):
                server.request("GET", "/__mock__/nothing")

            # 30 more requests bring the stand-in's stderr to some 300 KB, far
            # more than a pipe holds: the helper must keep draining it.
            for _ in range(30):
                server.state()
            self.assertIn("scenario detour", server.output()["stdout"])
            self.assertTrue(server.output()["stderr"])

        wait_until(lambda: not cdp.alive_pids([pid]), message="the mock server process survived the with-block")
        self.assertIsNone(server.process)
        server.stop()  # a second call is harmless
        with self.assertRaisesRegex(MockServerError, "failed"):
            server.state()

    def test_start_and_stop_without_with(self):
        server = MockServer("normal", script=self.script).start()
        self.addCleanup(server.stop)
        self.assertIs(server.start(), server, "start() twice keeps the same process")
        self.assertEqual(server.state()["scenario"], "normal")
        pid = server.pid
        server.close()
        wait_until(lambda: not cdp.alive_pids([pid]))

    def test_server_that_exits_reports_its_stderr(self):
        server = MockServer("normal", script=self.script, extra_args=("--behave", "crash"))
        with self.assertRaises(MockServerError) as raised:
            server.start()
        self.assertIn("exited with code 3", str(raised.exception))
        self.assertIn("stand-in: cannot start (тест)", str(raised.exception))
        self.assertIsNone(server.process)

    def test_wrong_first_line_is_refused_and_the_process_killed(self):
        server = MockServer("normal", script=self.script, extra_args=("--behave", "wrong-line"))
        with self.assertRaisesRegex(MockServerError, "Serving on port 1234"):
            server.start()
        wait_until(lambda: not cdp.alive_pids([server.pid]), message="the refused server was left running")

    def test_silent_server_times_out_and_is_killed(self):
        server = MockServer("normal", script=self.script, startup_timeout=1.0, extra_args=("--behave", "silent"))
        started = time.monotonic()
        with self.assertRaisesRegex(MockServerError, "printed nothing within 1 s"):
            server.start()
        self.assertLess(time.monotonic() - started, 8.0)
        wait_until(lambda: not cdp.alive_pids([server.pid]), message="the silent server was left running")

    def test_missing_script(self):
        with self.assertRaisesRegex(MockServerError, "not found"):
            MockServer("normal", script=os.path.join(os.path.dirname(self.script), "absent.py")).start()

    def test_default_script_is_the_mock_server_of_the_spec(self):
        self.assertEqual(MockServer().script, repo_path("team", "ui", "tools", "mock_server.py"))
        self.assertTrue(os.path.isfile(repo_path("team", "ui", "DESIGN.md")), "repo_path must resolve from the root")


if __name__ == "__main__":
    unittest.main()
