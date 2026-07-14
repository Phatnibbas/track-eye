"""UDP servo link (Pi side) for the per-eye pupil demo.

Maps each eye's head-normalized pupil signal (h, v in ~[-1, 1]) to servo angles
and sends them to the ESP32-S3 over WiFi UDP. Stdlib only (socket) — no extra
pip dependency. If the demo is launched without --udp-host, this module is not
used and pupil_spike behaves exactly as before.

Mapping / dead-zone / response-curve logic is carried over from the project's
earlier servo_mapper.py (recovered from git history). Slew-limiting and the
watchdog live on the ESP32 firmware; here we only do the static map + send.

Packet format (one datagram per frame):
    EYES,<Lpan>,<Ltilt>,<Rpan>,<Rtilt>,<gate>\n
    e.g.  EYES,96,74,88,70,tracking
gate in {tracking, hold, neutral}.
"""

from __future__ import annotations

import math
import socket


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def shape(x: float, deadband: float, exp: float) -> float:
    """Dead-zone around 0, then a response curve.

    exp < 1 makes small pupil movements more visible; the sign is preserved.
    Returns 0 inside the dead-band, else copysign(scaled**exp, x) in [-1, 1].
    """
    ax = abs(x)
    if ax <= deadband:
        return 0.0
    s = (ax - deadband) / (1.0 - deadband)
    return math.copysign(s ** exp, x)


class EyeMapper:
    """Map one eye's (h, v) normalized signal to integer (pan, tilt) angles.

    Defaults match the ranges measured on the current rig:
        pan  center 80, range 40..140
        tilt center 60, range 20..110   (up=110, down=20)
    pan_sign / tilt_sign (+/-1) set the movement direction; they are confirmed
    empirically during bring-up (the camera frame is mirror-flipped, so the sign
    cannot be assumed up front).

    Direction gains are DECOUPLED (base 45 deg per unit shape = "x1"):
        pan_gain       = 67.5  -> horizontal   x1.5
        tilt_up_gain   = 67.5  -> looking up   x1.5
        tilt_down_gain = 135.0 -> looking down x3  (under-read by MediaPipe, needs more)
    out_alpha low-passes the output angles to smooth servo motion (less jerk).
    """

    def __init__(
        self,
        pan_center: float = 80.0, pan_min: float = 40.0, pan_max: float = 140.0,
        pan_gain: float = 67.5, pan_sign: float = 1.0,
        tilt_center: float = 60.0, tilt_min: float = 20.0, tilt_max: float = 110.0,
        tilt_up_gain: float = 67.5, tilt_down_gain: float = 135.0, tilt_sign: float = -1.0,
        deadband_h: float = 0.03, deadband_v: float = 0.04,
        exp_h: float = 0.75, exp_v: float = 0.70,
        out_alpha: float = 0.5,
    ):
        self.pan_center, self.pan_min, self.pan_max = pan_center, pan_min, pan_max
        self.pan_gain, self.pan_sign = pan_gain, pan_sign
        self.tilt_center, self.tilt_min, self.tilt_max = tilt_center, tilt_min, tilt_max
        self.tilt_up_gain, self.tilt_down_gain = tilt_up_gain, tilt_down_gain
        self.tilt_sign = tilt_sign
        self.deadband_h, self.deadband_v = deadband_h, deadband_v
        self.exp_h, self.exp_v = exp_h, exp_v
        self.out_alpha = out_alpha
        self._pan = None
        self._tilt = None

    def map(self, h: float, v: float) -> tuple[int, int]:
        ph = shape(h, self.deadband_h, self.exp_h)
        pv = shape(v, self.deadband_v, self.exp_v)
        tilt_dir = self.tilt_sign * pv                    # >0 = up, <0 = down
        gain = self.tilt_up_gain if tilt_dir >= 0.0 else self.tilt_down_gain
        pan = clamp(self.pan_center + self.pan_sign * ph * self.pan_gain,
                    self.pan_min, self.pan_max)
        tilt = clamp(self.tilt_center + tilt_dir * gain, self.tilt_min, self.tilt_max)
        # output low-pass -> smoother servo motion (less jerk)
        if self._pan is None:
            self._pan, self._tilt = pan, tilt
        else:
            self._pan += self.out_alpha * (pan - self._pan)
            self._tilt += self.out_alpha * (tilt - self._tilt)
        return int(round(self._pan)), int(round(self._tilt))


class UdpServoLink:
    """Fire-and-forget UDP sender to the ESP32 eye-follower firmware."""

    def __init__(self, host: str, port: int = 8770):
        self.addr = (host, int(port))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        # allow subnet-broadcast targets (zero-config fallback: x.x.x.255)
        if host.endswith(".255") or host == "255.255.255.255":
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._warned = False

    def send(self, l_pan: int, l_tilt: int, r_pan: int, r_tilt: int, gate: str) -> None:
        msg = "EYES,{},{},{},{},{}\n".format(
            int(l_pan), int(l_tilt), int(r_pan), int(r_tilt), gate)
        try:
            self.sock.sendto(msg.encode("ascii"), self.addr)
        except OSError as exc:  # network hiccup must never crash the demo
            if not self._warned:
                print(f"[servo_link] UDP send error (further errors suppressed): {exc}")
                self._warned = True

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass
