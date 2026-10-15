"""Browser contract test with real model output and an explicitly fake Ditto transport."""

from datetime import datetime, timezone
from email.utils import formatdate
import functools
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
import unittest
import urllib.parse

from .server import Handler
from team.sim.model import Mine
from team.sim.twins import snapshot
from team.ui.tools.cdp import Browser, ChromeNotFound


class UIContractTests(unittest.TestCase):
    def test_model_projection_renders_without_fixture_geometry(self):
        mine = Mine()
        mine.command(dict(command_id="c-" + "f" * 32, type="condition.instability_on", target="zone-a", run=mine.run))
        lock = threading.Lock()

        class FakeTransport:
            def request(self, method, path, data=None):
                with lock:
                    twins = snapshot(mine)
                url = urllib.parse.urlsplit(path)
                if url.path == "/api/2/things":
                    ids = urllib.parse.parse_qs(url.query)["ids"][0].split(",")
                    body = [twins[i.split(":", 1)[1]] for i in ids]
                else:
                    body = twins[url.path.rsplit(":", 1)[1]]
                    body["_modified"] = datetime.now(timezone.utc).isoformat()
                    body["_revision"] = mine.publication_seq
                return 200, {"Date": formatdate(usegmt=True)}, json.dumps(body).encode()

        class TestHandler(Handler):
            ditto = FakeTransport()

            def log_message(self, *args):
                pass

        root = Path(__file__).resolve().parents[1] / "ui" / "public"
        server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(TestHandler, directory=str(root)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            try:
                browser = Browser(1280, 720)
            except ChromeNotFound:
                self.skipTest("Chrome unavailable")
            with browser:
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{server.server_port}/")
                page.wait_for("document.body.dataset.boot === 'ready' && document.body.dataset.snapshot === 'ok'", timeout=15)
                body = page.evaluate("document.body.innerText")
                self.assertIn("Участок A", body)
                self.assertFalse(list(page.console_errors), list(page.console_errors))
                state = page.evaluate("(async()=>{const {app}=await import('/js/main.js');const s=app.store.getState();return {boot:s.boot};})()")
                self.assertIsInstance(state, dict)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
