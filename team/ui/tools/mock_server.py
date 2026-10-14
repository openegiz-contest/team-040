#!/usr/bin/env python3
"""Test HTTP server for the dispatcher UI: replays contract fixtures.

THIS IS A TEST TOOL, NOT A SIMULATOR. It contains no mine logic: positions,
routes, states and numbers come only from the frames in team/ui/fixtures/, and
those numbers are invented for tests (see fixtures/README.md). The server only

  * serves team/ui/public/ at "/";
  * answers the Ditto reads and the one command POST of team/CONTRACT.md under
    "/ditto/", refusing and logging everything else;
  * counts publications by wall time (one per second), stamps publication_seq,
    _modified, _revision and model time on the current frame, and appends the
    acknowledgement records of received commands;
  * follows the command rules written in the fixture;
  * offers a control API under "/__mock__/" that production code never calls.

Usage:
    python team/ui/tools/mock_server.py --port 8088 --scenario normal
    python team/ui/tools/mock_server.py --port 0        # free port, printed on the first line

Standard library only. Binds 127.0.0.1 only.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
import re
import select
import signal
import socket
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

UI_DIR = Path(__file__).resolve().parent.parent
THINGS_PATH = "/ditto/api/2/things"
COMMAND_SUFFIX = "/inbox/messages/command"
COMMAND_ID = re.compile(r"^c-[0-9a-f]{32}$")
MAX_BODY = 4096
MAX_IDS = 20
ACK_WINDOW = 32
LOG_LIMIT = 5000
FAULTS = ("none", "http_502", "http_503", "hang", "drop")
FAULT_HANG_S = 30.0
FIXTURE_FORMAT = 1

# Command types of the contract and the kind of thing each one may target.
TARGET_KIND = {
    "condition.close_working": "working", "condition.open_working": "working",
    "condition.sensor_lost": "sensor", "condition.sensor_restored": "sensor",
    "condition.instability_on": "zone", "condition.instability_off": "zone",
    "action.stop_zone": "zone", "action.withdraw_zone": "zone",
    "action.resume_zone": "zone", "action.execute_option": "option",
    "run.reset": None, "run.start_preset": "preset",
}

MIME = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml", ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8", ".png": "image/png", ".ico": "image/x-icon",
}


def value_of(features: dict, name: str, default=None):
    try:
        return features[name]["properties"]["value"]
    except (KeyError, TypeError):
        return default


def is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def iso_ms(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def ditto_error(status: int, error: str, message: str, description: str) -> dict:
    return {"status": status, "error": error, "message": message, "description": description}


def not_found(thing_id: str) -> dict:
    return ditto_error(
        404, "things:thing.notfound",
        f"The Thing with ID '{thing_id}' could not be found or requester had insufficient "
        "permissions to access it.",
        "Check if the ID of your requested Thing was correct and you have sufficient permissions.")


# ---------------------------------------------------------------------------
# Fixture files
# ---------------------------------------------------------------------------

class FixtureFormatError(ValueError):
    """The fixture file is not in a format this server knows."""


def check_format(fx: dict) -> dict:
    """Refuses a fixture whose "format" is not the one this server reads."""
    if fx.get("format") != FIXTURE_FORMAT:
        raise FixtureFormatError(
            f"unsupported fixture format {fx.get('format')!r}; this server reads format "
            f"{FIXTURE_FORMAT} (run team/ui/tools/build_fixtures.py)")
    return fx


# ---------------------------------------------------------------------------
# Replay of one fixture
# ---------------------------------------------------------------------------

class Timeline:
    """State of one scenario session. All methods are called under App.lock."""

    def __init__(self, fx: dict, interval_ms: int):
        self.fx = fx
        self.interval_ms = interval_ms
        self.states: dict = fx.get("states", {})
        self.publication: dict = fx.get("publication", {})
        clock = fx.get("clock", {})
        self.step = clock.get("tick_step", 10)
        self.follow = set(clock.get("follow_fields", []))
        self.event = set(clock.get("event_fields", []))
        self.records: dict = clock.get("record_lists", {})
        self.ns = fx.get("namespace", "team040.mine")
        self.attribute_sets = {name: {t["thingId"]: t["attributes"] for t in things}
                               for name, things in fx.get("attribute_sets", {}).items()}
        self.archive = {t["thingId"]: t for t in fx.get("archive", [])}

        self.t0 = time.monotonic()
        self.wall0 = datetime.now(timezone.utc)
        self.n = 0                    # publications so far
        self.state = ""
        self.pubs_in_state = 0
        self.frame_index = 0
        self.clock = 0                # model tick of the current publication
        self.warps: dict[str, list] = {}   # run -> [(nominal tick boundary, delta)]
        self.pending_goto: str | None = None
        self.acks: list[dict] = []    # {"visible_from": publication, "record": {...}}
        self.unstamped: list[dict] = []
        self.seen: dict[str, dict] = {}
        self.bindings: dict[str, str] = {}
        self.attempts: dict[str, int] = {}
        self._rendered: dict | None = None
        if self.states:
            self._enter(fx["start"], None)
            self.n = 1

    # --- publications -------------------------------------------------------------

    def advance(self):
        """Catch up with wall time: one publication per interval, no drift."""
        if not self.states:
            return
        target = 1 + int((time.monotonic() - self.t0) * 1000 / self.interval_ms)
        freeze_at = self.publication.get("freeze_at")
        if freeze_at:
            target = min(target, freeze_at)
        while self.n < target:
            self._step()

    def frame(self) -> dict:
        return self.states[self.state]["frames"][self.frame_index]

    def _enter(self, name: str, prev: tuple | None):
        st = self.states[name]
        first = st["frames"][0]
        t0, run = value_of(first, "tick", 0), value_of(first, "idSimulationRun", "")
        if prev is None or st.get("new_run"):
            self.clock = t0
            self.warps[run] = [(-math.inf, 0)]
        else:
            prev_clock, prev_nominal, prev_run = prev
            if prev_clock == "run":
                self.clock += self.step
            boundary = prev_nominal + 1 if prev_run == run else -math.inf
            pivots = [p for p in self.warps.get(run, [(-math.inf, 0)]) if p[0] < boundary]
            self.warps[run] = pivots + [(boundary, self.clock - t0)]
        self.state, self.pubs_in_state, self.frame_index = name, 0, 0

    def _step(self):
        self.n += 1
        st = self.states[self.state]
        frame = self.frame()
        prev = (st["clock"], value_of(frame, "tick", 0), value_of(frame, "idSimulationRun", ""))
        if self.pending_goto is not None:
            target, self.pending_goto = self.pending_goto, None
            self._enter(target, prev)
        else:
            self.pubs_in_state += 1
            limit = st.get("publications", len(st["frames"]))
            if "next" in st and self.pubs_in_state >= limit:
                self._enter(st["next"], prev)
            else:
                self.frame_index = min(self.pubs_in_state, len(st["frames"]) - 1)
                if st["clock"] == "run":
                    self.clock += self.step
        for record in self.unstamped:
            record["tick"] = record["sim_time_s"] = self.clock
        self.unstamped.clear()
        self._rendered = None

    # --- re-timing a frame ----------------------------------------------------------

    def _warp(self, run: str, nominal):
        delta = 0
        for boundary, d in self.warps.get(run, ()):
            if boundary <= nominal:
                delta = d
        return nominal + delta

    def _retime(self, features: dict, run: str, surplus: int):
        own_nominal = value_of(features, "tick")
        own_actual = self._warp(run, own_nominal) + surplus if is_number(own_nominal) else None
        for name, feature in features.items():
            props = feature.get("properties") if isinstance(feature, dict) else None
            if not isinstance(props, dict) or "value" not in props:
                continue
            v = props["value"]
            if name in ("tick", "sim_time_s"):
                if is_number(v):
                    props["value"] = self._warp(run, v) + surplus
            elif name in self.follow:
                if is_number(v):
                    props["value"] = own_actual if v == own_nominal else self._warp(run, v)
            elif name in self.event:
                if is_number(v):
                    props["value"] = self._warp(run, v)
            elif name in self.records and isinstance(v, list):
                for record in v:
                    if not isinstance(record, dict):
                        continue
                    record_run = record.get("run", run)
                    for field in self.records[name]:
                        if is_number(record.get(field)):
                            record[field] = self._warp(record_run, record[field])
                    for key in list(record):
                        text = record[key]
                        if isinstance(text, str) and text.startswith("@"):
                            if text[1:] in self.bindings:
                                record[key] = self.bindings[text[1:]]
                            else:
                                del record[key]

    def shift_features(self) -> dict:
        if self._rendered is None:
            features = copy.deepcopy(self.frame())
            run = value_of(features, "idSimulationRun", "")
            nominal = value_of(features, "tick", 0)
            surplus = self.clock - self._warp(run, nominal)
            scene = value_of(features, "scene", [])
            self._retime(features, run, surplus)
            for element in scene:
                self._retime(element.get("features", {}), run, surplus)
            features["publication_seq"] = {"properties": {
                "value": self.publication.get("first_seq", 1) + self.n - 1}}
            authored = value_of(features, "commands", [])
            visible = [a["record"] for a in self.acks if a["visible_from"] <= self.n]
            features["commands"] = {"properties": {"value": (authored + visible)[-ACK_WINDOW:]}}
            self._rendered = features
        return self._rendered

    # --- things ---------------------------------------------------------------------

    def attribute_set_name(self) -> str:
        return self.states[self.state].get("attributes") or next(iter(self.attribute_sets), "")

    def modified(self, dynamic: bool) -> str:
        age = self.publication.get("modified_age_s", 0)
        elapsed = (self.n - 1) * self.interval_ms / 1000 if dynamic else 0
        return iso_ms(self.wall0 + timedelta(seconds=elapsed - age))

    def thing(self, thing_id: str) -> dict | None:
        if not self.states:
            return None
        attributes = self.attribute_sets.get(self.attribute_set_name(), {}).get(thing_id)
        shift = self.shift_features()
        if attributes is None:
            archived = self.archive.get(thing_id)
            local = thing_id.split(":", 1)[-1]
            if archived is None or local not in value_of(shift, "runs", []):
                return None
            thing = copy.deepcopy(archived)
            thing.update(policyId="default:basic_policy", _revision=2,
                         _modified=self.modified(False))
            return thing
        thing = {"thingId": thing_id, "policyId": "default:basic_policy",
                 "attributes": attributes}
        dynamic = True
        if thing_id == f"{self.ns}:shift":
            thing["features"] = shift
            if self.states[self.state].get("metadata", True) is False:
                return thing
        else:
            mirror = next((e for e in value_of(shift, "scene", [])
                           if e.get("thingId") == thing_id), None)
            dynamic = mirror is not None
            if dynamic:
                thing["features"] = mirror["features"]
        thing["_revision"] = (self.publication.get("first_revision", 1) + self.n - 1
                              if dynamic else 1)
        thing["_modified"] = self.modified(dynamic)
        return thing

    # --- commands -------------------------------------------------------------------

    def _logical(self) -> tuple[str, dict]:
        """The state a new command meets: the one the next publication will show."""
        if self.pending_goto is not None:
            return self.pending_goto, self.states[self.pending_goto]["frames"][0]
        return self.state, self.frame()

    def find_rule(self, body: dict) -> dict | None:
        name, _ = self._logical()
        for rule in self.states[name].get("rules", []):
            if all(body.get(k) == v for k, v in rule["when"].items()):
                return rule
        return None

    def transport(self, rule: dict | None) -> dict:
        """How this POST attempt is delivered; attempts are counted per rule key."""
        script = (rule or {}).get("transport")
        if not script:
            return {"status": 202, "delivered": True}
        key = rule.get("key") or json.dumps(rule["when"], sort_keys=True)
        attempt = self.attempts.get(key, 0)
        self.attempts[key] = attempt + 1
        if attempt < len(script):
            return {"status": 202, "delivered": True, **script[attempt]}
        return {"status": 202, "delivered": True}

    def _valid_target(self, ctype: str, target: str) -> bool:
        kind = TARGET_KIND[ctype]
        if kind is None:
            return True
        name, _ = self._logical()
        set_name = self.states[name].get("attributes") or next(iter(self.attribute_sets), "")
        things = self.attribute_sets.get(set_name, {})
        if kind == "preset":
            presets = things.get(f"{self.ns}:mine", {}).get("presets", [])
            return any(p.get("id") == target for p in presets)
        return things.get(f"{self.ns}:{target}", {}).get("kind") == kind

    def submit(self, body: dict, rule: dict | None) -> dict:
        """Applies a delivered command once. Returns what happened, for the log."""
        command_id = body["command_id"]
        canon = json.dumps(body, sort_keys=True, ensure_ascii=False)
        result = {"duplicate": False, "conflict": False, "effect_applied": False}
        known = self.seen.get(command_id)
        if known is not None:
            if known["body"] == canon:
                result.update(duplicate=True, ack=known["ack"])
                return result
            result["conflict"] = True
            result["ack"] = self._ack(body, "rejected", "command_id_conflict")
            return result
        entry = self.seen[command_id] = {"body": canon, "ack": None}
        ctype = body["type"]
        _, frame = self._logical()
        if ctype not in TARGET_KIND:
            ack = self._ack(body, "rejected", "unknown_type")
        elif not self._valid_target(ctype, body["target"]):
            ack = self._ack(body, "rejected", "unknown_target")
        elif ctype == "action.execute_option" and not isinstance(body.get("decision_id"), str):
            ack = self._ack(body, "rejected", "malformed")
        elif body["run"] != value_of(frame, "idSimulationRun"):
            ack = self._ack(body, "rejected", "invalid_run")
        elif rule is None:
            # no rule for this command in the current state of the scenario:
            # a limitation of the fixture, deliberately not a contract reason code
            ack = self._ack(body, "rejected", "not_scripted")
        else:
            result["rule"] = rule.get("key") or rule["when"]
            if "bind" in rule:
                self.bindings[rule["bind"]] = command_id
            if "goto" in rule:
                self.pending_goto = rule["goto"]
                result["effect_applied"] = True
                result["goto"] = rule["goto"]
            if rule.get("no_ack"):
                ack = None
            else:
                spec = rule["ack"]
                ack = self._ack(body, spec["status"], spec.get("reason", "none"),
                                spec.get("new_run"), rule.get("ack_delay", 0))
        entry["ack"] = result["ack"] = ack
        return result

    def _ack(self, body, status, reason, new_run=None, delay=0) -> dict:
        record = {"id": body["command_id"], "type": body["type"], "target": body["target"],
                  "run": body["run"], "status": status, "tick": self.clock,
                  "sim_time_s": self.clock, "reason": reason}
        if new_run:
            record["new_run"] = new_run
        self.unstamped.append(record)   # tick is set when the next publication is made
        self.acks.append({"visible_from": self.n + 1 + delay, "record": record})
        return record

    def summary(self) -> dict:
        if not self.states:
            return {"state": None, "publication": 0}
        st = self.states[self.state]
        shift = self.shift_features()
        freeze_at = self.publication.get("freeze_at")
        return {
            "state": self.state, "frame_index": self.frame_index,
            "frames_in_state": len(st["frames"]), "publications_in_state": self.pubs_in_state,
            "clock": st["clock"], "publication": self.n,
            "publication_seq": value_of(shift, "publication_seq"),
            "tick": value_of(shift, "tick"), "run": value_of(shift, "idSimulationRun"),
            "run_state": value_of(shift, "run_state"),
            "attribute_set": self.attribute_set_name(),
            "frozen": bool(freeze_at and self.n >= freeze_at),
            "pending_goto": self.pending_goto, "bindings": dict(self.bindings),
            "acknowledgements": [dict(a["record"], visible=a["visible_from"] <= self.n)
                                 for a in self.acks],
        }


class App:
    def __init__(self, fixtures_dir: Path, public_dir: Path, interval_ms: int):
        self.fixtures_dir = fixtures_dir
        self.public_dir = public_dir.resolve()
        self.interval_ms = interval_ms
        self.lock = threading.RLock()
        self.fault = "none"
        self.log: list[dict] = []
        self.log_n = 0
        self.batches = 0
        self.scenario = ""
        self.description = ""
        self.timeline: Timeline | None = None

    def scenarios(self) -> list[dict]:
        out = []
        decoder = json.JSONDecoder()
        for path in sorted(self.fixtures_dir.glob("*.json")):
            description = ""
            try:
                head = path.read_bytes()[:4096].decode("utf-8", "ignore")
                start = head.index('"_fixture":') + len('"_fixture":')
                description = decoder.raw_decode(head[start:].lstrip())[0].get("description", "")
            except (ValueError, OSError):
                pass
            out.append({"name": path.stem, "description": description})
        return out

    def load(self, name: str):
        if not re.fullmatch(r"[a-z0-9_]+", name or ""):
            raise KeyError(name)
        path = self.fixtures_dir / f"{name}.json"
        if not path.is_file():
            raise KeyError(name)
        fx = check_format(json.loads(path.read_text(encoding="utf-8")))
        with self.lock:
            self.scenario = name
            self.description = fx.get("_fixture", {}).get("description", "")
            self.timeline = Timeline(fx, self.interval_ms)
            self.fault = "none"
            self.log = []

    def record(self, entry: dict) -> dict:
        with self.lock:
            self.log_n += 1
            entry["n"] = self.log_n
            entry["t_ms"] = int((time.monotonic() - self.timeline.t0) * 1000)
            self.log.append(entry)
            del self.log[:-LOG_LIMIT]
        return entry


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def select_fields(thing: dict, fields: str | None) -> dict:
    """The subset of Ditto's ?fields= that the contract uses, plus simple a/b pointers."""
    if fields is None:
        return {k: v for k, v in thing.items() if not k.startswith("_")}
    if "(" in fields or ")" in fields:
        raise ValueError("fields with parentheses are not supported by the mock server")
    out: dict = {}
    for token in (t.strip() for t in fields.split(",")):
        if not token:
            continue
        parts = [p for p in token.split("/") if p]
        source, target = thing, out
        for i, part in enumerate(parts):
            if not isinstance(source, dict) or part not in source:
                break
            if i == len(parts) - 1:
                target[part] = source[part]
            else:
                source = source[part]
                target = target.setdefault(part, {})
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "mine-ui-mock/1"
    app: App

    def log_message(self, *args):   # the request log lives in /__mock__/log
        pass

    # --- plumbing ---------------------------------------------------------------------

    def _send(self, status: int, body=None, content_type="application/json"):
        if isinstance(body, (dict, list)):
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        else:
            data = body or b""
        try:
            self.send_response(status)
            if data:
                self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
        except OSError:
            self.close_connection = True

    def _client_gone(self) -> bool:
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
        except OSError:
            return True

    def _wait(self, seconds: float) -> bool:
        """Sleeps; returns False as soon as the client has disconnected."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._client_gone():
                return False
            time.sleep(0.05)
        return True

    def _drop(self):
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def _json_body(self):
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.close_connection = True
            return None
        if length < 0 or length > 1 << 20:
            self.close_connection = True
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def _entry(self, kind: str, **extra) -> dict:
        return self.app.record({"method": self.command, "path": self.path, "kind": kind,
                                "status": None, **extra})

    def _fault(self, entry: dict) -> bool:
        """Applies the active fault to a /ditto/ request. True if the request is finished."""
        mode = self.app.fault
        if mode == "none":
            return False
        entry["fault"] = mode
        if mode in ("http_502", "http_503"):
            status = int(mode[-3:])
            entry["status"] = status
            self.close_connection = True
            self._send(status, ditto_error(status, "gateway:mock.fault",
                                           f"Mock fault {mode}.", "Set by /__mock__/fault."))
        elif mode == "hang":
            self._wait(FAULT_HANG_S)
            self._drop()
        else:
            self._drop()
        return True

    # --- dispatch ---------------------------------------------------------------------

    def do_GET(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_PUT(self):
        self._dispatch()

    def do_PATCH(self):
        self._dispatch()

    def do_DELETE(self):
        self._dispatch()

    def do_OPTIONS(self):
        self._dispatch()

    def _dispatch(self):
        url = urlsplit(self.path)
        path = unquote(url.path)
        if path == "/ditto" or path.startswith("/ditto/"):
            self._ditto(path, url.query)
        elif path == "/__mock__" or path.startswith("/__mock__/"):
            self._mock(path, url.query)
        elif self.command in ("GET", "HEAD"):
            self._static(path)
        else:
            self.close_connection = True
            entry = self._entry("static", allowed=False)
            entry["status"] = 405
            self._send(405, b"method not allowed\n", "text/plain; charset=utf-8")

    # --- /ditto/ ------------------------------------------------------------------------

    def _ditto(self, path: str, query: str):
        entry = self._entry("ditto", allowed=True)
        keep_alive = not self.close_connection
        if self.command != "GET":
            # a request body is not read on the refusal paths below
            self.close_connection = True
        if self._fault(entry):
            return
        params = parse_qs(query, keep_blank_values=True)
        tail = path[len(THINGS_PATH):] if path.startswith(THINGS_PATH) else None
        if tail == "" and self.command == "GET":
            return self._batch(entry, params)
        if tail and tail.startswith("/") and "/" not in tail[1:] and self.command == "GET":
            return self._single(entry, tail[1:], params)
        shift = f"/{self.app.timeline.ns}:shift{COMMAND_SUFFIX}"
        if tail == shift and self.command == "POST":
            return self._command(entry, params, keep_alive)
        # everything else is outside what the future proxy allows
        known = tail == "" or tail == shift or (
            tail is not None and tail.startswith("/") and "/" not in tail[1:])
        status = 405 if known else 404
        entry.update(allowed=False, status=status)
        self._send(status, ditto_error(
            status, "mock:not.allowed",
            f"{self.command} {path} is not one of the calls of the contract.",
            "Allowed: GET /ditto/api/2/things/<id>, GET /ditto/api/2/things?ids=..., "
            "POST /ditto/api/2/things/<ns>:shift/inbox/messages/command?timeout=0."))

    def _bad(self, entry: dict, status: int, message: str):
        entry["status"] = status
        self._send(status, ditto_error(status, "mock:request.invalid", message,
                                       "See team/CONTRACT.md, sections 2 and 3."))

    def _fields(self, params: dict):
        return params["fields"][0] if "fields" in params else None

    def _single(self, entry: dict, thing_id: str, params: dict):
        with self.app.lock:
            self.app.timeline.advance()
            thing = self.app.timeline.thing(thing_id)
            try:
                body = None if thing is None else json.dumps(
                    select_fields(thing, self._fields(params)), ensure_ascii=False,
                    separators=(",", ":")).encode("utf-8")
            except ValueError as error:
                return self._bad(entry, 400, str(error))
        if body is None:
            entry["status"] = 404
            return self._send(404, not_found(thing_id))
        entry["status"] = 200
        self._send(200, body)

    def _batch(self, entry: dict, params: dict):
        ids = [i for i in ",".join(params.get("ids", [])).split(",") if i]
        ns = self.app.timeline.ns
        if not ids:
            return self._bad(entry, 400, "The query parameter 'ids' is required.")
        if len(ids) > MAX_IDS:
            return self._bad(entry, 400, f"At most {MAX_IDS} ids per request, got {len(ids)}.")
        if any(not i.startswith(ns + ":") for i in ids):
            return self._bad(entry, 400, f"Only ids of the namespace {ns} are allowed.")
        with self.app.lock:
            self.app.timeline.advance()
            self.app.batches += 1
            unique = list(dict.fromkeys(ids))
            found = [t for t in (self.app.timeline.thing(i) for i in unique) if t is not None]
            # Ditto does not keep the request order; make that visible on every call
            asked = [t["thingId"] for t in found]
            random.Random(self.app.batches).shuffle(found)
            if len(found) > 1 and [t["thingId"] for t in found] == asked:
                found.append(found.pop(0))
            try:
                fields = self._fields(params)
                body = json.dumps([select_fields(t, fields) for t in found], ensure_ascii=False,
                                  separators=(",", ":")).encode("utf-8")
            except ValueError as error:
                return self._bad(entry, 400, str(error))
        entry["status"] = 200
        self._send(200, body)

    def _command(self, entry: dict, params: dict, keep_alive: bool):
        entry["kind"] = "command"
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if params.get("timeout") != ["0"]:
            return self._bad(entry, 400, "The command must be sent with ?timeout=0.")
        if content_type != "application/json":
            return self._bad(entry, 400, "Content-Type must be application/json.")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._bad(entry, 400, "Content-Length is required.")
        if length > MAX_BODY:
            return self._bad(entry, 413, f"The command body is larger than {MAX_BODY} bytes.")
        raw = self.rfile.read(length)
        self.close_connection = not keep_alive
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._bad(entry, 400, "The command body is not valid JSON.")
        entry["body"] = body
        if not isinstance(body, dict):
            return self._bad(entry, 400, "The command body must be a JSON object.")
        for field in ("command_id", "type", "target", "run"):
            if not isinstance(body.get(field), str) or not body[field]:
                return self._bad(entry, 400, f"The field '{field}' is required (string).")
        if not COMMAND_ID.match(body["command_id"]):
            return self._bad(entry, 400, "command_id must be 'c-' and 32 lowercase hex digits.")

        with self.app.lock:
            timeline = self.app.timeline
            timeline.advance()
            if not timeline.states:
                return self._bad(entry, 404, "The shift thing does not exist in this scenario.")
            rule = timeline.find_rule(body)
            transport = timeline.transport(rule)
            entry["delivered"] = transport["delivered"]
            entry["effect_applied"] = False
            if transport["delivered"]:
                entry.update(timeline.submit(body, rule))
        hang_ms = transport.get("hang_ms")
        if hang_ms:
            entry["hang_ms"] = hang_ms * self.app.interval_ms // 1000
            if not self._wait(entry["hang_ms"] / 1000):
                entry["status"] = "client_disconnected"
                return self._drop()
        status = transport["status"]
        entry["status"] = status
        if status == 202:
            return self._send(202)
        self._send(status, ditto_error(status, "gateway:mock.scripted",
                                       "Scripted transport failure of the fixture.",
                                       "The delivery of the command is unknown to the client."))

    # --- /__mock__/ ---------------------------------------------------------------------

    def _mock(self, path: str, query: str):
        app = self.app
        route = (self.command, path.rstrip("/") or path)
        if route == ("GET", "/__mock__"):
            return self._send(200, control_page(app).encode("utf-8"), "text/html; charset=utf-8")
        if route == ("GET", "/__mock__/scenarios"):
            return self._send(200, {"scenarios": app.scenarios(), "current": app.scenario})
        if route == ("GET", "/__mock__/state"):
            with app.lock:
                app.timeline.advance()
                body = {"scenario": app.scenario, "description": app.description,
                        "fault": app.fault, "interval_ms": app.interval_ms,
                        "elapsed_ms": int((time.monotonic() - app.timeline.t0) * 1000),
                        **app.timeline.summary()}
            return self._send(200, body)
        if route == ("GET", "/__mock__/log"):
            since = parse_qs(query).get("since", ["0"])[0]
            with app.lock:
                entries = [copy.deepcopy(e) for e in app.log
                           if e["n"] > (int(since) if since.isdigit() else 0)]
            return self._send(200, {"scenario": app.scenario, "entries": entries})
        if route == ("POST", "/__mock__/scenario"):
            body = self._json_body()
            name = body.get("name") if isinstance(body, dict) else None
            try:
                app.load(name)
            except KeyError:
                return self._send(404, {"error": "unknown scenario", "name": name})
            except FixtureFormatError as error:
                return self._send(500, {"error": "unsupported fixture", "message": str(error)})
            return self._send(200, {"scenario": app.scenario, "restarted": True})
        if route == ("POST", "/__mock__/fault"):
            body = self._json_body()
            mode = body.get("mode") if isinstance(body, dict) else None
            if mode not in FAULTS:
                return self._send(400, {"error": "unknown fault mode", "modes": list(FAULTS)})
            app.fault = mode
            return self._send(200, {"fault": mode})
        if self.command != "GET":
            self.close_connection = True
        self._send(404, {"error": "unknown control call", "path": path})

    # --- static ---------------------------------------------------------------------------

    def _static(self, path: str):
        entry = self._entry("static", allowed=True)
        parts = [p for p in path.split("/") if p]
        if "\\" in path or "\x00" in path or any(p in (".", "..") for p in parts):
            entry.update(allowed=False, status=403)
            return self._send(403, b"forbidden\n", "text/plain; charset=utf-8")
        root = self.app.public_dir
        target = (root.joinpath(*parts) if parts else root / "index.html").resolve()
        if root not in target.parents or not target.is_file():
            entry["status"] = 404      # also for directories: no listing
            return self._send(404, b"not found\n", "text/plain; charset=utf-8")
        entry["status"] = 200
        mime = MIME.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, target.read_bytes(), mime)


CONTROL_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Тестовый имитатор платформы</title>
<style>
body{font:15px/1.4 system-ui,sans-serif;margin:24px;max-width:1000px}
h1{font-size:20px} button{font:inherit;margin:2px;padding:4px 10px}
button.current{font-weight:700;outline:2px solid #000}
td{padding:2px 8px;vertical-align:top} .warn{border:2px solid #000;padding:8px 12px}
</style></head><body>
<h1>Тестовый инструмент: имитатор ответов платформы</h1>
<p class="warn">Это не стенд и не симулятор. Сервер воспроизводит контрактные фикстуры;
все числа в них придуманы для тестов и не являются измерениями стенда.</p>
<p>Текущий сценарий: <b id="scenario">__SCENARIO__</b>. Сбой /ditto/: <b id="fault">__FAULT__</b>.
<a href="/">Открыть интерфейс</a></p>
<h2>Сценарии</h2><table>__SCENARIOS__</table>
<h2>Сбои /ditto/</h2><p>__FAULTS__</p>
<p><a href="/__mock__/state">state</a> · <a href="/__mock__/log">log</a> ·
<a href="/__mock__/scenarios">scenarios</a></p>
<script>
async function call(path, body) {
  await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"},
                     body: JSON.stringify(body)});
  location.reload();
}
for (const b of document.querySelectorAll("button[data-scenario]"))
  b.addEventListener("click", () => call("/__mock__/scenario", {name: b.dataset.scenario}));
for (const b of document.querySelectorAll("button[data-fault]"))
  b.addEventListener("click", () => call("/__mock__/fault", {mode: b.dataset.fault}));
</script></body></html>
"""


