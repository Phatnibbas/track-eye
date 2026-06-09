import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware" / "esp32_eye_ws_firmware" / "main.py"
SECRETS = ROOT / "firmware" / "esp32_eye_ws_firmware" / "secrets_example.py"


class ESP32WebSocketFirmwarePackageTests(unittest.TestCase):
    def test_ws_firmware_uses_wifi_client_and_two_servos(self):
        self.assertTrue(FIRMWARE.exists())
        source = FIRMWARE.read_text(encoding="utf-8")
        self.assertIn("import network", source)
        self.assertIn("def websocket_handshake", source)
        self.assertIn("base64 of exactly 16 bytes", source)
        self.assertIn("esp32-eye-key123", source)
        self.assertNotIn("esp32-eye-key-123", source)
        self.assertIn("def read_ws_text_frame", source)
        self.assertIn("sock.settimeout", source)
        self.assertIn("return None", source)
        self.assertIn("PAN_PIN = 5", source)
        self.assertIn("TILT_PIN = 4", source)
        self.assertNotIn("IP_LAPTOP", source)
        self.assertIn("SERVER_HOST = \"192.168.1.22\"", source)
        self.assertIn("WATCHDOG_TIMEOUT_MS", source)

    def test_ws_firmware_does_not_commit_real_wifi_password(self):
        self.assertTrue(SECRETS.exists())
        source = SECRETS.read_text(encoding="utf-8")
        self.assertIn("WIFI_SSID", source)
        self.assertIn("WIFI_PASSWORD", source)
        self.assertNotIn("comemakewithus", source.lower())


if __name__ == "__main__":
    unittest.main()
