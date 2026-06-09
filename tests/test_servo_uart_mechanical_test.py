import unittest

from tools.servo_uart_mechanical_test import build_limit_test_steps, format_step_packet


class ServoUartMechanicalTestScriptTests(unittest.TestCase):
    def test_builds_safe_limit_sequence_from_current_mechanical_range(self):
        steps = build_limit_test_steps()

        self.assertEqual(steps[0].name, "neutral")
        self.assertEqual((steps[0].pan, steps[0].tilt), (90, 0))
        self.assertIn((50, 0), [(step.pan, step.tilt) for step in steps])
        self.assertIn((130, 0), [(step.pan, step.tilt) for step in steps])
        self.assertIn((90, 50), [(step.pan, step.tilt) for step in steps])
        self.assertEqual(steps[-1].name, "neutral_final")
        self.assertEqual((steps[-1].pan, steps[-1].tilt), (90, 0))

    def test_formats_step_as_uart_eye_packet(self):
        step = build_limit_test_steps()[1]

        self.assertEqual(format_step_packet(step), f"EYE,{step.pan},{step.tilt},tracking\n")


if __name__ == "__main__":
    unittest.main()
