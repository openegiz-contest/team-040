"""Shared helpers of the UI tests: headless Chrome, servers, paths, PNG reading.

    from browser_support import BrowserTestCase, MockServer

    class SchemeTest(BrowserTestCase):
        @classmethod
        def setUpClass(cls):
            super().setUpClass()                      # skips the class when Chrome is absent
            cls.mock = MockServer("normal").start()
            cls.addClassCleanup(cls.mock.stop)

        def test_boot(self):
            self.page.goto(self.mock.url + "/")
            self.page.wait_for("document.body.dataset.boot === 'ready'")

Standard library only. Nothing here starts a process at import time.
"""

from __future__ import annotations

import collections
import functools
import http.server
import json
import os
import queue
import re
import struct
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
import zlib

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_UI_DIR = os.path.dirname(_TESTS_DIR)
_TOOLS_DIR = os.path.join(_UI_DIR, "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

# One module object whether a test wrote `import browser_support`,
# `from tests.browser_support import ...` or `from .browser_support import ...`.
for _alias in ("browser_support", "tests.browser_support"):
    sys.modules.setdefault(_alias, sys.modules[__name__])

import cdp  # noqa: E402  (needs the sys.path entry above)
from cdp import (  # noqa: E402,F401  (re-exported for test modules)
    Browser,
    CdpError,
    CdpTimeout,
    ChromeNotFound,
    ElementError,
    JsError,
    NavigationError,
    Page,
    WaitTimeout,
)

CHROME_MISSING_MESSAGE = "Chrome не найден: браузерная проверка не выполнена"


def repo_path(*parts):
    """Absolute path below the worktree root, independent of the current directory."""
    return os.path.join(os.path.dirname(os.path.dirname(_UI_DIR)), *parts)


OUTPUT_DIR = repo_path("team", "ui", "test-output")
PUBLIC_DIR = repo_path("team", "ui", "public")
MOCK_SERVER_SCRIPT = repo_path("team", "ui", "tools", "mock_server.py")


def chrome_available():
    """True when a Chrome binary can be found (see `cdp.find_chrome`)."""
    try:
        cdp.find_chrome()
    except ChromeNotFound:
        return False
    return True


def requires_chrome(test_item):
    """Decorator for a test or a test class: reported as skipped, with the reason, when Chrome is absent."""
    return unittest.skipUnless(chrome_available(), CHROME_MISSING_MESSAGE)(test_item)


def wait_until(predicate, timeout=5.0, interval=0.05, message=""):
    """Poll a Python callable until it returns something truthy; return that value.

    For state that lives on the Python side (`page.requests`, `page.console_errors`,
    `mock.log()`). For state in the page use `page.wait_for`.
    """
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise WaitTimeout(f"{message or 'condition not met'} after {timeout:g} s; last value: {value!r}", value)
        time.sleep(interval)


# --------------------------------------------------------------------------
# PNG reading (screenshots)
# --------------------------------------------------------------------------

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}


def _png_chunks(data):
    if data[:8] != _PNG_SIGNATURE:
        raise ValueError("not a PNG file")
    position = 8
    while position + 8 <= len(data):
        length, kind = struct.unpack_from(">I4s", data, position)
        yield kind, data[position + 8:position + 8 + length]
        position += 12 + length


def png_size(path):
    """(width, height) in pixels, read from the IHDR chunk."""
    with open(path, "rb") as handle:
        head = handle.read(33)
    if head[:8] != _PNG_SIGNATURE or head[12:16] != b"IHDR":
        raise ValueError(f"{path} is not a PNG file")
    return struct.unpack(">II", head[16:24])


class PngImage:
    """Decoded 8-bit PNG. `pixel(x, y)` gives (r, g, b, a)."""

    def __init__(self, width, height, channels, rows):
        self.width = width
        self.height = height
        self._channels = channels
        self._rows = rows

    def pixel(self, x, y):
        start = x * self._channels
        sample = self._rows[y][start:start + self._channels]
        if self._channels == 1:
            return sample[0], sample[0], sample[0], 255
        if self._channels == 2:
            return sample[0], sample[0], sample[0], sample[1]
        if self._channels == 3:
            return sample[0], sample[1], sample[2], 255
        return tuple(sample)


