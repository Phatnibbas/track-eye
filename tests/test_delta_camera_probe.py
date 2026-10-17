import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from delta_bridge.ik_validation import FirmwareIKReference
from tools import delta_camera_ik_probe as probe


class FakeLink:
    def __init__(self, policy, malformed_echo=False, reboot_reply=False):
        self.policy = policy
        self.quarantined = False
        self.last_rx = b""
        self.lines = type("Lines", (), {"buffer": bytearray()})()
        self.pending = []
        self.commands = []
        self.status_queries = 0
        self.malformed_echo = malformed_echo
        self.reboot_reply = reboot_reply
        root = Path(__file__).resolve().parent / "fixtures" / "delta_v1_20261008"
        self.ref = FirmwareIKReference(root / "spm_ik.py", root / "main.py", root / "neutral.txt")

    def open(self):
        pass

    def close(self):
        pass

    def send_query(self, cmd):
        assert cmd == "status"
        self.commands.append(cmd)
        self.status_queries += 1
        if self.status_queries == 1:
            self.pending = ["FAULT testSTAT fault=True queue=0 inflight=-"]
        else:
            self.pending = ["STAT fault=True queue=0 inflight=-"] + [
                f"STAT n{n} ON IDLE err=NONE homed=0 sw=0 pos=0 target=0" for n in (1, 2, 3)]

    def send_ik(self, *polar):
        self.commands.append(("ik", *polar))
        if self.reboot_reply:
            self.pending = ["EVT n1 BOOT fw=1 reset=HARD_RESET"]
            return
        wire = tuple(float(f"{v:.3f}") for v in polar)
        motors = self.ref.targets(wire)
        if self.malformed_echo:
            wire = (wire[0] + 1, *wire[1:])
        self.pending = [f"IK az={wire[0]} tilt={wire[1]} twist={wire[2]} -> " +
                        " ".join(f"n{n}={v:.3f}" for n, v in motors.items())]

    def receive(self, timeout):
        if not self.pending:
            return b"", []
        lines, self.pending = self.pending, []
        return ("\n".join(lines) + "\n").encode(), lines


class CameraProbeTests(unittest.TestCase):
    def run_probe(self, **flags):
        root = Path(__file__).resolve().parent.parent
        cfg = json.loads((root / "config" / "delta-camera-ik.validation-20261008.json").read_text())
        cfg["serial"]["io_timeout_s"] = .001
        cfg["poll_hz"] = 1000
        status = {"healthy": True, "capture_alive": True, "face_detected": True,
                  "last_frame_age_seconds": .01, "baseline": {"state": "idle"},
                  "output_left": {"x": .3, "y": -.6}, "frame_sequence": 1,
                  "output_tuning": {"calibration": {"gain": {"soft_limit": 1.5}}}}
        with tempfile.TemporaryDirectory() as tmp:
            config, out = Path(tmp) / "config.json", Path(tmp) / "out.jsonl"
            config.write_text(json.dumps(cfg))
            argv = ["probe", "--config", str(config), "--seconds", ".2", "--out", str(out),
                    "--reference-dir", str(root / "tests/fixtures/delta_v1_20261008"), "--tolerance-deg", ".000501",
                    "--status-sync-attempts", "2"]
            link = FakeLink(probe.load_config(config).serial, **flags)
            with patch.object(probe, "ReadOnlySerial", return_value=link), \
                    patch.object(probe.urllib.request, "urlopen", side_effect=lambda *a, **kw: io.StringIO(json.dumps(status))), \
                    patch.object(probe.sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                code = probe.main()
            return code, link, [json.loads(s) for s in out.read_text().splitlines()]

    def test_merged_header_not_repaired_and_fault_ik_is_not_motion(self):
        code, link, rows = self.run_probe()
        self.assertEqual(code, 0)
        self.assertEqual(link.status_queries, 2)
        self.assertTrue(any(r.get("match") is True for r in rows))
        self.assertTrue(any(r.get("motion_ready") is False for r in rows))
        self.assertFalse(any(r.get("motion_tx") for r in rows))
        self.assertTrue(all(cmd == "status" or cmd[0] == "ik" for cmd in link.commands))

    def test_wrong_echo_aborts(self):
        code, _link, rows = self.run_probe(malformed_echo=True)
        self.assertEqual(code, 1)
        self.assertTrue(any("echoed" in r.get("error", "") for r in rows))

    def test_node_reboot_during_probe_aborts(self):
        code, _link, rows = self.run_probe(reboot_reply=True)
        self.assertEqual(code, 1)
        self.assertTrue(any("BOOT" in r.get("error", "") for r in rows))


if __name__ == "__main__":
    unittest.main()
