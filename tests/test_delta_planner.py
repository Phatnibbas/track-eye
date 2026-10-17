import unittest

from delta_bridge.core import Mapping, MasterState
from delta_bridge.planner import PlannerPolicy, ProposalPlanner


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.planner = ProposalPlanner(Mapping("right", 5, 0, 1, -1, 0, 150),
                                       PlannerPolicy(.2, .2, .3, 10))
        self.master = MasterState((1, 2, 3), .1)

    def ready(self, now):
        self.master.consume("STAT fault=False queue=0 inflight=-", now)
        for n in (1, 2, 3):
            self.master.consume(f"STAT n{n} ON IDLE err=NONE homed=1 sw=0 pos=0 target=0", now)

    def sample(self, seq=1, x=0, uptime=1, **extra):
        return dict(frame_sequence=seq, uptime_seconds=uptime,
                    healthy=True, capture_alive=True, face_detected=True,
                    last_frame_age_seconds=.01, baseline={"state": "idle"},
                    output_right={"x": x, "y": 0},
                    output_tuning={"calibration": {"gain": {"soft_limit": 1}}}, **extra)

    def test_latest_only_and_rate_limit(self):
        self.ready(1)
        self.planner.observe(self.sample(1, .1), 1)
        self.assertIsNotNone(self.planner.propose(self.master, 1))
        self.planner.observe(self.sample(2, .2), 1.01)
        self.assertIsNone(self.planner.propose(self.master, 1.02))
        self.planner.observe(self.sample(3, .3), 1.03)
        self.assertEqual(self.planner.superseded, 1)
        command = self.planner.propose(self.master, 1.11)
        self.assertIn("1.500", command)
        self.assertIsNone(self.planner.propose(self.master, 1.12))

    def test_duplicate_does_not_refresh_local_age(self):
        self.ready(1.2)
        self.planner.observe(self.sample(), 1.2)
        self.planner.observe(self.sample(uptime=2), 1.39)
        self.assertIsNone(self.planner.propose(self.master, 1.41))
        self.assertEqual(self.planner.reason, "locally stale target")

    def test_fault_discards_and_no_resume_without_new_frame(self):
        self.ready(1)
        self.planner.observe(self.sample(), 1)
        self.master.consume("FAULT test", 1.01)
        self.assertIsNone(self.planner.propose(self.master, 1.01))
        self.ready(1.02)
        self.assertIsNone(self.planner.propose(self.master, 1.02))
        self.planner.observe(self.sample(), 1.03)
        self.assertIsNone(self.planner.propose(self.master, 1.03))

    def test_restart_counter_clock_and_invalid_clears(self):
        self.ready(1)
        self.planner.observe(self.sample(10, .1, 10), 1)
        self.planner.observe(self.sample(1, .2, 1), 1.01)
        self.assertIsNone(self.planner.propose(self.master, 1.02))
        self.planner.observe(self.sample(2, .3, 2), 1.03)
        self.assertIsNotNone(self.planner.propose(self.master, 1.04))
        self.planner.observe(self.sample(3, .3, 3), 1.05)
        self.assertIsNone(self.planner.propose(self.master, .5))
        self.planner.observe(None, 1.06)
        self.assertIsNone(self.planner.propose(self.master, 1.06))

    def test_shadow_never_promoted_and_master_stale(self):
        self.ready(1)
        status = self.sample()
        status["face_detected"] = False
        status["fallback"] = {"shadow_target_right": [1, 1]}
        self.planner.observe(status, 1)
        self.assertIsNone(self.planner.propose(self.master, 1))
        self.planner.observe(self.sample(2, .2), 1.3)
        self.assertIsNone(self.planner.propose(self.master, 1.31))


if __name__ == "__main__":
    unittest.main()
