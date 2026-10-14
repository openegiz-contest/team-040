import unittest

from .model import Mine
from .parameters import PARAMETERS, SOURCES
from .test_model import command


class ParameterTests(unittest.TestCase):
    def test_registry_matches_applied_values_and_metadata_after_reset(self):
        mine = Mine({"walking_speed_m_s": 0.75, "stale_after_s": 12})
        command(mine, "run.reset", "shift")
        registry = mine.attributes["mine"]["parameter_registry"]
        self.assertFalse(registry["calibrated"])
        self.assertEqual({k: e["value"] for k, e in registry["entries"].items()}, mine.parameters)
        self.assertEqual(mine.attributes["sens-ext-a"]["stale_after_s"], 12)
        self.assertAlmostEqual(SOURCES["escape1983"]["converted_m_s"][0], 96 * 0.3048 / 60)
        self.assertAlmostEqual(SOURCES["escape1983"]["converted_m_s"][1], 264 * 0.3048 / 60)
        self.assertEqual(set(registry["entries"]), set(PARAMETERS))

    def test_invalid_parameters_are_rejected_before_run(self):
        for settings in ({"walking_speed_m_s": 0}, {"walking_speed_m_s": float("nan")},
                         {"walking_speed_m_s": float("inf")}, {"speedup": True},
                         {"danger_rate_mm_h": 0.5}, {"stale_after_s": 40},
                         {"forecast_horizon_s": 1.5}, {"unknown": 2}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                Mine(settings)


if __name__ == "__main__":
    unittest.main()
