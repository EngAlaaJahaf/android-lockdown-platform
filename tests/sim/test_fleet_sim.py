"""Fleet simulator tests — staged rollout behavior only, never device truth."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for sub in ("backend",):
    sys.path.insert(0, os.path.join(ROOT, sub))

from backend import fleet


class TestSimulatorRollout(unittest.TestCase):
    def test_generates_n_devices(self):
        sim = fleet.FleetSimulator(n=100)
        devs = sim.generate()
        self.assertEqual(len(devs), 100)
        self.assertEqual(len({d["device_id"] for d in devs}), 100)
        self.assertTrue(all(7 <= d["android_version"] <= 15 for d in devs))

    def test_waves_are_tiny_first(self):
        r = fleet.simulate_bulk("POL-FULL_LOCKDOWN", n=50)
        self.assertEqual(r["total_devices"], 50)
        sizes = [w["devices"] for w in r["waves"]]
        self.assertEqual(sizes[0], 5)          # §86: 5 devices first
        self.assertEqual(sizes[1], 20)
        if r["stage"] == "FULL":
            self.assertEqual(sizes[2], 25)

    def test_reproducible_seed(self):
        a = fleet.FleetSimulator(n=20, seed=3).generate()
        b = fleet.FleetSimulator(n=20, seed=3).generate()
        self.assertTrue(all(x == y for x, y in zip(a, b)))

    def test_full_stage_reaches_all(self):
        r = fleet.simulate_bulk("POL-QUARANTINE", n=500)
        if r["stage"] == "FULL":
            seen = sum(w["devices"] for w in r["waves"])
            self.assertEqual(seen, 500)


if __name__ == "__main__":
    unittest.main()