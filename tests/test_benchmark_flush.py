import json
import tempfile
import unittest
from pathlib import Path

from benchmark_utils import SessionBenchmarkLogger
from gaze_estimator import EstimateResult


class BenchmarkFlushTests(unittest.TestCase):
    def test_log_frame_is_visible_on_disk_before_finalize(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "session.jsonl"
            logger = SessionBenchmarkLogger(
                log_path=path,
                summary_path=None,
                confidence_dropout_threshold=0.35,
            )

            try:
                logger.log_frame(
                    frame_index=0,
                    elapsed_s=0.0,
                    fps=30.0,
                    protocol_label="none",
                    estimate=EstimateResult.empty("test"),
                )

                lines = path.read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(lines), 1)
                self.assertEqual(json.loads(lines[0])["protocol_label"], "none")
            finally:
                logger.finalize([])


if __name__ == "__main__":
    unittest.main()
