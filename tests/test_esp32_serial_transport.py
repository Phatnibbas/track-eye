import unittest

from servo_serial import SingleEyeCommand, format_single_eye_packet


class ESP32SerialTransportTests(unittest.TestCase):
    def test_formats_single_eye_packet_for_micropython_firmware(self):
        packet = format_single_eye_packet(
            SingleEyeCommand(pan_deg=91.4, tilt_deg=79.6, gate_state="tracking")
        )

        self.assertEqual(packet, "EYE,91,80,tracking\n")

    def test_clamps_serial_angles_to_0_180(self):
        packet = format_single_eye_packet(
            SingleEyeCommand(pan_deg=-10, tilt_deg=200, gate_state="neutral")
        )

        self.assertEqual(packet, "EYE,0,180,neutral\n")


if __name__ == "__main__":
    unittest.main()
