"""Live calibrated pupil → typed USB IK → echoed angles + reference comparison.

No look/home/clear or motor command. Does not promote shadow fallback.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from delta_bridge.config import load_config
from delta_bridge.core import production_target, finite_number, MasterState
from delta_bridge.ik_validation import FirmwareIKReference, compare_ik
from delta_bridge.serial_transport import ReadOnlySerial, SerialProtocolError


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--seconds", type=float, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--reference-dir", type=Path, required=True)
    p.add_argument("--tolerance-deg", type=float, required=True)
    p.add_argument("--status-sync-attempts", type=int, required=True,
                   help="bounded status exchanges before IK; never repair merged lines")
    a = p.parse_args()
    if not finite_number(a.seconds) or a.seconds <= 0 or not finite_number(a.tolerance_deg) or a.tolerance_deg <= 0 or a.status_sync_attempts <= 0:
        p.error("finite positive duration/tolerance required")
    cfg = load_config(a.config)
    reference = FirmwareIKReference(a.reference_dir / "spm_ik.py", a.reference_dir / "main.py", a.reference_dir / "neutral.txt")
    link = ReadOnlySerial(cfg.serial)
    state = MasterState(cfg.expected_nodes, cfg.snapshot_window_s)
    start = time.monotonic()
    samples = queries = matches = 0
    previous = None
    failed = None
    with a.out.open("x", encoding="utf-8") as out:
        def log(**data):
            out.write(json.dumps({"t_s": time.monotonic() - start, **data}, ensure_ascii=False, allow_nan=False) + "\n")
            out.flush()
        try:
            link.open()
            until = time.monotonic() + cfg.serial.io_timeout_s
            while time.monotonic() < until:
                raw, lines = link.receive(max(0, until - time.monotonic()))
                if raw:
                    log(rx_hex=raw.hex(), lines=lines)
                if link.quarantined:
                    raise SerialProtocolError("master is not running protocol")
                for line in lines:
                    state.consume(line, time.monotonic())
            for _ in range(a.status_sync_attempts):
                state.reset()
                link.send_query("status")
                log(tx="status", motion_tx=False)
                deadline = time.monotonic() + cfg.serial.io_timeout_s
                while time.monotonic() < deadline:
                    raw, lines = link.receive(max(0, deadline - time.monotonic()))
                    if raw:
                        log(rx_hex=raw.hex(), lines=lines)
                    if link.quarantined:
                        raise SerialProtocolError("master boot/REPL/traceback during status sync")
                    for line in lines:
                        state.consume(line, time.monotonic())
                    if state.snapshot_at is not None:
                        break
                if state.snapshot_at is not None:
                    log(status_snapshot_complete=True,
                        motion_ready=state.ready(time.monotonic(), cfg.status_max_age_s),
                        reason=state.reason, motion_tx=False)
                    break
            if state.snapshot_at is None or link.lines.buffer:
                raise SerialProtocolError("no complete standalone status snapshot/line boundary")
            # IK is computation-only and can run during FAULT; readiness is logged
            # explicitly and must not be promoted to hardware movement approval.
            next_query = time.monotonic()
            while time.monotonic() - start < a.seconds:
                with urllib.request.urlopen(cfg.status_url, timeout=cfg.serial.io_timeout_s) as response:
                    status = json.load(response)
                samples += 1
                target = production_target(status, cfg.mapping, cfg.frame_max_age_s)
                seq = status.get("frame_sequence") if isinstance(status, dict) else None
                fresh = type(seq) is int and seq > 0 and (previous is None or seq > previous)
                previous = seq
                if target is None or not fresh:
                    log(sequence=seq, skipped="no fresh usable production eye", motion_tx=False)
                else:
                    polar = cfg.mapping.polar(*target)
                    link.send_ik(*polar)
                    queries += 1
                    log(sequence=seq, eye=status["output_" + cfg.mapping.slot],
                        soft_limit=status["output_tuning"]["calibration"]["gain"]["soft_limit"],
                        normalized=target, tx=f"ik {polar[0]:.3f} {polar[1]:.3f} {polar[2]:.3f}", motion_tx=False)
                    deadline = time.monotonic() + cfg.serial.io_timeout_s
                    matched = False
                    while time.monotonic() < deadline:
                        raw, lines = link.receive(max(0, deadline - time.monotonic()))
                        if raw:
                            log(rx_hex=raw.hex(), lines=lines)
                        if link.quarantined:
                            raise SerialProtocolError("master boot/REPL/traceback")
                        for line in lines:
                            if line.startswith(("ERR", "FAULT")) or (line.startswith("EVT") and "BOOT" in line):
                                raise SerialProtocolError(line)
                            if line.startswith("IK "):
                                evidence = compare_ik(polar, line, reference, cfg.expected_nodes, a.tolerance_deg)
                                matches += 1
                                matched = True
                                log(**evidence, motion_tx=False)
                        if matched:
                            break
                    if not matched:
                        raise TimeoutError("no verified IK response before deadline")
                next_query += 1 / cfg.poll_hz
                if next_query < time.monotonic():
                    next_query = time.monotonic()
                time.sleep(max(0, next_query - time.monotonic()))
        except (OSError, ValueError, RuntimeError) as exc:
            failed = str(exc)
            log(error=failed, last_rx_hex=link.last_rx.hex(), motion_tx=False)
        finally:
            link.close()
    summary = {"samples": samples, "ik_queries": queries, "verified_replies": matches,
               "error": failed, "motion_tx": False, "slot": cfg.mapping.slot}
    print(json.dumps(summary))
    return int(failed is not None or matches == 0)


if __name__ == "__main__":
    raise SystemExit(main())
