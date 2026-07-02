"""Simple realtime signal helpers."""

from __future__ import annotations

from dataclasses import dataclass


def clamp(value: float, minimum: float = -1.0, maximum: float = 1.0) -> float:
    """Clamp a float into the provided range."""

    return max(minimum, min(maximum, value))


def apply_dead_zone(value: float, dead_zone: float) -> float:
    """Remove tiny movements around zero while preserving full scale outside."""

    dead_zone = max(0.0, min(0.95, dead_zone))
    magnitude = abs(value)
    if magnitude <= dead_zone:
        return 0.0

    scaled = (magnitude - dead_zone) / (1.0 - dead_zone)
    return clamp((1.0 if value >= 0.0 else -1.0) * scaled)


@dataclass
class EMAFilter:
    """Single-value exponential moving average filter."""

    alpha: float
    value: float | None = None

    def update(self, sample: float) -> float:
        if self.value is None:
            self.value = sample
        else:
            self.value = (self.alpha * sample) + ((1.0 - self.alpha) * self.value)
        return self.value

    def reset(self, value: float | None = None) -> None:
        self.value = value
