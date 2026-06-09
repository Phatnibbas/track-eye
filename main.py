"""Entry point for the webcam gaze-to-control demo."""

from __future__ import annotations

import argparse
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Any


def _configure_low_memory_runtime() -> None:
    """Set conservative thread defaults to reduce startup memory pressure.

    These defaults help on Windows machines with small paging files where
    OpenBLAS/OpenMP thread pools can fail during module import.
    User-provided environment variables still take precedence.
    """

    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")


_configure_low_memory_runtime()

import cv2
import yaml

warnings.filterwarnings(
    "ignore",
    message=r"SymbolDatabase\.GetPrototype\(\) is deprecated\..*",
)

from benchmark_utils import (
    PROTOCOL_KEY_LABELS,
    PROTOCOL_LABEL_TITLES,
    InputVideoRecorder,
    LiveProtocolCollector,
    ProtocolTracker,
    SessionBenchmarkLogger,
    default_protocol_labels_path,
    default_summary_path,
    describe_protocol_keys,
)
from calibration import AxisCalibrationModel, CalibrationManager
from calibration_coupled import CoupledCalibrationModel
from draw_utils import draw_overlay
from gaze_estimator import EstimateResult, GazeEstimator
from session_manager import SessionManager
from servo_mapper import SingleEyeServoConfig, SingleEyeServoMapper
from servo_serial import SingleEyeCommand, SerialEyeWriter
from servo_ws import ServoWebSocketServer
from web_ui_server import FrameHub, WebUIServer


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    if not isinstance(config, dict):
        raise ValueError("Config file must contain a YAML mapping")
    if "calibration" not in config or not isinstance(config["calibration"], dict):
        raise ValueError("Config file must contain a 'calibration' mapping")
    return config


def open_camera(
    config: dict[str, Any], camera_override: int | None = None
) -> tuple[cv2.VideoCapture, str]:
    requested_index = int(
        config.get("camera_index", 0) if camera_override is None else camera_override
    )
    fallback_indices = [
        int(index) for index in config.get("camera_fallback_indices", [0, 1, 2, 3])
    ]
    candidate_indices = []
    for index in [requested_index, *fallback_indices]:
        if index not in candidate_indices:
            candidate_indices.append(index)

    backend_map = {
        "default": None,
        "dshow": getattr(cv2, "CAP_DSHOW", None),
        "msmf": getattr(cv2, "CAP_MSMF", None),
    }
    backend_names = list(config.get("camera_backends", ["default"]))
    unknown_backends = [name for name in backend_names if name not in backend_map]
    if unknown_backends:
        raise ValueError(f"Unknown camera backend(s): {', '.join(unknown_backends)}")

    attempts: list[str] = []

    for backend_name in backend_names:
        backend = backend_map.get(backend_name)
        for index in candidate_indices:
            attempts.append(f"index={index}, backend={backend_name}")
            capture = (
                cv2.VideoCapture(index)
                if backend is None
                else cv2.VideoCapture(index, backend)
            )
            if not capture.isOpened():
                capture.release()
                continue

            capture.set(cv2.CAP_PROP_FRAME_WIDTH, int(config.get("frame_width", 1280)))
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, int(config.get("frame_height", 720)))
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            ok, _ = capture.read()
            if ok:
                return capture, f"camera_index={index}, backend={backend_name}"

            capture.release()

    attempted = "; ".join(attempts)
    raise RuntimeError(f"Could not open webcam. Tried: {attempted}")


def open_replay_video(path: Path) -> tuple[cv2.VideoCapture, str]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Could not open replay video: {path}")

    ok, _ = capture.read()
    if not ok:
        capture.release()
        raise RuntimeError(f"Replay video has no readable frames: {path}")

    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
    return capture, f"replay_video={path.name}"


def create_auto_benchmark_paths(config: dict[str, Any]) -> dict[str, Path]:
    session_id = time.strftime("%Y%m%d_%H%M%S")
    root_dir = PROJECT_ROOT / str(
        config.get("benchmark_autosave_dir", "benchmark_data")
    )
    root_dir.mkdir(parents=True, exist_ok=True)
    base_path = root_dir / f"session_{session_id}"
    return {
        "log": base_path.with_suffix(".jsonl"),
        "summary": base_path.with_suffix(".summary.md"),
        "video": base_path.with_suffix(".mp4"),
        "labels": base_path.with_suffix(".labels.json"),
    }


def benchmark_label_for_logging(protocol_label: str | None) -> str:
    """Log every live frame, even when no manual protocol label is active."""
    return protocol_label if protocol_label is not None else "none"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Realtime webcam gaze control demo")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--camera-index", type=int, default=None)
    parser.add_argument("--calibration-path", type=Path, default=None)
    parser.add_argument(
        "--replay-video",
        type=Path,
        default=None,
        help="Run the pipeline on a recorded input video instead of a live camera",
    )
    parser.add_argument(
        "--record-video",
        type=Path,
        default=None,
        help="Record raw input frames for deterministic replay benchmarking",
    )
    parser.add_argument(
        "--benchmark-log",
        type=Path,
        default=None,
        help="Write per-frame benchmark data as JSONL",
    )
    parser.add_argument(
        "--benchmark-summary",
        type=Path,
        default=None,
        help="Write benchmark summary as .md or .json",
    )
    parser.add_argument(
        "--protocol-labels",
        type=Path,
        default=None,
        help="Load or save the benchmark protocol timeline sidecar",
    )
    parser.add_argument(
        "--max-frames", type=int, default=None, help="Optional limit for smoke testing"
    )
    parser.add_argument(
        "--condition-id",
        type=str,
        default="unspecified",
        help="Problem A condition tag stored in benchmark JSONL",
    )
    parser.add_argument(
        "--condition-glasses",
        type=str,
        default="unspecified",
        help="Glasses condition tag stored in benchmark JSONL",
    )
    parser.add_argument(
        "--condition-lighting",
        type=str,
        default="unspecified",
        help="Lighting condition tag stored in benchmark JSONL",
    )
    parser.add_argument(
        "--condition-distance-notes",
        type=str,
        default="unspecified",
        help="Distance/pose notes stored in benchmark JSONL",
    )
    parser.add_argument(
        "--condition-target-visibility",
        type=str,
        default="unspecified",
        help="Target visibility condition tag stored in benchmark JSONL",
    )
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="Run without cv2.imshow for smoke testing",
    )
    parser.add_argument(
        "--servo-port",
        type=str,
        default=None,
        help="Optional ESP32 serial port, e.g. COM5. If omitted, only overlay/log is used.",
    )
    parser.add_argument(
        "--servo-ws-host",
        type=str,
        default=None,
        help="Start laptop WebSocket host for ESP32 client, e.g. 0.0.0.0",
    )
    parser.add_argument("--servo-ws-port", type=int, default=8765)
    parser.add_argument("--web-ui-host", type=str, default=None)
    parser.add_argument("--web-ui-port", type=int, default=8080)
    return parser.parse_args()


def create_single_eye_servo_mapper(config: dict[str, Any]) -> SingleEyeServoMapper:
    return SingleEyeServoMapper(SingleEyeServoConfig.from_dict(config.get("servo", {})))


