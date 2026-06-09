"""Realtime eye feature extraction and control estimation."""

from __future__ import annotations

from itertools import permutations
from dataclasses import dataclass
from typing import Any

import cv2
import mediapipe as mp
import numpy as np

from calibration import AxisCalibrationModel, LinearCalibrationModel
from calibration_coupled import CoupledCalibrationModel
from constants import EYE_DEFINITIONS, IRIS_GROUPS, ORBITAL_LANDMARKS
from filters import EMAFilter, apply_dead_zone, clamp


FloatPoint = tuple[float, float]
IntPoint = tuple[int, int]


@dataclass
class EyeMeasurement:
    """Debug geometry for a single eye."""

    name: str
    contour: list[IntPoint]
    corners: tuple[IntPoint, IntPoint]
    top: IntPoint
    bottom: IntPoint
    iris_center: IntPoint
    iris_points: list[IntPoint]
    horizontal: float
    vertical: float
    iris_vertical_raw: float
    vertical_prebaseline: float
    local_u: FloatPoint
    local_v: FloatPoint
    vertical_eyelid_relative: float
    vertical_orbital_relative: float
    iris_ring_vertical_asymmetry: float
    openness: float
    width: float
    height: float
    iris_radius: float
    min_clearance_x: float
    min_clearance_y: float
    quality: float
    tracked: bool


@dataclass
class EstimateResult:
    """Output of one estimator step."""

    x_ctrl: float
    y_ctrl: float
    raw_x: float
    raw_y: float
    fallback_x: float
    fallback_y: float
    x_eye: float
    y_eye: float
    yaw_deg: float
    pitch_deg: float
    head_pose_x: float
    head_pose_y: float
    pose_valid: bool
    head_pose_enabled: bool
    confidence: float
    feature_vector: np.ndarray | None
    eyes: list[EyeMeasurement]
    fusion_mode: str
    left_weight: float
    right_weight: float
    eye_disagreement_x: float
    eye_disagreement_y: float
    vertical_reliability: float
    y_confidence: float
    face_detected: bool
    valid: bool
    output_source: str = "hold"
    message: str = ""

    @classmethod
    def empty(cls, message: str = "No data") -> "EstimateResult":
        return cls(
            x_ctrl=0.0,
            y_ctrl=0.0,
            raw_x=0.0,
            raw_y=0.0,
            fallback_x=0.0,
            fallback_y=0.0,
            x_eye=0.0,
            y_eye=0.0,
            yaw_deg=0.0,
            pitch_deg=0.0,
            head_pose_x=0.0,
            head_pose_y=0.0,
            pose_valid=False,
            head_pose_enabled=False,
            confidence=0.0,
            feature_vector=None,
            eyes=[],
            fusion_mode="none",
            left_weight=0.0,
            right_weight=0.0,
            eye_disagreement_x=0.0,
            eye_disagreement_y=0.0,
            vertical_reliability=0.0,
            y_confidence=0.0,
            face_detected=False,
            valid=False,
            message=message,
        )


