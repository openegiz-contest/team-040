"""Narrow server-side Ditto client. Credentials never enter MQTT or static files."""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Ditto:
    def __init__(self, url, password, user="ditto"):
        self.url = url.rstrip("/")
        self.auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, method, path, data=None):
        request = urllib.request.Request(self.url + path, method=method, data=data,
            headers={"Authorization": self.auth, "Content-Type": "application/json", "Accept": "application/json"})
        try:
            response = self.opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, dict(response.headers), response.read(4 * 1024 * 1024)

    def ensure(self, twin):
        path = "/api/2/things/" + urllib.parse.quote(twin["thingId"], safe=":")
        status, _, _ = self.request("GET", path + "?fields=thingId")
        if status == 404:
            # Dynamic features must arrive through MQTT, including first bootstrap.
            body = {k: twin[k] for k in ("thingId", "policyId", "attributes")}
            status, _, _ = self.request("PUT", path, json.dumps(body).encode())
        elif status == 200:
            status, _, _ = self.request("PUT", path + "/attributes", json.dumps(twin["attributes"]).encode())
        if status not in (200, 201, 204):
            raise RuntimeError(f"Ditto bootstrap HTTP {status} for {twin['thingId']}")
