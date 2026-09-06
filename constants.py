"""Static indices and calibration targets for the gaze control demo."""

from __future__ import annotations

from dataclasses import dataclass


# MediaPipe Face Mesh landmark indices for both eyes.
# These indices are stable for the 478-point topology returned by
# FaceMesh(refine_landmarks=True).
EYE_DEFINITIONS = [
    {
        "name": "eye_33_133",
        # Eye corners around the eye whose main corners are 33 and 133.
        "corners": (33, 133),
        "top": (159, 160, 161, 158),
        "bottom": (145, 153, 154, 155),
        "contour": (
            33,
            7,
            163,
            144,
            145,
            153,
            154,
            155,
            133,
            173,
            157,
            158,
            159,
            160,
            161,
            246,
        ),
    },
    {
        "name": "eye_362_263",
        # Eye corners around the eye whose main corners are 362 and 263.
        "corners": (362, 263),
        "top": (386, 387, 388, 384),
        "bottom": (374, 380, 381, 382),
        "contour": (
            362,
            382,
            381,
            380,
            374,
            373,
            390,
            249,
            263,
            466,
            388,
            387,
            386,
            385,
            384,
            398,
        ),
    },
]


# The two 4-point iris rings added when refine_landmarks=True.
IRIS_GROUPS = (
    (469, 470, 471, 472),
    (474, 475, 476, 477),
)


# Orbital height reference landmarks (brow/cheek) for vertical normalization.
# These are more stable than eyelid landmarks for raw vertical gaze signal.
# Keys must match EYE_DEFINITIONS[*]["name"].
ORBITAL_LANDMARKS = {
    "eye_33_133": {
        "brow": (105, 66),
        "cheek": (117, 118),
    },
    "eye_362_263": {
        "brow": (334, 296),
        "cheek": (346, 347),
    },
}


FEATURE_NAMES = ["left_eye_x", "left_eye_y", "right_eye_x", "right_eye_y"]


@dataclass(frozen=True)
class CalibrationPointSpec:
    """Target point used during on-screen calibration."""

    name: str
    target: tuple[float, float]
    screen_position: tuple[float, float]


# y_ctrl convention: up = -1, down = +1.
CALIBRATION_POINTS_AXIS5 = [
    CalibrationPointSpec("center", (0.0, 0.0), (0.50, 0.50)),
    CalibrationPointSpec("left", (-1.0, 0.0), (0.18, 0.50)),
    CalibrationPointSpec("right", (1.0, 0.0), (0.82, 0.50)),
    CalibrationPointSpec("up", (0.0, -1.0), (0.50, 0.18)),
    CalibrationPointSpec("down", (0.0, 1.0), (0.50, 0.82)),
]

CALIBRATION_POINTS_GRID9 = [
    CalibrationPointSpec("center", (0.0, 0.0), (0.50, 0.50)),
    CalibrationPointSpec("left", (-1.0, 0.0), (0.18, 0.50)),
    CalibrationPointSpec("right", (1.0, 0.0), (0.82, 0.50)),
    CalibrationPointSpec("up", (0.0, -1.0), (0.50, 0.18)),
    CalibrationPointSpec("down", (0.0, 1.0), (0.50, 0.82)),
    CalibrationPointSpec("upper_left", (-1.0, -1.0), (0.18, 0.18)),
    CalibrationPointSpec("upper_right", (1.0, -1.0), (0.82, 0.18)),
    CalibrationPointSpec("lower_left", (-1.0, 1.0), (0.18, 0.82)),
    CalibrationPointSpec("lower_right", (1.0, 1.0), (0.82, 0.82)),
]

# Default to axis5 for backward compatibility
CALIBRATION_POINTS = CALIBRATION_POINTS_AXIS5
