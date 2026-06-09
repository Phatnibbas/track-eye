"""Coupled 2D calibration model for Phase 3."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from constants import FEATURE_NAMES
from filters import clamp


FEATURE_SPACE_VERSION = "iris_width_vertical_v4"


@dataclass
class CoupledCalibrationModel:
    """Coupled 2D calibration with affine or quadratic basis expansion."""

    basis_type: str  # "affine" or "quadratic"
    coefficients: np.ndarray  # shape (2, n_basis)
    intercepts: np.ndarray  # shape (2,)
    feature_names: list[str]
    basis_feature_names: list[str]
    ridge_alpha: float
    training_features: list[list[float]] = field(default_factory=list)
    training_targets: list[list[float]] = field(default_factory=list)
    point_names: list[str] = field(default_factory=list)
    feature_space: str = FEATURE_SPACE_VERSION

    def transform(self, feature_vector: np.ndarray) -> np.ndarray:
        """Transform raw features to basis features."""
        vec = np.asarray(feature_vector, dtype=np.float64)
        if len(vec) != 4:
            raise ValueError(f"Expected 4 features, got {len(vec)}")
        if not np.all(np.isfinite(vec)):
            raise ValueError("Feature vector contains NaN/Inf")

        lx, ly, rx, ry = vec

        if self.basis_type == "affine":
            return vec
        elif self.basis_type == "quadratic":
            return np.asarray(
                [
                    lx,
                    ly,
                    rx,
                    ry,
                    lx * lx,
                    ly * ly,
                    rx * rx,
                    ry * ry,
                    lx * ly,
                    rx * ry,
                    lx - rx,
                    ly - ry,
                ],
                dtype=np.float64,
            )
        else:
            raise ValueError(f"Unknown basis_type: {self.basis_type}")

    def predict(self, feature_vector: np.ndarray) -> tuple[float, float]:
        """Predict x_ctrl, y_ctrl from raw feature vector."""
        raw_x, raw_y = self.predict_raw(feature_vector)
        return clamp(raw_x), clamp(raw_y)

    def predict_raw(self, feature_vector: np.ndarray) -> tuple[float, float]:
        """Predict unclamped x_ctrl, y_ctrl from raw feature vector."""
        basis = self.transform(feature_vector)
        output = (self.coefficients @ basis) + self.intercepts
        return float(output[0]), float(output[1])

    def training_prediction_stats(self) -> dict[str, float]:
        """Compatibility stats for loaded-model validation."""
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
        """Compatibility usability check for loaded-model validation."""
        if not self.training_features:
            return False
        stats = self.training_prediction_stats()
        return stats["max_abs_x"] >= min_abs_x and stats["max_abs_y"] >= min_abs_y

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "version": 3,
            "model_type": "coupled",
            "basis_type": self.basis_type,
            "feature_names": self.feature_names,
            "basis_feature_names": self.basis_feature_names,
            "coefficients": self.coefficients.tolist(),
            "intercepts": self.intercepts.tolist(),
            "training_features": self.training_features,
            "training_targets": self.training_targets,
            "point_names": self.point_names,
            "ridge_alpha": self.ridge_alpha,
            "feature_space": self.feature_space,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CoupledCalibrationModel":
        """Deserialize from dict."""
        basis_type = str(payload.get("basis_type", "affine"))
        if basis_type not in {"affine", "quadratic"}:
            raise ValueError(f"Unsupported coupled basis_type: {basis_type!r}")
        feature_names = list(payload.get("feature_names", FEATURE_NAMES))
        basis_feature_names = list(payload.get("basis_feature_names", []))
        coefficients = np.asarray(payload["coefficients"], dtype=np.float64)
        intercepts = np.asarray(payload["intercepts"], dtype=np.float64)

        if coefficients.ndim != 2 or coefficients.shape[0] != 2:
            raise ValueError("Coefficients must have shape (2, n_basis)")
        if intercepts.ndim != 1 or intercepts.shape[0] != 2:
            raise ValueError("Intercepts must have shape (2,)")
        if basis_feature_names and len(basis_feature_names) != coefficients.shape[1]:
            raise ValueError(
                "basis_feature_names length does not match coefficient width"
            )

        return cls(
            basis_type=basis_type,
            coefficients=coefficients,
            intercepts=intercepts,
            feature_names=feature_names,
            basis_feature_names=basis_feature_names,
            ridge_alpha=float(payload.get("ridge_alpha", 1.0)),
            training_features=[
                list(map(float, row)) for row in payload.get("training_features", [])
            ],
            training_targets=[
                list(map(float, row)) for row in payload.get("training_targets", [])
            ],
            point_names=list(payload.get("point_names", [])),
            feature_space=str(payload.get("feature_space", "legacy_v1")),
        )

    @classmethod
    def fit(
        cls,
        features: list[list[float]],
        targets: list[list[float]],
        point_names: list[str],
        basis_type: str,
        ridge_alpha: float,
    ) -> "CoupledCalibrationModel":
        """Fit coupled model using ridge regression."""
        if len(features) != len(targets) or len(features) != len(point_names):
            raise ValueError("Features, targets, and point_names must have same length")
        if len(features) < 5:
            raise ValueError("Need at least 5 points for coupled calibration")
        # LOO refits run with n-1 points; allow 8 so quadratic can be evaluated
        # from a standard 9-point session.
        if basis_type == "quadratic" and len(features) < 8:
            raise ValueError("Quadratic coupled calibration requires at least 8 points")

        # Transform to basis with NaN/Inf validation
        raw_features = np.asarray(features, dtype=np.float64)
        if not np.all(np.isfinite(raw_features)):
            raise ValueError("Feature matrix contains NaN/Inf values")
        target_array = np.asarray(targets, dtype=np.float64)
        if not np.all(np.isfinite(target_array)):
            raise ValueError("Target matrix contains NaN/Inf values")

        dummy_model = cls(
            basis_type=basis_type,
            coefficients=np.zeros((2, 4)),
            intercepts=np.zeros(2),
            feature_names=FEATURE_NAMES,
            basis_feature_names=[],
            ridge_alpha=ridge_alpha,
        )

        basis_matrix = np.asarray(
            [dummy_model.transform(row) for row in raw_features], dtype=np.float64
        )
        n_basis = basis_matrix.shape[1]

        # Feature normalization: standardize to zero mean, unit variance
        # This makes ridge_alpha meaningful regardless of feature scale
        basis_mean = np.mean(basis_matrix, axis=0)
        basis_std = np.std(basis_matrix, axis=0)
        # Prevent division by zero for constant features
        basis_std = np.where(basis_std < 1e-10, 1.0, basis_std)
        basis_normalized = (basis_matrix - basis_mean) / basis_std

        # Ridge regression for each output using centered X/y with explicit intercept.
        alpha = max(float(ridge_alpha), 1e-8)
        ridge_eye = alpha * np.eye(n_basis)
        x_mean = np.mean(basis_normalized, axis=0)
        x_centered = basis_normalized - x_mean
        coefficients_normalized = np.zeros((2, n_basis), dtype=np.float64)
        intercepts = np.zeros(2, dtype=np.float64)

        for output_idx in range(2):
            y = target_array[:, output_idx]
            y_mean = float(np.mean(y))
            y_centered = y - y_mean

            # Solve (Xc^T Xc + alpha I) beta = Xc^T yc
            XtX = x_centered.T @ x_centered
            Xty = x_centered.T @ y_centered
            beta_normalized = np.linalg.solve(XtX + ridge_eye, Xty)

            coefficients_normalized[output_idx, :] = beta_normalized
            intercepts[output_idx] = y_mean - float(x_mean @ beta_normalized)

        # Denormalize coefficients back to original feature scale
        # y = intercept + beta_normalized @ ((x - mean) / std)
        #   = (intercept - beta_normalized @ mean / std) + (beta_normalized / std) @ x
        coefficients = coefficients_normalized / basis_std[np.newaxis, :]
        intercepts = intercepts - np.sum(coefficients_normalized * basis_mean / basis_std, axis=1)

        # Generate basis feature names
        if basis_type == "affine":
            basis_names = FEATURE_NAMES
        elif basis_type == "quadratic":
            basis_names = [
                "lx",
                "ly",
                "rx",
                "ry",
                "lx^2",
                "ly^2",
                "rx^2",
                "ry^2",
                "lx*ly",
                "rx*ry",
                "lx-rx",
                "ly-ry",
            ]
        else:
            basis_names = [f"basis_{i}" for i in range(n_basis)]

        return cls(
            basis_type=basis_type,
            coefficients=coefficients,
            intercepts=intercepts,
            feature_names=FEATURE_NAMES,
            basis_feature_names=basis_names,
            ridge_alpha=ridge_alpha,
            training_features=features,
            training_targets=targets,
            point_names=point_names,
            feature_space=FEATURE_SPACE_VERSION,
        )
