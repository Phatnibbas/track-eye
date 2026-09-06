"""Bench sender — drive the ESP32 eye servos with SYNTHETIC signals (no camera).

Use during bring-up (Stage 1/2) to verify wifi + UDP + mapping + servo direction
and limits before wiring the camera in. Runs the same EyeMapper as pupil_spike,
so what you see here is exactly how real tracking will map.

    python tools/servo_link_test.py --udp-host <esp-ip>              # smooth sweep
    python tools/servo_link_test.py --udp-host <esp-ip> --mode poses # discrete poses

'poses' mode walks through center / left / right / up / down holding each ~1.5s and
prints the intended direction — use it to confirm the eyes move the SAME way and to
fix PAN_SIGN / TILT_SIGN in servo_link.py if a direction is reversed.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from servo_link import EyeMapper, UdpServoLink  # noqa: E402

# (label, h, v):  h>0 toward corner-1 side, v>0 = looking DOWN (see measure_eye)
POSES = [
    ("center", 0.0, 0.0),
    ("LEFT ", -0.8, 0.0),
    ("center", 0.0, 0.0),
    ("RIGHT", 0.8, 0.0),
    ("center", 0.0, 0.0),
    ("UP   ", 0.0, -0.8),
    ("center", 0.0, 0.0),
    ("DOWN ", 0.0, 0.8),
    ("center", 0.0, 0.0),
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Synthetic servo-link sender (bring-up)")
    p.add_argument("--udp-host", required=True, help="ESP32 IP (printed on its boot)")
    p.add_argument("--udp-port", type=int, default=8770)
    p.add_argument("--mode", choices=["sweep", "poses"], default="sweep")
    p.add_argument("--rate", type=float, default=25.0, help="packets per second")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    left = EyeMapper()
    right = EyeMapper()
    link = UdpServoLink(args.udp_host, args.udp_port)
    dt = 1.0 / max(1.0, args.rate)
    print(f"[test] -> {args.udp_host}:{args.udp_port}  mode={args.mode}  (Ctrl+C to stop)")
    try:
        if args.mode == "poses":
            while True:
                for label, h, v in POSES:
                    lp, lt = left.map(h, v)
                    rp, rt = right.map(h, v)
                    print(f"  {label}  h={h:+.2f} v={v:+.2f} -> L({lp:3d},{lt:3d}) R({rp:3d},{rt:3d})")
                    for _ in range(max(1, int(1.5 / dt))):
                        link.send(lp, lt, rp, rt, "tracking")
                        time.sleep(dt)
        else:
            t = 0.0
            while True:
                h = 0.8 * math.sin(t)
                v = 0.8 * math.sin(t * 0.6)
                lp, lt = left.map(h, v)
                rp, rt = right.map(h, v)
                link.send(lp, lt, rp, rt, "tracking")
                t += 0.06
                time.sleep(dt)
    except KeyboardInterrupt:
        for _ in range(10):                       # settle to neutral before exit
            link.send(80, 60, 80, 60, "neutral")
            time.sleep(dt)
        print("\n[test] stopped (sent neutral)")
    finally:
        link.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
