"""Observe existing Pi HTTP output and log proposed Delta commands; NO serial TX."""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from delta_bridge.core import production_target, finite_number
from delta_bridge.config import load_config


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--seconds", type=float, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if not finite_number(args.seconds) or args.seconds <= 0:
        p.error("seconds must be finite and positive")
    config = load_config(args.config)
    mapping = config.mapping
    end = time.monotonic() + args.seconds
    previous = None
    count = usable = errors = 0
    with args.out.open("x", encoding="utf-8") as out:
        while time.monotonic() < end:
            started = time.monotonic()
            row = {"serial_tx": False, "slot": mapping.slot}
            try:
                with urllib.request.urlopen(config.status_url, timeout=config.serial.io_timeout_s) as response:
                    status = json.load(response)
                if not isinstance(status, dict):
                    raise ValueError("status is not an object")
                sequence = status.get("frame_sequence")
                target = production_target(status, mapping, config.frame_max_age_s)
                fresh = type(sequence) is int and sequence > 0 and (previous is None or sequence > previous)
                previous = sequence
                row.update(sequence=sequence, fps=status.get("fps"), face=status.get("face_detected"),
                           healthy=status.get("healthy"), target=target,
                           command=mapping.command(*target).strip() if target is not None and fresh else None)
                usable += int(row["command"] is not None)
            except (OSError, ValueError, TypeError) as exc:
                errors += 1
                row["error"] = str(exc)
            count += 1
            out.write(json.dumps(row, allow_nan=False) + "\n")
            time.sleep(max(0, 1 / config.poll_hz - (time.monotonic() - started)))
    print(json.dumps({"samples": count, "proposed_commands": usable, "errors": errors,
                      "serial_tx": False, "out": str(args.out)}))


if __name__ == "__main__":
    main()
