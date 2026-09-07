"""Thread-safe live output calibration and persistence."""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path

from .output import EyeNeutral, OutputCalibration, OutputGain, OutputTrackingResult, scale_tracking_result
from .tracker import TrackingResult

GAIN_MIN = 0.1
GAIN_MAX = 10.0
LIMIT_MIN = 1.0
LIMIT_MAX = 3.0
NEUTRAL_SECONDS = 1.0


def _finite_number(value: object, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def calibration_to_dict(calibration: OutputCalibration) -> dict:
    return {
        "schema_version": 1,
        "gain": asdict(calibration.gain),
        "neutrals": [asdict(neutral) for neutral in calibration.neutrals],
    }


def calibration_from_dict(value: dict) -> OutputCalibration:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("unsupported output calibration schema")
    gain_value = value.get("gain")
    neutrals_value = value.get("neutrals", [])
    if not isinstance(gain_value, dict) or not isinstance(neutrals_value, list):
        raise ValueError("invalid output calibration document")
    gain = OutputGain(
        left=_finite_number(gain_value.get("left"), "left", GAIN_MIN, GAIN_MAX),
        right=_finite_number(gain_value.get("right"), "right", GAIN_MIN, GAIN_MAX),
        up=_finite_number(gain_value.get("up"), "up", GAIN_MIN, GAIN_MAX),
        down=_finite_number(gain_value.get("down"), "down", GAIN_MIN, GAIN_MAX),
        soft_limit=_finite_number(gain_value.get("soft_limit"), "soft_limit", LIMIT_MIN, LIMIT_MAX),
    )
    neutrals = []
    for item in neutrals_value:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("invalid eye neutral")
        neutrals.append(
            EyeNeutral(
                item["name"],
                _finite_number(item.get("x"), "neutral x", -2.0, 2.0),
                _finite_number(item.get("y"), "neutral y", -2.0, 2.0),
            )
        )
    return OutputCalibration(gain, tuple(neutrals))


class OutputTuner:
    def __init__(self, path: Path, default_gain: OutputGain = OutputGain()):
        self.path = path
        self._lock = threading.Lock()
        self._default = OutputCalibration(default_gain)
        self._calibration = self._default
        self._dirty = False
        self._load_error: str | None = None
        self._neutral_state = "idle"
        self._neutral_started_at: float | None = None
        self._neutral_samples: dict[str, list[tuple[float, float]]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            self._calibration = calibration_from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._load_error = str(exc)

    def update_gain(self, values: dict) -> dict:
        if not isinstance(values, dict):
            raise ValueError("JSON object required")
        with self._lock:
            current = self._calibration.gain
            gain = replace(
                current,
                left=_finite_number(values.get("left", current.left), "left", GAIN_MIN, GAIN_MAX),
                right=_finite_number(values.get("right", current.right), "right", GAIN_MIN, GAIN_MAX),
                up=_finite_number(values.get("up", current.up), "up", GAIN_MIN, GAIN_MAX),
                down=_finite_number(values.get("down", current.down), "down", GAIN_MIN, GAIN_MAX),
                soft_limit=_finite_number(values.get("soft_limit", current.soft_limit), "soft_limit", LIMIT_MIN, LIMIT_MAX),
            )
            self._calibration = replace(self._calibration, gain=gain)
            self._dirty = True
            return self._status_locked()

    def request_neutral(self) -> dict:
        with self._lock:
            self._neutral_state = "waiting_for_face"
            self._neutral_started_at = None
            self._neutral_samples = {}
            return self._status_locked()

    def reset(self) -> dict:
        with self._lock:
            self._calibration = self._default
            self._dirty = True
            self._neutral_state = "idle"
            self._neutral_started_at = None
            self._neutral_samples = {}
            return self._status_locked()

    def save(self) -> dict:
        with self._lock:
            document = calibration_to_dict(self._calibration)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)
            self._dirty = False
            self._load_error = None
            return self._status_locked()

    def process(self, result: TrackingResult) -> OutputTrackingResult:
        now = time.perf_counter()
        with self._lock:
            if self._neutral_state != "idle":
                if result.eyes is None:
                    self._neutral_state = "waiting_for_face"
                    self._neutral_started_at = None
                    self._neutral_samples = {}
                else:
                    if self._neutral_started_at is None:
                        self._neutral_started_at = now
                        self._neutral_state = "collecting"
                    for eye in result.eyes:
                        self._neutral_samples.setdefault(eye.name, []).append((eye.x, eye.y))
                    if now - self._neutral_started_at >= NEUTRAL_SECONDS:
                        neutrals = tuple(
                            EyeNeutral(
                                name,
                                sum(sample[0] for sample in samples) / len(samples),
                                sum(sample[1] for sample in samples) / len(samples),
                            )
                            for name, samples in sorted(self._neutral_samples.items())
                            if samples
                        )
                        self._calibration = replace(self._calibration, neutrals=neutrals)
                        self._neutral_state = "idle"
                        self._neutral_started_at = None
                        self._neutral_samples = {}
                        self._dirty = True
            calibration = self._calibration
        return scale_tracking_result(result, calibration)

    def status(self) -> dict:
        with self._lock:
            return self._status_locked()

    def _status_locked(self) -> dict:
        remaining = None
        if self._neutral_state == "collecting" and self._neutral_started_at is not None:
            remaining = max(0.0, NEUTRAL_SECONDS - (time.perf_counter() - self._neutral_started_at))
        return {
            "calibration": calibration_to_dict(self._calibration),
            "dirty": self._dirty,
            "load_error": self._load_error,
            "neutral_state": self._neutral_state,
            "neutral_remaining_seconds": remaining,
            "path": str(self.path),
        }
