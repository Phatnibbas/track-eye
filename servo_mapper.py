"""Laptop-side single-eye servo mapping for the ESP32 eye prototype."""

from __future__ import annotations

from dataclasses import dataclass
from math import copysign


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _shape(value: float, deadband: float, exponent: float) -> float:
    value = _clamp(float(value), -1.0, 1.0)
    if abs(value) < deadband:
        return 0.0
    return copysign(abs(value) ** exponent, value)


@dataclass
class SingleEyeServoConfig:
    pan_neutral_deg: float = 90.0
    pan_min_deg: float = 55.0
    pan_max_deg: float = 125.0
    pan_gain_deg: float = 35.0
    pan_invert: bool = True
    tilt_neutral_deg: float = 80.0
    tilt_min_deg: float = 50.0
    tilt_max_deg: float = 110.0
    tilt_gain_deg: float = 30.0
    tilt_invert: bool = True
    confidence_min: float = 0.45
    session_required: bool = True
    deadband_x: float = 0.03
    deadband_y: float = 0.04
    response_exponent_x: float = 0.75
    response_exponent_y: float = 0.70
    smoothing_alpha: float = 0.20
    max_step_deg: float = 3.0

    @classmethod
    def from_dict(cls, payload: dict) -> "SingleEyeServoConfig":
        eye = payload.get("single_eye", {}) if payload else {}
        return cls(
            pan_neutral_deg=float(eye.get("pan_neutral_deg", 90.0)),
            pan_min_deg=float(eye.get("pan_min_deg", 55.0)),
            pan_max_deg=float(eye.get("pan_max_deg", 125.0)),
            pan_gain_deg=float(eye.get("pan_gain_deg", 35.0)),
            pan_invert=bool(eye.get("pan_invert", True)),
            tilt_neutral_deg=float(eye.get("tilt_neutral_deg", 80.0)),
            tilt_min_deg=float(eye.get("tilt_min_deg", 50.0)),
            tilt_max_deg=float(eye.get("tilt_max_deg", 110.0)),
            tilt_gain_deg=float(eye.get("tilt_gain_deg", 30.0)),
            tilt_invert=bool(eye.get("tilt_invert", True)),
            confidence_min=float(payload.get("confidence_min", 0.45)),
            session_required=bool(payload.get("session_required", True)),
            smoothing_alpha=float(payload.get("smoothing_alpha", 0.20)),
            max_step_deg=float(payload.get("max_step_deg", 3.0)),
        )


@dataclass
class SingleEyeServoCommand:
    pan_deg: float
    tilt_deg: float
    gate_state: str
    reason: str


class SingleEyeServoMapper:
    def __init__(self, config: SingleEyeServoConfig):
        self.config = config
        self.current = SingleEyeServoCommand(
            pan_deg=config.pan_neutral_deg,
            tilt_deg=config.tilt_neutral_deg,
            gate_state="neutral",
            reason="startup",
        )

    def update(
        self,
        x_ctrl: float,
        y_ctrl: float,
        confidence: float,
        session_ready: bool,
        output_source: str,
        calibration_active: bool,
    ) -> SingleEyeServoCommand:
        if calibration_active:
            return self._set_neutral("calibration_active")
        if self.config.session_required and not session_ready:
            return self._hold("session_not_ready")
        if confidence < self.config.confidence_min:
            return self._hold("low_confidence")
        if output_source == "hold":
            return self._hold("held_gaze_output")

        x = _shape(x_ctrl, self.config.deadband_x, self.config.response_exponent_x)
        y = _shape(y_ctrl, self.config.deadband_y, self.config.response_exponent_y)
        pan_sign = -1.0 if self.config.pan_invert else 1.0
        tilt_sign = -1.0 if self.config.tilt_invert else 1.0
        target_pan = _clamp(
            self.config.pan_neutral_deg + (pan_sign * x * self.config.pan_gain_deg),
            self.config.pan_min_deg,
            self.config.pan_max_deg,
        )
        target_tilt = _clamp(
            self.config.tilt_neutral_deg + (tilt_sign * y * self.config.tilt_gain_deg),
            self.config.tilt_min_deg,
            self.config.tilt_max_deg,
        )
        return self._approach(target_pan, target_tilt, "tracking", "session_ready")

    def _set_neutral(self, reason: str) -> SingleEyeServoCommand:
        return self._approach(
            self.config.pan_neutral_deg,
            self.config.tilt_neutral_deg,
            "neutral",
            reason,
        )

    def _hold(self, reason: str) -> SingleEyeServoCommand:
        self.current = SingleEyeServoCommand(
            self.current.pan_deg,
            self.current.tilt_deg,
            "hold",
            reason,
        )
        return self.current

    def _approach(
        self, target_pan: float, target_tilt: float, gate_state: str, reason: str
    ) -> SingleEyeServoCommand:
        alpha = _clamp(self.config.smoothing_alpha, 0.0, 1.0)
        max_step = max(0.0, float(self.config.max_step_deg))

        def move(current: float, target: float) -> float:
            smoothed = current + ((target - current) * alpha)
            return current + _clamp(smoothed - current, -max_step, max_step)

        self.current = SingleEyeServoCommand(
            pan_deg=round(move(self.current.pan_deg, target_pan), 3),
            tilt_deg=round(move(self.current.tilt_deg, target_tilt), 3),
            gate_state=gate_state,
            reason=reason,
        )
        return self.current
