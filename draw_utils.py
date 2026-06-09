"""OpenCV overlay helpers."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from calibration import CalibrationManager
from filters import clamp
from gaze_estimator import EstimateResult


GREEN = (0, 220, 0)
RED = (0, 0, 255)
YELLOW = (0, 220, 220)
CYAN = (255, 255, 0)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


def _format_calibration_status(calibration_manager) -> str:
    """Format calibration status for overlay."""
    if not calibration_manager.has_model:
        return "raw"

    quality = calibration_manager.last_quality_report
    if quality is None:
        return "loaded"

    model_type = quality.get("model_type", "unknown")
    if model_type == "coupled":
        basis = quality.get("basis_type", "affine")
        return f"{model_type}/{basis}"
    return model_type


def draw_overlay(
    frame: np.ndarray,
    estimate: EstimateResult,
    fps: float,
    debug_enabled: bool,
    calibration_manager: CalibrationManager,
    paused: bool,
    benchmark_status: dict[str, Any] | None = None,
    session_status: dict[str, Any] | None = None,
    servo_status: Any | None = None,
) -> np.ndarray:
    if debug_enabled and estimate.eyes:
        _draw_eye_debug_panels(frame, estimate, calibration_manager)

    _draw_sharingan_widget(frame, estimate)
    _draw_status_text(
        frame,
        estimate,
        fps,
        debug_enabled,
        calibration_manager,
        paused,
        session_status=session_status,
        servo_status=servo_status,
    )
    _draw_calibration_target(frame, calibration_manager)
    _draw_benchmark_status(frame, benchmark_status)
    return frame


def _draw_status_text(
    frame: np.ndarray,
    estimate: EstimateResult,
    fps: float,
    debug_enabled: bool,
    calibration_manager: CalibrationManager,
    paused: bool,
    session_status: dict[str, Any] | None = None,
    servo_status: Any | None = None,
) -> None:
    panel_origin = (10, 20)
    lines = [
        f"x_ctrl: {estimate.x_ctrl:+.3f}",
        f"y_ctrl: {estimate.y_ctrl:+.3f}",
        f"signal: {estimate.raw_x:+.3f} {estimate.raw_y:+.3f}",
        f"eye_xy: {estimate.fallback_x:+.3f} {estimate.fallback_y:+.3f}",
        f"x_eye:  {estimate.x_eye:+.3f}",
        f"y_eye:  {estimate.y_eye:+.3f}",
        (
            f"pose:   {'on' if estimate.head_pose_enabled else 'off'}"
            f"/{'valid' if estimate.pose_valid else 'filtered'} "
            f"yaw={estimate.yaw_deg:+.1f} pitch={estimate.pitch_deg:+.1f}"
        ),
        f"conf:   {estimate.confidence:.2f}",
        (
            f"fusion: {estimate.fusion_mode} "
            f"wl={estimate.left_weight:.2f} wr={estimate.right_weight:.2f}"
        ),
        (
            f"agree:  dx={estimate.eye_disagreement_x:.3f} "
            f"dy={estimate.eye_disagreement_y:.3f}"
        ),
        (
            f"yrel:   {estimate.vertical_reliability:.2f} "
            f"yconf={estimate.y_confidence:.2f}"
        ),
        f"FPS:    {fps:.1f}",
        f"mode:   {'debug' if debug_enabled else 'clean'}",
        f"calib:  {_format_calibration_status(calibration_manager)}",
        f"source: {estimate.output_source}",
        f"state:  {'paused' if paused else 'running'}",
        f"info:   {estimate.message}",
    ]
    if session_status is not None:
        lines.insert(
            -1,
            "session: "
            f"{session_status.get('state', 'unknown')} "
            f"ready={'yes' if session_status.get('ready', False) else 'no'} "
            f"{session_status.get('reason', '')}",
        )
    if servo_status is not None:
        lines.insert(
            -1,
            "servo:  "
            f"pan={servo_status.pan_deg:.1f} tilt={servo_status.tilt_deg:.1f} "
            f"{servo_status.gate_state}",
        )

    if calibration_manager.active:
        lines.append(f"cal:    {calibration_manager.status_message}")
    elif calibration_manager.status_message:
        lines.append(f"cal:    {calibration_manager.status_message}")

    quality = calibration_manager.last_quality_report
    if quality is not None:
        model_type = quality.get("model_type", "unknown")
        grade = quality["grade"]
        score = quality["score"]

        if model_type == "coupled":
            basis = quality.get("basis_type", "unknown")
            metrics = quality.get("metrics", {})
            loo = metrics.get("loo_rmse", 0.0)
            diag = metrics.get("diagonal_rmse")
            lines.append(
                f"qcal:   {model_type}/{basis} {grade} s={score:.2f} loo={loo:.3f}"
            )
            if diag is not None:
                lines.append(f"        diag={diag:.3f}")
        else:
            spread_x = quality.get("spread_x", 0.0)
            spread_y = quality.get("spread_y", 0.0)
            lines.append(
                f"qcal:   {model_type} {grade} s={score:.2f} sx={spread_x:.3f} sy={spread_y:.3f}"
            )

    if len(estimate.eyes) == 2 and (debug_enabled or calibration_manager.active):
        eye_dx = estimate.eye_disagreement_x
        eye_dy = estimate.eye_disagreement_y
        eye_quality = min(estimate.eyes[0].quality, estimate.eyes[1].quality)
        stable_now = (
            estimate.confidence >= calibration_manager.min_confidence
            and eye_dx <= calibration_manager.max_eye_disagreement_x
            and eye_dy <= calibration_manager.max_eye_disagreement_y
            and all(eye.tracked for eye in estimate.eyes)
        )
        lines.append(
            f"eyes:   ql={estimate.eyes[0].quality:.2f} qr={estimate.eyes[1].quality:.2f} min={eye_quality:.2f}"
        )
        lines.append(f"sample: {'stable' if stable_now else 'unstable'}")

    for index, line in enumerate(lines):
        y = panel_origin[1] + (index * 22)
        cv2.putText(
            frame,
            line,
            (panel_origin[0] + 1, y + 1),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            BLACK,
            3,
        )
        cv2.putText(
            frame, line, (panel_origin[0], y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 1
        )

    shortcut_line = "q quit | c calibrate | r reset | z recenter | s save | l load | h headpose | d debug | p pause"
    y = frame.shape[0] - 15
    cv2.putText(
        frame, shortcut_line, (11, y + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.52, BLACK, 3
    )
    cv2.putText(frame, shortcut_line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, WHITE, 1)


def _draw_sharingan_widget(frame: np.ndarray, estimate: EstimateResult) -> None:
    frame_h, frame_w = frame.shape[:2]
    margin = 18
    gap = 18
    size = max(110, min(160, (frame_w - (2 * margin) - gap) // 2))
    radius = size // 2
    baseline_y = frame_h - margin - radius

    centers = [
        (frame_w - margin - gap - size - radius, baseline_y),
        (frame_w - margin - radius, baseline_y),
    ]
    labels = ["LEFT EYE", "RIGHT EYE"]

    for index, center in enumerate(centers):
        eye = estimate.eyes[index] if index < len(estimate.eyes) else None
        if eye is None:
            horizontal = 0.0
            vertical = 0.0
            confidence = 0.0
        else:
            horizontal = eye.horizontal
            vertical = eye.vertical
            confidence = eye.quality

        # 5x amplification for visibility
        x_amp = clamp(horizontal * 5.0, -1.5, 1.5)
        y_amp = clamp(vertical * 5.0, -1.5, 1.5)

        _draw_single_sharingan_widget(
            frame=frame,
            center=center,
            size=size,
            x_value=x_amp,
            y_value=y_amp,
            confidence=confidence,
            label=labels[index],
        )


def _draw_single_sharingan_widget(
    frame: np.ndarray,
    center: tuple[int, int],
    size: int,
    x_value: float,
    y_value: float,
    confidence: float,
    label: str,
) -> None:
    outer_radius = size // 2 - 8
    ring_radius = outer_radius - 14
    track_radius = ring_radius - 12

    overlay = frame.copy()
    cv2.circle(overlay, center, outer_radius + 12, (8, 8, 26), -1, lineType=cv2.LINE_AA)
    cv2.circle(overlay, center, outer_radius + 5, (10, 10, 45), 5, lineType=cv2.LINE_AA)
    cv2.circle(overlay, center, outer_radius - 2, (0, 0, 90), 3, lineType=cv2.LINE_AA)
    cv2.circle(
        overlay, center, outer_radius - 10, (10, 10, 110), -1, lineType=cv2.LINE_AA
    )
    cv2.addWeighted(overlay, 0.46, frame, 0.54, 0.0, frame)

    cv2.circle(frame, center, outer_radius, (20, 20, 110), 5, lineType=cv2.LINE_AA)
    cv2.circle(frame, center, outer_radius - 8, (30, 30, 200), 2, lineType=cv2.LINE_AA)
    cv2.circle(frame, center, ring_radius, (20, 20, 155), 2, lineType=cv2.LINE_AA)
    cv2.circle(frame, center, ring_radius - 16, (15, 15, 70), 1, lineType=cv2.LINE_AA)

    for angle_deg in range(0, 360, 45):
        angle = np.deg2rad(angle_deg)
        p1 = (
            int(round(center[0] + np.cos(angle) * (ring_radius - 4))),
            int(round(center[1] + np.sin(angle) * (ring_radius - 4))),
        )
        p2 = (
            int(round(center[0] + np.cos(angle) * (ring_radius + 5))),
            int(round(center[1] + np.sin(angle) * (ring_radius + 5))),
        )
        cv2.line(frame, p1, p2, (180, 180, 255), 1, lineType=cv2.LINE_AA)

    axis_color = (225, 225, 255)
    cv2.arrowedLine(
        frame,
        (center[0] - ring_radius + 18, center[1]),
        (center[0] + ring_radius - 10, center[1]),
        axis_color,
        1,
        tipLength=0.05,
    )
    cv2.arrowedLine(
        frame,
        (center[0], center[1] + ring_radius - 18),
        (center[0], center[1] - ring_radius + 10),
        axis_color,
        1,
        tipLength=0.05,
    )

    rotation_bias = float(np.degrees(np.arctan2(y_value, x_value)) * 0.18)
    for base_angle in (0.0, 120.0, 240.0):
        _draw_tomoe(frame, center, ring_radius - 8, base_angle + rotation_bias)

    cv2.circle(
        frame, center, max(18, size // 8), (12, 12, 55), -1, lineType=cv2.LINE_AA
    )
    cv2.circle(frame, center, max(11, size // 11), BLACK, -1, lineType=cv2.LINE_AA)
    cv2.circle(
        frame, center, max(5, size // 28), (15, 15, 120), -1, lineType=cv2.LINE_AA
    )

    dot = (
        int(round(center[0] + (track_radius * x_value))),
        int(round(center[1] + (track_radius * y_value))),
    )
    dot_color = GREEN if confidence >= 0.5 else YELLOW
    cv2.line(frame, center, dot, (235, 235, 255), 1, lineType=cv2.LINE_AA)
    cv2.circle(frame, dot, 9, WHITE, -1, lineType=cv2.LINE_AA)
    cv2.circle(frame, dot, 6, dot_color, -1, lineType=cv2.LINE_AA)

    cv2.putText(
        frame,
        label,
        (center[0] - int(size * 0.34), center[1] - outer_radius - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        WHITE,
        1,
        lineType=cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        "L",
        (center[0] - outer_radius - 10, center[1] + 5),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.50,
        WHITE,
        1,
        lineType=cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        "R",
        (center[0] + outer_radius + 2, center[1] + 5),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.50,
        WHITE,
        1,
        lineType=cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        "U",
        (center[0] - 6, center[1] - outer_radius - 8),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.40,
        WHITE,
        1,
        lineType=cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        "D",
        (center[0] - 6, center[1] + outer_radius + 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.40,
        WHITE,
        1,
        lineType=cv2.LINE_AA,
    )


def _draw_eye_debug_panels(
    frame: np.ndarray,
    estimate: EstimateResult,
    calibration_manager: CalibrationManager,
) -> None:
    frame_h, frame_w = frame.shape[:2]
    margin = 12
    gap = 10
    usable_width = frame_w - (2 * margin)
    usable_height = frame_h - (2 * margin)
    if usable_width < 120 or usable_height < 120:
        return

    panel_width = min(220, max(120, frame_w // 5), usable_width)
    panel_height = 120
    x = max(0, frame_w - panel_width - margin)
    y = margin
    source_frame = frame.copy()

    for eye in estimate.eyes[:2]:
        panel = _build_eye_debug_panel(
            source_frame=source_frame,
            eye=eye,
            panel_width=panel_width,
            panel_height=panel_height,
        )
        panel_h, panel_w = panel.shape[:2]
        if y >= frame_h - margin:
            break
        draw_h = min(panel_h, frame_h - y)
        draw_w = min(panel_w, frame_w - x)
        if draw_h <= 0 or draw_w <= 0:
            break
        frame[y : y + draw_h, x : x + draw_w] = panel[:draw_h, :draw_w]
        y += panel_h + gap


def _build_eye_debug_panel(
    source_frame: np.ndarray,
    eye: Any,
    panel_width: int,
    panel_height: int,
) -> np.ndarray:
    header_h = 20
    footer_h = 20
    inner_pad = 4
    image_h = panel_height - header_h - footer_h - (2 * inner_pad)
    image_w = panel_width - (2 * inner_pad)

    contour = np.asarray(eye.contour, dtype=np.int32)
    x, y, w, h = cv2.boundingRect(contour)
    pad_x = max(10, int(round(w * 0.35)))
    pad_y = max(10, int(round(h * 0.90)))

    x0 = max(0, x - pad_x)
    y0 = max(0, y - pad_y)
    x1 = min(source_frame.shape[1], x + w + pad_x)
    y1 = min(source_frame.shape[0], y + h + pad_y)
    crop = source_frame[y0:y1, x0:x1].copy()

    if crop.size == 0:
        crop = np.zeros((image_h, image_w, 3), dtype=np.uint8)
    else:
        local_contour = contour - np.array([[x0, y0]], dtype=np.int32)
        cv2.polylines(crop, [local_contour], isClosed=True, color=GREEN, thickness=1)
        cv2.circle(crop, (eye.corners[0][0] - x0, eye.corners[0][1] - y0), 2, CYAN, -1)
        cv2.circle(crop, (eye.corners[1][0] - x0, eye.corners[1][1] - y0), 2, CYAN, -1)
        cv2.circle(crop, (eye.top[0] - x0, eye.top[1] - y0), 2, YELLOW, -1)
        cv2.circle(crop, (eye.bottom[0] - x0, eye.bottom[1] - y0), 2, YELLOW, -1)
        for iris_point in eye.iris_points:
            cv2.circle(crop, (iris_point[0] - x0, iris_point[1] - y0), 2, WHITE, -1)

        local_center = (eye.iris_center[0] - x0, eye.iris_center[1] - y0)
        iris_radius = _estimate_iris_radius(eye)
        cv2.circle(crop, local_center, iris_radius, CYAN, 1, lineType=cv2.LINE_AA)
        cv2.drawMarker(
            crop,
            local_center,
            RED,
            markerType=cv2.MARKER_CROSS,
            markerSize=8,
            thickness=1,
        )

    scale = min(image_w / max(crop.shape[1], 1), image_h / max(crop.shape[0], 1))
    resized_w = max(1, int(round(crop.shape[1] * scale)))
    resized_h = max(1, int(round(crop.shape[0] * scale)))
    resized = cv2.resize(crop, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)

    panel = np.full((panel_height, panel_width, 3), (12, 12, 20), dtype=np.uint8)
    paste_x = inner_pad + ((image_w - resized_w) // 2)
    paste_y = header_h + inner_pad + ((image_h - resized_h) // 2)
    panel[paste_y : paste_y + resized_h, paste_x : paste_x + resized_w] = resized

    state = _eye_tracking_state(eye)
    border_color = GREEN if state == "ok" else (YELLOW if state == "weak" else RED)
    cv2.rectangle(panel, (0, 0), (panel_width - 1, panel_height - 1), border_color, 1)

    eye_label = "LEFT" if "33_133" in eye.name else "RIGHT"
    header = f"{eye_label} | {state.upper()}"
    footer = (
        f"q={eye.quality:.2f} h={eye.horizontal:+.2f} "
        f"v={eye.vertical:+.2f} cy={eye.min_clearance_y:+.2f}"
    )
    cv2.putText(
        panel,
        header,
        (6, 15),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        WHITE,
        1,
        lineType=cv2.LINE_AA,
    )
    cv2.putText(
        panel,
        footer,
        (6, panel_height - 6),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.40,
        WHITE,
        1,
        lineType=cv2.LINE_AA,
    )
    return panel


def _estimate_iris_radius(eye: Any) -> int:
    if hasattr(eye, "iris_radius"):
        return max(3, int(round(float(eye.iris_radius))))
    if not eye.iris_points:
        return 4
    center = np.asarray(eye.iris_center, dtype=np.float64)
    points = np.asarray(eye.iris_points, dtype=np.float64)
    distances = np.linalg.norm(points - center, axis=1)
    return max(3, int(round(float(np.mean(distances)))))


def _eye_tracking_state(eye: Any) -> str:
    if getattr(eye, "tracked", False) and getattr(eye, "quality", 0.0) >= 0.50:
        return "ok"
    if getattr(eye, "quality", 0.0) >= 0.28:
        return "weak"
    return "bad"


def _draw_tomoe(
    frame: np.ndarray, center: tuple[int, int], orbit_radius: int, angle_deg: float
) -> None:
    angle = np.deg2rad(angle_deg)
    head_center = (
        int(round(center[0] + np.cos(angle) * orbit_radius)),
        int(round(center[1] + np.sin(angle) * orbit_radius)),
    )
    tangent = np.array([-np.sin(angle), np.cos(angle)], dtype=np.float64)
    tail_center = (
        int(round(head_center[0] - tangent[0] * 11)),
        int(round(head_center[1] - tangent[1] * 11)),
    )

    cv2.ellipse(
        frame,
        tail_center,
        (12, 7),
        angle_deg + 90.0,
        200,
        360,
        BLACK,
        -1,
        lineType=cv2.LINE_AA,
    )
    cv2.circle(frame, head_center, 7, BLACK, -1, lineType=cv2.LINE_AA)
    cv2.circle(frame, head_center, 7, (0, 0, 70), 1, lineType=cv2.LINE_AA)


def _draw_calibration_target(
    frame: np.ndarray, calibration_manager: CalibrationManager
) -> None:
    target = calibration_manager.get_active_target()
    if target is None:
        return

    frame_h, frame_w = frame.shape[:2]
    x = int(round(target["screen_position"][0] * frame_w))
    y = int(round(target["screen_position"][1] * frame_h))
    stage = target["stage"]

    color = CYAN if stage == "settle" else RED
    cv2.circle(frame, (x, y), 36, color, 3)
    cv2.circle(frame, (x, y), 13, color, 3)
    cv2.line(frame, (x - 52, y), (x + 52, y), color, 2)
    cv2.line(frame, (x, y - 52), (x, y + 52), color, 2)

    label = f"{target['name'].upper()} {target['progress'] + 1}/{target['total']} | {stage} | {target['remaining']:.1f}s"
    cv2.putText(
        frame,
        label,
        (max(10, x - 140), max(35, y - 40)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.78,
        color,
        3,
    )


def _draw_benchmark_status(
    frame: np.ndarray, benchmark_status: dict[str, Any] | None
) -> None:
    if not benchmark_status or not benchmark_status.get("enabled", False):
        return

    protocol_title = str(benchmark_status.get("protocol_title", "No protocol label"))
    mode_parts = ["REPLAY" if benchmark_status.get("replay", False) else "LIVE"]
    if benchmark_status.get("logging", False):
        mode_parts.append("LOG")
    if benchmark_status.get("recording", False):
        mode_parts.append("REC")

    line1 = "BENCH | " + " | ".join(mode_parts)
    line2 = f"PROTO | {protocol_title}"
    collecting = bool(benchmark_status.get("collecting", False))
    armed = bool(benchmark_status.get("armed", False))
    settle_remaining_s = float(benchmark_status.get("settle_remaining_s", 0.0))
    auto_stop_remaining_s = float(benchmark_status.get("auto_stop_remaining_s", 0.0))
    collect_duration_s = float(benchmark_status.get("collect_duration_s", 0.0))

    panel_x = max(260, frame.shape[1] // 4)
    panel_y = 12
    panel_w = min(410, frame.shape[1] - panel_x - 12)
    panel_h = 54
    if panel_w < 180:
        panel_x = 10
        panel_w = min(410, frame.shape[1] - 20)
    if panel_w < 180:
        return

    overlay = frame.copy()
    cv2.rectangle(
        overlay,
        (panel_x, panel_y),
        (panel_x + panel_w, panel_y + panel_h),
        (18, 18, 28),
        -1,
        lineType=cv2.LINE_AA,
    )
    cv2.addWeighted(overlay, 0.62, frame, 0.38, 0.0, frame)

    border_color = CYAN if benchmark_status.get("replay", False) else YELLOW
    cv2.rectangle(
        frame,
        (panel_x, panel_y),
        (panel_x + panel_w, panel_y + panel_h),
        border_color,
        1,
        lineType=cv2.LINE_AA,
    )

    if collecting:
        indicator_color = GREEN
        indicator_text = (
            f"DATA {auto_stop_remaining_s:.1f}s"
            if collect_duration_s > 0.0
            else "DATA ON"
        )
    elif armed:
        indicator_color = YELLOW
        indicator_text = f"ARM {settle_remaining_s:.1f}s"
    else:
        indicator_color = RED
        indicator_text = "DATA OFF"
    indicator_center = (panel_x + panel_w - 70, panel_y + 18)
    cv2.circle(frame, indicator_center, 6, indicator_color, -1, lineType=cv2.LINE_AA)
    cv2.circle(frame, indicator_center, 6, WHITE, 1, lineType=cv2.LINE_AA)

    cv2.putText(
        frame,
        line1,
        (panel_x + 10, panel_y + 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        WHITE,
        1,
        lineType=cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        indicator_text,
        (panel_x + panel_w - 56, panel_y + 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        WHITE,
        1,
        lineType=cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        line2,
        (panel_x + 10, panel_y + 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        border_color,
        1,
        lineType=cv2.LINE_AA,
    )
