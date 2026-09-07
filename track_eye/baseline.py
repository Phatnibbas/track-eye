"""Browser-controlled baseline session sharing the production camera loop."""

from __future__ import annotations

import json
import statistics
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .output import OutputGain
from .rendering import draw_face_marker
from .tracker import EYE_DEFINITIONS, EMA_ALPHA, TrackingResult

OUTPUT_GAIN = OutputGain()
OUTPUT_DOWN_UP_RATIO = OUTPUT_GAIN.vertical_down / OUTPUT_GAIN.vertical_up
EYE_NAMES = [definition["name"] for definition in EYE_DEFINITIONS]


@dataclass(frozen=True)
class Phase:
    name: str
    instruction: str
    target: tuple[float, float]


PHASES = (
    Phase("center_left", "LOOK CENTER - HEAD STILL", (0.50, 0.50)),
    Phase("eyes_left", "EYES LEFT - HEAD STILL", (0.18, 0.50)),
    Phase("center_right", "RETURN TO CENTER - HEAD STILL", (0.50, 0.50)),
    Phase("eyes_right", "EYES RIGHT - HEAD STILL", (0.82, 0.50)),
    Phase("center_up", "RETURN TO CENTER - HEAD STILL", (0.50, 0.50)),
    Phase("eyes_up", "EYES UP - HEAD STILL", (0.50, 0.18)),
    Phase("center_down", "RETURN TO CENTER - HEAD STILL", (0.50, 0.50)),
    Phase("eyes_down", "EYES DOWN - HEAD STILL", (0.50, 0.82)),
    Phase("center_head", "LOOK CENTER - HEAD STILL", (0.50, 0.50)),
    Phase("head_left", "LOOK CENTER - MOVE HEAD LEFT", (0.50, 0.50)),
    Phase("head_right", "LOOK CENTER - MOVE HEAD RIGHT", (0.50, 0.50)),
    Phase("head_up", "LOOK CENTER - MOVE HEAD UP", (0.50, 0.50)),
    Phase("head_down", "LOOK CENTER - MOVE HEAD DOWN", (0.50, 0.50)),
)
REFERENCES = {
    "eyes_left": "center_left",
    "eyes_right": "center_right",
    "eyes_up": "center_up",
    "eyes_down": "center_down",
}


def empty_phase() -> dict:
    return {
        "frames": 0,
        "tracked_frames": 0,
        "read_failures": 0,
        "eyes": {name: {"x": [], "y": [], "raw_h": [], "raw_v": []} for name in EYE_NAMES},
    }


def summarize(values: list[float]) -> dict | None:
    if not values:
        return None
    data = np.asarray(values, dtype=np.float64)
    return {
        "mean": float(data.mean()),
        "std": float(data.std()),
        "p05": float(np.percentile(data, 5)),
        "p95": float(np.percentile(data, 95)),
    }


def separation(a: dict | None, b: dict | None) -> float | None:
    if a is None or b is None:
        return None
    return abs(a["mean"] - b["mean"]) / max(a["std"] + b["std"], 1e-6)


def mean_axis(phases: dict, phase: str, eye: str, axis: str) -> float | None:
    stats = phases.get(phase, {}).get("eyes", {}).get(eye, {}).get(axis)
    return None if stats is None else stats["mean"]


