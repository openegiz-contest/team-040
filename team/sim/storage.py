"""Persist model and command ledger together before acknowledging a mutation."""

import copy
import json
import os
from pathlib import Path
import tempfile

from .model import Mine, SCOPE_POLICY_VERSION
from .topology import MODEL_VERSION
from .journal import capture
from .parameters import registry, PARAMETERS


def migrate_v01(state):
    """Archive old physics without inventing equipment metrics for the old run."""
    fresh = Mine({**PARAMETERS, **state["parameters"]})
    for key in ("publication_seq", "run_number", "journal_seq", "events", "ledger", "commands", "archive"):
        setattr(fresh, key, copy.deepcopy(state[key]))
    if not state["archived_current"]:
        people = [state["workers"][k] for k in state["cohort"]]
        metrics = dict(out=sum(w["status"] == "out" for w in people),
            all_out=bool(people) and all(w["status"] == "out" for w in people),
            in_danger=sum(w.get("location_hazard") == "danger" for w in people),
            no_route=sum(w["status"] != "out" and w["egress_status"] == "none" for w in people),
            unknown=sum(w["status"] != "out" and (w["egress_status"] == "unknown" or
                (state["attributes"][w["at_working"]].get("zone") is not None and
                 w.get("location_hazard") == "unknown")) for w in people),
            danger_exposure_person_s=state["exposure"], unknown_exposure_person_s=state["unknown_exposure"],
            downtime_s=sum(z["downtime_s"] for z in state["zones"].values()))
        if metrics["all_out"] and state["last_out_s"] is not None:
            metrics["last_out_s"] = state["last_out_s"]
        result = dict(id=state["run"], state="finished", seed=state["seed"],
            scenario_key=state["scenario_key"], tick=state["tick"], sim_time_s=state["tick"],
            idSimulationRun=state["run"], completion_reason="reset", finished_at_sim_s=state["tick"],
            comparable=state["comparable"], conditions=copy.deepcopy(state["conditions"]), **metrics)
        if state.get("comparison_key"):
            result["comparison_key"] = state["comparison_key"]
        if state.get("selected_option"):
            result["executed_option"] = "option-" + state["selected_option"]
            result.update(copy.deepcopy(state["forecasts"].get(state["selected_option"], {})))
        fresh.archive = (fresh.archive + [result])[-10:]
    fresh._new_run()
    fresh._event("model.migrated", "shift", "Модель 0.1 → 0.2: старый прогон завершён, начат новый",
                 details=dict(from_version="0.1", to_version="0.2", previous_run=state["run"]))
    return fresh


class Store:
    """Single-process owner. Never open one checkpoint concurrently in two services."""

    def __init__(self, path):
        self.path = Path(path)
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("model_version") == "0.1" and MODEL_VERSION == "0.2":
                self.model = migrate_v01(data["state"])
                self.transact(lambda model: None)  # Atomic, one-time migration before any publication.
                return
            if data.get("model_version") != MODEL_VERSION:
                raise ValueError("checkpoint model version mismatch; explicit migration required")
            self.model = Mine.__new__(Mine)
            self.model.__dict__.update(data["state"])
            # Additive metadata/observer migration; keep run, physics and ledger intact.
            if not hasattr(self.model, "_journal_state"):
                self.model._journal_state = capture(self.model)
            self.model.attributes["mine"]["parameter_registry"] = registry(self.model.parameters)
            # Re-offer only an unexecuted decision under the new scope policy.
            # A fresh decision_id rejects commands made against the old offers.
            if (self.model.pause_reason == "decision" and self.model.incident["state"] == "active"
                    and self.model.incident.get("scope_policy_version", 1) != SCOPE_POLICY_VERSION):
                self.model._open_decision()
        else:
            self.model = Mine()

    def transact(self, operation):
        candidate = copy.deepcopy(self.model)
        result = operation(candidate)
        encoded = json.dumps(dict(model_version=MODEL_VERSION, state=candidate.__dict__),
                             ensure_ascii=False, allow_nan=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix="checkpoint-", suffix=".tmp", delete=False) as stream:
                temporary = stream.name
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        self.model = candidate
        return result
