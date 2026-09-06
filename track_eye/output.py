"""Explicit output-stage scaling for future integrations and status output."""

from __future__ import annotations

from dataclasses import dataclass

from .tracker import TrackingResult


@dataclass(frozen=True)
class OutputGain:
    """Directional gains matching the original Pi display mapping."""

    horizontal: float = 3.0
    vertical_up: float = 2.5
    vertical_down: float = 3.75


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


def scale_tracking_result(
    result: TrackingResult,
    gain: OutputGain = OutputGain(),
) -> OutputTrackingResult:
    """Scale only at the output boundary; the input result is never mutated."""
    if result.eyes is None:
        return OutputTrackingResult(result.timestamp_ns, False, None, result.inference_ms)
    eyes = tuple(
        OutputEyeSignal(
            name=eye.name,
            x=eye.x * gain.horizontal,
            y=eye.y * (gain.vertical_down if eye.y > 0.0 else gain.vertical_up),
        )
        for eye in result.eyes
    )
    return OutputTrackingResult(result.timestamp_ns, True, (eyes[0], eyes[1]), result.inference_ms)
