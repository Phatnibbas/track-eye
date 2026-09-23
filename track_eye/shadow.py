"""Shadow candidate detectors: head pose (Tasks Landmarker), face box, body.

All candidates run on the mirrored production frame inside the single camera
loop, or on a latest-frame worker that never blocks capture. Axis/sign
mappings stay in FallbackConfig and default to unvalidated/disabled.
"""

from __future__ import annotations

import hashlib
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .fallback import Candidate, FallbackConfig, SourceKind

FACE_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
FACE_LANDMARKER_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
FACE_LANDMARKER_SIZE = 3758596
MODEL_DIRNAME = "models"
FACE_LANDMARKER_FILENAME = "face_landmarker.task"


def model_path(root: Path) -> Path:
    return root / MODEL_DIRNAME / FACE_LANDMARKER_FILENAME


def ensure_face_landmarker(root: Path) -> Path:
    """Return the pinned asset path; download once, verify checksum/size.

    Never called implicitly from the production hot path: app startup calls it
    only when head-pose shadow is enabled, and failure disables the head
    candidate instead of crashing capture.
    """
    import urllib.request

    dest = model_path(root)
    if dest.exists() and _verified(dest):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".task.download")
    urllib.request.urlretrieve(FACE_LANDMARKER_URL, str(tmp))
    if not _verified(tmp):
        tmp.unlink(missing_ok=True)
        raise ValueError("downloaded face_landmarker.task failed checksum/size check")
    tmp.replace(dest)
    return dest


def _verified(path: Path) -> bool:
    try:
        if path.stat().st_size != FACE_LANDMARKER_SIZE:
            return False
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return digest == FACE_LANDMARKER_SHA256
    except OSError:
        return False


def clip_relative_box(
    x0: float, y0: float, width: float, height: float
) -> tuple[tuple[float, float, float, float], tuple[float, float]]:
    """Clip a detector box for diagnostics and bound its target center."""
    x1, y1 = x0 + width, y0 + height
    left = max(0.0, min(1.0, min(x0, x1)))
    top = max(0.0, min(1.0, min(y0, y1)))
    right = max(0.0, min(1.0, max(x0, x1)))
    bottom = max(0.0, min(1.0, max(y0, y1)))
    center = (
        max(0.0, min(1.0, x0 + width / 2.0)),
        max(0.0, min(1.0, y0 + height / 2.0)),
    )
    return (left, top, right - left, bottom - top), center


@dataclass
class TrackedVisitor:
    """Spatial-continuity visitor selection: nearest retained, never identity.

    Identity recognition is explicitly out of scope. Selection keeps the
    temporally nearest candidate center; ties prefer face, then head, then
    body priority. This is a policy placeholder for Gate 2: no validated
    distance/lighting/occlusion behavior exists yet.
    """

    center: tuple[float, float] = (0.5, 0.5)
    source: str = "none"
    updated_s: float = 0.0

    def nearest(self, options: dict[str, tuple[float, float] | None], now_s: float) -> str:
        best: str | None = None
        best_distance = float("inf")
        for source in ("face", "head", "body"):
            center = options.get(source)
            if center is None:
                continue
            distance = abs(center[0] - self.center[0]) + abs(center[1] - self.center[1])
            if distance < best_distance:
                best_distance = distance
                best = source
        if best is None:
            return "none"
        chosen = options[best]
        assert chosen is not None
        self.center = chosen
        self.source = best
        self.updated_s = now_s
        return best


def orthonormalize_rotation(m33: np.ndarray) -> tuple[np.ndarray, bool]:
    """Remove uniform scale via SVD; require finite proper rotation."""
    m = np.asarray(m33, dtype=np.float64)
    if m.shape != (3, 3) or not np.all(np.isfinite(m)):
        return np.eye(3), False
    try:
        u, _, vt = np.linalg.svd(m)
    except np.linalg.LinAlgError:
        return np.eye(3), False
    r = u @ vt
    if not np.all(np.isfinite(r)):
        return np.eye(3), False
    if float(np.linalg.det(r)) < 0.0:
        # Improper rotation (reflection): flip the last column's sign source.
        r = u @ np.diag([1.0, 1.0, -1.0]) @ vt
    if float(np.linalg.det(r)) <= 0.0 or not np.all(np.isfinite(r)):
        return np.eye(3), False
    return r, True


