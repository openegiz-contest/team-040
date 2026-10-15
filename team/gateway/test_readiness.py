import copy
import datetime
import unittest

from team.sim.model import Mine
from team.sim.twins import snapshot
from .readiness import validate


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        twins = snapshot(Mine())
        self.shift = twins["shift"]
        self.shift["_modified"] = datetime.datetime.fromtimestamp(1000, datetime.timezone.utc).isoformat()
        self.expected = twins["mine"]["attributes"]["dynamic_ids"]

    def test_complete_snapshot(self):
        self.assertEqual(validate(self.shift, self.expected, 1001), ("run-0001", 1))

    def test_stale_or_future_snapshot(self):
        for now in (1020, 990):
            with self.assertRaises(ValueError):
                validate(self.shift, self.expected, now)

    def test_missing_duplicate_or_different_tick(self):
        for kind in ("missing", "duplicate", "tick"):
            twin = copy.deepcopy(self.shift)
            scene = twin["features"]["scene"]["properties"]["value"]
            if kind == "missing":
                scene.pop()
            elif kind == "duplicate":
                scene[-1] = scene[0]
            else:
                scene[0]["features"]["tick"]["properties"]["value"] += 1
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate(twin, self.expected, 1001)


if __name__ == "__main__":
    unittest.main()
