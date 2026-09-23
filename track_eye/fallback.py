"""Fallback source hierarchy: observations, versioned config, selector, payload codec.

Shadow-first design: every degraded candidate runs and reports diagnostics,
but production output stays unchanged until emission is explicitly enabled
with a validated (non-placeholder) configuration.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import time
from dataclasses import dataclass, field
from enum import IntEnum

CONFIG_SCHEMA_VERSION = 1


def _check(name: str, value: float, lo: float, hi: float) -> float:
    number = float(value)
    if not math.isfinite(number) or not lo <= number <= hi:
        raise ValueError(f"{name} must be within [{lo}, {hi}]")
    return number


def _as_float(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _as_bool(name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


# ---------------------------------------------------------------------------
# Source states (accepted contract, docs/OPEN_RESEARCH_PROTOCOL_FALLBACK.md)
# ---------------------------------------------------------------------------


class EyeState(IntEnum):
    INVALID = 0
    TRACKED_PUPIL = 1
    HELD_TARGET = 2
    HEAD_POSE_DEGRADED = 3
    FACE_POSITION_DEGRADED = 4
    BODY_POSITION_DEGRADED = 5


class SourceKind(IntEnum):
    PUPIL_LEFT = 10
    PUPIL_RIGHT = 11
    HEAD_POSE = 3
    FACE_POSITION = 4
    BODY_POSITION = 5
    HELD = 2
    NONE = 0


SOURCE_PRIORITY: tuple[SourceKind, ...] = (
    SourceKind.PUPIL_LEFT,
    SourceKind.PUPIL_RIGHT,
    SourceKind.HEAD_POSE,
    SourceKind.FACE_POSITION,
    SourceKind.BODY_POSITION,
    SourceKind.HELD,
    SourceKind.NONE,
)

# EyeState emitted per source. Pupil eyes share TRACKED_PUPIL only when the
# selector runs in dual-pupil mode; degraded sources share one target.
SOURCE_EYE_STATE = {
    SourceKind.PUPIL_LEFT: EyeState.TRACKED_PUPIL,
    SourceKind.PUPIL_RIGHT: EyeState.TRACKED_PUPIL,
    SourceKind.HEAD_POSE: EyeState.HEAD_POSE_DEGRADED,
    SourceKind.FACE_POSITION: EyeState.FACE_POSITION_DEGRADED,
    SourceKind.BODY_POSITION: EyeState.BODY_POSITION_DEGRADED,
    SourceKind.HELD: EyeState.HELD_TARGET,
    SourceKind.NONE: EyeState.INVALID,
}


# ---------------------------------------------------------------------------
# Observation model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """One normalized target observation from a single source."""

    source: SourceKind
    monotonic_ns: int
    x: float
    y: float
    valid: bool
    latency_ms: float = 0.0
    quality: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EyePupilObservation:
    """Per-eye pupil measurement, independent of the other eye."""

    name: str
    monotonic_ns: int
    x: float
    y: float
    valid: bool
    latency_ms: float = 0.0
    quality: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SelectorDecision:
    left_state: EyeState
    right_state: EyeState
    left_x: float
    left_y: float
    right_x: float
    right_y: float
    active_source: SourceKind
    mixed: bool
    reason: str
    source_age_s: float
    held_age_s: float | None


# ---------------------------------------------------------------------------
# Versioned configuration with bounds; installation values live here, never
# as bare constants in the selector.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceTiming:
    promote_s: float = 0.30
    demote_s: float = 0.50
    expire_s: float = 1.50


@dataclass(frozen=True)
class FallbackConfig:
    schema_version: int = CONFIG_SCHEMA_VERSION
    emission_enabled: bool = False
    calibrated: bool = False
    pupil_mode: str = "compatibility"
    pupil: SourceTiming = SourceTiming(0.15, 0.40, 1.00)
    head_pose: SourceTiming = SourceTiming(0.30, 0.60, 2.00)
    face_position: SourceTiming = SourceTiming(0.40, 0.80, 2.50)
    body_position: SourceTiming = SourceTiming(0.60, 1.00, 3.00)
    hold_s: float = 0.60
    max_held_s: float = 0.60
    slew_per_s: float = 8.0
    head_yaw_neutral: float = 0.0
    head_yaw_scale: float = 0.6
    head_pitch_neutral: float = 0.0
    head_pitch_scale: float = 0.6
    head_sign_validated: bool = False
    face_roi: tuple[float, float, float, float] = (0.05, 0.05, 0.95, 0.95)
    face_gain: float = 1.0
    face_score_min: float = 0.30
    body_score_min: float = 0.35
    body_cadence_s: float = 0.50
    body_enabled: bool = False
    multi_person: str = "nearest-retained"
    pupil_quality: dict = field(default_factory=dict)

    def timings(self) -> dict[SourceKind, SourceTiming]:
        return {
            SourceKind.PUPIL_LEFT: self.pupil,
            SourceKind.PUPIL_RIGHT: self.pupil,
            SourceKind.HEAD_POSE: self.head_pose,
            SourceKind.FACE_POSITION: self.face_position,
            SourceKind.BODY_POSITION: self.body_position,
        }

    def validate(self) -> "FallbackConfig":
        if self.schema_version != CONFIG_SCHEMA_VERSION:
            raise ValueError("unsupported fallback config schema")
        if self.emission_enabled:
            raise ValueError("fallback emission is not integrated; emission_enabled must remain false")
        if self.pupil_mode not in ("compatibility", "gated"):
            raise ValueError("pupil_mode must be compatibility|gated")
        for timing in (self.pupil, self.head_pose, self.face_position, self.body_position):
            _check("promote_s", timing.promote_s, 0.0, 10.0)
            _check("demote_s", timing.demote_s, 0.0, 10.0)
            _check("expire_s", timing.expire_s, 0.05, 30.0)
        _check("hold_s", self.hold_s, 0.0, 5.0)
        _check("max_held_s", self.max_held_s, 0.0, 5.0)
        if self.max_held_s + 1e-9 < self.hold_s:
            raise ValueError("max_held_s must be at least hold_s")
        _check("slew_per_s", self.slew_per_s, 0.1, 100.0)
        _check("head_yaw_neutral", self.head_yaw_neutral, -1.0, 1.0)
        _check("head_yaw_scale", self.head_yaw_scale, 0.05, 5.0)
        _check("head_pitch_neutral", self.head_pitch_neutral, -1.0, 1.0)
        _check("head_pitch_scale", self.head_pitch_scale, 0.05, 5.0)
        x0, y0, x1, y1 = (float(v) for v in self.face_roi)
        if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
            raise ValueError("face_roi must be (x0,y0,x1,y1) inside [0,1]")
        _check("face_gain", self.face_gain, 0.1, 5.0)
        _check("face_score_min", self.face_score_min, 0.0, 1.0)
        _check("body_score_min", self.body_score_min, 0.0, 1.0)
        _check("body_cadence_s", self.body_cadence_s, 0.05, 5.0)
        if self.multi_person != "nearest-retained":
            raise ValueError("multi_person must be nearest-retained")
        return self

    def checksum(self) -> str:
        body = json.dumps(config_to_dict(self), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(body.encode()).hexdigest()[:16]



DEFAULT_FALLBACK_CONFIG = FallbackConfig().validate()


def config_from_dict(value: dict) -> FallbackConfig:
    if (
        not isinstance(value, dict)
        or isinstance(value.get("schema_version"), bool)
        or value.get("schema_version") != CONFIG_SCHEMA_VERSION
    ):
        raise ValueError("unsupported fallback config schema")
    allowed = {
        "schema_version", "emission_enabled", "calibrated", "pupil_mode",
        "pupil", "head_pose", "face_position", "body_position", "hold_s",
        "max_held_s", "slew_per_s", "head_yaw_neutral", "head_yaw_scale",
        "head_pitch_neutral", "head_pitch_scale", "head_sign_validated",
        "face_roi", "face_gain", "face_score_min", "body_score_min",
        "body_cadence_s", "body_enabled", "multi_person", "pupil_quality",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown fallback config fields: {', '.join(unknown)}")

    def timing(key: str, default: SourceTiming) -> SourceTiming:
        raw = value.get(key, {})
        if not isinstance(raw, dict):
            raise ValueError(f"{key} must be an object")
        timing_unknown = sorted(set(raw) - {"promote_s", "demote_s", "expire_s"})
        if timing_unknown:
            raise ValueError(f"unknown {key} fields: {', '.join(timing_unknown)}")
        return SourceTiming(
            promote_s=_as_float(f"{key}.promote_s", raw.get("promote_s", default.promote_s)),
            demote_s=_as_float(f"{key}.demote_s", raw.get("demote_s", default.demote_s)),
            expire_s=_as_float(f"{key}.expire_s", raw.get("expire_s", default.expire_s)),
        )

    base = FallbackConfig()
    roi = value.get("face_roi", base.face_roi)
    if not isinstance(roi, (list, tuple)) or len(roi) != 4:
        raise ValueError("face_roi must contain exactly four numbers")
    pupil_quality = value.get("pupil_quality", {})
    if not isinstance(pupil_quality, dict):
        raise ValueError("pupil_quality must be an object")
    return FallbackConfig(
        schema_version=CONFIG_SCHEMA_VERSION,
        emission_enabled=_as_bool("emission_enabled", value.get("emission_enabled", False)),
        calibrated=_as_bool("calibrated", value.get("calibrated", False)),
        pupil_mode=str(value.get("pupil_mode", "compatibility")),
        pupil=timing("pupil", base.pupil),
        head_pose=timing("head_pose", base.head_pose),
        face_position=timing("face_position", base.face_position),
        body_position=timing("body_position", base.body_position),
        hold_s=_as_float("hold_s", value.get("hold_s", base.hold_s)),
        max_held_s=_as_float("max_held_s", value.get("max_held_s", base.max_held_s)),
        slew_per_s=_as_float("slew_per_s", value.get("slew_per_s", base.slew_per_s)),
        head_yaw_neutral=_as_float("head_yaw_neutral", value.get("head_yaw_neutral", base.head_yaw_neutral)),
        head_yaw_scale=_as_float("head_yaw_scale", value.get("head_yaw_scale", base.head_yaw_scale)),
        head_pitch_neutral=_as_float("head_pitch_neutral", value.get("head_pitch_neutral", base.head_pitch_neutral)),
        head_pitch_scale=_as_float("head_pitch_scale", value.get("head_pitch_scale", base.head_pitch_scale)),
        head_sign_validated=_as_bool("head_sign_validated", value.get("head_sign_validated", False)),
        face_roi=tuple(_as_float(f"face_roi[{index}]", item) for index, item in enumerate(roi)),
        face_gain=_as_float("face_gain", value.get("face_gain", base.face_gain)),
        face_score_min=_as_float("face_score_min", value.get("face_score_min", base.face_score_min)),
        body_score_min=_as_float("body_score_min", value.get("body_score_min", base.body_score_min)),
        body_cadence_s=_as_float("body_cadence_s", value.get("body_cadence_s", base.body_cadence_s)),
        body_enabled=_as_bool("body_enabled", value.get("body_enabled", base.body_enabled)),
        multi_person=str(value.get("multi_person", base.multi_person)),
        pupil_quality=dict(pupil_quality),
    ).validate()


def config_to_dict(config: FallbackConfig) -> dict:
    return {
        "schema_version": config.schema_version,
        "emission_enabled": config.emission_enabled,
        "calibrated": config.calibrated,
        "pupil_mode": config.pupil_mode,
        "pupil": {"promote_s": config.pupil.promote_s, "demote_s": config.pupil.demote_s, "expire_s": config.pupil.expire_s},
        "head_pose": {"promote_s": config.head_pose.promote_s, "demote_s": config.head_pose.demote_s, "expire_s": config.head_pose.expire_s},
        "face_position": {"promote_s": config.face_position.promote_s, "demote_s": config.face_position.demote_s, "expire_s": config.face_position.expire_s},
        "body_position": {"promote_s": config.body_position.promote_s, "demote_s": config.body_position.demote_s, "expire_s": config.body_position.expire_s},
        "hold_s": config.hold_s,
        "max_held_s": config.max_held_s,
        "slew_per_s": config.slew_per_s,
        "head_yaw_neutral": config.head_yaw_neutral,
        "head_yaw_scale": config.head_yaw_scale,
        "head_pitch_neutral": config.head_pitch_neutral,
        "head_pitch_scale": config.head_pitch_scale,
        "head_sign_validated": config.head_sign_validated,
        "face_roi": list(config.face_roi),
        "face_gain": config.face_gain,
        "face_score_min": config.face_score_min,
        "body_score_min": config.body_score_min,
        "body_cadence_s": config.body_cadence_s,
        "body_enabled": config.body_enabled,
        "multi_person": config.multi_person,
        "pupil_quality": dict(config.pupil_quality),
    }


# ---------------------------------------------------------------------------
# Time-based selector with promotion/demotion hysteresis and bounded hold.
# ---------------------------------------------------------------------------


@dataclass
class _SourceTrack:
    valid_since: float | None = None
    invalid_since: float | None = None
    last_valid_ns: int | None = None
    last_x: float = 0.0
    last_y: float = 0.0


class FallbackSelector:
    """Best-available-source state machine over monotonic elapsed time."""

    def __init__(self, config: FallbackConfig = DEFAULT_FALLBACK_CONFIG):
        self.config = config.validate()
        self._tracks: dict[SourceKind, _SourceTrack] = {kind: _SourceTrack() for kind in SOURCE_PRIORITY}
        self._active: SourceKind = SourceKind.NONE
        self._active_since: float = time.monotonic()
        self._reason: str = "init"
        self._held: tuple[float, float, float, float] | None = None
        self._held_since: float | None = None
        self._held_from: SourceKind | None = None
        self._last_emit: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self._last_emit_at: float | None = None

    @property
    def active(self) -> SourceKind:
        return self._active

    @property
    def reason(self) -> str:
        return self._reason

    def update(
        self,
        now_s: float,
        pupils: tuple[EyePupilObservation, EyePupilObservation] | None,
        candidates: dict[SourceKind, Candidate],
        compat_eyes: tuple[tuple[float, float], tuple[float, float]] | None,
    ) -> SelectorDecision:
        timings = self.config.timings()
        fresh: dict[SourceKind, Candidate] = {}
        for kind, cand in candidates.items():
            if kind not in timings or cand.source != kind:
                continue
            # Age is computed against the caller clock: candidates carry
            # monotonic_ns from the same clock as now_s. Invalid numeric
            # targets are never allowed into selector state.
            age = now_s - cand.monotonic_ns / 1e9
            finite_target = math.isfinite(cand.x) and math.isfinite(cand.y)
            if cand.valid and finite_target and 0.0 <= age <= timings[kind].expire_s:
                fresh[kind] = cand
        # Update per-source valid/invalid clocks.
        for kind in timings:
            track = self._tracks[kind]
            if kind in (SourceKind.PUPIL_LEFT, SourceKind.PUPIL_RIGHT):
                continue  # pupil tracked separately below
            if kind in fresh:
                if track.valid_since is None:
                    track.valid_since = now_s
                track.invalid_since = None
                track.last_valid_ns = fresh[kind].monotonic_ns
                track.last_x, track.last_y = fresh[kind].x, fresh[kind].y
            else:
                if track.invalid_since is None:
                    track.invalid_since = now_s
                track.valid_since = None

        pupil_ok = self._pupil_ok(now_s, pupils, compat_eyes)
        if pupil_ok is not None:
            for kind in (SourceKind.PUPIL_LEFT, SourceKind.PUPIL_RIGHT):
                track = self._tracks[kind]
                if track.valid_since is None:
                    track.valid_since = now_s
                track.invalid_since = None
        else:
            for kind in (SourceKind.PUPIL_LEFT, SourceKind.PUPIL_RIGHT):
                track = self._tracks[kind]
                if track.invalid_since is None:
                    track.invalid_since = now_s
                track.valid_since = None

        ranked = self._rank(now_s, pupil_ok is not None, fresh)
        winner = ranked[0] if ranked else SourceKind.NONE
        # Promotion gate: every newly selected real source, including initial
        # acquisition from NONE, must be continuously valid. If the old source
        # disappears during that gate, hold its last full target instead of
        # emitting INVALID while a challenger is being qualified.
        if winner != self._active and self._priority_of(winner) < self._priority_of(self._active):
            challenger = winner
            timing = self._timing_for(challenger)
            since = self._tracks[challenger].valid_since if challenger not in (SourceKind.HELD, SourceKind.NONE) else now_s
            stable_for = 0.0 if since is None else now_s - since
            if stable_for < timing.promote_s:
                held_available = self._held_valid(now_s)
                active_available = (
                    (self._active == SourceKind.PUPIL_LEFT and pupil_ok is not None)
                    or self._active in fresh
                    or (self._active == SourceKind.HELD and held_available)
                )
                if active_available:
                    winner = self._active
                elif held_available:
                    winner = SourceKind.HELD
                else:
                    winner = SourceKind.NONE
                self._reason = f"promote-gated {challenger.name}"
        # Demotion: switch immediately in state, but keep emitting the last
        # valid target of the lost source through its demote grace + hold.
        # _emit falls back to the demote-gated track below via _held bridge.
        # The absolute bound always wins: no demote grace may outlive
        # max_held_s, even when a source-specific demote_s is larger.
        demote_hold: tuple[float, float, float, float] | None = None
        if winner != self._active and self._priority_of(winner) > self._priority_of(self._active):
            timing = self._timing_for(self._active)
            track = self._tracks[self._active]
            since_invalid = track.invalid_since
            held_age = self._held_age(now_s)
            held_within_absolute = held_age is not None and held_age <= self.config.max_held_s
            if (
                since_invalid is not None
                and now_s - since_invalid < timing.demote_s
                and held_within_absolute
            ):
                demote_hold = self._held
                if demote_hold is None:
                    demote_hold = (track.last_x, track.last_y, track.last_x, track.last_y)
                self._reason = f"demote-gated {self._active.name}"
        if winner != self._active and demote_hold is None:
            self._reason = f"select {winner.name} over {self._active.name}"
            self._active = winner
            self._active_since = now_s

        decision = self._emit(now_s, winner, pupil_ok, fresh, compat_eyes, demote_hold)
        return decision

    # -- internals ---------------------------------------------------------
    def _timing_for(self, kind: SourceKind) -> SourceTiming:
        if kind in (SourceKind.PUPIL_LEFT, SourceKind.PUPIL_RIGHT):
            return self.config.pupil
        if kind == SourceKind.HEAD_POSE:
            return self.config.head_pose
        if kind == SourceKind.FACE_POSITION:
            return self.config.face_position
        if kind == SourceKind.BODY_POSITION:
            return self.config.body_position
        return SourceTiming(0.0, 0.0, self.config.hold_s)

    @staticmethod
    def _priority_of(kind: SourceKind) -> int:
        return SOURCE_PRIORITY.index(kind)

    def _pupil_ok(
        self,
        now_s: float,
        pupils: tuple[EyePupilObservation, EyePupilObservation] | None,
        compat_eyes: tuple[tuple[float, float], tuple[float, float]] | None,
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        if self.config.pupil_mode == "compatibility":
            if compat_eyes is None:
                return None
            values = tuple(value for eye in compat_eyes for value in eye)
            if not all(math.isfinite(value) for value in values):
                return None
            track = self._tracks[SourceKind.PUPIL_LEFT]
            track.last_x, track.last_y = compat_eyes[0][0], compat_eyes[0][1]
            track2 = self._tracks[SourceKind.PUPIL_RIGHT]
            track2.last_x, track2.last_y = compat_eyes[1][0], compat_eyes[1][1]
            return compat_eyes
        # Gated mode: both per-eye observations must be valid and fresh.
        if pupils is None:
            return None
        timing = self.config.pupil
        for obs in pupils:
            age = now_s - obs.monotonic_ns / 1e9
            finite_target = math.isfinite(obs.x) and math.isfinite(obs.y)
            if not obs.valid or not finite_target or age < 0.0 or age > timing.expire_s:
                return None
        left, right = pupils
        self._tracks[SourceKind.PUPIL_LEFT].last_x = left.x
        self._tracks[SourceKind.PUPIL_LEFT].last_y = left.y
        self._tracks[SourceKind.PUPIL_RIGHT].last_x = right.x
        self._tracks[SourceKind.PUPIL_RIGHT].last_y = right.y
        return ((left.x, left.y), (right.x, right.y))

    def _rank(
        self,
        now_s: float,
        pupil_ok: bool,
        fresh: dict[SourceKind, Candidate],
    ) -> list[SourceKind]:
        ordered: list[SourceKind] = []
        if pupil_ok:
            # Dual-pupil winner; per-eye split decided at emit time.
            ordered.append(SourceKind.PUPIL_LEFT)
        for kind in (SourceKind.HEAD_POSE, SourceKind.FACE_POSITION, SourceKind.BODY_POSITION):
            if kind == SourceKind.BODY_POSITION and not self.config.body_enabled:
                # HOG has no demonstrated visitor recall: BODY_POSITION is not
                # selectable until a validated detector enables this source.
                continue
            if kind in fresh:
                ordered.append(kind)
        if self._held_valid(now_s):
            ordered.append(SourceKind.HELD)
        ordered.append(SourceKind.NONE)
        return ordered

    def _held_valid(self, now_s: float) -> bool:
        if self._held is None or self._held_since is None:
            return False
        age = now_s - self._held_since
        # hold_s is the normal bridge; max_held_s is the absolute bound that
        # demotion grace must never exceed.
        return 0.0 <= age <= min(self.config.hold_s, self.config.max_held_s)

    def _emit(
        self,
        now_s: float,
        winner: SourceKind,
        pupil_ok: tuple[tuple[float, float], tuple[float, float]] | None,
        fresh: dict[SourceKind, Candidate],
        compat_eyes: tuple[tuple[float, float], tuple[float, float]] | None,
        demote_hold: tuple[float, float, float, float] | None = None,
    ) -> SelectorDecision:
        if demote_hold is not None:
            out = self._slew(demote_hold, now_s)
            return SelectorDecision(
                EyeState.HELD_TARGET, EyeState.HELD_TARGET,
                out[0], out[1], out[2], out[3],
                SourceKind.HELD, False, self._reason,
                max(0.0, now_s - self._active_since), self._held_age(now_s),
            )
        if winner == SourceKind.PUPIL_LEFT and pupil_ok is not None:
            lx, ly = pupil_ok[0]
            rx, ry = pupil_ok[1]
            self._capture_hold(now_s, winner, (lx, ly, rx, ry))
            out = self._slew((lx, ly, rx, ry), now_s)
            return SelectorDecision(
                EyeState.TRACKED_PUPIL, EyeState.TRACKED_PUPIL,
                out[0], out[1], out[2], out[3],
                SourceKind.PUPIL_LEFT, False, self._reason,
                max(0.0, now_s - self._active_since), self._held_age(now_s),
            )
        if winner in fresh:
            cand = fresh[winner]
            state = SOURCE_EYE_STATE[winner]
            self._capture_hold(now_s, winner, (cand.x, cand.y, cand.x, cand.y))
            out = self._slew((cand.x, cand.y, cand.x, cand.y), now_s)
            return SelectorDecision(
                state, state, out[0], out[1], out[2], out[3],
                winner, False, self._reason,
                now_s - self._tracks[winner].valid_since if self._tracks[winner].valid_since else 0.0,
                self._held_age(now_s),
            )
        if winner == SourceKind.HELD and self._held is not None:
            out = self._slew(self._held, now_s)
            return SelectorDecision(
                EyeState.HELD_TARGET, EyeState.HELD_TARGET,
                out[0], out[1], out[2], out[3],
                SourceKind.HELD, False, self._reason,
                max(0.0, now_s - self._active_since), self._held_age(now_s),
            )
        return SelectorDecision(
            EyeState.INVALID, EyeState.INVALID, 0.0, 0.0, 0.0, 0.0,
            SourceKind.NONE, False, self._reason or "no visitor signal",
            max(0.0, now_s - self._active_since), self._held_age(now_s),
        )

    def _capture_hold(self, now_s: float, winner: SourceKind, quad: tuple[float, float, float, float]) -> None:
        if winner in (SourceKind.HELD, SourceKind.NONE):
            return
        self._held = quad
        self._held_since = now_s
        self._held_from = winner

    def _held_age(self, now_s: float) -> float | None:
        if self._held_since is None:
            return None
        return now_s - self._held_since

    def _slew(self, quad: tuple[float, float, float, float], now_s: float) -> tuple[float, float, float, float]:
        # Slew-limit per elapsed second from config; first emit passes through.
        prev = self._last_emit
        if self._last_emit_at is None:
            self._last_emit = quad
            self._last_emit_at = now_s
            return quad
        dt = max(0.0, now_s - self._last_emit_at)
        self._last_emit_at = now_s
        if dt <= 0.0:
            return prev
        limit = self.config.slew_per_s * dt
        out: list[float] = []
        for index, value in enumerate(quad):
            delta = value - prev[index]
            if abs(delta) > limit:
                delta = math.copysign(limit, delta)
            out.append(prev[index] + delta)
        self._last_emit = (out[0], out[1], out[2], out[3])
        return self._last_emit
    def diagnostics(self, now_s: float | None = None) -> dict:
        now = time.monotonic() if now_s is None else now_s
        availability = {}
        for kind, track in self._tracks.items():
            availability[kind.name] = {
                "valid_since": track.valid_since,
                "invalid_since": track.invalid_since,
                "last": (track.last_x, track.last_y),
            }
        return {
            "active": self._active.name,
            "reason": self._reason,
            "active_age_s": max(0.0, now - self._active_since),
            "held_age_s": self._held_age(now),
            "held_from": self._held_from.name if self._held_from else None,
            "availability": availability,
            "emission_enabled": self.config.emission_enabled,
            "calibrated": self.config.calibrated,
            "config_checksum": self.config.checksum(),
        }


# ---------------------------------------------------------------------------
# Canonical 20-byte payload codec (accepted contract)
# ---------------------------------------------------------------------------

MAGIC = 0x4559
PAYLOAD_SCHEMA_VERSION = 1
MESSAGE_TYPE = 1
PAYLOAD_SIZE = 20
PAYLOAD_STRUCT = struct.Struct("!HBBIBBHhhhh")
WIRE_RANGE = 1000


def quantize(value: float, soft_limit: float) -> int:
    number = _as_float("coordinate", value)
    limit = _as_float("soft_limit", soft_limit)
    if limit <= 0.0:
        raise ValueError("soft_limit must be greater than zero")
    wire = max(-1.0, min(1.0, number / limit))
    scaled = wire * WIRE_RANGE
    if scaled >= 0:
        return int(math.floor(scaled + 0.5))
    return int(math.ceil(scaled - 0.5))


def encode_frame(
    sample_id: int,
    left_state: EyeState,
    right_state: EyeState,
    left_x: float,
    left_y: float,
    right_x: float,
    right_y: float,
    soft_limit: float = 1.5,
) -> bytes:
    sample = int(sample_id) % (1 << 32)
    for state in (left_state, right_state):
        if int(state) not in (0, 1, 2, 3, 4, 5):
            raise ValueError(f"unknown eye state {state}")
    if left_state == EyeState.INVALID and (left_x != 0.0 or left_y != 0.0):
        raise ValueError("INVALID left eye requires zero coordinates")
    if right_state == EyeState.INVALID and (right_x != 0.0 or right_y != 0.0):
        raise ValueError("INVALID right eye requires zero coordinates")
    packet = PAYLOAD_STRUCT.pack(
        MAGIC, PAYLOAD_SCHEMA_VERSION, MESSAGE_TYPE, sample,
        int(left_state), int(right_state), 0,
        quantize(left_x, soft_limit), quantize(left_y, soft_limit),
        quantize(right_x, soft_limit), quantize(right_y, soft_limit),
    )
    if len(packet) != PAYLOAD_SIZE:
        raise AssertionError("payload must be exactly 20 bytes")
    return packet


@dataclass(frozen=True)
class DecodedFrame:
    sample_id: int
    left_state: EyeState
    right_state: EyeState
    left_x: int
    left_y: int
    right_x: int
    right_y: int


def decode_frame(packet: bytes) -> DecodedFrame:
    if len(packet) != PAYLOAD_SIZE:
        raise ValueError(f"payload must be exactly {PAYLOAD_SIZE} bytes")
    magic, version, message_type, sample_id, left_state, right_state, reserved, lx, ly, rx, ry = PAYLOAD_STRUCT.unpack(packet)
    if magic != MAGIC:
        raise ValueError("bad magic")
    if version != PAYLOAD_SCHEMA_VERSION:
        raise ValueError("bad schema version")
    if message_type != MESSAGE_TYPE:
        raise ValueError("bad message type")
    if reserved != 0:
        raise ValueError("reserved field must be zero")
    try:
        left = EyeState(left_state)
        right = EyeState(right_state)
    except ValueError:
        raise ValueError("unknown eye state")
    for value in (lx, ly, rx, ry):
        if not -WIRE_RANGE <= value <= WIRE_RANGE:
            raise ValueError("coordinate out of range")
    if left == EyeState.INVALID and (lx != 0 or ly != 0):
        raise ValueError("INVALID left eye requires zero coordinates")
    if right == EyeState.INVALID and (rx != 0 or ry != 0):
        raise ValueError("INVALID right eye requires zero coordinates")
    return DecodedFrame(sample_id, left, right, lx, ly, rx, ry)

def config_path_default(root: Path) -> Path:
    return root / "fallback-config.json"


def load_config_file(path: Path) -> tuple[FallbackConfig, str | None, str]:
    """Load versioned config; any malformed file yields safe shadow defaults."""
    try:
        raw = path.read_bytes()
    except OSError:
        return DEFAULT_FALLBACK_CONFIG, "missing file; using shadow defaults", DEFAULT_FALLBACK_CONFIG.checksum()
    try:
        config = config_from_dict(json.loads(raw.decode("utf-8")))
    except (ValueError, TypeError, IndexError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return DEFAULT_FALLBACK_CONFIG, f"invalid config; using shadow defaults: {exc}", DEFAULT_FALLBACK_CONFIG.checksum()
    return config, None, config.checksum()