def read_png(path):
    """Decode a PNG screenshot into a `PngImage`.

    Pure Python: a 1920x1080 screenshot takes about a second. To sample a few
    pixels take a small picture with `page.screenshot(path, clip=(x, y, w, h))`.
    """
    with open(path, "rb") as handle:
        data = handle.read()
    header = None
    compressed = []
    for kind, body in _png_chunks(data):
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            compressed.append(body)
    if header is None:
        raise ValueError(f"{path} has no IHDR chunk")
    width, height, depth, colour_type, _, _, interlace = header
    if depth != 8 or colour_type not in _PNG_CHANNELS or interlace:
        raise ValueError(f"{path}: unsupported PNG (depth {depth}, colour type {colour_type}, interlace {interlace})")
    channels = _PNG_CHANNELS[colour_type]
    stride = width * channels
    raw = zlib.decompress(b"".join(compressed))
    rows = []
    previous = bytes(stride)
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        line = bytearray(raw[position + 1:position + 1 + stride])
        position += stride + 1
        if filter_type == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:
            line = bytearray((a + b) & 0xFF for a, b in zip(line, previous))
        elif filter_type == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = previous[i]
                corner = previous[i - channels] if i >= channels else 0
                estimate = left + up - corner
                d_left, d_up, d_corner = abs(estimate - left), abs(estimate - up), abs(estimate - corner)
                if d_left <= d_up and d_left <= d_corner:
                    predictor = left
                elif d_up <= d_corner:
                    predictor = up
                else:
                    predictor = corner
                line[i] = (line[i] + predictor) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"{path}: unknown PNG filter {filter_type}")
        previous = bytes(line)
        rows.append(previous)
    return PngImage(width, height, channels, rows)


# --------------------------------------------------------------------------
# Static file server
# --------------------------------------------------------------------------

class _StaticHandler(http.server.SimpleHTTPRequestHandler):
    # Fixed types: on Windows the registry may map .js to text/plain, and
    # Chrome refuses to run a module script served with that type.
    extensions_map = {
        "": "application/octet-stream",
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".txt": "text/plain; charset=utf-8",
    }

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format, *args):
        pass


class _QuietHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], ConnectionError):  # the browser hung up: not an error
            super().handle_error(request, client_address)


class StaticServer:
    """Serve a directory on a free 127.0.0.1 port from a background thread.

        with StaticServer(directory) as server:
            page.goto(server.url + "/index.html")
    """

    def __init__(self, directory):
        self.directory = os.fspath(directory)
        self.url = None
        self.port = None
        self._server = None
        self._thread = None

    def start(self):
        if self._server is None:
            handler = functools.partial(_StaticHandler, directory=self.directory)
            self._server = _QuietHTTPServer(("127.0.0.1", 0), handler)
            self.port = self._server.server_address[1]
            self.url = f"http://127.0.0.1:{self.port}"
            self._thread = threading.Thread(target=self._server.serve_forever, name="static-server", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=5.0)
            self._server = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc_info):
        self.stop()


# --------------------------------------------------------------------------
# Mock server process (protocol: implementation spec, section 6)
# --------------------------------------------------------------------------

class MockServerError(Exception):
    """The mock server did not start, or its control API refused a call."""


_LISTENING_LINE = re.compile(r"LISTENING (http://127\.0\.0\.1:(\d+))/?")
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _parse_listening_line(line):
    """`LISTENING http://127.0.0.1:<port>` -> (url, port); anything else raises `MockServerError`."""
    match = _LISTENING_LINE.fullmatch(line.strip())
    if match is None:
        raise MockServerError(f"expected 'LISTENING http://127.0.0.1:<port>' as the first stdout line, got {line!r}")
    return match.group(1), int(match.group(2))


