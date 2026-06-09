import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_DIR = ROOT / "firmware" / "esp32_eye_uart_firmware"
FIRMWARE = FIRMWARE_DIR / "main.py"
README = FIRMWARE_DIR / "README.md"


class ESP32UartFirmwarePackageTests(unittest.TestCase):
    def test_active_uart_firmware_package_exists(self):
        self.assertTrue(FIRMWARE.exists())
        self.assertTrue(README.exists())

    def test_uart_firmware_parses_eye_packets_and_fails_safe(self):
        source = FIRMWARE.read_text(encoding="utf-8")
        self.assertIn("EYE,pan,tilt,gate", source)
        self.assertIn("def parse_eye_packet", source)
        self.assertIn("WATCHDOG_TIMEOUT_MS", source)
        self.assertIn("HORIZ_PINS = [42, 39]", source)
        self.assertIn("VERT_PINS = [41, 38]", source)
        self.assertIn("PAN_MIN = 50", source)
        self.assertIn("PAN_MAX = 130", source)
        self.assertIn("TILT_NEUTRAL = 0", source)
        self.assertIn("TILT_MIN = 0", source)
        self.assertIn("TILT_MAX = 50", source)
        self.assertIn("180 - angle", source)

    def test_uart_readme_documents_demo_command(self):
        text = README.read_text(encoding="utf-8")
        self.assertIn("--servo-port COM", text)
        self.assertIn("USB UART", text)
        self.assertIn("4 servo", text)
        self.assertIn("EYE,pan,tilt,gate", text)


if __name__ == "__main__":
    unittest.main()
