import unittest

from gaze_estimator import GazeEstimator


class VerticalFeatureModeTests(unittest.TestCase):
    def _config(self, mode: str) -> dict:
        return {
            "vertical_feature_mode": mode,
            "vertical_width_norm_gain": 0.30,
            "vertical_orbital_norm_gain": 0.50,
            "min_detection_confidence": 0.5,
            "min_tracking_confidence": 0.5,
        }

    def test_default_mode_is_current(self):
        estimator = GazeEstimator({})
        try:
            self.assertEqual(estimator.vertical_feature_mode, "current")
        finally:
            estimator.close()

    def test_orbital_mode_is_accepted(self):
        estimator = GazeEstimator(self._config("orbital_relative"))
        try:
            self.assertEqual(estimator.vertical_feature_mode, "orbital_relative")
        finally:
            estimator.close()

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            GazeEstimator(self._config("auto_magic"))


if __name__ == "__main__":
    unittest.main()
