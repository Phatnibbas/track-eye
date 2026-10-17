import math
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from track_eye.output import EyeNeutral, OutputCalibration, OutputGain, scale_tracking_result
from track_eye.tracker import EYE_DEFINITIONS, IRIS_GROUPS, EyeTracker


def face_points(bounds=(128, 64, 128, 64), horizontal=0.25, vertical=-0.25):
    """Full-image pixels, including tilted eyes with opposite corner ordering."""
    x, y, width, height = bounds
    points = np.tile([x + width / 2, y + height / 2], (478, 1)).astype(float)
    points[0] = (x, y)
    points[1] = (x + width, y + height)
    forward = np.array([0.8, 0.6])
    downward = np.array([-0.6, 0.8])
    for number, (definition, iris_group) in enumerate(zip(EYE_DEFINITIONS, IRIS_GROUPS)):
        fraction = 0.3125 if number == 0 else 0.6875
        center = np.array([x + width * fraction, y + height * fraction])
        axis = forward if number == 0 else -forward
        points[definition['corners'][0]] = center - axis * width / 8
        points[definition['corners'][1]] = center + axis * width / 8
        for index in definition['top']:
            points[index] = center - downward * height / 16
        for index in definition['bottom']:
            points[index] = center + downward * height / 16
        iris = center + forward * horizontal * width / 8 + downward * vertical * height / 16
        radius = height / 32
        for index, offset in zip(iris_group, ((radius, 0), (0, radius), (-radius, 0), (0, -radius))):
            points[index] = iris + offset
    return points


def image(width=512, height=256):
    y, x = np.indices((height, width))
    return np.stack((x % 251, y % 253, (x + y) % 255), axis=-1).astype(np.uint8)


class MeshBoundary:
    """Model boundary only: samples must be the exact unresized native crop."""

    def __init__(self, testcase):
        self.testcase = testcase
        self.samples = []

    def expect(self, frame, rectangle, points):
        self.samples.append((frame, rectangle, points))

    def process(self, rgb):
        self.testcase.assertTrue(self.samples, 'Unexpected extra model inference')
        frame, (left, top, width, height), points = self.samples.pop(0)
        np.testing.assert_array_equal(rgb, frame[top:top + height, left:left + width, ::-1])
        if points is None:
            return SimpleNamespace(multi_face_landmarks=None)
        landmarks = [
            SimpleNamespace(x=(x - left) / width, y=(y - top) / height)
            for x, y in points
        ]
        return SimpleNamespace(multi_face_landmarks=[SimpleNamespace(landmark=landmarks)])

    def reset(self):
        pass

    def close(self):
        pass


