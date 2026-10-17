import math
import unittest

from delta_bridge.core import Mapping, MasterState, production_target


def mapping():
    # Synthetic test fixture, not installed rig calibration.
    return Mapping("left", 5, 0, 1, -1, 0, 150)


def state():
    return MasterState((1, 2, 3), .5)


class MappingTests(unittest.TestCase):
    def test_neutral_axes_diagonal_cap(self):
        m = mapping()
        self.assertEqual(m.command(0, 0), "look 0.000 0.000 0.000 150\n")
        self.assertEqual(m.command(1, 0), "look 0.000 5.000 0.000 150\n")
        self.assertEqual(m.command(0, -1), "look 90.000 5.000 0.000 150\n")
        self.assertEqual(m.command(1, 1), "look 315.000 5.000 0.000 150\n")

    def test_reject_bad_inputs(self):
        for slot, tilt in (("average", 5), ("left", math.nan), ("left", 0)):
            with self.assertRaises(ValueError):
                Mapping(slot, tilt, 0, 1, -1, 0, 150)
        for v in (math.nan, math.inf, 1.1, True, "1"):
            with self.assertRaises(ValueError):
                mapping().command(v, 0)

    def test_no_implicit_rig_defaults(self):
        with self.assertRaises(TypeError):
            Mapping("left", 5)
        m = Mapping("right", 20, 45, -1, 1, 2, 900)
        self.assertEqual(m.command(-1, 0), "look 45.000 20.000 2.000 900\n")

    def test_production_only_and_normalization(self):
        s = dict(healthy=True, capture_alive=True, face_detected=True,
                 last_frame_age_seconds=.1, baseline={"state": "idle"},
                 output_left={"x": .75, "y": -.3},
                 output_tuning={"calibration": {"gain": {"soft_limit": 1.5}}})
        self.assertEqual(production_target(s, mapping(), .25), (.5, -.19999999999999998))
        s["face_detected"] = False
        s["fallback"] = {"shadow_target_left": [1, 1]}
        self.assertIsNone(production_target(s, mapping(), .25))

    def test_stale_invalid_and_baseline_block(self):
        s = dict(healthy=True, capture_alive=True, face_detected=True,
                 last_frame_age_seconds=.3, baseline={"state": "idle"})
        self.assertIsNone(production_target(s, mapping(), .25))
        s["last_frame_age_seconds"] = math.nan
        self.assertIsNone(production_target(s, mapping(), .25))
        s["last_frame_age_seconds"] = .1
        s["baseline"] = None
        self.assertIsNone(production_target(s, mapping(), .25))
        s["baseline"] = {"state": "running"}
        self.assertIsNone(production_target(s, mapping(), .25))
        self.assertIsNone(production_target([], mapping(), .25))


class StateTests(unittest.TestCase):
    def fill(self, s):
        s.consume("STAT fault=False queue=0 inflight=-", 1)
        for n in (1, 2, 3):
            s.consume(f"STAT n{n} ON IDLE err=NONE homed=1 sw=0 pos=12.857 target=12.857", 1 + .01 * n)

    def test_default_partial_and_ok_not_ready(self):
        s = state()
        self.assertFalse(s.ready(1, .5))
        s.consume("OK MOVE", 1)
        self.assertFalse(s.ready(1, .5))
        s.consume("STAT fault=False queue=0 inflight=-", 1)
        s.consume("STAT n1 ON IDLE err=NONE homed=1 sw=0 pos=12 target=12", 1.1)
        self.assertFalse(s.ready(1.1, .5))

    def test_ready_fresh_and_reconnect(self):
        s = state()
        self.fill(s)
        self.assertTrue(s.ready(1.1, .5))
        self.assertFalse(s.ready(2, .5))
        self.assertFalse(s.ready(math.nan, .5))
        s.reset()
        self.assertFalse(s.ready(1.1, .5))

    def test_fault_repl_reboot_block(self):
        for line in ("FAULT lost", ">>>", "Traceback (most recent call last):", "EVT n1 BOOT fw=1 reset=POWER_ON", "ERR n1 OFFLINE"):
            s = state()
            self.fill(s)
            s.consume(line, 1.1)
            self.assertFalse(s.ready(1.1, .5))

    def test_unhomed_malformed_duplicate_unknown_block(self):
        for line in ("STAT n2 ON IDLE err=NONE homed=0 sw=0 pos=0 target=0", "STAT n2 broken",
                     "STAT n1 ON IDLE err=NONE homed=1 sw=0 pos=0 target=0",
                     "STAT n9 ON IDLE err=NONE homed=1 sw=0 pos=0 target=0"):
            s = state()
            s.consume("STAT fault=False queue=0 inflight=-", 1)
            for n in (1, 2, 3):
                s.consume(line if n == 2 else f"STAT n{n} ON IDLE err=NONE homed=1 sw=0 pos=0 target=0", 1.1)
            self.assertFalse(s.ready(1.2, .5))

    def test_configured_nodes_and_window(self):
        s = MasterState((7,), .05)
        s.consume("STAT fault=False queue=0 inflight=-", 1)
        s.consume("STAT n7 ON IDLE err=NONE homed=1 sw=0 pos=0 target=0", 1.01)
        self.assertTrue(s.ready(1.02, .1))
        s.consume("STAT fault=False queue=0 inflight=-", 2)
        s.consume("STAT n7 ON IDLE err=NONE homed=1 sw=0 pos=0 target=0", 2.1)
        self.assertFalse(s.ready(2.1, .1))

    def test_real_master_offline_unknown_state_is_not_malformed(self):
        # Master prints '-' when it has never received this node's state.
        s = state()
        s.consume("STAT fault=False queue=0 inflight=-", 1)
        s.consume("STAT n1 OFF -        err=NONE           homed=0 sw=0 pos=   0.000 target=   0.000", 1.01)
        for n in (2, 3):
            s.consume(f"STAT n{n} ON  IDLE     err=NONE           homed=0 sw=0 pos=   0.000 target=   0.000", 1.02)
        self.assertEqual(s.nodes, {1: False, 2: False, 3: False})
        self.assertEqual(s.reason, "node not ready")
        self.assertFalse(s.ready(1.1, .5))


if __name__ == "__main__":
    unittest.main()