def rotation_to_quaternion(r: np.ndarray) -> tuple[float, float, float, float]:
    t = float(np.trace(r))
    if t > 0.0:
        s = 0.5 / np.sqrt(t + 1.0)
        return (0.25 / s, (r[2, 1] - r[1, 2]) * s, (r[0, 2] - r[2, 0]) * s, (r[1, 0] - r[0, 1]) * s)
    if r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = 2.0 * np.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2])
        return ((r[2, 1] - r[1, 2]) / s, 0.25 * s, (r[0, 1] + r[1, 0]) / s, (r[0, 2] + r[2, 0]) / s)
    if r[1, 1] > r[2, 2]:
        s = 2.0 * np.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2])
        return ((r[0, 2] - r[2, 0]) / s, (r[0, 1] + r[1, 0]) / s, 0.25 * s, (r[1, 2] + r[2, 1]) / s)
    s = 2.0 * np.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1])
    return ((r[1, 0] - r[0, 1]) / s, (r[0, 2] + r[2, 0]) / s, (r[1, 2] + r[2, 1]) / s, 0.25 * s)


@dataclass
class HeadPoseResult:
    valid: bool
    yaw_raw: float = 0.0
    pitch_raw: float = 0.0
    roll_raw: float = 0.0
    rotation: tuple[tuple[float, float, float], ...] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    quaternion: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
    determinant: float = 1.0
    latency_ms: float = 0.0
    reason: str = "uninitialized"


class HeadPoseShadow:
    """Tasks Face Landmarker head-pose candidate. Shadow only until validated."""

    def __init__(self, repo_root: Path, enabled: bool = True) -> None:
        self.enabled = enabled
        self._landmarker = None
        self._error: str | None = "not initialized"
        self.last = HeadPoseResult(valid=False, reason="not initialized")
        if not enabled:
            self._error = "disabled by config"
            self.last = HeadPoseResult(valid=False, reason="disabled by config")
            return
        try:
            asset = ensure_face_landmarker(repo_root)
            from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions
            from mediapipe.tasks.python.core.base_options import BaseOptions
            from mediapipe.tasks.python.vision.core.vision_task_running_mode import VisionTaskRunningMode

            options = FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(asset)),
                running_mode=VisionTaskRunningMode.VIDEO,
                num_faces=1,
                output_facial_transformation_matrixes=True,
            )
            self._landmarker = FaceLandmarker.create_from_options(options)
            self._error = None
            self.last = HeadPoseResult(valid=False, reason="no frame yet")
        except Exception as exc:  # never crash production startup
            self._landmarker = None
            self._error = f"{type(exc).__name__}: {exc}"
            self.last = HeadPoseResult(valid=False, reason=self._error)

    @property
    def error(self) -> str | None:
        return self._error

    def process(self, frame_bgr: np.ndarray, timestamp_ms: int, config: FallbackConfig) -> Candidate | None:
        now_ns = time.monotonic_ns()
        if self._landmarker is None:
            self.last = HeadPoseResult(valid=False, reason=self._error or "unavailable")
            return None
        import mediapipe as mp

        started = time.perf_counter()
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        try:
            result = self._landmarker.detect_for_video(image, timestamp_ms)
        except Exception as exc:
            self.last = HeadPoseResult(valid=False, reason=f"{type(exc).__name__}: {exc}")
            return Candidate(SourceKind.HEAD_POSE, now_ns, 0.0, 0.0, False, 0.0, {"reason": self.last.reason})
        latency_ms = (time.perf_counter() - started) * 1000.0
        matrices = list(getattr(result, "facial_transformation_matrixes", []) or [])
        if not matrices:
            self.last = HeadPoseResult(valid=False, reason="no face transform", latency_ms=latency_ms)
            return Candidate(SourceKind.HEAD_POSE, now_ns, 0.0, 0.0, False, latency_ms, {"reason": "no face transform"})
        m33 = np.asarray(matrices[0], dtype=np.float64)[0:3, 0:3]
        rotation, ok = orthonormalize_rotation(m33)
        if not ok:
            self.last = HeadPoseResult(valid=False, reason="non-proper rotation", latency_ms=latency_ms)
            return Candidate(SourceKind.HEAD_POSE, now_ns, 0.0, 0.0, False, latency_ms, {"reason": "non-proper rotation"})
        det = float(np.linalg.det(rotation))
        quat = rotation_to_quaternion(rotation)
        # Raw matrix elements as unlabeled yaw/pitch/roll proxies. Semantic
        # axis identity and sign under the mirrored path are NOT assigned
        # here; config mapping applies only when head_sign_validated is true.
        yaw_raw = float(rotation[0, 2])
        pitch_raw = float(rotation[1, 2])
        roll_raw = float(rotation[0, 1])
        self.last = HeadPoseResult(True, yaw_raw, pitch_raw, roll_raw,
                                   tuple(tuple(float(v) for v in row) for row in rotation),
                                   quat, det, latency_ms, "ok")
        if not config.head_sign_validated:
            return Candidate(SourceKind.HEAD_POSE, now_ns, 0.0, 0.0, False, latency_ms, {
                "reason": "axis/sign unvalidated",
                "yaw_raw": yaw_raw, "pitch_raw": pitch_raw, "roll_raw": roll_raw,
                "determinant": det, "quaternion": quat,
            })
        x = (yaw_raw - config.head_yaw_neutral) / config.head_yaw_scale
        y = (pitch_raw - config.head_pitch_neutral) / config.head_pitch_scale
        x = max(-1.0, min(1.0, x))
        y = max(-1.0, min(1.0, y))
        return Candidate(SourceKind.HEAD_POSE, now_ns, x, y, True, latency_ms, {
            "yaw_raw": yaw_raw, "pitch_raw": pitch_raw, "roll_raw": roll_raw,
            "determinant": det, "quaternion": quat,
        })

    def diagnostics(self) -> dict:
        last = self.last
        return {
            "enabled": self.enabled,
            "available": self._landmarker is not None,
            "error": self._error,
            "valid": last.valid,
            "reason": last.reason,
            "yaw_raw": last.yaw_raw,
            "pitch_raw": last.pitch_raw,
            "roll_raw": last.roll_raw,
            "rotation": [list(row) for row in last.rotation],
            "quaternion": list(last.quaternion),
            "determinant": last.determinant,
            "latency_ms": last.latency_ms,
            "model_sha256": FACE_LANDMARKER_SHA256,
            "model_size": FACE_LANDMARKER_SIZE,
        }

    def close(self) -> None:
        landmarker, self._landmarker = self._landmarker, None
        if landmarker is not None:
            try:
                landmarker.close()
            except Exception:
                pass