def validate_loaded_calibration(
    calibration_manager: CalibrationManager,
    min_range_x: float,
    min_range_y: float,
) -> tuple[bool, str | None]:
    model = calibration_manager.model
    if model is None:
        return False, "No calibration model loaded"

    stats = model.training_prediction_stats()
    axis_model = model if isinstance(model, AxisCalibrationModel) else None

    if calibration_manager.mode == "axis5" and axis_model is None:
        calibration_manager.model = None
        return False, "Current mode requires axis5 calibration model"

    if axis_model is not None:
        if calibration_manager.mode == "coupled_only":
            calibration_manager.model = None
            return False, "Current mode requires coupled calibration model"
        x_ok = axis_model.x_is_usable(min_range_x)
        y_ok = axis_model.y_is_usable(min_range_y)
        if not (x_ok or y_ok):
            calibration_manager.model = None
            return False, (
                "Calibration spread too small; recalibrate "
                f"(spread x={stats['min_feature_abs_x']:.3f}, y={stats['min_feature_abs_y']:.3f})"
            )
        if not (x_ok and y_ok):
            return (
                True,
                f"Partial calibration loaded (x={'ok' if x_ok else 'raw'}, y={'ok' if y_ok else 'raw'})",
            )
        return True, None

    if isinstance(model, CoupledCalibrationModel):
        if calibration_manager.mode == "axis5":
            calibration_manager.model = None
            return False, "Current mode requires axis5 calibration model"
        quality = calibration_manager.evaluate_model_quality()
        if quality is None or not quality.get("pass_hard_gates", False):
            calibration_manager.model = None
            return False, "Loaded coupled calibration failed quality gates; recalibrate"
        if not model.is_usable(min_abs_x=min_range_x, min_abs_y=min_range_y):
            calibration_manager.model = None
            return False, (
                "Calibration range too small; recalibrate "
                f"(pred x={stats['max_abs_x']:.3f}, y={stats['max_abs_y']:.3f})"
            )
        return True, "Coupled calibration loaded"

    if not model.is_usable(min_abs_x=min_range_x, min_abs_y=min_range_y):
        calibration_manager.model = None
        return False, (
            "Calibration range too small; recalibrate "
            f"(pred x={stats['max_abs_x']:.3f}, y={stats['max_abs_y']:.3f})"
        )
    return True, None


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    debug_enabled = bool(config.get("debug", True))

    if args.camera_index is not None and args.replay_video is not None:
        print("[WARN] --camera-index is ignored when --replay-video is set")

    config_dir = args.config.resolve().parent
    configured_calibration_path = Path(config["calibration"]["model_path"])
    default_calibration_path = (
        configured_calibration_path
        if configured_calibration_path.is_absolute()
        else (config_dir / configured_calibration_path)
    )
    calibration_path = args.calibration_path or default_calibration_path
    calibration_manager = CalibrationManager(
        config=config["calibration"], default_model_path=calibration_path
    )
    min_range_x = float(config.get("calibration_min_training_range_x", 0.05))
    min_range_y = float(config.get("calibration_min_training_range_y", 0.06))

    if bool(config.get("autoload_calibration", True)) and calibration_path.exists():
        try:
            calibration_manager.load_model(calibration_path)
            if calibration_manager.model is not None:
                ok, message = validate_loaded_calibration(
                    calibration_manager, min_range_x, min_range_y
                )
                if not ok and message is not None:
                    print(f"[WARN] {message}; using raw mode")
                elif message is not None:
                    calibration_manager.status_message = message
                    print(f"[WARN] {message}")
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] Failed to autoload calibration: {exc}")

    estimator = GazeEstimator(config)
    session_manager = SessionManager(
        acquire_frames=int(config.get("session_acquire_frames", 10)),
        baseline_hold_s=float(config.get("session_baseline_hold_s", 1.5)),
        lost_face_timeout_s=float(config.get("session_lost_face_timeout_s", 1.0)),
        min_confidence=float(config.get("session_min_confidence", 0.35)),
        drift_threshold=float(config.get("session_drift_threshold", 0.25)),
    )
    servo_mapper = create_single_eye_servo_mapper(config)
    servo_writer = SerialEyeWriter(args.servo_port) if args.servo_port else None
    effective_ws_host = args.servo_ws_host or ("0.0.0.0" if args.web_ui_host else None)
    servo_ws_server = (
        ServoWebSocketServer(effective_ws_host, args.servo_ws_port)
        if effective_ws_host
        else None
    )
    if servo_ws_server is not None:
        servo_ws_server.start()
        print(f"[INFO] Servo WebSocket host -> ws://{effective_ws_host}:{args.servo_ws_port}")
    frame_hub = FrameHub() if args.web_ui_host else None
    web_ui_server = (
        WebUIServer(frame_hub, args.web_ui_host, args.web_ui_port, args.servo_ws_port)
        if frame_hub is not None and args.web_ui_host
        else None
    )
    if web_ui_server is not None:
        web_ui_server.start()
        print(f"[INFO] Web UI -> http://{args.web_ui_host}:{args.web_ui_port}")
    display_window = (not args.no_window) and web_ui_server is None
    servo_command = None
    capture = None
    recorder = None
    window_name = str(config.get("window_name", "Gaze Control"))
    paused = False
    frame_count = 0

    benchmark_log_path = args.benchmark_log
    benchmark_summary_path = args.benchmark_summary
    auto_benchmark_enabled = bool(config.get("benchmark_autosave", True))
    auto_benchmark_paths: dict[str, Path] | None = None
    if (
        auto_benchmark_enabled
        and args.replay_video is None
        and not args.no_window
        and benchmark_log_path is None
        and args.record_video is None
    ):
        auto_benchmark_paths = create_auto_benchmark_paths(config)
        benchmark_log_path = auto_benchmark_paths["log"]
        benchmark_summary_path = auto_benchmark_paths["summary"]
        args.record_video = auto_benchmark_paths["video"]

    if benchmark_log_path is not None and benchmark_summary_path is None:
        benchmark_summary_path = default_summary_path(benchmark_log_path)

    protocol_labels_path = args.protocol_labels
    if protocol_labels_path is None:
        if args.replay_video is not None:
            protocol_labels_path = default_protocol_labels_path(args.replay_video)
        elif args.record_video is not None:
            protocol_labels_path = default_protocol_labels_path(args.record_video)
        elif benchmark_log_path is not None:
            protocol_labels_path = default_protocol_labels_path(benchmark_log_path)
    if auto_benchmark_paths is not None:
        protocol_labels_path = auto_benchmark_paths["labels"]

    if args.replay_video is not None and protocol_labels_path is not None:
        if protocol_labels_path.exists():
            protocol_tracker = ProtocolTracker.load(protocol_labels_path)
        else:
            print(
                f"[WARN] Protocol labels not found: {protocol_labels_path}; replay will be unlabeled"
            )
            protocol_tracker = ProtocolTracker(replay_spans=[])
    else:
        protocol_tracker = ProtocolTracker()

    benchmark_logger = SessionBenchmarkLogger(
        log_path=benchmark_log_path,
        summary_path=benchmark_summary_path,
        confidence_dropout_threshold=float(
            config.get("min_confidence_for_update", 0.35)
        ),
        condition_metadata={
            "condition_id": args.condition_id,
            "glasses": args.condition_glasses,
            "lighting": args.condition_lighting,
            "distance_notes": args.condition_distance_notes,
            "target_visibility": args.condition_target_visibility,
        },
    )
    protocol_settle_seconds = float(
        config.get("benchmark_protocol_settle_seconds", 0.0)
    )
    protocol_collect_seconds = float(
        config.get("benchmark_protocol_collect_seconds", 7.0)
    )
    benchmark_mode = (
        benchmark_logger.enabled
        or args.record_video is not None
        or args.replay_video is not None
    )
    live_protocol_collector = (
        None
        if args.replay_video is not None
        else LiveProtocolCollector(
            protocol_tracker,
            protocol_settle_seconds,
            protocol_collect_seconds,
        )
    )

    try:
        if args.replay_video is not None:
            capture, camera_label = open_replay_video(args.replay_video)
        else:
            capture, camera_label = open_camera(
                config, camera_override=args.camera_index
            )
        print(f"[INFO] Opened {camera_label}")
        print(
            "[INFO] Keys: q quit | c calibrate | r reset | z recenter | s save | l load | h headpose | d debug | p pause"
        )
        if benchmark_mode and display_window:
            print(f"[INFO] Protocol keys: {describe_protocol_keys()}")
            if live_protocol_collector is not None and protocol_settle_seconds > 0.0:
                print(f"[INFO] Protocol settle delay -> {protocol_settle_seconds:.1f}s")
            if live_protocol_collector is not None and protocol_collect_seconds > 0.0:
                print(
                    "[INFO] Protocol auto-collection -> "
                    f"{protocol_collect_seconds:.1f}s per label"
                )
        if benchmark_logger.enabled:
            if benchmark_log_path is not None:
                print(f"[INFO] Benchmark log -> {benchmark_log_path}")
            if benchmark_summary_path is not None:
                print(f"[INFO] Benchmark summary -> {benchmark_summary_path}")
        if auto_benchmark_paths is not None:
            print("[INFO] Benchmark autosave -> on")
        if (
            benchmark_mode
            and protocol_labels_path is not None
            and not protocol_tracker.is_replay
        ):
            print(f"[INFO] Protocol labels -> {protocol_labels_path}")
        if (
            protocol_tracker.is_replay
            and protocol_labels_path is not None
            and protocol_labels_path.exists()
        ):
            print(f"[INFO] Loaded protocol labels <- {protocol_labels_path}")
        if args.record_video is not None:
            fps_hint = float(capture.get(cv2.CAP_PROP_FPS))
            recorder = InputVideoRecorder(args.record_video, fps_hint=fps_hint or 30.0)
            print(f"[INFO] Recording raw input video -> {args.record_video}")
        if (args.no_window or web_ui_server is not None) and args.max_frames is None:
            print("[WARN] --no-window is active without --max-frames; stop with Ctrl+C")

        if display_window:
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        fps = 0.0
        last_timestamp = time.perf_counter()
        session_started_at = last_timestamp
        replay_fps = 0.0
        if args.replay_video is not None:
            replay_fps = float(capture.get(cv2.CAP_PROP_FPS))
            if replay_fps <= 1e-6:
                replay_fps = 30.0
        last_estimate = EstimateResult.empty("Waiting for frame")
        last_frame = None
        session_snapshot = session_manager.snapshot()

        while True:
            if not paused:
                current_frame_index = frame_count
                ok, frame = capture.read()
                if not ok:
                    if args.replay_video is not None:
                        break
                    raise RuntimeError("Webcam opened but frame capture failed")

                raw_frame = frame.copy()
                if recorder is not None:
                    recorder.write(raw_frame)

                if bool(config.get("mirror", True)):
                    frame = cv2.flip(frame, 1)

                last_estimate = estimator.process(frame, calibration_manager.model)
                calibration_manager.update(
                    last_estimate.feature_vector, last_estimate.confidence
                )
                last_frame = frame

                now = time.perf_counter()
                instantaneous_fps = 1.0 / max(1e-6, now - last_timestamp)
                fps = (
                    instantaneous_fps
                    if fps == 0.0
                    else ((0.9 * fps) + (0.1 * instantaneous_fps))
                )
                last_timestamp = now

                elapsed_s = (
                    (current_frame_index / replay_fps)
                    if args.replay_video is not None
                    else (now - session_started_at)
                )
                session_snapshot = session_manager.update(
                    face_detected=bool(last_estimate.face_detected),
                    confidence=float(last_estimate.confidence),
                    timestamp_s=float(elapsed_s),
                    x_eye=float(last_estimate.x_eye),
                    y_eye=float(last_estimate.y_eye),
                )
                if session_snapshot.reset_required:
                    estimator.reset_filters()
                    estimator.reset_raw_center()
                    session_manager.acknowledge_reset()
                servo_command = servo_mapper.update(
                    x_ctrl=float(last_estimate.x_ctrl),
                    y_ctrl=float(last_estimate.y_ctrl),
                    confidence=float(last_estimate.confidence),
                    session_ready=bool(session_snapshot.ready),
                    output_source=str(last_estimate.output_source),
                    calibration_active=bool(calibration_manager.active),
                )
                if servo_writer is not None:
                    servo_writer.write_command(
                        SingleEyeCommand(
                            pan_deg=servo_command.pan_deg,
                            tilt_deg=servo_command.tilt_deg,
                            gate_state=servo_command.gate_state,
                        )
                    )
                if servo_ws_server is not None:
                    servo_ws_server.broadcast_command(servo_command)
                protocol_label = None
                if live_protocol_collector is not None:
                    activated_label = live_protocol_collector.update(
                        current_frame_index, elapsed_s
                    )
                    if activated_label is not None:
                        print(
                            "[INFO] Collecting -> "
                            f"{PROTOCOL_LABEL_TITLES.get(activated_label, activated_label)}"
                        )
                    protocol_label = live_protocol_collector.current_collection_label()
                elif args.replay_video is not None:
                    replay_label = protocol_tracker.label_for_frame(current_frame_index)
                    protocol_label = replay_label if replay_label != "none" else None

                if benchmark_logger.enabled:
                    benchmark_logger.log_frame(
                        frame_index=current_frame_index,
                        elapsed_s=elapsed_s,
                        fps=fps,
                        protocol_label=benchmark_label_for_logging(protocol_label),
                        estimate=last_estimate,
                        session_state=session_snapshot.state,
                            session_ready=session_snapshot.ready,
                            session_reason=session_snapshot.reason,
                            vertical_feature_mode=estimator.vertical_feature_mode,
                            servo_command=servo_command,
                        )
                frame_count += 1

                if live_protocol_collector is not None:
                    completed_label = live_protocol_collector.finish_if_due(
                        frame_count, elapsed_s
                    )
                    if completed_label is not None:
                        print(
                            "[INFO] Auto-stopped -> "
                            f"{PROTOCOL_LABEL_TITLES.get(completed_label, completed_label)}"
                        )
                        if (
                            protocol_labels_path is not None
                            and not protocol_tracker.is_replay
                        ):
                            try:
                                saved_labels = protocol_tracker.save(
                                    protocol_labels_path, frame_count
                                )
                                print(
                                    f"[INFO] Auto-saved protocol labels -> {saved_labels}"
                                )
                            except Exception as exc:  # noqa: BLE001
                                print(f"[WARN] Auto-save protocol labels failed: {exc}")

            if last_frame is None:
                continue

            display_frame = draw_overlay(
                last_frame.copy(),
                estimate=last_estimate,
                fps=fps,
                debug_enabled=debug_enabled,
                calibration_manager=calibration_manager,
                paused=paused,
                benchmark_status={
                    "enabled": benchmark_mode
                    or protocol_tracker.current_label != "none"
                    or (
                        live_protocol_collector is not None
                        and live_protocol_collector.pending_label is not None
                    ),
                    "logging": benchmark_logger.enabled,
                    "recording": recorder is not None,
                    "replay": args.replay_video is not None,
                    **(
                        {
                            **live_protocol_collector.status_snapshot(
                                max(0.0, time.perf_counter() - session_started_at)
                            ),
                            "settle_remaining_s": live_protocol_collector.time_to_collect(
                                max(0.0, time.perf_counter() - session_started_at)
                            ),
                            "auto_stop_remaining_s": live_protocol_collector.time_to_auto_stop(
                                max(0.0, time.perf_counter() - session_started_at)
                            ),
                            "collect_duration_s": protocol_collect_seconds,
                        }
                        if live_protocol_collector is not None
                        else {
                            "armed": False,
                            "collecting": protocol_tracker.current_label != "none",
                            "protocol_label": protocol_tracker.current_label,
                            "protocol_title": PROTOCOL_LABEL_TITLES.get(
                                protocol_tracker.current_label,
                                protocol_tracker.current_label,
                            ),
                            "settle_remaining_s": 0.0,
                            "auto_stop_remaining_s": 0.0,
                            "collect_duration_s": protocol_collect_seconds,
                        }
                    ),
                },
                session_status={
                    "state": session_snapshot.state,
                    "ready": session_snapshot.ready,
                    "reason": session_snapshot.reason,
                },
                servo_status=servo_command,
            )

            if frame_hub is not None:
                frame_hub.update(display_frame)

            if not display_window:
                if frame_count % 30 == 0:
                    print(
                        f"[SMOKE] frame={frame_count} x={last_estimate.x_ctrl:+.3f} "
                        f"y={last_estimate.y_ctrl:+.3f} conf={last_estimate.confidence:.2f}"
                    )
            else:
                cv2.imshow(window_name, display_frame)

            if args.max_frames is not None and frame_count >= args.max_frames:
                break

            key = -1 if not display_window else (cv2.waitKey(1) & 0xFF)
            if key in (-1, 255):
                continue

            if key in (ord("q"), 27):
                break
            if key == ord("c"):
                if bool(config.get("kiosk_quick_calibration_enabled", True)):
                    calibration_manager.apply_quick_kiosk_preset(config["calibration"])
                calibration_manager.start()
                estimator.reset_filters()
                print("[INFO] Calibration started")
            elif key == ord("r"):
                calibration_manager.reset_model()
                estimator.reset_filters()
                estimator.reset_raw_center()
                print("[INFO] Calibration model reset")
            elif key == ord("z"):
                if calibration_manager.has_model:
                    ok = calibration_manager.recenter(
                        last_estimate.feature_vector, last_estimate.confidence
                    )
                    if ok:
                        estimator.reset_filters()
                    else:
                        # Fallback to raw recenter for non-axis models.
                        ok_raw, raw_message = estimator.recenter_raw(
                            last_estimate.feature_vector,
                            last_estimate.confidence,
                        )
                        if ok_raw:
                            estimator.reset_filters()
                            print(f"[INFO] {raw_message}")
                        else:
                            print(f"[INFO] {calibration_manager.status_message}")
                        continue
                    print(f"[INFO] {calibration_manager.status_message}")
                else:
                    ok, message = estimator.recenter_raw(
                        last_estimate.feature_vector, last_estimate.confidence
                    )
                    if ok:
                        estimator.reset_filters()
                    print(f"[INFO] {message}")
            elif key == ord("s"):
                try:
                    saved_path = calibration_manager.save_model(calibration_path)
                    print(f"[INFO] Saved calibration to {saved_path}")
                except Exception as exc:  # noqa: BLE001
                    print(f"[WARN] Save failed: {exc}")
            elif key == ord("l"):
                try:
                    loaded_path = calibration_manager.load_model(calibration_path)
                    if calibration_manager.model is not None:
                        ok, message = validate_loaded_calibration(
                            calibration_manager, min_range_x, min_range_y
                        )
                        if not ok and message is not None:
                            raise RuntimeError(message)
                        if message is not None:
                            calibration_manager.status_message = message
                            print(f"[WARN] {message}")
                    estimator.reset_filters()
                    print(f"[INFO] Loaded calibration from {loaded_path}")
                except Exception as exc:  # noqa: BLE001
                    print(f"[WARN] Load failed: {exc}")
            elif key == ord("h"):
                enabled = estimator.toggle_head_pose()
                print(f"[INFO] Head pose compensation {'on' if enabled else 'off'}")
            elif key == ord("d"):
                debug_enabled = not debug_enabled
                print(f"[INFO] Debug overlay {'on' if debug_enabled else 'off'}")
            elif key == ord("p"):
                paused = not paused
                print(f"[INFO] {'Paused' if paused else 'Resumed'}")
            elif key in PROTOCOL_KEY_LABELS:
                label = PROTOCOL_KEY_LABELS[key]
                if live_protocol_collector is not None:
                    elapsed_s = max(0.0, time.perf_counter() - session_started_at)
                    message = live_protocol_collector.handle_label_press(
                        label, frame_count, elapsed_s
                    )
                    print(f"[INFO] {message}")

        print(
            f"[INFO] Exit after {frame_count} frames | x={last_estimate.x_ctrl:+.3f} "
            f"y={last_estimate.y_ctrl:+.3f} conf={last_estimate.confidence:.2f}"
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    finally:
        if recorder is not None:
            recorder.close()
        if (
            frame_count > 0
            and protocol_labels_path is not None
            and not protocol_tracker.is_replay
        ):
            saved_labels = protocol_tracker.save(protocol_labels_path, frame_count)
            print(f"[INFO] Saved protocol labels to {saved_labels}")
        if benchmark_logger.enabled:
            summary = benchmark_logger.finalize(protocol_tracker.finalize(frame_count))
            if benchmark_summary_path is not None:
                print(
                    "[INFO] Benchmark summary ready | "
                    f"frames={summary['logged_frames']} "
                    f"duration={summary['timeline_duration_s']:.2f}s"
                )
        estimator.close()
        if servo_writer is not None:
            servo_writer.close()
        if servo_ws_server is not None:
            servo_ws_server.close()
        if web_ui_server is not None:
            web_ui_server.close()
        if capture is not None:
            capture.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())
