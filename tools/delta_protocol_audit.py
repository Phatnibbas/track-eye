"""Non-motion USB protocol conformance/soak/reopen audit.

Sends only status and typed IK. Node diagnostics are recorded separately from
transport/parse correctness. No frame repair, auto reset/clear/home or retries.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from delta_bridge.config import exact_keys, load_monitor_config, positive
from delta_bridge.core import MasterState
from delta_bridge.ik_validation import FirmwareIKReference, compare_ik
from delta_bridge.serial_transport import ReadOnlySerial, SerialProtocolError


def load_campaign(path):
    campaign = json.loads(path.read_text(encoding="utf-8"))
    exact_keys(campaign, ("schema_version", "rate_hz", "queries_per_session", "sessions",
                         "reopen_pause_s", "sync_attempts", "seed", "tilt_min_deg",
                         "tilt_max_deg", "twist_deg", "ik_tolerance_deg"), "audit campaign")
    if type(campaign["schema_version"]) is not int or campaign["schema_version"] != 1:
        raise ValueError("unsupported campaign schema")
    for k in ("rate_hz", "reopen_pause_s", "tilt_max_deg", "ik_tolerance_deg"):
        positive(campaign[k], k)
    for k in ("queries_per_session", "sessions", "sync_attempts"):
        if type(campaign[k]) is not int or campaign[k] <= 0:
            raise ValueError(f"{k} must be a positive integer")
    for k in ("tilt_min_deg", "twist_deg"):
        if type(campaign[k]) not in (int, float) or not math.isfinite(campaign[k]):
            raise ValueError(f"{k} must be finite")
    if type(campaign["seed"]) is not int or not 0 <= campaign["tilt_min_deg"] <= campaign["tilt_max_deg"]:
        raise ValueError("invalid seed or tilt interval")
    return campaign


def vectors(campaign):
    rng = random.Random(campaign["seed"])
    count = campaign["queries_per_session"]
    # 0/90/180/270/360 are protocol-domain axis/boundary values, not rig offsets.
    axes = (0, 90, 180, 270, 360)
    result = []
    for i in range(count):
        if i < len(axes):
            az, tilt = axes[i], campaign["tilt_max_deg"]
        else:
            az = rng.uniform(0, 360)
            tilt = rng.uniform(campaign["tilt_min_deg"], campaign["tilt_max_deg"])
        result.append((az, tilt, campaign["twist_deg"]))
    return result


def drain_diagnostics(link, timeout_s, observer):
    """Finish chunked async diagnostics before TX, without repairing frames.

    USB read boundaries can split even a UTF-8 character. A partial diagnostic
    is not a wire error until its configured completion deadline expires.
    """
    end = time.monotonic() + timeout_s
    wait = 0.0
    while True:
        raw, lines = link.receive(wait)
        if raw:
            observer(raw, lines)
        if link.quarantined:
            raise SerialProtocolError("master boot/REPL/traceback before query")
        if any("IK az=" in line for line in lines):
            raise SerialProtocolError("unsolicited/stale IK reply before query")
        if link.lines.buffer:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("partial diagnostic did not terminate before deadline")
            wait = remaining
            continue
        if not raw:
            return
        if time.monotonic() >= end:
            raise TimeoutError("async diagnostics did not drain before deadline")
        wait = 0.0


def run(config, campaign, reference, out_path, summary_path):
    start = time.monotonic()
    latencies = []
    max_motor_error = 0.0
    diagnostic_counts = {}
    results = []
    verified = 0
    echoed = 0
    failures = []
    tx_vectors = vectors(campaign)
    with out_path.open("x", encoding="utf-8") as out:
        def log(**fields):
            out.write(json.dumps({"t_s": time.monotonic() - start, **fields},
                                 ensure_ascii=False, allow_nan=False) + "\n")
            out.flush()

        for session_no in range(campaign["sessions"]):
            link = ReadOnlySerial(config.serial)
            session = {"session": session_no, "queries_sent": 0, "verified": 0,
                       "error": None, "status_fault": None}
            def receive(timeout):
                raw, lines = link.receive(timeout)
                if raw:
                    log(session=session_no, rx_hex=raw.hex(), lines=lines)
                if link.quarantined:
                    raise SerialProtocolError("master boot/REPL/traceback: no protocol TX permitted")
                for line in lines:
                    if line.startswith(("FAULT", "EVT", "WARN", "ERR")):
                        key = line.split()[0]
                        diagnostic_counts[key] = diagnostic_counts.get(key, 0) + 1
                        log(session=session_no, robot_diagnostic=line)
                return lines

            def observe_drain(raw, lines):
                log(session=session_no, unsolicited_rx_hex=raw.hex(), lines=lines)
                for line in lines:
                    if line.startswith(("FAULT", "EVT", "WARN", "ERR")):
                        key = line.split()[0]
                        diagnostic_counts[key] = diagnostic_counts.get(key, 0) + 1
                        log(session=session_no, robot_diagnostic=line)

            try:
                link.open()
                log(session=session_no, opened=True, device=config.serial.device,
                    baud=config.serial.baud, motion_tx=False)
                end = time.monotonic() + config.serial.io_timeout_s
                while time.monotonic() < end:
                    receive(max(0, end - time.monotonic()))
                # Require an intact line boundary and complete response; FAULT or
                # unhomed nodes do not prohibit a calculation-only conformance run.
                synced = False
                for sync_no in range(campaign["sync_attempts"]):
                    state = MasterState(config.expected_nodes, config.snapshot_window_s)
                    link.send_query("status")
                    log(session=session_no, sync_attempt=sync_no, tx="status")
                    end = time.monotonic() + config.serial.io_timeout_s
                    while time.monotonic() < end:
                        lines = receive(max(0, end - time.monotonic()))
                        for line in lines:
                            state.consume(line, time.monotonic())
                            if line.startswith("STAT fault="):
                                session["status_fault"] = line
                        if state.snapshot_at is not None:
                            synced = True
                            break
                    if synced:
                        break
                if not synced or link.lines.buffer:
                    raise SerialProtocolError("no intact status snapshot before IK audit")

                next_tx = time.monotonic()
                for query_no, polar in enumerate(tx_vectors):
                    time.sleep(max(0, next_tx - time.monotonic()))
                    # Drain pending async diagnostics before TX. Never reinterpret
                    # stale IK responses as the reply to the next query.
                    drain_diagnostics(link, config.serial.io_timeout_s, observe_drain)
                    sent_at = time.monotonic()
                    link.send_ik(*polar)
                    session["queries_sent"] += 1
                    log(session=session_no, sample_id=query_no, polar=polar,
                        tx=f"ik {polar[0]:.3f} {polar[1]:.3f} {polar[2]:.3f}", motion_tx=False)
                    end = sent_at + config.serial.io_timeout_s
                    match = None
                    while time.monotonic() < end:
                        for line in receive(max(0, end - time.monotonic())):
                            if line.startswith("ERR"):
                                raise SerialProtocolError(f"command rejection: {line}")
                            if line.startswith("IK "):
                                if match is not None:
                                    raise SerialProtocolError("duplicate IK reply")
                                match = compare_ik(polar, line, reference, config.expected_nodes,
                                                   campaign["ik_tolerance_deg"])
                            elif "IK az=" in line:
                                raise SerialProtocolError("IK reply merged into another diagnostic")
                        if match is not None:
                            break
                    if match is None:
                        raise TimeoutError("no matching standalone IK reply before deadline")
                    latency_ms = (time.monotonic() - sent_at) * 1000
                    latencies.append(latency_ms)
                    error = max(match["errors_deg"].values())
                    max_motor_error = max(max_motor_error, error)
                    session["verified"] += 1
                    verified += 1
                    echoed += 1
                    log(session=session_no, sample_id=query_no, response_latency_ms=latency_ms,
                        **match, motion_tx=False)
                    # Skip missed slots; no command backlog or catch-up burst.
                    next_tx = max(next_tx + 1 / campaign["rate_hz"], time.monotonic())
            except (OSError, ValueError, RuntimeError) as exc:
                session["error"] = str(exc)
                failures.append({"session": session_no, "error": str(exc)})
                log(session=session_no, error=str(exc), last_rx_hex=link.last_rx.hex(), motion_tx=False)
            finally:
                link.close()
                log(session=session_no, closed=True, motion_tx=False)
                results.append(session)
            if session["error"] is not None:
                break  # No same-error reconnect loop.
            if session_no + 1 < campaign["sessions"]:
                time.sleep(campaign["reopen_pause_s"])

    ordered = sorted(latencies)
    summary = {"duration_s": time.monotonic() - start, "campaign": campaign,
               "sessions": results, "verified_replies": verified,
               "exact_echo_and_node_set_matches": echoed,
               "max_reference_error_deg": max_motor_error if verified else None,
               "response_latency_ms": {"median": statistics.median(ordered),
                                       "p95_nearest_rank": ordered[math.ceil(.95 * len(ordered)) - 1],
                                       "max": ordered[-1]} if ordered else None,
               "robot_diagnostic_counts": diagnostic_counts,
               "protocol_failures": failures, "motion_tx": False,
               "limitation": "IK parsing/computation only; no USB transaction ID, no motor ACK/physical accuracy proof"}
    with summary_path.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, ensure_ascii=False, allow_nan=False)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--campaign", type=Path, required=True)
    p.add_argument("--reference-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--summary", type=Path, required=True)
    a = p.parse_args()
    reference = FirmwareIKReference(a.reference_dir / "spm_ik.py", a.reference_dir / "main.py",
                                    a.reference_dir / "neutral.txt")
    summary = run(load_monitor_config(a.config), load_campaign(a.campaign), reference, a.out, a.summary)
    print(json.dumps(summary, ensure_ascii=False))
    return int(bool(summary["protocol_failures"]))


if __name__ == "__main__":
    raise SystemExit(main())
