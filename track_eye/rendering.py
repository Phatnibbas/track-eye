"""OpenCV presentation only; never changes the tracking signal."""

from __future__ import annotations

import cv2
import numpy as np

from .output import OutputEyeSignal, OutputTrackingResult

FONT = cv2.FONT_HERSHEY_SIMPLEX
GREEN = (0, 220, 0)
RED = (0, 0, 255)
CYAN = (255, 255, 0)
YELLOW = (0, 220, 220)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RIN_FILL = (150, 70, 130)
RIN_RIM = (215, 150, 225)
RIN_RIPPLE = (235, 200, 240)
RIN_CORE = (60, 20, 55)
RIN_AXIS = (230, 210, 240)
ARROW_AMP = 2.6
ARROW_MAX = 1.5


def draw_face_marker(frame: np.ndarray, eye: EyeSignal) -> None:
    center = tuple(int(value) for value in eye.eye_center)
    iris = tuple(int(value) for value in eye.iris_center)
    contour = np.asarray(eye.contour, dtype=np.int32)
    cv2.polylines(frame, [contour], True, (0, 120, 0), 1, cv2.LINE_AA)
    cv2.circle(frame, iris, int(eye.iris_radius), CYAN, 1, cv2.LINE_AA)
    cv2.circle(frame, iris, 2, RED, -1, cv2.LINE_AA)
    cv2.line(frame, (center[0] - 5, center[1]), (center[0] + 5, center[1]), WHITE, 1, cv2.LINE_AA)
    cv2.line(frame, (center[0], center[1] - 5), (center[0], center[1] + 5), WHITE, 1, cv2.LINE_AA)
    vector = (eye.raw_h * np.asarray(eye.axis_x) + eye.raw_v * np.asarray(eye.axis_y)) * ARROW_AMP
    magnitude = float(np.linalg.norm(vector))
    if magnitude > ARROW_MAX:
        vector = vector / magnitude * ARROW_MAX
    tip = np.asarray(eye.eye_center) + vector * max(eye.eye_width, 1.0)


def _clamp(value: float, minimum: float = -1.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def draw_gauge(
    frame: np.ndarray,
    center: tuple[int, int],
    size: int,
    eye: OutputEyeSignal | None,
    label: str,
) -> None:
    outer = size // 2 - 8
    track = outer - 20
    overlay = frame.copy()
    cv2.circle(overlay, center, outer + 10, (55, 25, 50), -1, cv2.LINE_AA)
    cv2.circle(overlay, center, outer, RIN_FILL, -1, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.5, frame, 0.5, 0.0, frame)
    for index in range(1, 7):
        cv2.circle(frame, center, int(outer * index / 6), RIN_RIPPLE, 1, cv2.LINE_AA)
    cv2.circle(frame, center, outer, RIN_RIM, 2, cv2.LINE_AA)
    cv2.arrowedLine(frame, (center[0] - outer + 16, center[1]), (center[0] + outer - 8, center[1]), RIN_AXIS, 1, tipLength=0.05)
    cv2.arrowedLine(frame, (center[0], center[1] + outer - 16), (center[0], center[1] - outer + 8), RIN_AXIS, 1, tipLength=0.05)
    cv2.circle(frame, center, max(6, size // 16), RIN_CORE, -1, cv2.LINE_AA)
    cv2.circle(frame, center, max(3, size // 30), BLACK, -1, cv2.LINE_AA)
    if eye is not None:
        x_value = _clamp(eye.x, -1.5, 1.5)
        y_value = _clamp(eye.y, -1.5, 1.5)
        dot = (int(round(center[0] + track * x_value)), int(round(center[1] + track * y_value)))
        cv2.line(frame, center, dot, (235, 220, 245), 1, cv2.LINE_AA)
        cv2.circle(frame, dot, 9, WHITE, -1, cv2.LINE_AA)
        cv2.circle(frame, dot, 6, GREEN, -1, cv2.LINE_AA)
    cv2.putText(frame, label, (center[0] - int(size * 0.34), center[1] - outer - 10), FONT, 0.42, WHITE, 1, cv2.LINE_AA)
    for text, position in (("L", (center[0] - outer - 10, center[1] + 5)), ("R", (center[0] + outer + 2, center[1] + 5)), ("U", (center[0] - 6, center[1] - outer - 8)), ("D", (center[0] - 6, center[1] + outer + 18))):
        cv2.putText(frame, text, position, FONT, 0.44, WHITE, 1, cv2.LINE_AA)


def render_frame(
    frame: np.ndarray,
    result: TrackingResult,
    output: OutputTrackingResult,
    fps: float,
    shadow: dict | None = None,
) -> np.ndarray:
    if result.eyes is not None:
        for eye in result.eyes:
            draw_face_marker(frame, eye)
    height, width = frame.shape[:2]
    margin, gap = 18, 18
    size = max(110, min(160, (width - (2 * margin) - gap) // 2))
    radius = size // 2
    baseline_y = height - margin - radius
    centers = [(width - margin - gap - size - radius, baseline_y), (width - margin - radius, baseline_y)]
    eyes = output.eyes or (None, None)
    for center, eye, label in zip(centers, eyes, ("LEFT EYE", "RIGHT EYE")):
        draw_gauge(frame, center, size, eye, label)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (width, 34), (18, 18, 28), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0.0, frame)
    status = "BOTH PUPILS TRACKED" if result.face_detected else "NO FACE"
    cv2.putText(frame, f"PUPIL TRACKING  |  FPS {fps:4.1f}  |  {status}", (8, 23), FONT, 0.6, GREEN if result.face_detected else RED, 2, cv2.LINE_AA)
    if shadow is not None:
        source = str(shadow.get("shadow_source", "NONE"))
        states = shadow.get("shadow_states", ["?", "?"])
        cv2.putText(
            frame,
            f"SHADOW {source} L:{states[0]} R:{states[1]} emission={shadow.get('emission', 'disabled-shadow-only')}",
            (8, 52),
            FONT, 0.5, YELLOW, 1, cv2.LINE_AA,
        )
    return frame
