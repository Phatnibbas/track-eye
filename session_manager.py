"""Laptop-first user session lifecycle for the gaze runtime."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionSnapshot:
    state: str
    ready: bool
    reset_required: bool
    reason: str


class SessionManager:
    """Small deterministic state machine for sequential kiosk-style users."""

    def __init__(
        self,
        acquire_frames: int = 10,
        baseline_hold_s: float = 1.5,
        lost_face_timeout_s: float = 1.0,
        min_confidence: float = 0.35,
        drift_threshold: float = 0.25,
    ) -> None:
        self.acquire_frames = max(1, int(acquire_frames))
        self.baseline_hold_s = max(0.0, float(baseline_hold_s))
        self.lost_face_timeout_s = max(0.0, float(lost_face_timeout_s))
        self.min_confidence = float(min_confidence)
        self.drift_threshold = float(drift_threshold)

        self.state = "idle"
        self.ready = False
        self.reset_required = False
        self.reason = "waiting_for_user"
        self._stable_face_frames = 0
        self._state_started_at = 0.0
        self._last_face_seen_at: float | None = None
        self._baseline_x_eye = 0.0
        self._baseline_y_eye = 0.0

    def reset(self, reason: str = "manual_reset") -> SessionSnapshot:
        self.state = "idle"
        self.ready = False
        self.reset_required = True
        self.reason = reason
        self._stable_face_frames = 0
        self._state_started_at = 0.0
        self._last_face_seen_at = None
        self._baseline_x_eye = 0.0
        self._baseline_y_eye = 0.0
        return self.snapshot()

    def acknowledge_reset(self) -> None:
        self.reset_required = False

    def update(
        self,
        face_detected: bool,
        confidence: float,
        timestamp_s: float,
        x_eye: float = 0.0,
        y_eye: float = 0.0,
    ) -> SessionSnapshot:
        stable_face = bool(face_detected) and float(confidence) >= self.min_confidence

        if stable_face:
            self._last_face_seen_at = float(timestamp_s)
        elif self._last_face_seen_at is not None:
            if float(timestamp_s) - self._last_face_seen_at >= self.lost_face_timeout_s:
                return self.reset("lost_user")

        if self.state == "idle":
            self.ready = False
            if stable_face:
                self.state = "acquire_face"
                self.reason = "acquiring_user"
                self._stable_face_frames = 1
                self._state_started_at = float(timestamp_s)
            return self._advance_after_acquire(timestamp_s, x_eye, y_eye)

        if self.state == "acquire_face":
            self.ready = False
            if stable_face:
                self._stable_face_frames += 1
            else:
                self._stable_face_frames = 0
            return self._advance_after_acquire(timestamp_s, x_eye, y_eye)

        if self.state == "baseline_lock":
            self.ready = False
            self.reason = "locking_baseline"
            if stable_face and float(timestamp_s) - self._state_started_at >= self.baseline_hold_s:
                self.state = "active"
                self.ready = True
                self.reason = "active"
                self._baseline_x_eye = float(x_eye)
                self._baseline_y_eye = float(y_eye)
            return self.snapshot()

        if self.state == "needs_recenter":
            self.ready = False
            if stable_face and max(abs(float(x_eye)), abs(float(y_eye))) < self.drift_threshold * 0.5:
                self.state = "active"
                self.ready = True
                self.reason = "active"
                self._baseline_x_eye = float(x_eye)
                self._baseline_y_eye = float(y_eye)
            return self.snapshot()

        if self.state == "active":
            self.ready = stable_face
            self.reason = "active" if stable_face else "tracking_unstable"
            if stable_face:
                drift_x = abs(float(x_eye) - self._baseline_x_eye)
                drift_y = abs(float(y_eye) - self._baseline_y_eye)
                if max(drift_x, drift_y) >= self.drift_threshold:
                    self.state = "needs_recenter"
                    self.ready = False
                    self.reason = "center_drift"
            return self.snapshot()

        return self.snapshot()

    def _advance_after_acquire(
        self, timestamp_s: float, x_eye: float, y_eye: float
    ) -> SessionSnapshot:
        if self.state == "acquire_face" and self._stable_face_frames >= self.acquire_frames:
            self.state = "baseline_lock"
            self.reason = "locking_baseline"
            self._state_started_at = float(timestamp_s)
            if self.baseline_hold_s <= 0.0:
                self.state = "active"
                self.ready = True
                self.reason = "active"
                self._baseline_x_eye = float(x_eye)
                self._baseline_y_eye = float(y_eye)
        return self.snapshot()

    def snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(
            state=self.state,
            ready=self.ready,
            reset_required=self.reset_required,
            reason=self.reason,
        )
