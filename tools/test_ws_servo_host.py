"""Isolated WebSocket servo command host for ESP32 debugging.

This bypasses camera, gaze tracking, calibration, and UI. If ESP32 connects but
servos do not move with this script, the issue is in ESP32 firmware, wiring,
power, pin mapping, or servo mechanics.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from servo_ws import ServoWebSocketServer


@dataclass
class Command:
    pan_deg: float
    tilt_deg: float
    gate_state: str = "tracking"
    reason: str = "manual_test"


def run(host: str, port: int) -> None:
    server = ServoWebSocketServer(host, port)
    server.start()
    print(f"[HOST] ws://{host}:{port}/")
    print("[HOST] Waiting 3s for ESP32 to connect...")
    time.sleep(3.0)

    sequence = [
        Command(90, 80, "neutral"),
        Command(125, 80),
        Command(55, 80),
        Command(90, 110),
        Command(90, 50),
        Command(90, 80, "neutral"),
    ]
    try:
        while True:
            for command in sequence:
                print(
                    f"[SEND] pan={command.pan_deg:.0f} tilt={command.tilt_deg:.0f} "
                    f"gate={command.gate_state} clients={len(server.clients)}"
                )
                server.broadcast_command(command)
                time.sleep(1.5)
    except KeyboardInterrupt:
        print("[HOST] stopped")
    finally:
        server.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    run(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
