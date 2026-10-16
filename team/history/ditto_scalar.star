# One event -> at most one metric. Structured features never expand into rows.
load("json.star", "json")

INTEGER_FIELDS = ["tick", "publication_seq", "measured_at_tick", "index_at_tick",
                  "last_known_hazard_tick", "contract_version", "seed", "workers_total",
                  "workers_count", "workers_out", "workers_in_danger", "workers_no_route",
                  "workers_unknown", "last_seq", "opened_at_tick", "forecast_tick",
                  "machines_total", "machines_working", "machines_in_danger", "machines_stuck",
                  "machines_unknown", "loads_dumped", "conflicts"]

def scalar(value):
    return type(value) in ["int", "float", "bool", "string"]

def convert(name, value):
    # Explicit stable numeric types: counters are integers, physical values and
    # durations floats. A sensor value 0 must not conflict with later 0.01.
    if type(value) in ["int", "float"]:
        return int(value) if name in INTEGER_FIELDS else float(value)
    return value

def apply(metric):
    event = json.decode(metric.fields.get("value", "{}"))
    extra = event.get("extra", {})
    thing = extra.get("thingId")
    if not thing:
        return None
    metric.fields.clear()
    metric.tags["thingId"] = thing
    parent = extra.get("attributes", {}).get("_parents")
    if type(parent) == "string":
        metric.tags["parent"] = parent
    run = extra.get("features", {}).get("idSimulationRun", {}).get("properties", {}).get("value")
    if type(run) == "string":
        metric.tags["idSimulationRun"] = run
    path = event.get("path", "")
    value = event.get("value")
    if path == "/" and type(value) == "dict":
        value = value.get("features", {})
        path = "/features"
    if path == "/features" and type(value) == "dict":
        for name, feature in value.items():
            if type(feature) != "dict":
                continue
            field = feature.get("properties", {}).get("value")
            if scalar(field) and name != "idSimulationRun":
                metric.fields["value_" + name + "_properties_value"] = convert(name, field)
    elif path.startswith("/features/") and scalar(value):
        parts = path.split("/")
        if len(parts) == 5 and parts[3] == "properties" and parts[4] == "value":
            metric.fields["value_" + parts[2] + "_properties_value"] = convert(parts[2], value)
    return metric if len(metric.fields.keys()) else None
