"""Quality scoring for calibration models (Phase 3)."""

from __future__ import annotations

from typing import Any

import numpy as np


def _predict_xy_raw(model: Any, feature_vector: np.ndarray) -> tuple[float, float]:
    """Predict without output clamping when supported."""
    if hasattr(model, "predict_raw"):
        x_raw, y_raw = model.predict_raw(feature_vector)
        return float(x_raw), float(y_raw)
    x_pred, y_pred = model.predict(feature_vector)
    return float(x_pred), float(y_pred)


def _compute_loo_rmse_axis5(
    features: list[list[float]],
    targets: list[list[float]],
    point_names: list[str],
) -> tuple[float, float, float]:
    """Leave-one-out RMSE for axis5 model (refits axis model n times)."""
    from calibration import AxisCalibrationModel, CalibrationManager

    n = len(features)
    if n < 5:
        return 1e6, 1e6, 1e6  # Not enough points for axis5

    residuals = []
    failures = 0

    # Axis5 needs at least 5 core points
    core_points = {"center", "left", "right", "up", "down"}

    for i in range(n):
        # Skip if removing a core point would make axis5 unfittable
        remaining_points = set(point_names) - {point_names[i]}
        if not core_points.issubset(remaining_points):
            # Can't refit axis5 without core points, skip this fold
            continue

        train_features = [f for j, f in enumerate(features) if j != i]
        train_targets = [t for j, t in enumerate(targets) if j != i]
        train_point_names = [name for j, name in enumerate(point_names) if j != i]
        test_feature = np.asarray(features[i], dtype=np.float64)
        test_target = targets[i]

        try:
            # Create temporary CalibrationManager and fit axis model
            temp_config = {
                "ridge_alpha": 1.0,
                "y_fusion_mode": "weighted",
                "min_axis_separation_x": 0.04,
                "min_axis_separation_y": 0.06,
            }
            temp_manager = CalibrationManager(temp_config, "dummy")
            temp_manager.training_features = train_features
            temp_manager.training_targets = train_targets
            temp_manager.point_names = train_point_names
            
            loo_model = temp_manager._fit_axis_model()
            pred_x, pred_y = _predict_xy_raw(loo_model, test_feature)
            residuals.append([pred_x - test_target[0], pred_y - test_target[1]])
        except Exception:
            failures += 1
            continue

    if not residuals:
        return 1e6, 1e6, 1e6

    penalty = 1.0 + (failures / max(n, 1)) if failures > 0 else 1.0
    residuals_array = np.asarray(residuals, dtype=np.float64)
    rmse = float(np.sqrt(np.mean(np.sum(residuals_array**2, axis=1))) * penalty)
    rmse_x = float(np.sqrt(np.mean(residuals_array[:, 0] ** 2)) * penalty)
    rmse_y = float(np.sqrt(np.mean(residuals_array[:, 1] ** 2)) * penalty)

    return rmse, rmse_x, rmse_y


