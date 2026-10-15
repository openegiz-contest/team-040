import functools
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from .server import Handler, allowed_path
from team.sim.service import COMMAND_TOPIC, decode_command


class GatewayTests(unittest.TestCase):
    def test_allowlist(self):
        self.assertEqual(allowed_path("GET", "/ditto/api/2/things/team040.mine:shift?fields=thingId,features,_modified,_revision"),
                         "/api/2/things/team040.mine:shift?fields=thingId%2Cfeatures%2C_modified%2C_revision")
        invalid = [
            ("GET", "/ditto/api/2/things/other:shift"),
            ("GET", "/ditto/api/2/things/team040.mine:shift/features"),
            ("GET", "/ditto/api/2/things?ids=team040.mine:shift,other:x"),
            ("GET", "/ditto/api/2/things?ids=team040.mine:shift&ids=team040.mine:mine"),
            ("GET", "/ditto/api/2/things?ids=" + ",".join(["team040.mine:shift"] * 21)),
            ("POST", "/ditto/api/2/things/team040.mine:shift/inbox/messages/command?timeout=5"),
            ("DELETE", "/ditto/api/2/things/team040.mine:shift"),
            ("GET", "/ditto/api/2/things/team040.mine:shift?fields=policyId"),
            ("GET", "/ditto/api/2/things/team040.mine:shift%2F..%2Fother:x"),
        ]
        for method, path in invalid:
            with self.subTest(path=path), self.assertRaises(ValueError):
                allowed_path(method, path)

    def test_native_command_envelope(self):
        body = dict(command_id="c-" + "1" * 32, type="run.reset", target="shift", run="run-0001")
        envelope = dict(topic="team040.mine/shift/things/live/messages/command",
                        path="/inbox/messages/command", value=body)
        self.assertEqual(decode_command(COMMAND_TOPIC, json.dumps(envelope).encode()), body)
        for bad in [{**envelope, "path": "/outbox/messages/command"},
                    {**envelope, "topic": "other/shift/things/live/messages/command"},
                    {**envelope, "value": "not JSON object"}]:
            with self.assertRaises(ValueError):
                decode_command(COMMAND_TOPIC, json.dumps(bad).encode())

    def test_real_http_proxy_does_not_forward_client_credentials(self):
        calls = []

        class FakeDitto:
            def request(self, method, path, data=None):
                calls.append((method, path, data))
                return 202 if method == "POST" else 200, {"Date": "Wed, 14 Oct 2026 00:00:00 GMT"}, b"{}"

        class TestHandler(Handler):
            ditto = FakeDitto()

            def log_message(self, *args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "index.html").write_text("test UI")
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(TestHandler, directory=directory))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = "http://127.0.0.1:" + str(server.server_port)
            try:
                request = urllib.request.Request(base + "/ditto/api/2/things/team040.mine:shift",
                                                 headers={"Authorization": "Bearer do-not-forward"})
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertEqual(response.headers["Date"], "Wed, 14 Oct 2026 00:00:00 GMT")
                self.assertNotIn("do-not-forward", repr(calls))
                body = json.dumps(dict(command_id="c-" + "1" * 32, type="run.reset", target="shift", run="run-0001")).encode()
                request = urllib.request.Request(base + "/ditto/api/2/things/team040.mine:shift/inbox/messages/command?timeout=0",
                    data=body, headers={"Content-Type": "application/json", "Origin": "https://unrelated.invalid"})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request)
                self.assertEqual(caught.exception.code, 400)
                self.assertEqual(len(calls), 1)
                request.remove_header("Origin")
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(response.status, 202)
                self.assertEqual(calls[-1][0], "POST")
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
