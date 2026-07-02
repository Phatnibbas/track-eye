import asyncio
import json
import unittest

import websockets

from servo_mapper import SingleEyeServoCommand
from servo_ws import ServoWebSocketServer


class ServoWebSocketIntegrationTests(unittest.TestCase):
    def test_server_delivers_servo_payload_to_browser_or_esp32_client(self):
        async def run_case():
            server = ServoWebSocketServer("127.0.0.1", 8771)
            server.start()
            await asyncio.sleep(0.5)
            try:
                async with websockets.connect("ws://127.0.0.1:8771/") as ws:
                    await asyncio.sleep(0.1)
                    server.broadcast_command(
                        SingleEyeServoCommand(91, 82, "tracking", "test")
                    )
                    message = await asyncio.wait_for(ws.recv(), timeout=2)
                    payload = json.loads(message)
                    self.assertEqual(payload["pan"], 91)
                    self.assertEqual(payload["tilt"], 82)
                    self.assertEqual(payload["gate"], "tracking")
            finally:
                server.close()

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
