import unittest

import numpy as np

from track_eye.output import OutputEyeSignal
from track_eye.pupil_quality import PupilQualityMonitor
from track_eye.shadow import clip_relative_box, orthonormalize_rotation, rotation_to_quaternion
from track_eye.tracker import EyeSignal


def _eye(name, x, y, width=40.0, aperture=10.0):
    return EyeSignal(name, x, y, x, y, (), (0.0, 0.0), (1.0, 0.0), 3.0, width, aperture, 0.4, 0.1, (1.0, 0.0), (0.0, 1.0))


class PupilQualityTests(unittest.TestCase):
    def test_per_eye_metrics_and_velocity(self):
        monitor = PupilQualityMonitor()
        pair = monitor.update((_eye("eye_33_133", 0.1, 0.2), _eye("eye_362_263", -0.1, 0.3)), 1000.0)
        self.assertIsNotNone(pair)
        left, right = pair
        self.assertEqual(left.quality["eye_width_px"], 40.0)
        self.assertEqual(left.quality["eyelid_aperture_px"], 10.0)
        self.assertEqual(left.quality["iris_radius_px"], 3.0)
        self.assertEqual(left.quality["gate"], "uncalibrated")
        self.assertEqual(left.quality["velocity_per_s"], 0.0)
        pair2 = monitor.update((_eye("eye_33_133", 0.3, 0.2), _eye("eye_362_263", -0.1, 0.3)), 1001.0)
        assert pair2 is not None
        self.assertAlmostEqual(pair2[0].quality["velocity_per_s"], 0.2)
        self.assertAlmostEqual(pair2[1].quality["velocity_per_s"], 0.0)

    def test_missing_face_clears_velocity(self):
        monitor = PupilQualityMonitor()
        monitor.update((_eye("eye_33_133", 0.1, 0.2), _eye("eye_362_263", 0.0, 0.0)), 1000.0)
        self.assertIsNone(monitor.update(None, 1001.0))
        pair = monitor.update((_eye("eye_33_133", 0.5, 0.2), _eye("eye_362_263", 0.0, 0.0)), 1002.0)
        assert pair is not None
        self.assertEqual(pair[0].quality["velocity_per_s"], 0.0)

    def test_one_eye_never_fabricates_other(self):
        monitor = PupilQualityMonitor()
        # A single-eye tuple is malformed input: monitor must not invent a mate.
        self.assertIsNone(monitor.update((_eye("eye_33_133", 0.1, 0.1),), 1000.0))

    def test_output_targets_are_used_without_losing_raw_geometry(self):
        monitor = PupilQualityMonitor()
        raw = (_eye("eye_33_133", 0.1, 0.2), _eye("eye_362_263", -0.1, 0.3))
        targets = (
            OutputEyeSignal("eye_33_133", 0.7, -0.4),
            OutputEyeSignal("eye_362_263", -0.6, 0.5),
        )
        pair = monitor.update(raw, 1000.0, target_eyes=targets)
        assert pair is not None
        self.assertEqual((pair[0].x, pair[0].y), (0.7, -0.4))
        self.assertEqual((pair[1].x, pair[1].y), (-0.6, 0.5))
        self.assertEqual(pair[0].quality["normalized_h"], raw[0].raw_h)
        self.assertEqual(pair[0].quality["eye_width_px"], raw[0].eye_width)


class FaceBoxTests(unittest.TestCase):
    def test_out_of_frame_box_keeps_raw_evidence_and_bounds_target(self):
        clipped, center = clip_relative_box(-0.2, -0.1, 1.4, 0.8)
        self.assertEqual(clipped[:3], (0.0, 0.0, 1.0))
        self.assertAlmostEqual(clipped[3], 0.7)
        self.assertAlmostEqual(center[0], 0.5)
        self.assertAlmostEqual(center[1], 0.3)


class RotationMathTests(unittest.TestCase):
    def test_scale_removed_and_proper(self):
        scaled = np.eye(3) * 2.5
        rotation, ok = orthonormalize_rotation(scaled)
        self.assertTrue(ok)
        np.testing.assert_allclose(rotation, np.eye(3), atol=1e-9)
        bad, ok = orthonormalize_rotation(np.full((3, 3), np.nan))
        self.assertFalse(ok)
        reflection = np.diag([1.0, 1.0, -1.0])
        rotation, ok = orthonormalize_rotation(reflection)
        self.assertTrue(ok)
        self.assertGreater(float(np.linalg.det(rotation)), 0.0)

    def test_identity_quaternion(self):
        w, x, y, z = rotation_to_quaternion(np.eye(3))
        self.assertAlmostEqual(w, 1.0)
        self.assertAlmostEqual(x + y + z, 0.0)


if __name__ == "__main__":
    unittest.main()
