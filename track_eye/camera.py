"""Deterministic V4L2 camera ownership and negotiated-format checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

DEFAULT_DEVICE = "/dev/v4l/by-id/usb-UGREEN_Camera_UGREEN_Camera_SN0001-video-index0"


class CameraError(RuntimeError):
    """Base class for camera startup and runtime failures."""


class CameraOpenError(CameraError):
    """The configured device could not be opened or negotiated."""


class CameraReadError(CameraError):
    """The camera produced too many consecutive failed reads."""


@dataclass(frozen=True)
class CameraConfig:
    device: str = DEFAULT_DEVICE
    width: int = 1280
    height: int = 720
    fps: float = 30.0
    fourcc: str = "MJPG"
    buffer_size: int = 1
    max_consecutive_failures: int = 10


@dataclass(frozen=True)
class CameraInfo:
    device: str
    width: int
    height: int
    fps: float
    fourcc: str


def _decode_fourcc(value: float) -> str:
    integer = int(value)
    return "".join(chr((integer >> (8 * index)) & 0xFF) for index in range(4))


class Camera:
    """Own one V4L2 capture and release it exactly once."""

    def __init__(self, config: CameraConfig):
        self.config = config
        self.capture: cv2.VideoCapture | None = None
        self.info: CameraInfo | None = None
        self._pending: np.ndarray | None = None
        self._consecutive_failures = 0

    def open(self) -> CameraInfo:
        if self.capture is not None:
            return self.info  # type: ignore[return-value]
        path = Path(self.config.device)
        if not path.exists():
            raise CameraOpenError(f"camera device does not exist: {self.config.device}")
        capture = cv2.VideoCapture(self.config.device, cv2.CAP_V4L2)
        if not capture.isOpened():
            capture.release()
            raise CameraOpenError(f"could not open camera: {self.config.device}")
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.config.fourcc[:4].upper()))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        capture.set(cv2.CAP_PROP_FPS, self.config.fps)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, self.config.buffer_size)
        ok, frame = capture.read()
        if not ok or frame is None:
            capture.release()
            raise CameraOpenError(f"camera opened but initial read failed: {self.config.device}")

        actual = CameraInfo(
            device=self.config.device,
            width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fps=float(capture.get(cv2.CAP_PROP_FPS)),
            fourcc=_decode_fourcc(capture.get(cv2.CAP_PROP_FOURCC)),
        )
        if (actual.width, actual.height) != (self.config.width, self.config.height):
            capture.release()
            raise CameraOpenError(
                f"camera negotiated {actual.width}x{actual.height}, "
                f"requested {self.config.width}x{self.config.height}"
            )
        if actual.fps <= 0.0 or abs(actual.fps - self.config.fps) > 2.0:
            capture.release()
            raise CameraOpenError(
                f"camera negotiated {actual.fps:.2f} fps, requested {self.config.fps:.2f}"
            )
        if self.config.fourcc and actual.fourcc.upper() != self.config.fourcc[:4].upper():
            capture.release()
            raise CameraOpenError(
                f"camera negotiated {actual.fourcc!r}, requested {self.config.fourcc[:4]!r}"
            )
        self.capture = capture
        self.info = actual
        self._pending = frame
        self._consecutive_failures = 0
        print(
            f"[CAMERA] device={actual.device} requested={self.config.width}x{self.config.height} "
            f"@{self.config.fps:.1f} {self.config.fourcc} negotiated="
            f"{actual.width}x{actual.height} @{actual.fps:.1f} {actual.fourcc}",
            flush=True,
        )
        return actual

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self.capture is None:
            raise CameraReadError("camera is not open")
        if self._pending is not None:
            frame, self._pending = self._pending, None
            self._consecutive_failures = 0
            return True, frame
        ok, frame = self.capture.read()
        if ok and frame is not None:
            self._consecutive_failures = 0
            return True, frame
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.config.max_consecutive_failures:
            raise CameraReadError(
                f"camera failed {self._consecutive_failures} consecutive reads"
            )
        return False, None

    def close(self) -> None:
        capture, self.capture = self.capture, None
        self._pending = None
        if capture is not None:
            capture.release()

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()
