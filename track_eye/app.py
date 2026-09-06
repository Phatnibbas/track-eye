"""Production software-only camera -> tracker -> renderer -> web process."""

from __future__ import annotations

import argparse
import signal
import threading
import time

import cv2

from .camera import DEFAULT_DEVICE, Camera, CameraConfig, CameraError
from .output import OutputGain, scale_tracking_result
from .rendering import render_frame
from .tracker import EyeTracker
from .web import FrameHub, WebUIServer


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
    parser.add_argument("--output-horizontal-gain", type=float, default=3.0)
    parser.add_argument("--output-vertical-up-gain", type=float, default=2.5)
    parser.add_argument("--output-vertical-down-gain", type=float, default=3.75)
    parser.add_argument("--no-mirror", action="store_true")
    parser.add_argument("--max-frames", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda _signum, _frame: stop.set())
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())

    camera = Camera(CameraConfig(args.device, args.width, args.height, args.fps, args.fourcc))
    tracker: EyeTracker | None = None
    hub = FrameHub()
    state = {"started_at": time.time(), "last_frame_at": 0.0, "capture_alive": False, "result": None, "output": None, "fps": 0.0}
    output_gain = OutputGain(
        horizontal=args.output_horizontal_gain,
        vertical_up=args.output_vertical_up_gain,
        vertical_down=args.output_vertical_down_gain,
    )

    def status() -> dict:
        now = time.time()
        age = None if not state["last_frame_at"] else max(0.0, now - state["last_frame_at"])
        result = state["result"]
        output = state["output"]
        raw_eyes = result.eyes if result is not None and result.face_detected else None
        output_eyes = output.eyes if output is not None and output.face_detected else None
        return {
            "version": "0.1.0",
            "uptime_seconds": now - state["started_at"],
            "frame_sequence": hub.latest_sequence,
            "last_frame_age_seconds": age,
            "camera": camera.info.__dict__ if camera.info is not None else None,
            "fps": state["fps"],
            "face_detected": bool(result and result.face_detected),
            "inference_ms": None if result is None else result.inference_ms,
            "raw_left": None if raw_eyes is None else {"x": raw_eyes[0].x, "y": raw_eyes[0].y},
            "raw_right": None if raw_eyes is None else {"x": raw_eyes[1].x, "y": raw_eyes[1].y},
            "output_left": None if output_eyes is None else {"x": output_eyes[0].x, "y": output_eyes[0].y},
            "output_right": None if output_eyes is None else {"x": output_eyes[1].x, "y": output_eyes[1].y},
            "output_gain": {
                "horizontal": output_gain.horizontal,
                "vertical_up": output_gain.vertical_up,
                "vertical_down": output_gain.vertical_down,
            },
            "capture_alive": state["capture_alive"],
            "healthy": bool(state["capture_alive"] and age is not None and age <= 2.0),
        }

    server = WebUIServer(hub, args.web_host, args.web_port, status)
    frames = 0
    last_frame = time.perf_counter()
    fps = 0.0
    try:
        camera.open()
        tracker = EyeTracker(args.min_detect, args.min_track, args.ema_alpha)
        server.start()
        state["capture_alive"] = True
        print(f"[APP] web=http://{args.web_host}:{args.web_port} device={args.device}", flush=True)
        while not stop.is_set():
            ok, frame = camera.read()
            if not ok or frame is None:
                continue
            if not args.no_mirror:
                frame = cv2.flip(frame, 1)
            result = tracker.process(frame)
            now = time.perf_counter()
            instant = 1.0 / max(now - last_frame, 1e-6)
            fps = instant if fps == 0.0 else 0.9 * fps + 0.1 * instant
            last_frame = now
            output = scale_tracking_result(result, output_gain)
            rendered = render_frame(frame, result, output, fps)
            hub.update(rendered)
            state.update({"last_frame_at": time.time(), "result": result, "output": output, "fps": fps})
            frames += 1
            if frames % 30 == 0:
                print(f"[APP] frames={frames} fps={fps:.1f} face={result.face_detected} inference_ms={result.inference_ms:.1f}", flush=True)
            if args.max_frames is not None and frames >= args.max_frames:
                break
        return 0
    except (CameraError, OSError) as exc:
        state["capture_alive"] = False
        print(f"[APP] ERROR: {exc}", flush=True)
        if server.thread is not None:
            time.sleep(2.2)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        state["capture_alive"] = False
        server.close()
        if tracker is not None:
            tracker.close()
        camera.close()
        print(f"[APP] exit after {frames} frames", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
