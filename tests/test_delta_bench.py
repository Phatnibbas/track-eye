import unittest
from types import SimpleNamespace
from delta_bridge.bench import BenchSession, validate_start, validate_targets


class FakeBenchLink:
    def __init__(self):
        self.quarantined = False
        self.lines = SimpleNamespace(buffer=bytearray())
        self.fd = 1
        self.pending = []
        self.sent = []

    def _write_line(self, cmd):
        self.sent.append(cmd)
        if cmd == "clear":
            self.pending = ["OK CLEAR"]
        elif cmd.startswith("look "):
            self.pending = ["OK MOVE"]

    def send_query(self, cmd):
        self._write_line(cmd)
        if cmd == "status":
            moved = any(c.startswith("look ") for c in self.sent)
            cleared = "clear" in self.sent
            pos = 12.857 if moved else 3
            self.pending = [f"STAT fault={not cleared} queue=0 inflight=-"] + [
                f"STAT n{n} ON IDLE err=NONE homed=1 sw=0 pos={pos} target={pos}" for n in (1, 2, 3)]
        elif cmd == "cfg":
            self.pending = [f"CFG n{n} min=3 max=30" for n in (1, 2, 3)] + ["OK GETCFG"]

    def send_ik(self, *angles):
        self.sent.append("ik 0 0 0")
        self.pending = ["IK az=0.0 tilt=0.0 twist=0.0 -> n1=12.857 n2=12.857 n3=12.857"]

    def receive(self, timeout):
        lines, self.pending = self.pending, []
        return b"\n".join(s.encode() for s in lines), lines


class BenchGateTests(unittest.TestCase):
    def nodes(self):
        return {n: {"online": True, "homed": True, "state": "IDLE", "err": "NONE"} for n in (1, 2, 3)}

    def test_one_shot_clear_precondition_allows_only_idle_homed_nodes(self):
        header = {"fault": True, "queue": 0, "inflight": "-"}
        validate_start(header, self.nodes(), (1, 2, 3))
        for key, value in (("online", False), ("homed", False), ("state", "MOVING"), ("err", "LOST_STEP")):
            nodes = self.nodes()
            nodes[1][key] = value
            with self.assertRaises(ValueError):
                validate_start(header, nodes, (1, 2, 3))

    def test_live_limits_no_leg_clamp(self):
        cfg = {n: {"min": n, "max": 30} for n in (1, 2, 3)}
        validate_targets({n: 12.857 for n in (1, 2, 3)}, cfg, (1, 2, 3))
        with self.assertRaises(ValueError):
            validate_targets({1: 12.857, 2: 12.857, 3: 2}, cfg, (1, 2, 3))

    def test_actual_bench_path_clear_once_ik_then_move_and_report(self):
        from pathlib import Path
        from delta_bridge.ik_validation import FirmwareIKReference
        root = Path(__file__).resolve().parent / "fixtures" / "delta_v1_20261008"
        ref = FirmwareIKReference(root / "spm_ik.py", root / "main.py", root / "neutral.txt")
        cfg = SimpleNamespace(expected_nodes=(1, 2, 3), snapshot_window_s=.5,
                              poll_hz=1000, serial=SimpleNamespace(io_timeout_s=.05, max_line_bytes=512))
        log = []
        session = BenchSession(cfg, lambda **d: log.append(d), 2, .02)
        session.link = FakeBenchLink()
        result = session.neutral(ref, 1, .5, .000501)
        self.assertTrue(result["reported_completion"])
        self.assertFalse(result["physical_motion_verified"])
        self.assertEqual(session.clear_count, 1)
        self.assertEqual(session.link.sent.count("clear"), 1)
        self.assertEqual(sum(c.startswith("look ") for c in session.link.sent), 1)

    def test_no_move_after_failed_clear_or_unsafe_initial_state(self):
        cfg = SimpleNamespace(expected_nodes=(1, 2, 3), snapshot_window_s=.5,
                              poll_hz=1000, serial=SimpleNamespace(io_timeout_s=.01, max_line_bytes=512))
        session = BenchSession(cfg, lambda **d: None, 1, .02)
        session.link = FakeBenchLink()
        old_send = session.link._write_line
        def bad_clear(cmd):
            old_send(cmd)
            if cmd == "clear":
                session.link.pending = ["FAULT rejected"]
        session.link._write_line = bad_clear
        with self.assertRaises(ValueError):
            session.clear_once_if_needed()
        self.assertEqual(session.link.sent.count("clear"), 1)
        self.assertFalse(any(c.startswith("look ") for c in session.link.sent))

    def test_actual_offline_snapshot_blocks_before_clear_and_move(self):
        cfg = SimpleNamespace(expected_nodes=(1, 2, 3), snapshot_window_s=.5,
                              poll_hz=1, serial=SimpleNamespace(io_timeout_s=.05, max_line_bytes=512))
        session = BenchSession(cfg, lambda **d: None, 1, .02)
        session.link = FakeBenchLink()
        old_query = session.link.send_query
        def offline_status(cmd):
            old_query(cmd)
            if cmd == "status":
                session.link.pending = [
                    "STAT fault=True queue=0 inflight=-",
                    "STAT n1 OFF - err=NONE homed=0 sw=0 pos=0 target=0",
                    "STAT n2 ON IDLE err=NONE homed=1 sw=0 pos=1.993 target=1.993",
                    "STAT n3 OFF - err=NONE homed=0 sw=0 pos=0 target=0"]
        session.link.send_query = offline_status
        with self.assertRaises(ValueError):
            session.neutral(None, 3000, 12, .000501)
        self.assertEqual(session.link.sent, ["status"])
        self.assertEqual(session.clear_count, 0)
        self.assertFalse(session.move_attempted)


if __name__ == "__main__":
    unittest.main()