def build_analysis(phases: dict) -> dict:
    eyes: dict[str, dict] = {}
    gain_candidates = []
    for eye in EYE_NAMES:
        means = {
            phase: {axis: mean_axis(phases, phase, eye, axis) for axis in ("x", "y")}
            for phase in phases
        }

        def amplitude(pose: str, axis: str) -> float | None:
            pose_value = means.get(pose, {}).get(axis)
            ref_value = means.get(REFERENCES[pose], {}).get(axis)
            return None if pose_value is None or ref_value is None else abs(pose_value - ref_value)

        def pose_separation(pose: str, axis: str) -> float | None:
            return separation(
                phases.get(pose, {}).get("eyes", {}).get(eye, {}).get(axis),
                phases.get(REFERENCES[pose], {}).get("eyes", {}).get(eye, {}).get(axis),
            )

        left_amplitude = amplitude("eyes_left", "x")
        right_amplitude = amplitude("eyes_right", "x")
        up_amplitude = amplitude("eyes_up", "y")
        down_amplitude = amplitude("eyes_down", "y")
        left_separation = pose_separation("eyes_left", "x")
        right_separation = pose_separation("eyes_right", "x")
        up_separation = pose_separation("eyes_up", "y")
        down_separation = pose_separation("eyes_down", "y")
        horizontal_span = None if left_amplitude is None or right_amplitude is None else left_amplitude + right_amplitude
        vertical_span = None if up_amplitude is None or down_amplitude is None else up_amplitude + down_amplitude
        horizontal_separation = None if left_separation is None or right_separation is None else min(left_separation, right_separation)
        vertical_separation = None if up_separation is None or down_separation is None else min(up_separation, down_separation)
        reliable = (
            up_amplitude is not None and down_amplitude is not None and down_amplitude > 1e-4
            and up_separation is not None and down_separation is not None
            and up_separation >= 1.0 and down_separation >= 1.0
        )
        required_down_gain = up_amplitude / down_amplitude if reliable else None
        if required_down_gain is not None and 0.25 <= required_down_gain <= 4.0:
            gain_candidates.append(required_down_gain)
        center_stats = phases.get("center_head", {}).get("eyes", {}).get(eye, {})
        center_jitter = None
        if horizontal_span and vertical_span and center_stats.get("x") and center_stats.get("y"):
            center_jitter = {
                "x_over_span": center_stats["x"]["std"] / horizontal_span,
                "y_over_span": center_stats["y"]["std"] / vertical_span,
            }
        center_x = means.get("center_head", {}).get("x")
        center_y = means.get("center_head", {}).get("y")
        spans_reliable = (
            horizontal_separation is not None and vertical_separation is not None
            and horizontal_separation >= 1.0 and vertical_separation >= 1.0
        )
        head_drift = {}
        if center_x is not None and center_y is not None:
            for phase_name in ("head_left", "head_right", "head_up", "head_down"):
                px = means.get(phase_name, {}).get("x")
                py = means.get(phase_name, {}).get("y")
                if px is None or py is None:
                    continue
                head_drift[phase_name] = {
                    "dx": px - center_x,
                    "dy": py - center_y,
                    "normalized": None if not spans_reliable or not horizontal_span or not vertical_span else float(
                        np.hypot((px - center_x) / horizontal_span, (py - center_y) / vertical_span)
                    ),
                }
        eyes[eye] = {
            "horizontal_span": horizontal_span,
            "vertical_span": vertical_span,
            "horizontal_separation": horizontal_separation,
            "vertical_separation": vertical_separation,
            "left_separation": left_separation,
            "right_separation": right_separation,
            "up_separation": up_separation,
            "down_separation": down_separation,
            "up_amplitude": up_amplitude,
            "down_amplitude": down_amplitude,
            "required_down_gain": required_down_gain,
            "down_vs_up_after_current_gain": None if not reliable or not up_amplitude else down_amplitude * OUTPUT_DOWN_UP_RATIO / up_amplitude,
            "center_jitter": center_jitter,
            "head_drift": head_drift,
        }
    return {
        "eyes": eyes,
        "output_gain": {
            "horizontal": OUTPUT_GAIN.horizontal,
            "vertical_up": OUTPUT_GAIN.vertical_up,
            "vertical_down": OUTPUT_GAIN.vertical_down,
        },
        "measured_recommended_down_gain": statistics.median(gain_candidates) if gain_candidates else None,
    }


def build_report(raw_phases: dict, frame_times: list[float], config: dict) -> dict:
    phases = {}
    total_frames = total_tracked = total_failures = 0
    for name, raw in raw_phases.items():
        frames = raw["frames"]
        tracked = raw["tracked_frames"]
        total_frames += frames
        total_tracked += tracked
        total_failures += raw["read_failures"]
        phases[name] = {
            "frames": frames,
            "tracked_frames": tracked,
            "tracking_rate": tracked / frames if frames else 0.0,
            "read_failures": raw["read_failures"],
            "eyes": {eye: {axis: summarize(values) for axis, values in axes.items()} for eye, axes in raw["eyes"].items()},
        }
    report = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "config": config,
        "overall": {
            "frames": total_frames,
            "tracked_frames": total_tracked,
            "tracking_rate": total_tracked / total_frames if total_frames else 0.0,
            "read_failures": total_failures,
            "average_fps": None if not frame_times else 1.0 / statistics.mean(frame_times),
            "p95_frame_ms": None if not frame_times else float(np.percentile(frame_times, 95) * 1000.0),
        },
        "phases": phases,
    }
    report["analysis"] = build_analysis(phases)
    return report


