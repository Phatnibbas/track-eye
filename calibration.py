"""Calibration model and calibration session management."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from calibration_coupled import CoupledCalibrationModel
from calibration_quality import evaluate_coupled_quality
from constants import (
    CALIBRATION_POINTS_AXIS5,
    CALIBRATION_POINTS_GRID9,
    FEATURE_NAMES,
    CalibrationPointSpec,
)
from filters import clamp


FEATURE_SPACE_VERSION = "iris_width_vertical_v4"


def _as_feature4(vec: np.ndarray) -> np.ndarray | None:
    """Validate and normalize a 4-element feature vector.
    
    Returns None if the vector contains NaN/Inf or wrong shape.
    """
    if vec is None:
        return None
    arr = np.asarray(vec, dtype=np.float64).ravel()
    if arr.shape[0] != 4:
        return None
    if not np.all(np.isfinite(arr)):
        return None
    return arr


@dataclass
class LinearCalibrationModel:
    """Lightweight serializable linear model for x/y control prediction."""

    coefficients: np.ndarray
    intercepts: np.ndarray
    feature_names: list[str]
    training_features: list[list[float]] = field(default_factory=list)
    training_targets: list[list[float]] = field(default_factory=list)
    point_names: list[str] = field(default_factory=list)
    ridge_alpha: float = 1.0
    feature_space: str = FEATURE_SPACE_VERSION

    def predict(self, feature_vector: np.ndarray) -> tuple[float, float]:
        raw_x, raw_y = self.predict_raw(feature_vector)
        return clamp(raw_x), clamp(raw_y)

    def predict_raw(self, feature_vector: np.ndarray) -> tuple[float, float]:
        vector = np.asarray(feature_vector, dtype=np.float64)
        output = (self.coefficients @ vector) + self.intercepts
        return float(output[0]), float(output[1])

    def training_prediction_stats(self) -> dict[str, float]:
        if not self.training_features:
            return {
                "min_x": 0.0,
                "max_x": 0.0,
                "min_y": 0.0,
                "max_y": 0.0,
                "max_abs_x": 0.0,
                "max_abs_y": 0.0,
            }

        predictions = np.asarray(
            [
                self.predict_raw(np.asarray(row, dtype=np.float64))
                for row in self.training_features
            ],
            dtype=np.float64,
        )
        return {
            "min_x": float(np.min(predictions[:, 0])),
            "max_x": float(np.max(predictions[:, 0])),
            "min_y": float(np.min(predictions[:, 1])),
            "max_y": float(np.max(predictions[:, 1])),
            "max_abs_x": float(np.max(np.abs(predictions[:, 0]))),
            "max_abs_y": float(np.max(np.abs(predictions[:, 1]))),
        }

    def is_usable(self, min_abs_x: float, min_abs_y: float) -> bool:
        if not self.training_features:
            return False

        stats = self.training_prediction_stats()
        return stats["max_abs_x"] >= min_abs_x and stats["max_abs_y"] >= min_abs_y

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 2,
            "feature_names": self.feature_names,
            "coefficients": self.coefficients.tolist(),
            "intercepts": self.intercepts.tolist(),
            "training_features": self.training_features,
            "training_targets": self.training_targets,
            "point_names": self.point_names,
            "ridge_alpha": self.ridge_alpha,
            "feature_space": self.feature_space,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LinearCalibrationModel":
        feature_names = list(payload.get("feature_names", FEATURE_NAMES))
        coefficients = np.asarray(payload["coefficients"], dtype=np.float64)
        intercepts = np.asarray(payload["intercepts"], dtype=np.float64)

        if coefficients.ndim != 2:
            raise ValueError("Calibration coefficients must be a 2D matrix")
        if intercepts.ndim != 1 or intercepts.shape[0] != 2:
            raise ValueError("Calibration intercepts must have shape (2,)")
        if coefficients.shape[0] != 2:
            raise ValueError("Calibration coefficients must have shape (2, n_features)")
        if coefficients.shape[1] != len(feature_names):
            raise ValueError("Calibration feature count does not match feature_names")

        return cls(
            coefficients=coefficients,
            intercepts=intercepts,
            feature_names=feature_names,
            training_features=[
                list(map(float, row)) for row in payload.get("training_features", [])
            ],
            training_targets=[
                list(map(float, row)) for row in payload.get("training_targets", [])
            ],
            point_names=list(payload.get("point_names", [])),
            ridge_alpha=float(payload.get("ridge_alpha", 1.0)),
            feature_space=str(payload.get("feature_space", "legacy_v1")),
        )


@dataclass
class AxisCalibrationModel:
    """5-point axis calibration model with independent X/Y mapping."""

    center_x: float
    left_x: float
    right_x: float
    center_y: float
    up_y: float
    down_y: float
    feature_names: list[str]
    y_left_weight: float = 0.5
    y_right_weight: float = 0.5
    training_features: list[list[float]] = field(default_factory=list)
    training_targets: list[list[float]] = field(default_factory=list)
    point_names: list[str] = field(default_factory=list)
    feature_space: str = FEATURE_SPACE_VERSION

    def x_is_usable(self, min_abs_x: float) -> bool:
        left_delta = self.left_x - self.center_x
        right_delta = self.right_x - self.center_x
        return (
            abs(left_delta) >= min_abs_x
            and abs(right_delta) >= min_abs_x
            and np.sign(left_delta) != np.sign(right_delta)
        )

    def y_is_usable(self, min_abs_y: float) -> bool:
        up_delta = self.up_y - self.center_y
        down_delta = self.down_y - self.center_y
        return (
            abs(up_delta) >= min_abs_y
            and abs(down_delta) >= min_abs_y
            and np.sign(up_delta) != np.sign(down_delta)
        )

    def predict(self, feature_vector: np.ndarray) -> tuple[float, float]:
        raw_x, raw_y = self.predict_raw(feature_vector)
        return clamp(raw_x), clamp(raw_y)

    def predict_raw(self, feature_vector: np.ndarray) -> tuple[float, float]:
        vector = np.asarray(feature_vector, dtype=np.float64)
        if not np.all(np.isfinite(vector[:4])):
            return 0.0, 0.0
        fx = float(np.mean([vector[0], vector[2]]))
        fy = float((self.y_left_weight * vector[1]) + (self.y_right_weight * vector[3]))
        x_ctrl = self._piecewise_map(
            value=fx,
            center=self.center_x,
            anchor_a=self.left_x,
            target_a=-1.0,
            anchor_b=self.right_x,
            target_b=1.0,
        )
        y_ctrl = self._piecewise_map(
            value=fy,
            center=self.center_y,
            anchor_a=self.up_y,
            target_a=-1.0,
            anchor_b=self.down_y,
            target_b=1.0,
        )
        return float(x_ctrl), float(y_ctrl)

    def training_prediction_stats(self) -> dict[str, float]:
        left_delta = self.left_x - self.center_x
        right_delta = self.right_x - self.center_x
        up_delta = self.up_y - self.center_y
        down_delta = self.down_y - self.center_y

        if not self.training_features:
            return {
                "min_x": 0.0,
                "max_x": 0.0,
                "min_y": 0.0,
                "max_y": 0.0,
                "max_abs_x": 0.0,
                "max_abs_y": 0.0,
                "min_feature_abs_x": min(abs(left_delta), abs(right_delta)),
                "min_feature_abs_y": min(abs(up_delta), abs(down_delta)),
            }

        predictions = np.asarray(
            [
                self.predict_raw(np.asarray(row, dtype=np.float64))
                for row in self.training_features
            ],
            dtype=np.float64,
        )
        return {
            "min_x": float(np.min(predictions[:, 0])),
            "max_x": float(np.max(predictions[:, 0])),
            "min_y": float(np.min(predictions[:, 1])),
            "max_y": float(np.max(predictions[:, 1])),
            "max_abs_x": float(np.max(np.abs(predictions[:, 0]))),
            "max_abs_y": float(np.max(np.abs(predictions[:, 1]))),
            "min_feature_abs_x": float(min(abs(left_delta), abs(right_delta))),
            "min_feature_abs_y": float(min(abs(up_delta), abs(down_delta))),
        }

    def is_usable(self, min_abs_x: float, min_abs_y: float) -> bool:
        if not self.training_features:
            return False

        return self.x_is_usable(min_abs_x) or self.y_is_usable(min_abs_y)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 3,
            "model_type": "axis5",
            "feature_names": self.feature_names,
            "center_x": self.center_x,
            "left_x": self.left_x,
            "right_x": self.right_x,
            "center_y": self.center_y,
            "up_y": self.up_y,
            "down_y": self.down_y,
            "y_left_weight": self.y_left_weight,
            "y_right_weight": self.y_right_weight,
            "training_features": self.training_features,
            "training_targets": self.training_targets,
            "point_names": self.point_names,
            "feature_space": self.feature_space,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AxisCalibrationModel":
        return cls(
            center_x=float(payload["center_x"]),
            left_x=float(payload["left_x"]),
            right_x=float(payload["right_x"]),
            center_y=float(payload["center_y"]),
            up_y=float(payload["up_y"]),
            down_y=float(payload["down_y"]),
            feature_names=list(payload.get("feature_names", FEATURE_NAMES)),
            y_left_weight=float(payload.get("y_left_weight", 0.5)),
            y_right_weight=float(payload.get("y_right_weight", 0.5)),
            training_features=[
                list(map(float, row)) for row in payload.get("training_features", [])
            ],
            training_targets=[
                list(map(float, row)) for row in payload.get("training_targets", [])
            ],
            point_names=list(payload.get("point_names", [])),
            feature_space=str(payload.get("feature_space", "legacy_v1")),
        )

    @staticmethod
    def _piecewise_map(
        value: float,
        center: float,
        anchor_a: float,
        target_a: float,
        anchor_b: float,
        target_b: float,
    ) -> float:
        delta = value - center
        if abs(delta) < 1e-6:
            return 0.0

        candidates = []
        for anchor, target in ((anchor_a, target_a), (anchor_b, target_b)):
            anchor_delta = anchor - center
            if abs(anchor_delta) < 1e-6:
                continue
            if np.sign(anchor_delta) == np.sign(delta):
                candidates.append((anchor_delta, target))

        if not candidates:
            return 0.0

        anchor_delta, target = max(candidates, key=lambda item: abs(item[0]))
        return float((delta / anchor_delta) * target)


class CalibrationManager:
    """Handles 5-point calibration, fit, save, and load."""

    def __init__(self, config: dict[str, Any], default_model_path: str | Path):
        # Determine calibration points based on config.
        points_config = str(config.get("points", "axis5")).strip()
        if points_config not in {"axis5", "grid9"}:
            raise ValueError(
                f"Unsupported calibration.points={points_config!r}; use 'axis5' or 'grid9'"
            )
        self.points_mode = points_config
        self.points: list[CalibrationPointSpec] = (
            list(CALIBRATION_POINTS_GRID9)
            if self.points_mode == "grid9"
            else list(CALIBRATION_POINTS_AXIS5)
        )

        self.default_model_path = Path(default_model_path)
        self.settle_seconds = float(config.get("settle_seconds", 1.0))
        self.sample_seconds = float(config.get("sample_seconds", 1.2))
        self.min_confidence = float(config.get("min_confidence", 0.38))
        self.min_samples_per_point = int(config.get("min_samples_per_point", 12))
        self.min_stable_streak_frames = int(config.get("min_stable_streak_frames", 4))
        self.ridge_alpha = float(config.get("ridge_alpha", 1.0))
        self.max_eye_disagreement_x = float(config.get("max_eye_disagreement_x", 0.35))
        self.max_eye_disagreement_y = float(config.get("max_eye_disagreement_y", 0.35))
        self.min_axis_separation_x = float(config.get("min_axis_separation_x", 0.04))
        self.min_axis_separation_y = float(config.get("min_axis_separation_y", 0.06))
        self.y_fusion_mode = str(config.get("y_fusion_mode", "weighted")).strip()
        if self.y_fusion_mode not in {
            "mean",
            "weighted",
            "dominant_left",
            "dominant_right",
        }:
            raise ValueError(
                f"Unsupported calibration.y_fusion_mode={self.y_fusion_mode!r}; "
                "use 'mean', 'weighted', 'dominant_left', or 'dominant_right'"
            )
        self.quality_target_spread_x = float(
            config.get("quality_target_spread_x", 0.12)
        )
        self.quality_target_spread_y = float(
            config.get("quality_target_spread_y", 0.10)
        )
        self.recenter_alpha = float(config.get("recenter_alpha", 0.85))
        self.recenter_min_confidence = float(
            config.get("recenter_min_confidence", 0.35)
        )

        # Phase 3 coupled calibration config.
        self.mode = str(config.get("mode", "axis5")).strip()
        if self.mode not in {"axis5", "auto", "coupled_only"}:
            raise ValueError(
                f"Unsupported calibration.mode={self.mode!r}; "
                "use 'axis5', 'auto', or 'coupled_only'"
            )

        if self.mode == "coupled_only" and self.points_mode != "grid9":
            raise ValueError(
                "calibration.mode='coupled_only' requires calibration.points='grid9'"
            )

        self.coupled_basis = str(config.get("coupled_basis", "affine")).strip()
        if self.coupled_basis not in {"affine", "quadratic"}:
            raise ValueError(
                f"Unsupported calibration.coupled_basis={self.coupled_basis!r}; "
                "use 'affine' or 'quadratic'"
            )

        # Quality config for coupled models
        quality_config = config.get("quality", {})
        self.quality_loo_rmse_max = float(quality_config.get("loo_rmse_max", 0.45))
        self.quality_diagonal_rmse_max = float(
            quality_config.get("diagonal_rmse_max", 0.40)
        )
        self.quality_vertical_rmse_max = float(
            quality_config.get("vertical_rmse_max", 0.45)
        )
        self.quality_axis_leakage_max = float(
            quality_config.get("axis_leakage_max", 0.25)
        )
        self.quality_monotonicity_required = bool(
            quality_config.get("monotonicity_required", True)
        )

        # Model selection config
        selection_config = config.get("selection", {})
        self.min_score_margin = float(selection_config.get("min_score_margin", 0.05))
        self.min_rmse_delta = float(selection_config.get("min_rmse_delta", 0.03))
        self.selection_rmse_floor = float(selection_config.get("rmse_floor", 0.10))

        # Store quality config dict for evaluate_coupled_quality
        self._quality_config = {
            "loo_rmse_max": self.quality_loo_rmse_max,
            "diagonal_rmse_max": self.quality_diagonal_rmse_max,
            "vertical_rmse_max": self.quality_vertical_rmse_max,
            "axis_leakage_max": self.quality_axis_leakage_max,
            "monotonicity_required": self.quality_monotonicity_required,
        }

        self.model: (
            LinearCalibrationModel
            | AxisCalibrationModel
            | CoupledCalibrationModel
            | None
        ) = None
        self.active = False
        self.current_index = 0
        self.stage = "idle"
        self.stage_started_at = 0.0
        self.current_samples: list[np.ndarray] = []
        self.stable_streak = 0
        self.training_features: list[list[float]] = []
        self.training_targets: list[list[float]] = []
        self.point_names: list[str] = []
        self.last_quality_report: dict[str, Any] | None = None
        self.status_message = "Calibration not started"

    @property
    def has_model(self) -> bool:
        return self.model is not None

    def start(self) -> None:
        self.active = True
        self.current_index = 0
        self.stage = "settle"
        self.stage_started_at = time.monotonic()
        self.current_samples = []
        self.stable_streak = 0
        self.training_features = []
        self.training_targets = []
        self.point_names = []
        self.status_message = "Calibration started"

    def cancel(self) -> None:
        self.active = False
        self.stage = "idle"
        self.current_samples = []
        self.stable_streak = 0
        self.status_message = "Calibration cancelled"

    def reset_model(self) -> None:
        self.model = None
        self.active = False
        self.current_index = 0
        self.stage = "idle"
        self.stage_started_at = 0.0
        self.current_samples = []
        self.stable_streak = 0
        self.training_features = []
        self.training_targets = []
        self.point_names = []
        self.last_quality_report = None
        self.status_message = "Calibration reset"

    def apply_quick_kiosk_preset(self, config: dict[str, Any]) -> None:
        """Use shorter laptop-kiosk calibration timing for sequential users."""
        self.settle_seconds = float(
            config.get("kiosk_quick_settle_seconds", self.settle_seconds)
        )
        self.sample_seconds = float(
            config.get("kiosk_quick_sample_seconds", self.sample_seconds)
        )
        self.min_samples_per_point = int(
            config.get(
                "kiosk_quick_min_samples_per_point", self.min_samples_per_point
            )
        )

    def update(self, feature_vector: np.ndarray | None, confidence: float) -> None:
        if not self.active:
            return

        now = time.monotonic()
        point = self.points[self.current_index]

        if self.stage == "settle":
            remaining = max(0.0, self.settle_seconds - (now - self.stage_started_at))
            self.status_message = f"Look at {point.name.upper()} ({remaining:.1f}s)"
            if now - self.stage_started_at >= self.settle_seconds:
                self.stage = "collect"
                self.stage_started_at = now
                self.current_samples = []
                self.stable_streak = 0
            return

        is_stable_frame = (
            feature_vector is not None and confidence >= self.min_confidence
        )
        if is_stable_frame:
            self.stable_streak += 1
            if self.stable_streak >= self.min_stable_streak_frames:
                self.current_samples.append(
                    np.asarray(feature_vector, dtype=np.float64)
                )
        else:
            self.stable_streak = 0

        remaining = max(0.0, self.sample_seconds - (now - self.stage_started_at))
        self.status_message = (
            f"Collecting {point.name.upper()} ({remaining:.1f}s) - "
            f"accepted {len(self.current_samples)}/{self.min_samples_per_point} | "
            f"streak {self.stable_streak}/{self.min_stable_streak_frames}"
        )

        if now - self.stage_started_at < self.sample_seconds:
            return

        if len(self.current_samples) < self.min_samples_per_point:
            self.stage = "settle"
            self.stage_started_at = now
            self.current_samples = []
            self.stable_streak = 0
            self.status_message = (
                f"Not enough stable samples for {point.name.upper()}, retrying"
            )
            return

        aggregate_feature = self._aggregate_current_samples()
        if aggregate_feature is None:
            self.stage = "settle"
            self.stage_started_at = now
            self.current_samples = []
            self.stable_streak = 0
            self.status_message = (
                f"Samples for {point.name.upper()} too noisy, retrying"
            )
            return

        self.training_features.append(aggregate_feature.astype(float).tolist())
        self.training_targets.append(list(point.target))
        self.point_names.append(point.name)

        self.current_index += 1
        if self.current_index >= len(self.points):
            try:
                self._fit_model()
                quality = self.evaluate_model_quality()
                if quality is not None:
                    self.status_message = f"Calibration completed | score={quality['score']:.2f} ({quality['grade']})"
                else:
                    self.status_message = "Calibration completed"
            except Exception as exc:  # noqa: BLE001
                self.model = None
                self.last_quality_report = None
                self.status_message = f"Calibration failed: {exc}"
            self.active = False
            self.stage = "idle"
            self.current_samples = []
            self.stable_streak = 0
            return

        self.stage = "settle"
        self.stage_started_at = now
        self.current_samples = []
        self.stable_streak = 0
        next_point = self.points[self.current_index]
        self.status_message = (
            f"Captured {point.name.upper()}, next: {next_point.name.upper()}"
        )

    def _fit_model(self) -> None:
        """Fit model(s) based on config.mode and select the best.
        
        NOTE: This method ALWAYSNS returns a model if fitting succeeds,
        regardless of quality gates. Quality is reported as warning only.
        """
        # First, always try to fit axis model (requires 5 core points)
        axis_model = None
        axis_quality = None
        if self.mode != "coupled_only":
            try:
                axis_model = self._fit_axis_model()
                axis_quality = self._evaluate_quality_for_model(axis_model)
            except Exception as exc:
                # Axis model failed, will use coupled-only if available
                print(f"[WARN] Axis model fitting failed: {exc}")
                axis_model = None
                axis_quality = None

        # Try to fit coupled model if we have enough points
        coupled_model = None
        coupled_quality = None
        if self.mode != "axis5":
            try:
                coupled_model = self._fit_coupled_model()
                if coupled_model is not None:
                    coupled_quality = self._evaluate_quality_for_model(coupled_model)
            except Exception:
                coupled_model = None
                coupled_quality = None

        # Select best model (never returns None if any model exists)
        self.model = self._select_best_model(
            axis_model, axis_quality, coupled_model, coupled_quality
        )

        if self.model is None:
            # Last resort: try to use axis model even if it failed checks
            if axis_model is not None:
                self.model = axis_model
                self.status_message = "Calibration completed (weak quality - use with caution)"
            else:
                raise ValueError("No calibration model could be fit from collected data")
        else:
            # Re-evaluate quality for the selected model.
            quality = self.evaluate_model_quality()
            if quality is not None:
                grade = quality.get("grade", "unknown")
                score = quality.get("score", 0.0)
                spread_x = quality.get("spread_x", 0.0)
                spread_y = quality.get("spread_y", 0.0)
                print(f"[CALIB] Quality: grade={grade}, score={score:.3f}")
                print(f"  spread_x={spread_x:.3f}, spread_y={spread_y:.3f}")
                if grade == "weak":
                    self.status_message += f" | WARNING: Weak calibration quality"
                elif grade == "ok":
                    self.status_message += f" | Acceptable calibration"
                else:
                    self.status_message += f" | Good calibration"

    def _fit_axis_model(self) -> AxisCalibrationModel:
        """Fit axis calibration model (requires 5 core points)."""
        point_to_feature = {
            name: np.asarray(feature, dtype=np.float64)
            for name, feature in zip(self.point_names, self.training_features)
        }
        required_points = {"center", "left", "right", "up", "down"}
        if not required_points.issubset(point_to_feature):
            missing = sorted(required_points - set(point_to_feature))
            raise ValueError(f"missing points: {', '.join(missing)}")

        center_feature = point_to_feature["center"]
        left_feature = point_to_feature["left"]
        right_feature = point_to_feature["right"]
        up_feature = point_to_feature["up"]
        down_feature = point_to_feature["down"]

        center_x = float(np.mean([center_feature[0], center_feature[2]]))
        left_x = float(np.mean([left_feature[0], left_feature[2]]))
        right_x = float(np.mean([right_feature[0], right_feature[2]]))
        y_left_weight, y_right_weight = self._compute_axis_y_weights(
            center_feature=center_feature,
            up_feature=up_feature,
            down_feature=down_feature,
        )
        center_y = float(
            (y_left_weight * center_feature[1]) + (y_right_weight * center_feature[3])
        )
        up_y = float((y_left_weight * up_feature[1]) + (y_right_weight * up_feature[3]))
        down_y = float(
            (y_left_weight * down_feature[1]) + (y_right_weight * down_feature[3])
        )

        left_delta = left_x - center_x
        right_delta = right_x - center_x
        up_delta = up_y - center_y
        down_delta = down_y - center_y

        # Log calibration details for debugging
        print(f"[CALIB] Axis5 details:")
        print(f"  spread_x: left={abs(left_delta):.3f}, right={abs(right_delta):.3f} (min={self.min_axis_separation_x:.3f})")
        print(f"  spread_y: up={abs(up_delta):.3f}, down={abs(down_delta):.3f} (min={self.min_axis_separation_y:.3f})")
        print(f"  polarity: x=({'OK' if np.sign(left_delta) != np.sign(right_delta) else 'FAIL'}), y=({'OK' if np.sign(up_delta) != np.sign(down_delta) else 'FAIL'})")

        if (
            abs(left_delta) < self.min_axis_separation_x
            or abs(right_delta) < self.min_axis_separation_x
        ):
            raise ValueError("horizontal calibration spread too small")
        if (
            abs(up_delta) < self.min_axis_separation_y
            or abs(down_delta) < self.min_axis_separation_y
        ):
            raise ValueError("vertical calibration spread too small")
        if np.sign(left_delta) == np.sign(right_delta):
            raise ValueError("left/right samples landed on same side of center")
        if np.sign(up_delta) == np.sign(down_delta):
            raise ValueError("up/down samples landed on same side of center")

        return AxisCalibrationModel(
            center_x=center_x,
            left_x=left_x,
            right_x=right_x,
            center_y=center_y,
            up_y=up_y,
            down_y=down_y,
            feature_names=list(FEATURE_NAMES),
            y_left_weight=y_left_weight,
            y_right_weight=y_right_weight,
            training_features=self.training_features,
            training_targets=self.training_targets,
            point_names=self.point_names,
        )

    def _compute_axis_y_weights(
        self,
        center_feature: np.ndarray,
        up_feature: np.ndarray,
        down_feature: np.ndarray,
    ) -> tuple[float, float]:
        if self.y_fusion_mode == "mean":
            return 0.5, 0.5
        if self.y_fusion_mode == "dominant_left":
            return 1.0, 0.0
        if self.y_fusion_mode == "dominant_right":
            return 0.0, 1.0

        left_up = float(up_feature[1] - center_feature[1])
        left_down = float(down_feature[1] - center_feature[1])
        right_up = float(up_feature[3] - center_feature[3])
        right_down = float(down_feature[3] - center_feature[3])

        left_strength = min(abs(left_up), abs(left_down))
        right_strength = min(abs(right_up), abs(right_down))
        total_strength = left_strength + right_strength

        if total_strength <= 1e-6:
            return 0.5, 0.5

        left_weight = float(left_strength / total_strength)
        right_weight = 1.0 - left_weight
        return left_weight, right_weight

    def _fit_coupled_model(self) -> CoupledCalibrationModel | None:
        """Fit coupled calibration model if enough points available."""
        required_corners = {"upper_left", "upper_right", "lower_left", "lower_right"}
        if len(self.training_features) < 9:
            return None
        if not required_corners.issubset(set(self.point_names)):
            return None

        return CoupledCalibrationModel.fit(
            features=self.training_features,
            targets=self.training_targets,
            point_names=self.point_names,
            basis_type=self.coupled_basis,
            ridge_alpha=self.ridge_alpha,
        )

    def _evaluate_quality_for_model(self, model: Any) -> dict[str, Any] | None:
        """Evaluate quality for a specific candidate model without mutating state."""
        previous_model = self.model
        previous_report = self.last_quality_report
        self.model = model
        try:
            return self.evaluate_model_quality()
        finally:
            self.model = previous_model
            self.last_quality_report = previous_report

    def _select_best_model(
        self,
        axis_model: AxisCalibrationModel | None,
        axis_quality: dict[str, Any] | None,
        coupled_model: CoupledCalibrationModel | None,
        coupled_quality: dict[str, Any] | None,
    ) -> LinearCalibrationModel | AxisCalibrationModel | CoupledCalibrationModel | None:
        """Select best model based on mode and quality gates."""
        mode = self.mode

        # Handle axis5 mode (original behavior - axis only)
        if mode == "axis5":
            return axis_model  # Always return axis5 if available, even if quality gates fail

        # Handle coupled_only mode
        if mode == "coupled_only":
            return coupled_model  # Always return coupled if available

        # Auto mode: select based on quality
        # If only axis available, use it
        if axis_model is not None and coupled_model is None:
            return axis_model

        # If only coupled available, return it (don't reject based on gates)
        if axis_model is None and coupled_model is not None:
            return coupled_model

        # Both available - select based on quality, but ALWAYS return something
        if axis_quality is not None and coupled_quality is not None:
            axis_rmse = axis_quality.get("selection_rmse", 1.0)
            coupled_rmse = coupled_quality.get("selection_rmse", 1.0)
            
            # Prefer coupled only if it's clearly better, otherwise axis5
            if coupled_rmse < axis_rmse * 0.9:  # Coupled must be 10% better
                return coupled_model
            return axis_model

        # Fallback: return whatever is available
        return axis_model or coupled_model

    def _aggregate_current_samples(self) -> np.ndarray | None:
        stacked = np.vstack(self.current_samples).astype(np.float64)
        # Filter out NaN/Inf samples
        finite_mask = np.all(np.isfinite(stacked), axis=1)
        stacked = stacked[finite_mask]
        if stacked.shape[0] < self.min_samples_per_point:
            return None
        mask = (
            np.abs(stacked[:, 0] - stacked[:, 2]) <= self.max_eye_disagreement_x
        ) & (np.abs(stacked[:, 1] - stacked[:, 3]) <= self.max_eye_disagreement_y)
        filtered = stacked[mask]
        if filtered.shape[0] < self.min_samples_per_point:
            return None
        median_result = np.median(filtered, axis=0)
        # Final check: median should be finite
        if not np.all(np.isfinite(median_result)):
            return None
        return median_result

    def save_model(self, path: str | Path | None = None) -> Path:
        if self.model is None:
            raise RuntimeError("No calibration model to save")

        target_path = Path(path) if path is not None else self.default_model_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            json.dumps(self.model.to_dict(), indent=2), encoding="utf-8"
        )
        self.status_message = f"Saved calibration to {target_path}"
        return target_path

    def load_model(self, path: str | Path | None = None) -> Path:
        target_path = Path(path) if path is not None else self.default_model_path
        payload = json.loads(target_path.read_text(encoding="utf-8"))
        model_type = payload.get("model_type", "linear")

        if self.mode == "axis5" and model_type != "axis5":
            raise ValueError(
                "Current calibration.mode='axis5' only accepts axis5 model files"
            )
        if self.mode == "coupled_only" and model_type != "coupled":
            raise ValueError(
                "Current calibration.mode='coupled_only' only accepts coupled model files"
            )

        if model_type == "axis5":
            self.model = AxisCalibrationModel.from_dict(payload)
        elif model_type == "coupled":
            self.model = CoupledCalibrationModel.from_dict(payload)
        else:
            self.model = LinearCalibrationModel.from_dict(payload)
        if getattr(self.model, "feature_space", "legacy_v1") != FEATURE_SPACE_VERSION:
            self.model = None
            raise ValueError(
                "Calibration file was created with an older eye-feature format; recalibrate"
            )
        self.evaluate_model_quality()
        self.status_message = f"Loaded calibration from {target_path}"
        return target_path

    def evaluate_model_quality(self) -> dict[str, Any] | None:
        if self.model is None:
            self.last_quality_report = None
            return None

        if isinstance(self.model, AxisCalibrationModel):
            left_delta = self.model.left_x - self.model.center_x
            right_delta = self.model.right_x - self.model.center_x
            up_delta = self.model.up_y - self.model.center_y
            down_delta = self.model.down_y - self.model.center_y

            spread_x = float(min(abs(left_delta), abs(right_delta)))
            spread_y = float(min(abs(up_delta), abs(down_delta)))
            balance_x = self._balance_score(left_delta, right_delta)
            balance_y = self._balance_score(up_delta, down_delta)
            x_score = float(
                np.clip(spread_x / max(self.quality_target_spread_x, 1e-6), 0.0, 1.0)
            )
            y_score = float(
                np.clip(spread_y / max(self.quality_target_spread_y, 1e-6), 0.0, 1.0)
            )

            score = (
                (0.42 * x_score)
                + (0.38 * y_score)
                + (0.10 * balance_x)
                + (0.10 * balance_y)
            )
            polarity_ok = bool(
                np.sign(left_delta) != np.sign(right_delta)
                and np.sign(up_delta) != np.sign(down_delta)
            )
            if not polarity_ok:
                score *= 0.55

            # Compute LOO-CV for axis5 for fair comparison with coupled
            from calibration_quality import _compute_loo_rmse_axis5
            loo_rmse, loo_rmse_x, loo_rmse_y = _compute_loo_rmse_axis5(
                features=self.model.training_features,
                targets=self.model.training_targets,
                point_names=self.model.point_names,
            )
            in_sample_rmse = self._selection_rmse_for_model(self.model)

            grade = "good" if score >= 0.75 else ("ok" if score >= 0.55 else "weak")
            report = {
                "model_type": "axis5",
                "score": float(np.clip(score, 0.0, 1.0)),
                "grade": grade,
                "spread_x": spread_x,
                "spread_y": spread_y,
                "balance_x": float(balance_x),
                "balance_y": float(balance_y),
                "polarity_ok": polarity_ok,
                # Use pessimistic RMSE for model selection (like coupled)
                "selection_rmse": float(max(in_sample_rmse, loo_rmse)),
                "loo_rmse": float(loo_rmse),
                "loo_rmse_x": float(loo_rmse_x),
                "loo_rmse_y": float(loo_rmse_y),
                "in_sample_rmse": float(in_sample_rmse),
            }
        elif isinstance(self.model, CoupledCalibrationModel):
            # Use Phase 3 quality evaluation for coupled models
            report = evaluate_coupled_quality(
                model=self.model,
                features=self.model.training_features,
                targets=self.model.training_targets,
                point_names=self.model.point_names,
                config=self._quality_config,
            )
        else:
            # LinearCalibrationModel
            stats = self.model.training_prediction_stats()
            x_score = float(np.clip(stats["max_abs_x"] / 0.8, 0.0, 1.0))
            y_score = float(np.clip(stats["max_abs_y"] / 0.8, 0.0, 1.0))
            score = (0.5 * x_score) + (0.5 * y_score)
            report = {
                "model_type": "linear",
                "score": float(np.clip(score, 0.0, 1.0)),
                "grade": "good"
                if score >= 0.75
                else ("ok" if score >= 0.55 else "weak"),
                "spread_x": float(stats["max_abs_x"]),
                "spread_y": float(stats["max_abs_y"]),
                "balance_x": 0.0,
                "balance_y": 0.0,
                "polarity_ok": True,
                "selection_rmse": self._selection_rmse_for_model(self.model),
            }

        self.last_quality_report = report
        return report

    def recenter(self, feature_vector: np.ndarray | None, confidence: float) -> bool:
        if feature_vector is None:
            self.status_message = "Recenter failed: no eye features"
            return False
        if confidence < self.recenter_min_confidence:
            self.status_message = f"Recenter failed: confidence too low ({confidence:.2f} < {self.recenter_min_confidence:.2f})"
            return False
        if not isinstance(self.model, AxisCalibrationModel):
            self.status_message = "Recenter requires an axis calibration model"
            return False

        vector = _as_feature4(np.asarray(feature_vector, dtype=np.float64))
        if vector is None:
            self.status_message = "Recenter failed: invalid feature vector (NaN/Inf)"
            return False

        fx = float(np.mean([vector[0], vector[2]]))
        fy = float(
            (self.model.y_left_weight * vector[1])
            + (self.model.y_right_weight * vector[3])
        )

        old_center_x = self.model.center_x
        old_center_y = self.model.center_y
        new_center_x = ((1.0 - self.recenter_alpha) * old_center_x) + (
            self.recenter_alpha * fx
        )
        new_center_y = ((1.0 - self.recenter_alpha) * old_center_y) + (
            self.recenter_alpha * fy
        )
        shift_x = new_center_x - old_center_x
        shift_y = new_center_y - old_center_y

        self.model.center_x += shift_x
        self.model.left_x += shift_x
        self.model.right_x += shift_x
        self.model.center_y += shift_y
        self.model.up_y += shift_y
        self.model.down_y += shift_y

        self.evaluate_model_quality()
        self.status_message = f"Recentered (dx={shift_x:+.3f}, dy={shift_y:+.3f})"
        return True

    @staticmethod
    def _balance_score(delta_a: float, delta_b: float) -> float:
        a = abs(delta_a)
        b = abs(delta_b)
        if a <= 1e-6 and b <= 1e-6:
            return 0.0
        return float(np.clip(1.0 - (abs(a - b) / max(a, b, 1e-6)), 0.0, 1.0))

    @staticmethod
    def _selection_rmse_for_model(model: Any) -> float:
        """Compute common RMSE metric on training points for model selection."""
        features = getattr(model, "training_features", [])
        targets = getattr(model, "training_targets", [])
        if not features or not targets or len(features) != len(targets):
            return 1e6

        residuals = []
        for row, target in zip(features, targets):
            vec = np.asarray(row, dtype=np.float64)
            if hasattr(model, "predict_raw"):
                pred_x, pred_y = model.predict_raw(vec)
            else:
                pred_x, pred_y = model.predict(vec)
            residuals.append([pred_x - float(target[0]), pred_y - float(target[1])])
        residuals_array = np.asarray(residuals, dtype=np.float64)
        return float(np.sqrt(np.mean(np.sum(residuals_array**2, axis=1))))

    def get_active_target(self) -> dict[str, Any] | None:
        if not self.active:
            return None

        point = self.points[self.current_index]
        duration = (
            self.settle_seconds if self.stage == "settle" else self.sample_seconds
        )
        remaining = max(0.0, duration - (time.monotonic() - self.stage_started_at))
        return {
            "name": point.name,
            "target": point.target,
            "screen_position": point.screen_position,
            "stage": self.stage,
            "remaining": remaining,
            "sample_count": len(self.current_samples),
            "stable_streak": self.stable_streak,
            "progress": self.current_index,
            "total": len(self.points),
        }
