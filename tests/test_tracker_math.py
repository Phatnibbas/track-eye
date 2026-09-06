import unittest

import numpy as np

from track_eye.tracker import EYE_DEFINITIONS, IRIS_GROUPS, EyeSmoother, measure_eye


class TrackerMathTests(unittest.TestCase):
    def _points(self, transform=lambda point: point):
        points = np.zeros((478, 2), dtype=np.float64)
        for definition, iris_group in zip(EYE_DEFINITIONS, IRIS_GROUPS):
            c0, c1 = definition["corners"]
            left = np.array([10.0, 20.0]) if c0 == 33 else np.array([10.0, 80.0])
            right = left + np.array([40.0, 0.0])
            points[c0], points[c1] = left, right
            for index in definition["top"]:
                points[index] = left * 0 + np.array([30.0, left[1] - 5.0])
            for index in definition["bottom"]:
                points[index] = left * 0 + np.array([30.0, left[1] + 5.0])
            iris = np.array([30.0, left[1] - 2.0])
            for index in iris_group:
                points[index] = iris
        return np.asarray([transform(point) for point in points])

    def test_uniform_transform_preserves_normalized_measurement(self):
        base = measure_eye(self._points(), EYE_DEFINITIONS[0], IRIS_GROUPS[0])
        theta = np.deg2rad(27.0)
        rotation = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
        transformed = self._points(lambda point: point @ rotation.T * 3.0 + np.array([200.0, -70.0]))
        rotated = measure_eye(transformed, EYE_DEFINITIONS[0], IRIS_GROUPS[0])
        self.assertAlmostEqual(base["h"], rotated["h"], places=10)
        self.assertAlmostEqual(base["v"], rotated["v"], places=10)

    def test_ema_first_update_and_reset(self):
        smoother = EyeSmoother(0.5)
        self.assertEqual(smoother.update(2.0, -2.0), (2.0, -2.0))
        self.assertEqual(smoother.update(0.0, 0.0), (1.0, -1.0))
        smoother.reset()
        self.assertEqual(smoother.update(4.0, 5.0), (4.0, 5.0))


if __name__ == "__main__":
    unittest.main()