def draw_prompt(frame: np.ndarray, headline: str, instruction: str, remaining: float, target: tuple[float, float], recording: bool, fps: float, face_found: bool) -> None:
    height, width = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (width, 112), (8, 10, 14), -1)
    cv2.addWeighted(overlay, 0.82, frame, 0.18, 0.0, frame)
    color = (40, 60, 255) if recording else (0, 210, 255)
    cv2.putText(frame, headline, (24, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.82, color, 2, cv2.LINE_AA)
    cv2.putText(frame, instruction, (24, 74), cv2.FONT_HERSHEY_SIMPLEX, 0.76, (245, 245, 245), 2, cv2.LINE_AA)
    cv2.putText(frame, f"{remaining:4.1f}s  |  FPS {fps:4.1f}  |  {'FACE OK' if face_found else 'NO FACE'}", (24, 101), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (190, 200, 210), 1, cv2.LINE_AA)
    tx, ty = int(target[0] * width), int(target[1] * height)
    cv2.circle(frame, (tx, ty), 18, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.circle(frame, (tx, ty), 10, (30, 30, 255), -1, cv2.LINE_AA)


class BaselineSession:
    def __init__(self, output_dir: Path, countdown: float = 3.0, duration: float = 6.0, min_tracking_rate: float = 0.80):
        self.output_dir = output_dir
        self.countdown = countdown
        self.duration = duration
        self.min_tracking_rate = min_tracking_rate
        self._lock = threading.Lock()
        self._state = "idle"
        self._start_requested = False
        self._face_ready_since: float | None = None
        self._phase_index = 0
        self._phase_started_at = 0.0
        self._raw_phases = {phase.name: empty_phase() for phase in PHASES}
        self._frame_times: list[float] = []
        self._report: dict | None = None
        self._json_path: str | None = None
        self._text_path: str | None = None
        self._camera_config: dict = {}

    def configure(self, camera_info: dict, device: str, mirror: bool) -> None:
        with self._lock:
            self._camera_config = {
                "device": device,
                "requested_width": 1280,
                "requested_height": 720,
                "actual_width": camera_info["width"],
                "actual_height": camera_info["height"],
                "actual_camera_fps": camera_info["fps"],
                "fourcc": camera_info["fourcc"],
                "mirror": mirror,
                "ema_alpha": EMA_ALPHA,
                "duration_seconds": self.duration,
                "countdown_seconds": self.countdown,
                "min_tracking_rate": self.min_tracking_rate,
                "phases": [phase.name for phase in PHASES],
            }

    def request_start(self) -> None:
        with self._lock:
            if self._state in ("idle", "completed", "error"):
                self._raw_phases = {phase.name: empty_phase() for phase in PHASES}
                self._frame_times = []
                self._report = None
                self._json_path = None
                self._text_path = None
                self._face_ready_since = None
                self._phase_index = 0
                self._state = "ready"
            self._start_requested = True

    def status(self) -> dict:
        with self._lock:
            now = time.perf_counter()
            phase = PHASES[self._phase_index] if self._phase_index < len(PHASES) else None
            ready = self._face_ready_since is not None and now - self._face_ready_since >= 1.0
            return {
                "state": self._state,
                "start_requested": self._start_requested,
                "face_ready": ready,
                "phase": None if phase is None else phase.name,
                "phase_index": self._phase_index + 1 if phase is not None else len(PHASES),
                "phase_total": len(PHASES),
                "instruction": None if phase is None else phase.instruction,
                "remaining_seconds": max(0.0, self._phase_started_at + (self.duration if self._state == "recording" else self.countdown) - now) if self._state in ("countdown", "recording") else None,
                "json_path": self._json_path,
                "text_path": self._text_path,
                "invalid_phases": [] if self._report is None else [
                    name for name, value in self._report["phases"].items() if value["tracking_rate"] < self.min_tracking_rate
                ],
            }

    def process(self, frame: np.ndarray, result: TrackingResult, fps: float, frame_time: float) -> bool:
        now = time.perf_counter()
        with self._lock:
            if result.face_detected:
                self._face_ready_since = self._face_ready_since or now
            else:
                self._face_ready_since = None
            if self._state == "ready":
                if self._start_requested and self._face_ready_since is not None and now - self._face_ready_since >= 1.0:
                    self._state = "countdown"
                    self._phase_started_at = now
            elif self._state == "countdown" and now - self._phase_started_at >= self.countdown:
                self._state = "recording"
                self._phase_started_at = now
            if self._state == "recording":
                phase = PHASES[self._phase_index]
                bucket = self._raw_phases[phase.name]
                bucket["frames"] += 1
                bucket["tracked_frames"] += int(result.face_detected)
                if result.eyes is not None:
                    for eye in result.eyes:
                        values = bucket["eyes"][eye.name]
                        values["x"].append(eye.x)
                        values["y"].append(eye.y)
                        values["raw_h"].append(eye.raw_h)
                        values["raw_v"].append(eye.raw_v)
                self._frame_times.append(frame_time)
                if now - self._phase_started_at >= self.duration:
                    self._phase_index += 1
                    if self._phase_index >= len(PHASES):
                        self._finish_report()
                    else:
                        self._state = "countdown"
                        self._phase_started_at = now
            state = self._state
            phase = PHASES[self._phase_index] if self._phase_index < len(PHASES) else PHASES[-1]
            if state == "ready":
                headline = "READY - PRESS START"
                remaining = 0.0
                recording = False
            elif state == "countdown":
                headline = "PREPARE"
                remaining = max(0.0, self._phase_started_at + self.countdown - now)
                recording = False
            elif state == "recording":
                headline = "RECORDING"
                remaining = max(0.0, self._phase_started_at + self.duration - now)
                recording = True
            else:
                return False
            if result.eyes is not None:
                for eye in result.eyes:
                    draw_face_marker(frame, eye)
            draw_prompt(frame, headline, phase.instruction, remaining, phase.target, recording, fps, result.face_detected)
            return True

    def _finish_report(self) -> None:
        config = dict(self._camera_config)
        self._report = build_report(self._raw_phases, self._frame_times, config)
        text = json.dumps(self._report, ensure_ascii=False, indent=2) + "\n"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.output_dir / f"tracking-baseline-{stamp}.json"
        text_path = self.output_dir / f"tracking-baseline-{stamp}.txt"
        json_path.write_text(text, encoding="utf-8")
        text_path.write_text(self._render_text_report(), encoding="utf-8")
        self._json_path = str(json_path)
        self._text_path = str(text_path)
        self._state = "completed"

    def _render_text_report(self) -> str:
        assert self._report is not None
        overall = self._report["overall"]
        lines = [
            "TRACK EYE BASELINE",
            "=" * 72,
            f"created: {self._report['created_at']}",
            f"camera: {self._report['config']['actual_width']}x{self._report['config']['actual_height']} @ {self._report['config']['actual_camera_fps']:.1f} fps, {self._report['config']['fourcc']}",
            f"runtime: avg {overall['average_fps']:.1f} fps, p95 {overall['p95_frame_ms']:.1f} ms/frame",
            f"tracking: {overall['tracked_frames']}/{overall['frames']} ({overall['tracking_rate'] * 100:.1f}%), camera read failures={overall['read_failures']}",
            "",
            "PHASES (canonical x: image-right positive, y: down positive)",
        ]
        for phase_name, phase in self._report["phases"].items():
            lines.append(f"  {phase_name:<12} tracking={phase['tracking_rate'] * 100:5.1f}% frames={phase['frames']}")
        analysis = self._report["analysis"]
        lines.extend(["", "SIGNAL ANALYSIS"])
        for eye, values in analysis["eyes"].items():
            lines.extend([
                f"  {eye}",
                f"    separation L/R/U/D: {values['left_separation']} / {values['right_separation']} / {values['up_separation']} / {values['down_separation']}",
                f"    up/down amplitude: {values['up_amplitude']} / {values['down_amplitude']}",
                f"    required down gain: {values['required_down_gain']}",
            ])
        lines.extend([
            "",
            "OUTPUT-GAIN DECISION",
            f"  horizontal gain: {OUTPUT_GAIN.horizontal:.2f}",
            f"  vertical up gain: {OUTPUT_GAIN.vertical_up:.2f}",
            f"  vertical down gain: {OUTPUT_GAIN.vertical_down:.2f}",
            f"  measured median required down gain: {analysis['measured_recommended_down_gain']}",
        ])
        return "\n".join(lines) + "\n"
