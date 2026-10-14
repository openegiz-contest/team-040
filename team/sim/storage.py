"""Persist model and command ledger together before acknowledging a mutation."""

import copy
import json
import os
from pathlib import Path
import tempfile

from .model import Mine, SCOPE_POLICY_VERSION
from .topology import MODEL_VERSION
from .journal import capture
from .parameters import registry


class Store:
    """Single-process owner. Never open one checkpoint concurrently in two services."""

    def __init__(self, path):
        self.path = Path(path)
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
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
