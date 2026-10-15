import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import urllib.parse

from team.sim.platform import Ditto

ROOT = "/ditto/api/2/things"
THING = re.compile(r"team040\.mine:[a-z0-9_.-]+\Z")
COMMAND = ROOT + "/team040.mine:shift/inbox/messages/command"


def allowed_path(method, raw):
    if len(raw) > 8192:
        raise ValueError("URL too long")
    url = urllib.parse.urlsplit(raw)
    if url.scheme or url.netloc or url.fragment:
        raise ValueError("invalid URL")
    path = urllib.parse.unquote(url.path)
    query = urllib.parse.parse_qs(url.query, keep_blank_values=True, strict_parsing=True)
    if any(len(v) != 1 for v in query.values()):
        raise ValueError("duplicate query")
    if method == "POST":
        if path != COMMAND or query != {"timeout": ["0"]}:
            raise ValueError("unsupported command URL")
    elif method == "GET":
        if set(query) - {"ids", "fields"}:
            raise ValueError("unsupported query")
        if path == ROOT:
            ids = query.get("ids", [""])[0].split(",")
            if not 1 <= len(ids) <= 20 or not all(THING.fullmatch(i) for i in ids):
                raise ValueError("invalid batch")
        elif path.startswith(ROOT + "/") and THING.fullmatch(path[len(ROOT) + 1:]):
            if "ids" in query:
                raise ValueError("ids only permitted on collection")
        else:
            raise ValueError("unsupported thing")
        if "fields" in query and (not query["fields"][0] or
                set(query["fields"][0].split(",")) - {"thingId", "attributes", "features", "_modified", "_revision"}):
            raise ValueError("unsupported fields")
    else:
        raise ValueError("unsupported method")
    return path.removeprefix("/ditto") + ("?" + urllib.parse.urlencode({k: v[0] for k, v in query.items()}) if query else "")


class Handler(SimpleHTTPRequestHandler):
    ditto = None

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        elif self.path.startswith("/ditto"):
            self.proxy("GET")
        elif any(part.startswith(".") for part in urllib.parse.unquote(self.path.split("?", 1)[0]).split("/") if part):
            self.send_error(404)
        else:
            super().do_GET()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def do_POST(self):
        self.proxy("POST")

    def do_HEAD(self):
        self.send_error(405)

    def proxy(self, method):
        try:
            path = allowed_path(method, self.path)
            body = None
            if method == "POST":
                origin = self.headers.get("Origin")
                if origin and origin != "http://" + self.headers.get("Host", ""):
                    raise ValueError("cross-origin command")
                if self.headers.get("Sec-Fetch-Site") == "cross-site":
                    raise ValueError("cross-site command")
                if self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding"):
                    raise ValueError("JSON body required")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096:
                    raise ValueError("invalid body size")
                self.connection.settimeout(3)
                body = self.rfile.read(size)
                parsed = json.loads(body)
                if not isinstance(parsed, dict) or any(not isinstance(parsed.get(k), str)
                        for k in ("command_id", "type", "target", "run")):
                    raise ValueError("invalid command")
                if not re.fullmatch(r"c-[0-9a-f]{32}", parsed["command_id"]):
                    raise ValueError("invalid command id")
        except (ValueError, TimeoutError):
            self.send_error(400, "Unsupported request")
            return
        try:
            status, headers, response = self.ditto.request(method, path, body)
        except (OSError, TimeoutError):
            self.send_error(502, "Platform unavailable; command delivery may be unknown")
            return
        self.send_response_only(status)
        self.send_header("Date", headers.get("Date", self.date_time_string()))
        self.send_header("Content-Type", headers.get("Content-Type", "application/json"))
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def main():
    Handler.ditto = Ditto(os.environ.get("DITTO_URL", "http://ditto-nginx"), os.environ["DITTO_PASSWORD"])
    root = Path(os.environ.get("UI_ROOT", "team/ui/public")).resolve()
    server = ThreadingHTTPServer((os.environ.get("UI_BIND", "127.0.0.1"), 8088),
                                functools.partial(Handler, directory=str(root)))
    server.serve_forever()


if __name__ == "__main__":
    main()
