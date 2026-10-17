import json
import os
from pathlib import Path
import tempfile
import unittest

from delta_bridge.config import SerialPolicy, load_config, load_monitor_config
from delta_bridge.serial_transport import TextLines, ReadOnlySerial, SerialProtocolError


class FramingTests(unittest.TestCase):
    def test_split_coalesced_crlf(self):
        p = TextLines(30)
        self.assertEqual(p.feed(b"STA"), [])
        self.assertEqual(p.feed(b"T ok\r\nOK\n"), ["STAT ok", "OK"])

    def test_overflow_and_bad_bytes(self):
        for value in (b"12345", b"\xff\n", b"\x03\n"):
            with self.assertRaises(SerialProtocolError):
                TextLines(4).feed(value)

    def test_vietnamese_diagnostic_across_chunks(self):
        p = TextLines(80)
        data = "WARN mất kết nối\n".encode("utf-8")
        result = []
        for byte in data:
            result.extend(p.feed(bytes([byte])))
        self.assertEqual(result, ["WARN mất kết nối"])


class ConfigTests(unittest.TestCase):
    def fixture(self):
        return {"schema_version": 1, "mode": "dry-run", "expected_nodes": [1, 2, 3],
                "snapshot_window_s": .5, "status_max_age_s": 1, "frame_max_age_s": .2,
                "poll_hz": 10, "status_url": "http://localhost/status.json",
                "serial": {"device": "test-only", "baud": 115200, "io_timeout_s": 1, "max_line_bytes": 512},
                "mapping": {"slot": "right", "max_tilt_deg": 3, "az_offset_deg": 90,
                            "x_sign": -1, "y_sign": 1, "twist_deg": 0, "duration_ms": 200}}

    def load(self, d):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "fixture.json"
            p.write_text(json.dumps(d), encoding="utf-8")
            return load_config(p)

    def test_explicit_config(self):
        c = self.load(self.fixture())
        self.assertEqual(c.mapping.x_sign, -1)
        self.assertEqual(c.expected_nodes, (1, 2, 3))

    def test_missing_unknown_motion_nonfinite_bool(self):
        for key, value in (("mode", "emit"), ("poll_hz", True), ("snapshot_window_s", float("nan")),
                           ("poll_hz", 10 ** 500), ("surprise", 1)):
            d = self.fixture()
            d[key] = value
            with self.assertRaises(ValueError):
                self.load(d)
        d = self.fixture()
        del d["mapping"]["y_sign"]
        with self.assertRaises(ValueError):
            self.load(d)

    def test_templates_are_intentionally_not_deployable(self):
        root = Path(__file__).resolve().parent.parent
        with self.assertRaises(ValueError):
            load_config(root / "config" / "delta-bridge.template.json")
        with self.assertRaises(ValueError):
            load_monitor_config(root / "config" / "delta-monitor.template.json")

    def test_duplicate_config_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.json"
            p.write_text('{"mode":"dry-run","mode":"emit"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(p)


@unittest.skipUnless(os.name == "posix", "Linux PTY/termios transport tests")
class PtyTests(unittest.TestCase):
    def setUp(self):
        import pty
        self.master, slave = pty.openpty()
        self.transport = ReadOnlySerial(SerialPolicy(os.ttyname(slave), 115200, .2, 256))
        self.transport.open()
        os.close(slave)

    def tearDown(self):
        self.transport.close()
        if self.master is not None:
            os.close(self.master)

    def test_read_query_and_reject_motion(self):
        self.transport.send_query("status")
        self.assertEqual(os.read(self.master, 256), b"status\n")
        for command in ("look 0 0 0 200", "home", "clear", "status\nlook 0 0"):
            with self.assertRaises(ValueError):
                self.transport.send_query(command)
        os.write(self.master, b"STAT fault=False queue=0 inflight=-\n")
        raw, lines = self.transport.receive(.2)
        self.assertTrue(raw)
        self.assertEqual(lines, ["STAT fault=False queue=0 inflight=-"])

    def test_partial_repl_quarantines(self):
        os.write(self.master, b">>")
        self.transport.receive(.2)
        os.write(self.master, b"> ")
        self.transport.receive(.2)
        with self.assertRaises(RuntimeError):
            self.transport.send_query("status")

    def test_unterminated_traceback_quarantines(self):
        os.write(self.master, b"Trace")
        self.transport.receive(.2)
        os.write(self.master, b"back (most recent")
        self.transport.receive(.2)
        self.assertTrue(self.transport.quarantined)

    def test_disconnect_and_invalid_bytes_quarantine(self):
        os.write(self.master, b"\xff\n")
        with self.assertRaises(SerialProtocolError):
            self.transport.receive(.2)
        self.assertTrue(self.transport.quarantined)

    def test_device_removed(self):
        os.close(self.master)
        self.master = None
        with self.assertRaises((ConnectionError, OSError)):
            self.transport.receive(.2)
        self.assertTrue(self.transport.quarantined)

    def test_second_open_rejected(self):
        other = ReadOnlySerial(self.transport.policy)
        with self.assertRaises(OSError):
            other.open()
        other.close()


if __name__ == "__main__":
    unittest.main()
