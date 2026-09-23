"""Production software-only camera -> tracker -> renderer -> web process."""

from __future__ import annotations

import argparse
import signal
import threading
import time
from pathlib import Path

import cv2

from .baseline import BaselineSession
from .camera import DEFAULT_DEVICE, Camera, CameraConfig, CameraError
from .fallback import (
    Candidate,
    FallbackSelector,
    SourceKind,
    config_to_dict,
    load_config_file,
)
from .output import OutputGain
from .output_tuning import OutputTuner
from .pupil_quality import PupilQualityMonitor
from .rendering import render_frame
from .shadow import BodyPositionWorker, FacePositionShadow, HeadPoseShadow, TrackedVisitor
from .tracker import EyeTracker
from .validation import ValidationSession
from .web import FrameHub, WebUIServer

REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track Eye software-only tracker")
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--fourcc", default="MJPG")
    parser.add_argument("--web-host", default="0.0.0.0")
    parser.add_argument("--web-port", type=int, default=8080)
    parser.add_argument("--min-detect", type=float, default=0.5)
    parser.add_argument("--min-track", type=float, default=0.5)
    parser.add_argument("--ema-alpha", type=float, default=0.45)
    parser.add_argument("--output-left-gain", type=float, default=3.0)
    parser.add_argument("--output-right-gain", type=float, default=3.0)
    parser.add_argument("--output-up-gain", type=float, default=2.5)
    parser.add_argument("--output-down-gain", type=float, default=3.75)
    parser.add_argument("--output-soft-limit", type=float, default=1.5)
    parser.add_argument("--output-config", type=Path, default=Path("output-calibration.json"))
    parser.add_argument("--fallback-config", type=Path, default=Path("fallback-config.json"))
    parser.add_argument("--no-head-shadow", action="store_true")
    parser.add_argument("--no-face-shadow", action="store_true")
    parser.add_argument("--no-body-shadow", action="store_true")
    parser.add_argument("--validation-dir", type=Path, default=Path("validation_data"))
    parser.add_argument("--no-mirror", action="store_true")
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--validation-token", default=None, help="Required bearer token for validation capture endpoints")
    return parser.parse_args(argv)


def _require_validation_token(expected: str | None, body: dict) -> None:
    if expected is None:
        raise ValueError("validation endpoints are disabled; set --validation-token on a trusted network")
    provided = body.get("token") if isinstance(body, dict) else None
    if not isinstance(provided, str) or provided != expected:
        raise ValueError("invalid validation token")


