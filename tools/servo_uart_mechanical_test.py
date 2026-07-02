"""Interactive USB UART mechanical limit test for the 4-servo eye.

This sends conservative `EYE,pan,tilt,gate` packets to the ESP32 UART
firmware one step at a time. Press Enter before each movement so the operator
can watch for buzzing, end-stop contact, wrong direction, or power issues.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class LimitTestStep:
    name: str
    pan: int
    tilt: int
    note: str
    gate: str = "tracking"


def build_limit_test_steps() -> list[LimitTestStep]:
    """Return conservative mechanical limit checks matching config.yaml."""
    return [
        LimitTestStep("neutral", 90, 0, "Home: centered horizontal, vertical home", "neutral"),
        LimitTestStep("pan_left_limit", 50, 0, "Horizontal low end of safe range"),
        LimitTestStep("neutral_after_left", 90, 0, "Return to neutral", "neutral"),
        LimitTestStep("pan_right_limit", 130, 0, "Horizontal high end of safe range"),
        LimitTestStep("neutral_after_right", 90, 0, "Return to neutral", "neutral"),
        LimitTestStep("tilt_up_limit", 90, 50, "Vertical high end of safe range"),
        LimitTestStep("neutral_after_up", 90, 0, "Return to neutral", "neutral"),
        LimitTestStep("diagonal_low_high", 50, 50, "Combined pan low + tilt high"),
        LimitTestStep("neutral_after_diag_1", 90, 0, "Return to neutral", "neutral"),
        LimitTestStep("diagonal_high_high", 130, 50, "Combined pan high + tilt high"),
        LimitTestStep("neutral_final", 90, 0, "Final neutral", "neutral"),
    ]


def format_step_packet(step: LimitTestStep) -> str:
    return f"EYE,{step.pan},{step.tilt},{step.gate}\n"


def send_steps(port: str, baudrate: int, delay_s: float, auto: bool) -> None:
    import serial

    steps = build_limit_test_steps()
    with serial.Serial(port, baudrate=baudrate, timeout=1) as ser:
        for index, step in enumerate(steps, start=1):
            packet = format_step_packet(step)
            print(
                f"[{index}/{len(steps)}] {step.name}: pan={step.pan} "
                f"tilt={step.tilt} gate={step.gate} | {step.note}"
            )
            print("    If servo buzzes/hits end-stop, disconnect servo power immediately.")
            if not auto:
                input("    Press Enter to send, or Ctrl+C to stop...")
            ser.write(packet.encode("ascii"))
            ser.flush()
            print(f"    sent: {packet.strip()}")
            time.sleep(delay_s)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ESP32 UART servo mechanical limit test")
    parser.add_argument("--port", required=True, help="Serial port, e.g. COM12")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--delay", type=float, default=1.2, help="Delay after each packet")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Do not wait for Enter between steps. Use only after manual test is safe.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    send_steps(args.port, args.baudrate, args.delay, args.auto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
