import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from delta_bridge.config import MonitorConfig, SerialPolicy
from delta_bridge.ik_validation import FirmwareIKReference
from tools.delta_protocol_audit import drain_diagnostics, load_campaign, run, vectors
from delta_bridge.serial_transport import TextLines, SerialProtocolError
from test_delta_camera_probe import FakeLink


class AuditTests(unittest.TestCase):
    def campaign(self):
        return {"schema_version": 1, "rate_hz": 1000, "queries_per_session": 6,
                "sessions": 1, "reopen_pause_s": .001, "sync_attempts": 2,
                "seed": 7, "tilt_min_deg": 0, "tilt_max_deg": 2,
                "twist_deg": 0, "ik_tolerance_deg": .000501}

    def exercise(self, wrong_echo=False, stale=False):
        root = Path(__file__).resolve().parent / "fixtures" / "delta_v1_20261008"
        ref = FirmwareIKReference(root / "spm_ik.py", root / "main.py", root / "neutral.txt")
        cfg = MonitorConfig(SerialPolicy("fake", 115200, .03, 512), (1, 2, 3), .5, 1, 1)
        link = FakeLink(cfg.serial, malformed_echo=wrong_echo)
        if stale:
            original_ik = link.send_ik
            def altered_ik(*polar):
                original_ik(*polar)
                link.pending[0] = "FAULT node" + link.pending[0]
            link.send_ik = altered_ik
        with tempfile.TemporaryDirectory() as tmp:
            out, summary = Path(tmp) / "rx.jsonl", Path(tmp) / "summary.json"
            with patch("tools.delta_protocol_audit.ReadOnlySerial", return_value=link):
                result = run(cfg, self.campaign(), ref, out, summary)
            rows = [json.loads(x) for x in out.read_text().splitlines()]
            self.assertEqual(result, json.loads(summary.read_text()))
        return result, link, rows

    def test_faulted_nodes_do_not_prevent_computation_only_proof(self):
        result, link, rows = self.exercise()
        self.assertEqual(result["verified_replies"], 6)
        self.assertEqual(result["protocol_failures"], [])
        self.assertTrue(all(cmd == "status" or cmd[0] == "ik" for cmd in link.commands))
        self.assertFalse(result["motion_tx"])

    def test_wrong_echo_stops_on_first_command_no_reopen(self):
        result, link, rows = self.exercise(wrong_echo=True)
        self.assertEqual(result["verified_replies"], 0)
        self.assertEqual(result["sessions"][0]["queries_sent"], 1)
        self.assertEqual(len(result["protocol_failures"]), 1)

    def test_merged_reply_not_repaired(self):
        result, link, rows = self.exercise(stale=True)
        self.assertEqual(result["verified_replies"], 0)

    def test_campaign_vectors_reproducible_and_no_defaults(self):
        campaign = self.campaign()
        self.assertEqual(vectors(campaign), vectors(campaign))
        self.assertEqual([v[0] for v in vectors(campaign)[:5]], [0, 90, 180, 270, 360])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.json"
            p.write_text(json.dumps(campaign))
            self.assertEqual(load_campaign(p), campaign)
            campaign.pop("rate_hz")
            p.write_text(json.dumps(campaign))
            with self.assertRaises(ValueError):
                load_campaign(p)

    def test_drain_finishes_fragmented_utf8_robot_diagnostic(self):
        class Stream:
            quarantined = False
            lines = TextLines(512)
            data = ["WARN STOP tất c".encode(), "ả\r\n".encode(), b""]
            def receive(self, timeout):
                raw = self.data.pop(0)
                return raw, self.lines.feed(raw)
        records = []
        link = Stream()
        drain_diagnostics(link, .1, lambda raw, lines: records.extend(lines))
        self.assertEqual(records, ["WARN STOP tất cả"])
        self.assertEqual(link.lines.buffer, b"")

    def test_drain_timeout_and_stale_ik_are_not_repaired(self):
        class Stream:
            quarantined = False
            def __init__(self, data):
                self.lines = TextLines(512)
                self.data = data
            def receive(self, timeout):
                raw, self.data = self.data, b""
                return raw, self.lines.feed(raw)
        with self.assertRaises(TimeoutError):
            drain_diagnostics(Stream(b"WARN partial"), .001, lambda *args: None)
        with self.assertRaises(SerialProtocolError):
            drain_diagnostics(Stream(b"IK az=0 tilt=0 twist=0 -> n1=1\n"), .1, lambda *args: None)


if __name__ == "__main__":
    unittest.main()
