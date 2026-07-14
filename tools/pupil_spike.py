"""Per-eye pupil tracking demo (Pi, UGREEN cam) — old Sharingan UI + robust core.

CORE (best fit for the goal): read iris landmarks DIRECTLY from MediaPipe FaceMesh
(refine_landmarks=True). Whenever a face is present BOTH irises are available — no
per-eye quality-gate dropout. For each eye we compute the pupil offset inside the
socket, head-normalized by the eye corners (so it survives head motion), and
EMA-smooth it.

UI (kept close to the original app): the two circular "Sharingan" gauges from
draw_utils, one per eye (LEFT EYE / RIGHT EYE), each with L/R/U/D axes and a dot
that moves to where that pupil points. On the face we also mark the detected iris
so you can see the gauge maps to the real pupil. NO servo, NO calibration.

Run on the Pi (watch on desktop browser http://<pi-ip>:8080):
  ~/track-eye/.venv/bin/python tools/pupil_spike.py --web-ui-host 0.0.0.0
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import mediapipe as mp  # noqa: E402

from constants import EYE_DEFINITIONS, IRIS_GROUPS  # noqa: E402
from filters import clamp  # noqa: E402
from servo_link import EyeMapper, UdpServoLink  # noqa: E402
from web_ui_server import FrameHub, WebUIServer  # noqa: E402

FONT = cv2.FONT_HERSHEY_SIMPLEX
GREEN = (0, 220, 0)
RED = (0, 0, 255)
CYAN = (255, 255, 0)
YELLOW = (0, 220, 220)
WHITE = (255, 255, 255)
INK = (244, 239, 228)
BLACK = (0, 0, 0)
# Rinnegan palette (BGR): light lavender ripples over a deep purple disc
RIN_FILL = (150, 70, 130)
RIN_RIM = (215, 150, 225)
RIN_RIPPLE = (235, 200, 240)
RIN_CORE = (60, 20, 55)
RIN_AXIS = (230, 210, 240)

ARROW_AMP = 2.6         # on-face arrow amplification
ARROW_MAX = 1.5         # cap arrow length at this * eye_width
EMA_ALPHA = 0.45        # smoothing (higher = snappier, lower = smoother)
GAUGE_GAIN_H = 3.0      # map normalized pupil h -> gauge dot (clamped to +/-1.5)
GAUGE_GAIN_V = 2.5      # vertical is more sensitive; smaller gain
V_DOWN_GAIN = 1.5       # extra amplification for DOWNWARD gaze only (looking-down is under-read)


def apply_down_gain(v: float, u: np.ndarray) -> float:
    """Amplify only the downward vertical component (up/level unchanged).

    For a near-horizontal eye, disp_y > 0 (pupil below eye-center in image = looking
    down) <=> v * u[0] > 0, independent of which corner is index 0. So we scale v by
    V_DOWN_GAIN exactly when the pupil is pointing down.
    """
    if v * float(u[0]) > 0.0:
        return v * V_DOWN_GAIN
    return v


def _mean(points: list[np.ndarray]) -> np.ndarray:
    return np.mean(np.asarray(points, dtype=np.float64), axis=0)


def open_camera(indices: list[int], width: int, height: int, fourcc: str) -> cv2.VideoCapture:
    for index in indices:
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            cap.release()
            continue
        if fourcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc.upper()[:4]))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok, _ = cap.read()
        if ok:
            print(f"[PUPIL] opened camera index {index}")
            return cap
        cap.release()
    raise RuntimeError(f"Could not open any camera in {indices}")


class EyeSmoother:
    def __init__(self, alpha: float):
        self.alpha = alpha
        self.h = None
        self.v = None

    def update(self, h: float, v: float) -> tuple[float, float]:
        if self.h is None:
            self.h, self.v = h, v
        else:
            self.h = self.alpha * h + (1 - self.alpha) * self.h
            self.v = self.alpha * v + (1 - self.alpha) * self.v
        return self.h, self.v


def measure_eye(px: np.ndarray, eyedef: dict, iris_group: tuple) -> dict:
    """Head-normalized pupil offset for one eye, from raw landmark pixels."""
    c0 = px[eyedef["corners"][0]]
    c1 = px[eyedef["corners"][1]]
    top = _mean([px[i] for i in eyedef["top"]])
    bottom = _mean([px[i] for i in eyedef["bottom"]])
    ring = [px[i] for i in iris_group]
    iris_c = _mean(ring)
    iris_r = float(np.mean([np.linalg.norm(p - iris_c) for p in ring]))

    eye_center = (c0 + c1) * 0.5
    u = c1 - c0
    width = float(np.linalg.norm(u))
    u = u / max(width, 1e-6)
    v_axis = np.array([-u[1], u[0]])          # perpendicular (vertical-ish)
    eye_h = float(np.linalg.norm(top - bottom))

    disp = iris_c - eye_center
    h = float(np.dot(disp, u) / max(width * 0.5, 1e-6))       # -1..1 (pupil at corner)
    v = float(np.dot(disp, v_axis) / max(eye_h * 0.5, 1e-6))  # -1..1 (pupil at lid)
    return {
        "name": eyedef["name"],
        "contour": [px[i].astype(int) for i in eyedef["contour"]],
        "eye_center": eye_center,
        "iris_c": iris_c,
        "iris_r": iris_r,
        "u": u,
        "v_axis": v_axis,
        "width": width,
        "h": h,
        "v": v,
    }


def draw_face_markers(frame: np.ndarray, eye: dict, h: float, v: float) -> None:
    """Mark the detected iris on the real face so the gauge is verifiable."""
    ec = eye["eye_center"]
    ecx, ecy = int(ec[0]), int(ec[1])
    ic = eye["iris_c"]
    cv2.polylines(frame, [np.array(eye["contour"], np.int32)], True, (0, 120, 0), 1, cv2.LINE_AA)
    cv2.circle(frame, (int(ic[0]), int(ic[1])), int(eye["iris_r"]), CYAN, 1, cv2.LINE_AA)
    cv2.circle(frame, (int(ic[0]), int(ic[1])), 2, RED, -1, cv2.LINE_AA)
    cv2.line(frame, (ecx - 5, ecy), (ecx + 5, ecy), WHITE, 1, cv2.LINE_AA)
    cv2.line(frame, (ecx, ecy - 5), (ecx, ecy + 5), WHITE, 1, cv2.LINE_AA)
    vec = (h * eye["u"] + v * eye["v_axis"]) * ARROW_AMP
    mag = float(np.linalg.norm(vec))
    if mag > ARROW_MAX:
        vec = vec / mag * ARROW_MAX
    tip = ec + vec * eye["width"]
    cv2.arrowedLine(frame, (ecx, ecy), (int(tip[0]), int(tip[1])), YELLOW, 2, cv2.LINE_AA, tipLength=0.3)


def draw_rinnegan_widget(
    frame: np.ndarray,
    center: tuple[int, int],
    size: int,
    x_value: float,
    y_value: float,
    confidence: float,
    label: str,
) -> None:
    """Rinnegan-style gauge: concentric ripple rings + a dot showing pupil direction."""
    outer_radius = size // 2 - 8
    track_radius = outer_radius - 20

    # translucent purple disc with a dark halo
    overlay = frame.copy()
    cv2.circle(overlay, center, outer_radius + 10, (55, 25, 50), -1, lineType=cv2.LINE_AA)
    cv2.circle(overlay, center, outer_radius, RIN_FILL, -1, lineType=cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.5, frame, 0.5, 0.0, frame)

    # concentric ripple rings (the Rinnegan signature)
    n_rings = 6
    for i in range(1, n_rings + 1):
        cv2.circle(frame, center, int(outer_radius * i / n_rings), RIN_RIPPLE, 1, lineType=cv2.LINE_AA)
    cv2.circle(frame, center, outer_radius, RIN_RIM, 2, lineType=cv2.LINE_AA)

    # subtle L/R + U/D reference axes
    cv2.arrowedLine(frame, (center[0] - outer_radius + 16, center[1]),
                    (center[0] + outer_radius - 8, center[1]), RIN_AXIS, 1, tipLength=0.05)
    cv2.arrowedLine(frame, (center[0], center[1] + outer_radius - 16),
                    (center[0], center[1] - outer_radius + 8), RIN_AXIS, 1, tipLength=0.05)

    # central pupil core
    cv2.circle(frame, center, max(6, size // 16), RIN_CORE, -1, lineType=cv2.LINE_AA)
    cv2.circle(frame, center, max(3, size // 30), BLACK, -1, lineType=cv2.LINE_AA)

    # moving pupil-direction dot + connector
    dot = (int(round(center[0] + track_radius * x_value)),
           int(round(center[1] + track_radius * y_value)))
    dot_color = GREEN if confidence >= 0.5 else YELLOW
    cv2.line(frame, center, dot, (235, 220, 245), 1, lineType=cv2.LINE_AA)
    cv2.circle(frame, dot, 9, WHITE, -1, lineType=cv2.LINE_AA)
    cv2.circle(frame, dot, 6, dot_color, -1, lineType=cv2.LINE_AA)

    # label + axis letters
    cv2.putText(frame, label, (center[0] - int(size * 0.34), center[1] - outer_radius - 10),
                FONT, 0.42, WHITE, 1, cv2.LINE_AA)
    for txt, pos in (
        ("L", (center[0] - outer_radius - 10, center[1] + 5)),
        ("R", (center[0] + outer_radius + 2, center[1] + 5)),
        ("U", (center[0] - 6, center[1] - outer_radius - 8)),
        ("D", (center[0] - 6, center[1] + outer_radius + 18)),
    ):
        cv2.putText(frame, txt, pos, FONT, 0.44, WHITE, 1, cv2.LINE_AA)


def draw_gauges(frame: np.ndarray, per_eye: list[dict | None]) -> None:
    """Two Rinnegan gauges (LEFT/RIGHT EYE) at the bottom-right of the frame."""
    h_img, w_img = frame.shape[:2]
    margin = 18
    gap = 18
    size = max(110, min(160, (w_img - (2 * margin) - gap) // 2))
    radius = size // 2
    baseline_y = h_img - margin - radius
    centers = [
        (w_img - margin - gap - size - radius, baseline_y),
        (w_img - margin - radius, baseline_y),
    ]
    labels = ["LEFT EYE", "RIGHT EYE"]
    for index, center in enumerate(centers):
        eye = per_eye[index] if index < len(per_eye) else None
        if eye is None:
            x_value = y_value = 0.0
            confidence = 0.0
        else:
            x_value = clamp(eye["h"] * GAUGE_GAIN_H, -1.5, 1.5)
            y_value = clamp(eye["v"] * GAUGE_GAIN_V, -1.5, 1.5)
            confidence = 0.9
        draw_rinnegan_widget(
            frame=frame,
            center=center,
            size=size,
            x_value=x_value,
            y_value=y_value,
            confidence=confidence,
            label=labels[index],
        )


def draw_hud(frame, fps: float, face: bool) -> None:
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (frame.shape[1], 34), (18, 18, 28), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0.0, frame)
    status = "BOTH PUPILS TRACKED" if face else "NO FACE"
    color = GREEN if face else RED
    cv2.putText(frame, f"PUPIL TRACKING  |  FPS {fps:4.1f}  |  {status}",
                (8, 23), FONT, 0.6, color, 2, cv2.LINE_AA)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Per-eye pupil tracking demo (Pi)")
    p.add_argument("--camera-index", type=int, default=0)
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--fourcc", type=str, default="MJPG")
    p.add_argument("--web-ui-host", type=str, default="0.0.0.0")
    p.add_argument("--web-ui-port", type=int, default=8080)
    p.add_argument("--min-detect", type=float, default=0.5)
    p.add_argument("--min-track", type=float, default=0.5)
    p.add_argument("--no-mirror", action="store_true")
    p.add_argument("--udp-host", type=str, default=None,
                   help="ESP32 IP for servo UDP output; unset = no servo emit (demo unchanged)")
    p.add_argument("--udp-port", type=int, default=8770)
    p.add_argument("--max-frames", type=int, default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    face_mesh = mp.solutions.face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=args.min_detect,
        min_tracking_confidence=args.min_track,
    )
    smoothers = {d["name"]: EyeSmoother(EMA_ALPHA) for d in EYE_DEFINITIONS}

    servo_link = UdpServoLink(args.udp_host, args.udp_port) if args.udp_host else None
    eye_mappers = [EyeMapper(), EyeMapper()] if servo_link is not None else None
    if servo_link is not None:
        print(f"[PUPIL] servo UDP -> {args.udp_host}:{args.udp_port}")

    frame_hub = FrameHub() if args.web_ui_host else None
    server = (
        WebUIServer(frame_hub, args.web_ui_host, args.web_ui_port, 8765)
        if frame_hub is not None else None
    )

    cap = None
    frame_count = 0
    try:
        cap = open_camera([args.camera_index, 0, 1, 2, 3], args.width, args.height, args.fourcc)
        if server is not None:
            server.start()
            print(f"[PUPIL] Web UI -> http://{args.web_ui_host}:{args.web_ui_port}")
        print("[PUPIL] running; Ctrl+C to stop")

        fps = 0.0
        last = time.perf_counter()
        while True:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("camera read failed")
            if not args.no_mirror:
                frame = cv2.flip(frame, 1)

            h_img, w_img = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = face_mesh.process(rgb)

            face = False
            per_eye: list[dict | None] = [None, None]
            log_bits = []
            if result.multi_face_landmarks:
                face = True
                lm = result.multi_face_landmarks[0].landmark
                px = np.array([[p.x * w_img, p.y * h_img] for p in lm], dtype=np.float64)
                for idx, (eyedef, iris_group) in enumerate(zip(EYE_DEFINITIONS, IRIS_GROUPS)):
                    eye = measure_eye(px, eyedef, iris_group)
                    hs, vs = smoothers[eye["name"]].update(eye["h"], eye["v"])
                    vs_disp = apply_down_gain(vs, eye["u"])   # display keeps downward boost
                    eye["h"], eye["v"] = hs, vs_disp
                    eye["v_servo"] = vs                        # raw (pre-down-gain) -> servo mapper
                    per_eye[idx] = eye
                    draw_face_markers(frame, eye, hs, vs_disp)
                    log_bits.append(f"{eye['name'][-3:]}:h={hs:+.2f} v={vs:+.2f}")

            if servo_link is not None:
                if face and per_eye[0] is not None and per_eye[1] is not None:
                    lp, lt = eye_mappers[0].map(per_eye[0]["h"], per_eye[0]["v_servo"])
                    rp, rt = eye_mappers[1].map(per_eye[1]["h"], per_eye[1]["v_servo"])
                    servo_link.send(lp, lt, rp, rt, "tracking")
                else:
                    servo_link.send(80, 60, 80, 60, "neutral")

            draw_gauges(frame, per_eye)

            now = time.perf_counter()
            inst = 1.0 / max(1e-6, now - last)
            fps = inst if fps == 0.0 else (0.9 * fps + 0.1 * inst)
            last = now
            draw_hud(frame, fps, face)

            if frame_hub is not None:
                frame_hub.update(frame)
            frame_count += 1
            if frame_count % 30 == 0:
                print(f"[PUPIL] f={frame_count} fps={fps:.1f} face={face} {' | '.join(log_bits)}")
            if args.max_frames is not None and frame_count >= args.max_frames:
                break
        return 0
    except KeyboardInterrupt:
        print("[PUPIL] stopped")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    finally:
        print(f"[PUPIL] exit after {frame_count} frames")
        face_mesh.close()
        if cap is not None:
            cap.release()
        if server is not None:
            server.close()
        if servo_link is not None:
            servo_link.close()


if __name__ == "__main__":
    raise SystemExit(main())
