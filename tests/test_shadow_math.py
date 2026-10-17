import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from track_eye.fallback import FallbackConfig, FallbackSelector, SourceKind
from track_eye.output import OutputEyeSignal
from track_eye.pupil_quality import PupilQualityMonitor
from track_eye.shadow import FacePositionShadow, clip_relative_box, orthonormalize_rotation, rotation_to_quaternion
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

class FaceAssociationTests(unittest.TestCase):
    frame = np.zeros((12, 16, 3), dtype=np.uint8)
    reference = (0.1, 0.2, 0.2, 0.3)
    newcomer = (0.65, 0.2, 0.2, 0.3)
    config = replace(
        FallbackConfig(), face_roi=(0.05, 0.05, 0.95, 0.95), face_gain=1.0,
    )

    @staticmethod
    def detection(box, score):
        x, y, w, h = box
        return SimpleNamespace(
            score=[score],
            location_data=SimpleNamespace(relative_bounding_box=SimpleNamespace(
                xmin=x, ymin=y, width=w, height=h,
            )),
        )

    def shadow(self, *samples):
        class Detector:
            calls = 0

            def process(self, _rgb):
                sample = samples[self.calls]
                self.calls += 1
                if isinstance(sample, Exception):
                    raise sample
                return SimpleNamespace(detections=sample)

        shadow = FacePositionShadow(enabled=False)
        shadow.enabled = True
        shadow._error = None
        shadow._detector = Detector()
        return shadow

    @staticmethod
    def selector():
        config = FaceAssociationTests.config
        return FallbackSelector(replace(
            config, face_position=replace(config.face_position, promote_s=0.0, expire_s=2.5),
        ))

    def test_retained_reference_beats_louder_newcomer_and_maps_same_face(self):
        shadow = self.shadow([
            self.detection(self.newcomer, 0.99), self.detection(self.reference, 0.5),
        ])
        candidate = shadow.process(self.frame, self.config, reference_box=self.reference)
        self.assertTrue(candidate.valid)
        np.testing.assert_allclose(candidate.quality["box"], self.reference)
        self.assertAlmostEqual(candidate.x, -2.0 / 3.0)
        self.assertAlmostEqual(candidate.y, -1.0 / 3.0)

    def test_overlap_rank_precedes_score_and_equal_overlap_uses_score(self):
        shifted = (0.2, 0.2, 0.2, 0.3)
        shadow = self.shadow([
            self.detection(shifted, 0.99),
            self.detection(self.reference, 0.5),
            self.detection(self.reference, 0.7),
        ])
        candidate = shadow.process(self.frame, self.config, reference_box=self.reference)
        self.assertTrue(candidate.valid)
        np.testing.assert_allclose(candidate.quality["box"], self.reference)
        self.assertEqual(candidate.quality["score"], 0.7)

    def test_qualified_matching_face_is_not_hidden_by_better_overlap_below_gate(self):
        shifted = (0.2, 0.2, 0.2, 0.3)
        shadow = self.shadow([
            self.detection(self.reference, 0.29),
            self.detection(shifted, 0.7),
        ])
        candidate = shadow.process(self.frame, self.config, score_min=0.3, reference_box=self.reference)
        self.assertTrue(candidate.valid)
        np.testing.assert_allclose(candidate.quality["box"], shifted)
        self.assertAlmostEqual(candidate.quality["score"], 0.7)

    def test_reference_lifetime_is_controlled_only_by_caller(self):
        detections = [self.detection(self.newcomer, 0.99), self.detection(self.reference, 0.5)]
        shadow = self.shadow(detections, detections, detections)
        with patch("track_eye.shadow.time.monotonic_ns", side_effect=[1_000_000_000, 21_000_000_000, 22_000_000_000]):
            first = shadow.process(self.frame, self.config, reference_box=self.reference)
            retained = shadow.process(self.frame, self.config, reference_box=self.reference)
            released = shadow.process(self.frame, self.config, reference_box=None)
        np.testing.assert_allclose(first.quality["box"], self.reference)
        np.testing.assert_allclose(retained.quality["box"], self.reference)
        np.testing.assert_allclose(released.quality["box"], self.newcomer)

    def test_no_match_does_not_reuse_old_box_or_choose_another_visitor(self):
        shadow = self.shadow(
            [self.detection(self.reference, 0.7)], [self.detection(self.newcomer, 0.99)],
        )
        self.assertTrue(shadow.process(self.frame, self.config).valid)
        candidate = shadow.process(self.frame, self.config, reference_box=self.reference)
        self.assertFalse(candidate.valid)
        self.assertNotIn("box", candidate.quality)
        diagnostics = shadow.diagnostics()
        self.assertIsNone(diagnostics["box"])
        self.assertIsNone(diagnostics["raw_box"])
        self.assertEqual(diagnostics["score"], 0.0)
        decision = self.selector().update(candidate.monotonic_ns / 1e9, None, {SourceKind.FACE_POSITION: candidate}, None)
        self.assertEqual(decision.active_source, SourceKind.NONE)

    def test_failed_empty_and_disabled_samples_clear_previous_geometry(self):
        for failure in ([], RuntimeError("detector failed"), None):
            with self.subTest(failure=failure):
                shadow = self.shadow([self.detection(self.reference, 0.7)], failure)
                self.assertTrue(shadow.process(self.frame, self.config).valid)
                if failure is None:
                    shadow.enabled = False
                    shadow._detector = None
                candidate = shadow.process(self.frame, self.config)
                self.assertFalse(candidate.valid)
                self.assertNotIn("box", candidate.quality)
                diagnostics = shadow.diagnostics()
                self.assertIsNone(diagnostics["box"])
                self.assertIsNone(diagnostics["raw_box"])
                self.assertEqual(diagnostics["score"], 0.0)

    def test_configured_score_gate_still_applies_to_matching_face(self):
        shadow = self.shadow([
            self.detection(self.reference, 0.2), self.detection(self.newcomer, 0.99),
        ])
        candidate = shadow.process(self.frame, self.config, score_min=0.3, reference_box=self.reference)
        self.assertFalse(candidate.valid)
        self.assertEqual(candidate.quality["score"], 0.2)
        np.testing.assert_allclose(candidate.quality["box"], self.reference)

    def test_inference_delay_expires_face_but_fresh_face_still_needs_no_pupil(self):
        shadow = self.shadow([self.detection(self.reference, 0.7)])
        clock = [10.0]
        detector_process = shadow._detector.process

        def slow_detection(rgb):
            clock[0] = 10.125
            return detector_process(rgb)

        shadow._detector.process = slow_detection
        with patch("track_eye.shadow.time.monotonic_ns", side_effect=lambda: int(clock[0] * 1e9)), patch(
            "track_eye.shadow.time.perf_counter", side_effect=lambda: clock[0],
        ):
            candidate = shadow.process(self.frame, self.config, reference_box=self.reference)
        candidates = {SourceKind.FACE_POSITION: candidate}
        for expire_s, expected_source in ((0.1, SourceKind.NONE), (0.5, SourceKind.FACE_POSITION)):
            config = replace(
                self.config,
                face_position=replace(self.config.face_position, promote_s=0.0, expire_s=expire_s),
            )
            decision = FallbackSelector(config).update(10.125, None, candidates, None)
            self.assertEqual(decision.active_source, expected_source)



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
