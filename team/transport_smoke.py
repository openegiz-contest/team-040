"""Real MQTT/service test with a FAKE HTTP Ditto bootstrap. Not an end-to-end platform test.

Uses isolated test MQTT topics and client id: no test telemetry reaches Ditto.
Requires localhost Mosquitto and paho-mqtt.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import ExitStack
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import paho.mqtt.client as mqtt



def stop_process(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        # Windows venv python may be a launcher with a child interpreter.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        process.terminate()
    process.wait(10)


def main():
    created = set()
    test_id = "team040-test-" + uuid.uuid4().hex
    command_topic = test_id + "/commands"
    telemetry_prefix = test_id + "/telemetry"

    class FakeDitto(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200 if self.path.split("?")[0] in created else 404)
            self.end_headers()

        def do_PUT(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert "features" not in body
            created.add(self.path)
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeDitto)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    received = queue.Queue()
    subscriber = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="team040-test-" + uuid.uuid4().hex)
    subscriber.on_connect = lambda c, u, f, r, p: c.subscribe(telemetry_prefix + "/team040.mine/shift", qos=1)
    subscriber.on_message = lambda c, u, m: received.put(json.loads(m.payload))
    subscriber.connect("127.0.0.1", 1883)
    subscriber.loop_start()

    def wait(predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            envelope = received.get(timeout=max(0.1, deadline - time.monotonic()))
            values = {k: v["properties"]["value"] for k, v in envelope["value"].items()}
            if predicate(values):
                return values
        raise AssertionError("MQTT state timeout")

    process = None
    try:
        with tempfile.TemporaryDirectory() as directory, ExitStack() as processes:
            environment = {**os.environ, "DITTO_URL": f"http://127.0.0.1:{server.server_port}",
                "DITTO_PASSWORD": "TEST-ONLY-NO-REAL-CREDENTIAL", "MQTT_HOST": "127.0.0.1", "MQTT_PORT": "1883",
                "MQTT_CLIENT_ID": test_id, "MQTT_COMMAND_TOPIC": command_topic, "MQTT_TELEMETRY_PREFIX": telemetry_prefix,
                "STATE_PATH": str(Path(directory) / "model.json")}
            with open(Path(directory) / "service.log", "w", encoding="utf-8") as log:
                process = subprocess.Popen([sys.executable, "-m", "team.sim.service"], env=environment,
                    stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                processes.callback(stop_process, process)
                state = wait(lambda s: bool(s["scene"]))
                command_id = "c-" + uuid.uuid4().hex
                body = dict(command_id=command_id, type="condition.close_working", target="w-07", run=state["idSimulationRun"])
                envelope = dict(topic="team040.mine/shift/things/live/messages/command", path="/inbox/messages/command", value=body)
                started = time.monotonic()
                subscriber.publish(command_topic, json.dumps(envelope), qos=1).wait_for_publish(5)
                state = wait(lambda s: any(c["id"] == command_id for c in s["commands"]))
                assert state["workers_no_route"] == 3
                assert state["run_state"] == "paused"
                ack = next(c for c in state["commands"] if c["id"] == command_id)
                assert ack["status"] == "applied"
                elapsed = time.monotonic() - started
                tick, seq = state["tick"], state["publication_seq"]
                state = wait(lambda s: s["publication_seq"] >= seq + 2)
                assert state["tick"] == tick
                assert "TEST-ONLY-NO-REAL-CREDENTIAL" not in json.dumps(state)
                # Kill the process without a graceful save and verify the durable ledger.
                stop_process(process)
                process = subprocess.Popen([sys.executable, "-m", "team.sim.service"], env=environment,
                    stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                processes.callback(stop_process, process)
                restored = wait(lambda s: s["publication_seq"] > state["publication_seq"])
                assert restored["tick"] == tick
                subscriber.publish(command_topic, json.dumps(envelope), qos=1).wait_for_publish(5)
                repeated = wait(lambda s: s["publication_seq"] > restored["publication_seq"])
                assert next(c for c in repeated["commands"] if c["id"] == command_id) == ack
                stop_process(process)
                process = None
                print(json.dumps(dict(result="PASS", real_mqtt=True, real_ditto=False,
                    command_to_state_s=round(elapsed, 3), durable_restart=True, paused_heartbeat=True,
                    bootstrap_objects=len([p for p in created if not p.endswith("/attributes")]))), flush=True)
    finally:
        if process:
            stop_process(process)
        subscriber.disconnect()
        subscriber.loop_stop()
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
