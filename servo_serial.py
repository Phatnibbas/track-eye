"""Serial packet helpers for laptop-to-ESP32 eye servo commands."""

from __future__ import annotations

from dataclasses import dataclass


def _clamp_angle(value: float) -> int:
    return max(0, min(180, int(round(float(value)))))


@dataclass
class SingleEyeCommand:
    pan_deg: float
    tilt_deg: float
    gate_state: str


def format_single_eye_packet(command: SingleEyeCommand) -> str:
    return "EYE,{},{},{}\n".format(
        _clamp_angle(command.pan_deg),
        _clamp_angle(command.tilt_deg),
        str(command.gate_state),
    )


class SerialEyeWriter:
    def __init__(self, port: str, baudrate: int = 115200):
        import serial

        self.serial = serial.Serial(port, baudrate=baudrate, timeout=0)

    def write_command(self, command: SingleEyeCommand) -> None:
        self.serial.write(format_single_eye_packet(command).encode("ascii"))

    def close(self) -> None:
        self.serial.close()
