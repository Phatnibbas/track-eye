"""One-shot approved neutral move, guarded by live node readiness and config.

Not continuous tracking. No home/calib/automatic retry or firmware writes.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import signal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from delta_bridge.bench import BenchSession
from delta_bridge.config import load_monitor_config
from delta_bridge.ik_validation import FirmwareIKReference


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--reference-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--operator-approved", action="store_true", required=True)
    p.add_argument("--duration-ms", type=int, required=True)
    p.add_argument("--completion-timeout-s", type=float, required=True)
    p.add_argument("--status-attempts", type=int, required=True)
    p.add_argument("--completion-tolerance-deg", type=float, required=True)
    p.add_argument("--ik-tolerance-deg", type=float, required=True)
    a = p.parse_args()
    cfg = load_monitor_config(a.config)
    root = a.reference_dir
    ref = FirmwareIKReference(root / "spm_ik.py", root / "main.py", root / "neutral.txt")
    started = time.monotonic()
    result = None
    error = None
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    with a.out.open("x", encoding="utf-8") as out:
        def log(**data):
            out.write(json.dumps({"t_s": time.monotonic() - started, **data}, ensure_ascii=False, allow_nan=False) + "\n")
            out.flush()
        session = BenchSession(cfg, log, a.status_attempts, a.completion_tolerance_deg)
        try:
            session.link.open()
            session.listen()
            result = session.neutral(ref, a.duration_ms, a.completion_timeout_s, a.ik_tolerance_deg)
        except (OSError, ValueError, RuntimeError) as exc:
            error = str(exc)
            log(error=error)
            session.abort()
        except KeyboardInterrupt:
            error = "operator/process interrupted; stop attempted"
            log(error=error)
            session.abort()
        finally:
            session.link.close()
    print(json.dumps({"error": error, "result": result, "clear_count": session.clear_count,
                      "move_attempted": session.move_attempted}))
    return int(error is not None)


if __name__ == "__main__":
    raise SystemExit(main())
