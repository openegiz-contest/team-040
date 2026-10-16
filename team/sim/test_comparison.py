import unittest

from .comparison import experiment, OPTIONS


class ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = experiment()
        cls.scenarios = {s["preset"]: s for s in cls.report["scenarios"]}

    def test_complete_matrix_same_inputs_and_conservation(self):
        self.assertEqual(len(self.scenarios), 4)
        for scenario in self.scenarios.values():
            self.assertEqual([row["option"] for row in scenario["rows"]], list(OPTIONS))
            for row in scenario["rows"]:
                self.assertEqual(row["comparison_key"], scenario["comparison_key"])
                self.assertEqual(row["finished_at_sim_s"], scenario["decision_tick"] + 900)
                self.assertEqual(len(row["workers"]), 8)
                self.assertEqual(row["actual"]["out"], sum(w["status"] == "out" for w in row["workers"].values()))
                self.assertEqual("last_out_s" in row["actual"], row["actual"]["all_out"])
                self.assertTrue(row["forecast_matches_actual"])

    def test_local_withdrawal_keeps_unaffected_production(self):
        rows = self.scenarios["p-instability"]["rows"]
        observe, local, all_workers = rows
        self.assertEqual(local["target_zones"], ["zone-a"])
        self.assertEqual(local["actual"]["out"], 4)
        self.assertAlmostEqual(local["zones"]["zone-b"]["production_rate"], 14 * 3600 / 179)
        self.assertEqual(local["zones"]["zone-a"]["production_rate"], 0)
        self.assertEqual(local["actual"]["danger_exposure_person_s"], all_workers["actual"]["danger_exposure_person_s"])
        self.assertLess(local["actual"]["danger_exposure_person_s"], observe["actual"]["danger_exposure_person_s"])
        self.assertEqual(all_workers["actual"]["downtime_s"], 2 * local["actual"]["downtime_s"])
        self.assertIsNotNone(local["target_out_s"])
        self.assertNotIn("last_out_s", local["actual"])

    def test_closures_only_withdraw_affected_zone(self):
        for preset in ("p-detour", "p-trapped"):
            scenario = self.scenarios[preset]
            self.assertEqual(scenario["scope"], ["zone-a"])
            local, full = scenario["rows"][1:]
            self.assertAlmostEqual(local["zones"]["zone-b"]["production_rate"], 14 * 3600 / 179)
            self.assertEqual(local["actual"]["downtime_s"], 900)
            self.assertEqual(full["actual"]["downtime_s"], 1800)
        self.assertEqual(self.scenarios["p-detour"]["rows"][1]["actual"]["out"], 4)
        self.assertEqual(self.scenarios["p-trapped"]["rows"][1]["actual"]["out"], 0)
        for row in self.scenarios["p-trapped"]["rows"]:
            self.assertEqual(row["actual"]["no_route"], 4)
            self.assertFalse(row["actual"]["all_out"])
            for index in range(1, 4):
                worker = row["workers"][f"worker-a{index}"]
                self.assertEqual(worker["at_working"], "w-07")
                self.assertEqual(worker["offset_m"], index * 20)

    def test_sensor_uncertainty_is_not_zero_risk(self):
        scenario = self.scenarios["p-sensor"]
        self.assertGreater(scenario["decision_tick"], scenario["event_tick"])
        self.assertEqual(scenario["rows"][0]["actual"]["unknown_exposure_person_s"], 3 * 900 + 3)
        for row in scenario["rows"]:
            self.assertEqual(row["forecast"]["forecast_quality"], "partial")
            self.assertEqual(row["actual"]["danger_exposure_person_s"], 0)
            self.assertGreater(row["actual"]["unknown_exposure_person_s"], 0)


if __name__ == "__main__":
    unittest.main()