def evaluate_coupled_quality(
    model: Any,
    features: list[list[float]],
    targets: list[list[float]],
    point_names: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate coupled model quality with LOO, diagonal, monotonicity checks."""
    if len(features) != len(targets) or len(features) != len(point_names):
        raise ValueError("Features, targets, point_names length mismatch")

    features_array = np.asarray(features, dtype=np.float64)
    targets_array = np.asarray(targets, dtype=np.float64)

    # Leave-one-out RMSE
    loo_rmse, loo_rmse_x, loo_rmse_y = _compute_loo_rmse(
        model, features_array, targets_array
    )

    # In-sample RMSE (diagnostic only)
    train_rmse = _compute_train_rmse(model, features_array, targets_array)

    # Diagonal residuals (if corners exist)
    diagonal_rmse, diagonal_quadrant_acc = _compute_diagonal_metrics(
        model, features, targets, point_names
    )

    # Vertical-specific RMSE
    vertical_rmse = _compute_vertical_rmse(model, features, targets, point_names)

    # Monotonicity checks
    monotonicity_pass, monotonicity_score = _check_monotonicity(
        model, features, targets, point_names
    )

    # Cross-axis leakage
    axis_leakage = _compute_axis_leakage(model, features, targets, point_names)

    # Hard gates
    loo_max = float(config.get("loo_rmse_max", 0.45))
    diagonal_max = float(config.get("diagonal_rmse_max", 0.40))
    vertical_max = float(config.get("vertical_rmse_max", 0.45))
    leakage_max = float(config.get("axis_leakage_max", 0.25))
    monotonicity_required = bool(config.get("monotonicity_required", True))

    hard_gates_pass = (
        loo_rmse <= loo_max
        and (diagonal_rmse is None or diagonal_rmse <= diagonal_max)
        and (vertical_rmse is None or vertical_rmse <= vertical_max)
        and (axis_leakage is None or axis_leakage <= leakage_max)
        and (not monotonicity_required or monotonicity_pass)
    )

    # Composite score
    loo_score = max(0.0, min(1.0, 1.0 - loo_rmse / 0.35))
    diagonal_score = (
        max(0.0, min(1.0, 1.0 - diagonal_rmse / 0.40))
        if diagonal_rmse is not None
        else 1.0
    )
    vertical_score = (
        max(0.0, min(1.0, 1.0 - vertical_rmse / 0.35))
        if vertical_rmse is not None
        else 1.0
    )
    leakage_score = (
        max(0.0, min(1.0, 1.0 - axis_leakage / 0.25))
        if axis_leakage is not None
        else 1.0
    )

    composite_score = (
        0.35 * loo_score
        + 0.25 * diagonal_score
        + 0.20 * vertical_score
        + 0.10 * monotonicity_score
        + 0.10 * leakage_score
    )

    # Grade
    if not hard_gates_pass:
        grade = "weak"
    elif composite_score >= 0.75:
        grade = "good"
    elif composite_score >= 0.55:
        grade = "ok"
    else:
        grade = "weak"

    return {
        "model_type": "coupled",
        "basis_type": getattr(model, "basis_type", "unknown"),
        "score": float(composite_score),
        "grade": grade,
        "pass_hard_gates": hard_gates_pass,
        "metrics": {
            "loo_rmse": float(loo_rmse),
            "loo_rmse_x": float(loo_rmse_x),
            "loo_rmse_y": float(loo_rmse_y),
            "train_rmse": float(train_rmse),
            "diagonal_rmse": float(diagonal_rmse)
            if diagonal_rmse is not None
            else None,
            "diagonal_quadrant_acc": (
                float(diagonal_quadrant_acc)
                if diagonal_quadrant_acc is not None
                else None
            ),
            "vertical_rmse": float(vertical_rmse)
            if vertical_rmse is not None
            else None,
            "axis_leakage": float(axis_leakage) if axis_leakage is not None else None,
            "monotonicity_pass": monotonicity_pass,
            "monotonicity_score": float(monotonicity_score),
        },
        "component_scores": {
            "loo": float(loo_score),
            "diagonal": float(diagonal_score),
            "vertical": float(vertical_score),
            "monotonicity": float(monotonicity_score),
            "leakage": float(leakage_score),
        },
        # Lower is better. Use pessimistic RMSE for cross-model selection
        # to avoid favoring overfitted coupled models.
        # Governed by loo_rmse hard gates for generalization safety.
        "selection_rmse": float(max(train_rmse, loo_rmse)),
    }


def _compute_train_rmse(model: Any, features: np.ndarray, targets: np.ndarray) -> float:
    residuals = []
    for i in range(features.shape[0]):
        pred_x, pred_y = _predict_xy_raw(model, features[i])
        residuals.append([pred_x - targets[i, 0], pred_y - targets[i, 1]])
    if not residuals:
        return 1e6
    residuals_array = np.asarray(residuals, dtype=np.float64)
    return float(np.sqrt(np.mean(np.sum(residuals_array**2, axis=1))))


def _compute_loo_rmse(
    model: Any, features: np.ndarray, targets: np.ndarray
) -> tuple[float, float, float]:
    """Leave-one-out RMSE."""
    n = features.shape[0]
    residuals = []
    failures = 0

    for i in range(n):
        train_features = np.delete(features, i, axis=0)
        train_targets = np.delete(targets, i, axis=0)
        test_feature = features[i]
        test_target = targets[i]

        # Refit model without point i
        try:
            loo_model = type(model).fit(
                features=train_features.tolist(),
                targets=train_targets.tolist(),
                point_names=[f"point_{j}" for j in range(len(train_features))],
                basis_type=getattr(model, "basis_type", "affine"),
                ridge_alpha=getattr(model, "ridge_alpha", 1.0),
            )
            pred_x, pred_y = _predict_xy_raw(loo_model, test_feature)
            residuals.append([pred_x - test_target[0], pred_y - test_target[1]])
        except Exception:
            # If refit fails, skip this point
            failures += 1
            continue

    if not residuals:
        # Fail closed when all folds fail.
        return 1e6, 1e6, 1e6

    if failures > 0:
        # Penalize partial LOO fit failures heavily.
        penalty = 1.0 + (failures / max(n, 1))
    else:
        penalty = 1.0

    residuals_array = np.asarray(residuals, dtype=np.float64)
    rmse = float(np.sqrt(np.mean(np.sum(residuals_array**2, axis=1))) * penalty)
    rmse_x = float(np.sqrt(np.mean(residuals_array[:, 0] ** 2)) * penalty)
    rmse_y = float(np.sqrt(np.mean(residuals_array[:, 1] ** 2)) * penalty)

    return rmse, rmse_x, rmse_y


def _compute_diagonal_metrics(
    model: Any,
    features: list[list[float]],
    targets: list[list[float]],
    point_names: list[str],
) -> tuple[float | None, float | None]:
    """Diagonal corner RMSE and quadrant accuracy."""
    corner_names = {"upper_left", "upper_right", "lower_left", "lower_right"}
    corner_indices = [i for i, name in enumerate(point_names) if name in corner_names]

    if not corner_indices:
        return None, None

    residuals = []
    correct_quadrant = 0

    for i in corner_indices:
        pred_x, pred_y = _predict_xy_raw(
            model, np.asarray(features[i], dtype=np.float64)
        )
        target_x, target_y = targets[i]
        residuals.append([pred_x - target_x, pred_y - target_y])

        # Check quadrant
        if np.sign(pred_x) == np.sign(target_x) and np.sign(pred_y) == np.sign(
            target_y
        ):
            correct_quadrant += 1

    residuals_array = np.asarray(residuals, dtype=np.float64)
    rmse = float(np.sqrt(np.mean(np.sum(residuals_array**2, axis=1))))
    quadrant_acc = float(correct_quadrant / len(corner_indices))

    return rmse, quadrant_acc


def _compute_vertical_rmse(
    model: Any,
    features: list[list[float]],
    targets: list[list[float]],
    point_names: list[str],
) -> float | None:
    """RMSE on points with non-zero target_y."""
    vertical_indices = [i for i, (_, ty) in enumerate(targets) if abs(ty) > 0.1]

    if not vertical_indices:
        return None

    residuals_y = []
    for i in vertical_indices:
        _, pred_y = _predict_xy_raw(model, np.asarray(features[i], dtype=np.float64))
        _, target_y = targets[i]
        residuals_y.append(pred_y - target_y)

    return float(np.sqrt(np.mean(np.asarray(residuals_y, dtype=np.float64) ** 2)))


def _check_monotonicity(
    model: Any,
    features: list[list[float]],
    targets: list[list[float]],
    point_names: list[str],
) -> tuple[bool, float]:
    """Check monotonicity and ordering."""
    name_to_pred = {}
    for i, name in enumerate(point_names):
        pred_x, pred_y = _predict_xy_raw(
            model, np.asarray(features[i], dtype=np.float64)
        )
        name_to_pred[name] = (pred_x, pred_y)

    violations = 0
    checks = 0

    # X monotonicity
    if "left" in name_to_pred and "center" in name_to_pred and "right" in name_to_pred:
        checks += 1
        if not (
            name_to_pred["left"][0]
            < name_to_pred["center"][0]
            < name_to_pred["right"][0]
        ):
            violations += 1

    # Y monotonicity
    if "up" in name_to_pred and "center" in name_to_pred and "down" in name_to_pred:
        checks += 1
        if not (
            name_to_pred["up"][1] < name_to_pred["center"][1] < name_to_pred["down"][1]
        ):
            violations += 1

    # Corner X ordering
    if "upper_left" in name_to_pred and "upper_right" in name_to_pred:
        checks += 1
        if not (name_to_pred["upper_left"][0] < name_to_pred["upper_right"][0]):
            violations += 1

    if "lower_left" in name_to_pred and "lower_right" in name_to_pred:
        checks += 1
        if not (name_to_pred["lower_left"][0] < name_to_pred["lower_right"][0]):
            violations += 1

    # Corner Y ordering
    if "upper_left" in name_to_pred and "lower_left" in name_to_pred:
        checks += 1
        if not (name_to_pred["upper_left"][1] < name_to_pred["lower_left"][1]):
            violations += 1

    if "upper_right" in name_to_pred and "lower_right" in name_to_pred:
        checks += 1
        if not (name_to_pred["upper_right"][1] < name_to_pred["lower_right"][1]):
            violations += 1

    if checks == 0:
        return True, 1.0

    monotonicity_pass = violations == 0
    monotonicity_score = 1.0 - (violations / checks)

    return monotonicity_pass, monotonicity_score


def _compute_axis_leakage(
    model: Any,
    features: list[list[float]],
    targets: list[list[float]],
    point_names: list[str],
) -> float | None:
    """Cross-axis leakage on axis-aligned targets."""
    leakages = []

    for i, name in enumerate(point_names):
        target_x, target_y = targets[i]
        pred_x, pred_y = _predict_xy_raw(
            model, np.asarray(features[i], dtype=np.float64)
        )

        # Horizontal targets should have low |pred_y|
        if abs(target_y) < 0.1 and abs(target_x) > 0.5:
            leakages.append(abs(pred_y))

        # Vertical targets should have low |pred_x|
        if abs(target_x) < 0.1 and abs(target_y) > 0.5:
            leakages.append(abs(pred_x))

    if not leakages:
        return None

    return float(np.mean(leakages))
