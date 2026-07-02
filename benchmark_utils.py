"""Phase 1 benchmarking helpers for session logging and replay."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

if TYPE_CHECKING:
    from gaze_estimator import EstimateResult


PROTOCOL_KEY_LABELS: dict[int, str] = {
    ord("0"): "none",
    ord("1"): "center_hold",
    ord("2"): "horizontal_sweep",
    ord("3"): "vertical_sweep",
    ord("4"): "diagonal_sweep",
    ord("5"): "head_motion",
    ord("6"): "blink_degrade",
}

PROTOCOL_LABEL_TITLES: dict[str, str] = {
    "none": "No protocol label",
    "center_hold": "Center hold",
    "horizontal_sweep": "Horizontal sweep",
    "vertical_sweep": "Vertical sweep",
    "diagonal_sweep": "Diagonal sweep",
    "head_motion": "Head motion",
    "blink_degrade": "Blink / one-eye degrade",
}


@dataclass
class ProtocolSpan:
    label: str
    start_frame: int
    end_frame: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
        }


class ProtocolTracker:
    """Tracks manual protocol labels or replays them from a saved timeline."""

    def __init__(self, replay_spans: list[ProtocolSpan] | None = None):
        self._replay_spans = replay_spans
        self._replay_index = 0
        self._live_spans: list[ProtocolSpan] = []
        self._current_label = "none"
        if replay_spans is None:
            self._live_spans.append(ProtocolSpan(label="none", start_frame=0))

    @property
    def is_replay(self) -> bool:
        return self._replay_spans is not None

    @property
    def current_label(self) -> str:
        return self._current_label

    @classmethod
    def load(cls, path: Path) -> "ProtocolTracker":
        payload = json.loads(path.read_text(encoding="utf-8"))
        spans = [
            ProtocolSpan(
                label=str(item["label"]),
                start_frame=int(item["start_frame"]),
                end_frame=(
                    None if item.get("end_frame") is None else int(item["end_frame"])
                ),
            )
            for item in payload.get("spans", [])
        ]
        _validate_spans(spans)
        return cls(replay_spans=spans)

    def set_live_label(self, label: str, next_frame_index: int) -> bool:
        if self.is_replay or label == self._current_label:
            return False

        if self._live_spans:
            self._live_spans[-1].end_frame = next_frame_index
        self._live_spans.append(ProtocolSpan(label=label, start_frame=next_frame_index))
        self._current_label = label
        return True

    def label_for_frame(self, frame_index: int) -> str:
        if not self.is_replay:
            return self._current_label

        spans = self._replay_spans or []
        if not spans:
            self._current_label = "none"
            return self._current_label

        while self._replay_index + 1 < len(spans):
            current_span = spans[self._replay_index]
            if current_span.end_frame is None or frame_index < current_span.end_frame:
                break
            self._replay_index += 1

        current_span = spans[self._replay_index]
        in_span = frame_index >= current_span.start_frame and (
            current_span.end_frame is None or frame_index < current_span.end_frame
        )
        self._current_label = current_span.label if in_span else "none"
        return self._current_label

    def finalize(self, total_frames: int) -> list[ProtocolSpan]:
        if not self.is_replay and self._live_spans:
            if self._live_spans[-1].end_frame is None:
                self._live_spans[-1].end_frame = total_frames
        return list(self._replay_spans or self._live_spans)

    def save(self, path: Path, total_frames: int) -> Path:
        spans = self.finalize(total_frames)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "total_frames": total_frames,
            "spans": [span.to_dict() for span in spans],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path


class LiveProtocolCollector:
    """Arms a label first, then starts collecting after a short settle delay."""

    def __init__(
        self, tracker: ProtocolTracker, settle_seconds: float, collect_seconds: float
    ):
        self.tracker = tracker
        self.settle_seconds = max(0.0, float(settle_seconds))
        self.collect_seconds = max(0.0, float(collect_seconds))
        self.pending_label: str | None = None
        self.pending_since_s: float | None = None
        self.active_label: str | None = None
        self.active_started_s: float | None = None

    def handle_label_press(self, label: str, frame_index: int, elapsed_s: float) -> str:
        if label == "none":
            self.pending_label = None
            self.pending_since_s = None
            if self.active_label is not None or self.tracker.current_label != "none":
                self._stop_collection(frame_index)
                return "Protocol collection stopped"
            return "Protocol cleared"

        if self.active_label is not None or self.tracker.current_label != "none":
            self._stop_collection(frame_index)

        self.pending_label = label
        self.pending_since_s = float(elapsed_s)
        if self.settle_seconds <= 0.0:
            self._activate(frame_index, elapsed_s)
            title = PROTOCOL_LABEL_TITLES.get(label, label)
            if self.collect_seconds > 0.0:
                return f"Collecting {title} for {self.collect_seconds:.1f}s"
            return f"Collecting {title}"

        return (
            f"Armed {PROTOCOL_LABEL_TITLES.get(label, label)} | "
            f"collecting in {self.settle_seconds:.1f}s"
        )

    def update(self, frame_index: int, elapsed_s: float) -> str | None:
        if self.pending_label is None or self.pending_since_s is None:
            return None
        if (elapsed_s - self.pending_since_s) < self.settle_seconds:
            return None

        activated_label = self.pending_label
        self._activate(frame_index, elapsed_s)
        return activated_label

    def finish_if_due(self, next_frame_index: int, elapsed_s: float) -> str | None:
        if self.active_label is None or self.active_started_s is None:
            return None
        if self.collect_seconds <= 0.0:
            return None
        if (elapsed_s - self.active_started_s) < self.collect_seconds:
            return None

        completed_label = self.active_label
        self._stop_collection(next_frame_index)
        return completed_label

    def current_collection_label(self) -> str | None:
        return (
            self.tracker.current_label if self.tracker.current_label != "none" else None
        )

    def status_snapshot(self, elapsed_s: float | None = None) -> dict[str, Any]:
        armed = self.pending_label is not None
        collecting = self.tracker.current_label != "none"
        display_label = self.pending_label if armed else self.tracker.current_label
        display_title = (
            PROTOCOL_LABEL_TITLES.get(display_label, display_label)
            if display_label is not None
            else "No protocol label"
        )
        settle_remaining_s = 0.0
        if armed:
            if elapsed_s is not None and self.pending_since_s is not None:
                settle_remaining_s = max(
                    0.0, self.settle_seconds - (elapsed_s - self.pending_since_s)
                )
            else:
                settle_remaining_s = self.settle_seconds

        collect_remaining_s = 0.0
        if collecting and self.collect_seconds > 0.0:
            if elapsed_s is not None and self.active_started_s is not None:
                collect_remaining_s = max(
                    0.0, self.collect_seconds - (elapsed_s - self.active_started_s)
                )
            else:
                collect_remaining_s = self.collect_seconds

        return {
            "armed": armed,
            "collecting": collecting,
            "protocol_label": display_label,
            "protocol_title": display_title,
            "settle_remaining_s": settle_remaining_s,
            "collect_remaining_s": collect_remaining_s,
        }

    def time_to_collect(self, elapsed_s: float) -> float:
        if self.pending_label is None or self.pending_since_s is None:
            return 0.0
        return max(0.0, self.settle_seconds - (elapsed_s - self.pending_since_s))

    def time_to_auto_stop(self, elapsed_s: float) -> float:
        if self.active_label is None or self.active_started_s is None:
            return 0.0
        if self.collect_seconds <= 0.0:
            return 0.0
        return max(0.0, self.collect_seconds - (elapsed_s - self.active_started_s))

    def _activate(self, frame_index: int, elapsed_s: float) -> None:
        if self.pending_label is not None:
            self.tracker.set_live_label(self.pending_label, frame_index)
            self.active_label = self.pending_label
            self.active_started_s = float(elapsed_s)
        self.pending_label = None
        self.pending_since_s = None

    def _stop_collection(self, next_frame_index: int) -> None:
        if self.tracker.current_label != "none":
            self.tracker.set_live_label("none", next_frame_index)
        self.active_label = None
        self.active_started_s = None


class SessionBenchmarkLogger:
    """Writes per-frame logs and a compact benchmark summary."""

    def __init__(
        self,
        log_path: Path | None,
        summary_path: Path | None,
        confidence_dropout_threshold: float,
        condition_metadata: dict[str, Any] | None = None,
    ):
        self.log_path = log_path
        self.summary_path = summary_path
        self.confidence_dropout_threshold = float(confidence_dropout_threshold)
        self.condition_metadata = dict(condition_metadata or {})
        self.records: list[dict[str, Any]] = []
        self._handle = None

        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.log_path.open("w", encoding="utf-8")

    @property
    def enabled(self) -> bool:
        return self.log_path is not None or self.summary_path is not None

    def log_frame(
        self,
        frame_index: int,
        elapsed_s: float,
        fps: float,
        protocol_label: str,
        estimate: "EstimateResult",
        session_state: str = "unknown",
        session_ready: bool = False,
        session_reason: str = "unknown",
        vertical_feature_mode: str = "current",
        servo_command: Any | None = None,
    ) -> None:
        left_eye = estimate.eyes[0] if len(estimate.eyes) >= 1 else None
        right_eye = estimate.eyes[1] if len(estimate.eyes) >= 2 else None
        disagreement_x = None
        disagreement_y = None
        if left_eye is not None and right_eye is not None:
            disagreement_x = abs(left_eye.horizontal - right_eye.horizontal)
            disagreement_y = abs(left_eye.vertical - right_eye.vertical)

        record = {
            "frame_index": frame_index,
            "elapsed_s": float(elapsed_s),
            "fps": float(fps),
            "protocol_label": protocol_label,
            "session_state": str(session_state),
            "session_ready": bool(session_ready),
            "session_reason": str(session_reason),
            "vertical_feature_mode": str(vertical_feature_mode),
            "x_ctrl": float(estimate.x_ctrl),
            "y_ctrl": float(estimate.y_ctrl),
            "raw_x": float(estimate.raw_x),
            "raw_y": float(estimate.raw_y),
            "x_eye": float(estimate.x_eye),
            "y_eye": float(estimate.y_eye),
            "confidence": float(estimate.confidence),
            "y_confidence": float(estimate.y_confidence),
            "vertical_reliability": float(estimate.vertical_reliability),
            "output_source": estimate.output_source,
            "pose_valid": bool(estimate.pose_valid),
            "head_pose_enabled": bool(estimate.head_pose_enabled),
            "yaw_deg": float(estimate.yaw_deg),
            "pitch_deg": float(estimate.pitch_deg),
            "head_pose_x": float(estimate.head_pose_x),
            "head_pose_y": float(estimate.head_pose_y),
            "face_detected": bool(estimate.face_detected),
            "valid": bool(estimate.valid),
            "message": estimate.message,
            "left_eye_quality": None if left_eye is None else float(left_eye.quality),
            "right_eye_quality": (
                None if right_eye is None else float(right_eye.quality)
            ),
            "left_h": None if left_eye is None else float(left_eye.horizontal),
            "right_h": None if right_eye is None else float(right_eye.horizontal),
            "left_v_prebaseline": (
                None if left_eye is None else float(left_eye.vertical_prebaseline)
            ),
            "right_v_prebaseline": (
                None if right_eye is None else float(right_eye.vertical_prebaseline)
            ),
            "left_v_postbaseline": None if left_eye is None else float(left_eye.vertical),
            "right_v_postbaseline": (
                None if right_eye is None else float(right_eye.vertical)
            ),
            "left_iris_v_raw": (
                None if left_eye is None else float(left_eye.iris_vertical_raw)
            ),
            "right_iris_v_raw": (
                None if right_eye is None else float(right_eye.iris_vertical_raw)
            ),
            "left_width": None if left_eye is None else float(left_eye.width),
            "right_width": None if right_eye is None else float(right_eye.width),
            "left_height": None if left_eye is None else float(left_eye.height),
            "right_height": None if right_eye is None else float(right_eye.height),
            "left_openness": None if left_eye is None else float(left_eye.openness),
            "right_openness": None if right_eye is None else float(right_eye.openness),
            "left_min_clearance_x": None if left_eye is None else float(left_eye.min_clearance_x),
            "right_min_clearance_x": None if right_eye is None else float(right_eye.min_clearance_x),
            "left_min_clearance_y": None if left_eye is None else float(left_eye.min_clearance_y),
            "right_min_clearance_y": None if right_eye is None else float(right_eye.min_clearance_y),
            "left_iris_radius": None if left_eye is None else float(left_eye.iris_radius),
            "right_iris_radius": None if right_eye is None else float(right_eye.iris_radius),
            "left_iris_center": None if left_eye is None else _point_to_list(left_eye.iris_center),
            "right_iris_center": None if right_eye is None else _point_to_list(right_eye.iris_center),
            "left_iris_points": None if left_eye is None else [_point_to_list(point) for point in left_eye.iris_points],
            "right_iris_points": None if right_eye is None else [_point_to_list(point) for point in right_eye.iris_points],
            "left_corners": None if left_eye is None else [_point_to_list(point) for point in left_eye.corners],
            "right_corners": None if right_eye is None else [_point_to_list(point) for point in right_eye.corners],
            "left_top": None if left_eye is None else _point_to_list(left_eye.top),
            "right_top": None if right_eye is None else _point_to_list(right_eye.top),
            "left_bottom": None if left_eye is None else _point_to_list(left_eye.bottom),
            "right_bottom": None if right_eye is None else _point_to_list(right_eye.bottom),
            "left_u": None if left_eye is None else _float_point_to_list(left_eye.local_u),
            "right_u": None if right_eye is None else _float_point_to_list(right_eye.local_u),
            "left_v_axis": None if left_eye is None else _float_point_to_list(left_eye.local_v),
            "right_v_axis": None if right_eye is None else _float_point_to_list(right_eye.local_v),
            "left_v_current_width_norm": None if left_eye is None else float(left_eye.vertical_prebaseline),
            "right_v_current_width_norm": None if right_eye is None else float(right_eye.vertical_prebaseline),
            "left_v_raw_px": None if left_eye is None else float(left_eye.iris_vertical_raw),
            "right_v_raw_px": None if right_eye is None else float(right_eye.iris_vertical_raw),
            "left_v_eyelid_relative": None if left_eye is None else float(left_eye.vertical_eyelid_relative),
            "right_v_eyelid_relative": None if right_eye is None else float(right_eye.vertical_eyelid_relative),
            "left_v_orbital_relative": None if left_eye is None else float(left_eye.vertical_orbital_relative),
            "right_v_orbital_relative": None if right_eye is None else float(right_eye.vertical_orbital_relative),
            "left_iris_ring_vertical_asymmetry": None if left_eye is None else float(left_eye.iris_ring_vertical_asymmetry),
            "right_iris_ring_vertical_asymmetry": None if right_eye is None else float(right_eye.iris_ring_vertical_asymmetry),
            "disagreement_x": disagreement_x,
            "disagreement_y": disagreement_y,
        }
        if servo_command is not None:
            record.update(
                {
                    "servo_pan_deg": float(servo_command.pan_deg),
                    "servo_tilt_deg": float(servo_command.tilt_deg),
                    "servo_gate_state": str(servo_command.gate_state),
                    "servo_reason": str(servo_command.reason),
                }
            )
        record.update(_condition_record_fields(self.condition_metadata))
        self.records.append(record)

        if self._handle is not None:
            self._handle.write(json.dumps(record, ensure_ascii=True) + "\n")
            self._handle.flush()

    def finalize(self, protocol_spans: list[ProtocolSpan]) -> dict[str, Any]:
        summary = self._build_summary(protocol_spans)
        if self._handle is not None:
            self._handle.close()
            self._handle = None

        if self.summary_path is not None:
            self.summary_path.parent.mkdir(parents=True, exist_ok=True)
            if self.summary_path.suffix.lower() == ".md":
                self.summary_path.write_text(
                    self._summary_to_markdown(summary), encoding="utf-8"
                )
            else:
                self.summary_path.write_text(
                    json.dumps(summary, indent=2), encoding="utf-8"
                )
        return summary

    def _build_summary(self, protocol_spans: list[ProtocolSpan]) -> dict[str, Any]:
        if not self.records:
            return {
                "logged_frames": 0,
                "active_duration_s": 0.0,
                "timeline_duration_s": 0.0,
                "overall": {},
                "segments": [],
                "protocol_spans": [span.to_dict() for span in protocol_spans],
            }

        fps_values = [record["fps"] for record in self.records if record["fps"] > 0.0]
        confidences = np.asarray(
            [record["confidence"] for record in self.records], dtype=np.float64
        )
        x_values = np.asarray(
            [record["x_ctrl"] for record in self.records], dtype=np.float64
        )
        y_values = np.asarray(
            [record["y_ctrl"] for record in self.records], dtype=np.float64
        )

        overall = {
            "mean_confidence": float(np.mean(confidences)),
            "confidence_dropout_rate": float(
                np.mean(confidences < self.confidence_dropout_threshold)
            ),
            "face_detected_rate": float(
                np.mean([record["face_detected"] for record in self.records])
            ),
            "valid_rate": float(np.mean([record["valid"] for record in self.records])),
            "x_std": float(np.std(x_values)),
            "y_std": float(np.std(y_values)),
            "fps_p50": _percentile(fps_values, 50.0),
            "fps_p95": _percentile(fps_values, 95.0),
            "output_source_counts": dict(
                Counter(record["output_source"] for record in self.records)
            ),
        }

        label_counts: dict[str, int] = defaultdict(int)
        segments: list[dict[str, Any]] = []
        active_duration_s = 0.0
        for span in protocol_spans:
            if span.label == "none":
                continue
            span_records = [
                record
                for record in self.records
                if record["frame_index"] >= span.start_frame
                and (span.end_frame is None or record["frame_index"] < span.end_frame)
            ]
            label_counts[span.label] += 1
            segment_id = f"{span.label}#{label_counts[span.label]}"
            segment = self._build_segment_summary(span.label, segment_id, span_records)
            segment["start_frame"] = span.start_frame
            segment["end_frame"] = span.end_frame
            active_duration_s += segment["duration_s"]
            segments.append(segment)

        return {
            "logged_frames": len(self.records),
            "active_duration_s": float(active_duration_s),
            "timeline_duration_s": float(
                self.records[-1]["elapsed_s"] - self.records[0]["elapsed_s"]
            ),
            "overall": overall,
            "segments": segments,
            "protocol_spans": [span.to_dict() for span in protocol_spans],
        }

    def _build_segment_summary(
        self, label: str, segment_id: str, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if not records:
            return {
                "id": segment_id,
                "label": label,
                "title": PROTOCOL_LABEL_TITLES.get(label, label),
                "frame_count": 0,
                "duration_s": 0.0,
                "mean_confidence": 0.0,
                "confidence_dropout_rate": 0.0,
                "x_std": 0.0,
                "y_std": 0.0,
                "x_range": 0.0,
                "y_range": 0.0,
                "mean_abs_x": 0.0,
                "mean_abs_y": 0.0,
                "mean_disagreement_x": 0.0,
                "mean_disagreement_y": 0.0,
            }

        x_values = np.asarray(
            [record["x_ctrl"] for record in records], dtype=np.float64
        )
        y_values = np.asarray(
            [record["y_ctrl"] for record in records], dtype=np.float64
        )
        confidences = np.asarray(
            [record["confidence"] for record in records], dtype=np.float64
        )
        disagreement_x = np.asarray(
            [
                np.nan if record["disagreement_x"] is None else record["disagreement_x"]
                for record in records
            ],
            dtype=np.float64,
        )
        disagreement_y = np.asarray(
            [
                np.nan if record["disagreement_y"] is None else record["disagreement_y"]
                for record in records
            ],
            dtype=np.float64,
        )

        summary = {
            "id": segment_id,
            "label": label,
            "title": PROTOCOL_LABEL_TITLES.get(label, label),
            "frame_count": len(records),
            "duration_s": _records_duration_s(records),
            "mean_confidence": float(np.mean(confidences)),
            "confidence_dropout_rate": float(
                np.mean(confidences < self.confidence_dropout_threshold)
            ),
            "x_std": float(np.std(x_values)),
            "y_std": float(np.std(y_values)),
            "x_range": float(np.ptp(x_values)),
            "y_range": float(np.ptp(y_values)),
            "mean_abs_x": float(np.mean(np.abs(x_values))),
            "mean_abs_y": float(np.mean(np.abs(y_values))),
            "mean_disagreement_x": _nanmean(disagreement_x),
            "mean_disagreement_y": _nanmean(disagreement_y),
        }

        if label == "center_hold":
            radii = np.sqrt((x_values * x_values) + (y_values * y_values))
            summary["center_jitter"] = float(np.std(radii))
            settle_time = _estimate_settle_time(records)
            if settle_time is not None:
                summary["settle_time_s"] = settle_time
        elif label == "horizontal_sweep":
            summary["primary_range"] = float(np.ptp(x_values))
            summary["cross_axis_leakage"] = float(np.mean(np.abs(y_values)))
        elif label == "vertical_sweep":
            summary["primary_range"] = float(np.ptp(y_values))
            summary["cross_axis_leakage"] = float(np.mean(np.abs(x_values)))
        elif label == "diagonal_sweep":
            summary["xy_correlation"] = _safe_correlation(x_values, y_values)
        elif label == "head_motion":
            summary["drift_span"] = float(max(np.ptp(x_values), np.ptp(y_values)))
        elif label == "blink_degrade":
            summary["dropout_frames"] = int(
                np.sum(confidences < self.confidence_dropout_threshold)
            )
        return summary

    def _summary_to_markdown(self, summary: dict[str, Any]) -> str:
        lines = ["# Benchmark Summary", ""]
        lines.append(f"- Logged frames: {summary['logged_frames']}")
        lines.append(f"- Active labeled duration: {summary['active_duration_s']:.2f}s")
        lines.append(f"- Timeline span: {summary['timeline_duration_s']:.2f}s")
        overall = summary.get("overall", {})
        if overall:
            lines.append(f"- Mean confidence: {overall['mean_confidence']:.3f}")
            lines.append(
                f"- Confidence dropout rate: {overall['confidence_dropout_rate']:.3f}"
            )
            lines.append(
                f"- FPS p50/p95: {overall['fps_p50']:.2f} / {overall['fps_p95']:.2f}"
            )
            lines.append("")
            lines.append("## Segments")
            lines.append("")

        for segment in summary.get("segments", []):
            lines.append(f"### {segment['title']} (`{segment['id']}`)")
            lines.append("")
            lines.append(f"- Frames: {segment['frame_count']}")
            lines.append(f"- Duration: {segment['duration_s']:.2f}s")
            if segment.get("start_frame") is not None:
                lines.append(
                    f"- Frame span: {segment['start_frame']} -> {segment['end_frame']}"
                )
            lines.append(f"- Mean confidence: {segment['mean_confidence']:.3f}")
            lines.append(
                f"- X std/range: {segment['x_std']:.3f} / {segment['x_range']:.3f}"
            )
            lines.append(
                f"- Y std/range: {segment['y_std']:.3f} / {segment['y_range']:.3f}"
            )
            if "cross_axis_leakage" in segment:
                lines.append(
                    f"- Cross-axis leakage: {segment['cross_axis_leakage']:.3f}"
                )
            if "center_jitter" in segment:
                lines.append(f"- Center jitter: {segment['center_jitter']:.3f}")
            if "settle_time_s" in segment:
                lines.append(f"- Settle time: {segment['settle_time_s']:.3f}s")
            lines.append("")
        return "\n".join(lines).strip() + "\n"


class InputVideoRecorder:
    """Records raw mirrored input frames for deterministic replay."""

    def __init__(self, path: Path, fps_hint: float = 30.0):
        self.path = path
        self.fps_hint = float(max(fps_hint, 1.0))
        self._writer: cv2.VideoWriter | None = None

    def write(self, frame_bgr: np.ndarray) -> None:
        if self._writer is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            height, width = frame_bgr.shape[:2]
            fourcc = getattr(cv2, "VideoWriter_fourcc")(*"mp4v")
            writer = cv2.VideoWriter(
                str(self.path), fourcc, self.fps_hint, (width, height)
            )
            if not writer.isOpened():
                raise RuntimeError(f"Failed to open video writer: {self.path}")
            self._writer = writer
        self._writer.write(frame_bgr)

    def close(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None


def default_summary_path(log_path: Path) -> Path:
    return log_path.with_suffix(".summary.md")


def _point_to_list(point: tuple[int, int]) -> list[int]:
    return [int(point[0]), int(point[1])]


def _float_point_to_list(point: tuple[float, float]) -> list[float]:
    return [float(point[0]), float(point[1])]


def _condition_record_fields(metadata: dict[str, Any]) -> dict[str, str]:
    return {
        "condition_id": str(metadata.get("condition_id", "unspecified")),
        "condition_glasses": str(metadata.get("glasses", "unspecified")),
        "condition_lighting": str(metadata.get("lighting", "unspecified")),
        "condition_distance_notes": str(metadata.get("distance_notes", "unspecified")),
        "condition_target_visibility": str(
            metadata.get("target_visibility", "unspecified")
        ),
    }


def default_protocol_labels_path(base_path: Path) -> Path:
    return base_path.with_suffix(".labels.json")


def describe_protocol_keys() -> str:
    parts = [
        "0 none",
        "1 center",
        "2 horiz",
        "3 vert",
        "4 diag",
        "5 head",
        "6 blink",
    ]
    return " | ".join(parts)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile))


def _nanmean(values: np.ndarray) -> float:
    if values.size == 0 or np.all(np.isnan(values)):
        return 0.0
    return float(np.nanmean(values))


def _safe_correlation(x_values: np.ndarray, y_values: np.ndarray) -> float:
    if x_values.size < 2 or y_values.size < 2:
        return 0.0
    if np.allclose(np.std(x_values), 0.0) or np.allclose(np.std(y_values), 0.0):
        return 0.0
    corr = np.corrcoef(x_values, y_values)
    return float(corr[0, 1])


def _estimate_settle_time(records: list[dict[str, Any]]) -> float | None:
    if len(records) < 12:
        return None

    stable_slice = records[len(records) // 2 :]
    target_x = float(np.median([record["x_ctrl"] for record in stable_slice]))
    target_y = float(np.median([record["y_ctrl"] for record in stable_slice]))
    tolerance = 0.08
    consecutive_required = min(10, len(records))

    for start_index in range(0, len(records) - consecutive_required + 1):
        window = records[start_index : start_index + consecutive_required]
        stable = True
        for record in window:
            dx = record["x_ctrl"] - target_x
            dy = record["y_ctrl"] - target_y
            if np.hypot(dx, dy) > tolerance:
                stable = False
                break
        if stable:
            return float(window[0]["elapsed_s"] - records[0]["elapsed_s"])
    return None


def _records_duration_s(records: list[dict[str, Any]]) -> float:
    if not records:
        return 0.0
    if len(records) == 1:
        fps = float(records[0].get("fps", 0.0))
        return float(1.0 / fps) if fps > 1e-6 else 0.0
    return float(records[-1]["elapsed_s"] - records[0]["elapsed_s"])


def _validate_spans(spans: list[ProtocolSpan]) -> None:
    previous_end = 0
    for index, span in enumerate(spans):
        if span.start_frame < 0:
            raise ValueError("Protocol span start_frame must be >= 0")
        if span.end_frame is not None and span.end_frame < span.start_frame:
            raise ValueError("Protocol span end_frame must be >= start_frame")
        if index > 0 and span.start_frame < previous_end:
            raise ValueError("Protocol spans must be sorted and non-overlapping")
        previous_end = span.start_frame if span.end_frame is None else span.end_frame
