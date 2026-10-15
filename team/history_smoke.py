"""Read live scalar history and check HTTP command headers on MQTT for credential leakage."""

import csv
import io
import json
import os
from pathlib import Path
import queue
import time
import urllib.request
import uuid

import paho.mqtt.client as mqtt


def main():
    settings = dict(line.split("=", 1) for line in (Path(__file__).resolve().parents[1] /
                    "deploy/compose/.env").read_text(encoding="utf-8").splitlines()
                    if line and not line.startswith("#") and "=" in line)
    influx_url = "http://127.0.0.1:" + settings.get("INFLUXDB_PORT", "8086") + "/api/v2/query?org=opentwins"
    flux = 'from(bucket:"default") |> range(start:-2m) |> filter(fn:(r) => r.thingId == "team040.mine:shift" or r.thingId == "team040.mine:sens-ext-a") |> last()'
    deadline = time.monotonic() + 35
    fields = set()
    while time.monotonic() < deadline:
        request = urllib.request.Request(influx_url, data=json.dumps(dict(query=flux,
            dialect=dict(annotations=[]))).encode(), headers={"Authorization": "Token " + settings["INFLUXDB_TOKEN"],
            "Content-Type": "application/json", "Accept": "application/csv"})
        with urllib.request.urlopen(request, timeout=10) as response:
            text = response.read().decode()
        rows = list(csv.DictReader(io.StringIO(text)))
        fields = {r.get("_field") for r in rows}
        if {"value_publication_seq_properties_value", "value_rate_properties_value"} <= fields:
            break
        time.sleep(2)
    assert "value_publication_seq_properties_value" in fields, "shift history missing"
    assert "value_rate_properties_value" in fields, "sensor history missing"
    assert not any(str(f).startswith(("value_scene_", "value_route_", "value_commands_")) for f in fields)

    received = queue.Queue()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="team040-leak-check-" + uuid.uuid4().hex)
    client.on_connect = lambda c, u, f, r, p: c.subscribe("opentwins/live/messages/team040.mine/shift", qos=1)
    ready = queue.Queue()
    client.on_subscribe = lambda *args: ready.put(True)
    client.on_message = lambda c, u, m: received.put(m.payload)
    client.connect("127.0.0.1", int(settings.get("MQTT_PORT", "1883")))
    client.loop_start()
    try:
        ready.get(timeout=10)
        base = os.environ.get("TEAM_UI_URL", "http://127.0.0.1:" + settings.get("TEAM_UI_PORT", "8088"))
        url = base + "/ditto/api/2/things/team040.mine:shift"
        with urllib.request.urlopen(url, timeout=5) as response:
            shift = json.load(response)
        body = dict(command_id="c-" + uuid.uuid4().hex, type="test.unsupported", target="shift",
                    run=shift["features"]["idSimulationRun"]["properties"]["value"])
        request = urllib.request.Request(url + "/inbox/messages/command?timeout=0", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 202
        payload = received.get(timeout=10).decode()
        assert "authorization" not in payload.lower(), "Authorization header leaked on MQTT"
        assert settings["DITTO_PASSWORD"] not in payload, "Ditto secret leaked on MQTT"
    finally:
        client.disconnect()
        client.loop_stop()
    print(json.dumps(dict(result="PASS", history_fields=len(fields), sensor_history=True,
                          structured_fields_expanded=False, live_command_credentials_leaked=False)))


if __name__ == "__main__":
    main()
