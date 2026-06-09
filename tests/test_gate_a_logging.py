import unittest
from dataclasses import fields
from types import SimpleNamespace

from benchmark_utils import SessionBenchmarkLogger
from gaze_estimator import EyeMeasurement


def _eye(name: str, horizontal: float, vertical: float) -> EyeMeasurement:
    eye = EyeMeasurement(
        name=name,
        contour=[],
        corners=((0, 0), (20, 0)),
        top=(10, -3),
        bottom=(10, 3),
        iris_center=(10, 1),
        iris_points=[(9, 1), (10, 0), (11, 1), (10, 2)],
        horizontal=horizontal,
        vertical=vertical,
        iris_vertical_raw=1.25,
        vertical_prebaseline=vertical + 0.10,
        local_u=(1.0, 0.0),
        local_v=(0.0, 1.0),
        vertical_eyelid_relative=0.11,
        vertical_orbital_relative=0.22,
        iris_ring_vertical_asymmetry=0.33,
        openness=0.30,
        width=20.0,
        height=6.0,
        iris_radius=2.0,
        min_clearance_x=0.20,
        min_clearance_y=0.10,
        quality=0.80,
        tracked=True,
    )
    return eye


class GateALoggingTests(unittest.TestCase):
    def test_eye_measurement_declares_raw_vertical_tap_fields(self):
        names = {field.name for field in fields(EyeMeasurement)}

        self.assertIn("iris_vertical_raw", names)
        self.assertIn("vertical_prebaseline", names)
        self.assertIn("local_u", names)
        self.assertIn("local_v", names)
        self.assertIn("vertical_eyelid_relative", names)
        self.assertIn("vertical_orbital_relative", names)
        self.assertIn("iris_ring_vertical_asymmetry", names)

    def test_benchmark_logger_persists_per_eye_raw_observation_fields(self):
        left = _eye("eye_33_133", horizontal=-0.20, vertical=0.30)
        right = _eye("eye_362_263", horizontal=-0.10, vertical=0.25)
        estimate = SimpleNamespace(
            eyes=[left, right],
            x_ctrl=0.01,
            y_ctrl=0.02,
            raw_x=0.03,
            raw_y=0.04,
            x_eye=0.05,
            y_eye=0.06,
            confidence=0.90,
            y_confidence=0.85,
            vertical_reliability=0.75,
            output_source="raw",
            pose_valid=False,
            head_pose_enabled=False,
            yaw_deg=1.0,
            pitch_deg=-2.0,
            head_pose_x=0.10,
            head_pose_y=-0.20,
            face_detected=True,
            valid=True,
            message="OK",
        )
        logger = SessionBenchmarkLogger(
            log_path=None,
            summary_path=None,
            confidence_dropout_threshold=0.35,
            condition_metadata={
                "condition_id": "controlled_no_glasses",
                "glasses": "none",
                "lighting": "normal",
                "distance_notes": "baseline",
                "target_visibility": "clear",
            },
        )

        logger.log_frame(
            frame_index=1,
            elapsed_s=0.1,
            fps=30.0,
            protocol_label="center_hold",
            estimate=estimate,
        )

        record = logger.records[0]
        expected = {
            "left_h": -0.20,
            "right_h": -0.10,
            "left_v_postbaseline": 0.30,
            "right_v_postbaseline": 0.25,
            "left_v_prebaseline": 0.40,
            "right_v_prebaseline": 0.35,
            "left_iris_v_raw": 1.25,
            "right_iris_v_raw": 1.25,
            "left_width": 20.0,
            "right_width": 20.0,
            "left_height": 6.0,
            "right_height": 6.0,
            "left_openness": 0.30,
            "right_openness": 0.30,
            "left_min_clearance_x": 0.20,
            "right_min_clearance_x": 0.20,
            "left_min_clearance_y": 0.10,
            "right_min_clearance_y": 0.10,
            "left_iris_radius": 2.0,
            "right_iris_radius": 2.0,
            "left_v_eyelid_relative": 0.11,
            "right_v_eyelid_relative": 0.11,
            "left_v_orbital_relative": 0.22,
            "right_v_orbital_relative": 0.22,
            "left_iris_ring_vertical_asymmetry": 0.33,
            "right_iris_ring_vertical_asymmetry": 0.33,
            "yaw_deg": 1.0,
            "pitch_deg": -2.0,
            "head_pose_x": 0.10,
            "head_pose_y": -0.20,
        }
        for key, value in expected.items():
            self.assertIn(key, record)
            self.assertEqual(record[key], value)

        self.assertEqual(record["condition_id"], "controlled_no_glasses")
        self.assertEqual(record["condition_glasses"], "none")
        self.assertEqual(record["condition_lighting"], "normal")
        self.assertEqual(record["condition_distance_notes"], "baseline")
        self.assertEqual(record["condition_target_visibility"], "clear")
        self.assertEqual(record["left_iris_center"], [10, 1])
        self.assertEqual(record["left_iris_points"], [[9, 1], [10, 0], [11, 1], [10, 2]])
        self.assertEqual(record["left_corners"], [[0, 0], [20, 0]])
        self.assertEqual(record["left_top"], [10, -3])
        self.assertEqual(record["left_bottom"], [10, 3])
        self.assertEqual(record["left_u"], [1.0, 0.0])
        self.assertEqual(record["left_v_axis"], [0.0, 1.0])


if __name__ == "__main__":
    unittest.main()