class TrackerAcquisitionTests(unittest.TestCase):
    proposal = (0.25, 0.25, 0.25, 0.25)
    roi = (76, 38, 232, 116)

    def setUp(self):
        self.mesh = MeshBoundary(self)
        model = SimpleNamespace(solutions=SimpleNamespace(face_mesh=SimpleNamespace(
            FaceMesh=lambda **kwargs: self.mesh,
        )))
        self.module_patch = patch.dict(sys.modules, {'mediapipe': model})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.enterContext(patch('track_eye.tracker.ROI_PADDING', 1.8))
        self.enterContext(patch('track_eye.tracker.REFERENCE_SECONDS', 0.6))
        self.tracker = EyeTracker(ema_alpha=0.5)
        self.addCleanup(self.tracker.close)
        self.frame = image()

    def assert_geometry(self, result, points, bounds=(128, 64, 128, 64), horizontal=0.25, vertical=-0.25):
        self.assertTrue(result.face_detected)
        self.assertIsNotNone(result.eyes)
        x, y, width, height = bounds
        for number, (eye, definition, iris_group) in enumerate(zip(result.eyes, EYE_DEFINITIONS, IRIS_GROUPS)):
            fraction = 0.3125 if number == 0 else 0.6875
            np.testing.assert_allclose(eye.eye_center, (x + width * fraction, y + height * fraction))
            np.testing.assert_allclose(eye.iris_center, points[list(iris_group)].mean(axis=0))
            self.assertAlmostEqual(eye.eye_width, width / 4)
            self.assertAlmostEqual(eye.eyelid_aperture, height / 8)
            self.assertAlmostEqual(eye.iris_radius, height / 32)
            self.assertAlmostEqual(eye.x, horizontal)
            self.assertAlmostEqual(eye.y, vertical)
            sign = 1 if number == 0 else -1
            self.assertAlmostEqual(eye.raw_h, sign * horizontal)
            self.assertAlmostEqual(eye.raw_v, sign * vertical)
            np.testing.assert_allclose(eye.axis_x, np.array((0.8, 0.6)) * sign)
            np.testing.assert_allclose(eye.axis_y, np.array((-0.6, 0.8)) * sign)
            # Contours intentionally use integer pixels; floating reconstruction
            # can put an integer-boundary coordinate just below that boundary.
            np.testing.assert_allclose(eye.contour, points[list(definition['contour'])].astype(int), atol=1)

    def test_cold_roi_maps_tilted_eyes_and_output_calibration_in_original_pixels(self):
        points = face_points()
        self.mesh.expect(self.frame, self.roi, points)
        result = self.tracker.process(self.frame, self.proposal, now_s=0)
        self.assert_geometry(result, points)
        self.assertEqual(self.tracker.diagnostics()['roi_px'], list(self.roi))
        self.assertEqual(self.tracker.diagnostics()['mode'], 'roi')
        self.assertTrue(self.tracker.diagnostics()['tracking'])
        calibration = OutputCalibration(
            OutputGain(left=2, right=10, up=10, down=4, soft_limit=1.5),
            tuple(EyeNeutral(eye.name, 0.05, 0.05) for eye in result.eyes),
        )
        output = scale_tracking_result(result, calibration)
        for eye in output.eyes:
            self.assertAlmostEqual(eye.x, 1 + 0.5 * (1 - math.exp(-2)))
            self.assertAlmostEqual(eye.y, -(1 + 0.5 * (1 - math.exp(-4))))

    def test_border_crop_keeps_native_aspect_and_global_overlay_coordinates(self):
        points = face_points((0, 0, 128, 64))
        # Padding clips only at the image edges, not by squashing the face.
        self.mesh.expect(self.frame, (0, 0, 180, 90), points)
        result = self.tracker.process(self.frame, (0, 0, 0.25, 0.25), now_s=0)
        self.assert_geometry(result, points, bounds=(0, 0, 128, 64))
        self.assertEqual(self.tracker.diagnostics()['roi_px'], [0, 0, 180, 90])

    def test_warm_roi_survives_detector_miss_and_follows_last_accepted_bounds(self):
        points = face_points()
        moved = face_points((136, 68, 128, 64))
        self.mesh.expect(self.frame, self.roi, points)
        self.mesh.expect(self.frame, self.roi, moved)
        self.mesh.expect(self.frame, (84, 42, 232, 116), moved)
        self.tracker.process(self.frame, self.proposal, now_s=0)
        second = self.tracker.process(self.frame, now_s=0.1)
        third = self.tracker.process(self.frame, now_s=0.2)
        self.assert_geometry(second, moved, bounds=(136, 68, 128, 64))
        self.assert_geometry(third, moved, bounds=(136, 68, 128, 64))
        np.testing.assert_allclose(self.tracker.reference_box(0.2), (136 / 512, 68 / 256, 0.25, 0.25))

    def test_good_full_frame_tracking_does_not_switch_to_detector_crop(self):
        points = face_points()
        self.mesh.expect(self.frame, (0, 0, 512, 256), points)
        self.mesh.expect(self.frame, (0, 0, 512, 256), points)
        self.assert_geometry(self.tracker.process(self.frame, now_s=0), points)
        self.assert_geometry(self.tracker.process(self.frame, self.proposal, now_s=0.1), points)
        self.assertEqual(self.tracker.diagnostics()['mode'], 'full_frame')
        self.assertIsNone(self.tracker.diagnostics()['roi_px'])

    def test_loss_has_no_stale_eyes_and_reacquisition_starts_fresh_ema(self):
        self.mesh.expect(self.frame, self.roi, face_points())
        self.mesh.expect(self.frame, self.roi, None)
        changed = face_points(horizontal=0.75, vertical=0.5)
        self.mesh.expect(self.frame, self.roi, changed)
        self.tracker.process(self.frame, self.proposal, now_s=0)
        lost = self.tracker.process(self.frame, now_s=0.1)
        self.assertFalse(lost.face_detected)
        self.assertIsNone(lost.eyes)
        self.assertFalse(self.tracker.diagnostics()['tracking'])
        self.assertIsNone(self.tracker.diagnostics()['unfiltered'])
        np.testing.assert_allclose(self.tracker.reference_box(0.2), self.proposal)
        reacquired = self.tracker.process(self.frame, self.proposal, now_s=0.3)
        self.assert_geometry(reacquired, changed, horizontal=0.75, vertical=0.5)

    def test_warm_ema_is_retained_until_actual_loss(self):
        self.mesh.expect(self.frame, self.roi, face_points(horizontal=0.25))
        changed = face_points(horizontal=0.75)
        self.mesh.expect(self.frame, self.roi, changed)
        self.tracker.process(self.frame, self.proposal, now_s=0)
        result = self.tracker.process(self.frame, now_s=0.1)
        for eye in result.eyes:
            self.assertAlmostEqual(eye.x, 0.5)
            self.assertAlmostEqual(eye.y, -0.25)
        unfiltered = self.tracker.diagnostics()['unfiltered']
        for side in ('left', 'right'):
            self.assertAlmostEqual(unfiltered[side]['x'], 0.75)
            self.assertAlmostEqual(unfiltered[side]['y'], -0.25)

    def test_unrelated_mesh_and_proposal_cannot_steal_lock_until_timeout(self):
        other_bounds = (352, 160, 128, 64)
        other_proposal = (352 / 512, 160 / 256, 0.25, 0.25)
        other = face_points(other_bounds, horizontal=-0.5)
        self.mesh.expect(self.frame, (0, 0, 512, 256), face_points())
        self.mesh.expect(self.frame, (0, 0, 512, 256), other)
        self.tracker.process(self.frame, now_s=0)
        rejected_mesh = self.tracker.process(self.frame, now_s=0.1)
        self.assertFalse(rejected_mesh.face_detected)
        self.assertIsNone(rejected_mesh.eyes)
        rejected_proposal = self.tracker.process(self.frame, other_proposal, now_s=0.2)
        self.assertFalse(rejected_proposal.face_detected)
        self.assertIsNone(rejected_proposal.eyes)
        np.testing.assert_allclose(self.tracker.reference_box(0.6), self.proposal)
        self.assertIsNone(self.tracker.reference_box(0.6001))
        self.mesh.expect(self.frame, (300, 134, 212, 116), other)
        acquired = self.tracker.process(self.frame, other_proposal, now_s=0.7)
        self.assert_geometry(acquired, other, bounds=other_bounds, horizontal=-0.5)

    def test_cold_mesh_must_match_selected_proposal(self):
        self.mesh.expect(self.frame, self.roi, face_points((352, 160, 128, 64)))
        result = self.tracker.process(self.frame, self.proposal, now_s=0)
        self.assertFalse(result.face_detected)
        self.assertIsNone(result.eyes)
        self.assertIsNone(self.tracker.reference_box(0))

    def test_long_frame_gap_discards_warm_roi_and_ema(self):
        self.mesh.expect(self.frame, self.roi, face_points())
        changed = face_points(horizontal=-0.5)
        self.mesh.expect(self.frame, (0, 0, 512, 256), changed)
        self.tracker.process(self.frame, self.proposal, now_s=0)
        result = self.tracker.process(self.frame, now_s=0.7)
        self.assert_geometry(result, changed, horizontal=-0.5)
        self.assertEqual(self.tracker.diagnostics()['mode'], 'full_frame')

    def test_loss_switches_full_frame_to_clean_roi_on_next_frame(self):
        self.mesh.expect(self.frame, (0, 0, 512, 256), face_points())
        self.mesh.expect(self.frame, (0, 0, 512, 256), None)
        self.mesh.expect(self.frame, self.roi, face_points(horizontal=-0.5))
        self.tracker.process(self.frame, now_s=0)
        lost = self.tracker.process(self.frame, self.proposal, now_s=0.1)
        self.assertIsNone(lost.eyes)
        acquired = self.tracker.process(self.frame, self.proposal, now_s=0.2)
        self.assert_geometry(acquired, face_points(horizontal=-0.5), horizontal=-0.5)
        self.assertEqual(self.tracker.diagnostics()['mode'], 'roi')

    def test_frame_size_change_discards_old_reference_graph_and_ema(self):
        self.mesh.expect(self.frame, self.roi, face_points())
        self.tracker.process(self.frame, self.proposal, now_s=0)
        frame = image(256, 512)
        bounds = (64, 128, 64, 128)
        points = face_points(bounds, horizontal=-0.5, vertical=0.5)
        self.mesh.expect(frame, (38, 76, 116, 232), points)
        result = self.tracker.process(frame, self.proposal, now_s=0.1)
        self.assert_geometry(result, points, bounds=bounds, horizontal=-0.5, vertical=0.5)
        self.assertEqual(self.tracker.diagnostics()['roi_px'], [38, 76, 116, 232])

    def test_explicit_reset_removes_hidden_crop_and_reference(self):
        self.mesh.expect(self.frame, self.roi, face_points())
        self.tracker.process(self.frame, self.proposal, now_s=0)
        self.tracker.reset()
        self.assertIsNone(self.tracker.reference_box(0.1))
        self.assertFalse(self.tracker.diagnostics()['tracking'])
        self.assertIsNone(self.tracker.diagnostics()['roi_px'])
        changed = face_points(horizontal=-0.5)
        self.mesh.expect(self.frame, (0, 0, 512, 256), changed)
        result = self.tracker.process(self.frame, now_s=0.2)
        self.assert_geometry(result, changed, horizontal=-0.5)

    def test_invalid_boxes_do_not_slice_or_prevent_legacy_full_frame_acquisition(self):
        for box in ((), (0, 0, 0, 1), (0, 0, -1, 1), (2, 0, 1, 1),
                    (0, 0, float('nan'), 1), (0, 0, float('inf'), 1), 'bad'):
            with self.subTest(box=box):
                self.tracker.reset()
                self.mesh.expect(self.frame, (0, 0, 512, 256), face_points())
                result = self.tracker.process(self.frame, box, now_s=0)
                self.assert_geometry(result, face_points())
                self.assertIsNone(self.tracker.diagnostics()['roi_px'])

    def test_partially_outside_box_clips_without_negative_indexing(self):
        points = face_points((0, 0, 128, 64))
        self.mesh.expect(self.frame, (0, 0, 180, 90), points)
        result = self.tracker.process(self.frame, (-0.25, -0.25, 0.5, 0.5), now_s=0)
        self.assert_geometry(result, points, bounds=(0, 0, 128, 64))


if __name__ == '__main__':
    unittest.main()
