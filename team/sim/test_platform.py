from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest

from .platform import Ditto


class PlatformClientTests(unittest.TestCase):
    def test_bootstrap_only_creates_metadata_and_refreshes_attributes(self):
        requests = []
        exists = [False]

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200 if exists[0] else 404)
                self.end_headers()

            def do_PUT(self):
                requests.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                exists[0] = True
                self.send_response(204)
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = Ditto(f"http://127.0.0.1:{server.server_port}", "test-password")
            twin = dict(thingId="team040.mine:shift", policyId="default:basic_policy",
                        attributes={"kind": "shift"}, features={"must_not_use_http": {}})
            client.ensure(twin)
            client.ensure(twin)
            self.assertEqual(requests[0][0], "/api/2/things/team040.mine:shift")
            self.assertNotIn("features", requests[0][1])
            self.assertEqual(requests[1], ("/api/2/things/team040.mine:shift/attributes", twin["attributes"]))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_redirect_is_not_followed_with_server_credentials(self):
        paths = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                paths.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/unexpected")
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = Ditto(f"http://127.0.0.1:{server.server_port}", "test-password")
            self.assertEqual(client.request("GET", "/original")[0], 302)
            self.assertEqual(paths, ["/original"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