class MockServer:
    """Run `mock_server.py --port 0 --scenario <name>` as a child process.

        with MockServer("normal") as mock:
            page.goto(mock.url + "/")
            mock.fault("http_502")
            mock.scenario("detour")       # restarts the scenario from frame 0
            commands = mock.log()

    `url` has no trailing slash. The process is terminated on exit, and on
    Windows it also dies if the test runner is killed. Outside a with-block:
    `mock = MockServer("normal").start()` and `mock.stop()`.
    """

    def __init__(self, scenario="normal", script=None, startup_timeout=15.0, grace=3.0, extra_args=()):
        self.initial_scenario = scenario
        self.script = os.fspath(script) if script is not None else MOCK_SERVER_SCRIPT
        self.startup_timeout = startup_timeout
        self.grace = grace
        self.extra_args = tuple(extra_args)
        self.url = None
        self.port = None
        self.process = None
        self.pid = None  # kept after stop(), so a test can check that the process is gone
        self._guard = None
        self._threads = []
        self._stdout_lines = queue.Queue()
        self._stdout_tail = collections.deque(maxlen=200)
        self._stderr_tail = collections.deque(maxlen=200)

    # ---- lifecycle -------------------------------------------------------

    def start(self):
        if self.process is not None:
            return self
        if not os.path.isfile(self.script):
            raise MockServerError(f"mock server script not found: {self.script}")
        environment = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        options = {} if os.name == "nt" else {"start_new_session": True}
        self.process = subprocess.Popen(
            [sys.executable, "-u", self.script, "--port", "0", "--scenario", self.initial_scenario, *self.extra_args],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=repo_path(), env=environment, **options)
        self.pid = self.process.pid
        self._guard = cdp.kill_on_exit(self.process)
        # Both pipes are drained for the whole life of the process: a server
        # that logs every request would otherwise block on a full pipe.
        self._drain(self.process.stdout, self._stdout_tail, self._stdout_lines)
        self._drain(self.process.stderr, self._stderr_tail, None)
        try:
            self.url, self.port = _parse_listening_line(self._first_line())
        except BaseException:
            self.stop()
            raise
        return self

    def _drain(self, pipe, tail, lines):
        def pump():
            for raw in pipe:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                tail.append(line)
                if lines is not None:
                    lines.put(line)
            if lines is not None:
                lines.put(None)

        thread = threading.Thread(target=pump, name="mock-server-pipe", daemon=True)
        thread.start()
        self._threads.append(thread)

    def _first_line(self):
        try:
            line = self._stdout_lines.get(timeout=self.startup_timeout)
        except queue.Empty:
            raise MockServerError(
                f"mock server printed nothing within {self.startup_timeout:g} s. {self._diagnostics()}") from None
        if line is None:
            try:
                code = self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                code = None
            time.sleep(0.1)  # let the stderr reader catch up with the dead process
            raise MockServerError(f"mock server exited with code {code} before listening. {self._diagnostics()}")
        return line

    def _diagnostics(self):
        stderr = "\n".join(self._stderr_tail)
        return f"stderr:\n{stderr}" if stderr else "stderr is empty."

    def output(self):
        """Recent stdout and stderr lines of the server, for failure messages."""
        return {"stdout": list(self._stdout_tail), "stderr": list(self._stderr_tail)}

    def stop(self):
        """Terminate the process; kill it if it is still alive after the grace period. Safe to call twice."""
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=self.grace)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10.0)
        if self._guard is not None:
            self._guard.terminate()
            self._guard = None
        for thread in self._threads:
            thread.join(timeout=2.0)
        self._threads.clear()
        for pipe in (process.stdout, process.stderr):
            pipe.close()
        self.process = None

    close = stop

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc_info):
        self.stop()

    # ---- control API -----------------------------------------------------

    def request(self, method, path, body=None, timeout=5.0):
        """Call the server and return the parsed JSON body (None when the body is empty)."""
        if self.url is None:
            raise MockServerError("mock server is not running")
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        request = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        try:
            with _NO_PROXY_OPENER.open(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:500]
            raise MockServerError(f"{method} {path} answered HTTP {error.code}: {detail}") from None
        except (urllib.error.URLError, OSError) as error:
            raise MockServerError(f"{method} {path} failed: {error}. {self._diagnostics()}") from None
        text = raw.decode("utf-8", "replace")
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except ValueError:
            raise MockServerError(f"{method} {path} answered with a body that is not JSON: {text[:200]!r}") from None

    def scenario(self, name):
        """Switch the scenario; it restarts from frame 0."""
        return self.request("POST", "/__mock__/scenario", {"name": name})

    def fault(self, mode):
        """Set the fault of the /ditto/ paths: "none", "http_502", "http_503", "hang" or "drop"."""
        return self.request("POST", "/__mock__/fault", {"mode": mode})

    def log(self):
        """Every request and received command the server has recorded."""
        return self.request("GET", "/__mock__/log")

    def state(self):
        return self.request("GET", "/__mock__/state")

    def scenarios(self):
        return self.request("GET", "/__mock__/scenarios")


