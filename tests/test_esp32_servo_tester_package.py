import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "firmware" / "esp32_servo_tester"


class ESP32ServoTesterPackageTests(unittest.TestCase):
    def test_thonny_package_contains_uploadable_main_and_readme(self):
        self.assertTrue((PACKAGE / "main.py").exists())
        self.assertTrue((PACKAGE / "README.md").exists())

    def test_main_py_contains_safe_micropython_servo_controls(self):
        source = (PACKAGE / "main.py").read_text(encoding="utf-8")

        self.assertIn("from machine import Pin, PWM", source)
        self.assertIn("SERVO_FREQ_HZ = 50", source)
        self.assertIn("SAFE_TEST_ANGLES = (90, 75, 105, 90)", source)
        self.assertIn("def angle_to_duty", source)
        self.assertIn("def classify_hint", source)
        self.assertIn("def classify_servo", source)
        self.assertIn("def test_servo", source)
        self.assertIn("def release_all", source)
        self.assertIn("Commands:", source)
        self.assertIn("CLASSIFY_STEPS", source)
        self.assertIn("Press Enter after observing", source)

    def test_main_py_defaults_to_one_servo_at_a_time(self):
        source = (PACKAGE / "main.py").read_text(encoding="utf-8")

        self.assertIn("# Never sweep all unknown servos at once.", source)
        self.assertIn("PIN_BY_SLOT", source)
        self.assertIn('"h1": 42', source)
        self.assertIn('"h2": 39', source)
        self.assertIn('"v1": 41', source)
        self.assertIn('"v2": 38', source)

    def test_main_py_has_thonny_min_max_limit_commands_for_real_mechanics(self):
        source = (PACKAGE / "main.py").read_text(encoding="utf-8")

        self.assertIn("PAN_MIN = 50", source)
        self.assertIn("PAN_MAX = 130", source)
        self.assertIn("TILT_MIN = 0", source)
        self.assertIn("TILT_MAX = 50", source)
        self.assertIn("def test_mechanical_limits", source)
        self.assertIn("limits", source)
        self.assertIn("hmin", source)
        self.assertIn("hmax", source)
        self.assertIn("vmax", source)

    def test_main_py_has_obvious_180_vs_360_classification_commands(self):
        source = (PACKAGE / "main.py").read_text(encoding="utf-8")

        self.assertIn("classify h1", source)
        self.assertIn("If it holds positions", source)
        self.assertIn("test one servo only: h1/h2/v1/v2", source)
        self.assertIn("180 positional", source)


if __name__ == "__main__":
    unittest.main()
