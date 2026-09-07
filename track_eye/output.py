"""Explicit, configurable output mapping; tracker values remain untouched."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .tracker import TrackingResult


@dataclass(frozen=True)
class OutputGain:
    """Directional gains matching the original Pi display mapping."""

    left: float = 3.0
    right: float = 3.0
    up: float = 2.5
    down: float = 3.75
    soft_limit: float = 1.5


@dataclass(frozen=True)
class EyeNeutral:
    name: str
    x: float
    y: float


@dataclass(frozen=True)
class OutputCalibration:
    gain: OutputGain = OutputGain()
    neutrals: tuple[EyeNeutral, ...] = ()


@dataclass(frozen=True)
class OutputEyeSignal:
    name: str
    x: float
    y: float


@dataclass(frozen=True)
class OutputTrackingResult:
    timestamp_ns: int
    face_detected: bool
    eyes: tuple[OutputEyeSignal, OutputEyeSignal] | None
    inference_ms: float


def _soft_limit(value: float, limit: float) -> float:
    """Preserve the central range and approach the output limit smoothly."""
    knee = min(1.0, limit * 0.75)
    magnitude = abs(value)
    if magnitude <= knee:
        return value
    span = limit - knee
    limited = knee + span * (1.0 - math.exp(-(magnitude - knee) / span))
    return math.copysign(limited, value)


def _scale_eye(eye, calibration: OutputCalibration) -> OutputEyeSignal:
    neutral_x = neutral_y = 0.0
    for neutral in calibration.neutrals:
        if neutral.name == eye.name:
            neutral_x, neutral_y = neutral.x, neutral.y
            break
    x = eye.x - neutral_x
    y = eye.y - neutral_y
    x *= calibration.gain.left if x < 0.0 else calibration.gain.right
    y *= calibration.gain.up if y < 0.0 else calibration.gain.down
    return OutputEyeSignal(
        name=eye.name,
        x=_soft_limit(x, calibration.gain.soft_limit),
        y=_soft_limit(y, calibration.gain.soft_limit),
    )


def scale_tracking_result(
    result: TrackingResult,
    calibration: OutputCalibration = OutputCalibration(),
) -> OutputTrackingResult:
    """Apply neutral offsets, directional gains, and soft limits at output only."""
    if result.eyes is None:
        return OutputTrackingResult(result.timestamp_ns, False, None, result.inference_ms)
    eyes = (_scale_eye(result.eyes[0], calibration), _scale_eye(result.eyes[1], calibration))
    return OutputTrackingResult(result.timestamp_ns, True, eyes, result.inference_ms)
