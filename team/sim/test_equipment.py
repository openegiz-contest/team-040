import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .model import Mine
from .storage import Store
from .twins import snapshot, mqtt_messages
from .equipment import cycle_step, distance_of, locate, reset_window
from .test_model import command, execute

FIXTURES = Path(__file__).with_name("fixtures")


class EquipmentTests(unittest.TestCase):
    def test_geometry_guard_and_placements(self):
        m = Mine()
        geometry = dict(nodes=m.attributes["mine"]["nodes"], workings={
            k: {f: v[f] for f in ("from", "to", "points", "length_m")}
            for k, v in m.attributes.items() if v["kind"] == "working"})
        self.assertEqual(geometry, json.loads((FIXTURES/"topology-t1.json").read_text()))
        self.assertFalse(set(m.attributes["lhd-a"]["cycle_route"]) & set(m.attributes["lhd-b"]["cycle_route"]))
        for key in m.machines:
            a = m.attributes[key]
            for point in (a["load_point"], a["bay"]):
                self.assertTrue(0 <= point["offset_m"] <= m.attributes[point["working"]]["length_m"])
            self.assertIsNone(m.attributes[a["bay"]["working"]].get("zone"))
            for k, w in m.workers.items():
                if m.attributes[k]["role"] == "crew":
                    self.assertNotIn(a["bay"]["working"], w["route"])

    def test_cycle_and_nominal_rate_are_derived(self):
        for changes in ({}, {"lhd_load_s": 12, "lhd_speed_empty_m_s": 4, "lhd_payload_t": 10}):
            m = Mine(changes)
            a = m.attributes["lhd-a"]
            expected = (m.parameters["lhd_load_s"] + m.parameters["lhd_dump_s"] +
                        math.ceil(155/m.parameters["lhd_speed_loaded_m_s"]) +
                        math.ceil(155/m.parameters["lhd_speed_empty_m_s"]))
            self.assertEqual(a["cycle_s"], expected)
            m.advance(expected)
            state = m.machines["lhd-a"]
            self.assertEqual((state["_phase"], state["_s"], state["_elapsed"], state["loaded"]), ("loading", 0, 0, False))
            self.assertEqual(state["loads_dumped"], 1)
            self.assertAlmostEqual(a["nominal_production_t_h"], m.parameters["lhd_payload_t"]*3600/expected)

    def test_tick_60_loaded_position_and_operator(self):
        m = Mine()
        m.advance(60)
        machine = m.machines["lhd-a"]
        self.assertEqual((machine["at_working"], machine["offset_m"], machine["loaded"]), ("w-07", 42.5, True))
        operator = m.workers["worker-a4"]
        self.assertEqual(operator["aboard"], "lhd-a")
        self.assertEqual(operator["offset_m"], machine["offset_m"])

    def test_crews_exit_at_exact_original_walk_ticks_in_every_option(self):
        for preset in ("p-instability", "p-detour", "p-trapped", "p-sensor"):
            base = Mine()
            command(base, "run.start_preset", preset)
            base.advance(1000)
            for option in ("observe", "stop_withdraw_zone", "withdraw_all"):
                m = copy.deepcopy(base)
                expected = {}
                for k,w in m.workers.items():
                    a = m.attributes[k]
                    targeted = option == "withdraw_all" or (option == "stop_withdraw_zone" and a["home_zone"] in m.incident["scope"])
                    if a["role"] == "crew":
                        expected[k] = math.ceil(w["egress_length_m"]/1.25) if targeted and w["egress_status"] == "ok" else None
                execute(m, option)
                actual = {k: None for k in expected}
                for elapsed in range(1,901):
                    m.advance()
                    for k in actual:
                        if actual[k] is None and m.workers[k]["status"] == "out":
                            actual[k] = elapsed
                self.assertEqual(actual, expected, (preset, option))

    def traffic_case(self, worker_s):
        m = Mine()
        machine = m.machines["lhd-a"]
        machine.update(_s=20., _phase="hauling", loaded=True)
        # A waiting person has no route and remains stationary for exact gap checks.
        w = m.workers["worker-a1"]
        w.update(status="waiting", at_working="w-07", offset_m=80-worker_s)
        for exit in m.exits.values():
            exit["state"]="unavailable"
        m._refresh()
        reset_window(m)
        return m

    def test_yield_starts_one_episode_and_delays_machine_only(self):
        m = self.traffic_case(30)
        offset = m.machines["lhd-a"]["offset_m"]
        m.advance(3)
        machine = m.machines["lhd-a"]
        self.assertEqual(machine["offset_m"], offset)
        self.assertEqual((machine["activity"], machine["yielding_to"]), ("yielding", "worker-a1"))
        self.assertEqual((m.conflicts, m.conflict_yield_s), (1,3))
        events = [e for e in m.events if e["code"]=="equipment.conflict"]
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]["details"]["gap_m"],10)
        m.workers["worker-a1"]["offset_m"] = 75
        m.advance()
        self.assertNotIn("yielding_to", machine)
        self.assertEqual(m.conflicts,1)

    def test_person_behind_or_beyond_leg_never_causes_encounter(self):
        for s in (10, 165):
            m=self.traffic_case(s)
            if s == 165:
                m.workers["worker-a1"].update(at_working="w-03",offset_m=65)
                m._refresh()
            m.advance()
            self.assertEqual(m.conflicts,0)
            self.assertEqual(m.machines["lhd-a"]["_s"],22.5)

    def test_entry_latches_until_resume(self):
        m=Mine()
        command(m,"condition.instability_on","zone-a")
        execute(m,"observe")
        m.advance(150)
        machine=m.machines["lhd-a"]
        self.assertEqual((machine["state"],machine["hold_reason"]),("parked","entry_blocked"))
        self.assertEqual((machine["at_working"],machine["offset_m"]),("w-03",75))
        command(m,"condition.instability_off","zone-a")
        m.advance(10)
        self.assertEqual(machine["offset_m"],75)
        self.assertEqual(command(m,"action.resume_zone","zone-a")["status"],"applied")
        m.advance()
        self.assertGreater(machine["offset_m"],75)

    def test_closure_current_and_next_no_teleport_and_explicit_resume(self):
        for edge in ("w-07","w-03"):
            m=Mine()
            m.advance(60)
            command(m,"condition.close_working",edge)
            execute(m,"withdraw_all")
            m.advance(70)
            machine=m.machines["lhd-a"]
            self.assertEqual(machine["hold_reason"],"path_closed")
            position=(machine["at_working"],machine["offset_m"])
            self.assertEqual(m.metrics()["machines_stuck"],1)
            if edge=="w-07":
                self.assertEqual(position,("w-07",42.5))
                self.assertEqual(m.workers["worker-a4"]["egress_reason"],"current_working_closed")
            command(m,"condition.open_working",edge)
            m.advance(5)
            self.assertEqual((machine["at_working"],machine["offset_m"]),position)

    def test_hazard_while_returning_in_corridor_cannot_enter_zone(self):
        m=Mine()
        m.advance(140)  # Already left the bay, still outside the controlled zone.
        machine=m.machines["lhd-a"]
        self.assertEqual(machine["at_working"],"w-03")
        position=machine["offset_m"]
        command(m,"condition.instability_on","zone-a")
        execute(m,"observe"); m.advance(100)
        self.assertEqual(machine["hold_reason"],"entry_blocked")
        self.assertEqual(machine["offset_m"],position)

    def test_loaded_withdraw_dumps_then_operator_walks(self):
        m=Mine()
        m.advance(60)
        command(m,"action.withdraw_zone","zone-a")
        m.advance(10)
        self.assertEqual(m.workers["worker-a4"]["aboard"],"lhd-a")
        for _ in range(200):
            m.advance()
            if not m.workers["worker-a4"].get("aboard"):
                break
        machine=m.machines["lhd-a"]
        operator=m.workers["worker-a4"]
        self.assertEqual(machine["run_hauled_t"],14)
        self.assertFalse(machine["loaded"])
        self.assertEqual((operator["at_working"],operator["offset_m"]),("w-03",75))
        self.assertNotEqual(m.zones["zone-a"]["withdrawal_state"],"done")
        m.advance(900)
        self.assertEqual(m.zones["zone-a"]["withdrawal_state"],"done")

    def test_stop_without_withdraw_keeps_operator_and_can_resume(self):
        m=Mine()
        command(m,"action.stop_zone","zone-a")
        m.advance(100)
        machine=m.machines["lhd-a"]
        self.assertEqual((machine["activity"],machine["offset_m"]),("idle",75))
        self.assertEqual(m.workers["worker-a4"]["aboard"],"lhd-a")
        self.assertEqual(command(m,"action.resume_zone","zone-a")["status"],"applied")
        m.advance()
        self.assertGreater(machine["offset_m"],75)

    def test_crew_staffing_excludes_operator_and_latches(self):
        m=Mine()
        m.workers["worker-a1"]["status"]="waiting"
        m._refresh()
        self.assertEqual(m.machines["lhd-a"]["hold_reason"],"crew_absent")
        self.assertEqual(m.zones["zone-a"]["production_rate"],0)
        self.assertEqual(command(m,"action.resume_zone","zone-a")["reason"],"insufficient_workers")
        m.workers["worker-a1"]["status"]="working"
        m._refresh()
        self.assertEqual(m.machines["lhd-a"]["state"],"parked")
        command(m,"action.resume_zone","zone-a")
        self.assertEqual(m.machines["lhd-a"]["state"],"working")

    def test_plan_same_options_all_metrics_equal_nonnegative(self):
        for preset in ("p-instability","p-detour","p-trapped","p-sensor"):
            m=Mine()
            command(m,"run.start_preset",preset); m.advance(1000)
            plans={v["forecast_planned_t"] for v in m.forecasts.values()}
            self.assertEqual(len(plans),1)
            self.assertEqual(m.forecasts["observe"]["forecast_conflicts"],0)
            for option in m.forecasts:
                trial=copy.deepcopy(m)
                execute(trial,option); trial.advance(900)
                for k,v in trial.metrics().items():
                    self.assertEqual(v,m.forecasts[option]["forecast_"+k])
                self.assertGreaterEqual(trial.metrics()["production_lost_t"],0)

    def test_paused_heartbeat_and_reset(self):
        m=Mine()
        command(m,"run.start_preset","p-instability"); m.advance(60)
        before=copy.deepcopy(m.machines)
        snapshot(m); m.advance(20); snapshot(m)
        self.assertEqual(m.machines,before)
        execute(m,"withdraw_all"); m.advance(120)
        command(m,"run.reset","shift")
        self.assertTrue(all(e["_phase"]=="loading" and e["run_hauled_t"]==0 for e in m.machines.values()))
        self.assertEqual((m.conflicts,m.conflict_yield_s,m.hauled_t,m.planned_t),(0,0,0,0))

    def test_publication_and_units_no_internal_state(self):
        m=Mine(); twins=snapshot(m)
        self.assertEqual(len(m.attributes["mine"]["manifest"]),38)
        self.assertEqual(len(m.attributes["mine"]["dynamic_ids"]),33)
        scene=twins["shift"]["features"]["scene"]["properties"]["value"]
        self.assertIn("team040.mine:lhd-a",{t["thingId"] for t in scene})
        self.assertEqual(twins["lhd-a"]["features"]["run_hauled_t"]["properties"]["unit"],"t")
        self.assertFalse(any(k.startswith("_") for k in twins["lhd-a"]["features"]))
        self.assertEqual(twins["shift"]["features"]["topology_version"]["properties"]["value"],"t2")
        topics={t for t,_ in mqtt_messages(twins)}
        self.assertTrue({"telemetry/team040.mine/lhd-a","telemetry/team040.mine/lhd-b"}<=topics)

    def test_comparison_key_covers_machine_state(self):
        m=Mine()
        command(m,"condition.instability_on","zone-a")
        key=m.comparison_key
        m.machines["lhd-a"]["_elapsed"]+=1
        m._open_decision()
        self.assertNotEqual(key,m.comparison_key)

    def test_equipment_journal_transition_once_and_no_forecast_events(self):
        m=Mine()
        command(m,"condition.instability_on","zone-a")
        self.assertEqual(len([e for e in m.events if e["code"]=="equipment.hazard_changed"]),1)
        before=copy.deepcopy(m.events)
        m.forecast(); m._refresh()
        self.assertEqual(m.events,before)
        execute(m,"observe"); m.advance(150)
        events=[e for e in m.events if e["code"]=="equipment.state_changed"]
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]["details"]["after"]["hold_reason"],"entry_blocked")
        m._refresh()
        self.assertEqual(len([e for e in m.events if e["code"]=="equipment.state_changed"]),1)

    def test_explicit_persistent_migration_preserves_history_and_dedup(self):
        data=json.loads((FIXTURES/"checkpoint-0.1.json").read_text(encoding="utf-8"))
        old=data["state"]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"model.json"
            path.write_text(json.dumps(data),encoding="utf-8")
            m=Store(path).model
            self.assertEqual(m.run_number,old["run_number"]+1)
            self.assertEqual(m.ledger,old["ledger"])
            self.assertEqual(m.commands,old["commands"])
            self.assertEqual(m.archive[:-1],old["archive"])
            self.assertEqual(m.archive[-1]["completion_reason"],"reset")
            self.assertNotIn("hauled_t",m.archive[-1])
            self.assertEqual(m.publication_seq,old["publication_seq"])
            self.assertGreater(snapshot(m)["shift"]["features"]["publication_seq"]["properties"]["value"],old["publication_seq"])
            self.assertEqual(Store(path).model.run_number,m.run_number)
            self.assertTrue(any(e["code"]=="model.migrated" for e in m.events))
            ack=m.command(dict(command_id="c-"+"a"*32,type="run.reset",target="shift",run="run-0001"))
            self.assertEqual(ack,old["commands"][-1])
            self.assertEqual(m.run_number,old["run_number"]+1)

    def test_lhd_parameter_validation_and_provenance(self):
        for bad in ({"lhd_load_s":.5},{"lhd_dump_s":True},{"lhd_availability":1.1},
                    {"lhd_speed_loaded_m_s":4},{"lhd_clearance_m":0}):
            with self.assertRaises(ValueError): Mine(bad)
        m=Mine()
        entries=m.attributes["mine"]["parameter_registry"]["entries"]
        for k,v in entries.items():
            if k.startswith("lhd_"):
                self.assertEqual(v["value"],m.parameters[k])
                self.assertTrue(v["source_ids"] or "TBD-source" in v["rationale"])
        a=Mine({"lhd_availability":.1}); b=Mine({"lhd_availability":1})
        a.advance(400);b.advance(400)
        self.assertEqual(a.metrics(),b.metrics())


if __name__=="__main__":
    unittest.main()
