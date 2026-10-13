"""Persist model and command ledger together before acknowledging a mutation."""

import copy
import json
import os
from pathlib import Path
import tempfile

from .model import Mine
from .topology import MODEL_VERSION


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
