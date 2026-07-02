import unittest

from calibration import CalibrationManager


class QuickKioskCalibrationTests(unittest.TestCase):
    def test_quick_kiosk_preset_overrides_collection_timing(self):
        manager = CalibrationManager(
            config={
                "settle_seconds": 0.8,
                "sample_seconds": 1.5,
                "min_samples_per_point": 5,
            },
            default_model_path="calibration_data/calibration.json",
        )

        manager.apply_quick_kiosk_preset(
            {
                "kiosk_quick_settle_seconds": 0.25,
                "kiosk_quick_sample_seconds": 0.65,
                "kiosk_quick_min_samples_per_point": 4,
            }
        )

        self.assertEqual(manager.settle_seconds, 0.25)
        self.assertEqual(manager.sample_seconds, 0.65)
        self.assertEqual(manager.min_samples_per_point, 4)


if __name__ == "__main__":
    unittest.main()
