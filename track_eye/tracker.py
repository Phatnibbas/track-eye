"""Pure per-eye measurement plus FaceMesh lifecycle and EMA state."""

from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

EYE_DEFINITIONS = (
    {
        "name": "eye_33_133",
        "corners": (33, 133),
        "top": (159, 160, 161, 158),
        "bottom": (145, 153, 154, 155),
        "contour": (33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246),
    },
    {
        "name": "eye_362_263",
        "corners": (362, 263),
        "top": (386, 387, 388, 384),
        "bottom": (374, 380, 381, 382),
        "contour": (362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398),
    },
)
IRIS_GROUPS = ((469, 470, 471, 472), (474, 475, 476, 477))
EMA_ALPHA = 0.45


@dataclass(frozen=True)
class EyeSignal:
    name: str
    x: float
    y: float
    raw_h: float
    raw_v: float
    # Presentation-only geometry; x/y remain the stable consumer contract.
    contour: tuple[tuple[int, int], ...] = ()
    eye_center: tuple[float, float] = (0.0, 0.0)
    iris_center: tuple[float, float] = (0.0, 0.0)
    iris_radius: float = 0.0
    eye_width: float = 0.0
    axis_x: tuple[float, float] = (1.0, 0.0)
    axis_y: tuple[float, float] = (0.0, 1.0)


@dataclass(frozen=True)
class TrackingResult:
    timestamp_ns: int
    face_detected: bool
    eyes: tuple[EyeSignal, EyeSignal] | None
    inference_ms: float


class EyeSmoother:
    def __init__(self, alpha: float = EMA_ALPHA):
        if not 0.0 < alpha <= 1.0:
            raise ValueError("EMA alpha must be in (0, 1]")
        self.alpha = float(alpha)
        self.h: float | None = None
        self.v: float | None = None

    def update(self, h: float, v: float) -> tuple[float, float]:
        if self.h is None:
            self.h, self.v = float(h), float(v)
        else:
            self.h = self.alpha * h + (1.0 - self.alpha) * self.h
            self.v = self.alpha * v + (1.0 - self.alpha) * self.v
        return self.h, self.v  # type: ignore[return-value]

    def reset(self) -> None:
        self.h = None
        self.v = None


def _mean(points: list[np.ndarray]) -> np.ndarray:
    return np.mean(np.asarray(points, dtype=np.float64), axis=0)


def measure_eye(px: np.ndarray, eyedef: dict, iris_group: tuple[int, ...]) -> dict:
    """Measure one eye in its local corner/lid axes, before canonical mapping."""
    c0 = px[eyedef["corners"][0]]
    c1 = px[eyedef["corners"][1]]
    top = _mean([px[index] for index in eyedef["top"]])
    bottom = _mean([px[index] for index in eyedef["bottom"]])
    ring = [px[index] for index in iris_group]
    iris_c = _mean(ring)
    iris_r = float(np.mean([np.linalg.norm(point - iris_c) for point in ring]))
    eye_center = (c0 + c1) * 0.5
    axis_x = c1 - c0
    width = float(np.linalg.norm(axis_x))
    axis_x = axis_x / max(width, 1e-6)
    axis_y = np.array([-axis_x[1], axis_x[0]])
    eye_h = float(np.linalg.norm(top - bottom))
    disp = iris_c - eye_center
    h = float(np.dot(disp, axis_x) / max(width * 0.5, 1e-6))
    v = float(np.dot(disp, axis_y) / max(eye_h * 0.5, 1e-6))
    return {
        "name": eyedef["name"],
        "contour": tuple(tuple(int(value) for value in px[index]) for index in eyedef["contour"]),
        "eye_center": tuple(float(value) for value in eye_center),
        "iris_center": tuple(float(value) for value in iris_c),
        "iris_radius": iris_r,
        "axis_x": tuple(float(value) for value in axis_x),
        "axis_y": tuple(float(value) for value in axis_y),
        "u": axis_x,
        "v_axis": axis_y,
        "width": width,
        "h": h,
        "v": v,
    }


class EyeTracker:
    """Own one MediaPipe FaceMesh instance and deterministic eye EMA state."""

    def __init__(
        self,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
        ema_alpha: float = EMA_ALPHA,
    ):
        import mediapipe as mp

        self._mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._smoothers = {definition["name"]: EyeSmoother(ema_alpha) for definition in EYE_DEFINITIONS}

    def reset(self) -> None:
        for smoother in self._smoothers.values():
            smoother.reset()

    def process(self, frame: np.ndarray) -> TrackingResult:
        started = time.perf_counter_ns()
        height, width = frame.shape[:2]
        result = self._mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        inference_ms = (time.perf_counter_ns() - started) / 1_000_000.0
        if not result.multi_face_landmarks:
            return TrackingResult(time.time_ns(), False, None, inference_ms)

        landmarks = result.multi_face_landmarks[0].landmark
        pixels = np.asarray([[point.x * width, point.y * height] for point in landmarks], dtype=np.float64)
        signals = []
        for definition, iris_group in zip(EYE_DEFINITIONS, IRIS_GROUPS):
            measured = measure_eye(pixels, definition, iris_group)
            smooth_h, smooth_v = self._smoothers[measured["name"]].update(measured["h"], measured["v"])
            orientation = 1.0 if measured["u"][0] >= 0.0 else -1.0
            signals.append(
                EyeSignal(
                    name=measured["name"],
                    x=smooth_h * orientation,
                    y=smooth_v * orientation,
                    raw_h=smooth_h,
                    contour=measured["contour"],
                    eye_center=measured["eye_center"],
                    iris_center=measured["iris_center"],
                    iris_radius=measured["iris_radius"],
                    eye_width=measured["width"],
                    axis_x=measured["axis_x"],
                    axis_y=measured["axis_y"],
                )
            )
        return TrackingResult(time.time_ns(), True, (signals[0], signals[1]), inference_ms)

    def close(self) -> None:
        self._mesh.close()