def control_page(app: App) -> str:
    def esc(text: str) -> str:
        return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;"))

    rows = "".join(
        '<tr><td><button data-scenario="{0}"{1}>{0}</button></td><td>{2}</td></tr>'.format(
            esc(s["name"]), ' class="current"' if s["name"] == app.scenario else "",
            esc(s["description"]))
        for s in app.scenarios())
    faults = "".join(
        '<button data-fault="{0}"{1}>{0}</button>'.format(
            f, ' class="current"' if f == app.fault else "") for f in FAULTS)
    return (CONTROL_PAGE.replace("__SCENARIO__", esc(app.scenario))
            .replace("__FAULT__", esc(app.fault))
            .replace("__SCENARIOS__", rows).replace("__FAULTS__", faults))


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = sys.platform != "win32"
    request_queue_size = 64


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Test server replaying contract fixtures. Not a simulator; invented data.")
    parser.add_argument("--port", type=int, default=8088, help="0 picks a free port")
    parser.add_argument("--scenario", default="normal")
    parser.add_argument("--publication-ms", type=int, default=1000,
                        help="wall time of one publication; lower it only to speed tests up")
    parser.add_argument("--public-dir", type=Path, default=UI_DIR / "public",
                        help="directory served at / (default: team/ui/public)")
    parser.add_argument("--fixtures-dir", type=Path, default=UI_DIR / "fixtures")
    args = parser.parse_args(argv)
    if args.publication_ms < 10:
        parser.error("--publication-ms must be at least 10")

    app = App(args.fixtures_dir, args.public_dir, args.publication_ms)
    try:
        app.load(args.scenario)
    except KeyError:
        names = ", ".join(s["name"] for s in app.scenarios()) or "none (run build_fixtures.py)"
        print(f"unknown scenario {args.scenario!r}; available: {names}", file=sys.stderr)
        return 2
    except FixtureFormatError as error:
        print(f"cannot load scenario {args.scenario!r}: {error}", file=sys.stderr)
        return 2
    Handler.app = app
    server = Server(("127.0.0.1", args.port), Handler)
    print(f"LISTENING http://127.0.0.1:{server.server_address[1]}", flush=True)
    print(f"scenario {app.scenario}; test tool with invented data, not a simulator; "
          f"control page at /__mock__/", flush=True)

    def stop(signum, frame):
        raise KeyboardInterrupt

    for name in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
