"""Durable single-writer simulator: HTTP bootstrap, MQTT commands and telemetry."""

import json
import logging
import os
from pathlib import Path
import queue
import signal
import threading
import time

from .platform import Ditto
from .storage import Store
from .topology import NAMESPACE
from .twins import mqtt_messages, snapshot

COMMAND_TOPIC = f"opentwins/live/messages/{NAMESPACE}/shift"


def decode_command(topic, payload, expected_topic=COMMAND_TOPIC):
    if topic != expected_topic or len(payload) > 16384:
        raise ValueError("unexpected command topic or size")
    envelope = json.loads(payload)
    if not isinstance(envelope, dict) or envelope.get("topic") != f"{NAMESPACE}/shift/things/live/messages/command":
        raise ValueError("unexpected Ditto message topic")
    if envelope.get("path") != "/inbox/messages/command" or not isinstance(envelope.get("value"), dict):
        raise ValueError("unexpected Ditto message path or body")
    return envelope["value"]


def main():
    import paho.mqtt.client as mqtt

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = Store(os.environ.get("STATE_PATH", "/state/model.json"))
    ditto = Ditto(os.environ.get("DITTO_URL", "http://ditto-nginx"), os.environ["DITTO_PASSWORD"])
    inbox = queue.Queue(maxsize=128)
    stopping, connected = threading.Event(), threading.Event()
    command_topic = os.environ.get("MQTT_COMMAND_TOPIC", COMMAND_TOPIC)
    telemetry_prefix = os.environ.get("MQTT_TELEMETRY_PREFIX", "telemetry")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=os.environ.get("MQTT_CLIENT_ID", "team040-simulation"),
                         clean_session=False, manual_ack=True)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logging.error("MQTT connection refused")
            return
        client.subscribe(command_topic, qos=1)

    def on_subscribe(client, userdata, mid, reasons, properties):
        if any(reason.is_failure for reason in reasons):
            stopping.set()
        else:
            connected.set()

    def on_message(client, userdata, message):
        try:
            inbox.put_nowait(message)
        except queue.Full:
            logging.error("Command queue full; restarting without acknowledging pending messages")
            stopping.set()

    def on_disconnect(client, userdata, flags, reason, properties):
        connected.clear()

    client.on_connect, client.on_subscribe = on_connect, on_subscribe
    client.on_message, client.on_disconnect = on_message, on_disconnect
    client.reconnect_delay_set(1, 10)
    client.connect_async(os.environ.get("MQTT_HOST", "mosquitto"), int(os.environ.get("MQTT_PORT", "1883")))
    client.loop_start()
    signal.signal(signal.SIGTERM, lambda *args: stopping.set())
    signal.signal(signal.SIGINT, lambda *args: stopping.set())
    known = set()
    initial = True
    try:
        while not stopping.is_set():
            if not connected.wait(1):
                continue
            started = time.monotonic()
            pending = []
            for _ in range(128):
                try:
                    message = inbox.get_nowait()
                except queue.Empty:
                    break
                try:
                    body = decode_command(message.topic, message.payload, command_topic)
                    # Commit before PUBACK. Redelivery after a crash uses the ledger.
                    store.transact(lambda model: model.command(body))
                except (ValueError, TypeError, KeyError):
                    logging.warning("Ignored malformed command envelope")
                client.ack(message.mid, message.qos)
                pending.append(message.mid)

            def step(model):
                if not initial:
                    model.advance(model.parameters["speedup"])
                return snapshot(model)

            twins = store.transact(step)
            initial = False
            for key in ["mine"] + [k for k in twins if k != "mine"]:
                if key not in known:
                    ditto.ensure(twins[key])
                    known.add(key)
            message_count, batch_bytes, shift_bytes = 0, 0, 0
            for topic, payload in mqtt_messages(twins):
                topic = telemetry_prefix + topic.removeprefix("telemetry")
                encoded = json.dumps(payload, separators=(",", ":"))
                message_count += 1
                batch_bytes += len(encoded.encode("utf-8"))
                if topic.endswith("/shift"):
                    shift_bytes = len(encoded.encode("utf-8"))
                info = client.publish(topic, encoded, qos=1)
                info.wait_for_publish(timeout=5)
                if not info.is_published():
                    raise RuntimeError("MQTT publish was not acknowledged")
            Path(os.environ.get("STATE_PATH", "/state/model.json")).with_name("heartbeat").write_text(str(time.time()))
            if pending or store.model.publication_seq % 30 == 0:
                logging.info("Published seq=%s tick=%s run=%s state=%s commands=%s messages=%s batch_bytes=%s shift_bytes=%s loop_s=%.4f",
                             store.model.publication_seq, store.model.tick, store.model.run,
                             store.model.run_state, len(pending), message_count, batch_bytes, shift_bytes,
                             time.monotonic()-started)
            stopping.wait(max(0, 1 - (time.monotonic() - started)))
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