class GazeEstimator:
    """CPU-first gaze estimator built on MediaPipe FaceMesh."""

    def __init__(self, config: dict[str, Any]):
        self.scale_x = float(config.get("control_scale_x", 1.6))
        self.scale_y = float(config.get("control_scale_y", 1.8))
        self.dead_zone = float(config.get("dead_zone", 0.08))
        self.dead_zone_y = float(config.get("dead_zone_y", max(self.dead_zone, 0.05)))
        self.min_confidence_for_update = float(
            config.get("min_confidence_for_update", 0.45)
        )
        self.min_confidence_for_update_y = float(
            config.get(
                "min_confidence_for_update_y", max(self.min_confidence_for_update, 0.45)
            )
        )
        self.low_conf_hold_frames = int(config.get("low_conf_hold_frames", 6))
        self.low_conf_decay = float(config.get("low_conf_decay", 0.92))
        self.partial_confidence_threshold = float(
            config.get("partial_confidence_threshold", 0.20)
        )
        self.partial_confidence_threshold_y = float(
            config.get(
                "partial_confidence_threshold_y",
                max(self.partial_confidence_threshold, 0.28),
            )
        )
        self.partial_blend_min = float(config.get("partial_blend_min", 0.25))
        self.partial_blend_min_y = float(
            config.get("partial_blend_min_y", max(0.15, self.partial_blend_min * 0.72))
        )
        self.calibration_output_floor = float(
            config.get("calibration_output_floor", 0.05)
        )
        self.calibration_raw_fallback_threshold = float(
            config.get("calibration_raw_fallback_threshold", 0.12)
        )
        self.calibration_min_training_range_x = float(
            config.get("calibration_min_training_range_x", 0.05)
        )
        self.calibration_min_training_range_y = float(
            config.get("calibration_min_training_range_y", 0.06)
        )
        self.head_pose_enabled = bool(config.get("head_pose_enabled", True))
        self.head_pose_gain_x = float(config.get("head_pose_gain_x", 0.18))
        self.head_pose_gain_y = float(config.get("head_pose_gain_y", 0.12))
        self.head_pose_yaw_norm_deg = float(config.get("head_pose_yaw_norm_deg", 20.0))
        self.head_pose_pitch_norm_deg = float(
            config.get("head_pose_pitch_norm_deg", 16.0)
        )
        self.max_head_pose_yaw_deg = float(config.get("max_head_pose_yaw_deg", 45.0))
        self.max_head_pose_pitch_deg = float(
            config.get("max_head_pose_pitch_deg", 35.0)
        )
        self.raw_center_x = 0.0
        self.raw_center_y = 0.0
        self.raw_recenter_alpha = float(config.get("raw_recenter_alpha", 0.85))
        self.raw_recenter_min_confidence = float(
            config.get("raw_recenter_min_confidence", 0.35)
        )
        self.fusion_disagreement_threshold_x = float(
            config.get("fusion_disagreement_threshold_x", 0.18)
        )
        self.fusion_disagreement_threshold_y = float(
            config.get("fusion_disagreement_threshold_y", 0.16)
        )
        self.fusion_dominance_gap = float(config.get("fusion_dominance_gap", 0.08))
        self.fusion_strategy = str(config.get("fusion_strategy", "weighted")).strip()
        self.disagreement_outlier_weight = float(
            config.get("disagreement_outlier_weight", 0.08)
        )
        self.mono_fallback_quality = float(config.get("mono_fallback_quality", 0.56))
        self.mono_confidence_penalty = float(
            config.get("mono_confidence_penalty", 0.78)
        )
        self.mono_vertical_penalty = float(config.get("mono_vertical_penalty", 0.78))
        self.vertical_soft_disagreement_y = float(
            config.get("vertical_soft_disagreement_y", 0.10)
        )
        self.vertical_hard_disagreement_y = float(
            config.get("vertical_hard_disagreement_y", 0.28)
        )
        self.vertical_min_reliability = float(
            config.get("vertical_min_reliability", 0.22)
        )
        self.vertical_clearance_soft_floor = float(
            config.get("vertical_clearance_soft_floor", -0.10)
        )
        self.vertical_clearance_hard_floor = float(
            config.get("vertical_clearance_hard_floor", -0.26)
        )
        self.vertical_openness_soft_floor = float(
            config.get("vertical_openness_soft_floor", 0.11)
        )
        self.vertical_openness_hard_floor = float(
            config.get("vertical_openness_hard_floor", 0.06)
        )
        self.vertical_orbital_norm_gain = float(
            config.get("vertical_orbital_norm_gain", 0.5)
        )
        self.vertical_width_norm_gain = float(
            config.get("vertical_width_norm_gain", 0.30)
        )
        self.vertical_feature_mode = str(
            config.get("vertical_feature_mode", "current")
        ).strip()
        if self.vertical_feature_mode not in {"current", "orbital_relative"}:
            raise ValueError(
                "Unsupported vertical_feature_mode="
                f"{self.vertical_feature_mode!r}; use 'current' or 'orbital_relative'"
            )

        # Per-eye vertical baseline: capture iris_vertical when looking straight
        # This removes the natural iris offset (iris doesn't sit on corner-to-corner line)
        self.left_vertical_baseline = None
        self.right_vertical_baseline = None
        self.vertical_baseline_frames = 0
        self.vertical_baseline_required = 15  # ~0.5s at 30fps

        if self.fusion_strategy not in {"weighted", "mean"}:
            raise ValueError(
                f"Unsupported fusion_strategy={self.fusion_strategy!r}; use 'weighted' or 'mean'"
            )

        alpha = float(config.get("smoothing_alpha", 0.35))
        alpha_y = float(config.get("smoothing_alpha_y", min(alpha, 0.42)))
        self.x_filter = EMAFilter(alpha=alpha)
        self.y_filter = EMAFilter(alpha=alpha_y)
        self.last_output = (0.0, 0.0)
        self.lost_frames = 0

        self.face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=float(config.get("min_detection_confidence", 0.5)),
            min_tracking_confidence=float(config.get("min_tracking_confidence", 0.5)),
        )
        self.head_pose_indices = [1, 152, 33, 263, 61, 291]
        self.head_pose_model_points = np.asarray(
            [
                (0.0, 0.0, 0.0),
                (0.0, -63.6, -12.5),
                (-43.3, 32.7, -26.0),
                (43.3, 32.7, -26.0),
                (-28.9, -28.9, -24.1),
                (28.9, -28.9, -24.1),
            ],
            dtype=np.float64,
        )

    def reset_filters(self) -> None:
        self.x_filter.reset(0.0)
        self.y_filter.reset(0.0)
        self.last_output = (0.0, 0.0)
        self.lost_frames = 0
        # Reset vertical baselines
        self.left_vertical_baseline = None
        self.right_vertical_baseline = None
        self.vertical_baseline_frames = 0

    def reset_raw_center(self) -> None:
        self.raw_center_x = 0.0
        self.raw_center_y = 0.0

    def recenter_raw(
        self, feature_vector: np.ndarray | None, confidence: float
    ) -> tuple[bool, str]:
        if feature_vector is None:
            return False, "Raw recenter failed: no eye features"
        if confidence < self.raw_recenter_min_confidence:
            return (
                False,
                "Raw recenter failed: confidence too low "
                f"({confidence:.2f} < {self.raw_recenter_min_confidence:.2f})",
            )

        vector = np.asarray(feature_vector, dtype=np.float64)
        fx = float(np.mean([vector[0], vector[2]]))
        fy = float(np.mean([vector[1], vector[3]]))

        old_center_x = self.raw_center_x
        old_center_y = self.raw_center_y
        self.raw_center_x = ((1.0 - self.raw_recenter_alpha) * old_center_x) + (
            self.raw_recenter_alpha * fx
        )
        self.raw_center_y = ((1.0 - self.raw_recenter_alpha) * old_center_y) + (
            self.raw_recenter_alpha * fy
        )
        return (
            True,
            f"Raw recentered (dx={self.raw_center_x - old_center_x:+.3f}, "
            f"dy={self.raw_center_y - old_center_y:+.3f})",
        )

    def close(self) -> None:
        self.face_mesh.close()

    def toggle_head_pose(self) -> bool:
        self.head_pose_enabled = not self.head_pose_enabled
        return self.head_pose_enabled

    def process(
        self,
        frame_bgr: np.ndarray,
        calibration_model: (
            LinearCalibrationModel
            | AxisCalibrationModel
            | CoupledCalibrationModel
            | None
        ) = None,
    ) -> EstimateResult:
        rgb_frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb_frame.flags.writeable = False
        results = self.face_mesh.process(rgb_frame)

        if not results.multi_face_landmarks:
            return self._handle_missing("No face detected")

        frame_h, frame_w = frame_bgr.shape[:2]
        landmarks = results.multi_face_landmarks[0].landmark
        pixel_points = [
            (
                float(np.clip(landmark.x, 0.0, 1.0) * frame_w),
                float(np.clip(landmark.y, 0.0, 1.0) * frame_h),
            )
            for landmark in landmarks
        ]

        pose_valid, yaw_deg, pitch_deg, head_pose_x, head_pose_y = (
            self._estimate_head_pose(
                pixel_points=pixel_points,
                frame_w=frame_w,
                frame_h=frame_h,
            )
        )

        eyes, feature_vector, x_eye, y_eye, fusion_mode, left_weight, right_weight = (
            self._extract_eye_features(pixel_points)
        )
        if len(eyes) == 0:
            return self._handle_missing("Eye landmarks unstable", face_detected=True)

        confidence = self._compute_confidence(
            eyes, fusion_mode, left_weight, right_weight
        )
        eye_disagreement_x = 0.0
        eye_disagreement_y = 0.0
        if len(eyes) >= 2:
            eye_disagreement_x = abs(eyes[0].horizontal - eyes[1].horizontal)
            eye_disagreement_y = abs(eyes[0].vertical - eyes[1].vertical)

        vertical_reliability = self._compute_vertical_reliability(
            eyes=eyes,
            fusion_mode=fusion_mode,
            disagreement_y=eye_disagreement_y,
        )
        centered_x_eye = x_eye - self.raw_center_x
        centered_y_eye = y_eye - self.raw_center_y
        fallback_x = clamp(centered_x_eye * self.scale_x)
        fallback_y = clamp((centered_y_eye * self.scale_y) * vertical_reliability)

        if (
            calibration_model is not None
            and feature_vector is not None
            and fusion_mode == "binocular"
        ):
            calibrated_x, calibrated_y = calibration_model.predict(feature_vector)
            axis_x_usable = True
            axis_y_usable = True
            if isinstance(calibration_model, AxisCalibrationModel):
                axis_x_usable = calibration_model.x_is_usable(
                    self.calibration_min_training_range_x
                )
                axis_y_usable = calibration_model.y_is_usable(
                    self.calibration_min_training_range_y
                )
            use_raw_x = not axis_x_usable or (
                abs(fallback_x) >= self.calibration_raw_fallback_threshold
                and abs(calibrated_x) <= self.calibration_output_floor
            )
            use_raw_y = not axis_y_usable or (
                abs(fallback_y) >= self.calibration_raw_fallback_threshold
                and abs(calibrated_y) <= self.calibration_output_floor
            )
            raw_x = fallback_x if use_raw_x else calibrated_x
            raw_y = fallback_y if use_raw_y else calibrated_y

            if use_raw_x and use_raw_y:
                output_source = "raw-fallback"
            elif use_raw_x or use_raw_y:
                output_source = "hybrid-fallback"
            else:
                output_source = "calibrated"
        else:
            raw_x, raw_y = fallback_x, fallback_y
            output_source = "raw"

        if fusion_mode.startswith("mono"):
            output_source = f"{output_source}-{fusion_mode}"

        if self.head_pose_enabled and pose_valid:
            raw_x = clamp(raw_x - (self.head_pose_gain_x * head_pose_x))
            raw_y = clamp(raw_y - (self.head_pose_gain_y * head_pose_y))
            output_source = f"{output_source}-pose"

        # Y-axis confidence for stabilization (currently same as overall confidence)
        y_confidence = confidence

        x_ctrl, y_ctrl, valid, output_source = self._stabilize_output(
            raw_x,
            raw_y,
            confidence,
            y_confidence,
            output_source,
        )

        return EstimateResult(
            x_ctrl=x_ctrl,
            y_ctrl=y_ctrl,
            raw_x=raw_x,
            raw_y=raw_y,
            fallback_x=fallback_x,
            fallback_y=fallback_y,
            x_eye=centered_x_eye,
            y_eye=centered_y_eye,
            yaw_deg=yaw_deg,
            pitch_deg=pitch_deg,
            head_pose_x=head_pose_x,
            head_pose_y=head_pose_y,
            pose_valid=pose_valid,
            head_pose_enabled=self.head_pose_enabled,
            confidence=confidence,
            feature_vector=feature_vector,
            eyes=eyes,
            fusion_mode=fusion_mode,
            left_weight=left_weight,
            right_weight=right_weight,
            eye_disagreement_x=eye_disagreement_x,
            eye_disagreement_y=eye_disagreement_y,
            vertical_reliability=vertical_reliability,
            y_confidence=y_confidence,
            face_detected=True,
            valid=valid,
            output_source=output_source,
            message=self._build_message(
                eyes,
                fusion_mode,
                confidence,
                valid,
                pose_valid,
                self.head_pose_enabled,
            ),
        )

    def _handle_missing(
        self, message: str, face_detected: bool = False
    ) -> EstimateResult:
        self.lost_frames += 1
        x_ctrl, y_ctrl = self.last_output
        if self.lost_frames > self.low_conf_hold_frames:
            x_ctrl *= self.low_conf_decay
            y_ctrl *= self.low_conf_decay
            self.last_output = (x_ctrl, y_ctrl)

        result = EstimateResult.empty(message=message)
        result.x_ctrl = x_ctrl
        result.y_ctrl = y_ctrl
        result.face_detected = face_detected
        result.output_source = "hold"
        result.head_pose_enabled = self.head_pose_enabled
        return result

    def _extract_eye_features(
        self,
        pixel_points: list[FloatPoint],
    ) -> tuple[
        list[EyeMeasurement], np.ndarray | None, float, float, str, float, float
    ]:
        eye_slots: list[dict[str, Any]] = []
        for eye_definition in EYE_DEFINITIONS:
            corners = [pixel_points[index] for index in eye_definition["corners"]]
            left_corner = min(corners, key=lambda point: point[0])
            right_corner = max(corners, key=lambda point: point[0])
            top_points = [pixel_points[index] for index in eye_definition["top"]]
            bottom_points = [pixel_points[index] for index in eye_definition["bottom"]]
            top = tuple(np.median(np.asarray(top_points, dtype=np.float64), axis=0))
            bottom = tuple(
                np.median(np.asarray(bottom_points, dtype=np.float64), axis=0)
            )
            contour = [pixel_points[index] for index in eye_definition["contour"]]

            # Extract orbital landmarks for vertical normalization
            orbital = ORBITAL_LANDMARKS.get(eye_definition["name"], {})
            brow_points = [pixel_points[i] for i in orbital.get("brow", [])]
            cheek_points = [pixel_points[i] for i in orbital.get("cheek", [])]
            brow = (
                tuple(np.median(np.asarray(brow_points, dtype=np.float64), axis=0))
                if brow_points
                else top
            )
            cheek = (
                tuple(np.median(np.asarray(cheek_points, dtype=np.float64), axis=0))
                if cheek_points
                else bottom
            )

            eye_slots.append(
                {
                    "name": eye_definition["name"],
                    "left_corner": left_corner,
                    "right_corner": right_corner,
                    "top": top,
                    "bottom": bottom,
                    "contour": contour,
                    "brow": brow,
                    "cheek": cheek,
                    "center_x": (left_corner[0] + right_corner[0]) * 0.5,
                }
            )

        iris_candidates = []
        for iris_group in IRIS_GROUPS:
            iris_points = [pixel_points[index] for index in iris_group]
            iris_center = tuple(
                np.mean(np.asarray(iris_points, dtype=np.float64), axis=0)
            )
            iris_candidates.append({"points": iris_points, "center": iris_center})

        eye_slots.sort(key=lambda eye: eye["center_x"])
        paired_slots = self._pair_eyes_and_irises(eye_slots, iris_candidates)

        eyes: list[EyeMeasurement] = []
        for eye_slot, iris in paired_slots:
            left_corner = eye_slot["left_corner"]
            right_corner = eye_slot["right_corner"]
            top = eye_slot["top"]
            bottom = eye_slot["bottom"]
            iris_center = iris["center"]

            left_corner_vec = np.asarray(left_corner, dtype=np.float64)
            right_corner_vec = np.asarray(right_corner, dtype=np.float64)
            top_vec = np.asarray(top, dtype=np.float64)
            bottom_vec = np.asarray(bottom, dtype=np.float64)
            brow_vec = np.asarray(eye_slot["brow"], dtype=np.float64)
            cheek_vec = np.asarray(eye_slot["cheek"], dtype=np.float64)
            iris_vec = np.asarray(iris_center, dtype=np.float64)

            eye_axis = right_corner_vec - left_corner_vec
            width = float(np.linalg.norm(eye_axis))
            if width < 10.0:
                continue

            u = eye_axis / width
            v = np.asarray([-u[1], u[0]], dtype=np.float64)
            eye_center = 0.5 * (left_corner_vec + right_corner_vec)

            top_local = float(np.dot(top_vec - eye_center, v))
            bottom_local = float(np.dot(bottom_vec - eye_center, v))
            if top_local > bottom_local:
                top_local, bottom_local = bottom_local, top_local

            height = bottom_local - top_local
            if height < 4.0:
                continue

            iris_horizontal = float(np.dot(iris_vec - left_corner_vec, u))
            iris_vertical = float(np.dot(iris_vec - eye_center, v))
            iris_offsets = np.asarray(iris["points"], dtype=np.float64) - iris_vec
            iris_radius = float(np.mean(np.linalg.norm(iris_offsets, axis=1)))

            horizontal = (iris_horizontal / width) * 2.0 - 1.0
            openness = height / width
            left_clearance = iris_horizontal - iris_radius
            right_clearance = width - iris_horizontal - iris_radius
            top_clearance = (iris_vertical - iris_radius) - top_local
            bottom_clearance = bottom_local - (iris_vertical + iris_radius)

            # Legacy eyelid-based vertical (for A/B comparison only)
            vertical_denom_legacy = max(
                abs(top_clearance) + abs(bottom_clearance), height * 0.35, 1e-6
            )
            vertical_legacy = (top_clearance - bottom_clearance) / vertical_denom_legacy

            brow_local = float(np.dot(brow_vec - eye_center, v))
            cheek_local = float(np.dot(cheek_vec - eye_center, v))
            orbital_top = min(brow_local, cheek_local)
            orbital_bottom = max(brow_local, cheek_local)
            orbital_center = (orbital_top + orbital_bottom) * 0.5
            orbital_height = max(orbital_bottom - orbital_top, 1e-6)
            vertical_orbital = (iris_vertical - orbital_center) / (
                orbital_height * max(self.vertical_orbital_norm_gain, 1e-6)
            )

            # Width-normalized vertical: iris displacement / eye_width
            # Eye width is stable across up/down gaze and scales with distance.
            # Brow/cheek (orbital) landmarks are kept for reliability/debug only.
            vertical = iris_vertical / max(
                width * self.vertical_width_norm_gain, 1e-6
            )
            active_vertical = vertical
            if self.vertical_feature_mode == "orbital_relative":
                active_vertical = vertical_orbital
            vertical_prebaseline = clamp(float(active_vertical), -1.5, 1.5)
            iris_local_y = (np.asarray(iris["points"], dtype=np.float64) - eye_center) @ v
            iris_ring_vertical_asymmetry = float(
                ((np.max(iris_local_y) + np.min(iris_local_y)) * 0.5 - iris_vertical)
                / max(iris_radius, 1e-6)
            )

            min_clearance_x = float(min(left_clearance, right_clearance) / width)
            min_clearance_y = float(min(top_clearance, bottom_clearance) / height)
            quality = self._compute_eye_quality(
                openness=float(openness),
                horizontal=float(horizontal),
                vertical=float(vertical),
                iris_radius=iris_radius,
                height=height,
                min_clearance_x=min_clearance_x,
                min_clearance_y=min_clearance_y,
            )
            tracked = quality >= 0.42

            eyes.append(
                EyeMeasurement(
                    name=eye_slot["name"],
                    contour=[self._to_int(point) for point in eye_slot["contour"]],
                    corners=(self._to_int(left_corner), self._to_int(right_corner)),
                    top=self._to_int(top),
                    bottom=self._to_int(bottom),
                    iris_center=self._to_int(iris_center),
                    iris_points=[self._to_int(point) for point in iris["points"]],
                    horizontal=clamp(float(horizontal), -1.5, 1.5),
                    vertical=vertical_prebaseline,
                    iris_vertical_raw=iris_vertical,
                    vertical_prebaseline=vertical_prebaseline,
                    local_u=(float(u[0]), float(u[1])),
                    local_v=(float(v[0]), float(v[1])),
                    vertical_eyelid_relative=clamp(float(vertical_legacy), -1.5, 1.5),
                    vertical_orbital_relative=clamp(float(vertical_orbital), -1.5, 1.5),
                    iris_ring_vertical_asymmetry=clamp(
                        float(iris_ring_vertical_asymmetry), -1.5, 1.5
                    ),
                    openness=float(openness),
                    width=width,
                    height=float(height),
                    iris_radius=iris_radius,
                    min_clearance_x=min_clearance_x,
                    min_clearance_y=min_clearance_y,
                    quality=quality,
                    tracked=tracked,
                )
            )

        if not eyes:
            return eyes, None, 0.0, 0.0, "none", 0.0, 0.0

        # Capture per-eye vertical baselines from first good frames
        # This removes natural iris offset (iris doesn't sit on corner-to-corner line)
        if (
            len(eyes) == 2
            and self.vertical_baseline_frames < self.vertical_baseline_required
        ):
            avg_confidence = (eyes[0].quality + eyes[1].quality) / 2.0
            if avg_confidence >= 0.45:
                left_raw = eyes[0].vertical
                right_raw = eyes[1].vertical
                n = self.vertical_baseline_frames
                if self.left_vertical_baseline is None:
                    self.left_vertical_baseline = left_raw
                    self.right_vertical_baseline = right_raw
                else:
                    self.left_vertical_baseline = (n * self.left_vertical_baseline + left_raw) / (n + 1)
                    self.right_vertical_baseline = (n * self.right_vertical_baseline + right_raw) / (n + 1)
                self.vertical_baseline_frames += 1
                if self.vertical_baseline_frames == self.vertical_baseline_required:
                    print(
                        f"[INFO] Vertical baselines locked: "
                        f"L={self.left_vertical_baseline:+.3f}, R={self.right_vertical_baseline:+.3f}"
                    )

        # Subtract baselines from per-eye vertical features
        if self.left_vertical_baseline is not None and len(eyes) >= 1:
            eyes[0].vertical = eyes[0].vertical - self.left_vertical_baseline
        if self.right_vertical_baseline is not None and len(eyes) >= 2:
            eyes[1].vertical = eyes[1].vertical - self.right_vertical_baseline

        x_eye, y_eye, fusion_mode, left_weight, right_weight = self._fuse_eyes(eyes)
        feature_vector = (
            np.asarray(
                [
                    eyes[0].horizontal,
                    eyes[0].vertical,
                    eyes[1].horizontal,
                    eyes[1].vertical,
                ],
                dtype=np.float64,
            )
            if len(eyes) == 2 and fusion_mode == "binocular"
            else None
        )
        return (
            eyes,
            feature_vector,
            x_eye,
            y_eye,
            fusion_mode,
            left_weight,
            right_weight,
        )

    def _fuse_eyes(
        self, eyes: list[EyeMeasurement]
    ) -> tuple[float, float, str, float, float]:
        if len(eyes) == 1:
            eye = eyes[0]
            if "33_133" in eye.name:
                return eye.horizontal, eye.vertical, "mono-left", 1.0, 0.0
            return eye.horizontal, eye.vertical, "mono-right", 0.0, 1.0

        left_eye, right_eye = eyes[0], eyes[1]
        if self.fusion_strategy == "mean":
            return (
                float((left_eye.horizontal + right_eye.horizontal) * 0.5),
                float((left_eye.vertical + right_eye.vertical) * 0.5),
                "binocular",
                0.5,
                0.5,
            )

        left_weight = self._base_eye_weight(left_eye)
        right_weight = self._base_eye_weight(right_eye)
        disagreement_x = abs(left_eye.horizontal - right_eye.horizontal)
        disagreement_y = abs(left_eye.vertical - right_eye.vertical)

        if (
            disagreement_x > self.fusion_disagreement_threshold_x
            or disagreement_y > self.fusion_disagreement_threshold_y
        ):
            if abs(left_eye.quality - right_eye.quality) >= self.fusion_dominance_gap:
                if left_eye.quality > right_eye.quality:
                    right_weight *= self.disagreement_outlier_weight
                else:
                    left_weight *= self.disagreement_outlier_weight

        total_weight = left_weight + right_weight
        if total_weight <= 1e-6:
            return 0.0, 0.0, "none", 0.0, 0.0

        left_weight /= total_weight
        right_weight /= total_weight
        if left_weight >= 0.85 and left_eye.quality >= self.mono_fallback_quality:
            return left_eye.horizontal, left_eye.vertical, "mono-left", 1.0, 0.0
        if right_weight >= 0.85 and right_eye.quality >= self.mono_fallback_quality:
            return right_eye.horizontal, right_eye.vertical, "mono-right", 0.0, 1.0
        if (
            left_eye.tracked
            and not right_eye.tracked
            and left_eye.quality >= self.mono_fallback_quality
        ):
            return left_eye.horizontal, left_eye.vertical, "mono-left", 1.0, 0.0
        if (
            right_eye.tracked
            and not left_eye.tracked
            and right_eye.quality >= self.mono_fallback_quality
        ):
            return right_eye.horizontal, right_eye.vertical, "mono-right", 0.0, 1.0

        x_eye = float(
            (left_weight * left_eye.horizontal) + (right_weight * right_eye.horizontal)
        )
        y_eye = float(
            (left_weight * left_eye.vertical) + (right_weight * right_eye.vertical)
        )
        return x_eye, y_eye, "binocular", left_weight, right_weight

    @staticmethod
    def _base_eye_weight(eye: EyeMeasurement) -> float:
        weight = max(eye.quality, 0.05)
        if not eye.tracked:
            weight *= 0.45
        return float(weight)

    def _pair_eyes_and_irises(
        self,
        eye_slots: list[dict[str, Any]],
        iris_candidates: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        if len(eye_slots) != len(iris_candidates):
            return list(zip(eye_slots, iris_candidates))

        best_cost: float | None = None
        best_pairs: list[tuple[dict[str, Any], dict[str, Any]]] | None = None

        for iris_perm in permutations(iris_candidates, len(eye_slots)):
            total_cost = 0.0
            for eye_slot, iris in zip(eye_slots, iris_perm):
                left_corner = np.asarray(eye_slot["left_corner"], dtype=np.float64)
                right_corner = np.asarray(eye_slot["right_corner"], dtype=np.float64)
                eye_center = 0.5 * (left_corner + right_corner)
                iris_center = np.asarray(iris["center"], dtype=np.float64)

                width = max(float(np.linalg.norm(right_corner - left_corner)), 1e-6)
                horizontal_cost = abs(float(iris_center[0] - eye_center[0])) / width
                vertical_cost = abs(float(iris_center[1] - eye_center[1])) / width

                left_bound = min(left_corner[0], right_corner[0]) - (0.35 * width)
                right_bound = max(left_corner[0], right_corner[0]) + (0.35 * width)
                outside_penalty = 0.0
                if iris_center[0] < left_bound or iris_center[0] > right_bound:
                    outside_penalty += 4.0

                total_cost += horizontal_cost + (0.35 * vertical_cost) + outside_penalty

            if best_cost is None or total_cost < best_cost:
                best_cost = total_cost
                best_pairs = list(zip(eye_slots, iris_perm))

        return (
            best_pairs
            if best_pairs is not None
            else list(zip(eye_slots, iris_candidates))
        )

    def _compute_confidence(
        self,
        eyes: list[EyeMeasurement],
        fusion_mode: str,
        left_weight: float,
        right_weight: float,
    ) -> float:
        if not eyes:
            return 0.0

        if fusion_mode.startswith("mono") or len(eyes) == 1:
            eye = (
                eyes[0]
                if len(eyes) == 1
                else (eyes[0] if left_weight >= right_weight else eyes[1])
            )
            confidence = (0.08 + (0.76 * eye.quality)) * self.mono_confidence_penalty
            if not eye.tracked:
                confidence *= 0.75
            return clamp(float(min(confidence, 0.82)), 0.0, 1.0)

        left_eye, right_eye = eyes
        disagreement_x = abs(left_eye.horizontal - right_eye.horizontal)
        disagreement_y = abs(left_eye.vertical - right_eye.vertical)
        agreement_x = float(
            np.interp(disagreement_x, [0.0, 0.10, 0.32], [1.0, 0.75, 0.0])
        )
        agreement_y = float(
            np.interp(disagreement_y, [0.0, 0.08, 0.24], [1.0, 0.75, 0.0])
        )
        tracking_quality = (0.65 * min(left_eye.quality, right_eye.quality)) + (
            0.35
            * ((left_weight * left_eye.quality) + (right_weight * right_eye.quality))
        )
        confidence = (
            0.10
            + (0.55 * tracking_quality)
            + (0.18 * agreement_x)
            + (0.17 * agreement_y)
        )
        if not all(eye.tracked for eye in eyes):
            confidence *= 0.85
        return clamp(float(confidence), 0.0, 1.0)

    def _compute_vertical_reliability(
        self,
        eyes: list[EyeMeasurement],
        fusion_mode: str,
        disagreement_y: float,
    ) -> float:
        if not eyes:
            return 0.0

        min_clearance_y = min(eye.min_clearance_y for eye in eyes)
        min_openness = min(eye.openness for eye in eyes)
        tracked_ratio = sum(1 for eye in eyes if eye.tracked) / max(len(eyes), 1)

        disagreement_score = float(
            np.interp(
                disagreement_y,
                [
                    0.0,
                    self.vertical_soft_disagreement_y,
                    self.vertical_hard_disagreement_y,
                ],
                [1.0, 0.74, self.vertical_min_reliability],
            )
        )
        clearance_score = float(
            np.interp(
                min_clearance_y,
                [
                    self.vertical_clearance_hard_floor,
                    self.vertical_clearance_soft_floor,
                    0.02,
                ],
                [self.vertical_min_reliability, 0.72, 1.0],
            )
        )
        openness_score = float(
            np.interp(
                min_openness,
                [
                    self.vertical_openness_hard_floor,
                    self.vertical_openness_soft_floor,
                    0.20,
                ],
                [self.vertical_min_reliability, 0.68, 1.0],
            )
        )
        tracking_score = float(
            np.interp(tracked_ratio, [0.0, 0.5, 1.0], [0.3, 0.68, 1.0])
        )

        reliability = (
            (0.36 * disagreement_score)
            + (0.26 * clearance_score)
            + (0.20 * openness_score)
            + (0.18 * tracking_score)
        )

        if fusion_mode.startswith("mono"):
            reliability *= self.mono_vertical_penalty

        floor = self.vertical_min_reliability
        if fusion_mode.startswith("mono"):
            floor = min(
                floor, self.vertical_min_reliability * self.mono_vertical_penalty
            )

        return clamp(float(reliability), floor, 1.0)

    def _compute_eye_quality(
        self,
        openness: float,
        horizontal: float,
        vertical: float,
        iris_radius: float,
        height: float,
        min_clearance_x: float,
        min_clearance_y: float,
    ) -> float:
        openness_score = float(np.interp(openness, [0.08, 0.22], [0.0, 1.0]))
        horizontal_score = float(
            np.interp(abs(horizontal), [0.0, 0.85, 1.22], [1.0, 0.92, 0.0])
        )
        vertical_score = float(
            np.interp(abs(vertical), [0.0, 0.78, 1.18], [1.0, 0.92, 0.0])
        )
        margin_x_score = float(np.interp(min_clearance_x, [-0.12, 0.02], [0.0, 1.0]))
        margin_y_score = float(np.interp(min_clearance_y, [-0.28, 0.00], [0.0, 1.0]))
        radius_ratio = iris_radius / max(height, 1e-6)
        radius_score = clamp(1.0 - (abs(radius_ratio - 0.36) / 0.32), 0.0, 1.0)
        quality = (
            (0.18 * openness_score)
            + (0.16 * horizontal_score)
            + (0.12 * vertical_score)
            + (0.18 * margin_x_score)
            + (0.22 * margin_y_score)
            + (0.14 * radius_score)
        )
        return clamp(float(quality), 0.0, 1.0)

    def _estimate_head_pose(
        self,
        pixel_points: list[FloatPoint],
        frame_w: int,
        frame_h: int,
    ) -> tuple[bool, float, float, float, float]:
        if not self.head_pose_enabled:
            return False, 0.0, 0.0, 0.0, 0.0

        try:
            image_points = np.asarray(
                [pixel_points[index] for index in self.head_pose_indices],
                dtype=np.float64,
            )
            focal_length = float(frame_w)
            camera_matrix = np.asarray(
                [
                    [focal_length, 0.0, frame_w / 2.0],
                    [0.0, focal_length, frame_h / 2.0],
                    [0.0, 0.0, 1.0],
                ],
                dtype=np.float64,
            )
            dist_coeffs = np.zeros((4, 1), dtype=np.float64)

            ok, rotation_vec, translation_vec = cv2.solvePnP(
                self.head_pose_model_points,
                image_points,
                camera_matrix,
                dist_coeffs,
                flags=cv2.SOLVEPNP_ITERATIVE,
            )
            if not ok:
                return False, 0.0, 0.0, 0.0, 0.0

            rotation_matrix, _ = cv2.Rodrigues(rotation_vec)
            projection_matrix = np.hstack((rotation_matrix, translation_vec))
            _, _, _, _, _, _, euler_angles = cv2.decomposeProjectionMatrix(
                projection_matrix
            )

            pitch_deg = float(euler_angles[0][0])
            yaw_deg = float(euler_angles[1][0])
            pitch_deg = self._normalize_pose_angle(pitch_deg)
            yaw_deg = self._normalize_pose_angle(yaw_deg)
            if (
                abs(yaw_deg) > self.max_head_pose_yaw_deg
                or abs(pitch_deg) > self.max_head_pose_pitch_deg
            ):
                return False, yaw_deg, pitch_deg, 0.0, 0.0
            head_pose_x = clamp(
                yaw_deg / max(self.head_pose_yaw_norm_deg, 1e-6), -1.5, 1.5
            )
            head_pose_y = clamp(
                pitch_deg / max(self.head_pose_pitch_norm_deg, 1e-6), -1.5, 1.5
            )
            return True, yaw_deg, pitch_deg, float(head_pose_x), float(head_pose_y)
        except Exception:  # noqa: BLE001
            return False, 0.0, 0.0, 0.0, 0.0

    @staticmethod
    def _normalize_pose_angle(angle_deg: float) -> float:
        normalized = ((angle_deg + 180.0) % 360.0) - 180.0
        if normalized > 90.0:
            normalized -= 180.0
        elif normalized < -90.0:
            normalized += 180.0
        return float(normalized)

    @staticmethod
    def _build_message(
        eyes: list[EyeMeasurement],
        fusion_mode: str,
        confidence: float,
        valid: bool,
        pose_valid: bool,
        head_pose_enabled: bool,
    ) -> str:
        if not eyes:
            return "Eye landmarks unstable"
        if head_pose_enabled and not pose_valid:
            return "Eye tracking only (pose filtered)"
        if fusion_mode.startswith("mono"):
            return "One-eye fallback"
        if not all(eye.tracked for eye in eyes):
            return "Iris tracking weak"
        if confidence < 0.45:
            return "Low confidence"
        return "OK" if valid else "Low confidence"

    def _stabilize_output(
        self,
        raw_x: float,
        raw_y: float,
        confidence: float,
        y_confidence: float,
        output_source: str,
    ) -> tuple[float, float, bool, str]:
        x_target, x_state = self._axis_target(
            raw_value=raw_x,
            last_value=self.last_output[0],
            confidence=confidence,
            partial_threshold=self.partial_confidence_threshold,
            full_threshold=self.min_confidence_for_update,
            blend_min=self.partial_blend_min,
        )
        y_target, y_state = self._axis_target(
            raw_value=raw_y,
            last_value=self.last_output[1],
            confidence=y_confidence,
            partial_threshold=self.partial_confidence_threshold_y,
            full_threshold=self.min_confidence_for_update_y,
            blend_min=self.partial_blend_min_y,
        )

        if x_state != "hold" or y_state != "hold":
            self.lost_frames = 0
            smoothed_x = self.x_filter.update(x_target)
            smoothed_y = self.y_filter.update(y_target)
            x_ctrl = clamp(apply_dead_zone(smoothed_x, self.dead_zone))
            y_ctrl = clamp(apply_dead_zone(smoothed_y, self.dead_zone_y))
            self.last_output = (x_ctrl, y_ctrl)

            suffixes = []
            if x_state == "partial" or y_state == "partial":
                suffixes.append("partial")
            if x_state == "hold":
                suffixes.append("xhold")
            if y_state == "hold":
                suffixes.append("yhold")
            merged_source = output_source
            if suffixes:
                merged_source = output_source + "-" + "-".join(suffixes)
            return (
                x_ctrl,
                y_ctrl,
                (x_state != "hold" and y_state != "hold"),
                merged_source,
            )

        self.lost_frames += 1
        x_ctrl, y_ctrl = self.last_output
        if self.lost_frames > self.low_conf_hold_frames:
            x_ctrl *= self.low_conf_decay
            y_ctrl *= self.low_conf_decay
            self.last_output = (x_ctrl, y_ctrl)
        return x_ctrl, y_ctrl, False, f"{output_source}-hold"

    @staticmethod
    def _axis_target(
        raw_value: float,
        last_value: float,
        confidence: float,
        partial_threshold: float,
        full_threshold: float,
        blend_min: float,
    ) -> tuple[float, str]:
        if confidence >= full_threshold:
            return raw_value, "full"
        if confidence >= partial_threshold:
            blend = np.interp(
                confidence,
                [partial_threshold, full_threshold],
                [blend_min, 1.0],
            )
            blended_value = ((1.0 - blend) * last_value) + (blend * raw_value)
            return float(blended_value), "partial"
        return last_value, "hold"

    @staticmethod
    def _to_int(point: FloatPoint) -> IntPoint:
        return int(round(point[0])), int(round(point[1]))
