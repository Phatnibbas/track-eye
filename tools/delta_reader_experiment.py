"""RAM-only experiment on a board already in REPL; no motor commands.

The 'recover' mode runs existing master definitions with AUTO_REHOME disabled
in RAM. It does not write firmware or survive reset. Requires explicit approval.
"""
import argparse
import json
import math

from delta_serial_probe import probe


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--device", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--mode", choices=("inspect", "text", "bytes", "recover"), required=True)
    p.add_argument("--confirmed-repl", action="store_true", required=True)
    p.add_argument("--reply-seconds", type=float, required=True)
    p.add_argument("--baud", type=int, required=True)
    p.add_argument("--max-line-bytes", type=int, required=True)
    p.add_argument("--reader-timeout-seconds", type=float)
    p.add_argument("--listen-seconds", type=float, required=True)
    p.add_argument("--clear-repl-input", action="store_true",
                   help="send Ctrl-C to discard incomplete input on the confirmed REPL")
    args = p.parse_args()
    if args.mode in ("text", "bytes") and (args.reader_timeout_seconds is None
            or not math.isfinite(args.reader_timeout_seconds) or args.reader_timeout_seconds <= 0):
        p.error("text/bytes experiment requires positive --reader-timeout-seconds")
    if args.mode == "inspect":
        commands = ("import sys, gc; gc.collect(); print('AUDIT_HEAP', gc.mem_free()); print('AUDIT_GLOBALS', 'main' in globals(), 'Master' in globals(), 'LineReader' in globals()); print('AUDIT_STDIN', type(sys.stdin), hasattr(sys.stdin, 'buffer')); print('AUDIT_POLICY', AUTO_REHOME, ENABLE_WDT)",)
    elif args.mode in ("text", "bytes"):
        stream = "sys.stdin" if args.mode == "text" else "sys.stdin.buffer"
        code = ("import sys, select, time\n"
                f"s={stream}\np=select.poll()\np.register(s, select.POLLIN)\n"
                "start=time.ticks_ms()\nprint('AUDIT_READER_READY')\n"
                f"while time.ticks_diff(time.ticks_ms(), start)<{int(args.reader_timeout_seconds * 1000)}:\n"
                " if p.poll(0):\n"
                "  try:\n   c=s.read(1)\n   print('AUDIT_BYTE', repr(c))\n"
                "   if c in ('\\n', b'\\n'): break\n"
                "  except Exception as e:\n   print('AUDIT_READER_ERROR', repr(e))\n"
                " time.sleep_ms(1)\nprint('AUDIT_READER_DONE')\n")
        commands = ("exec(" + repr(code) + ")", "status")
    else:
        # Source-confirmed entry point. Suppress autonomous rehome during audit.
        commands = ("AUTO_REHOME=False; print('AUDIT_RECOVER_AUTO_REHOME', AUTO_REHOME); main()",)
    if args.clear_repl_input:
        commands = ("\x03",) + commands
    result = probe(args.device, listen_s=args.listen_seconds, reply_s=args.reply_seconds,
                   commands=commands, restore_settings=False,
                   baud=args.baud, max_line_bytes=args.max_line_bytes)
    with open(args.out, "x", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    # Keep large byte transcripts in the artifact rather than console noise.
    print(json.dumps({k: v for k, v in result.items() if k != "events"}))
    for e in result["events"]:
        if "rx" in e or "rx_partial" in e:
            print(e)


if __name__ == "__main__":
    main()
