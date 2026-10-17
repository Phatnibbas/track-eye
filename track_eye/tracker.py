"""Pure per-eye measurement plus FaceMesh lifecycle and EMA state."""

from __future__ import annotations

import math
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
ROI_PADDING = 1.8
REFERENCE_SECONDS = 0.6


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
    eyelid_aperture: float = 0.0
    iris_inside_lid: float = 0.0
    lid_overflow: float = 0.0
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
        "aperture": eye_h,
        "iris_inside_lid": float(np.linalg.norm(iris_c - (top + bottom) * 0.5) / max(eye_h * 0.5, 1e-6)),
        "lid_overflow": max(0.0, (float(np.linalg.norm(iris_c - (top + bottom) * 0.5)) + iris_r - eye_h * 0.5) / max(eye_h * 0.5, 1e-6)),
        "h": h,
        "v": v,
    }


class EyeTracker:
    """One FaceMesh graph, with native-pixel ROI acquisition and warm tracking.

    The short-lived reference is geometric association only. A failed mesh
    always clears pupil output and EMA, even while that reference remains.
    """

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
        self._tracking = False
        self._mode = "full_frame"
        self._reason = "Awaiting acquisition"
        self._roi_px: tuple[int, int, int, int] | None = None
        self._frame_size: tuple[int, int] | None = None
        self._reference: tuple[float, float, float, float] | None = None
        self._last_success_s: float | None = None
        self._mesh_dirty = False
        self._unfiltered: dict | None = None

    def _clear_temporal(self, *, reset_graph: bool = True) -> None:
        if reset_graph and self._mesh_dirty:
            self._mesh.reset()
            self._mesh_dirty = False
        self._tracking = False
        self._unfiltered = None
        for smoother in self._smoothers.values():
            smoother.reset()

    def reset(self) -> None:
        """Forget both graph coordinates and pupil history, including any ROI."""
        self._clear_temporal()
        self._reference = None
        self._last_success_s = None
        self._frame_size = None
        self._mode = "full_frame"
        self._roi_px = None
        self._reason = "Explicit reset"

    @staticmethod
    def _valid_box(box) -> tuple[float, float, float, float] | None:
        if box is None:
            return None
        try:
            x, y, width, height = (float(value) for value in box)
        except (TypeError, ValueError, OverflowError):
            return None
        if not all(math.isfinite(value) for value in (x, y, width, height)):
            return None
        if width <= 0.0 or height <= 0.0:
            return None
        left, top = max(0.0, x), max(0.0, y)
        right, bottom = min(1.0, x + width), min(1.0, y + height)
        if right <= left or bottom <= top:
            return None
        return left, top, right - left, bottom - top

    @staticmethod
    def _overlaps(first, second) -> bool:
        return (
            min(first[0] + first[2], second[0] + second[2]) > max(first[0], second[0])
            and min(first[1] + first[3], second[1] + second[3]) > max(first[1], second[1])
        )

    @staticmethod
    def _crop_box(box, width: int, height: int) -> tuple[int, int, int, int]:
        x, y, box_width, box_height = box
        pad_x = box_width * (ROI_PADDING - 1.0) * 0.5
        pad_y = box_height * (ROI_PADDING - 1.0) * 0.5
        left = max(0, math.floor((x - pad_x) * width))
        top = max(0, math.floor((y - pad_y) * height))
        right = min(width, math.ceil((x + box_width + pad_x) * width))
        bottom = min(height, math.ceil((y + box_height + pad_y) * height))
        return left, top, right - left, bottom - top

    def reference_box(self, now_s: float | None = None) -> tuple[float, float, float, float] | None:
        now = time.monotonic() if now_s is None else now_s
        if self._last_success_s is not None and now - self._last_success_s > REFERENCE_SECONDS:
            self._reference = None
            self._last_success_s = None
        return self._reference

    def diagnostics(self) -> dict:
        return {
            "mode": self._mode,
            "reason": self._reason,
            "roi_px": list(self._roi_px) if self._roi_px is not None else None,
            "tracking": self._tracking,
            "unfiltered": self._unfiltered,
        }

    def process(
        self, frame: np.ndarray, face_box=None, *, now_s: float | None = None
    ) -> TrackingResult:
        started = time.perf_counter_ns()
        now = time.monotonic() if now_s is None else now_s
        height, width = frame.shape[:2]
        if self._frame_size is not None and self._frame_size != (width, height):
            self.reset()
        self._frame_size = (width, height)
        reference = self.reference_box(now)
        if self._tracking and reference is None:
            self._clear_temporal()
        proposal = self._valid_box(face_box)

        def lost(reason: str, *, reset_graph: bool = True) -> TrackingResult:
            self._clear_temporal(reset_graph=reset_graph)
            self._reason = reason
            return TrackingResult(
                time.time_ns(), False, None, (time.perf_counter_ns() - started) / 1_000_000.0
            )

        if proposal is not None and reference is not None and not self._overlaps(proposal, reference):
            return lost("Detector proposal does not overlap the active face")

        # A healthy full-frame track remains full-frame. A healthy ROI track
        # follows accepted mesh bounds even when the current detector misses.
        crop_source = reference if self._tracking and self._mode == "roi" else None
        if not self._tracking:
            crop_source = proposal
        mode = "roi" if crop_source is not None else "full_frame"
        if mode != self._mode:
            self._clear_temporal()
        self._mode = mode
        self._roi_px = self._crop_box(crop_source, width, height) if crop_source is not None else None
        if self._roi_px is None:
            left, top, crop_width, crop_height = 0, 0, width, height
            sample = frame
        else:
            left, top, crop_width, crop_height = self._roi_px
            sample = frame[top:top + crop_height, left:left + crop_width]
        if crop_width <= 0 or crop_height <= 0:
            return lost("Empty image region")

        was_tracking = self._tracking
        self._mesh_dirty = True
        result = self._mesh.process(cv2.cvtColor(sample, cv2.COLOR_BGR2RGB))
        inference_ms = (time.perf_counter_ns() - started) / 1_000_000.0
        if not result.multi_face_landmarks:
            return lost("No mesh in the current image region", reset_graph=was_tracking)

        landmarks = result.multi_face_landmarks[0].landmark
        if len(landmarks) < 478:
            return lost("Mesh has no refined iris landmarks")
        # Convert crop-normalized coordinates directly to ORIGINAL pixels.
        # Never resize/prewarp: eye widths, apertures and overlay geometry all
        # use the same full-image pixel metric before measure_eye is called.
        pixels = np.asarray(
            [[left + point.x * crop_width, top + point.y * crop_height] for point in landmarks],
            dtype=np.float64,
        )
        if not np.isfinite(pixels).all():
            return lost("Nonfinite mesh geometry")
        bounds_min = pixels.min(axis=0)
        bounds_max = pixels.max(axis=0)
        accepted_box = self._valid_box((
            bounds_min[0] / width, bounds_min[1] / height,
            (bounds_max[0] - bounds_min[0]) / width, (bounds_max[1] - bounds_min[1]) / height,
        ))
        if accepted_box is None:
            return lost("Mesh has no visible face bounds")
        if reference is not None and not self._overlaps(accepted_box, reference):
            return lost("Mesh does not overlap the active face")
        if proposal is not None and not self._overlaps(accepted_box, proposal):
            return lost("Mesh does not overlap the selected detector face")
        signals = []
        unfiltered = {}
        for side, definition, iris_group in zip(("left", "right"), EYE_DEFINITIONS, IRIS_GROUPS):
            measured = measure_eye(pixels, definition, iris_group)
            orientation = 1.0 if measured["u"][0] >= 0.0 else -1.0
            unfiltered[side] = {"x": measured["h"] * orientation, "y": measured["v"] * orientation}
            smooth_h, smooth_v = self._smoothers[measured["name"]].update(measured["h"], measured["v"])
            signals.append(
                EyeSignal(
                    name=measured["name"],
                    x=smooth_h * orientation,
                    y=smooth_v * orientation,
                    raw_h=smooth_h,
                    raw_v=smooth_v,
                    contour=measured["contour"],
                    eye_center=measured["eye_center"],
                    iris_center=measured["iris_center"],
                    iris_radius=measured["iris_radius"],
                    eye_width=measured["width"],
                    eyelid_aperture=measured["aperture"],
                    iris_inside_lid=measured["iris_inside_lid"],
                    lid_overflow=measured["lid_overflow"],
                    axis_x=measured["axis_x"],
                    axis_y=measured["axis_y"],
                )
            )
        self._tracking = True
        self._unfiltered = unfiltered
        self._reference = accepted_box
        self._last_success_s = time.monotonic() if now_s is None else now
        self._reason = "Tracking accepted mesh" if reference is not None else "Acquired mesh"
        return TrackingResult(time.time_ns(), True, (signals[0], signals[1]), inference_ms)

    def close(self) -> None:
        self._mesh.close()