def _validation_string(body: dict, key: str, default: str = "unlabeled") -> str:
    value = body.get(key, default) if isinstance(body, dict) else default
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _candidate_view(candidates: dict) -> dict:
    view = {}
    now_s = time.monotonic()
    for kind, cand in candidates.items():
        view[kind.name] = {
            "valid": cand.valid,
            "target": (cand.x, cand.y),
            "age_s": now_s - cand.monotonic_ns / 1e9,
            "latency_ms": cand.latency_ms,
            "quality": cand.quality,
        }
    return view


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda _signum, _frame: stop.set())
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())

    camera = Camera(CameraConfig(args.device, args.width, args.height, args.fps, args.fourcc))
    tracker: EyeTracker | None = None
    head_shadow: HeadPoseShadow | None = None
    face_shadow: FacePositionShadow | None = None
    body_worker: BodyPositionWorker | None = None
    hub = FrameHub()
    baseline = BaselineSession(Path("benchmark_data"))
    output_tuner = OutputTuner(
        args.output_config,
        OutputGain(
            left=args.output_left_gain,
            right=args.output_right_gain,
            up=args.output_up_gain,
            down=args.output_down_gain,
            soft_limit=args.output_soft_limit,
        ),
    )
    fallback_config, fallback_error, fallback_checksum = load_config_file(args.fallback_config)
    selector = FallbackSelector(fallback_config)
    pupil_monitor = PupilQualityMonitor()
    validation = ValidationSession(args.validation_dir)
    state_lock = threading.Lock()
    shadow_state: dict = {
        "decision": None,
        "candidates": {},
        "pupils": None,
        "stages_ms": {},
        "sample_id": 0,
        "head": {"enabled": False},
        "face": {"enabled": False},
        "body": {"enabled": False},
    }
    state = {
        "started_at": time.time(),
        "last_frame_at": 0.0,
        "capture_alive": False,
        "result": None,
        "output": None,
        "fps": 0.0,
        "frame_sequence": 0,
    }

    def status() -> dict:
        now = time.time()
        with state_lock:
            state_view = dict(state)
            shadow_view = dict(shadow_state)
        age = None if not state_view["last_frame_at"] else max(0.0, now - state_view["last_frame_at"])
        result = state_view["result"]
        output = state_view["output"]
        raw_eyes = result.eyes if result is not None and result.face_detected else None
        output_eyes = output.eyes if output is not None and output.face_detected else None
        decision = shadow_view["decision"]
        pupils = shadow_view["pupils"]
        return {
            "version": "0.1.0",
            "uptime_seconds": now - state_view["started_at"],
            "frame_sequence": state_view["frame_sequence"],
            "last_frame_age_seconds": age,
            "camera": camera.info.__dict__ if camera.info is not None else None,
            "fps": state_view["fps"],
            "face_detected": bool(result and result.face_detected),
            "inference_ms": None if result is None else result.inference_ms,
            "raw_left": None if raw_eyes is None else {"x": raw_eyes[0].x, "y": raw_eyes[0].y},
            "raw_right": None if raw_eyes is None else {"x": raw_eyes[1].x, "y": raw_eyes[1].y},
            "output_left": None if output_eyes is None else {"x": output_eyes[0].x, "y": output_eyes[0].y},
            "output_right": None if output_eyes is None else {"x": output_eyes[1].x, "y": output_eyes[1].y},
            "capture_alive": state_view["capture_alive"],
            "healthy": bool(state_view["capture_alive"] and age is not None and age <= 2.0),
            "baseline": baseline.status(),
            "output_tuning": output_tuner.status(),
            "fallback": {
                "config": config_to_dict(fallback_config),
                "config_checksum": fallback_checksum,
                "config_error": fallback_error,
                "emission_enabled": False,
                "emission_requested": fallback_config.emission_enabled,
                "emission": "disabled-shadow-only",
                "calibrated": fallback_config.calibrated,
                "shadow_source": decision.active_source.name if decision else "NONE",
                "shadow_reason": decision.reason if decision else "no frame yet",
                "shadow_states": [decision.left_state.name, decision.right_state.name] if decision else ["INVALID", "INVALID"],
                "shadow_target_left": (decision.left_x, decision.left_y) if decision else (0.0, 0.0),
                "shadow_target_right": (decision.right_x, decision.right_y) if decision else (0.0, 0.0),
                "source_age_s": decision.source_age_s if decision else 0.0,
                "held_age_s": decision.held_age_s if decision else None,
                "candidates": _candidate_view(shadow_view["candidates"]),
                "pupil_left": None if pupils is None else {
                    "target": (pupils[0].x, pupils[0].y),
                    "valid": pupils[0].valid,
                    "latency_ms": pupils[0].latency_ms,
                    "quality": pupils[0].quality,
                },
                "pupil_right": None if pupils is None else {
                    "target": (pupils[1].x, pupils[1].y),
                    "valid": pupils[1].valid,
                    "latency_ms": pupils[1].latency_ms,
                    "quality": pupils[1].quality,
                },
                "head": shadow_view["head"],
                "face": shadow_view["face"],
                "body": shadow_view["body"],
                "stages_ms": dict(shadow_view["stages_ms"]),
                "sample_id": shadow_view["sample_id"],
            },
            "validation": validation.status(),
        }

    def validation_start(body: dict) -> dict:
        _require_validation_token(args.validation_token, body)
        info = camera.info.__dict__ if camera.info is not None else {}
        exposure = body.get("exposure") if isinstance(body, dict) else None
        return validation.start(
            REPO_ROOT,
            info,
            args.device,
            not args.no_mirror,
            args.output_config,
            fallback_checksum,
            _validation_string(body, "scenario"),
            lighting_condition=_validation_string(body, "lighting_condition"),
            exposure=exposure,
            consent_ref=_validation_string(body, "consent_ref"),
            participant_split=_validation_string(body, "participant_split"),
        )

    def validation_stop(body: dict) -> dict:
        _require_validation_token(args.validation_token, body)
        return validation.stop() or {"active": False}

    def validation_cleanup(body: dict) -> dict:
        _require_validation_token(args.validation_token, body)
        return ValidationSession.cleanup(args.validation_dir)

    server = WebUIServer(
        hub,
        args.web_host,
        args.web_port,
        status,
        start_callback=baseline.request_start,
        action_callbacks={
            "/baseline/start": lambda _body: baseline.request_start() or baseline.status(),
            "/output/gain": output_tuner.update_gain,
            "/output/neutral": lambda _body: output_tuner.request_neutral(),
            "/output/save": lambda _body: output_tuner.save(),
            "/output/reset": lambda _body: output_tuner.reset(),
            "/validation/start": validation_start,
            "/validation/stop": validation_stop,
            "/validation/cleanup": validation_cleanup,
        },
    )
    frames = 0
    last_frame = time.perf_counter()
    fps = 0.0
    try:
        camera.open()
        baseline.configure(camera.info.__dict__, args.device, not args.no_mirror)
        tracker = EyeTracker(args.min_detect, args.min_track, args.ema_alpha)
        head_shadow = HeadPoseShadow(REPO_ROOT, enabled=not args.no_head_shadow)
        face_shadow = FacePositionShadow(enabled=not args.no_face_shadow)
        body_worker = BodyPositionWorker(
            enabled=not args.no_body_shadow,
            cadence_s=fallback_config.body_cadence_s,
            score_min=fallback_config.body_score_min,
            selected=fallback_config.body_enabled,
        )
        visitor = TrackedVisitor()
        server.start()
        with state_lock:
            state["capture_alive"] = True
        print(f"[APP] web=http://{args.web_host}:{args.web_port} device={args.device}", flush=True)
        print(f"[APP] fallback shadow emission={'enabled' if fallback_config.emission_enabled else 'disabled'} checksum={fallback_checksum}", flush=True)
        while not stop.is_set():
            loop_started = time.perf_counter()
            ok, frame = camera.read()
            if not ok or frame is None:
                baseline.record_read_failure()
                continue
            if not args.no_mirror:
                frame = cv2.flip(frame, 1)
            # Raw pre-render validation frame: mirrored, before any overlay.
            pre_render = frame.copy() if validation.active else None
            result = tracker.process(frame)
            output = output_tuner.process(result)
            tracker_ms = result.inference_ms
            mono_now = time.monotonic()
            pupils = pupil_monitor.update(result.eyes, mono_now, tracker_ms, output.eyes)
            candidates: dict[SourceKind, Candidate] = {}
            stages_ms: dict[str, float] = {"tracker": tracker_ms}
            if head_shadow is not None and head_shadow._landmarker is not None:
                head_cand = head_shadow.process(frame, int(mono_now * 1000), fallback_config)
                if head_cand is not None:
                    candidates[SourceKind.HEAD_POSE] = head_cand
                    stages_ms["head"] = head_cand.latency_ms
            if face_shadow is not None and face_shadow._detector is not None:
                face_cand = face_shadow.process(frame, fallback_config, fallback_config.face_score_min)
                if face_cand is not None:
                    candidates[SourceKind.FACE_POSITION] = face_cand
                    stages_ms["face"] = face_cand.latency_ms
            if body_worker is not None:
                body_worker.submit(frame)
                body_cand = body_worker.latest()
                if body_cand is not None:
                    candidates[SourceKind.BODY_POSITION] = body_cand
                    stages_ms["body"] = body_cand.latency_ms
            compat = None
            if output.eyes is not None:
                compat = ((output.eyes[0].x, output.eyes[0].y), (output.eyes[1].x, output.eyes[1].y))
            selector_now = time.monotonic()
            visitor_options = {
                "face": (candidates[SourceKind.FACE_POSITION].x, candidates[SourceKind.FACE_POSITION].y)
                if SourceKind.FACE_POSITION in candidates and candidates[SourceKind.FACE_POSITION].valid else None,
                "head": (candidates[SourceKind.HEAD_POSE].x, candidates[SourceKind.HEAD_POSE].y)
                if SourceKind.HEAD_POSE in candidates and candidates[SourceKind.HEAD_POSE].valid else None,
                "body": (candidates[SourceKind.BODY_POSITION].x, candidates[SourceKind.BODY_POSITION].y)
                if SourceKind.BODY_POSITION in candidates and candidates[SourceKind.BODY_POSITION].valid else None,
            }
            visitor_source = visitor.nearest(visitor_options, selector_now)
            decision = selector.update(selector_now, pupils, candidates, compat)
            if validation.active and pre_render is not None:
                validation.record(pre_render, {
                    "timestamp_s": mono_now,
                    "frame_sequence": frames,
                    "fps": fps,
                    "face_detected": result.face_detected,
                    "tracker_ms": tracker_ms,
                    "pupil_left": None if pupils is None else {"x": pupils[0].x, "y": pupils[0].y, "quality": pupils[0].quality},
                    "pupil_right": None if pupils is None else {"x": pupils[1].x, "y": pupils[1].y, "quality": pupils[1].quality},
                    "candidates": _candidate_view(candidates),
                    "selected_source": decision.active_source.name,
                    "transition_reason": decision.reason,
                    "shadow_states": (decision.left_state.name, decision.right_state.name),
                    "selected_target_left": [decision.left_x, decision.left_y],
                    "selected_target_right": [decision.right_x, decision.right_y],
                    "selected_visitor": visitor_source,
                    "visitor_center": list(visitor.center),
                    "multi_person": fallback_config.multi_person,
                    "source_age_s": decision.source_age_s,
                    "held_age_s": decision.held_age_s,
                    "emitted": False,
                    "stages_ms": stages_ms,
                })
            now = time.perf_counter()
            instant = 1.0 / max(now - last_frame, 1e-6)
            fps = instant if fps == 0.0 else 0.9 * fps + 0.1 * instant
            last_frame = now

            render_shadow = {
                "shadow_source": decision.active_source.name,
                "shadow_states": [decision.left_state.name, decision.right_state.name],
                "emission": "disabled-shadow-only",
            }
            if not baseline.process(frame, result, fps, time.perf_counter() - loop_started):
                rendered = render_frame(frame, result, output, fps, render_shadow)
            else:
                rendered = frame
            sequence = hub.update(rendered)
            with state_lock:
                shadow_state.update({
                    "decision": decision,
                    "candidates": dict(candidates),
                    "pupils": pupils,
                    "stages_ms": dict(stages_ms),
                    "sample_id": frames + 1,
                    "head": head_shadow.diagnostics() if head_shadow else {"enabled": False},
                    "face": face_shadow.diagnostics() if face_shadow else {"enabled": False},
                    "body": body_worker.diagnostics() if body_worker else {"enabled": False},
                })
                state.update({
                    "last_frame_at": time.time(),
                    "result": result,
                    "output": output,
                    "fps": fps,
                    "frame_sequence": sequence,
                })
            frames += 1
            if frames % 30 == 0:
                print(f"[APP] frames={frames} fps={fps:.1f} face={result.face_detected} inference_ms={result.inference_ms:.1f} shadow={decision.active_source.name}", flush=True)
            if args.max_frames is not None and frames >= args.max_frames:
                break
        return 0
    except (CameraError, OSError) as exc:
        with state_lock:
            state["capture_alive"] = False
        print(f"[APP] ERROR: {exc}", flush=True)
        if server.thread is not None:
            time.sleep(2.2)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        with state_lock:
            state["capture_alive"] = False
        if validation.active:
            try:
                validation.stop()
            except OSError as exc:
                print(f"[APP] validation finalize error: {exc}", flush=True)
        server.close()
        if tracker is not None:
            tracker.close()
        if head_shadow is not None:
            head_shadow.close()
        if face_shadow is not None:
            face_shadow.close()
        if body_worker is not None:
            body_worker.close()
        camera.close()
        print(f"[APP] exit after {frames} frames", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
