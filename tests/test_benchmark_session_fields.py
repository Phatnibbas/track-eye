import unittest
from types import SimpleNamespace

from benchmark_utils import SessionBenchmarkLogger


class BenchmarkSessionFieldsTests(unittest.TestCase):
    def test_logger_persists_session_state_and_vertical_mode(self):
        estimate = SimpleNamespace(
            eyes=[],
            x_ctrl=0.0,
            y_ctrl=0.0,
            raw_x=0.0,
            raw_y=0.0,
            x_eye=0.0,
            y_eye=0.0,
            confidence=0.0,
            y_confidence=0.0,
            vertical_reliability=0.0,
            output_source="hold",
            pose_valid=False,
            head_pose_enabled=False,
            yaw_deg=0.0,
            pitch_deg=0.0,
            head_pose_x=0.0,
            head_pose_y=0.0,
            face_detected=False,
            valid=False,
            message="No face detected",
        )
        logger = SessionBenchmarkLogger(
            log_path=None,
            summary_path=None,
            confidence_dropout_threshold=0.35,
        )

        logger.log_frame(
            frame_index=1,
            elapsed_s=0.1,
            fps=30.0,
            protocol_label="center_hold",
            estimate=estimate,
            session_state="idle",
            session_ready=False,
            session_reason="waiting_for_user",
            vertical_feature_mode="current",
        )

        record = logger.records[0]
        self.assertEqual(record["session_state"], "idle")
        self.assertFalse(record["session_ready"])
        self.assertEqual(record["session_reason"], "waiting_for_user")
        self.assertEqual(record["vertical_feature_mode"], "current")


if __name__ == "__main__":
    unittest.main()
