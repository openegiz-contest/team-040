import copy
import json
from pathlib import Path
import tempfile
import unittest

from .model import Mine, SCOPE_POLICY_VERSION
from .storage import Store
from .test_model import command, execute


class ScopeTests(unittest.TestCase):
    def test_unused_closure_does_not_stop_any_zone(self):
        mine = Mine()
        command(mine, "condition.close_working", "w-05")
        self.assertEqual(mine.incident["scope"], [])
        self.assertNotIn("zone", mine.incident)
        execute(mine, "stop_withdraw_zone")
        self.assertTrue(all(z["work_state"] == "working" for z in mine.zones.values()))

    def test_shared_exit_affects_both_zones(self):
        mine = Mine()
        self.assertTrue(all("w-02" in w["route"] for w in mine.workers.values()))
        command(mine, "condition.close_working", "w-02")
        self.assertEqual(mine.incident["scope"], ["zone-a", "zone-b"])

    def test_multiple_closures_union_reopen_and_hazard(self):
        mine = Mine()
        command(mine, "condition.close_working", "w-07")
        self.assertEqual(mine.incident["scope"], ["zone-a"])
        command(mine, "condition.close_working", "w-12")
        self.assertEqual(mine.incident["scope"], ["zone-a", "zone-b"])
        command(mine, "condition.open_working", "w-07")
        self.assertEqual(mine.incident["scope"], ["zone-b"])
        command(mine, "condition.instability_on", "zone-a")
        self.assertEqual(mine.incident["scope"], ["zone-a", "zone-b"])

    def test_current_closed_edge_includes_worker_even_without_reference_exit(self):
        mine = Mine()
        for e in mine.exits.values():
            e["state"] = "unavailable"
        mine._refresh()
        command(mine, "condition.close_working", "w-07")
        self.assertEqual(mine.incident["scope"], ["zone-a"])
        self.assertEqual(mine.incident["scope_reasons"]["zone-a"][0]["reason"], "current_working_closed")

    def test_scope_uses_current_position_not_initial_home_route(self):
        mine = Mine()
        mine.workers["worker-b1"].update(at_working="w-07", offset_m=20)
        mine._refresh()
        command(mine, "condition.close_working", "w-07")
        self.assertEqual(mine.incident["scope"], ["zone-a", "zone-b"])
        evidence = mine.incident["scope_reasons"]["zone-b"]
        self.assertEqual([r["worker"] for r in evidence], ["worker-b1"])

    def test_old_pending_decision_is_reoffered_and_old_command_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = Store(path)
            store.transact(lambda m: command(m, "condition.close_working", "w-04"))
            old = store.model.incident["decision_id"]
            data = json.loads(path.read_text(encoding="utf-8"))
            data["state"]["incident"].pop("scope_policy_version")
            data["state"]["incident"]["scope"] = ["zone-a", "zone-b"]
            path.write_text(json.dumps(data), encoding="utf-8")
            restored = Store(path)
            self.assertEqual(restored.model.incident["scope"], ["zone-a"])
            self.assertEqual(restored.model.incident["scope_policy_version"], SCOPE_POLICY_VERSION)
            self.assertNotEqual(restored.model.incident["decision_id"], old)
            self.assertEqual(command(restored.model, "action.execute_option", "option-stop_withdraw_zone",
                                     decision_id=old)["reason"], "stale_decision")
            restored.transact(lambda m: None)
            self.assertEqual(Store(path).model.incident, restored.model.incident)

    def test_executing_checkpoint_is_not_retroactively_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = Store(path)
            store.transact(lambda m: command(m, "condition.close_working", "w-04"))
            store.transact(lambda m: execute(m, "withdraw_all"))
            state = copy.deepcopy(store.model.__dict__)
            state["incident"].pop("scope_policy_version")
            data = json.loads(path.read_text(encoding="utf-8"))
            data["state"] = state
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(Store(path).model.__dict__, state)


if __name__ == "__main__":
    unittest.main()
