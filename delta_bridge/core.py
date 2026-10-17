"""Pure mapping and fail-closed master state for the Delta text protocol."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Mapping:
    slot: str  # Explicit display slot, never silently fuse binocular targets.
    max_tilt_deg: float
    az_offset_deg: float
    x_sign: int
    y_sign: int
    twist_deg: float
    duration_ms: int

    def __post_init__(self):
        if self.slot not in ("left", "right"):
            raise ValueError("choose one explicit display slot")
        if not finite_number(self.max_tilt_deg) or self.max_tilt_deg <= 0:
            raise ValueError("tilt scale must be finite and positive; rig limits require separate evidence")
        if not finite_number(self.az_offset_deg) or not finite_number(self.twist_deg):
            raise ValueError("azimuth offset and twist must be finite")
        if type(self.x_sign) is not int or type(self.y_sign) is not int or self.x_sign not in (-1, 1) or self.y_sign not in (-1, 1):
            raise ValueError("axis signs must be integer +/-1")
        # MOVE_FMT uses uint16 milliseconds. This is a protocol bound, not rig tuning.
        if type(self.duration_ms) is not int or not 1 <= self.duration_ms <= 65535:
            raise ValueError("duration must be integer 1..65535 ms")

    def polar(self, x: float, y: float) -> tuple[float, float, float]:
        if not all(finite_number(v) and -1 <= v <= 1 for v in (x, y)):
            raise ValueError("normalized target must be finite in [-1,1]")
        xx, yy = self.x_sign * x, self.y_sign * y
        radius = math.hypot(xx, yy)
        az = 0.0 if radius == 0 else (math.degrees(math.atan2(yy, xx)) + self.az_offset_deg) % 360
        tilt = min(1.0, radius) * self.max_tilt_deg
        return az, tilt, self.twist_deg

    def command(self, x: float, y: float) -> str:
        az, tilt, twist = self.polar(x, y)
        return f"look {az:.3f} {tilt:.3f} {twist:.3f} {self.duration_ms}\n"


def finite_number(value) -> bool:
    try:
        return type(value) in (float, int) and math.isfinite(value)
    except OverflowError:
        return False


def production_target(status: dict, mapping: Mapping, max_age_s: float):
    """Read calibrated production output only; never promote shadow fallback.

    Frame age is server-reported. A future sender must also bound local receive
    age and stop on HTTP failure; this alone is not an actuator safety gate.
    """
    if not finite_number(max_age_s) or max_age_s <= 0:
        raise ValueError("max frame age must be configured, finite and positive")
    if not isinstance(status, dict) or status.get("healthy") is not True or status.get("capture_alive") is not True:
        return None
    age = status.get("last_frame_age_seconds")
    if not finite_number(age) or not 0 <= age <= max_age_s:
        return None
    if status.get("face_detected") is not True:
        return None
    baseline = status.get("baseline")
    if not isinstance(baseline, dict) or baseline.get("state") != "idle":
        return None
    eye = status.get("output_" + mapping.slot)
    tuning = status.get("output_tuning")
    calibration = tuning.get("calibration") if isinstance(tuning, dict) else None
    gain = calibration.get("gain") if isinstance(calibration, dict) else None
    soft = gain.get("soft_limit") if isinstance(gain, dict) else None
    if not isinstance(eye, dict) or not finite_number(soft) or soft <= 0:
        return None
    values = [eye.get("x"), eye.get("y")]
    if any(not finite_number(v) for v in values):
        return None
    return tuple(max(-1.0, min(1.0, v / soft)) for v in values)


NODE_RE = re.compile(r"^STAT n(\d+) (ON|OFF)\s+(DISABLED|IDLE|HOMING|MOVING|ERROR|-)\s+err=(\w+)\s+homed=([01])\s+sw=([01])\s+pos=\s*(-?\d+(?:\.\d+)?)\s+target=\s*(-?\d+(?:\.\d+)?)$")


class MasterState:
    """Session-local evidence, invalidated by fault, reboot, REPL or bad status.

    Intended future TX gate only. Does not send clear/home/move or infer readiness
    from OK MOVE; require a full fresh status snapshot after every reconnect.
    """

    def __init__(self, expected_nodes: tuple[int, ...], snapshot_window_s: float):
        if (not expected_nodes or any(type(n) is not int or n <= 0 for n in expected_nodes)
                or len(set(expected_nodes)) != len(expected_nodes)):
            raise ValueError("explicit unique positive node IDs required")
        if not finite_number(snapshot_window_s) or snapshot_window_s <= 0:
            raise ValueError("snapshot window must be configured, finite and positive")
        self.expected_nodes = frozenset(expected_nodes)
        self.snapshot_window_s = snapshot_window_s
        self.reset()

    def reset(self):
        self.blocked = True
        self.nodes = {}
        self.snapshot_at = None
        self.header_at = None
        self.reason = "no verified status snapshot"

    def consume(self, line: str, now: float):
        if not finite_number(now) or now < 0:
            self.reset()
            return
        line = line.strip()
        if any(s in line for s in ("Traceback", ">>>", "MicroPython", "UnicodeError")) or line.startswith(("FAULT", "ERR", "WARN STOP")) or (line.startswith("EVT") and ("BOOT" in line or "OFFLINE" in line)):
            self.reset()
            self.reason = line[:200]
            return
        if line.startswith("STAT fault="):
            self.reset()
            self.header_at = now
            self.blocked = not bool(re.match(r"^STAT fault=False queue=0 inflight=-$", line))
            self.reason = "status incomplete" if not self.blocked else "master fault/busy queue"
            return
        if line.startswith("STAT n"):
            match = NODE_RE.fullmatch(line)
            if match is None or self.header_at is None or not 0 <= now - self.header_at <= self.snapshot_window_s:
                self.reset()
                self.reason = "malformed or incomplete status"
                return
            nid, online, state, err, homed, _sw, _pos, _target = match.groups()
            if int(nid) not in self.expected_nodes or int(nid) in self.nodes:
                self.reset()
                self.reason = "unknown or duplicate node in snapshot"
                return
            self.nodes[int(nid)] = online == "ON" and state in ("IDLE", "MOVING") and err == "NONE" and homed == "1"
            if self.nodes.keys() == self.expected_nodes:
                self.snapshot_at = now
                self.reason = "verified ready" if not self.blocked and all(self.nodes.values()) else "node not ready"

    def ready(self, now: float, max_age_s: float):
        if not finite_number(now) or not finite_number(max_age_s) or max_age_s <= 0:
            return False
        return (not self.blocked and self.snapshot_at is not None
                and 0 <= now - self.snapshot_at <= max_age_s
                and self.nodes.keys() == self.expected_nodes and all(self.nodes.values()))
