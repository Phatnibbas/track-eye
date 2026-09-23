"""Production-owned raw validation capture: manifest, frames, cleanup.

Runs inside the single camera loop; never opens the device twice. Raw
images are stored ONLY while a validation session is explicitly started;
normal production stores no images. Derived per-frame observations,
candidate targets, selector decisions, and per-stage timings are recorded
for offline analysis; retention + cleanup are explicit.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2

CAPTURE_SCHEMA_VERSION = 1


def sha_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return "missing"


def sha_track_eye(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "track_eye").glob("*.py")):
        try:
            digest.update(path.read_bytes())
        except OSError:
            continue
    return digest.hexdigest()[:16]


@dataclass
class ValidationSession:
    output_dir: Path
    scenario: str = "unlabeled"
    max_frames: int = 2000
    jpeg_quality: int = 90

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False
        self._dir: Path | None = None
        self._manifest: dict = {}
        self._frames: list[dict] = []
        self._sequence = 0
        self._last_error: str | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def start(
        self,
        repo_root: Path,
        camera_info: dict,
        device: str,
        mirror: bool,
        calibration_path: Path,
        fallback_checksum: str,
        scenario: str | None = None,
        lighting_condition: str = "unlabeled",
        exposure: dict | None = None,
        consent_ref: str = "unlabeled",
        participant_split: str = "unlabeled",
    ) -> dict:
        with self._lock:
            if self._active:
                return dict(self._manifest)
            if scenario:
                self.scenario = scenario
            if not isinstance(lighting_condition, str) or not lighting_condition:
                raise ValueError("lighting_condition must be a non-empty string")
            if exposure is not None and not isinstance(exposure, dict):
                raise ValueError("exposure must be an object")
            if not isinstance(consent_ref, str) or not consent_ref:
                raise ValueError("consent_ref must be a non-empty string")
            if not isinstance(participant_split, str) or not participant_split:
                raise ValueError("participant_split must be a non-empty string")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            self._dir = self.output_dir / f"validation-{stamp}"
            (self._dir / "frames").mkdir(parents=True, exist_ok=False)
            try:
                import mediapipe

                mp_version = mediapipe.__version__
            except Exception:
                mp_version = "unknown"
            self._manifest = {
                "schema_version": CAPTURE_SCHEMA_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "scenario": self.scenario,
                "code_checksum": sha_track_eye(repo_root),
                "model": "mediapipe-facemesh-builtin",
                "model_version": mp_version,
                "face_landmarker_sha256": sha_file(repo_root / "models" / "face_landmarker.task"),
                "camera": dict(camera_info),
                "device": device,
                "mirror": mirror,
                "output_calibration_checksum": sha_file(calibration_path),
                "fallback_config_checksum": fallback_checksum,
                "lighting_condition": lighting_condition,
                "exposure": dict(exposure) if exposure is not None else {},
                "consent_ref": consent_ref,
                "participant_split": participant_split,
                "max_frames": self.max_frames,
            }
            (self._dir / "manifest.json").write_text(json.dumps(self._manifest, indent=2) + "\n", encoding="utf-8")
            self._frames = []
            self._sequence = 0
            self._last_error = None
            self._active = True
            return dict(self._manifest)

    def record(
        self,
        frame: "cv2.typing.MatLike",
        record: dict,
    ) -> bool:
        with self._lock:
            if not self._active or self._dir is None:
                return False
            try:
                if self._sequence >= self.max_frames:
                    self._finish_locked()
                    return False
                name = f"frame-{self._sequence:06d}.jpg"
                ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
                if ok:
                    (self._dir / "frames" / name).write_bytes(bytes(encoded))
                entry = {"sequence": self._sequence, "image": name if ok else None}
                entry.update(record)
                self._frames.append(entry)
                self._sequence += 1
                if self._sequence >= self.max_frames:
                    self._finish_locked()
                return True
            except (OSError, cv2.error) as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._active = False
                return False

    def stop(self) -> dict | None:
        with self._lock:
            if not self._active or self._dir is None:
                return None
            return self._finish_locked()

    def _finish_locked(self) -> dict:
        assert self._dir is not None
        (self._dir / "frames.jsonl").write_text(
            "".join(json.dumps(entry) + "\n" for entry in self._frames), encoding="utf-8"
        )
        summary = {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "frames": len(self._frames),
            "dir": str(self._dir),
            "manifest": self._manifest,
        }
        (self._dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        self._active = False
        result = dict(summary)
        self._dir = None
        return result

    def status(self) -> dict:
        with self._lock:
            return {
                "active": self._active,
                "scenario": self.scenario,
                "frames": self._sequence,
                "max_frames": self.max_frames,
                "dir": str(self._dir) if self._dir else None,
                "last_error": self._last_error,
            }

    @staticmethod
    def cleanup(root: Path, keep: int = 5) -> dict:
        """Keep the newest `keep` validation sessions; delete older raw frames."""
        sessions = sorted(root.glob("validation-*"), key=lambda p: p.name)
        removed: list[str] = []
        for session in sessions[:-keep] if len(sessions) > keep else []:
            shutil.rmtree(session, ignore_errors=True)
            removed.append(session.name)
        return {"kept": keep, "removed": removed, "remaining": sorted(p.name for p in root.glob("validation-*"))}
