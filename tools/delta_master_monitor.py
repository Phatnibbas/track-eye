"""Bounded read-only Delta monitor; no reconnect loop or motor commands.

Configuration must be explicit. Writes raw RX hex and timing to an audit log.
Readiness only describes parsed status, not rig safety or motion approval.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from delta_bridge.config import load_monitor_config
from delta_bridge.core import MasterState, finite_number
from delta_bridge.serial_transport import ReadOnlySerial, SerialProtocolError


def monitor(config, seconds: float, out: Path) -> dict:
    transport = ReadOnlySerial(config.serial)
    state = MasterState(config.expected_nodes, config.snapshot_window_s)
    started = time.monotonic()
    queries = replies = 0
    failed = None
    with out.open("x", encoding="utf-8") as stream:
        def record(**fields):
            stream.write(json.dumps({"t_s": time.monotonic() - started, **fields}, ensure_ascii=False) + "\n")
            stream.flush()
        try:
            transport.open()
            record(open=True, device=config.serial.device, baud=config.serial.baud, motion_tx=False)
            # Listen before queries; do not blindly send a Delta command to REPL.
            next_query = time.monotonic() + config.serial.io_timeout_s
            while time.monotonic() - started < seconds:
                remaining = seconds - (time.monotonic() - started)
                until_query = max(0, next_query - time.monotonic())
                raw, lines = transport.receive(min(config.serial.io_timeout_s, max(0, remaining), until_query))
                if raw:
                    record(rx_hex=raw.hex(), lines=lines)
                now = time.monotonic()
                for line in lines:
                    state.consume(line, now)
                    replies += int(line.startswith("STAT fault="))
                if transport.quarantined:
                    raise SerialProtocolError("master boot/REPL/traceback requires explicit recovery")
                if now - started < seconds and now >= next_query:
                    transport.send_query("status")
                    record(tx="status", status_ready=state.ready(now, config.status_max_age_s), reason=state.reason)
                    queries += 1
                    # Skip missed periods; never catch up by sending a burst.
                    next_query = now + 1 / config.poll_hz
        except (OSError, ValueError, RuntimeError) as exc:
            state.reset()
            failed = str(exc)
            record(error=failed, last_rx_hex=transport.last_rx.hex(), status_ready=False)
        finally:
            transport.close()
            record(closed=True, motion_tx=False)
    return {"queries": queries, "status_headers": replies, "error": failed,
            "motion_tx": False, "seconds": time.monotonic() - started}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--seconds", type=float, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if not finite_number(args.seconds) or args.seconds <= 0:
        p.error("positive finite duration required")
    result = monitor(load_monitor_config(args.config), args.seconds, args.out)
    print(json.dumps(result))
    return int(result["error"] is not None)


if __name__ == "__main__":
    raise SystemExit(main())
