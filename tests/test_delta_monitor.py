import os
from pathlib import Path
import select
import tempfile
import threading
import unittest

from delta_bridge.config import MonitorConfig, SerialPolicy
from tools.delta_master_monitor import monitor


@unittest.skipUnless(os.name == "posix", "Linux PTY end-to-end monitor tests")
class FakeMasterTests(unittest.TestCase):
    def exercise(self, response):
        import pty
        master, slave = pty.openpty()
        config = MonitorConfig(SerialPolicy(os.ttyname(slave), 115200, .03, 512),
                               (1, 2, 3), .2, .2, 100)
        stop = threading.Event()
        sent = []
        errors = []

        def fake():
            buf = bytearray()
            try:
                while not stop.is_set():
                    ready, _, _ = select.select([master], [], [], .02)
                    if ready:
                        buf.extend(os.read(master, 4096))
                        while b"\n" in buf:
                            line, _, tail = buf.partition(b"\n")
                            buf[:] = tail
                            sent.append(bytes(line))
                            os.write(master, response)
            except OSError as exc:
                if not stop.is_set():
                    errors.append(str(exc))

        worker = threading.Thread(target=fake)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "audit.jsonl"
                result = monitor(config, 1.2, path)
                artifact = path.read_text(encoding="utf-8")
            self.assertEqual(errors, [])
            self.assertEqual(set(sent), {b"status"})
            self.assertFalse(result["motion_tx"])
            return result, artifact, sent
        finally:
            stop.set()
            worker.join(timeout=1)
            os.close(master)
            os.close(slave)

    def test_complete_fake_status_exchange(self):
        response = b"STAT fault=False queue=0 inflight=-\n" + b"".join(
            f"STAT n{n} ON IDLE err=NONE homed=1 sw=0 pos=12 target=12\n".encode()
            for n in (1, 2, 3))
        result, artifact, sent = self.exercise(response)
        self.assertIsNone(result["error"])
        self.assertIn('"status_ready": true', artifact)

    def test_repl_aborts_without_retries(self):
        result, artifact, sent = self.exercise(b">>> ")
        self.assertIsNotNone(result["error"])
        self.assertEqual(len(sent), 1)
        self.assertIn('"status_ready": false', artifact)

    def test_corrupt_bytes_recorded_and_aborted(self):
        result, artifact, sent = self.exercise(b"\xff\n")
        self.assertIsNotNone(result["error"])
        self.assertEqual(len(sent), 1)
        self.assertIn('"last_rx_hex": "ff0a"', artifact)


if __name__ == "__main__":
    unittest.main()