# --------------------------------------------------------------------------
# Test case with a browser
# --------------------------------------------------------------------------

def failure_artifact_path(test_id, extension=".png"):
    """Where the evidence of a failed test is saved: test-output/failures/<test id><extension>."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", test_id)
    return os.path.join(OUTPUT_DIR, "failures", safe + extension)


class BrowserTestCase(unittest.TestCase):
    """One headless Chrome per test class, a fresh page (`self.page`) per test.

    * Without Chrome the whole class is skipped with `CHROME_MISSING_MESSAGE`.
    * A test fails at teardown if the page logged an uncaught exception or a
      console.error, unless the test set `self.allow_console_errors = True`.
    * When a test fails (also on that console check), a screenshot and a text
      log of the page are saved to `test-output/failures/<test id>.png` / `.txt`.

    A subclass that overrides `setUpClass` or `setUp` calls `super()` first.
    """

    viewport = (1280, 720)
    chrome_args = ()
    allow_console_errors = False
    browser = None
    page = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not chrome_available():
            raise unittest.SkipTest(CHROME_MISSING_MESSAGE)
        cls.browser = Browser(cls.viewport[0], cls.viewport[1], extra_args=cls.chrome_args)
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        super().setUp()
        self.page = self.browser.new_page()
        self.addCleanup(self._finish_page)

    def _test_failed(self):
        # unittest records a failure in the result as soon as it happens;
        # there is no public way to ask "did this test fail" during cleanup.
        result = getattr(getattr(self, "_outcome", None), "result", None)
        for bucket in ("failures", "errors"):
            for test, _ in getattr(result, bucket, ()):
                if test is self or getattr(test, "test_case", None) is self:
                    return True
        return False

    def _save_failure_evidence(self, page):
        try:
            page.screenshot(failure_artifact_path(self.id()))
            lines = ["url: " + str(page.evaluate("location.href", timeout=3.0))]
            lines += [f"console {entry['kind']}: {entry['text']} ({entry['url']}:{entry['line']})"
                      for entry in list(page.console_messages)[-50:]]
            lines += [f"error {entry['kind']}: {entry['text']} ({entry['url']}:{entry['line']})"
                      for entry in list(page.console_errors)]
            lines += [f"request {entry['method']} {entry['url']} -> "
                      f"{entry['error'] if entry['failed'] else entry['status']}"
                      for entry in list(page.requests)[-80:]]
            with open(failure_artifact_path(self.id(), ".txt"), "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except (CdpError, OSError) as error:
            sys.stderr.write(f"\n[browser_support] no failure evidence for {self.id()}: {error!r}\n")

    def _finish_page(self):
        page = self.page
        try:
            errors = [] if self.allow_console_errors else list(page.console_errors)
            if errors or self._test_failed():
                self._save_failure_evidence(page)
        finally:
            page.close()
        if errors:
            shown = "\n".join(f"  [{entry['kind']}] {entry['text']} ({entry['url']}:{entry['line']})"
                              for entry in errors[:10])
            self.fail(f"the page logged {len(errors)} console error(s):\n{shown}")
