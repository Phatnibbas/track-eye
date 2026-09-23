"""Real per-eye pupil quality from existing FaceMesh-derived signals.

No accepted thresholds exist, so gates stay explicitly uncalibrated: this
module measures and exposes diagnostics (geometry passthrough + temporal
velocity per eye). Compatibility mode preserves the current TRACKED_PUPIL
behavior (FaceMesh hit == both eyes); gated mode is available only once a
labeled tuning split freezes thresholds.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from .fallback import EyePupilObservation


@dataclass
class _EyeVelocity:
    x: float | None = None
    y: float | None = None
    t_s: float | None = None


class PupilQualityMonitor:
    """Per-eye geometry passthrough + temporal velocity from EyeSignals."""

    def __init__(self) -> None:
        self._prev: dict[str, _EyeVelocity] = {}

    def update(self, eyes, now_s: float, latency_ms: float = 0.0, target_eyes=None) -> tuple[EyePupilObservation, EyePupilObservation] | None:
        """Build independent per-eye observations; None when no face.

        One eye missing never fabricates the other: observations are built
        only for eyes actually present in the input pair.
        """
        if eyes is None:
            self.mark_missing()
            return None
        targets = {} if target_eyes is None else {eye.name: eye for eye in target_eyes}
        timestamp_ns = int(now_s * 1e9)
        observations: list[EyePupilObservation] = []
        for eye in eyes:
            target = targets.get(eye.name, eye)
            prev = self._prev.get(eye.name)
            if prev is None:
                prev = _EyeVelocity()
                self._prev[eye.name] = prev
            velocity = 0.0
            if prev.x is not None and prev.t_s is not None and now_s > prev.t_s:
                velocity = math.hypot(target.x - prev.x, target.y - prev.y) / (now_s - prev.t_s)
            self._prev[eye.name] = _EyeVelocity(target.x, target.y, now_s)
            quality = {
                "eye_width_px": eye.eye_width,
                "eyelid_aperture_px": eye.eyelid_aperture,
                "iris_radius_px": eye.iris_radius,
                "iris_inside_lid": eye.iris_inside_lid,
                "lid_overflow": eye.lid_overflow,
                "normalized_h": eye.raw_h,
                "normalized_v": eye.raw_v,
                "velocity_per_s": velocity,
                "gate": "uncalibrated",
            }
            observations.append(
                EyePupilObservation(
                    name=eye.name,
                    monotonic_ns=timestamp_ns,
                    x=target.x,
                    y=target.y,
                    valid=True,  # geometry extracted; NOT tracking truth
                    latency_ms=latency_ms,
                    quality=quality,
                )
            )
        if len(observations) != 2:
            return None
        return (observations[0], observations[1])

    def mark_missing(self) -> None:
        for state in self._prev.values():
            state.x = None
            state.y = None
            state.t_s = None