class FacePositionShadow:
    """Full-range FaceDetection box-center candidate. Real detector, real box."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._detector = None
        self._error: str | None = None
        self.last_box: tuple[float, float, float, float] | None = None
        self.last_raw_box: tuple[float, float, float, float] | None = None
        self.last_score: float = 0.0
        self.last_latency_ms: float = 0.0
        if not enabled:
            self._error = "disabled by config"
            return
        try:
            import mediapipe as mp

            self._detector = mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.1)
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"

    @property
    def error(self) -> str | None:
        return self._error

    def process(self, frame_bgr: np.ndarray, config: FallbackConfig, score_min: float = 0.1) -> Candidate | None:
        now_ns = time.monotonic_ns()
        if self._detector is None:
            return Candidate(SourceKind.FACE_POSITION, now_ns, 0.0, 0.0, False, 0.0, {"reason": self._error or "unavailable"})

        started = time.perf_counter()
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        try:
            result = self._detector.process(rgb)
        except Exception as exc:
            return Candidate(SourceKind.FACE_POSITION, now_ns, 0.0, 0.0, False, 0.0, {"reason": f"{type(exc).__name__}: {exc}"})
        latency_ms = (time.perf_counter() - started) * 1000.0
        detections = list(getattr(result, "detections", []) or [])
        if not detections:
            self.last_box = None
            self.last_raw_box = None
            self.last_score = 0.0
            self.last_latency_ms = latency_ms
            return Candidate(SourceKind.FACE_POSITION, now_ns, 0.0, 0.0, False, latency_ms, {"reason": "no detection"})
        best = max(detections, key=lambda d: float(d.score[0]) if len(d.score) else 0.0)
        score = float(best.score[0]) if len(best.score) else 0.0
        box = best.location_data.relative_bounding_box
        x0, y0, w, h = float(box.xmin), float(box.ymin), float(box.width), float(box.height)
        raw_box = (x0, y0, w, h)
        clipped_box, (cx, cy) = clip_relative_box(x0, y0, w, h)
        self.last_raw_box = raw_box
        self.last_box = clipped_box
        self.last_score = score
        self.last_latency_ms = latency_ms
        if score < score_min:
            return Candidate(SourceKind.FACE_POSITION, now_ns, 0.0, 0.0, False, latency_ms, {
                "reason": "below score_min", "score": score, "box": self.last_box, "raw_box": raw_box,
            })
        # Map box center relative to the configured installation ROI.
        rx0, ry0, rx1, ry1 = config.face_roi
        roi_cx, roi_cy = (rx0 + rx1) / 2.0, (ry0 + ry1) / 2.0
        half_w, half_h = max((rx1 - rx0) / 2.0, 1e-6), max((ry1 - ry0) / 2.0, 1e-6)
        x = ((cx - roi_cx) / half_w) * config.face_gain
        y = ((cy - roi_cy) / half_h) * config.face_gain
        x = max(-1.0, min(1.0, x))
        y = max(-1.0, min(1.0, y))
        return Candidate(SourceKind.FACE_POSITION, now_ns, x, y, True, latency_ms, {
            "score": score, "box": self.last_box, "raw_box": raw_box, "center": (cx, cy),
        })

    def diagnostics(self) -> dict:
        return {
            "enabled": self.enabled,
            "available": self._detector is not None,
            "error": self._error,
            "score": self.last_score,
            "box": list(self.last_box) if self.last_box else None,
            "raw_box": list(self.last_raw_box) if self.last_raw_box else None,
            "latency_ms": self.last_latency_ms,
        }

    def close(self) -> None:
        detector, self._detector = self._detector, None
        if detector is not None:
            try:
                detector.close()
            except Exception:
                pass


class BodyPositionWorker:
    """Latest-frame body/person candidate on a worker with queue depth 1.

    Uses OpenCV HOG people detection (ships with opencv-contrib, runs on Pi
    CPU, no extra model asset). Runs at a configured cadence on the latest
    frame only; never blocks the camera loop; stale pending frames dropped.
    HOG has no demonstrated visitor recall on the inspected visitor/empty
    scenes (score 0.0 in both): it is diagnostics-only and BODY_POSITION
    stays unselectable until body_enabled is explicitly validated.
    """

    def __init__(self, enabled: bool = True, cadence_s: float = 0.5, score_min: float = 0.35, selected: bool = False) -> None:
        self.enabled = enabled
        self.selected = selected
        self.cadence_s = cadence_s
        self.score_min = score_min
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._latest: Candidate | None = None
        self._last_box: tuple[float, float, float, float] | None = None
        self._last_score: float = 0.0
        self._last_latency_ms: float = 0.0
        self._last_run_s: float = 0.0
        self._error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._hog = None
        if not enabled:
            self._error = "disabled by config"
            return
        try:
            self._hog = cv2.HOGDescriptor()
            self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            return
        self._thread = threading.Thread(target=self._loop, name="body-shadow", daemon=True)
        self._thread.start()

    def submit(self, frame_bgr: np.ndarray) -> None:
        if self._hog is None or self._thread is None:
            return
        small = cv2.resize(frame_bgr, (640, 360))
        try:
            self._queue.put_nowait(small)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(small)
            except queue.Full:
                pass

    def _loop(self) -> None:
        assert self._hog is not None
        while not self._stop.is_set():
            try:
                frame = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            # Drain to latest: drop every stale pending frame.
            try:
                while True:
                    frame = self._queue.get_nowait()
            except queue.Empty:
                pass
            now = time.monotonic()
            if now - self._last_run_s < self.cadence_s:
                continue
            self._last_run_s = now
            started = time.perf_counter()
            try:
                boxes, weights = self._hog.detectMultiScale(frame, winStride=(16, 16))
            except Exception as exc:
                with self._lock:
                    self._error = f"{type(exc).__name__}: {exc}"
                continue
            latency_ms = (time.perf_counter() - started) * 1000.0
            height, width = frame.shape[:2]
            with self._lock:
                self._last_latency_ms = latency_ms
                if len(boxes) == 0:
                    self._latest = Candidate(SourceKind.BODY_POSITION, time.monotonic_ns(), 0.0, 0.0, False, latency_ms, {"reason": "no detection"})
                    self._last_box = None
                    self._last_score = 0.0
                    continue
                best_idx = int(np.argmax(weights)) if len(weights) else 0
                x, y, w, h = (float(v) for v in boxes[best_idx])
                score = float(weights[best_idx]) if len(weights) else 0.0
                cx, cy = (x + w / 2.0) / width, (y + h / 2.0) / height
                self._last_box = (x / width, y / height, w / width, h / height)
                self._last_score = score
                if score < self.score_min:
                    self._latest = Candidate(SourceKind.BODY_POSITION, time.monotonic_ns(), 0.0, 0.0, False, latency_ms, {
                        "reason": "below score_min", "score": score, "box": self._last_box,
                    })
                    continue
                tx = max(-1.0, min(1.0, (cx - 0.5) * 2.0))
                ty = max(-1.0, min(1.0, (cy - 0.5) * 2.0))
                self._latest = Candidate(SourceKind.BODY_POSITION, time.monotonic_ns(), tx, ty, True, latency_ms, {
                    "score": score, "box": self._last_box, "center": (cx, cy),
                })

    def latest(self) -> Candidate | None:
        with self._lock:
            return self._latest

    def diagnostics(self) -> dict:
        with self._lock:
            latest = self._latest
            return {
                "enabled": self.enabled,
                "available": self._hog is not None and self._thread is not None,
                "selected": self.selected,
                "error": self._error,
                "valid": bool(latest and latest.valid),
                "score": self._last_score,
                "box": list(self._last_box) if self._last_box else None,
                "target": (latest.x, latest.y) if latest else None,
                "age_s": (time.monotonic_ns() - latest.monotonic_ns) / 1e9 if latest else None,
                "latency_ms": self._last_latency_ms,
                "cadence_s": self.cadence_s,
                "score_min": self.score_min,
            }

    def close(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
