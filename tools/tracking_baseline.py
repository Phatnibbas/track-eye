"""Controlled browser-guided baseline for the current per-eye tracker.

The runner does not alter the tracking algorithm. It records the production
FaceMesh measurement before the display-only down-gain, shows each pose in the
browser stream, and writes a compact JSON plus a human-readable report.
 

Run on the Pi with the camera free:
    .venv/bin/python tools/tracking_baseline.py --web-ui-host 0.0.0.0
    # open http://<pi-ip>:8080 before the start countdown ends
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent

from track_eye.camera import DEFAULT_DEVICE, Camera, CameraConfig  # noqa: E402
from track_eye.output import OutputGain  # noqa: E402
from track_eye.rendering import draw_face_marker  # noqa: E402
from track_eye.tracker import EYE_DEFINITIONS, EMA_ALPHA, EyeTracker  # noqa: E402
from track_eye.web import FrameHub, WebUIServer  # noqa: E402

OUTPUT_GAIN = OutputGain()
OUTPUT_DOWN_UP_RATIO = OUTPUT_GAIN.vertical_down / OUTPUT_GAIN.vertical_up


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
PHASE_BY_NAME = {phase.name: phase for phase in PHASES}
EYE_NAMES = [definition["name"] for definition in EYE_DEFINITIONS]


def render_baseline_html(_ws_port: int) -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Track Eye Baseline</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; background: #050607; color: #f4efe4;
           font-family: system-ui, sans-serif; display: grid; place-items: center; }
    main { width: min(96vw, 1280px); }
    h1 { margin: 0 0 8px; font-size: 22px; letter-spacing: .08em; }
    p { margin: 0 0 12px; color: #aeb5bf; }
    button { margin-bottom: 12px; padding: 8px 18px; cursor: pointer; }
    img { display: block; width: 100%; max-height: 84vh; object-fit: contain;
          border: 1px solid #343940; border-radius: 12px; background: #000; }
  </style>
</head>
<body><main>
  <h1>TRACK EYE BASELINE</h1>
  <p>Keep your head still. Press Start when FACE OK is stable, then follow the target.</p>
  <button id="start">Start recording</button>
  <img src="/stream.mjpg" alt="baseline camera stream">
  <script>
    document.getElementById("start").onclick = async () => {
      await fetch("/start");
      document.getElementById("start").disabled = true;
      document.getElementById("start").textContent = "Recording started";
    };
  </script>
</main></body>
</html>"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Controlled per-eye tracking baseline")
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fourcc", default="MJPG")
    parser.add_argument("--web-ui-host", default="0.0.0.0")
    parser.add_argument("--web-ui-port", type=int, default=8080)
    parser.add_argument("--start-delay", type=float, default=0.0, help="Headless pre-start delay; web mode uses Start button by default")
    parser.add_argument("--countdown", type=float, default=3.0)
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument(
        "--phases",
        default=",".join(phase.name for phase in PHASES),
        help="Comma-separated subset of: " + ",".join(phase.name for phase in PHASES),
    )
    parser.add_argument("--min-tracking-rate", type=float, default=0.80)
    parser.add_argument("--no-mirror", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=_REPO_ROOT / "benchmark_data")
    return parser.parse_args(argv)


def selected_phases(value: str) -> list[Phase]:
    names = [name.strip() for name in value.split(",") if name.strip()]
    unknown = [name for name in names if name not in PHASE_BY_NAME]
    if unknown:
        raise ValueError("unknown phases: " + ", ".join(unknown))
    if not names:
        raise ValueError("at least one phase is required")
    return [PHASE_BY_NAME[name] for name in names]


def empty_phase() -> dict:
    return {
        "frames": 0,
        "tracked_frames": 0,
        "read_failures": 0,
        "eyes": {name: {"x": [], "y": [], "raw_h": [], "raw_v": []} for name in EYE_NAMES},
    }


def draw_prompt(
    frame: np.ndarray,
    headline: str,
    instruction: str,
    remaining: float,
    target: tuple[float, float],
    recording: bool,
    fps: float,
    face_found: bool,
) -> None:
    height, width = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (width, 112), (8, 10, 14), -1)
    cv2.addWeighted(overlay, 0.82, frame, 0.18, 0.0, frame)
    color = (40, 60, 255) if recording else (0, 210, 255)
    cv2.putText(frame, headline, (24, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.82, color, 2, cv2.LINE_AA)
    cv2.putText(frame, instruction, (24, 74), cv2.FONT_HERSHEY_SIMPLEX, 0.76, (245, 245, 245), 2, cv2.LINE_AA)
    cv2.putText(
        frame,
        f"{remaining:4.1f}s  |  FPS {fps:4.1f}  |  {'FACE OK' if face_found else 'NO FACE'}",
        (24, 101),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (190, 200, 210),
        1,
        cv2.LINE_AA,
    )
    tx, ty = int(target[0] * width), int(target[1] * height)
    cv2.circle(frame, (tx, ty), 18, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.circle(frame, (tx, ty), 10, (30, 30, 255), -1, cv2.LINE_AA)


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
    references = {
        "eyes_left": "center_left",
        "eyes_right": "center_right",
        "eyes_up": "center_up",
        "eyes_down": "center_down",
    }
    for eye in EYE_NAMES:
        means = {
            phase: {
                axis: mean_axis(phases, phase, eye, axis)
                for axis in ("x", "y")
            }
            for phase in phases
        }

        def amplitude(pose: str, axis: str) -> float | None:
            pose_value = means.get(pose, {}).get(axis)
            reference_value = means.get(references[pose], {}).get(axis)
            if pose_value is None or reference_value is None:
                return None
            return abs(pose_value - reference_value)

        def pose_separation(pose: str, axis: str) -> float | None:
            return separation(
                phases.get(pose, {}).get("eyes", {}).get(eye, {}).get(axis),
                phases.get(references[pose], {}).get("eyes", {}).get(eye, {}).get(axis),
            )

        left_amplitude = amplitude("eyes_left", "x")
        right_amplitude = amplitude("eyes_right", "x")
        up_amplitude = amplitude("eyes_up", "y")
        down_amplitude = amplitude("eyes_down", "y")
        left_separation = pose_separation("eyes_left", "x")
        right_separation = pose_separation("eyes_right", "x")
        up_separation = pose_separation("eyes_up", "y")
        down_separation = pose_separation("eyes_down", "y")

        horizontal_span = (
            None
            if left_amplitude is None or right_amplitude is None
            else left_amplitude + right_amplitude
        )
        vertical_span = (
            None
            if up_amplitude is None or down_amplitude is None
            else up_amplitude + down_amplitude
        )
        horizontal_separation = (
            None
            if left_separation is None or right_separation is None
            else min(left_separation, right_separation)
        )
        vertical_separation = (
            None
            if up_separation is None or down_separation is None
            else min(up_separation, down_separation)
        )

        required_down_gain = None
        gain_is_reliable = (
            up_amplitude is not None
            and down_amplitude is not None
            and down_amplitude > 1e-4
            and up_separation is not None
            and down_separation is not None
            and up_separation >= 1.0
            and down_separation >= 1.0
        )
        if gain_is_reliable:
            required_down_gain = up_amplitude / down_amplitude
            if 0.25 <= required_down_gain <= 4.0:
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
        head_drift = {}
        spans_are_reliable = (
            horizontal_separation is not None
            and vertical_separation is not None
            and horizontal_separation >= 1.0
            and vertical_separation >= 1.0
        )
        if center_x is not None and center_y is not None:
            for phase_name in ("head_left", "head_right", "head_up", "head_down"):
                px = means.get(phase_name, {}).get("x")
                py = means.get(phase_name, {}).get("y")
                if px is None or py is None:
                    continue
                head_drift[phase_name] = {
                    "dx": px - center_x,
                    "dy": py - center_y,
                    "normalized": None
                    if not spans_are_reliable or not horizontal_span or not vertical_span
                    else float(np.hypot((px - center_x) / horizontal_span, (py - center_y) / vertical_span)),
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
            "down_vs_up_after_current_gain": None
            if not gain_is_reliable or not up_amplitude
            else down_amplitude * OUTPUT_DOWN_UP_RATIO / up_amplitude,
            "center_jitter": center_jitter,
            "head_drift": head_drift,
        }

    recommended_gain = statistics.median(gain_candidates) if gain_candidates else None
    return {
        "eyes": eyes,
        "output_gain": {
            "horizontal": OUTPUT_GAIN.horizontal,
            "vertical_up": OUTPUT_GAIN.vertical_up,
            "vertical_down": OUTPUT_GAIN.vertical_down,
        },
        "measured_recommended_down_gain": recommended_gain,
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
            "eyes": {
                eye: {axis: summarize(values) for axis, values in axes.items()}
                for eye, axes in raw["eyes"].items()
            },
        }

    fps = None if not frame_times else 1.0 / statistics.mean(frame_times)
    p95_ms = None if not frame_times else float(np.percentile(frame_times, 95) * 1000.0)
    report = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "config": config,
        "overall": {
            "frames": total_frames,
            "tracked_frames": total_tracked,
            "tracking_rate": total_tracked / total_frames if total_frames else 0.0,
            "read_failures": total_failures,
            "average_fps": fps,
            "p95_frame_ms": p95_ms,
        },
        "phases": phases,
    }
    report["analysis"] = build_analysis(phases)
    return report


def fmt(value: float | None, digits: int = 3) -> str:
    return "--" if value is None else f"{value:.{digits}f}"


def format_stats(stats: dict | None) -> str:
    if stats is None:
        return "--"
    return f"{stats['mean']:.3f}+-{stats['std']:.3f}"


def render_text_report(report: dict) -> str:
    overall = report["overall"]
    lines = [
        "TRACK EYE BASELINE",
        "=" * 72,
        f"created: {report['created_at']}",
        f"camera: {report['config']['actual_width']}x{report['config']['actual_height']} "
        f"@ {report['config']['actual_camera_fps']:.1f} fps, {report['config']['fourcc']}",
        f"runtime: avg {fmt(overall['average_fps'], 1)} fps, p95 {fmt(overall['p95_frame_ms'], 1)} ms/frame",
        f"tracking: {overall['tracked_frames']}/{overall['frames']} "
        f"({overall['tracking_rate'] * 100:.1f}%), camera read failures={overall['read_failures']}",
        "",
        "PHASES (canonical x: image-right positive, y: down positive)",
    ]
    for phase_name, phase in report["phases"].items():
        lines.append(
            f"  {phase_name:<12} tracking={phase['tracking_rate'] * 100:5.1f}% "
            f"frames={phase['frames']}"
        )
    analysis = report["analysis"]
    lines.extend(["", "SIGNAL ANALYSIS"])
    for eye, values in analysis["eyes"].items():
        lines.extend(
            [
                f"  {eye}",
                f"    span x/y: {fmt(values['horizontal_span'])} / {fmt(values['vertical_span'])}",
                f"    separation x/y: {fmt(values['horizontal_separation'], 2)} / "
                f"{fmt(values['vertical_separation'], 2)}",
                f"    separation L/R/U/D: {fmt(values['left_separation'], 2)} / "
                f"{fmt(values['right_separation'], 2)} / {fmt(values['up_separation'], 2)} / "
                f"{fmt(values['down_separation'], 2)}",
                f"    up/down amplitude: {fmt(values['up_amplitude'])} / {fmt(values['down_amplitude'])}",
                f"    down/up after current output ratio {OUTPUT_DOWN_UP_RATIO:.2f}: "
                f"{fmt(values['down_vs_up_after_current_gain'], 2)}",
            ]
        )
        jitter = values["center_jitter"]
        if jitter:
            lines.append(
                f"    center jitter/span x/y: {jitter['x_over_span']:.2%} / {jitter['y_over_span']:.2%}"
            )
        for phase_name, drift in values["head_drift"].items():
            lines.append(
                f"    {phase_name} drift: dx={drift['dx']:+.3f} dy={drift['dy']:+.3f} "
                f"normalized={fmt(drift['normalized'], 2)}"
            )

    lines.extend(
        [
            "",
            "OUTPUT-GAIN DECISION",
            f"  horizontal gain: {OUTPUT_GAIN.horizontal:.2f}",
            f"  vertical up gain: {OUTPUT_GAIN.vertical_up:.2f}",
            f"  vertical down gain: {OUTPUT_GAIN.vertical_down:.2f}",
            f"  measured median required down gain: {fmt(analysis['measured_recommended_down_gain'], 2)}",
            "  Gain is reported only when both UP and DOWN separate from their adjacent center (D >= 1).",
            "  Separation: <1 poor, 1-3 weak/moderate, >3 clear.",
            "  Head drift normalized near 0 is better; 1.0 equals a full gaze span.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        phases = selected_phases(args.phases)
    except ValueError as exc:
        print(f"[BASELINE] {exc}", file=sys.stderr)
        return 2

    camera = Camera(CameraConfig(args.device, args.width, args.height, 30.0, args.fourcc))
    tracker: EyeTracker | None = None
    server = None
    frame_hub = FrameHub() if args.web_ui_host else None
    raw_phases = {phase.name: empty_phase() for phase in phases}
    frame_times: list[float] = []
    last_frame_at = time.perf_counter()
    fps = 0.0
    start_requested = threading.Event()
    face_ready_since: float | None = None

    def status() -> dict:
        return {
            "version": "0.1.0",
            "healthy": True,
            "frame_sequence": 0 if frame_hub is None else frame_hub.latest_sequence,
            "camera": None if camera.info is None else camera.info.__dict__,
            "start_requested": start_requested.is_set(),
            "face_ready": face_ready_since is not None and time.perf_counter() - face_ready_since >= 1.0,
        }

    try:
        camera.open()
        tracker = EyeTracker()
        if frame_hub is not None:
            server = WebUIServer(
                frame_hub,
                args.web_ui_host,
                args.web_ui_port,
                status,
                index_html=render_baseline_html(0),
                start_callback=start_requested.set,
            )
            server.start()
            print(f"[BASELINE] open http://{args.web_ui_host}:{args.web_ui_port}", flush=True)

        def run_window(phase: Phase, seconds: float, recording: bool, headline: str) -> None:
            nonlocal fps, last_frame_at, face_ready_since
            started = time.perf_counter()
            while True:
                loop_started = time.perf_counter()
                elapsed = loop_started - started
                if elapsed >= seconds:
                    return
                ok, frame = camera.read()
                bucket = raw_phases[phase.name]
                if recording:
                    bucket["frames"] += 1
                if not ok or frame is None:
                    if recording:
                        bucket["read_failures"] += 1
                    continue
                if not args.no_mirror:
                    frame = cv2.flip(frame, 1)
                result = tracker.process(frame)
                if result.face_detected:
                    face_ready_since = face_ready_since or time.perf_counter()
                else:
                    face_ready_since = None
                if recording:
                    bucket["tracked_frames"] += int(result.face_detected)
                    if result.eyes is not None:
                        for eye in result.eyes:
                            values = bucket["eyes"][eye.name]
                            values["x"].append(eye.x)
                            values["y"].append(eye.y)
                            values["raw_h"].append(eye.raw_h)
                            values["raw_v"].append(eye.raw_v)
                if result.eyes is not None:
                    for eye in result.eyes:
                        draw_face_marker(frame, eye)
                now = time.perf_counter()
                instant_fps = 1.0 / max(now - last_frame_at, 1e-6)
                fps = instant_fps if fps == 0.0 else 0.9 * fps + 0.1 * instant_fps
                last_frame_at = now
                draw_prompt(frame, headline, phase.instruction, seconds - elapsed, phase.target, recording, fps, result.face_detected)
                if frame_hub is not None:
                    frame_hub.update(frame)
                if recording:
                    frame_times.append(time.perf_counter() - loop_started)

        first_phase = phases[0]
        if args.start_delay > 0:
            run_window(first_phase, args.start_delay, False, "GET READY")
        elif frame_hub is None:
            raise ValueError("--start-delay is required when web UI is disabled")
        else:
            while not start_requested.is_set() or face_ready_since is None or time.perf_counter() - face_ready_since < 1.0:
                run_window(first_phase, 0.1, False, "READY - PRESS START")
        for index, phase in enumerate(phases, start=1):
            print(f"[BASELINE] {index}/{len(phases)} prepare {phase.name}: {phase.instruction}", flush=True)
            if args.countdown > 0:
                run_window(phase, args.countdown, False, "PREPARE")
            print(f"[BASELINE] {index}/{len(phases)} recording {phase.name}", flush=True)
            run_window(phase, args.duration, True, "RECORDING")

        info = camera.info
        config = {
            "device": args.device,
            "requested_width": args.width,
            "requested_height": args.height,
            "actual_width": info.width,
            "actual_height": info.height,
            "actual_camera_fps": info.fps,
            "fourcc": info.fourcc,
            "mirror": not args.no_mirror,
            "ema_alpha": EMA_ALPHA,
            "duration_seconds": args.duration,
            "countdown_seconds": args.countdown,
            "min_tracking_rate": args.min_tracking_rate,
            "phases": [phase.name for phase in phases],
        }
        report = build_report(raw_phases, frame_times, config)
        text = render_text_report(report)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        json_path = args.output_dir / f"tracking-baseline-{stamp}.json"
        text_path = args.output_dir / f"tracking-baseline-{stamp}.txt"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        text_path.write_text(text, encoding="utf-8")
        print("\n" + text, flush=True)
        print(f"[BASELINE] JSON: {json_path}", flush=True)
        print(f"[BASELINE] TEXT: {text_path}", flush=True)
        invalid_phases = [
            name for name, phase in report["phases"].items()
            if phase["tracking_rate"] < args.min_tracking_rate
        ]
        if invalid_phases:
            print(
                f"[BASELINE] INVALID: phases below {args.min_tracking_rate:.1%}: {', '.join(invalid_phases)}",
                file=sys.stderr,
                flush=True,
            )
            return 3
        return 0
    except KeyboardInterrupt:
        print("\n[BASELINE] interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"[BASELINE] ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if server is not None:
            server.close()
        if tracker is not None:
            tracker.close()
        camera.close()


if __name__ == "__main__":
    raise SystemExit(main())
