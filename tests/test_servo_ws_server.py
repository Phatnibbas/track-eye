import unittest

from servo_ws import servo_command_payload
from servo_mapper import SingleEyeServoCommand


class ServoWebSocketServerTests(unittest.TestCase):
    def test_payload_contains_single_eye_servo_command(self):
        payload = servo_command_payload(
            SingleEyeServoCommand(90.4, 79.6, "tracking", "session_ready")
        )

        self.assertEqual(
            payload,
            '{"type":"eye","pan":90,"tilt":80,"gate":"tracking"}',
        )


if __name__ == "__main__":
    unittest.main()
