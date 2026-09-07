import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from track_eye.output_tuning import OutputTuner
from track_eye.tracker import EyeSignal, TrackingResult


class OutputTunerTests(unittest.TestCase):
    def test_saved_gain_and_neutral_survive_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "output-calibration.json"
            tuner = OutputTuner(path)
            tuner.update_gain({"left": 4.0, "right": 3.5, "up": 2.0, "down": 5.0, "soft_limit": 1.8})
            tuner.request_neutral()
            result = TrackingResult(
                1,
                True,
                (
                    EyeSignal("left", 0.1, -0.2, 0.1, -0.2),
                    EyeSignal("right", -0.1, -0.3, -0.1, -0.3),
                ),
                1.0,
            )
            with patch("track_eye.output_tuning.time.perf_counter", side_effect=(10.0, 11.1)):
                tuner.process(result)
                output = tuner.process(result)
            self.assertAlmostEqual(output.eyes[0].x, 0.0)
            self.assertAlmostEqual(output.eyes[1].y, 0.0)
            tuner.save()

            reloaded = OutputTuner(path)
            status = reloaded.status()
            self.assertEqual(status["calibration"]["gain"]["down"], 5.0)
            self.assertEqual(len(status["calibration"]["neutrals"]), 2)
            self.assertFalse(status["dirty"])
            self.assertEqual(json.loads(path.read_text())["schema_version"], 1)

    def test_invalid_gain_does_not_replace_current_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            tuner = OutputTuner(Path(directory) / "output-calibration.json")
            before = tuner.status()["calibration"]
            with self.assertRaises(ValueError):
                tuner.update_gain({"down": 20.0})
            self.assertEqual(tuner.status()["calibration"], before)


if __name__ == "__main__":
    unittest.main()
