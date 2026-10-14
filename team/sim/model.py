"""Deterministic one-second model shared by actual and forecast runs."""

import copy
import hashlib
import json
import re

from .routing import route
from .journal import observe
from .parameters import validate
from .topology import MODEL_VERSION, PARAMETERS, build_attributes


def fingerprint(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


class Mine:
    def __init__(self, parameters=None):
        self.parameters = copy.deepcopy(PARAMETERS)
        if parameters is not None:
            self.parameters.update(parameters)
        validate(self.parameters)
        self.publication_seq = 0
        self.run_number = 0
        self.journal_seq = 0
        self.events = []
        self.ledger = {}
        self.commands = []
        self.archive = []
        self._new_run()

    def _new_run(self, preset=None):
        self.attributes = build_attributes(self.parameters)
        self._journal_state = None
        self.run_number += 1
        self.run = f"run-{self.run_number:04d}"
        self.tick = 0
        self.run_state = "running"
        self.pause_reason = "none"
        self.seed = 40
        self.conditions = []
        self.schedule = [copy.deepcopy(preset)] if preset else []
        self.scenario_key = preset["id"] if preset else "manual"
        self.incident = {"state": "none"}
        self.decision_counter = 0
        self.decision_tick = None
        self.comparison_key = None
        self.comparable = False
        self.selected_option = None
        self.forecasts = {}
        self.last_out_s = None
        self.archived_current = False
        self.exposure = 0
        self.unknown_exposure = 0
        self.workings, self.zones, self.sensors, self.workers, self.exits = {}, {}, {}, {}, {}
        for key, a in self.attributes.items():
            kind = a["kind"]
            if kind == "working":
                self.workings[key] = dict(passability="open", closed_by="none")
            elif kind == "zone":
                self.zones[key] = dict(work_state="working", withdrawal_state="none", downtime_s=0,
                                       hazard_state="normal", data_quality="fresh", routing_restriction="allowed",
                                       last_known_hazard_state="normal", last_known_hazard_tick=0)
            elif kind == "sensor":
                self.sensors[key] = dict(value=0.0, rate=self.parameters["baseline_rate_mm_h"], measured_at_tick=0, measured_at_sim_s=0,
                                         link_state="online", quality="fresh")
            elif kind == "worker":
                self.workers[key] = dict(status="working", at_working=a["initial_working"],
                                         offset_m=a["initial_offset_m"], pos_quality="fresh")
            elif kind == "exit":
                self.exits[key] = dict(state="available", workers_out=0)
        self.cohort = sorted(self.workers)
        self._refresh()
        self._event("run.started", "shift")

    def _event(self, code, subject, arg="", command_id="", *, details=None):
        if getattr(self, "_forecast_only", False):
            return
        self.journal_seq += 1
        self.events.append(dict(seq=self.journal_seq, run=self.run, tick=self.tick,
                                sim_time_s=self.tick, code=code, subject=subject,
                                arg=arg, command_id=command_id or getattr(self, "_active_command_id", "")))
        if details is not None:
            self.events[-1]["details"] = copy.deepcopy(details)
        self.events = self.events[-50:]

    def _refresh(self):
        for key, s in self.sensors.items():
            a = self.attributes[key]
            if s["link_state"] == "online":
                s.update(measured_at_tick=self.tick, measured_at_sim_s=self.tick, quality="fresh")
                s["rate"] = self.parameters["unstable_rate_mm_h"] if (
                    f"instability:{a['zone']}" in self.conditions) else self.parameters["baseline_rate_mm_h"]
            else:
                age = self.tick - s["measured_at_sim_s"]
                s["quality"] = "lost" if age >= a["lost_after_s"] else (
                    "stale" if age >= a["stale_after_s"] else "fresh")
        for key, z in self.zones.items():
            sensor_id = self.attributes[key]["sensors"][0]
            s = self.sensors[sensor_id]
            z["data_quality"] = s["quality"]
            z["reason_sensor"] = sensor_id
            if s["quality"] == "fresh":
                rate = s["rate"]
                hazard = "danger" if rate >= self.parameters["danger_rate_mm_h"] else (
                    "attention" if rate >= self.parameters["attention_rate_mm_h"] else "normal")
                z.update(hazard_state=hazard, last_known_hazard_state=hazard,
                         last_known_hazard_tick=self.tick, index_at_tick=self.tick,
                         instability_index=min(1, rate / self.parameters["danger_rate_mm_h"]),
                         routing_restriction="blocked" if hazard == "danger" else "allowed",
                         reason_code="none" if hazard == "normal" else f"rate_above_{hazard}")
                if hazard != "normal":
                    z.update(reason_value=rate, reason_threshold=self.parameters[f"{hazard}_rate_mm_h"],
                             reason_unit="mm/h")
                else:
                    for field in ("reason_value", "reason_threshold", "reason_unit"):
                        z.pop(field, None)
            else:
                z.update(hazard_state="unknown", reason_code="sensor_" + s["quality"],
                         routing_restriction="blocked" if z["last_known_hazard_state"] == "danger" else "unknown")
                for field in ("reason_value", "reason_threshold", "reason_unit"):
                    z.pop(field, None)
        for key, w in self.workers.items():
            for field in list(w):
                if field.startswith("egress_") or field.startswith("route"):
                    del w[field]
            w.update(route(self.attributes, self.workings, self.zones, self.exits, w))
            if "egress_length_m" in w:
                w["egress_eta_s"] = w["egress_length_m"] / self.parameters["walking_speed_m_s"]
            if w["status"] != "out":
                zone = self.attributes[w["at_working"]].get("zone")
                w["location_hazard"] = self.zones[zone]["hazard_state"] if zone else "unknown"
                if w["status"] in ("moving_to_exit", "waiting"):
                    w["status"] = "moving_to_exit" if w["egress_status"] == "ok" else "waiting"
            else:
                w.pop("location_hazard", None)
        for key, z in self.zones.items():
            z["workers_count"] = sum(w["status"] != "out" and
                self.attributes[w["at_working"]].get("zone") == key for w in self.workers.values())
            staffed = sum(w["status"] == "working" and self.attributes[k]["home_zone"] == key
                          for k, w in self.workers.items()) >= self.attributes[key]["required_workers"]
            z["production_rate"] = self.attributes[key]["nominal_production_t_h"] if (
                z["work_state"] == "working" and staffed) else 0
            if z["withdrawal_state"] != "none":
                people = [w for k, w in self.workers.items() if self.attributes[k]["home_zone"] == key]
                z["withdrawal_state"] = "done" if all(w["status"] == "out" for w in people) else (
                    "incomplete" if any(w["status"] == "waiting" for w in people) else "in_progress")
        for key, e in self.exits.items():
            e["workers_out"] = sum(w.get("at_exit") == key for w in self.workers.values())
        observe(self)

    def _causes(self):
        return sorted(["passage_closed:" + k for k, w in self.workings.items() if w["passability"] == "closed"] +
                      ["hazard:" + k for k, z in self.zones.items() if z["hazard_state"] == "danger"] +
                      ["data_lost:" + k for k, z in self.zones.items() if z["data_quality"] != "fresh"])

    def _open_decision(self):
        causes = self._causes()
        if not causes:
            self.incident = {"state": "none"}
            self.forecasts = {}
            self.run_state, self.pause_reason = "running", "none"
            return
        self.decision_counter += 1
        self.run_state, self.pause_reason = "paused", "decision"
        self.decision_tick = self.tick
        self.selected_option = None
        self.last_out_s = None
        self.exposure = self.unknown_exposure = 0
        self.cohort = sorted(k for k, w in self.workers.items() if w["status"] != "out")
        affected = sorted(k for k in self.zones if any(c.endswith(":" + k) for c in causes))
        for key, w in self.workers.items():
            if w["status"] != "out" and (w["egress_status"] == "none" or any(
                    c.startswith("passage_closed:") for c in causes)):
                affected.append(self.attributes[key]["home_zone"])
        affected = sorted(set(affected))
        self.incident = dict(state="active", trigger=causes[0].split(":")[0], causes=causes,
                             zone=affected[0] if affected else "zone-a", scope=affected,
                             opened_at_tick=self.tick, decision_id=f"{self.run}-d{self.decision_counter}")
        self.comparison_key = fingerprint(dict(model=MODEL_VERSION, parameters=self.parameters,
            topology=self.attributes, seed=self.seed, tick=self.tick, workings=self.workings,
            zones=self.zones, sensors=self.sensors, workers=self.workers, exits=self.exits,
            cohort=self.cohort, conditions=sorted(self.conditions), schedule=self.schedule))
        self.comparable = True
        self._event("decision.opened", "incident", "Варианты рассчитаны из одного состояния",
                    details=dict(causes=causes, decision_id=self.incident["decision_id"],
                                 comparison_key=self.comparison_key))
        self.forecasts = self.forecast()

    def forecast(self):
        predictions = {}
        horizon = self.parameters["forecast_horizon_s"]
        for kind in ("observe", "stop_withdraw_zone", "withdraw_all"):
            trial = copy.deepcopy(self)
            trial._forecast_only = True
            trial.forecasts = {}
            trial.ledger = {}
            trial._execute(kind)
            trial.advance(horizon, decisions=False)
            predictions[kind] = dict(decision_id=self.incident["decision_id"],
                comparison_key=self.comparison_key, forecast_tick=self.tick,
                forecast_horizon_s=horizon, forecast_quality="partial" if any(
                    z["data_quality"] != "fresh" for z in self.zones.values()) else "full",
                **{"forecast_" + k: v for k, v in trial.metrics().items()})
        return predictions

    def _execute(self, kind):
        self._event("decision.selected", "incident", kind,
                    details=dict(decision_id=self.incident.get("decision_id"), option=kind))
        self.selected_option = kind
        self.incident.update(state="executing", selected_option=kind)
        scope = list(self.zones) if kind == "withdraw_all" else self.incident.get("scope", [])
        if kind != "observe":
            for zone in scope:
                self._withdraw(zone)
        self.run_state, self.pause_reason = "running", "none"
        self._refresh()

    def _withdraw(self, zone):
        self.zones[zone].update(work_state="stopped", withdrawal_state="in_progress")
        for key, w in self.workers.items():
            if self.attributes[key]["home_zone"] == zone and w["status"] != "out":
                w["status"] = "moving_to_exit"

    def _move(self, worker):
        if worker["status"] != "moving_to_exit" or worker["egress_status"] != "ok":
            return
        budget = self.parameters["walking_speed_m_s"]
        for segment in worker["route_segments"]:
            start, end = segment["from_offset_m"], segment["to_offset_m"]
            distance = abs(end - start)
            worker["at_working"] = segment["working"]
            worker["offset_m"] = end if distance <= budget else start + (1 if end > start else -1) * budget
            if distance > budget:
                return
            budget -= distance
        worker.update(status="out", at_exit=worker["egress_exit"])
        worker.pop("at_working", None)
        worker.pop("offset_m", None)

    def advance(self, seconds=1, *, decisions=True):
        if type(seconds) is not int or seconds < 0:
            raise ValueError("seconds must be a nonnegative integer")
        for _ in range(seconds):
            if self.run_state == "paused":
                break
            before = self._causes()
            # Left-endpoint integration over each one-second interval.
            metrics = self.metrics()
            self.exposure += metrics["in_danger"]
            self.unknown_exposure += metrics["unknown"]
            for z in self.zones.values():
                if z["production_rate"] == 0:
                    z["downtime_s"] += 1
            for w in self.workers.values():
                self._move(w)
            for s in self.sensors.values():
                if s["link_state"] == "online":
                    s["value"] += s["rate"] / 3600
            self.tick += 1
            due = [event for event in self.schedule if event["at_s"] <= self.tick]
            self.schedule = [event for event in self.schedule if event["at_s"] > self.tick]
            for event in due:
                self._condition(event["type"], event["target"])
            self._refresh()
            if self.decision_tick is not None and self.last_out_s is None and self.metrics()["all_out"]:
                self.last_out_s = self.tick - self.decision_tick
            if decisions and not self.selected_option and set(self._causes()) - set(before):
                self._open_decision()
            if self.selected_option and self.decision_tick is not None and (
                    self.tick - self.decision_tick >= self.parameters["forecast_horizon_s"]):
                self.incident["state"] = "done"
                self.run_state, self.pause_reason = "paused", "none"
                if decisions:
                    self._archive("horizon")

    def _archive(self, reason):
        if self.archived_current:
            return
        self._event("run.finished", "shift", reason, details=self.metrics())
        result = dict(id=self.run, state="finished", seed=self.seed, scenario_key=self.scenario_key,
            tick=self.tick, sim_time_s=self.tick, idSimulationRun=self.run,
            completion_reason=reason, finished_at_sim_s=self.tick, comparable=self.comparable,
            conditions=copy.deepcopy(self.conditions), **self.metrics())
        if self.comparison_key:
            result["comparison_key"] = self.comparison_key
        if self.selected_option:
            result["executed_option"] = "option-" + self.selected_option
            result.update(copy.deepcopy(self.forecasts.get(self.selected_option, {})))
        self.archive = (self.archive + [result])[-10:]
        self.archived_current = True

    def metrics(self):
        people = [self.workers[k] for k in self.cohort]
        unknown = sum(w["status"] != "out" and (
            w["egress_status"] == "unknown" or (
                self.attributes[w["at_working"]].get("zone") is not None and
                w.get("location_hazard") == "unknown")) for w in people)
        metrics = dict(out=sum(w["status"] == "out" for w in people),
                       all_out=bool(people) and all(w["status"] == "out" for w in people),
                       in_danger=sum(w.get("location_hazard") == "danger" for w in people),
                       no_route=sum(w["status"] != "out" and w["egress_status"] == "none" for w in people),
                       unknown=unknown, danger_exposure_person_s=self.exposure,
                       unknown_exposure_person_s=self.unknown_exposure,
                       downtime_s=sum(z["downtime_s"] for z in self.zones.values()))
        if metrics["all_out"] and self.last_out_s is not None:
            metrics["last_out_s"] = self.last_out_s
        return metrics

    def _condition(self, kind, target):
        mapping = {
            "condition.close_working": (self.workings, "working_closed", True),
            "condition.open_working": (self.workings, "working_closed", False),
            "condition.sensor_lost": (self.sensors, "sensor_lost", True),
            "condition.sensor_restored": (self.sensors, "sensor_lost", False),
            "condition.instability_on": (self.zones, "instability", True),
            "condition.instability_off": (self.zones, "instability", False),
        }
        if kind not in mapping:
            return "unknown_type"
        collection, prefix, enabled = mapping[kind]
        if target not in collection:
            return "unknown_target"
        condition = prefix + ":" + target
        if (condition in self.conditions) == enabled:
            return "already_in_state"
        if enabled:
            self.conditions.append(condition)
            self.conditions.sort()
        else:
            self.conditions.remove(condition)
        if prefix == "working_closed":
            collection[target].update(passability="closed" if enabled else "open",
                                      closed_by="scenario" if enabled else "none")
        elif prefix == "sensor_lost":
            collection[target]["link_state"] = "offline" if enabled else "online"
        self._event("condition.set" if enabled else "condition.cancelled", target, kind)
        return "none"

    def command(self, body):
        if not isinstance(body, dict) or not isinstance(body.get("command_id"), str) or not re.fullmatch(
                r"c-[0-9a-f]{32}", body["command_id"]):
            raise ValueError("malformed command_id")
        command_id = body["command_id"]
        digest = fingerprint(body)
        previous = self.ledger.get(command_id)
        if previous and previous["digest"] == digest:
            ack = copy.deepcopy(previous["ack"])
            self.commands = [a for a in self.commands if a["id"] != command_id][-31:] + [ack]
            return ack
        ack = dict(id=command_id, type=body.get("type", ""), target=body.get("target", ""),
                   run=self.run, tick=self.tick, sim_time_s=self.tick, status="rejected", reason="malformed")
        if previous:
            reason = "command_id_conflict"
        elif any(not isinstance(body.get(k), str) for k in ("type", "target", "run")):
            reason = "malformed"
        elif body["run"] != self.run:
            reason = "invalid_run"
            # The ack run/tick describe where the rejection was processed.
            ack["requested_run"] = body["run"]
        else:
            self._active_command_id = command_id
            try:
                reason = self._apply(body)
            finally:
                self._active_command_id = ""
        ack["reason"] = reason
        if reason in ("none", "already_in_state"):
            ack["status"] = "applied"
        if ack["run"] != self.run and ack["status"] == "applied":
            ack["new_run"] = self.run
        self.commands = [a for a in self.commands if a["id"] != command_id][-31:] + [ack]
        if not previous:
            self.ledger[command_id] = dict(digest=digest, ack=copy.deepcopy(ack))
        self._event("command." + ack["status"], body.get("target", ""),
                    body.get("type", "") if ack["status"] == "applied" else reason,
                    command_id, details=dict(reason=reason, status=ack["status"]))
        return copy.deepcopy(ack)

    def _apply(self, body):
        kind, target = body["type"], body["target"]
        if self.archived_current and kind not in ("run.reset", "run.start_preset"):
            return "not_allowed_in_state"
        if kind.startswith("condition."):
            before = self._causes()
            reason = self._condition(kind, target)
            if reason != "none":
                return reason
            self._refresh()
            if self.selected_option:
                self.comparable = False
            if self.selected_option:
                self.incident["causes"] = self._causes()
            elif self.pause_reason == "decision" or set(self._causes()) - set(before):
                self._open_decision()
            return "none"
        if kind in ("run.reset", "run.start_preset"):
            preset = None
            if kind == "run.start_preset":
                preset = next((p for p in self.attributes["mine"]["presets"] if p["id"] == target), None)
                if preset is None:
                    return "unknown_target"
            elif target != "shift":
                return "unknown_target"
            self._archive("reset")
            self._new_run(preset)
            return "none"
        if kind == "action.execute_option":
            option = self.attributes.get(target, {}).get("option_kind")
            if not option:
                return "unknown_target"
            if body.get("decision_id") != self.incident.get("decision_id"):
                return "stale_decision"
            if self.incident["state"] != "active":
                return "not_allowed_in_state"
            self._execute(option)
            return "none"
        if kind not in ("action.stop_zone", "action.resume_zone", "action.withdraw_zone"):
            return "unknown_type"
        if target not in self.zones:
            return "unknown_target"
        z = self.zones[target]
        if kind == "action.resume_zone":
            if z["routing_restriction"] != "allowed":
                return "not_allowed_in_state"
            staffed = sum(w["status"] == "working" and self.attributes[k]["home_zone"] == target
                          for k, w in self.workers.items())
            if staffed < self.attributes[target]["required_workers"]:
                return "insufficient_workers"
            if z["work_state"] == "working":
                return "already_in_state"
            z["work_state"] = "working"
        elif kind == "action.stop_zone":
            if z["work_state"] == "stopped":
                return "already_in_state"
            z["work_state"] = "stopped"
        else:
            if z["withdrawal_state"] != "none":
                return "already_in_state"
            self._withdraw(target)
            self.run_state, self.pause_reason = "running", "none"
            self.incident["state"] = "executing"
        if self.selected_option:
            self.comparable = False
        self._refresh()
        # A stop on the decision checkpoint changes the state being compared.
        if self.pause_reason == "decision":
            self._open_decision()
        return "none"
