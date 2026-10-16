import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .model import Mine
from .storage import Store
from .twins import mqtt_messages, snapshot


def command(mine, kind, target, **extra):
    return mine.command(dict(command_id=f"c-{len(mine.ledger) + 1:032x}", type=kind,
                             target=target, run=mine.run, **extra))


def execute(mine, kind):
    return command(mine, "action.execute_option", "option-" + kind,
                   decision_id=mine.incident["decision_id"])


class ModelTests(unittest.TestCase):
    def test_geometry_matches_travel_distance(self):
        mine = Mine()
        nodes = mine.attributes["mine"]["nodes"]
        for key in mine.workings:
            a = mine.attributes[key]
            points = [[nodes[a["from"]][c] for c in "xyz"], *a["points"],
                      [nodes[a["to"]][c] for c in "xyz"]]
            self.assertAlmostEqual(a["length_m"], sum(math.dist(p, q) for p, q in zip(points, points[1:])))

    def test_closure_causes_detour(self):
        mine = Mine()
        before = mine.workers["worker-a1"]["egress_length_m"]
        command(mine, "condition.close_working", "w-04")
        worker = mine.workers["worker-a1"]
        self.assertGreater(worker["egress_length_m"], before)
        self.assertNotIn("w-04", worker["route"])
        self.assertEqual(mine.run_state, "paused")

    def test_closed_edge_does_not_teleport_worker(self):
        mine = Mine()
        position = mine.workers["worker-a1"]["offset_m"]
        command(mine, "condition.close_working", "w-07")
        prediction = mine.forecasts["withdraw_all"]
        self.assertFalse(prediction["forecast_all_out"])
        self.assertNotIn("forecast_last_out_s", prediction)
        execute(mine, "withdraw_all")
        mine.advance(100)
        worker = mine.workers["worker-a1"]
        self.assertEqual(worker["offset_m"], position)
        self.assertEqual(worker["egress_reason"], "current_working_closed")
        command(mine, "condition.open_working", "w-07")
        mine.advance(1)
        self.assertLess(worker["offset_m"], position)
        self.assertFalse(mine.comparable)

    def test_no_route_when_both_exits_unavailable(self):
        mine = Mine()
        for e in mine.exits.values():
            e["state"] = "unavailable"
        mine._refresh()
        self.assertEqual(mine.metrics()["no_route"], 8)

    def test_movement_consumes_distance_across_junction(self):
        mine = Mine()
        worker = mine.workers["worker-a1"]
        worker["offset_m"] = 0.3
        mine._refresh()
        initial = worker["egress_length_m"]
        next_edge = worker["route"][1]
        command(mine, "action.withdraw_zone", "zone-a")
        mine.advance(1)
        self.assertAlmostEqual(worker["egress_length_m"], initial - 1.25)
        self.assertEqual(worker["at_working"], next_edge)

    def test_exit_time_matches_distance_and_workers_preserved(self):
        mine = Mine()
        distance = max(w["egress_length_m"] for k, w in mine.workers.items()
                       if mine.attributes[k]["home_zone"] == "zone-a" and mine.attributes[k]["role"] == "crew")
        command(mine, "action.withdraw_zone", "zone-a")
        mine.advance(math.ceil(distance / 1.25) - 1)
        crew_out = lambda: sum(mine.workers[f"worker-a{i}"]["status"] == "out" for i in range(1, 4))
        self.assertLess(crew_out(), 3)
        mine.advance(1)
        self.assertEqual(crew_out(), 3)
        self.assertEqual(mine.metrics()["out"], 4)
        self.assertEqual(len(mine.workers), 8)
        self.assertEqual(mine.zones["zone-a"]["withdrawal_state"], "done")
        self.assertFalse(mine.metrics()["all_out"])
        self.assertNotIn("last_out_s", mine.metrics())
        self.assertEqual(command(mine, "action.resume_zone", "zone-a")["reason"], "insufficient_workers")

    def test_danger_lost_sensor_retains_measurement_and_restriction(self):
        mine = Mine()
        command(mine, "condition.instability_on", "zone-a")
        execute(mine, "observe")
        mine.advance(2)
        command(mine, "condition.sensor_lost", "sens-ext-a")
        measured = copy.deepcopy(mine.sensors["sens-ext-a"])
        mine.advance(15)
        zone = mine.zones["zone-a"]
        self.assertEqual(zone["hazard_state"], "unknown")
        self.assertEqual(zone["last_known_hazard_state"], "danger")
        self.assertEqual(zone["routing_restriction"], "blocked")
        mine.advance(15)
        sensor = mine.sensors["sens-ext-a"]
        self.assertEqual(sensor["quality"], "lost")
        self.assertEqual(sensor["value"], measured["value"])
        self.assertEqual(sensor["measured_at_sim_s"], measured["measured_at_sim_s"])
        self.assertGreater(mine.metrics()["unknown_exposure_person_s"], 0)

    def test_first_sensor_stale_opens_decision_at_measurement_age(self):
        mine = Mine()
        command(mine, "condition.sensor_lost", "sens-ext-a")
        mine.advance(100)
        self.assertEqual(mine.tick, 15)
        self.assertEqual(mine.run_state, "paused")
        self.assertEqual(mine.forecasts["observe"]["forecast_quality"], "partial")

    def test_manual_change_preserves_original_forecast_and_marks_incomparable(self):
        mine = Mine()
        command(mine, "condition.instability_on", "zone-a")
        forecasts = copy.deepcopy(mine.forecasts)
        key = mine.comparison_key
        execute(mine, "withdraw_all")
        mine.advance(20)
        command(mine, "condition.close_working", "w-03")
        self.assertFalse(mine.comparable)
        self.assertEqual(mine.forecasts, forecasts)
        self.assertEqual(mine.comparison_key, key)

    def test_danger_edge_can_be_left_but_not_entered(self):
        mine = Mine()
        command(mine, "condition.instability_on", "zone-a")
        self.assertEqual(mine.workers["worker-a1"]["egress_status"], "ok")
        for key, worker in mine.workers.items():
            if mine.attributes[key]["home_zone"] == "zone-b":
                self.assertNotIn("w-07", worker["route"])

    def test_forecasts_do_not_mutate_actual_state(self):
        mine = Mine()
        command(mine, "condition.instability_on", "zone-a")
        before = copy.deepcopy(mine.__dict__)
        self.assertEqual(mine.forecast(), mine.forecasts)
        self.assertEqual(mine.__dict__, before)
        self.assertEqual(mine.forecasts["observe"]["forecast_danger_exposure_person_s"], 2777)
        self.assertLess(mine.forecasts["withdraw_all"]["forecast_danger_exposure_person_s"], 2700)
        self.assertTrue(mine.forecasts["withdraw_all"]["forecast_all_out"])
        self.assertFalse(mine.forecasts["stop_withdraw_zone"]["forecast_all_out"])

    def test_each_forecast_equals_execution_of_same_model(self):
        original = Mine()
        command(original, "condition.instability_on", "zone-a")
        for kind in original.forecasts:
            with self.subTest(kind=kind):
                mine = copy.deepcopy(original)
                expected = {k.removeprefix("forecast_"): v for k, v in mine.forecasts[kind].items()
                            if k.startswith("forecast_") and k.removeprefix("forecast_") in
                            ("out", "all_out", "in_danger", "no_route", "unknown", "danger_exposure_person_s",
                             "unknown_exposure_person_s", "downtime_s", "last_out_s", "hauled_t", "planned_t",
                             "production_lost_t", "machines_in_danger", "machines_unknown", "machines_stuck",
                             "conflicts", "conflict_yield_s")}
                execute(mine, kind)
                mine.advance(1000)
                self.assertEqual(mine.metrics(), expected)
                self.assertEqual(mine.tick, 900)
                self.assertEqual(mine.archive[-1]["completion_reason"], "horizon")
                archived = copy.deepcopy(mine.archive[-1])
                command(mine, "run.reset", "shift")
                self.assertEqual(mine.archive[-1], archived)

    def test_presets_reproducible_despite_different_run_ids(self):
        mine = Mine()
        command(mine, "run.start_preset", "p-instability")
        mine.advance(500)
        self.assertEqual(mine.tick, 60)
        key = mine.comparison_key
        command(mine, "run.start_preset", "p-instability")
        mine.advance(500)
        self.assertEqual(mine.comparison_key, key)
        mine.parameters["walking_speed_m_s"] = 1.0
        mine._open_decision()
        self.assertNotEqual(mine.comparison_key, key)

    def test_repeated_condition_is_idempotent_and_decision_is_checked(self):
        mine = Mine()
        command(mine, "condition.instability_on", "zone-a")
        decision = mine.incident["decision_id"]
        self.assertEqual(command(mine, "condition.instability_on", "zone-a")["reason"], "already_in_state")
        self.assertEqual(mine.incident["decision_id"], decision)
        command(mine, "action.stop_zone", "zone-a")
        self.assertNotEqual(mine.incident["decision_id"], decision)
        self.assertEqual(command(mine, "action.execute_option", "option-withdraw_all",
                                 decision_id=decision)["reason"], "stale_decision")

    def test_duplicate_reset_survives_restart_and_ack_window_eviction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = Store(path)
            body = dict(command_id="c-" + "e" * 32, type="run.reset", target="shift", run=store.model.run)
            original_ack = store.transact(lambda m: m.command(body))
            for _ in range(35):
                store.transact(lambda m: command(m, "action.stop_zone", "zone-a"))
            self.assertNotIn(body["command_id"], [c["id"] for c in store.model.commands])
            store = Store(path)
            self.assertEqual(store.transact(lambda m: m.command(body)), original_ack)
            self.assertEqual(store.model.run_number, 2)
            self.assertEqual(store.model.commands[-1], original_ack)
            conflicting = {**body, "target": "other"}
            self.assertEqual(store.transact(lambda m: m.command(conflicting))["reason"], "command_id_conflict")
            self.assertEqual(store.transact(lambda m: m.command(body)), original_ack)

    def test_failed_checkpoint_does_not_ack_or_mutate_in_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.json")
            with patch("team.sim.storage.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    store.transact(lambda m: command(m, "run.reset", "shift"))
            self.assertEqual(store.model.run_number, 1)
            self.assertFalse(store.model.ledger)

    def test_stale_run_and_invalid_command_do_not_change_model(self):
        mine = Mine()
        command(mine, "run.reset", "shift")
        ack = mine.command(dict(command_id="c-" + "a" * 32, type="condition.close_working",
                                target="w-07", run="run-0001"))
        self.assertEqual(ack["reason"], "invalid_run")
        self.assertEqual(mine.workings["w-07"]["passability"], "open")
        self.assertEqual(command(mine, "condition.close_working", "w-no-such-edge")["reason"], "unknown_target")

    def test_snapshot_consistency_and_paused_heartbeat(self):
        mine = Mine()
        command(mine, "condition.close_working", "w-07")
        first = snapshot(mine)
        mine.advance(10)
        second = snapshot(mine)
        get = lambda twin, name: twin["features"][name]["properties"]["value"]
        self.assertEqual(get(first["shift"], "tick"), get(second["shift"], "tick"))
        self.assertEqual(get(second["shift"], "publication_seq"), get(first["shift"], "publication_seq") + 1)
        scene = get(second["shift"], "scene")
        self.assertEqual({s["thingId"] for s in scene}, set(mine.attributes["mine"]["dynamic_ids"]))
        for twin in scene:
            for name in ("tick", "sim_time_s", "idSimulationRun"):
                self.assertEqual(get(twin, name), get(second["shift"], name))
        self.assertNotIn("_modified", second["shift"])
        self.assertEqual(json.loads(json.dumps(second)), second)
        envelopes = list(mqtt_messages(second))
        self.assertTrue(envelopes[-1][0].endswith("/shift"))
        self.assertNotIn("authorization", json.dumps(envelopes).lower())


if __name__ == "__main__":
    unittest.main()
