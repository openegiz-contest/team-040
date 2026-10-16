import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .model import Mine
from .storage import Store
from .test_model import command, execute
from .twins import snapshot


class JournalTests(unittest.TestCase):
    def test_hazard_evidence_command_correlation_and_forecast_isolation(self):
        mine = Mine()
        ack = command(mine, "condition.instability_on", "zone-a")
        events = [e for e in mine.events if e["code"] == "hazard.transition"]
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["command_id"], ack["id"])
        self.assertEqual(event["details"]["reason_value"], 2.6)
        self.assertEqual(event["details"]["reason_threshold"], 2)
        self.assertEqual(event["details"]["after"]["hazard_state"], "danger")
        self.assertFalse(any(e["code"] in ("decision.selected", "worker.exited") for e in mine.events))
        before = copy.deepcopy(mine.events)
        mine.forecast()
        mine._refresh()
        snapshot(mine)
        self.assertEqual(mine.events, before)

    def test_closure_removes_route_reopening_restores_it(self):
        mine = Mine()
        command(mine, "condition.close_working", "w-07")
        lost = [e for e in mine.events if e["code"] == "route.changed"]
        self.assertEqual(len(lost), 4)
        self.assertTrue(all(e["details"]["after"]["egress_reason"] == "current_working_closed" for e in lost))
        self.assertIn("passage_closed:w-07", lost[0]["details"]["causes"])
        seq = mine.journal_seq
        command(mine, "condition.open_working", "w-07")
        restored = [e for e in mine.events if e["seq"] > seq and e["code"] == "route.changed"]
        self.assertEqual(len(restored), 4)
        self.assertTrue(all(e["details"]["after"]["egress_status"] == "ok" for e in restored))

    def test_movement_is_not_reroute_exit_once(self):
        mine = Mine()
        command(mine, "condition.instability_on", "zone-a")
        execute(mine, "withdraw_all")
        mine.advance(900)
        self.assertFalse(any(e["code"] == "route.changed" and mine.attributes[e["subject"]]["role"] == "crew"
                             for e in mine.events))
        exits = [e for e in mine.events if e["code"] == "worker.exited"]
        self.assertEqual(len(exits), 8)
        self.assertEqual(len({e["subject"] for e in exits}), 8)
        self.assertEqual(mine.events[-1]["code"], "run.finished")

    def test_alternative_exit_is_a_real_reroute(self):
        mine = Mine()
        original = mine.workers["worker-a1"]["egress_exit"]
        closed = mine.workers["worker-a1"]["route"][-1]
        command(mine, "condition.close_working", closed)
        event = next(e for e in mine.events if e["code"] == "route.changed" and e["subject"] == "worker-a1")
        self.assertEqual(event["details"]["before"]["exit"], original)
        self.assertNotEqual(event["details"]["after"]["exit"], original)
        self.assertEqual(event["details"]["after"]["egress_status"], "ok")
        self.assertNotIn(closed, [p[0] for p in event["details"]["after"]["path"]])

    def test_loss_and_recovery_preserve_last_danger_evidence(self):
        mine = Mine()
        command(mine, "condition.instability_on", "zone-a")
        execute(mine, "observe")
        command(mine, "condition.sensor_lost", "sens-ext-a")
        mine.advance(30)
        changes = [e for e in mine.events if e["code"] == "hazard.transition"]
        self.assertEqual([e["tick"] for e in changes], [0, 15, 30])
        self.assertEqual(changes[-1]["details"]["last_known_hazard_state"], "danger")
        self.assertEqual(changes[-1]["details"]["after"]["routing_restriction"], "blocked")
        command(mine, "condition.sensor_restored", "sens-ext-a")
        self.assertEqual([e for e in mine.events if e["code"] == "hazard.transition"][-1]
                         ["details"]["after"]["hazard_state"], "danger")

    def test_restart_dedup_reset_and_old_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = Store(path)
            body = dict(command_id="c-" + "a" * 32, type="condition.close_working", target="w-07", run=store.model.run)
            store.transact(lambda m: m.command(body))
            events = copy.deepcopy(store.model.events)
            store = Store(path)
            store.transact(lambda m: (m._refresh(), m.command(body)))
            self.assertEqual(events, store.model.events)
            old_seq = store.model.journal_seq
            store.transact(lambda m: command(m, "run.reset", "shift"))
            new = [e for e in store.model.events if e["seq"] > old_seq]
            self.assertEqual([e["code"] for e in new], ["run.finished", "run.started", "command.applied"])
            data = json.loads(path.read_text(encoding="utf-8"))
            data["state"].pop("_journal_state")
            path.write_text(json.dumps(data), encoding="utf-8")
            store = Store(path)
            seq = store.model.journal_seq
            store.transact(lambda m: m._refresh())
            self.assertEqual(store.model.journal_seq, seq)

    def test_ring_sequences_and_snapshot_details(self):
        mine = Mine()
        with patch.object(mine, "forecast", return_value={}):
            for _ in range(20):
                command(mine, "condition.close_working", "w-07")
                command(mine, "condition.open_working", "w-07")
        self.assertEqual(len(mine.events), 50)
        self.assertEqual([e["seq"] for e in mine.events], list(range(mine.journal_seq - 49, mine.journal_seq + 1)))
        exported = snapshot(mine)["journal"]["features"]["events"]["properties"]["value"]
        self.assertEqual(json.loads(json.dumps(exported)), mine.events)


if __name__ == "__main__":
    unittest.main()
