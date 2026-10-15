"""Read-only startup check of coherent live data received through the UI proxy."""

import datetime
import json
import time
import urllib.request


def values(twin):
    return {k: v["properties"]["value"] for k, v in twin["features"].items()}


def validate(shift, expected, now):
    state = values(shift)
    modified = datetime.datetime.fromisoformat(shift["_modified"].replace("Z", "+00:00")).timestamp()
    if not -5 <= now - modified <= 15:
        raise ValueError("snapshot is stale")
    if type(state["publication_seq"]) is not int or state["publication_seq"] <= 0:
        raise ValueError("missing publication sequence")
    scene = state["scene"]
    if not expected or len(scene) != len(expected) or {t["thingId"] for t in scene} != set(expected):
        raise ValueError("scene does not match manifest")
    for twin in scene:
        data = values(twin)
        if any(data[key] != state[key] for key in ("tick", "sim_time_s", "idSimulationRun")):
            raise ValueError("inconsistent scene")
    return state["idSimulationRun"], state["publication_seq"]


def main():
    base = "http://127.0.0.1:8088/ditto/api/2/things/team040.mine:"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(name):
        with opener.open(base + name + "?fields=thingId,attributes,features,_modified", timeout=5) as response:
            return json.load(response)

    deadline = time.monotonic() + 180
    previous, streak, reason = None, 0, "waiting for first snapshot"
    print("Waiting for Team 040 live data through MQTT / Ditto / UI proxy...", flush=True)
    while time.monotonic() < deadline:
        try:
            expected = get("mine")["attributes"]["dynamic_ids"]
            current = validate(get("shift"), expected, time.time())
            streak = streak + 1 if previous and current[0] == previous[0] and current[1] > previous[1] else 1
            previous = current
            if streak >= 3:
                print("Team 040 ready: complete, fresh scene and advancing publication sequence.", flush=True)
                return
            reason = "waiting for advancing publications"
        except (OSError, ValueError, KeyError, TypeError) as error:
            previous, streak = None, 0
            reason = type(error).__name__
        time.sleep(2)
    raise SystemExit("Team 040 not ready after 180 seconds (" + reason + "). Inspect make logs S=team-simulator and S=connectivity.")


if __name__ == "__main__":
    main()
